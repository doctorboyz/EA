"""
MarketRegimeDetector — Classifies current market conditions.

Regimes:
    trending   — strong directional move (ADX > 25, EMA slope steep)
    choppy     — no direction, oscillating (ADX < 20, RSI ~50)
    ranging    — bounded range (low ATR, mean-reverting)
    volatile   — high ATR spike, news-driven chaos

Each regime maps to a historically best framework:
    trending   → TrendFollowing, IchimokuCloud
    choppy     → MeanReversion, GridTrading
    ranging    → MeanReversion, SniperEntry
    volatile   → SniperEntry, CandlePattern (fewer trades)

Usage:
    detector = MarketRegimeDetector()
    snapshot = detector.detect("EURUSD", recent_bars_df)
    print(snapshot.regime)  # "trending"
    print(snapshot.best_frameworks)  # ["TrendFollowing", "IchimokuCloud"]
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import statistics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regime → Framework mapping (prior knowledge)
# ---------------------------------------------------------------------------

REGIME_FRAMEWORK_MAP: dict[str, list[str]] = {
    "trending":  ["TrendFollowing", "IchimokuCloud", "Breakout"],
    "choppy":    ["MeanReversion", "GridTrading", "SniperEntry"],
    "ranging":   ["MeanReversion", "SniperEntry", "CandlePattern"],
    "volatile":  ["CandlePattern", "SniperEntry", "Breakout"],
    "unknown":   ["TrendFollowing", "MeanReversion", "Breakout",
                  "GridTrading", "SniperEntry", "CandlePattern", "IchimokuCloud"],
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Bar:
    """OHLCV bar."""
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class RegimeSnapshot:
    symbol: str
    timeframe: str
    regime: str                           # trending/choppy/ranging/volatile/unknown
    adx: Optional[float] = None
    atr: Optional[float] = None
    atr_pct: Optional[float] = None       # ATR / close * 100
    ema_slope: Optional[float] = None     # positive = uptrend, negative = downtrend
    rsi: Optional[float] = None
    best_frameworks: list[str] = field(default_factory=list)
    rationale: str = ""
    detected_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class MarketRegimeDetector:
    """
    Analyzes a list of recent bars and classifies the market regime.

    Inputs are raw OHLCV bars — no external data source needed.
    All indicators are calculated internally from price data.
    """

    def __init__(
        self,
        adx_period: int = 14,
        atr_period: int = 14,
        ema_period: int = 50,
        rsi_period: int = 14,
    ):
        self.adx_period  = adx_period
        self.atr_period  = atr_period
        self.ema_period  = ema_period
        self.rsi_period  = rsi_period

    # ── Public interface ─────────────────────────────────────────────────────

    def detect(self, symbol: str, timeframe: str, bars: list[Bar]) -> RegimeSnapshot:
        """
        Classify market regime from recent bars.

        Args:
            symbol:    e.g. "EURUSD"
            timeframe: e.g. "H1"
            bars:      list of Bar objects, most recent LAST

        Returns:
            RegimeSnapshot with regime + recommended frameworks
        """
        if len(bars) < max(self.adx_period, self.atr_period, self.ema_period, self.rsi_period) + 5:
            return RegimeSnapshot(
                symbol=symbol, timeframe=timeframe,
                regime="unknown",
                best_frameworks=REGIME_FRAMEWORK_MAP["unknown"],
                rationale="Not enough bars to detect regime",
            )

        closes = [b.close for b in bars]
        highs  = [b.high  for b in bars]
        lows   = [b.low   for b in bars]

        atr       = self._calc_atr(highs, lows, closes, self.atr_period)
        adx       = self._calc_adx(highs, lows, closes, self.adx_period)
        ema_slope = self._calc_ema_slope(closes, self.ema_period)
        rsi       = self._calc_rsi(closes, self.rsi_period)
        atr_pct   = (atr / closes[-1] * 100) if closes[-1] > 0 else 0

        regime, rationale = self._classify(adx, atr_pct, ema_slope, rsi)

        snap = RegimeSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            regime=regime,
            adx=round(adx, 2),
            atr=round(atr, 6),
            atr_pct=round(atr_pct, 4),
            ema_slope=round(ema_slope, 6),
            rsi=round(rsi, 2),
            best_frameworks=REGIME_FRAMEWORK_MAP.get(regime, REGIME_FRAMEWORK_MAP["unknown"]),
            rationale=rationale,
        )

        logger.info("[%s %s] Regime: %s (ADX=%.1f, ATR%%=%.3f, RSI=%.1f) → %s",
                   symbol, timeframe, regime.upper(),
                   adx, atr_pct, rsi, snap.best_frameworks[:2])
        return snap

    # ── Classification logic ─────────────────────────────────────────────────

    def _classify(
        self, adx: float, atr_pct: float, ema_slope: float, rsi: float
    ) -> tuple[str, str]:
        """
        Decision tree for regime classification.

        ADX > 25 AND slope steep    → trending
        ADX < 20 AND ATR% low       → choppy (oscillating in tight range)
        ADX < 20 AND ATR% very low  → ranging (consolidation)
        ATR% very high              → volatile (spike)
        """
        # Volatile: ATR spike (>0.8% for EURUSD, higher for XAUUSD)
        if atr_pct > 0.8:
            return "volatile", f"High ATR ({atr_pct:.3f}%) — news/spike driven"

        # Trending: strong direction
        if adx > 25 and abs(ema_slope) > 0:
            direction = "UP" if ema_slope > 0 else "DOWN"
            return "trending", f"Strong trend {direction} (ADX={adx:.1f}, slope={ema_slope:.6f})"

        # Ranging: very low volatility + oscillating RSI
        if atr_pct < 0.2 and 35 < rsi < 65:
            return "ranging", f"Low volatility ranging (ATR%={atr_pct:.3f}, RSI={rsi:.1f})"

        # Choppy: weak ADX, moderate ATR
        if adx < 20:
            return "choppy", f"Weak trend (ADX={adx:.1f}) — choppy oscillation"

        # Moderate trend
        return "trending", f"Moderate trend (ADX={adx:.1f})"

    # ── Indicator calculations ────────────────────────────────────────────────

    def _calc_atr(self, highs: list[float], lows: list[float],
                  closes: list[float], period: int) -> float:
        """Average True Range."""
        trs = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)
        if not trs:
            return 0.0
        return sum(trs[-period:]) / min(len(trs), period)

    def _calc_adx(self, highs: list[float], lows: list[float],
                  closes: list[float], period: int) -> float:
        """
        Simplified ADX (directional movement index strength).
        Returns 0-100 where >25 = strong trend.
        """
        plus_dms, minus_dms, trs = [], [], []

        for i in range(1, len(closes)):
            up_move   = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]

            plus_dms.append(up_move   if up_move > down_move and up_move > 0   else 0.0)
            minus_dms.append(down_move if down_move > up_move and down_move > 0 else 0.0)

            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i]  - closes[i - 1]))
            trs.append(tr)

        if len(trs) < period:
            return 0.0

        atr_sum  = sum(trs[-period:])
        plus_sum = sum(plus_dms[-period:])
        minus_sum = sum(minus_dms[-period:])

        if atr_sum == 0:
            return 0.0

        plus_di  = 100 * plus_sum / atr_sum
        minus_di = 100 * minus_sum / atr_sum
        di_diff  = abs(plus_di - minus_di)
        di_sum   = plus_di + minus_di

        adx = 100 * di_diff / di_sum if di_sum > 0 else 0.0
        return min(adx, 100.0)

    def _calc_ema_slope(self, closes: list[float], period: int) -> float:
        """EMA slope — positive = uptrend, negative = downtrend."""
        if len(closes) < period + 2:
            return 0.0
        ema_now  = self._ema(closes, period, offset=0)
        ema_prev = self._ema(closes, period, offset=5)  # 5 bars ago
        return (ema_now - ema_prev) / 5.0 if ema_prev != 0 else 0.0

    def _ema(self, closes: list[float], period: int, offset: int = 0) -> float:
        """Calculate EMA at position offset from end."""
        series = closes[:len(closes) - offset] if offset > 0 else closes
        if len(series) < period:
            return series[-1] if series else 0.0
        k = 2.0 / (period + 1)
        ema = sum(series[:period]) / period
        for price in series[period:]:
            ema = price * k + ema * (1 - k)
        return ema

    def _calc_rsi(self, closes: list[float], period: int) -> float:
        """RSI — 0 to 100."""
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
