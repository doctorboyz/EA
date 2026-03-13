"""Pydantic models for strategy configuration. All parameter bounds enforced here."""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class StrategyVersion(BaseModel):
    """Version tracking: major.minor.iteration"""
    major: int = 0
    minor: int
    iteration: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.iteration}"

    def bump_iteration(self) -> "StrategyVersion":
        return StrategyVersion(major=self.major, minor=self.minor, iteration=self.iteration + 1)

    def bump_minor(self) -> "StrategyVersion":
        return StrategyVersion(major=self.major, minor=self.minor + 1, iteration=0)


class StrategyConfig(BaseModel):
    """Master configuration for a trading strategy. Used to generate MQL5 code."""

    # Metadata
    version: StrategyVersion
    name: str = Field(default="AureusV3")
    symbol: str = Field(default="EURUSD", pattern="^[A-Z]{6}$")
    timeframe: str = Field(default="H1")
    magic_number: int = Field(default=20260400, ge=1, le=2147483647)

    # Risk Management - ALWAYS percentage, NEVER fixed USD (V4 failure guard)
    risk_percent: float = Field(default=1.0, ge=0.5, le=2.0)

    # Core Indicators
    ema_period: int = Field(default=200, ge=150, le=200)
    rsi_period: int = Field(default=14, ge=7, le=21)
    rsi_oversold: float = Field(default=30.0, ge=20.0, le=35.0)
    rsi_overbought: float = Field(default=70.0, ge=65.0, le=80.0)
    atr_period: int = Field(default=14, ge=10, le=21)
    atr_max_multiplier: float = Field(default=1.5, ge=1.0, le=3.0)

    # Trade Management
    stop_loss_pips: int = Field(default=30, ge=20, le=60)
    take_profit_pips: int = Field(default=90, ge=60, le=150)
    breakeven_pips: int = Field(default=15, ge=10, le=30)
    trailing_stop_pips: int = Field(default=20, ge=10, le=40)
    lookback_period: int = Field(default=120, ge=48, le=240)
    max_spread_pips: float = Field(default=2.0, ge=1.0, le=3.0)

    # Optional Advanced Filters
    use_adx_filter: bool = Field(default=False)
    adx_min_strength: Optional[int] = Field(default=None, ge=15, le=35)
    use_h4_filter: bool = Field(default=False)
    h4_ema_period: Optional[int] = Field(default=None, ge=30, le=100)

    # News Filter
    news_block_hours: List[str] = Field(default_factory=list)  # ISO datetime strings of blocked hours

    # Metadata
    parent_version: Optional[str] = None
    change_rationale: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator('take_profit_pips')
    @classmethod
    def tp_must_be_2x_sl(cls, v: int, info) -> int:
        """Enforce minimum 2:1 R/R ratio."""
        if 'stop_loss_pips' in info.data and v < info.data['stop_loss_pips'] * 2:
            raise ValueError(
                f"TP ({v}) must be >= 2x SL ({info.data['stop_loss_pips']}). "
                f"Got {v / info.data['stop_loss_pips']:.1f}:1 ratio."
            )
        return v

    @field_validator('rsi_oversold')
    @classmethod
    def rsi_oversold_max(cls, v: float) -> float:
        """V4 failed with 35/65. Clamp to 30/70 range."""
        if v > 35.0:
            return 35.0
        return v

    @field_validator('rsi_overbought')
    @classmethod
    def rsi_overbought_min(cls, v: float) -> float:
        """V4 failed with 35/65. Clamp to 30/70 range."""
        if v < 65.0:
            return 65.0
        return v

    @model_validator(mode='after')
    def rsi_no_cross(self) -> "StrategyConfig":
        """Ensure oversold < overbought."""
        if self.rsi_oversold >= self.rsi_overbought:
            raise ValueError(
                f"RSI oversold ({self.rsi_oversold}) must be < overbought ({self.rsi_overbought})"
            )
        return self

    @model_validator(mode='after')
    def breakeven_less_than_tp(self) -> "StrategyConfig":
        """Breakeven must be before TP."""
        if self.breakeven_pips >= self.take_profit_pips:
            raise ValueError(
                f"Breakeven ({self.breakeven_pips}) must be < TP ({self.take_profit_pips})"
            )
        return self

    @model_validator(mode='after')
    def adx_filter_coherence(self) -> "StrategyConfig":
        """If ADX filter enabled, adx_min_strength must be set."""
        if self.use_adx_filter and self.adx_min_strength is None:
            raise ValueError("adx_min_strength required when use_adx_filter=True")
        if not self.use_adx_filter and self.adx_min_strength is not None:
            self.adx_min_strength = None
        return self

    @model_validator(mode='after')
    def h4_filter_coherence(self) -> "StrategyConfig":
        """If H4 filter enabled, h4_ema_period must be set."""
        if self.use_h4_filter and self.h4_ema_period is None:
            raise ValueError("h4_ema_period required when use_h4_filter=True")
        if not self.use_h4_filter and self.h4_ema_period is not None:
            self.h4_ema_period = None
        return self

    def to_dict_for_mql5(self) -> Dict[str, Any]:
        """Export config to MQL5-compatible dict for template rendering."""
        return {
            'MagicNumber': self.magic_number,
            'RiskPercent': self.risk_percent,
            'EMAPeriod': self.ema_period,
            'RSIPeriod': self.rsi_period,
            'RSIOversold': self.rsi_oversold,
            'RSIOverbought': self.rsi_overbought,
            'ATRPeriod': self.atr_period,
            'ATRMaxMultiplier': self.atr_max_multiplier,
            'StopLossPips': self.stop_loss_pips,
            'TakeProfitPips': self.take_profit_pips,
            'BreakevenPips': self.breakeven_pips,
            'TrailingStopPips': self.trailing_stop_pips,
            'LookbackPeriod': self.lookback_period,
            'MaxSpreadPips': self.max_spread_pips,
            'UseADXFilter': self.use_adx_filter,
            'ADXMinStrength': self.adx_min_strength or 0,
            'UseH4Filter': self.use_h4_filter,
            'H4EMAPeriod': self.h4_ema_period or 0,
        }


class BacktestResult(BaseModel):
    """Parsed MT5 backtest result metrics."""

    strategy_version: str
    symbol: str
    timeframe: str
    date_from: str
    date_to: str
    initial_capital: float
    report_path: Optional[str] = None
    test_bars: int = 0
    test_ticks: int = 0

    # Edge metrics (profitability)
    profit_factor: float
    net_profit: float
    gross_profit: float
    gross_loss: float
    expected_payoff: float

    # Survival metrics (risk)
    max_drawdown_pct: float
    recovery_factor: float

    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    avg_win_usd: float
    avg_loss_usd: float
    avg_win_loss_ratio: float
    max_consecutive_losses: int

    # Risk metrics
    sharpe_ratio: float
    margin_level_min_pct: float

    # Derived flags
    meets_pf_target: bool = False  # PF > 1.5
    meets_dd_target: bool = False  # DD < 15%
    meets_rf_target: bool = False  # RF > 3.0
    meets_rr_target: bool = False  # Win/Loss > 2.0
    meets_all_targets: bool = False

    def check_targets(self) -> None:
        """Evaluate against target metrics from AUREUS_INSPECTION_GUIDELINE.md"""
        self.meets_pf_target = self.profit_factor > 1.5
        self.meets_dd_target = self.max_drawdown_pct < 15.0
        self.meets_rf_target = self.recovery_factor > 3.0
        self.meets_rr_target = self.avg_win_loss_ratio > 2.0
        self.meets_all_targets = (
            self.meets_pf_target and
            self.meets_dd_target and
            self.meets_rf_target and
            self.meets_rr_target
        )


class Weakness(BaseModel):
    """Identified weakness in strategy results."""
    metric: str  # e.g., 'profit_factor', 'max_drawdown_pct'
    current_value: float
    target_value: float
    gap: float
    severity: str  # "critical", "high", "medium", "low"
    description: str
    probable_causes: List[str] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    """LLM analysis of backtest results."""
    strategy_version: str
    analysis_model: str  # "llama3.2:3b"
    summary: str
    weaknesses: List[Weakness] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    raw_llm_response: Optional[str] = None
