"""SQLAlchemy ORM models and session management for Aureus AI Trading Bot."""

from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Optional, AsyncGenerator
from sqlalchemy import (
    Integer, String, Float, Boolean, DateTime, Date, Text, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import yaml
import os


def load_db_url() -> str:
    """Load database URL from config, swap to asyncpg driver."""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    url: str = cfg['database']['url']
    # Swap psycopg2 → asyncpg driver
    return url.replace("postgresql://", "postgresql+asyncpg://")


class Base(DeclarativeBase):
    pass


class Strategy(Base):
    """One row per unique strategy configuration."""

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_str: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)       # full StrategyConfig dict
    code_hash: Mapped[Optional[str]] = mapped_column(String(64))       # SHA-256 of .mq5 file
    code_path: Mapped[Optional[str]] = mapped_column(Text)
    framework_type: Mapped[Optional[str]] = mapped_column(String(50), default="base_ea")  # TrendFollowing, MeanReversion, etc
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("strategies.id"))
    change_rationale: Mapped[Optional[dict]] = mapped_column(JSONB)   # why params changed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    backtest_runs: Mapped[list["BacktestRun"]] = relationship("BacktestRun", back_populates="strategy")
    parent: Mapped[Optional["Strategy"]] = relationship("Strategy", remote_side=[id])


# GIN index on JSONB config for fast parameter queries
Index("idx_strategies_config", Strategy.config, postgresql_using="gin")


class BacktestRun(Base):
    """One row per MT5 backtest execution."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), nullable=False)

    # Test setup
    symbol: Mapped[str] = mapped_column(String(10), default="EURUSD")
    timeframe: Mapped[str] = mapped_column(String(5), default="H1")
    date_from: Mapped[Optional[date]] = mapped_column(Date)
    date_to: Mapped[Optional[date]] = mapped_column(Date)
    initial_capital: Mapped[float] = mapped_column(Float, default=1000.0)
    framework_type: Mapped[Optional[str]] = mapped_column(String(50))  # TrendFollowing, MeanReversion, etc

    # Edge metrics (profitability)
    profit_factor: Mapped[Optional[float]] = mapped_column(Float)
    net_profit: Mapped[Optional[float]] = mapped_column(Float)
    gross_profit: Mapped[Optional[float]] = mapped_column(Float)
    gross_loss: Mapped[Optional[float]] = mapped_column(Float)
    expected_payoff: Mapped[Optional[float]] = mapped_column(Float)

    # Survival metrics
    max_drawdown_pct: Mapped[Optional[float]] = mapped_column(Float)
    recovery_factor: Mapped[Optional[float]] = mapped_column(Float)

    # Trade statistics
    total_trades: Mapped[Optional[int]] = mapped_column(Integer)
    win_rate_pct: Mapped[Optional[float]] = mapped_column(Float)
    avg_win_usd: Mapped[Optional[float]] = mapped_column(Float)
    avg_loss_usd: Mapped[Optional[float]] = mapped_column(Float)
    avg_win_loss_ratio: Mapped[Optional[float]] = mapped_column(Float)
    max_consecutive_losses: Mapped[Optional[int]] = mapped_column(Integer)

    # Risk metrics
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(Float)
    margin_level_min_pct: Mapped[Optional[float]] = mapped_column(Float)

    # Target flags
    meets_pf_target: Mapped[bool] = mapped_column(Boolean, default=False)
    meets_dd_target: Mapped[bool] = mapped_column(Boolean, default=False)
    meets_rf_target: Mapped[bool] = mapped_column(Boolean, default=False)
    meets_rr_target: Mapped[bool] = mapped_column(Boolean, default=False)
    meets_all_targets: Mapped[bool] = mapped_column(Boolean, default=False)
    is_champion: Mapped[bool] = mapped_column(Boolean, default=False)

    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="backtest_runs")
    analyses: Mapped[list["Analysis"]] = relationship("Analysis", back_populates="backtest_run")


class Analysis(Base):
    """LLM analysis of a backtest run."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), nullable=False)
    model_used: Mapped[str] = mapped_column(String(64), default="llama3.2:3b")
    weaknesses_json: Mapped[Optional[dict]] = mapped_column(JSONB)     # list of Weakness dicts
    recommendations_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    raw_response: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    backtest_run: Mapped["BacktestRun"] = relationship("BacktestRun", back_populates="analyses")
    improvements: Mapped[list["Improvement"]] = relationship("Improvement", back_populates="analysis")


class Improvement(Base):
    """One parameter change proposal from StrategyImproverAgent."""

    __tablename__ = "improvements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    from_strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), nullable=False)
    to_strategy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("strategies.id"))
    improvement_type: Mapped[str] = mapped_column(String(32))  # "rule_based" | "llm"
    param_changes_json: Mapped[Optional[dict]] = mapped_column(JSONB)  # {param: {from, to, reason}}
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    analysis: Mapped["Analysis"] = relationship("Analysis", back_populates="improvements")


class NewsEvent(Base):
    """High-impact economic calendar events (MT5 calendar or ForexFactory fallback)."""

    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)   # "USD", "EUR"
    impact: Mapped[str] = mapped_column(String(10), nullable=False)    # "high", "medium", "low"
    event_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="MT5")     # "MT5" | "ForexFactory"
    actual: Mapped[Optional[float]] = mapped_column(Float)             # Reported actual value
    forecast: Mapped[Optional[float]] = mapped_column(Float)           # Analyst forecast
    previous: Mapped[Optional[float]] = mapped_column(Float)           # Prior release value
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    market_feedbacks: Mapped[list["EventMarketFeedback"]] = relationship(
        "EventMarketFeedback", back_populates="news_event"
    )


class EventMarketFeedback(Base):
    """
    Price reaction captured after each high-impact news event.

    Stored after the post-event window has elapsed so the system can learn:
    - Which events cause large pip moves (block longer)
    - Which events are benign (reduce block window)
    - Direction bias per event type (NFP → USD bullish, ECB rate cut → EUR bearish)
    - Whether the EA had open trades during the event (risk exposure)
    """

    __tablename__ = "event_market_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("news_events.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # "EURUSD"

    # Price snapshot: 1h before → at event → 1h after → 2h after
    price_1h_before: Mapped[Optional[float]] = mapped_column(Float)
    price_at_event:  Mapped[Optional[float]] = mapped_column(Float)
    price_1h_after:  Mapped[Optional[float]] = mapped_column(Float)
    price_2h_after:  Mapped[Optional[float]] = mapped_column(Float)

    # Movement metrics (positive = up, negative = down)
    pip_move_1h: Mapped[Optional[float]] = mapped_column(Float)   # pips from event to +1h
    pip_move_2h: Mapped[Optional[float]] = mapped_column(Float)   # pips from event to +2h
    pip_spike:   Mapped[Optional[float]] = mapped_column(Float)   # max abs pip move in 2h window

    # Directional outcome
    direction: Mapped[Optional[str]] = mapped_column(String(10))  # "bullish"|"bearish"|"choppy"

    # Volatility: ATR at event / ATR baseline (>1.5 = spike)
    volatility_ratio: Mapped[Optional[float]] = mapped_column(Float)

    # EA exposure during event
    open_positions_at_event: Mapped[int] = mapped_column(Integer, default=0)
    trades_blocked: Mapped[int] = mapped_column(Integer, default=0)  # signals suppressed

    # Context: which framework + regime was active
    framework_type: Mapped[Optional[str]] = mapped_column(String(50))
    market_regime:  Mapped[Optional[str]] = mapped_column(String(20))  # trending|choppy|ranging

    # Outcome flag: did blocking this event prevent a loss?
    news_block_was_protective: Mapped[Optional[bool]] = mapped_column(Boolean)

    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, index=True
    )

    # Relationships
    news_event: Mapped["NewsEvent"] = relationship("NewsEvent", back_populates="market_feedbacks")


class ScheduledRun(Base):
    """Scheduled/queued improvement loop runs (audit trail)."""

    __tablename__ = "scheduled_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)    # EURUSD, GBPUSD, etc.
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "cron", "manual", "news"
    trigger_reason: Mapped[str] = mapped_column(String(256), default="")
    iterations: Mapped[int] = mapped_column(Integer, nullable=False)   # Max iterations for this run
    variant_count: Mapped[Optional[int]] = mapped_column(Integer)      # If batch generation
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued, running, completed, failed
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Results (populated after run completes)
    final_champion_version: Mapped[Optional[str]] = mapped_column(String(64))
    final_profit_factor: Mapped[Optional[float]] = mapped_column(Float)
    final_max_drawdown_pct: Mapped[Optional[float]] = mapped_column(Float)


class RunTrigger(Base):
    """Audit trail for why each run was triggered."""

    __tablename__ = "run_triggers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scheduled_runs.id"), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String(256), default="")
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class GlobalChampion(Base):
    """Best-performing strategy per symbol (persistent across runs)."""

    __tablename__ = "global_champions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # EURUSD, GBPUSD
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)

    # Backtest metrics
    profit_factor: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    recovery_factor: Mapped[float] = mapped_column(Float, nullable=False)
    avg_win_loss_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    meets_all_targets: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# Phase 6+ Tables — Forward Test, Live Trading, Signals
# ---------------------------------------------------------------------------

class ForwardTestRun(Base):
    """Demo deployment of a champion strategy. One row per champion+symbol+deploy."""

    __tablename__ = "forward_test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("strategies.id"))
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    account_type: Mapped[str] = mapped_column(String(10), default="demo")   # "demo" | "real"
    ea_magic_number: Mapped[int] = mapped_column(Integer, nullable=False)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(20), default="running")      # running|promoted|failed|paused
    promotion_criteria: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Accumulating metrics (updated by ForwardTestManager)
    days_running: Mapped[int] = mapped_column(Integer, default=0)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    net_profit: Mapped[float] = mapped_column(Float, default=0.0)
    profit_factor: Mapped[Optional[float]] = mapped_column(Float)
    max_drawdown_pct: Mapped[Optional[float]] = mapped_column(Float)
    win_rate_pct: Mapped[Optional[float]] = mapped_column(Float)
    vs_backtest_pf_delta: Mapped[Optional[float]] = mapped_column(Float)    # live_pf - backtest_pf

    promoted_to_real: Mapped[bool] = mapped_column(Boolean, default=False)
    promoted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    live_trades: Mapped[list["LiveTrade"]] = relationship("LiveTrade", back_populates="forward_test_run")


class LiveTrade(Base):
    """Every individual trade on demo or real account, polled via REST bridge."""

    __tablename__ = "live_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forward_test_id: Mapped[Optional[int]] = mapped_column(ForeignKey("forward_test_runs.id"))
    ticket: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    account_type: Mapped[str] = mapped_column(String(10), default="demo")
    magic_number: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String(5), nullable=False)      # "buy" | "sell"
    open_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    close_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    open_price: Mapped[Optional[float]] = mapped_column(Float)
    close_price: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[float]] = mapped_column(Float)
    sl: Mapped[Optional[float]] = mapped_column(Float)
    tp: Mapped[Optional[float]] = mapped_column(Float)
    profit_usd: Mapped[Optional[float]] = mapped_column(Float)
    commission: Mapped[Optional[float]] = mapped_column(Float)
    swap: Mapped[Optional[float]] = mapped_column(Float)
    pips: Mapped[Optional[float]] = mapped_column(Float)
    news_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    signal_regime: Mapped[Optional[str]] = mapped_column(String(20))        # trending|ranging|volatile
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    forward_test_run: Mapped[Optional["ForwardTestRun"]] = relationship("ForwardTestRun", back_populates="live_trades")


class SignalSnapshot(Base):
    """Periodic technical regime snapshots from SignalAgent."""

    __tablename__ = "signal_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(5), default="H1")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    ema200_price: Mapped[Optional[float]] = mapped_column(Float)
    close_price: Mapped[Optional[float]] = mapped_column(Float)
    trend_direction: Mapped[Optional[str]] = mapped_column(String(10))      # bullish|bearish|neutral
    rsi_value: Mapped[Optional[float]] = mapped_column(Float)
    atr_value: Mapped[Optional[float]] = mapped_column(Float)
    atr_percentile: Mapped[Optional[float]] = mapped_column(Float)
    regime: Mapped[Optional[str]] = mapped_column(String(20))               # trending|ranging|volatile
    regime_confidence: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20), default="bridge_poll")


class ChampionPromotion(Base):
    """Full audit trail of every promotion: backtest → forward test → real trading."""

    __tablename__ = "champion_promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("strategies.id"))
    backtest_pf: Mapped[Optional[float]] = mapped_column(Float)
    backtest_dd: Mapped[Optional[float]] = mapped_column(Float)
    forward_test_id: Mapped[Optional[int]] = mapped_column(ForeignKey("forward_test_runs.id"))
    forward_pf: Mapped[Optional[float]] = mapped_column(Float)
    forward_dd: Mapped[Optional[float]] = mapped_column(Float)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)          # backtest_champion|forward_test|real_trading
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    promoted_by: Mapped[str] = mapped_column(String(20), default="auto")    # auto|manual


# ---------------------------------------------------------------------------
# Phase 7: Walk-Forward & Robustness Validation Tables
# ---------------------------------------------------------------------------

class WalkForwardRun(Base):
    """Summary of a walk-forward validation run for a champion strategy."""

    __tablename__ = "walk_forward_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("strategies.id"))
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(5), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False)
    full_period_pf: Mapped[float] = mapped_column(Float, nullable=False)  # Original backtest PF

    # Aggregate walk-forward stats
    n_windows: Mapped[int] = mapped_column(Integer, default=0)
    windows_passed: Mapped[int] = mapped_column(Integer, default=0)
    mean_pf: Mapped[Optional[float]] = mapped_column(Float)
    min_pf: Mapped[Optional[float]] = mapped_column(Float)
    max_pf: Mapped[Optional[float]] = mapped_column(Float)
    pf_std: Mapped[Optional[float]] = mapped_column(Float)
    pf_degradation: Mapped[Optional[float]] = mapped_column(Float)  # full_pf - mean_wf_pf
    mean_dd: Mapped[Optional[float]] = mapped_column(Float)

    # Gate result
    is_robust: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)

    # Capital range results {capital: pf}
    capital_range_results: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Multi-TF results {timeframe: pf}
    timeframe_results: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Per-window detail [{window_index, test_from, test_to, pf, dd, trades, status}]
    window_details: Mapped[Optional[dict]] = mapped_column(JSONB)

    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Phase 3: Experience Database Tables
# ---------------------------------------------------------------------------

class FrameworkExperiment(Base):
    """
    One row per backtest run — records which framework was used,
    what the market regime was, and what result it got.
    This is the raw training data for the experience system.
    """
    __tablename__ = "framework_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(5), nullable=False)
    framework_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    market_regime: Mapped[Optional[str]] = mapped_column(String(20))      # trending/choppy/ranging/volatile
    adx: Mapped[Optional[float]] = mapped_column(Float)
    atr_pct: Mapped[Optional[float]] = mapped_column(Float)               # ATR as % of price
    profit_factor: Mapped[Optional[float]] = mapped_column(Float)
    max_drawdown_pct: Mapped[Optional[float]] = mapped_column(Float)
    recovery_factor: Mapped[Optional[float]] = mapped_column(Float)
    total_trades: Mapped[Optional[int]] = mapped_column(Integer)
    meets_all_targets: Mapped[bool] = mapped_column(Boolean, default=False)
    strategy_version: Mapped[Optional[str]] = mapped_column(String(32))
    parameter_set: Mapped[Optional[dict]] = mapped_column(JSONB)          # key params used
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class FrameworkPerformance(Base):
    """
    Aggregate statistics per (symbol, framework_type, market_regime).
    Updated after each experiment — used to pick the best next framework.
    """
    __tablename__ = "framework_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    framework_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    market_regime: Mapped[Optional[str]] = mapped_column(String(20), index=True)  # None = overall

    # Aggregate stats
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    champion_runs: Mapped[int] = mapped_column(Integer, default=0)        # runs that met all targets
    avg_profit_factor: Mapped[Optional[float]] = mapped_column(Float)
    best_profit_factor: Mapped[Optional[float]] = mapped_column(Float)
    avg_drawdown_pct: Mapped[Optional[float]] = mapped_column(Float)
    success_rate_pct: Mapped[Optional[float]] = mapped_column(Float)       # champion_runs / total_runs * 100
    recommended: Mapped[bool] = mapped_column(Boolean, default=True)       # false = blacklisted

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


# Composite unique index: one row per (symbol, framework, regime)
Index("idx_fw_perf_unique", FrameworkPerformance.symbol,
      FrameworkPerformance.framework_type, FrameworkPerformance.market_regime, unique=True)


class MarketSnapshot(Base):
    """
    Periodic snapshots of market conditions per symbol.
    Used to detect current regime (trending/choppy/ranging/volatile)
    and to match against which frameworks historically worked.
    """
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(5), nullable=False)
    regime: Mapped[str] = mapped_column(String(20), nullable=False)       # trending/choppy/ranging/volatile
    adx: Mapped[Optional[float]] = mapped_column(Float)
    atr: Mapped[Optional[float]] = mapped_column(Float)
    atr_pct: Mapped[Optional[float]] = mapped_column(Float)               # ATR / price * 100
    ema_slope: Mapped[Optional[float]] = mapped_column(Float)             # positive = uptrend
    rsi: Mapped[Optional[float]] = mapped_column(Float)
    best_framework: Mapped[Optional[str]] = mapped_column(String(50))     # historically best for this regime
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)


class Pair(Base):
    """
    Pair metadata loaded from pairs.yaml — characteristics, constraints, trading properties.
    Enables dynamic symbol management without hardcoding.
    """
    __tablename__ = "pairs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)  # EURUSD, GBPUSD, etc.

    # Leverage and spread
    broker_leverage: Mapped[str] = mapped_column(String(20), default="1:2000")
    typical_spread_pips: Mapped[float] = mapped_column(Float, nullable=False)

    # Volatility
    typical_volatility_pips_h1: Mapped[float] = mapped_column(Float, nullable=False)

    # Market hours
    trading_hours: Mapped[str] = mapped_column(String(50), default="Unknown")  # Asia+London+NY or 24/5

    # Correlation
    correlation_vs_eurusd: Mapped[float] = mapped_column(Float, default=0.0)

    # Metadata
    description: Mapped[str] = mapped_column(Text, default="")
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)

    # Tracking
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

_engine = None
_session_factory = None


def get_engine(db_url: Optional[str] = None):
    global _engine
    if _engine is None:
        url = db_url or load_db_url()
        _engine = create_async_engine(url, pool_size=5, echo=False)
    return _engine


def get_session_factory(db_url: Optional[str] = None) -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        engine = get_engine(db_url)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return _session_factory


@asynccontextmanager
async def get_session(db_url: Optional[str] = None):
    """Async context manager yielding a database session."""
    factory = get_session_factory(db_url)
    async with factory() as session:
        yield session


async def create_tables(db_url: Optional[str] = None) -> None:
    """Create all tables (use Alembic for production; this is for testing)."""
    engine = get_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def load_pairs_into_db(db_url: Optional[str] = None) -> None:
    """Load all pairs from pairs.yaml into the pairs table."""
    pairs_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'pairs.yaml')
    with open(pairs_path) as f:
        cfg = yaml.safe_load(f)

    pairs_data = cfg.get('pairs', {})
    async with get_session(db_url) as session:
        from sqlalchemy import delete
        # Clear existing pairs
        await session.execute(delete(Pair))
        await session.commit()

        # Insert from pairs.yaml
        for symbol, meta in pairs_data.items():
            pair = Pair(
                symbol=symbol,
                broker_leverage=meta.get('broker_leverage', '1:2000'),
                typical_spread_pips=meta.get('typical_spread_pips', 0.0),
                typical_volatility_pips_h1=meta.get('typical_volatility_pips_h1', 0.0),
                trading_hours=meta.get('trading_hours', 'Unknown'),
                correlation_vs_eurusd=meta.get('correlation', 0.0),
                description=meta.get('description', ''),
                recommended=meta.get('recommended', False),
            )
            session.add(pair)

        await session.commit()
