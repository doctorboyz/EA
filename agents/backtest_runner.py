"""
BacktestRunnerAgent (Agent 2) — Runs MT5 Strategy Tester via Wine on macOS.

Workflow:
  1. Write tester.ini config to MT5 config path
  2. Copy .mq5 file to MT5 Experts folder (wine shares macOS filesystem)
  3. Launch MT5 terminal64.exe via subprocess (wine)
  4. Poll reports_path for a new HTML report (with timeout)
  5. Return path to the HTML report for ReportParserAgent

Note: MetaTrader5 pip package does NOT work under Wine.
      We use subprocess + file system polling instead.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


def _load_mt5_config() -> dict:
    cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
    with open(cfg_path) as f:
        return yaml.safe_load(f)


@dataclass
class BacktestSpec:
    """Parameters for a single backtest run."""
    mq5_file_path: str           # Absolute path to generated .mq5 file
    symbol: str = "EURUSD"
    timeframe: str = "H1"
    date_from: date = None
    date_to: date = None
    initial_deposit: float = 1000.0
    leverage: int = 100
    model: int = 1               # 0=OHLC, 1=1-min bars, 2=real ticks
    broker_server: str = "Exness-MT5Trial7"  # MT5 broker server name

    def __post_init__(self):
        if self.date_from is None:
            self.date_from = date(2025, 1, 1)
        if self.date_to is None:
            self.date_to = date(2026, 3, 12)


@dataclass
class BacktestRunResult:
    """Outcome of a backtest run."""
    report_html_path: str
    spec: BacktestSpec
    run_at: datetime
    duration_seconds: float


# ---------------------------------------------------------------------------
# MT5 timeframe map (MT5 tester.ini format)
# ---------------------------------------------------------------------------

TIMEFRAME_MAP = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408,
}


class BacktestRunnerAgent:
    """
    Agent 2: Runs MT5 Strategy Tester via Wine subprocess on macOS.

    Designed for Whisky app (Wine wrapper) where MT5 is installed.
    The macOS filesystem is directly accessible from Wine, so we can:
    - Write files directly to Wine paths
    - Read report HTML files without any translation
    """

    def __init__(self, config: Optional[dict] = None, ollama=None) -> None:
        cfg = config or _load_mt5_config()
        mt5 = cfg.get('mt5', {})
        proj = cfg.get('project', {})

        # CompileErrorAgent: auto-fix MQL5 syntax errors on compile failure
        self._compile_fixer = None
        if ollama is not None:
            try:
                from agents.compile_error_agent import CompileErrorAgent
                self._compile_fixer = CompileErrorAgent(ollama=ollama)
                logger.info("BacktestRunner: CompileErrorAgent ready (auto-fix enabled)")
            except Exception as exc:
                logger.warning("BacktestRunner: CompileErrorAgent init failed: %s", exc)

        self.mode: str = mt5.get('mode', 'wine')
        self.experts_path: str = mt5.get('experts_path', '')
        self.reports_path: str = mt5.get('reports_path', '')
        self.mt5_exe: str = mt5.get('mt5_exe', '')
        self.wine_bin: str = mt5.get('wine_bin', 'wine')
        self.broker_server: str = mt5.get('broker_server', 'Exness-MT5Trial7')
        self.backtest_timeout: int = mt5.get('backtest_timeout_seconds', 600)
        self.poll_interval: int = mt5.get('report_poll_interval_seconds', 5)
        self.report_wait_timeout: int = mt5.get('report_wait_timeout_seconds', 300)

        # Default backtest settings from project config
        self.default_symbol: str = proj.get('symbol', 'EURUSD')
        self.default_capital: float = proj.get('initial_capital', 1000.0)

    # ------------------------------------------------------------------
    # Main interface
    # ------------------------------------------------------------------

    def run(self, spec: BacktestSpec) -> BacktestRunResult:
        """
        Run a single backtest and return the path to the HTML report.

        Raises:
            FileNotFoundError: if the .mq5 file doesn't exist
            TimeoutError: if the report doesn't appear within timeout
            RuntimeError: if MT5 process fails to start
        """
        if not os.path.exists(spec.mq5_file_path):
            raise FileNotFoundError(f"MQ5 file not found: {spec.mq5_file_path}")

        # Log backtest configuration for debugging
        logger.info("[Backtest Config] %s %s | Period: %s → %s | Capital: $%.0f | Broker: %s",
                   spec.symbol, spec.timeframe, spec.date_from, spec.date_to,
                   spec.initial_deposit, spec.broker_server)

        start_time = time.time()

        # Step 1: Copy .mq5 to MT5 experts folder
        ea_name = self._copy_ea_to_experts(spec.mq5_file_path)
        logger.info("Copied EA to experts: %s", ea_name)

        # Step 1b: Compile .mq5 → .ex5 (required for MT5 Strategy Tester)
        self._compile_ea(ea_name)

        # Step 2: Write tester.ini
        ini_path = self._write_tester_ini(spec, ea_name)
        logger.info("Wrote tester.ini: %s", ini_path)

        # Step 3: Record files already in reports_path before launch
        existing_reports = self._snapshot_reports()

        # Step 4: Launch MT5 tester
        self._launch_mt5(ini_path)
        logger.info("MT5 launched, waiting for report...")

        # Step 5: Poll for new report
        report_path = self._wait_for_report(existing_reports)

        duration = time.time() - start_time
        logger.info("Backtest completed in %.1fs → %s", duration, report_path)

        return BacktestRunResult(
            report_html_path=report_path,
            spec=spec,
            run_at=datetime.utcnow(),
            duration_seconds=duration,
        )

    # ------------------------------------------------------------------
    # Step 1: Copy EA to MT5 experts folder
    # ------------------------------------------------------------------

    def _copy_ea_to_experts(self, mq5_path: str) -> str:
        """Copy .mq5 to MT5 Experts/Aureus/ folder. Returns base name."""
        if not self.experts_path:
            raise RuntimeError("mt5.experts_path not configured in system.yaml")

        os.makedirs(self.experts_path, exist_ok=True)
        filename = os.path.basename(mq5_path)
        dest = os.path.join(self.experts_path, filename)
        shutil.copy2(mq5_path, dest)
        return os.path.splitext(filename)[0]  # Return name without extension

    # ------------------------------------------------------------------
    # Step 1b: Compile .mq5 → .ex5
    # ------------------------------------------------------------------

    def _compile_ea(self, ea_name: str) -> None:
        """
        Compile the .mq5 file to .ex5 using terminal64.exe /compile.
        MT5 Strategy Tester requires compiled .ex5 — it cannot run .mq5 source.

        On compile failure, calls CompileErrorAgent to auto-fix syntax errors
        and retries up to MAX_COMPILE_RETRIES times.
        """
        if not self.experts_path or not self.mt5_exe:
            raise RuntimeError("mt5.experts_path or mt5.mt5_exe not configured")

        mq5_path = os.path.join(self.experts_path, f"{ea_name}.mq5")
        ex5_path = os.path.join(self.experts_path, f"{ea_name}.ex5")

        # Already compiled and up-to-date — skip
        if os.path.exists(ex5_path):
            mq5_mtime = os.path.getmtime(mq5_path)
            ex5_mtime = os.path.getmtime(ex5_path)
            if ex5_mtime >= mq5_mtime:
                logger.info("EA already compiled (up-to-date): %s.ex5", ea_name)
                return

        max_compile_retries = 3 if self._compile_fixer else 1

        for compile_attempt in range(1, max_compile_retries + 1):
            # Kill any lingering terminal64.exe (one Wine instance at a time)
            subprocess.run(["pkill", "-f", "terminal64"], capture_output=True)
            time.sleep(2)

            # Remove stale .ex5 so we can detect fresh compile success
            if os.path.exists(ex5_path):
                os.remove(ex5_path)

            wine_mq5 = "Z:" + mq5_path.replace("/", "\\")
            cmd = [self.wine_bin, self.mt5_exe, f"/compile:{wine_mq5}"]
            logger.info("Compiling EA: %s (attempt %d/%d)", ea_name, compile_attempt, max_compile_retries)

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except FileNotFoundError as e:
                raise RuntimeError(f"Wine not found: {self.wine_bin}") from e

            # Poll for .ex5 to appear (max 90 seconds)
            compile_timeout = 90
            deadline = time.time() + compile_timeout
            success = False
            while time.time() < deadline:
                time.sleep(2)
                if os.path.exists(ex5_path):
                    success = True
                    break

            proc.kill()
            stdout_text = ""
            try:
                stdout_raw, stderr_raw = proc.communicate(timeout=3)
                stdout_text = (stdout_raw or b"").decode("utf-8", errors="replace")
                stdout_text += (stderr_raw or b"").decode("utf-8", errors="replace")
            except Exception:
                pass

            if success:
                logger.info("Compiled successfully: %s.ex5", ea_name)
                return

            # Compile failed — log what we got
            logger.warning(
                "Compile attempt %d/%d FAILED for %s.mq5 (timeout=%ds)",
                compile_attempt, max_compile_retries, ea_name, compile_timeout,
            )
            if stdout_text:
                logger.warning("Compiler output:\n%s", stdout_text[:1000])

            # Try auto-fix if we have the fixer and retries remain
            if self._compile_fixer and compile_attempt < max_compile_retries:
                logger.info("Calling CompileErrorAgent to fix %s.mq5 ...", ea_name)
                fixed = self._compile_fixer.fix(mq5_path, error_output=stdout_text)
                if fixed:
                    logger.info("CompileErrorAgent applied a fix — retrying compile")
                    # Copy fixed .mq5 back to experts path (it IS already there, but re-copy to be sure)
                    continue
                else:
                    logger.warning("CompileErrorAgent could not fix errors — stopping retries")
                    break

        raise RuntimeError(
            f"Compilation failed after {max_compile_retries} attempt(s) for {ea_name}.mq5 — "
            "check logs for MQL5 syntax errors"
        )

    # ------------------------------------------------------------------
    # Step 2: Write tester.ini
    # ------------------------------------------------------------------

    def _write_tester_ini(self, spec: BacktestSpec, ea_name: str) -> str:
        """
        Write MT5 tester configuration file.
        Returns path to the ini file.
        """
        tf_code = TIMEFRAME_MAP.get(spec.timeframe, 16385)  # Default H1
        report_name = f"aureus_{ea_name}_{spec.date_from}_{spec.date_to}"

        ini_content = (
            "[Tester]\n"
            f"Expert=Aureus\\{ea_name}\n"
            f"Symbol={spec.symbol}\n"
            f"Period={tf_code}\n"
            f"Deposit={spec.initial_deposit:.0f}\n"
            "Currency=USD\n"
            f"Leverage={spec.leverage}\n"
            f"FromDate={spec.date_from.strftime('%Y.%m.%d')}\n"
            f"ToDate={spec.date_to.strftime('%Y.%m.%d')}\n"
            f"Model={spec.model}\n"
            "Optimization=Disabled\n"
            "OptimizationCriterion=0\n"
            f"Report={report_name}\n"
            "ReplaceReport=true\n"
            "ShutdownTerminal=true\n"
            f"Server={spec.broker_server}\n"
        )

        # Write ini to same folder as mt5_exe
        mt5_dir = os.path.dirname(self.mt5_exe) if self.mt5_exe else tempfile.gettempdir()
        ini_path = os.path.join(mt5_dir, "tester.ini")
        with open(ini_path, 'w') as f:
            f.write(ini_content)
        return ini_path

    # ------------------------------------------------------------------
    # Step 3: Snapshot existing reports
    # ------------------------------------------------------------------

    def _snapshot_reports(self) -> set:
        """Return set of HTML filenames currently in the reports directory."""
        if not os.path.exists(self.reports_path):
            return set()
        return {
            f for f in os.listdir(self.reports_path)
            if f.lower().endswith('.html') or f.lower().endswith('.htm')
        }

    # ------------------------------------------------------------------
    # Step 4: Launch MT5 via Wine
    # ------------------------------------------------------------------

    def _launch_mt5(self, ini_path: str) -> None:
        """Launch MT5 tester via Wine subprocess."""
        if not self.mt5_exe:
            raise RuntimeError("mt5.mt5_exe not configured in system.yaml")
        if not os.path.exists(self.mt5_exe):
            raise FileNotFoundError(
                f"MT5 executable not found: {self.mt5_exe}\n"
                "Check mt5.mt5_exe in config/system.yaml"
            )

        # Use terminal64.exe /config: to run the Strategy Tester automatically.
        # This works because we pre-compiled the .ex5 in _compile_ea().
        # terminal64.exe reads tester.ini, runs the backtest, writes report, exits.
        wine_ini_path = "Z:" + ini_path.replace("/", "\\")
        cmd = [self.wine_bin, self.mt5_exe, f"/config:{wine_ini_path}"]
        logger.info("Launching MT5 tester: %s", " ".join(cmd))

        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # Don't wait — metatester64.exe runs tester then exits
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Wine not found at '{self.wine_bin}'. Check mt5.wine_bin in system.yaml. "
                f"Original error: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Step 5: Poll for new HTML report
    # ------------------------------------------------------------------

    def _wait_for_report(self, existing_reports: set) -> str:
        """
        Poll the reports directory for a new HTML file.
        Returns absolute path to the new report.
        Raises TimeoutError if report doesn't appear within timeout.
        """
        if not self.reports_path:
            raise RuntimeError("mt5.reports_path not configured in system.yaml")

        deadline = time.time() + self.report_wait_timeout
        logger.info(
            "Polling %s for new report (timeout: %ds)...",
            self.reports_path,
            self.report_wait_timeout,
        )

        while time.time() < deadline:
            if os.path.exists(self.reports_path):
                current = {
                    f for f in os.listdir(self.reports_path)
                    if f.lower().endswith('.html') or f.lower().endswith('.htm')
                }
                new_files = current - existing_reports
                if new_files:
                    # Return the newest file if multiple appeared
                    newest = max(
                        new_files,
                        key=lambda f: os.path.getmtime(
                            os.path.join(self.reports_path, f)
                        ),
                    )
                    return os.path.join(self.reports_path, newest)

            time.sleep(self.poll_interval)

        raise TimeoutError(
            f"No new backtest report appeared in {self.reports_path} "
            f"within {self.report_wait_timeout}s. "
            "Check MT5 is running and strategy compiled successfully."
        )

    # ------------------------------------------------------------------
    # Dry-run mode (for testing without MT5)
    # ------------------------------------------------------------------

    def dry_run(self, spec: BacktestSpec, fixture_html_path: str) -> BacktestRunResult:
        """
        Skip actual MT5 execution and return a fixture HTML path.
        Used in tests and when MT5 is not available.
        """
        logger.info("DRY RUN: using fixture %s", fixture_html_path)
        return BacktestRunResult(
            report_html_path=fixture_html_path,
            spec=spec,
            run_at=datetime.utcnow(),
            duration_seconds=0.0,
        )
