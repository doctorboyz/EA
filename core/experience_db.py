"""
ExperienceDB — Read/write helpers for the Phase 3 learning system.

Responsibilities:
  1. Record every framework experiment after backtest
  2. Update aggregate FrameworkPerformance stats
  3. Query: "what's the best framework to try next for this symbol/regime?"
  4. Exploration vs exploitation: 80% pick best known, 20% random explore

Usage:
    exp = ExperienceDB(db_url)

    # After each backtest
    await exp.record_experiment(symbol, framework, regime_snapshot, backtest_result)

    # Before next generation
    best = await exp.pick_framework(symbol, current_regime, all_frameworks)
    # → "MeanReversion"
"""

import logging
import random
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import FrameworkExperiment, FrameworkPerformance, MarketSnapshot

logger = logging.getLogger(__name__)

# Shared async engine — one pool across all ExperienceDB instances
_shared_async_engine = None
_shared_async_session = None

def _get_async_session(db_url: str):
    global _shared_async_engine, _shared_async_session
    if _shared_async_engine is None:
        if "postgresql://" in db_url and "+asyncpg" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        _shared_async_engine = create_async_engine(db_url, pool_size=3, max_overflow=2, echo=False)
        _shared_async_session = async_sessionmaker(_shared_async_engine, expire_on_commit=False)
    return _shared_async_session

# 80% exploit best known, 20% explore random
EXPLOIT_RATIO = 0.80

# Minimum experiments before we trust the stats
MIN_EXPERIMENTS_FOR_TRUST = 3


class ExperienceDB:
    """
    Async read/write interface for the experience learning system.
    All methods are async — call with await.
    """

    def __init__(self, db_url: str):
        self._session = _get_async_session(db_url)

    # ─── Record experiment ────────────────────────────────────────────────────

    async def record_experiment(
        self,
        symbol: str,
        timeframe: str,
        framework: str,
        regime: Optional[str],
        adx: Optional[float],
        atr_pct: Optional[float],
        profit_factor: Optional[float],
        max_drawdown_pct: Optional[float],
        recovery_factor: Optional[float],
        total_trades: Optional[int],
        meets_all_targets: bool,
        strategy_version: Optional[str] = None,
        parameter_set: Optional[dict] = None,
    ) -> None:
        """Save one experiment row and update aggregate performance stats."""
        async with self._session() as session:
            # Insert raw experiment
            exp = FrameworkExperiment(
                symbol=symbol,
                timeframe=timeframe,
                framework_type=framework,
                market_regime=regime,
                adx=adx,
                atr_pct=atr_pct,
                profit_factor=profit_factor,
                max_drawdown_pct=max_drawdown_pct,
                recovery_factor=recovery_factor,
                total_trades=total_trades,
                meets_all_targets=meets_all_targets,
                strategy_version=strategy_version,
                parameter_set=parameter_set,
            )
            session.add(exp)
            await session.flush()

            # Update aggregate performance (upsert)
            await self._update_performance(session, symbol, framework, regime,
                                           profit_factor, meets_all_targets)
            await session.commit()

        logger.debug("[Experience] Recorded %s/%s framework=%s regime=%s PF=%.2f meets=%s",
                    symbol, timeframe, framework, regime, profit_factor or 0, meets_all_targets)

    async def _update_performance(
        self,
        session: AsyncSession,
        symbol: str,
        framework: str,
        regime: Optional[str],
        profit_factor: Optional[float],
        meets_all_targets: bool,
    ) -> None:
        """Upsert aggregate row in framework_performance."""
        # Try to fetch existing row
        result = await session.execute(
            select(FrameworkPerformance).where(
                FrameworkPerformance.symbol == symbol,
                FrameworkPerformance.framework_type == framework,
                FrameworkPerformance.market_regime == regime,
            )
        )
        row = result.scalar_one_or_none()

        if row is None:
            row = FrameworkPerformance(
                symbol=symbol,
                framework_type=framework,
                market_regime=regime,
                total_runs=0,
                champion_runs=0,
                avg_profit_factor=profit_factor,
                best_profit_factor=profit_factor,
                avg_drawdown_pct=None,
                success_rate_pct=0.0,
                recommended=True,
            )
            session.add(row)

        row.total_runs += 1
        if meets_all_targets:
            row.champion_runs += 1
        if profit_factor is not None:
            if row.avg_profit_factor is None:
                row.avg_profit_factor = profit_factor
            else:
                # Running average
                row.avg_profit_factor = (
                    row.avg_profit_factor * (row.total_runs - 1) + profit_factor
                ) / row.total_runs
            if row.best_profit_factor is None or profit_factor > row.best_profit_factor:
                row.best_profit_factor = profit_factor

        row.success_rate_pct = (row.champion_runs / row.total_runs * 100) if row.total_runs > 0 else 0.0

    # ─── Pick next framework ──────────────────────────────────────────────────

    async def pick_framework(
        self,
        symbol: str,
        regime: Optional[str],
        all_frameworks: list[str],
        exploration_ratio: float = 1 - EXPLOIT_RATIO,
    ) -> str:
        """
        Intelligently pick the next framework to try.

        Strategy:
          - 80% of the time: pick framework with highest success_rate (exploit)
          - 20% of the time: pick a random untried/underexplored framework (explore)
          - If no data yet: rotate through all_frameworks sequentially

        Returns framework name string.
        """
        if random.random() < exploration_ratio:
            choice = random.choice(all_frameworks)
            logger.info("[Experience] %s: EXPLORE → %s (random 20%%)", symbol, choice)
            return choice

        # Exploit: query best performing
        best = await self._query_best_framework(symbol, regime, all_frameworks)
        if best:
            logger.info("[Experience] %s regime=%s: EXPLOIT → %s (best known)", symbol, regime, best)
            return best

        # Fallback: random (no data yet)
        choice = random.choice(all_frameworks)
        logger.info("[Experience] %s: no data yet → random %s", symbol, choice)
        return choice

    async def _query_best_framework(
        self,
        symbol: str,
        regime: Optional[str],
        allowed: list[str],
    ) -> Optional[str]:
        """Query framework_performance for the best performing framework."""
        async with self._session() as session:
            # Try regime-specific first, fall back to overall
            for regime_filter in [regime, None]:
                result = await session.execute(
                    select(FrameworkPerformance)
                    .where(
                        FrameworkPerformance.symbol == symbol,
                        FrameworkPerformance.market_regime == regime_filter,
                        FrameworkPerformance.framework_type.in_(allowed),
                        FrameworkPerformance.recommended == True,
                        FrameworkPerformance.total_runs >= MIN_EXPERIMENTS_FOR_TRUST,
                    )
                    .order_by(
                        FrameworkPerformance.success_rate_pct.desc(),
                        FrameworkPerformance.avg_profit_factor.desc(),
                    )
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                if row:
                    return row.framework_type

        return None

    # ─── Save market snapshot ─────────────────────────────────────────────────

    async def save_market_snapshot(
        self,
        symbol: str,
        timeframe: str,
        regime: str,
        adx: Optional[float] = None,
        atr: Optional[float] = None,
        atr_pct: Optional[float] = None,
        ema_slope: Optional[float] = None,
        rsi: Optional[float] = None,
        best_framework: Optional[str] = None,
    ) -> None:
        """Save a market regime snapshot."""
        async with self._session() as session:
            snap = MarketSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                regime=regime,
                adx=adx,
                atr=atr,
                atr_pct=atr_pct,
                ema_slope=ema_slope,
                rsi=rsi,
                best_framework=best_framework,
            )
            session.add(snap)
            await session.commit()

    # ─── Analytics queries ────────────────────────────────────────────────────

    async def get_framework_leaderboard(
        self,
        symbol: str,
        regime: Optional[str] = None,
    ) -> list[dict]:
        """
        Return ranked frameworks by success rate for given symbol/regime.
        Used by dashboard to show which strategies work best.
        """
        async with self._session() as session:
            q = select(FrameworkPerformance).where(
                FrameworkPerformance.symbol == symbol,
                FrameworkPerformance.market_regime == regime,
            ).order_by(FrameworkPerformance.success_rate_pct.desc())
            result = await session.execute(q)
            rows = result.scalars().all()

        return [
            {
                "framework": r.framework_type,
                "regime": r.market_regime,
                "total_runs": r.total_runs,
                "champion_runs": r.champion_runs,
                "success_rate_pct": r.success_rate_pct,
                "avg_pf": r.avg_profit_factor,
                "best_pf": r.best_profit_factor,
                "recommended": r.recommended,
            }
            for r in rows
        ]

    async def get_total_experiments(self, symbol: str) -> int:
        """Total experiments recorded for a symbol."""
        async with self._session() as session:
            result = await session.execute(
                select(func.count()).select_from(FrameworkExperiment).where(
                    FrameworkExperiment.symbol == symbol
                )
            )
            return result.scalar_one() or 0

    async def blacklist_framework(self, symbol: str, framework: str, regime: Optional[str] = None):
        """Mark a framework as not recommended for this symbol/regime."""
        async with self._session() as session:
            await session.execute(
                update(FrameworkPerformance)
                .where(
                    FrameworkPerformance.symbol == symbol,
                    FrameworkPerformance.framework_type == framework,
                    FrameworkPerformance.market_regime == regime,
                )
                .values(recommended=False)
            )
            await session.commit()
        logger.warning("[Experience] Blacklisted %s for %s regime=%s", framework, symbol, regime)
