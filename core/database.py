"""SQLAlchemy ORM models and session management for Aureus AI Trading Bot."""

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
    """High-impact economic calendar events (ForexFactory)."""

    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)   # "USD", "EUR", etc.
    impact: Mapped[str] = mapped_column(String(10), nullable=False)    # "high", "medium", "low"
    event_name: Mapped[str] = mapped_column(String(256), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


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


async def get_session(db_url: Optional[str] = None) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a database session."""
    factory = get_session_factory(db_url)
    async with factory() as session:
        yield session


async def create_tables(db_url: Optional[str] = None) -> None:
    """Create all tables (use Alembic for production; this is for testing)."""
    engine = get_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
