"""
DaddyAgent — Environment bootstrapper and self-healing agent.

GOVERNANCE RULES (read before touching this file)
--------------------------------------------------
1. SEVERITY LEVELS      Each check is CRITICAL or WARNING.
                        - CRITICAL: all_ok=False if unfixed → startup blocked.
                        - WARNING:  logged but startup proceeds.
2. MAX_LLM_FIX_ATTEMPTS Hard cap on LLM-assisted fixes per prepare() call
                        (default 3). Prevents runaway LLM loops.
3. SAFE-ONLY EXECUTION  DaddyAgent only runs shell commands that the LLM
                        explicitly marks safe=true. Unsafe commands are
                        logged and skipped — never executed silently.
4. NO DESTRUCTIVE FIXES DaddyAgent NEVER runs rm, drop, truncate, or any
                        command that deletes existing data.
5. MT5/Wine is MANUAL   DaddyAgent cannot install MetaTrader or Wine.
                        Those checks are WARNING-only and surface a message.

LLM Usage in DaddyAgent
------------------------
DaddyAgent calls the LLM ONLY as a last resort after all built-in fix
recipes have already failed. It is governed by MAX_LLM_FIX_ATTEMPTS.
The LLM is NOT used for routine checks — only for unknown errors.
"""

from __future__ import annotations

import importlib
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Governance constants
# ---------------------------------------------------------------------------

MAX_LLM_FIX_ATTEMPTS: int = 3   # LLM is last resort — cap it hard


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class CheckSeverity(Enum):
    CRITICAL = "CRITICAL"   # Must pass — blocks startup if unfixed
    WARNING  = "WARNING"    # Should pass — startup proceeds regardless


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str
    severity: CheckSeverity = CheckSeverity.CRITICAL
    fix_applied: bool = False
    fix_description: str = ""

    def __str__(self) -> str:
        icon = "✓" if self.ok else ("⚠" if self.severity == CheckSeverity.WARNING else "✗")
        sev  = f"[{self.severity.value}] " if not self.ok else ""
        fix  = f"  → fixed: {self.fix_description}" if self.fix_applied else ""
        return f"{icon} {sev}{self.name}: {self.message}{fix}"

    @property
    def blocks_startup(self) -> bool:
        return not self.ok and self.severity == CheckSeverity.CRITICAL


@dataclass
class HealthReport:
    all_ok: bool        # True only when all CRITICAL checks pass
    checks: list[CheckResult] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["=== DaddyAgent Environment Report ==="]
        for c in self.checks:
            lines.append(f"  {c}")
        status = "READY" if self.all_ok else "BLOCKED — fix CRITICAL issues above"
        lines.append(f"=== Status: {status} ===")
        return "\n".join(lines)

    @property
    def failed_critical(self) -> list[CheckResult]:
        return [c for c in self.checks if c.blocks_startup]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok and c.severity == CheckSeverity.WARNING]

    @property
    def fixed(self) -> list[CheckResult]:
        return [c for c in self.checks if c.fix_applied]


# ---------------------------------------------------------------------------
# DaddyAgent
# ---------------------------------------------------------------------------


class DaddyAgent:
    """
    Environment bootstrapper and self-healing agent.

    Run prepare() before orchestrator.run() or crew.kickoff().
    Returns a HealthReport.  If report.all_ok is False, there are
    unresolved CRITICAL issues and startup should be aborted.

    Auto-fix hierarchy (tried in this order per failing check):
      1. Built-in recipe  (pip install / mkdir / ollama pull / alembic)
      2. LLM diagnosis    (last resort, capped at MAX_LLM_FIX_ATTEMPTS,
                           only runs safe=true shell commands)
      3. Surface to human (manual action message logged)
    """

    REQUIRED_PACKAGES: list[str] = [
        "yaml",        # pyyaml
        "jinja2",
        "sqlalchemy",
        "httpx",
        "tenacity",
        "pydantic",
        "bs4",         # beautifulsoup4
        "alembic",
    ]

    _INSTALL_NAME: dict[str, str] = {
        "yaml": "pyyaml",
        "bs4":  "beautifulsoup4",
    }

    # Commands DaddyAgent will NEVER run even if LLM suggests them
    _BANNED_COMMAND_PATTERNS: tuple[str, ...] = (
        "rm ", "rm\t", "rmdir",
        "drop ", "truncate ",
        "dd if=", "mkfs",
        "> /dev/", "format ",
    )

    def __init__(self, config_path: str = "config/system.yaml") -> None:
        abs_path = Path(__file__).parent.parent / config_path
        with open(abs_path) as f:
            self.config: dict = yaml.safe_load(f)
        self._ollama = None
        self._llm_fix_count: int = 0   # Counts LLM-assisted fix attempts

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def prepare(self, auto_fix: bool = True) -> HealthReport:
        """
        Run all environment checks and attempt to fix failures.

        Severity rules:
        - CRITICAL checks that are still failing → all_ok = False → abort startup
        - WARNING checks that are still failing  → all_ok stays True → startup OK

        LLM diagnosis is only attempted for CRITICAL failures that have no
        built-in fix, and only up to MAX_LLM_FIX_ATTEMPTS times.
        """
        checks: list[CheckResult] = []

        checks.append(self._check_python_packages(auto_fix))   # CRITICAL
        checks.append(self._check_directories(auto_fix))        # CRITICAL
        checks.append(self._check_ollama(auto_fix))             # CRITICAL
        checks.append(self._check_database(auto_fix))           # CRITICAL
        checks.append(self._check_bridge_dirs(auto_fix))        # CRITICAL
        checks.append(self._check_templates())                   # CRITICAL
        checks.append(self._check_mql5_syntax())                 # WARNING (renders + static checks)
        checks.append(self._check_mt5_paths())                  # WARNING (manual install)
        checks.append(self._check_wine_stale_processes(auto_fix))  # WARNING (auto-kill stale MT5)
        checks.append(self._check_wine_semaphore())              # WARNING (kernel panic guard)

        # Last resort: LLM diagnosis for unfixed CRITICAL failures
        if auto_fix and self._ollama is not None:
            for i, check in enumerate(checks):
                if (
                    check.blocks_startup
                    and not check.fix_applied
                    and self._llm_fix_count < MAX_LLM_FIX_ATTEMPTS
                ):
                    checks[i] = self._llm_diagnose_and_fix(check)

        # all_ok = no unfixed CRITICAL failures (warnings are allowed)
        all_ok = not any(c.blocks_startup for c in checks)
        report = HealthReport(all_ok=all_ok, checks=checks)

        if all_ok:
            warn_count = len(report.warnings)
            suffix = f" ({warn_count} warning(s))" if warn_count else ""
            logger.info(f"DaddyAgent: environment ready ✓{suffix}")
        else:
            names = [c.name for c in report.failed_critical]
            logger.error(
                f"DaddyAgent: {len(names)} CRITICAL check(s) unresolved: {names}. "
                "Startup blocked."
            )

        return report

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_python_packages(self, auto_fix: bool) -> CheckResult:
        missing: list[str] = []
        for pkg in self.REQUIRED_PACKAGES:
            try:
                importlib.import_module(pkg)
            except ImportError:
                missing.append(pkg)

        if not missing:
            return CheckResult("python_packages", True, "All packages present")

        if auto_fix:
            install_names = [self._INSTALL_NAME.get(p, p) for p in missing]
            logger.info(f"DaddyAgent: pip install {install_names}")
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install"] + install_names,
                capture_output=True, text=True,
            )
            if proc.returncode == 0:
                return CheckResult(
                    "python_packages", True, "All packages present",
                    fix_applied=True,
                    fix_description=f"pip install {' '.join(install_names)}",
                )
            return CheckResult(
                "python_packages", False, f"pip install failed: {proc.stderr[:200]}",
            )

        return CheckResult("python_packages", False, f"Missing: {missing}")

    def _check_directories(self, auto_fix: bool) -> CheckResult:
        paths = self.config.get("paths", {})
        log_dir = self.config.get("logging", {}).get("log_dir", "./logs")

        required: list[str] = [
            paths.get("strategies", "./strategies"),
            paths.get("generated",  "./strategies/generated"),
            paths.get("validated",  "./strategies/validated"),
            paths.get("champion",   "./strategies/champion"),
            paths.get("archive",    "./strategies/archive"),
            paths.get("reports",    "./reports"),
            "./reports/raw",
            "./reports/parsed",
            "./reports/analysis",
            log_dir,
        ]

        missing = [d for d in required if not Path(d).is_dir()]
        if not missing:
            return CheckResult("directories", True, "All project directories exist")

        if auto_fix:
            for d in missing:
                Path(d).mkdir(parents=True, exist_ok=True)
            return CheckResult(
                "directories", True, "All project directories exist",
                fix_applied=True,
                fix_description=f"created {len(missing)} missing dirs",
            )

        return CheckResult("directories", False, f"Missing: {missing}")

    def _check_ollama(self, auto_fix: bool) -> CheckResult:
        try:
            from core.ollama_client import OllamaClient

            client = OllamaClient()
            health = client.health_check()

            if health["ok"]:
                self._ollama = client
                models = ", ".join(sorted(health["models"])[:3])
                return CheckResult("ollama", True, f"Running — models: {models}")

            missing_models: list[str] = health.get("missing", [])
            if not missing_models:
                self._ollama = client
                return CheckResult("ollama", True, "Running")

            if auto_fix:
                pulled, failed = [], []
                for model in missing_models:
                    logger.info(f"DaddyAgent: ollama pull {model} ...")
                    proc = subprocess.run(
                        ["ollama", "pull", model],
                        capture_output=True, text=True, timeout=300,
                    )
                    (pulled if proc.returncode == 0 else failed).append(model)

                self._ollama = client
                if not failed:
                    return CheckResult(
                        "ollama", True, "All models ready",
                        fix_applied=True,
                        fix_description=f"pulled {pulled}",
                    )
                return CheckResult(
                    "ollama", False, f"Could not pull: {failed}",
                    fix_applied=bool(pulled),
                    fix_description=f"pulled {pulled}, failed {failed}",
                )

            return CheckResult("ollama", False, f"Missing models: {missing_models}")

        except Exception as exc:
            return CheckResult("ollama", False, f"Not reachable: {exc}")

    def _check_database(self, auto_fix: bool) -> CheckResult:
        db_url: str = self.config.get("database", {}).get("url", "")
        if not db_url:
            return CheckResult("database", False, "No database.url in config/system.yaml")

        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(db_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            host = db_url.split("@")[-1]
            return CheckResult("database", True, f"Connected ({host})")

        except Exception as exc:
            err = str(exc)
            if auto_fix and "does not exist" in err:
                db_name = db_url.rsplit("/", 1)[-1]
                create_proc = subprocess.run(
                    ["createdb", db_name], capture_output=True, text=True
                )
                if create_proc.returncode == 0:
                    mig_proc = subprocess.run(
                        ["alembic", "upgrade", "head"], capture_output=True, text=True
                    )
                    ok = mig_proc.returncode == 0
                    msg = (
                        "DB created + migrations applied" if ok
                        else f"DB created but migration failed: {mig_proc.stderr[:200]}"
                    )
                    return CheckResult(
                        "database", ok, msg,
                        fix_applied=True,
                        fix_description=f"createdb {db_name} + alembic upgrade head",
                    )
            return CheckResult("database", False, f"Connection failed: {err[:200]}")

    def _check_bridge_dirs(self, auto_fix: bool) -> CheckResult:
        bridge = self.config.get("bridge", {})
        dirs = [bridge.get("request_dir", ""), bridge.get("response_dir", "")]
        missing = [d for d in dirs if d and not Path(d).is_dir()]

        if not missing:
            return CheckResult("bridge_dirs", True, "Bridge IPC directories exist")

        if auto_fix:
            for d in missing:
                Path(d).mkdir(parents=True, exist_ok=True)
            return CheckResult(
                "bridge_dirs", True, "Bridge IPC directories ready",
                fix_applied=True,
                fix_description=f"created {len(missing)} IPC dirs",
            )
        return CheckResult("bridge_dirs", False, f"Missing IPC dirs: {missing}")

    def _check_templates(self) -> CheckResult:
        base = Path("templates/mql5")
        required = [
            "base_ea.mq5.jinja2",
            "frameworks/XAUBreakout.mq5.jinja2",
            "frameworks/TrendFollowing.mq5.jinja2",
        ]
        missing = [t for t in required if not (base / t).exists()]
        if missing:
            return CheckResult("templates", False, f"Missing templates: {missing}")
        return CheckResult("templates", True, f"Templates present in {base}")

    def _check_mql5_syntax(self) -> CheckResult:
        """
        WARNING severity — render each framework template with dummy values and
        run static checks via CompileErrorAgent.validate_template_output().

        Catches Jinja2 errors and obvious MQL5 mistakes before any compile is attempted.
        """
        try:
            from jinja2 import Environment, FileSystemLoader, StrictUndefined, UndefinedError
            from agents.compile_error_agent import CompileErrorAgent

            base = Path("templates/mql5")
            fixer = CompileErrorAgent()

            # Minimal dummy context matching code_generator.py render_ctx
            dummy_ctx = dict(
                name="AureusTest",
                version="0.0.1",
                symbol="XAUUSD",
                timeframe="H1",
                magic_number=12345678,
                risk_percent=0.5,
                max_spread_pips=50,
                stop_loss_pips=30,
                take_profit_pips=90,
                breakeven_pips=15,
                trailing_stop_pips=20,
                rsi_period=14,
                rsi_oversold=30.0,
                rsi_overbought=70.0,
                atr_period=14,
                atr_max_multiplier=1.5,
                ema_period=200,
                lookback_period=20,
                use_adx_filter=False,
                adx_min_strength=25,
                use_h4_filter=False,
                h4_ema_period=50,
                generated_at="2026-01-01T00:00:00",
                # breakout-specific extras
                atr_sl_mult=1.5,
            )

            check_templates = [
                "frameworks/XAUBreakout.mq5.jinja2",
                "frameworks/TrendFollowing.mq5.jinja2",
            ]

            issues: list[str] = []
            env = Environment(
                loader=FileSystemLoader(str(base.resolve())),
                undefined=StrictUndefined,
                trim_blocks=True,
                lstrip_blocks=True,
            )

            for tmpl_name in check_templates:
                if not (base / tmpl_name).exists():
                    continue
                try:
                    rendered = env.get_template(tmpl_name).render(**dummy_ctx)
                    ok, violations = fixer.validate_template_output(rendered)
                    if not ok:
                        for v in violations:
                            issues.append(f"{tmpl_name}: {v}")
                except UndefinedError as e:
                    issues.append(f"{tmpl_name}: Jinja2 undefined variable — {e}")
                except Exception as e:
                    issues.append(f"{tmpl_name}: render error — {e}")

            if issues:
                return CheckResult(
                    "mql5_syntax", False,
                    "Template static checks failed:\n  " + "\n  ".join(issues),
                    severity=CheckSeverity.WARNING,
                )
            return CheckResult(
                "mql5_syntax", True,
                f"All {len(check_templates)} templates render cleanly",
                severity=CheckSeverity.WARNING,
            )

        except Exception as exc:
            return CheckResult(
                "mql5_syntax", False,
                f"Syntax check skipped: {exc}",
                severity=CheckSeverity.WARNING,
            )

    def _check_mt5_paths(self) -> CheckResult:
        """
        WARNING severity — DaddyAgent cannot install MT5 or Wine.
        Startup is NOT blocked by missing MT5 paths (useful for CI/dev).
        """
        mt5 = self.config.get("mt5", {})
        issues: list[str] = []

        for key, label in [
            ("experts_path", "experts_path"),
            ("wine_bin",     "wine_bin"),
            ("mt5_exe",      "mt5_exe"),
        ]:
            val = mt5.get(key, "")
            if val:
                check_fn = Path(val).is_dir if key == "experts_path" else Path(val).is_file
                if not check_fn():
                    issues.append(f"{label} not found")

        if issues:
            return CheckResult(
                "mt5_paths", False,
                "; ".join(issues) + " — install MT5 + Wine manually",
                severity=CheckSeverity.WARNING,   # WARNING — does not block startup
            )
        return CheckResult("mt5_paths", True, "MT5 paths verified",
                           severity=CheckSeverity.WARNING)

    def _check_wine_stale_processes(self, auto_fix: bool) -> CheckResult:
        """
        WARNING severity — kill stale terminal64.exe before startup.

        Root cause learned: 2026-03-16 kernel panic on Mac Mini M1.
        Panicked task: pid 6180 terminal64.exe — spinlock timeout.
        Cause: multiple terminal64.exe instances running concurrently under Wine on
        Apple Silicon cause kernel-level memory lock deadlock → machine reboots.
        Fix: always kill stale instances before launching new backtest cycle.
        """
        result = subprocess.run(
            ["pgrep", "-f", "terminal64"],
            capture_output=True, text=True,
        )
        pids = [p.strip() for p in result.stdout.splitlines() if p.strip()]

        if not pids:
            return CheckResult(
                "wine_stale_processes", True,
                "No stale terminal64.exe processes",
                severity=CheckSeverity.WARNING,
            )

        if auto_fix:
            subprocess.run(["pkill", "-f", "terminal64"], capture_output=True)
            logger.warning(
                "DaddyAgent: killed %d stale terminal64.exe process(es) %s "
                "— prevents kernel spinlock panic on Apple Silicon",
                len(pids), pids,
            )
            return CheckResult(
                "wine_stale_processes", True,
                f"Killed {len(pids)} stale terminal64.exe (prevents kernel panic)",
                severity=CheckSeverity.WARNING,
                fix_applied=True,
                fix_description=f"pkill -f terminal64 (was: {pids})",
            )

        return CheckResult(
            "wine_stale_processes", False,
            f"{len(pids)} stale terminal64.exe running — risk of kernel panic on Apple Silicon",
            severity=CheckSeverity.WARNING,
        )

    def _check_wine_semaphore(self) -> CheckResult:
        """
        WARNING severity — verify MultiSymbolOrchestrator uses _wine_semaphore.

        Root cause learned: 2026-03-16 kernel panic on Mac Mini M1.
        When 3 symbols run backtests concurrently each spawns terminal64.exe
        → Wine memory lock contention → kernel spinlock timeout → machine reboot.
        Fix: _wine_semaphore = asyncio.Semaphore(1) serialises all MT5 calls.
        This check ensures that fix is still in place (regression guard).
        """
        try:
            import inspect
            from agents.multi_symbol_orchestrator import MultiSymbolOrchestrator
            src = inspect.getsource(MultiSymbolOrchestrator.__init__)
            if "_wine_semaphore" in src and "asyncio.Semaphore" in src:
                return CheckResult(
                    "wine_semaphore", True,
                    "MultiSymbolOrchestrator._wine_semaphore present — kernel panic guard active",
                    severity=CheckSeverity.WARNING,
                )
            return CheckResult(
                "wine_semaphore", False,
                "WARNING: _wine_semaphore missing from MultiSymbolOrchestrator — "
                "concurrent terminal64.exe WILL cause kernel panic on Apple Silicon M1. "
                "Add: self._wine_semaphore = asyncio.Semaphore(1) and pass to OrchestratorAgent.",
                severity=CheckSeverity.WARNING,
            )
        except Exception as exc:
            return CheckResult(
                "wine_semaphore", False,
                f"Could not inspect MultiSymbolOrchestrator: {exc}",
                severity=CheckSeverity.WARNING,
            )

    # ------------------------------------------------------------------
    # LLM-assisted diagnosis  (last resort — capped)
    # ------------------------------------------------------------------

    def _llm_diagnose_and_fix(self, check: CheckResult) -> CheckResult:
        """
        Ask the LLM to diagnose a CRITICAL failure and propose a safe fix.

        Governance:
        - Only runs when _llm_fix_count < MAX_LLM_FIX_ATTEMPTS
        - Only executes commands the LLM marks safe=true
        - Never executes commands matching _BANNED_COMMAND_PATTERNS
        """
        if self._ollama is None:
            return check

        self._llm_fix_count += 1
        logger.info(
            f"DaddyAgent: LLM diagnosis [{self._llm_fix_count}/{MAX_LLM_FIX_ATTEMPTS}]"
            f" for '{check.name}'"
        )

        system = (
            "You are a DevOps engineer. Given an environment check failure, respond with "
            'JSON: {"diagnosis": str, "fix_command": str or null, "safe": bool}. '
            "fix_command must be a single idempotent shell command. "
            "safe=true ONLY if the command is non-destructive and cannot cause data loss. "
            "Never suggest rm, drop, truncate, or format commands."
        )
        prompt = (
            f"Check '{check.name}' failed.\n"
            f"Error: {check.message}\n"
            f"Platform: macOS Darwin, Python {sys.version.split()[0]}\n"
            f"Working directory: {os.getcwd()}\n"
            "Propose a safe fix."
        )

        try:
            data = self._ollama.analyze(prompt=prompt, system=system)
            diagnosis: str = data.get("diagnosis", "")
            fix_cmd: Optional[str] = data.get("fix_command")
            safe: bool = bool(data.get("safe", False))

            logger.info(f"DaddyAgent LLM [{check.name}]: {diagnosis}")

            if fix_cmd:
                if self._is_banned_command(fix_cmd):
                    logger.error(
                        f"DaddyAgent: LLM proposed BANNED command — refused: {fix_cmd}"
                    )
                    return CheckResult(
                        check.name, False,
                        f"{check.message} | LLM proposed destructive command — manual fix required",
                    )

                if safe:
                    logger.info(f"DaddyAgent: running LLM fix: {fix_cmd}")
                    proc = subprocess.run(
                        fix_cmd, shell=True, capture_output=True, text=True, timeout=60,
                    )
                    if proc.returncode == 0:
                        return CheckResult(
                            check.name, True, f"Fixed — {diagnosis}",
                            fix_applied=True, fix_description=fix_cmd,
                        )
                    return CheckResult(
                        check.name, False,
                        f"{check.message} | LLM fix failed: {proc.stderr[:200]}",
                        fix_applied=True, fix_description=f"tried: {fix_cmd}",
                    )
                else:
                    logger.warning(
                        f"DaddyAgent: LLM proposed unsafe fix — skipped: {fix_cmd}"
                    )
                    return CheckResult(
                        check.name, False,
                        f"{check.message} | manual fix needed: {fix_cmd}",
                    )

        except Exception as exc:
            logger.warning(f"DaddyAgent: LLM diagnosis error: {exc}")

        return check

    def _is_banned_command(self, cmd: str) -> bool:
        lower = cmd.lower()
        return any(pattern in lower for pattern in self._BANNED_COMMAND_PATTERNS)
