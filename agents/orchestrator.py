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
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from core.strategy_config import StrategyConfig, StrategyVersion, BacktestResult
from core.database import Strategy, BacktestRun, Analysis, Improvement, get_session
from core.constraint_validator import ConstraintViolation
from core.champion_manager import ChampionManager
from core.ollama_client import OllamaClient
from agents.code_generator import CodeGeneratorAgent
from agents.backtest_runner import BacktestRunnerAgent, BacktestSpec
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
    ) -> None:
        cfg = config_override or _load_config()
        proj = cfg.get('project', {})

        self.max_iterations: int = max_iterations or proj.get('max_iterations', 50)
        self.dry_run = dry_run
        self.dry_run_fixture = dry_run_fixture
        self.use_llm = use_llm

        self.symbol: str = proj.get('symbol', 'EURUSD')
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

        # Champion manager (database-backed, per-symbol)
        db_url = cfg.get('database', {}).get('url')
        self.champion_manager = ChampionManager(db_url)

        # Tracking
        # Load global champion for this symbol (or start fresh if none exists)
        global_champ = self.champion_manager.get_global_champion(self.symbol)
        self._champion_pf: float = global_champ['profit_factor'] if global_champ else 0.0
        self._champion_version: Optional[str] = global_champ['version'] if global_champ else None
        self._champion_path: Optional[str] = global_champ['file_path'] if global_champ else None
        self._history: list[dict] = []

        logger.info(
            "Initialized OrchestratorAgent for %s: global champion PF=%.2f (v%s)",
            self.symbol, self._champion_pf, self._champion_version or "none"
        )

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

        return LoopResult(
            iterations_run=len(self._history),
            champion_version=self._champion_version,
            champion_pf=self._champion_pf,
            champion_path=self._champion_path,
            all_targets_met=any(h["meets_all_targets"] for h in self._history),
            history=self._history,
        )

    # ------------------------------------------------------------------
    # Single iteration
    # ------------------------------------------------------------------

    async def _run_one_iteration(
        self,
        config: StrategyConfig,
        iteration: int,
        history: list[BacktestResult],
    ) -> Optional[tuple[BacktestResult, StrategyConfig]]:
        """Run one full Generate → Test → Parse → Analyze → Improve cycle."""

        # === Step 1: Generate ===
        logger.info("[1/5] Generating MQL5 code for v%s...", config.version)
        generated = self.code_gen.generate(config)  # Raises ConstraintViolation if fails
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
        )

        if self.dry_run:
            run_result = self.backtest_runner.dry_run(spec, self.dry_run_fixture)
        else:
            run_result = self.backtest_runner.run(spec)  # Can raise TimeoutError

        logger.info("  Report: %s (%.1fs)", run_result.report_html_path, run_result.duration_seconds)

        # === Step 3: Parse ===
        logger.info("[3/5] Parsing report...")
        backtest_result = ReportParser.parse(run_result.report_html_path)
        backtest_result.strategy_version = str(config.version)
        backtest_result.check_targets()
        self._log_metrics(backtest_result)

        # === Step 4: Save to database ===
        async with get_session() as session:
            db_strategy = await self._upsert_strategy(session, config, generated.code_hash, generated.file_path)
            db_run = await self._save_backtest_run(session, db_strategy.id, backtest_result, spec)

        # === Step 5: Promote champion (database-backed) ===
        promoted = self.champion_manager.promote_if_better(backtest_result, self.symbol)
        if promoted:
            # Update session tracking
            self._champion_pf = backtest_result.profit_factor
            self._champion_version = str(config.version)
            self._champion_path = generated.file_path
            # Also write local champion file for backwards compatibility
            self._promote_champion(config, generated, backtest_result)

        # === Step 6: Analyze ===
        logger.info("[4/5] Analyzing result...")
        analysis = self.result_analyzer.analyze(backtest_result, history[-5:] if history else None)
        async with get_session() as session:
            await self._save_analysis(session, db_run.id, analysis)
        logger.info("  Summary: %s", analysis.summary[:100] if analysis.summary else "n/a")

        # === Step 7: Improve ===
        logger.info("[5/5] Generating improved config...")
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
            "promoted_at": datetime.utcnow().isoformat(),
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
    ) -> BacktestRun:
        """Insert a backtest_runs row."""
        run = BacktestRun(
            strategy_id=strategy_id,
            symbol=spec.symbol,
            timeframe=spec.timeframe,
            date_from=spec.date_from,
            date_to=spec.date_to,
            initial_capital=spec.initial_deposit,
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
        targets = [
            ("PF",  result.profit_factor,      1.5,  ">", result.meets_pf_target),
            ("DD",  result.max_drawdown_pct,   15.0, "<", result.meets_dd_target),
            ("RF",  result.recovery_factor,    3.0,  ">", result.meets_rf_target),
            ("W/L", result.avg_win_loss_ratio, 2.0,  ">", result.meets_rr_target),
        ]
        parts = [
            f"{'✓' if ok else '✗'}{name}={val:.2f}(tgt{op}{tgt})"
            for name, val, tgt, op, ok in targets
        ]
        logger.info("  Metrics: %s | Trades=%d", "  ".join(parts), result.total_trades)
