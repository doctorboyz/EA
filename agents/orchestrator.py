"""
OrchestratorAgent — Main improvement loop connecting all 6 agents.

Loop:
  for iteration in range(max_iterations):
    1. Generate MQL5 code  (CodeGeneratorAgent)
    2. Run backtest        (BacktestRunnerAgent)
    3. Parse report        (ReportParser)
    4. Save to database    (SQLAlchemy)
    5. Analyze result      (ResultAnalyzerAgent)
    6. Promote champion    (if meets_all_targets and best PF so far)
    7. Improve config      (StrategyImproverAgent)

Stop early if: all 4 targets hit, or max_iterations reached.
"""

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from core.strategy_config import StrategyConfig, StrategyVersion, BacktestResult
from core.database import Strategy, BacktestRun, Analysis, Improvement, get_session
from core.constraint_validator import ConstraintViolation
from core.champion_manager import ChampionManager
from core.ollama_client import OllamaClient
from core.experience_db import ExperienceDB
from agents.code_generator import CodeGeneratorAgent
from agents.backtest_runner import BacktestRunnerAgent, BacktestSpec
from agents.market_regime_detector import MarketRegimeDetector, Bar, RegimeSnapshot
from agents.report_parser import ReportParser
from agents.result_analyzer import ResultAnalyzerAgent
from agents.strategy_improver import StrategyImproverAgent

logger = logging.getLogger(__name__)

CHAMPION_DIR = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'champion')


def _load_config() -> dict:
    cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
    with open(cfg_path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Result summary for the caller
# ---------------------------------------------------------------------------

@dataclass
class LoopResult:
    """Summary of a completed improvement loop."""
    iterations_run: int
    champion_version: Optional[str]
    champion_pf: float
    champion_path: Optional[str]
    all_targets_met: bool
    history: list[dict] = field(default_factory=list)  # per-iteration snapshots


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class OrchestratorAgent:
    """
    Main improvement loop connecting all 6 agents.

    Can be run in two modes:
    - live:    uses real MT5 backtesting (requires Wine + MT5)
    - dry_run: uses fixture HTML files (for testing without MT5)
    """

    def __init__(
        self,
        max_iterations: Optional[int] = None,
        dry_run: bool = False,
        dry_run_fixture: Optional[str] = None,
        use_llm: bool = True,
        config_override: Optional[dict] = None,
        symbol: Optional[str] = None,
        iterations: Optional[int] = None,
        llm_semaphore: Optional[asyncio.Semaphore] = None,
        wine_semaphore: Optional[asyncio.Semaphore] = None,
        on_champion_callback=None,
    ) -> None:
        cfg = config_override or _load_config()
        proj = cfg.get('project', {})

        self.max_iterations: int = iterations or max_iterations or proj.get('max_iterations', 50)
        self.dry_run = dry_run
        self.dry_run_fixture = dry_run_fixture
        self.use_llm = use_llm

        # Multi-symbol support: override project.symbol if provided
        self.symbol: str = symbol or proj.get('symbol', 'EURUSD')
        self.timeframe: str = proj.get('timeframe', 'H1')
        self.initial_capital: float = proj.get('initial_capital', 1000.0)
        self.date_from: date = date.fromisoformat(proj.get('test_period_start', '2025-01-01'))
        self.date_to: date = date.fromisoformat(proj.get('test_period_end', '2026-03-12'))

        # Initialize agents
        ollama = OllamaClient()
        self.code_gen = CodeGeneratorAgent(ollama=ollama, use_llm=False)
        self.backtest_runner = BacktestRunnerAgent(config=cfg)
        self.result_analyzer = ResultAnalyzerAgent(ollama=ollama)
        self.strategy_improver = StrategyImproverAgent(ollama=ollama)

        # Walk-forward validation config
        wf_cfg = cfg.get('walk_forward', {})
        self._wf_enabled         = wf_cfg.get('enabled', True)
        self._wf_n_windows       = wf_cfg.get('n_windows', 6)
        self._wf_train_months    = wf_cfg.get('train_months', 3)
        self._wf_test_months     = wf_cfg.get('test_months', 2)
        self._wf_capital_ranges  = wf_cfg.get('capital_ranges', [100, 500, 1000, 5000])
        self._wf_timeframes      = wf_cfg.get('timeframes', ["H1", "H4"])

        # Lazy init walk-forward validator (avoids import cycle)
        self._wf_validator = None

        # Multi-symbol coordination
        self._llm_semaphore  = llm_semaphore   # shared across all symbols (max 1 LLM call)
        self._wine_semaphore = wine_semaphore  # shared across all symbols (max 1 MT5/Wine process)
        self._on_champion_callback = on_champion_callback  # async callback(symbol, result, mq5_path)

        # Champion manager (database-backed, per-symbol)
        db_url = cfg.get('database', {}).get('url')
        self.champion_manager = ChampionManager(db_url)

        # Symbol-aware framework priority (XAUUSD-only with all 8 frameworks)
        _symbol_frameworks: dict[str, list[str]] = {
            "XAUUSD": [
                "XAUBreakout",      # ATR-channel breakout — built for XAUUSD volatility
                "TrendFollowing",   # EMA-based trend — proven on XAUUSD (PF 2.85)
                "Breakout",         # Generic breakout
                "MeanReversion",    # RSI mean reversion
                "SniperEntry",      # Precision entries
                "CandlePattern",    # Pattern recognition
                "IchimokuCloud",    # Trend + cloud
                "GridTrading",      # Choppy/ranging markets
            ],
        }
        self._frameworks: list[str] = _symbol_frameworks.get(self.symbol, [
            "XAUBreakout",
            "TrendFollowing",
            "Breakout",
            "MeanReversion",
            "SniperEntry",
            "CandlePattern",
            "IchimokuCloud",
            "GridTrading",
        ])
        self._current_framework_idx = 0  # Fallback round-robin when no experience data

        # Phase 3: Experience DB + market regime detector
        db_url = cfg.get('database', {}).get('url', '')
        self._experience = ExperienceDB(db_url) if db_url else None
        self._regime_detector = MarketRegimeDetector()
        self._current_regime: Optional[RegimeSnapshot] = None

        # Tracking
        # Load global champion for this symbol (or start fresh if none exists)
        global_champ = self.champion_manager.get_global_champion(self.symbol)
        self._champion_pf: float = global_champ['profit_factor'] if global_champ else 0.0
        self._champion_version: Optional[str] = global_champ['version'] if global_champ else None
        self._champion_path: Optional[str] = global_champ['file_path'] if global_champ else None
        self._history: list[dict] = []

        # Phase tracking (for dashboard)
        self._current_phase: str = "hunt"  # hunt | walk_forward | forward_test | live
        self._phase_gate_pf: float = cfg.get('targets', {}).get('champion', {}).get('profit_factor', 1.3)
        self._phase_detail: str = "Initializing..."

        logger.info(
            "Initialized OrchestratorAgent for %s: global champion PF=%.2f (v%s)",
            self.symbol, self._champion_pf, self._champion_version or "none"
        )
        logger.info(
            "Framework rotation enabled: %s",
            " → ".join(self._frameworks)
        )

    def set_regime(self, snapshot: RegimeSnapshot) -> None:
        """Inject current market regime from MultiSymbolOrchestrator."""
        self._current_regime = snapshot
        logger.info("[%s] Regime injected: %s (ADX=%.1f, ATR%%=%.3f)",
                   self.symbol, snapshot.regime, snapshot.adx or 0, snapshot.atr_pct or 0)

    def _write_phase_status(self, iteration: int, max_iterations: int) -> None:
        """Write phase-aware status to JSON for dashboard."""
        status_file = Path(os.path.join(os.path.dirname(__file__), '..', 'logs', 'system_status.json'))
        status_file.parent.mkdir(parents=True, exist_ok=True)

        # Determine current phase
        if self._champion_pf >= self._phase_gate_pf:
            self._current_phase = "walk_forward"
            phase_gate = f"4/6 windows pass to trigger forward_test. Current best PF: {self._champion_pf:.2f}"
        else:
            self._current_phase = "hunt"
            phase_gate = f"PF >= {self._phase_gate_pf} to trigger Walk-Forward. Current best PF: {self._champion_pf:.2f}"

        # Current framework (safe index)
        fw_idx = self._current_framework_idx % len(self._frameworks) if self._frameworks else 0
        current_fw = self._frameworks[fw_idx] if self._frameworks else "unknown"

        # Fetch champion details from DB if available
        champ_dd = 0.0
        champ_rf = 0.0
        champ_wl = 0.0
        try:
            champ_data = self.champion_manager.get_global_champion(self.symbol)
            if champ_data:
                champ_dd = champ_data.get('max_drawdown_pct', 0.0)
                champ_rf = champ_data.get('recovery_factor', 0.0)
                champ_wl = champ_data.get('avg_win_loss_ratio', 0.0)
        except Exception:
            pass

        status = {
            "state": "running",
            "phase": self._current_phase,
            "phase_detail": f"Iteration {iteration}/{max_iterations} -- {current_fw} (champion: v{self._champion_version or 'none'})",
            "phase_gate": phase_gate,
            "symbol": self.symbol,
            "champion": {
                "version": self._champion_version or "none",
                "pf": round(self._champion_pf, 2),
                "dd": round(champ_dd, 1),
                "rf": round(champ_rf, 2),
                "wl": round(champ_wl, 2),
            },
            "hunt_log": self._history[-20:],
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
        }

        try:
            status_file.write_text(json.dumps(status, indent=2))
        except Exception as e:
            logger.warning("Failed to write status JSON: %s", e)

    # ------------------------------------------------------------------
    # Entry point (async for database I/O)
    # ------------------------------------------------------------------

    async def run(
        self,
        initial_config: Optional[StrategyConfig] = None,
    ) -> LoopResult:
        """
        Run the improvement loop.

        Args:
            initial_config: Starting StrategyConfig (default: V3 baseline)

        Returns:
            LoopResult with champion info and per-iteration history
        """
        current_config = initial_config or self._load_v3_baseline()
        history: list[BacktestResult] = []

        logger.info(
            "=== Aureus Improvement Loop ===\n"
            "  Starting version: %s\n"
            "  Max iterations: %d\n"
            "  Symbol: %s %s\n"
            "  Period: %s → %s\n"
            "  Mode: %s",
            current_config.version,
            self.max_iterations,
            self.symbol, self.timeframe,
            self.date_from, self.date_to,
            "DRY RUN" if self.dry_run else "LIVE",
        )

        for iteration in range(self.max_iterations):
            logger.info("\n--- Iteration %d / %d ---", iteration + 1, self.max_iterations)

            # Write phase status so dashboard can read it
            self._write_phase_status(iteration + 1, self.max_iterations)

            try:
                result = await self._run_one_iteration(
                    current_config, iteration, history
                )
            except ConstraintViolation as e:
                logger.error("Constraint violation at iteration %d: %s", iteration + 1, e)
                current_config = current_config.version.bump_iteration() and current_config
                continue
            except Exception as e:
                logger.error("Iteration %d failed: %s", iteration + 1, e, exc_info=True)
                break

            if result is None:
                break

            backtest_result, new_config = result
            history.append(backtest_result)
            current_config = new_config

            # Record snapshot
            self._history.append({
                "iteration": iteration + 1,
                "version": backtest_result.strategy_version,
                "profit_factor": backtest_result.profit_factor,
                "max_drawdown_pct": backtest_result.max_drawdown_pct,
                "recovery_factor": backtest_result.recovery_factor,
                "avg_win_loss_ratio": backtest_result.avg_win_loss_ratio,
                "meets_all_targets": backtest_result.meets_all_targets,
            })

            # Early exit if all targets met
            if backtest_result.meets_all_targets:
                logger.info(
                    "🏆 ALL TARGETS MET at iteration %d! "
                    "PF=%.2f DD=%.1f%% RF=%.2f WL=%.2f",
                    iteration + 1,
                    backtest_result.profit_factor,
                    backtest_result.max_drawdown_pct,
                    backtest_result.recovery_factor,
                    backtest_result.avg_win_loss_ratio,
                )
                break

        result = LoopResult(
            iterations_run=len(self._history),
            champion_version=self._champion_version,
            champion_pf=self._champion_pf,
            champion_path=self._champion_path,
            all_targets_met=any(h["meets_all_targets"] for h in self._history),
            history=self._history,
        )
        # Return as dict for MultiSymbolOrchestrator.summary.get() access
        return result

    # ------------------------------------------------------------------
    async def _get_next_framework(self) -> str:
        """
        Pick next framework using experience data (Phase 3).
        Falls back to round-robin if no experience yet.
        """
        regime = self._current_regime.regime if self._current_regime else None

        # Use ExperienceDB when available
        if self._experience:
            try:
                framework = await self._experience.pick_framework(
                    symbol=self.symbol,
                    regime=regime,
                    all_frameworks=self._frameworks,
                )
                return framework
            except Exception as e:
                logger.warning("ExperienceDB pick_framework failed (%s), using round-robin", e)

        # Fallback: simple round-robin
        framework = self._frameworks[self._current_framework_idx % len(self._frameworks)]
        self._current_framework_idx += 1
        return framework

    async def _detect_regime_from_history(self, history: list[BacktestResult]) -> Optional[RegimeSnapshot]:
        """Detect market regime from available signal agent or simple heuristic."""
        # We don't have live bar data in the orchestrator,
        # so use the regime snapshot from MultiSymbolOrchestrator if available
        return self._current_regime

    # Single iteration
    # ------------------------------------------------------------------

    async def _run_one_iteration(
        self,
        config: StrategyConfig,
        iteration: int,
        history: list[BacktestResult],
    ) -> Optional[tuple[BacktestResult, StrategyConfig]]:
        """Run one full Generate → Test → Parse → Analyze → Improve cycle."""

        # === Validate config consistency ===
        # Ensure config matches orchestrator's symbol/timeframe/capital
        config.symbol = self.symbol
        config.timeframe = self.timeframe
        if config.initial_capital != self.initial_capital:
            logger.info("[Config] Syncing capital: %.0f → %.0f", config.initial_capital, self.initial_capital)
            config.initial_capital = self.initial_capital

        # === Step 1: Generate ===
        framework = await self._get_next_framework()
        regime_name = self._current_regime.regime if self._current_regime else "unknown"
        logger.info("[1/5] Generating v%s | %s %s %s R%s Cap%.0f | %s framework (regime: %s)",
                   config.version, self.symbol, self.timeframe, "H1", config.risk_percent,
                   self.initial_capital, framework, regime_name)
        gen_kwargs = dict(
            symbol=self.symbol,
            timeframe=self.timeframe,
            risk_percent=config.risk_percent,
            initial_capital=self.initial_capital,
            framework=framework,  # Add framework parameter
        )
        if self._llm_semaphore is not None:
            async with self._llm_semaphore:
                generated = await asyncio.to_thread(
                    lambda: self.code_gen.generate(config, **gen_kwargs)
                )
        else:
            generated = self.code_gen.generate(config, **gen_kwargs)
        logger.info("  Generated: %s", generated.file_path)

        # === Step 2: Backtest ===
        logger.info("[2/5] Running backtest...")
        spec = BacktestSpec(
            mq5_file_path=generated.file_path,
            symbol=self.symbol,
            timeframe=self.timeframe,
            date_from=self.date_from,
            date_to=self.date_to,
            initial_deposit=self.initial_capital,
            broker_server=self.backtest_runner.broker_server,
        )

        if self.dry_run:
            run_result = self.backtest_runner.dry_run(spec, self.dry_run_fixture)
        else:
            # Acquire Wine semaphore — only 1 terminal64.exe at a time (prevents kernel panic on ARM)
            if self._wine_semaphore is not None:
                async with self._wine_semaphore:
                    run_result = await asyncio.to_thread(self.backtest_runner.run, spec)
            else:
                run_result = await asyncio.to_thread(self.backtest_runner.run, spec)

        logger.info("  Report: %s (%.1fs)", run_result.report_html_path, run_result.duration_seconds)

        # === Step 3: Parse ===
        logger.info("[3/5] Parsing report...")
        backtest_result = ReportParser.parse(run_result.report_html_path)
        backtest_result.strategy_version = str(config.version)
        backtest_result.check_targets()
        self._log_metrics(backtest_result)

        # === Step 4: Save to database ===
        async with get_session() as session:
            db_strategy = await self._upsert_strategy(session, config, generated.code_hash, generated.file_path, framework)
            db_run = await self._save_backtest_run(session, db_strategy.id, backtest_result, spec, framework)

        # === Step 4c: Record experience (Phase 3) ===
        if self._experience:
            try:
                regime = self._current_regime
                await self._experience.record_experiment(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    framework=framework,
                    regime=regime.regime if regime else None,
                    adx=regime.adx if regime else None,
                    atr_pct=regime.atr_pct if regime else None,
                    profit_factor=backtest_result.profit_factor,
                    max_drawdown_pct=backtest_result.max_drawdown_pct,
                    recovery_factor=backtest_result.recovery_factor,
                    total_trades=backtest_result.total_trades,
                    meets_all_targets=backtest_result.meets_all_targets,
                    strategy_version=str(config.version),
                    parameter_set={
                        "risk_percent": config.risk_percent,
                        "stop_loss_pips": config.stop_loss_pips,
                        "take_profit_pips": config.take_profit_pips,
                        "ema_period": config.ema_period,
                        "rsi_period": config.rsi_period,
                    },
                )
            except Exception as e:
                logger.warning("Experience recording failed (non-fatal): %s", e)

        # === Step 4b: Walk-Forward Validation (if enabled + result is promising) ===
        wf_report = None
        if (
            self._wf_enabled
            and not self.dry_run
            and backtest_result.profit_factor is not None
            and backtest_result.profit_factor >= 1.3          # Champion tier triggers walk-forward
        ):
            wf_report = await self._run_walk_forward(
                backtest_result, generated, config
            )
            if wf_report is not None and not wf_report.is_robust:
                logger.warning(
                    "[WalkForward] v%s REJECTED as curve-fitted: %s",
                    config.version, wf_report.rejection_reason
                )
                # Save rejection to history for learning, then continue loop
                self._history.append({
                    "iteration": iteration + 1,
                    "version": backtest_result.strategy_version,
                    "profit_factor": backtest_result.profit_factor,
                    "max_drawdown_pct": backtest_result.max_drawdown_pct,
                    "recovery_factor": backtest_result.recovery_factor,
                    "avg_win_loss_ratio": backtest_result.avg_win_loss_ratio,
                    "meets_all_targets": False,
                    "wf_rejected": True,
                    "wf_reason": wf_report.rejection_reason,
                })
                new_config = self.strategy_improver.improve(
                    await asyncio.to_thread(self.result_analyzer.analyze, backtest_result, history[-5:] if history else None),
                    config, use_llm=self.use_llm
                )
                return backtest_result, new_config

        # === Step 5: Promote champion (database-backed) ===
        promoted = self.champion_manager.promote_if_better(backtest_result, self.symbol)
        if promoted:
            # Update session tracking
            self._champion_pf = backtest_result.profit_factor
            self._champion_version = str(config.version)
            self._champion_path = generated.file_path
            # Also write local champion file for backwards compatibility
            self._promote_champion(config, generated, backtest_result)
            # Notify MultiSymbolOrchestrator so it can deploy to forward test
            if self._on_champion_callback is not None:
                await self._on_champion_callback(
                    self.symbol,
                    backtest_result,
                    generated.file_path,
                )

        # === Step 6: Analyze ===
        logger.info("[4/5] Analyzing result...")
        if self._llm_semaphore is not None:
            async with self._llm_semaphore:
                analysis = await asyncio.to_thread(
                    self.result_analyzer.analyze, backtest_result, history[-5:] if history else None
                )
        else:
            analysis = self.result_analyzer.analyze(backtest_result, history[-5:] if history else None)
        async with get_session() as session:
            await self._save_analysis(session, db_run.id, analysis)
        logger.info("  Summary: %s", analysis.summary[:100] if analysis.summary else "n/a")

        # === Step 7: Improve ===
        logger.info("[5/5] Generating improved config...")
        if self._llm_semaphore is not None:
            async with self._llm_semaphore:
                new_config = await asyncio.to_thread(
                    self.strategy_improver.improve, analysis, config, self.use_llm
                )
        else:
            new_config = self.strategy_improver.improve(
                analysis, config, use_llm=self.use_llm
            )
        logger.info(
            "  v%s → v%s  changes: %s",
            config.version,
            new_config.version,
            list(new_config.change_rationale.keys()),
        )

        return backtest_result, new_config

    # ------------------------------------------------------------------
    # Champion promotion
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Walk-Forward Validation
    # ------------------------------------------------------------------

    async def _run_walk_forward(self, backtest_result, generated, config):
        """Run walk-forward + capital range + multi-TF validation. Returns WalkForwardReport or None."""
        from core.walk_forward import WalkForwardValidator
        from agents.report_parser import ReportParser
        from core.database import WalkForwardRun
        from sqlalchemy.orm import Session

        try:
            if self._wf_validator is None:
                self._wf_validator = WalkForwardValidator(
                    backtest_runner=self.backtest_runner,
                    report_parser_cls=ReportParser,
                )

            logger.info("[WalkForward] Starting validation for v%s...", config.version)

            # 1. Walk-forward windows
            wf_report = await asyncio.to_thread(
                self._wf_validator.run,
                generated.file_path,
                self.symbol,
                self.timeframe,
                self.initial_capital,
                str(config.version),
                backtest_result.profit_factor or 0,
                self._wf_n_windows,
                self._wf_train_months,
                self._wf_test_months,
            )

            # 2. Capital range test
            if wf_report.is_robust:
                cap_results = await asyncio.to_thread(
                    self._wf_validator.run_capital_range,
                    generated.file_path,
                    self.symbol,
                    self.timeframe,
                    str(config.version),
                    self.date_from,
                    self.date_to,
                    self._wf_capital_ranges,
                )
                wf_report.capital_range_results = cap_results
                logger.info("[WalkForward] Capital range: %s", cap_results)

            # 3. Multi-TF test
            if wf_report.is_robust and len(self._wf_timeframes) > 1:
                tf_results = await asyncio.to_thread(
                    self._wf_validator.run_multi_timeframe,
                    generated.file_path,
                    self.symbol,
                    self.initial_capital,
                    str(config.version),
                    self.date_from,
                    self.date_to,
                    self._wf_timeframes,
                )
                wf_report.timeframe_results = tf_results
                logger.info("[WalkForward] Multi-TF: %s", tf_results)

            # 4. Save to DB
            from sqlalchemy import create_engine
            db_url = cfg.get('database', {}).get('url')  # Fix: get db_url from config, not manager
            if db_url:
                sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
                engine = create_engine(sync_url)
                with Session(engine) as session:
                    row = WalkForwardRun(
                        strategy_version=str(config.version),
                        symbol=self.symbol,
                        timeframe=self.timeframe,
                        initial_capital=self.initial_capital,
                        full_period_pf=backtest_result.profit_factor or 0,
                        n_windows=wf_report.windows_total,
                        windows_passed=wf_report.windows_passed,
                        mean_pf=wf_report.mean_pf,
                        min_pf=wf_report.min_pf,
                        max_pf=wf_report.max_pf,
                        pf_std=wf_report.pf_std,
                        pf_degradation=wf_report.pf_degradation,
                        mean_dd=wf_report.mean_dd,
                        is_robust=wf_report.is_robust,
                        rejection_reason=wf_report.rejection_reason,
                        capital_range_results=wf_report.capital_range_results or {},
                        timeframe_results=wf_report.timeframe_results or {},
                        window_details=[
                            {
                                "window": w.window_index,
                                "test_from": str(w.test_from),
                                "test_to": str(w.test_to),
                                "pf": w.test_profit_factor,
                                "dd": w.test_max_drawdown_pct,
                                "trades": w.test_total_trades,
                                "status": w.status,
                            }
                            for w in wf_report.windows
                        ],
                    )
                    session.add(row)
                    session.commit()

            return wf_report

        except Exception as e:
            logger.error("[WalkForward] Validation error (skipping): %s", e, exc_info=True)
            return None

    def _promote_champion(
        self,
        config: StrategyConfig,
        generated,
        result: BacktestResult,
    ) -> None:
        """Save the best-performing strategy as champion."""
        os.makedirs(CHAMPION_DIR, exist_ok=True)
        champion_file = os.path.join(CHAMPION_DIR, "champion.mq5")
        champion_meta = os.path.join(CHAMPION_DIR, "champion_meta.json")

        shutil.copy2(generated.file_path, champion_file)

        meta = {
            "version": str(config.version),
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown_pct,
            "recovery_factor": result.recovery_factor,
            "avg_win_loss_ratio": result.avg_win_loss_ratio,
            "meets_all_targets": result.meets_all_targets,
            "source_file": generated.file_path,
            "code_hash": generated.code_hash,
        }
        with open(champion_meta, 'w') as f:
            json.dump(meta, f, indent=2)

        prev = self._champion_pf
        self._champion_pf = result.profit_factor
        self._champion_version = str(config.version)
        self._champion_path = champion_file

        flag = "🏆" if result.meets_all_targets else "↑"
        logger.info(
            "%s New champion v%s: PF %.2f→%.2f (DD %.1f%% RF %.2f WL %.2f)",
            flag, config.version,
            prev, result.profit_factor,
            result.max_drawdown_pct,
            result.recovery_factor,
            result.avg_win_loss_ratio,
        )

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    async def _upsert_strategy(
        self,
        session: AsyncSession,
        config: StrategyConfig,
        code_hash: str,
        code_path: str,
        framework: Optional[str] = None,
    ) -> Strategy:
        """Insert or update strategy row."""
        from sqlalchemy import select
        version_str = str(config.version)

        result = await session.execute(
            select(Strategy).where(Strategy.version_str == version_str)
        )
        db_strat = result.scalar_one_or_none()

        if db_strat is None:
            db_strat = Strategy(
                version_str=version_str,
                config=config.model_dump(mode='json', exclude={'created_at'}),
                code_hash=code_hash,
                code_path=code_path,
                framework_type=framework or "base_ea",
                parent_id=None,
                change_rationale=config.change_rationale,
            )
            session.add(db_strat)
            await session.commit()
            await session.refresh(db_strat)

        return db_strat

    async def _save_backtest_run(
        self,
        session: AsyncSession,
        strategy_id: int,
        result: BacktestResult,
        spec: BacktestSpec,
        framework: Optional[str] = None,
    ) -> BacktestRun:
        """Insert a backtest_runs row."""
        run = BacktestRun(
            strategy_id=strategy_id,
            symbol=spec.symbol,
            timeframe=spec.timeframe,
            date_from=spec.date_from,
            date_to=spec.date_to,
            initial_capital=spec.initial_deposit,
            framework_type=framework or "base_ea",
            profit_factor=result.profit_factor,
            net_profit=result.net_profit,
            gross_profit=result.gross_profit,
            gross_loss=result.gross_loss,
            expected_payoff=result.expected_payoff,
            max_drawdown_pct=result.max_drawdown_pct,
            recovery_factor=result.recovery_factor,
            total_trades=result.total_trades,
            win_rate_pct=result.win_rate_pct,
            avg_win_usd=result.avg_win_usd,
            avg_loss_usd=result.avg_loss_usd,
            avg_win_loss_ratio=result.avg_win_loss_ratio,
            max_consecutive_losses=result.max_consecutive_losses,
            sharpe_ratio=result.sharpe_ratio,
            margin_level_min_pct=result.margin_level_min_pct,
            meets_pf_target=result.meets_pf_target,
            meets_dd_target=result.meets_dd_target,
            meets_rf_target=result.meets_rf_target,
            meets_rr_target=result.meets_rr_target,
            meets_all_targets=result.meets_all_targets,
            is_champion=(result.profit_factor == self._champion_pf),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run

    async def _save_analysis(
        self,
        session: AsyncSession,
        backtest_run_id: int,
        analysis,
    ) -> None:
        """Insert an analyses row."""
        from core.strategy_config import AnalysisReport
        row = Analysis(
            backtest_run_id=backtest_run_id,
            model_used=analysis.analysis_model,
            weaknesses_json=[w.model_dump() for w in analysis.weaknesses],
            recommendations_json=analysis.recommendations,
            summary=analysis.summary,
            raw_response=analysis.raw_llm_response,
        )
        session.add(row)
        await session.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_v3_baseline(self) -> StrategyConfig:
        """Load V3 baseline as starting config."""
        return StrategyConfig(
            version=StrategyVersion(major=0, minor=3, iteration=0),
            name="AureusV3_AI",
            symbol=self.symbol,
            timeframe=self.timeframe,
            magic_number=20260400,
            risk_percent=1.0,
            ema_period=200,
            rsi_period=14,
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            atr_period=14,
            atr_max_multiplier=1.5,
            stop_loss_pips=30,
            take_profit_pips=90,
            breakeven_pips=15,
            trailing_stop_pips=20,
            lookback_period=120,
            max_spread_pips=2.0,
        )

    def _log_metrics(self, result: BacktestResult) -> None:
        # Use Champion-tier targets for XAUUSD (PF>1.3, DD<30%, RF>1.0, W/L>1.5)
        targets = [
            ("PF",  result.profit_factor,      1.3,  ">", result.meets_champion),
            ("DD",  result.max_drawdown_pct,   30.0, "<", result.max_drawdown_pct < 30.0),
            ("RF",  result.recovery_factor,    1.0,  ">", result.recovery_factor > 1.0),
            ("W/L", result.avg_win_loss_ratio, 1.5,  ">", result.avg_win_loss_ratio > 1.5),
        ]
        parts = [
            f"{'✓' if ok else '✗'}{name}={val:.2f}(tgt{op}{tgt})"
            for name, val, tgt, op, ok in targets
        ]
        tier = "GOLD" if result.meets_gold else ("CHAMPION" if result.meets_champion else ("GATE" if result.meets_gate else "BELOW GATE"))
        logger.info("  Metrics: %s | Trades=%d | Tier=%s", "  ".join(parts), result.total_trades, tier)
