"""
SignalAgent — Market regime detection for EURUSD/XAUUSD/GBPUSD.

Reads live tick data via REST bridge + stores/retrieves price snapshots from DB.
Classifies current market as: trending | ranging | volatile.
Used to guide EA generation parameters and annotate live trades.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import statistics
import yaml
import os

from bridge.rest_bridge_client import BridgeClient
from bridge.bridge_models import BridgeNotAvailableError, BridgeTimeoutError

logger = logging.getLogger(__name__)

REGIME_TRENDING = "trending"
REGIME_RANGING  = "ranging"
REGIME_VOLATILE = "volatile"
REGIME_UNKNOWN  = "unknown"


@dataclass
class SignalSnapshot:
    symbol:            str
    timeframe:         str
    captured_at:       datetime
    close_price:       float
    ema200_price:      Optional[float]
    trend_direction:   str          # bullish | bearish | neutral
    rsi_value:         Optional[float]
    atr_value:         Optional[float]
    atr_percentile:    Optional[float]   # 0-100, ATR vs recent history
    regime:            str
    regime_confidence: float        # 0.0 - 1.0
    source:            str = "bridge_poll"


@dataclass
class GenerationHints:
    """Parameter suggestions for CodeGeneratorAgent based on current regime."""
    symbol:           str
    regime:           str
    stop_loss_pips:   int
    take_profit_pips: int
    rsi_oversold:     float
    rsi_overbought:   float
    use_adx_filter:   bool
    rationale:        str


class SignalAgent:
    """
    Analyses market conditions via bridge tick data + stored price history.

    Usage:
        agent = SignalAgent()
        snapshot = agent.get_regime("EURUSD")
        hints = agent.get_generation_hints("EURUSD")
    """

    # Price history cache: {symbol: [close_prices]}
    _price_cache: dict[str, list[float]] = {}
    _cache_limit = 250      # store last 250 closes for EMA/ATR calculations

    def __init__(self, bridge: BridgeClient = None, db_engine=None):
        cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
        with open(cfg_path) as f:
            self._cfg = yaml.safe_load(f)
        self.bridge = bridge or BridgeClient()
        self._engine = db_engine

    # ─── Public API ───────────────────────────────────────────────────────────

    def get_regime(self, symbol: str, timeframe: str = "H1") -> SignalSnapshot:
        """
        Classify current market regime for a symbol.

        Fallback priority (bridge → yfinance → DB cache → unknown):
        1. Bridge tick data (live, most accurate)
        2. yfinance H1 price data (if bridge unavailable)
        3. Last saved snapshot from DB
        4. UNKNOWN (last resort — no learning)
        """
        mid = None

        # Layer 1: MT5 bridge (live)
        try:
            tick = self.bridge.get_tick(symbol)
            mid = (tick.bid + tick.ask) / 2
        except (BridgeNotAvailableError, BridgeTimeoutError):
            pass  # fall through to yfinance

        # Layer 2: yfinance (bridge unavailable)
        if mid is None:
            yf_prices = self._fetch_yfinance_prices(symbol)
            if yf_prices:
                self._price_cache[symbol] = yf_prices[-self._cache_limit:]
                mid = yf_prices[-1]
                logger.info("SignalAgent: regime for %s via yfinance (%d bars)", symbol, len(yf_prices))

        # Layer 3: last DB snapshot (yfinance also failed)
        if mid is None:
            cached = self._load_last_snapshot(symbol, timeframe)
            if cached:
                logger.info(
                    "SignalAgent: using cached DB regime for %s: %s (%.0fh old)",
                    symbol, cached.regime,
                    (datetime.utcnow() - cached.captured_at).total_seconds() / 3600,
                )
                return cached
            logger.warning("SignalAgent: all sources failed — UNKNOWN regime for %s", symbol)
            return self._unknown_snapshot(symbol, timeframe)

        self._update_cache(symbol, mid)
        prices = self._price_cache.get(symbol, [mid])

        ema200     = self._ema(prices, 200)
        rsi        = self._rsi(prices, 14)
        atr        = self._atr(prices, 14)
        atr_pct    = self._atr_percentile(symbol, atr)
        trend_dir  = self._trend_direction(mid, ema200)
        regime, confidence = self._classify(mid, ema200, rsi, atr_pct)
        source     = "bridge_poll" if self._price_cache.get(symbol + "_source") != "yfinance" else "yfinance"

        snapshot = SignalSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            captured_at=datetime.utcnow(),
            close_price=mid,
            ema200_price=ema200,
            trend_direction=trend_dir,
            rsi_value=rsi,
            atr_value=atr,
            atr_percentile=atr_pct,
            regime=regime,
            regime_confidence=confidence,
            source=source,
        )
        self._save_snapshot(snapshot)
        return snapshot

    def _fetch_yfinance_prices(self, symbol: str) -> list[float]:
        """Fetch H1 close prices from yfinance. Returns empty list on failure."""
        # Map MT5 symbol names to yfinance tickers
        _YF_MAP = {
            "EURUSD": "EURUSD=X",
            "GBPUSD": "GBPUSD=X",
            "XAUUSD": "GC=F",   # Gold futures
            "USDJPY": "USDJPY=X",
            "USDCHF": "USDCHF=X",
        }
        ticker = _YF_MAP.get(symbol)
        if not ticker:
            return []
        try:
            import yfinance as yf
            hist = yf.Ticker(ticker).history(period="60d", interval="1h", auto_adjust=True)
            if hist.empty:
                return []
            closes = hist["Close"].dropna().tolist()
            self._price_cache[symbol + "_source"] = "yfinance"
            return closes
        except Exception as e:
            logger.debug("yfinance fetch failed for %s: %s", symbol, e)
            return []

    def _load_last_snapshot(self, symbol: str, timeframe: str) -> Optional["SignalSnapshot"]:
        """Load most recent regime snapshot from DB."""
        if self._engine is None:
            return None
        try:
            from sqlalchemy import text
            with self._engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT * FROM signal_snapshots WHERE symbol=:s AND timeframe=:t "
                    "ORDER BY captured_at DESC LIMIT 1"
                ), {"s": symbol, "t": timeframe}).fetchone()
            if row is None:
                return None
            return SignalSnapshot(
                symbol=row.symbol, timeframe=row.timeframe,
                captured_at=row.captured_at,
                close_price=row.close_price, ema200_price=row.ema200_price,
                trend_direction=row.trend_direction, rsi_value=row.rsi_value,
                atr_value=row.atr_value, atr_percentile=row.atr_percentile,
                regime=row.regime, regime_confidence=row.regime_confidence,
                source="db_cache",
            )
        except Exception as e:
            logger.debug("Could not load cached snapshot: %s", e)
            return None

    def get_generation_hints(self, symbol: str) -> GenerationHints:
        """Return suggested EA parameters based on current market regime."""
        snapshot = self.get_regime(symbol)
        regime = snapshot.regime

        if regime == REGIME_TRENDING:
            return GenerationHints(
                symbol=symbol, regime=regime,
                stop_loss_pips=25, take_profit_pips=75,
                rsi_oversold=35.0, rsi_overbought=65.0,
                use_adx_filter=True,
                rationale="Trending market: tighter SL, wider TP, ADX filter for trend confirmation",
            )
        elif regime == REGIME_RANGING:
            return GenerationHints(
                symbol=symbol, regime=regime,
                stop_loss_pips=20, take_profit_pips=50,
                rsi_oversold=30.0, rsi_overbought=70.0,
                use_adx_filter=False,
                rationale="Ranging market: RSI mean-reversion, tighter SL/TP, no ADX filter",
            )
        elif regime == REGIME_VOLATILE:
            return GenerationHints(
                symbol=symbol, regime=regime,
                stop_loss_pips=45, take_profit_pips=90,
                rsi_oversold=25.0, rsi_overbought=75.0,
                use_adx_filter=True,
                rationale="Volatile market: wider SL to avoid stop-outs, wider RSI bands",
            )
        else:
            return GenerationHints(
                symbol=symbol, regime=REGIME_UNKNOWN,
                stop_loss_pips=30, take_profit_pips=90,
                rsi_oversold=30.0, rsi_overbought=70.0,
                use_adx_filter=False,
                rationale="Unknown regime — using V3 baseline defaults",
            )

    def should_retrigger_backtest(self, symbol: str, last_regime: str) -> tuple[bool, str]:
        """Returns (True, reason) if regime has shifted since last backtest."""
        current = self.get_regime(symbol)
        if current.regime != last_regime and current.regime_confidence > 0.65:
            return True, f"Regime shifted: {last_regime} → {current.regime} (confidence={current.regime_confidence:.2f})"
        return False, ""

    # ─── Technical Calculations ───────────────────────────────────────────────

    def _update_cache(self, symbol: str, price: float):
        if symbol not in self._price_cache:
            self._price_cache[symbol] = []
        self._price_cache[symbol].append(price)
        if len(self._price_cache[symbol]) > self._cache_limit:
            self._price_cache[symbol] = self._price_cache[symbol][-self._cache_limit:]

    def _ema(self, prices: list[float], period: int) -> Optional[float]:
        if len(prices) < period:
            return None
        k = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = p * k + ema * (1 - k)
        return round(ema, 5)

    def _rsi(self, prices: list[float], period: int = 14) -> Optional[float]:
        if len(prices) < period + 1:
            return None
        gains, losses = [], []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - 100 / (1 + rs), 2)

    def _atr(self, prices: list[float], period: int = 14) -> Optional[float]:
        if len(prices) < period + 1:
            return None
        trs = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        return round(sum(trs[-period:]) / period, 5)

    def _atr_percentile(self, symbol: str, current_atr: Optional[float]) -> Optional[float]:
        if current_atr is None:
            return None
        prices = self._price_cache.get(symbol, [])
        if len(prices) < 30:
            return 50.0  # default mid
        trs = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        sorted_trs = sorted(trs)
        rank = sum(1 for t in sorted_trs if t <= current_atr)
        return round(rank / len(sorted_trs) * 100, 1)

    def _trend_direction(self, price: float, ema200: Optional[float]) -> str:
        if ema200 is None:
            return "neutral"
        pct = (price - ema200) / ema200 * 100
        if pct > 0.1:
            return "bullish"
        elif pct < -0.1:
            return "bearish"
        return "neutral"

    def _classify(
        self,
        price: float,
        ema200: Optional[float],
        rsi: Optional[float],
        atr_pct: Optional[float],
    ) -> tuple[str, float]:
        """Returns (regime, confidence)."""
        if atr_pct is None:
            return REGIME_UNKNOWN, 0.0

        # Volatile: ATR in top 20%
        if atr_pct >= 80:
            confidence = min((atr_pct - 80) / 20, 1.0) * 0.9 + 0.5
            return REGIME_VOLATILE, round(min(confidence, 1.0), 2)

        # Trending: price clearly above/below EMA200 + RSI not extreme
        if ema200 is not None:
            price_vs_ema = abs(price - ema200) / ema200 * 100
            if price_vs_ema > 0.3 and rsi is not None and 35 < rsi < 70:
                confidence = min(price_vs_ema / 1.0, 1.0) * 0.8 + 0.2
                return REGIME_TRENDING, round(min(confidence, 1.0), 2)

        # Ranging: ATR low + price near EMA200
        if atr_pct < 50:
            confidence = (50 - atr_pct) / 50 * 0.8 + 0.2
            return REGIME_RANGING, round(min(confidence, 1.0), 2)

        return REGIME_RANGING, 0.5

    # ─── DB Persistence ───────────────────────────────────────────────────────

    def _save_snapshot(self, snapshot: SignalSnapshot):
        if self._engine is None:
            return
        try:
            from sqlalchemy.orm import Session
            from core.database import SignalSnapshot as SignalSnapshotORM
            with Session(self._engine) as session:
                row = SignalSnapshotORM(
                    symbol=snapshot.symbol,
                    timeframe=snapshot.timeframe,
                    captured_at=snapshot.captured_at,
                    close_price=snapshot.close_price,
                    ema200_price=snapshot.ema200_price,
                    trend_direction=snapshot.trend_direction,
                    rsi_value=snapshot.rsi_value,
                    atr_value=snapshot.atr_value,
                    atr_percentile=snapshot.atr_percentile,
                    regime=snapshot.regime,
                    regime_confidence=snapshot.regime_confidence,
                    source=snapshot.source,
                )
                session.add(row)
                session.commit()
        except Exception as e:
            logger.debug("Could not save signal snapshot: %s", e)

    def _unknown_snapshot(self, symbol: str, timeframe: str) -> SignalSnapshot:
        return SignalSnapshot(
            symbol=symbol, timeframe=timeframe,
            captured_at=datetime.utcnow(),
            close_price=0.0, ema200_price=None,
            trend_direction="neutral", rsi_value=None,
            atr_value=None, atr_percentile=None,
            regime=REGIME_UNKNOWN, regime_confidence=0.0,
            source="unavailable",
        )
