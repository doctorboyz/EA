"""
LiveTradeAgent — Monitors real-account positions, records trades, triggers improvements.

Safety rules (HARD — never relax):
  - If equity drops 10% from session start → emergency_stop()
  - If live DD > 12% → emergency_stop()
  - If news is active → close_all()
  - This agent is READ/MONITOR only — it does NOT open trades (EA does)
  - live_trading.enabled must be True in system.yaml to activate
"""

import logging
import os
import time
import yaml
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bridge.rest_bridge_client import BridgeClient
from bridge.bridge_models import BridgeNotAvailableError, BridgeTimeoutError
from agents.news_filter import NewsFilterAgent
from core.database import LiveTrade, ForwardTestRun

logger = logging.getLogger(__name__)


class LiveTradeAgent:
    """
    Monitors real-account trades via REST bridge, records to DB, guards safety limits.

    Usage:
        agent = LiveTradeAgent()
        agent.run_poll_cycle("EURUSD", magic_number=77770101)
    """

    def __init__(self, bridge: BridgeClient = None, db_engine=None):
        cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)

        self._cfg         = cfg
        self._live_cfg    = cfg.get('live_trading', {})
        self._bridge_cfg  = cfg.get('bridge', {})
        self.bridge       = bridge or BridgeClient()
        self.news_filter  = NewsFilterAgent()

        # Safety thresholds
        self._emergency_dd    = float(self._live_cfg.get('emergency_dd_threshold', 12.0))
        self._emergency_eq_drop = float(self._live_cfg.get('emergency_equity_drop_pct', 10.0))
        self._feed_back_pf    = float(self._live_cfg.get('feed_back_threshold_pf', 1.2))
        self._real_magic_base = int(self._bridge_cfg.get('real_magic_base', 77770000))

        # Session tracking: {magic: starting_equity}
        self._session_equity: dict[int, float] = {}

        if db_engine is None:
            url = cfg['database']['url']
            db_engine = create_engine(url)
        self._engine = db_engine

    # ─── Guard ────────────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """Real trading must be explicitly enabled in config."""
        return bool(self._live_cfg.get('enabled', False))

    # ─── Main Poll Cycle ──────────────────────────────────────────────────────

    def run_poll_cycle(self, symbol: str, magic_number: int, forward_test_id: int = None) -> dict:
        """
        One full monitoring cycle:
          1. Check news → close if blocked
          2. Check equity safety → emergency stop if needed
          3. Sync closed trades to DB
          4. Check if feedback loop should be triggered
        Returns status dict.
        """
        if not self.is_enabled():
            return {'status': 'disabled', 'reason': 'live_trading.enabled is false in system.yaml'}

        result = {
            'symbol':      symbol,
            'magic':       magic_number,
            'timestamp':   datetime.utcnow().isoformat(),
            'news_closed': 0,
            'new_trades':  0,
            'emergency':   False,
            'retrigger':   False,
        }

        # 1. News check
        news_closed = self._check_news(symbol, magic_number)
        result['news_closed'] = news_closed
        if news_closed > 0:
            return result

        # 2. Safety check
        emergency, reason = self._check_safety(magic_number)
        if emergency:
            self.emergency_stop(symbol, magic_number, reason)
            result['emergency'] = True
            result['reason']    = reason
            return result

        # 3. Sync closed trades
        new_count = self.sync_closed_trades(symbol, magic_number, forward_test_id)
        result['new_trades'] = new_count

        # 4. Feedback check
        if new_count > 0:
            should_retrigger, retrigger_reason = self._check_feedback(symbol, magic_number)
            if should_retrigger:
                self._trigger_backtest_loop(symbol, retrigger_reason)
                result['retrigger'] = True
                result['retrigger_reason'] = retrigger_reason

        return result

    # ─── Sync Trades ──────────────────────────────────────────────────────────

    def sync_closed_trades(self, symbol: str, magic_number: int, forward_test_id: int = None) -> int:
        """Pull closed trades from bridge, upsert into live_trades. Returns new trade count."""
        # Find the earliest unrecorded trade
        with Session(self._engine) as session:
            existing_tickets = {
                r[0] for r in session.query(LiveTrade.ticket)
                .filter_by(magic_number=magic_number, account_type="real")
            }

        # Fetch last 30 days of history
        since = datetime.utcnow() - timedelta(days=30)
        try:
            trades = self.bridge.get_history(
                from_dt=since,
                to_dt=datetime.utcnow(),
                magic=magic_number,
            )
        except (BridgeNotAvailableError, BridgeTimeoutError) as e:
            logger.warning("Bridge unavailable during sync: %s", e)
            return 0

        inserted = 0
        with Session(self._engine) as session:
            for t in trades:
                if t.ticket in existing_tickets:
                    continue
                row = LiveTrade(
                    forward_test_id=forward_test_id,
                    ticket=t.ticket,
                    symbol=symbol,
                    account_type="real",
                    magic_number=magic_number,
                    order_type=t.order_type.value,
                    open_time=t.open_time,
                    close_time=t.close_time,
                    open_price=t.open_price,
                    close_price=t.close_price,
                    volume=t.volume,
                    profit_usd=t.profit,
                    commission=t.commission,
                    swap=t.swap,
                    pips=t.pips,
                )
                session.add(row)
                inserted += 1
            session.commit()

        if inserted:
            logger.info("LiveTrade sync: +%d new real trades (magic=%d)", inserted, magic_number)
        return inserted

    def compute_live_metrics(self, symbol: str, magic_number: int, days: int = 30) -> dict:
        """Compute rolling metrics from live_trades for this magic number."""
        since = datetime.utcnow() - timedelta(days=days)
        with Session(self._engine) as session:
            trades = (
                session.query(LiveTrade)
                .filter(
                    LiveTrade.magic_number == magic_number,
                    LiveTrade.account_type == "real",
                    LiveTrade.close_time >= since,
                )
                .all()
            )

        if not trades:
            return {'total_trades': 0, 'profit_factor': 0.0}

        profits  = [t.profit_usd or 0.0 for t in trades]
        wins     = [p for p in profits if p > 0]
        losses   = [abs(p) for p in profits if p < 0]
        gross_p  = sum(wins)
        gross_l  = sum(losses)
        pf       = round(gross_p / gross_l, 3) if gross_l > 0 else 0.0
        win_rate = round(len(wins) / len(profits) * 100, 1) if profits else 0.0

        # Rolling drawdown
        equity = 0.0; peak = 0.0; max_dd = 0.0
        for p in profits:
            equity += p
            peak = max(peak, equity)
            dd = (peak - equity) / (peak + 1e-9) * 100
            max_dd = max(max_dd, dd)

        return {
            'total_trades':     len(profits),
            'net_profit':       round(sum(profits), 2),
            'profit_factor':    pf,
            'max_drawdown_pct': round(max_dd, 2),
            'win_rate_pct':     win_rate,
        }

    # ─── Safety Checks ────────────────────────────────────────────────────────

    def _check_safety(self, magic_number: int) -> tuple[bool, str]:
        """Returns (should_emergency_stop, reason)."""
        try:
            info = self.bridge.account_info()
        except Exception:
            return False, ""

        # Track starting equity per session
        if magic_number not in self._session_equity:
            self._session_equity[magic_number] = info.equity

        start_equity = self._session_equity[magic_number]

        # Equity drop check
        if start_equity > 0:
            eq_drop = (start_equity - info.equity) / start_equity * 100
            if eq_drop > self._emergency_eq_drop:
                return True, f"Equity dropped {eq_drop:.1f}% (threshold: {self._emergency_eq_drop}%)"

        # Live DD check (from DB)
        metrics = self.compute_live_metrics("", magic_number, days=7)
        if metrics.get('max_drawdown_pct', 0) > self._emergency_dd:
            return True, f"Live DD {metrics['max_drawdown_pct']:.1f}% exceeds {self._emergency_dd}%"

        return False, ""

    def _check_news(self, symbol: str, magic_number: int) -> int:
        """Returns count of positions closed due to news."""
        try:
            currency = "EUR" if "EUR" in symbol else ("XAU" if "XAU" in symbol else "GBP")
            blocked_windows = self.news_filter.get_blocked_windows(currency)
            now = datetime.utcnow()
            for start, end in blocked_windows:
                if start <= now <= end:
                    count = self.bridge.close_all(magic_number)
                    logger.warning("NEWS BLOCK: closed %d positions for %s (magic=%d)", count, symbol, magic_number)
                    return count
        except Exception as e:
            logger.debug("News check error: %s", e)
        return 0

    def _check_feedback(self, symbol: str, magic_number: int) -> tuple[bool, str]:
        """Returns (should_retrigger_backtest, reason)."""
        if not self._live_cfg.get('feed_back_to_improver', True):
            return False, ""
        metrics = self.compute_live_metrics(symbol, magic_number, days=14)
        pf = metrics.get('profit_factor', 0.0)
        if pf < self._feed_back_pf and metrics.get('total_trades', 0) >= 10:
            return True, f"Live PF={pf:.2f} fell below threshold {self._feed_back_pf}"
        return False, ""

    def _trigger_backtest_loop(self, symbol: str, reason: str):
        """Queue a new backtest run via SchedulerAgent."""
        try:
            from agents.scheduler_agent import SchedulerAgent
            scheduler = SchedulerAgent()
            scheduler.queue_manual_run(
                symbol=symbol,
                iterations=10,
                trigger_reason=f"live_feedback: {reason}",
            )
            logger.info("Triggered backtest loop for %s: %s", symbol, reason)
        except Exception as e:
            logger.warning("Could not trigger backtest loop: %s", e)

    # ─── Emergency Stop ───────────────────────────────────────────────────────

    def emergency_stop(self, symbol: str, magic_number: int, reason: str):
        """
        CRITICAL SAFETY: Close all positions for this magic number.
        Logs reason and marks any related ForwardTestRun as failed.
        """
        logger.critical(
            "EMERGENCY STOP — symbol=%s magic=%d reason=%s",
            symbol, magic_number, reason
        )
        try:
            count = self.bridge.close_all(magic_number)
            logger.critical("Emergency stop: closed %d positions", count)
        except Exception as e:
            logger.critical("Emergency stop bridge call failed: %s", e)

        # Mark related forward_test_run as failed
        with Session(self._engine) as session:
            runs = session.query(ForwardTestRun).filter_by(
                ea_magic_number=magic_number, status="running"
            ).all()
            for run in runs:
                run.status = "failed"
                run.notes  = f"EMERGENCY STOP: {reason}"
            session.commit()

        # Reset session equity tracking
        self._session_equity.pop(magic_number, None)

    # ─── Magic Number ─────────────────────────────────────────────────────────

    def get_real_magic(self, symbol: str, run_index: int = 0) -> int:
        symbol_offset = {'EURUSD': 1, 'XAUUSD': 2, 'GBPUSD': 3}.get(symbol, 9)
        return self._real_magic_base + symbol_offset * 100 + run_index + 1
