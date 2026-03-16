"""
ForwardTestManager — Manages the lifecycle of a champion EA on Demo account.

Pipeline:
  1. deploy_champion()     → copies EA to MT5 demo experts, creates ForwardTestRun row
  2. poll_trades()         → bridge get_history → inserts LiveTrade rows
  3. compute_metrics()     → PF, DD, win rate from live_trades
  4. check_promotion()     → if criteria pass → promote_to_real()
  5. pause_for_news()      → bridge close_all if news is active
"""

import logging
import os
import shutil
import yaml
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bridge.rest_bridge_client import BridgeClient
from bridge.bridge_models import BridgeNotAvailableError, BridgeTimeoutError
from agents.news_filter import NewsFilterAgent
from core.database import ForwardTestRun, LiveTrade, ChampionPromotion

logger = logging.getLogger(__name__)


class ForwardTestManager:
    """
    Manages demo deployment and monitoring of champion EAs.

    Usage:
        manager = ForwardTestManager()
        run = manager.deploy_champion("EURUSD", "0.5.2", "/path/to/AureusV3_AI_v0_5_2.mq5")
        # ... later, called by scheduler ...
        manager.poll_and_evaluate(run.id)
    """

    def __init__(self, bridge: BridgeClient = None, db_engine=None):
        cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)

        self._cfg        = cfg
        self._ft_cfg     = cfg.get('forward_test', {})
        self._bridge_cfg = cfg.get('bridge', {})
        self._mt5_cfg    = cfg.get('mt5', {})
        self.bridge      = bridge or BridgeClient()
        self.news_filter = NewsFilterAgent()

        self._demo_magic_base = int(self._bridge_cfg.get('demo_magic_base', 88880000))
        self._experts_path    = self._mt5_cfg.get('experts_path', '')
        self._forward_dir     = os.path.join(
            os.path.dirname(__file__), '..', 'strategies', 'forward_test')
        os.makedirs(self._forward_dir, exist_ok=True)

        if db_engine is None:
            url = cfg['database']['url']
            db_engine = create_engine(url)
        self._engine = db_engine

    # ─── Deploy ───────────────────────────────────────────────────────────────

    def deploy_champion(
        self,
        symbol: str,
        strategy_version: str,
        mq5_path: str,
        strategy_id: int = None,
        backtest_pf: float = None,
        backtest_dd: float = None,
    ) -> ForwardTestRun:
        """
        Copy champion EA to MT5 demo experts folder and create ForwardTestRun record.
        Returns the ForwardTestRun ORM object.
        """
        magic = self._next_magic(symbol)
        ea_name = os.path.basename(mq5_path).replace('.mq5', '')

        # Copy to forward_test archive
        dest_archive = os.path.join(self._forward_dir, os.path.basename(mq5_path))
        shutil.copy2(mq5_path, dest_archive)

        # Copy to MT5 Experts/Aureus/ folder
        dest_mt5 = os.path.join(self._experts_path, os.path.basename(mq5_path))
        if os.path.exists(self._experts_path):
            shutil.copy2(mq5_path, dest_mt5)
            logger.info("Copied EA to MT5 Experts: %s", dest_mt5)
        else:
            logger.warning("MT5 experts path not found: %s", self._experts_path)

        criteria = {
            'min_days_running': self._ft_cfg.get('min_days_running', 7),
            'min_trades':       self._ft_cfg.get('min_trades', 20),
            'min_profit_factor':self._ft_cfg.get('min_profit_factor', 1.3),
            'max_drawdown_pct': self._ft_cfg.get('max_drawdown_pct', 12.0),
            'max_pf_degradation': self._ft_cfg.get('max_pf_degradation', 0.3),
        }

        with Session(self._engine) as session:
            run = ForwardTestRun(
                strategy_id=strategy_id,
                symbol=symbol,
                account_type="demo",
                ea_magic_number=magic,
                status="running",
                promotion_criteria=criteria,
            )
            session.add(run)
            session.flush()
            run_id = run.id

            # Record promotion audit
            promo = ChampionPromotion(
                symbol=symbol,
                strategy_version=strategy_version,
                strategy_id=strategy_id,
                backtest_pf=backtest_pf,
                backtest_dd=backtest_dd,
                forward_test_id=run_id,
                phase="forward_test",
                promoted_by="auto",
            )
            session.add(promo)
            session.commit()
            session.refresh(run)

        logger.info(
            "Deployed champion %s to demo (magic=%d, run_id=%d)",
            strategy_version, magic, run_id
        )
        return run

    # ─── Poll + Evaluate ──────────────────────────────────────────────────────

    def poll_and_evaluate(self, forward_test_id: int) -> dict:
        """
        Poll bridge for new trades, update metrics, check promotion criteria.
        Returns status dict.
        """
        with Session(self._engine) as session:
            run = session.get(ForwardTestRun, forward_test_id)
            if run is None:
                return {'status': 'not_found'}
            if run.status != 'running':
                return {'status': run.status}

            magic  = run.ea_magic_number
            symbol = run.symbol

        # Check news block
        self._handle_news_block(symbol, magic)

        # Poll new trades
        new_count = self.poll_trades(forward_test_id)

        # Recompute metrics
        metrics = self.compute_metrics(forward_test_id)

        # Update run record
        with Session(self._engine) as session:
            run = session.get(ForwardTestRun, forward_test_id)
            deployed_at = run.deployed_at.replace(tzinfo=None) if run.deployed_at.tzinfo else run.deployed_at
            run.days_running       = (datetime.utcnow() - deployed_at).days
            run.total_trades       = metrics.get('total_trades', 0)
            run.net_profit         = metrics.get('net_profit', 0.0)
            run.profit_factor      = metrics.get('profit_factor')
            run.max_drawdown_pct   = metrics.get('max_drawdown_pct')
            run.win_rate_pct       = metrics.get('win_rate_pct')
            session.commit()

        # Check promotion
        should_promote, reason = self.check_promotion_criteria(forward_test_id, metrics)
        if should_promote and self._ft_cfg.get('auto_promote', True):
            self.promote_to_real(forward_test_id)
            return {'status': 'promoted', 'reason': reason, 'metrics': metrics}

        # Check failure (too long without meeting criteria)
        max_days = self._ft_cfg.get('min_days_running', 7) * 3
        with Session(self._engine) as session:
            run = session.get(ForwardTestRun, forward_test_id)
            if run.days_running > max_days and not should_promote:
                run.status = 'failed'
                run.notes  = f"Did not meet criteria after {run.days_running} days"
                session.commit()
                return {'status': 'failed', 'metrics': metrics}

        return {
            'status':     'running',
            'new_trades': new_count,
            'metrics':    metrics,
        }

    def poll_trades(self, forward_test_id: int) -> int:
        """Pull closed trades from bridge, insert new ones into live_trades. Returns count inserted."""
        with Session(self._engine) as session:
            run = session.get(ForwardTestRun, forward_test_id)
            if not run:
                return 0
            magic      = run.ea_magic_number
            symbol     = run.symbol
            deployed_at = run.deployed_at

        try:
            trades = self.bridge.get_history(
                from_dt=deployed_at,
                to_dt=datetime.utcnow(),
                magic=magic,
            )
        except (BridgeNotAvailableError, BridgeTimeoutError) as e:
            logger.warning("Bridge unavailable during poll: %s", e)
            return 0

        inserted = 0
        with Session(self._engine) as session:
            existing = {r[0] for r in session.query(LiveTrade.ticket).filter_by(magic_number=magic)}
            for t in trades:
                if t.ticket in existing:
                    continue
                row = LiveTrade(
                    forward_test_id=forward_test_id,
                    ticket=t.ticket,
                    symbol=symbol,
                    account_type="demo",
                    magic_number=magic,
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
            logger.info("ForwardTest #%d: inserted %d new trades", forward_test_id, inserted)
        return inserted

    def compute_metrics(self, forward_test_id: int) -> dict:
        """Compute PF, DD, win rate from live_trades for this run."""
        with Session(self._engine) as session:
            trades = session.query(LiveTrade).filter_by(forward_test_id=forward_test_id).all()
            if not trades:
                return {'total_trades': 0, 'net_profit': 0.0}

            profits  = [t.profit_usd or 0.0 for t in trades]
            wins     = [p for p in profits if p > 0]
            losses   = [p for p in profits if p < 0]
            net      = sum(profits)
            gross_p  = sum(wins)
            gross_l  = abs(sum(losses))
            pf       = round(gross_p / gross_l, 3) if gross_l > 0 else 0.0
            win_rate = round(len(wins) / len(profits) * 100, 1)

            # Max drawdown
            equity = 0.0
            peak   = 0.0
            max_dd = 0.0
            for p in profits:
                equity += p
                peak = max(peak, equity)
                dd = (peak - equity) / (peak + 1e-9) * 100
                max_dd = max(max_dd, dd)

            return {
                'total_trades':    len(profits),
                'net_profit':      round(net, 2),
                'gross_profit':    round(gross_p, 2),
                'gross_loss':      round(gross_l, 2),
                'profit_factor':   pf,
                'max_drawdown_pct': round(max_dd, 2),
                'win_rate_pct':    win_rate,
            }

    def check_promotion_criteria(self, forward_test_id: int, metrics: dict = None) -> tuple[bool, str]:
        """Returns (should_promote, reason)."""
        if metrics is None:
            metrics = self.compute_metrics(forward_test_id)

        with Session(self._engine) as session:
            run = session.get(ForwardTestRun, forward_test_id)
            if not run:
                return False, "Run not found"
            criteria    = run.promotion_criteria or {}
            days        = run.days_running

        min_days   = criteria.get('min_days_running', 7)
        min_trades = criteria.get('min_trades', 20)
        min_pf     = criteria.get('min_profit_factor', 1.3)
        max_dd     = criteria.get('max_drawdown_pct', 12.0)

        if days < min_days:
            return False, f"Only {days}/{min_days} days running"
        if metrics.get('total_trades', 0) < min_trades:
            return False, f"Only {metrics.get('total_trades',0)}/{min_trades} trades"
        if (metrics.get('profit_factor') or 0) < min_pf:
            return False, f"PF {metrics.get('profit_factor'):.2f} < {min_pf}"
        if (metrics.get('max_drawdown_pct') or 99) > max_dd:
            return False, f"DD {metrics.get('max_drawdown_pct'):.1f}% > {max_dd}%"

        return True, (
            f"All criteria met: {days}d, "
            f"PF={metrics.get('profit_factor'):.2f}, "
            f"DD={metrics.get('max_drawdown_pct'):.1f}%"
        )

    def promote_to_real(self, forward_test_id: int):
        """Mark run as promoted. LiveTradeAgent will pick it up."""
        with Session(self._engine) as session:
            run = session.get(ForwardTestRun, forward_test_id)
            if not run:
                return
            run.status          = 'promoted'
            run.promoted_to_real = True
            run.promoted_at     = datetime.utcnow()
            session.commit()
        logger.info("ForwardTestRun #%d promoted to real trading!", forward_test_id)

    # ─── News Block ───────────────────────────────────────────────────────────

    def _handle_news_block(self, symbol: str, magic: int):
        """Close all demo positions if news is active for this symbol."""
        try:
            currency = "EUR" if "EUR" in symbol else ("XAU" if "XAU" in symbol else "GBP")
            blocked_windows = self.news_filter.get_blocked_windows(currency)
            now = datetime.utcnow()
            for start, end in blocked_windows:
                if start <= now <= end:
                    count = self.bridge.close_all(magic)
                    logger.info("News block active — closed %d positions (magic=%d)", count, magic)
                    return
        except Exception as e:
            logger.debug("News check failed: %s", e)

    # ─── Magic Number Management ──────────────────────────────────────────────

    def _next_magic(self, symbol: str) -> int:
        """Generate a unique magic number for this symbol's forward test."""
        symbol_offset = {'EURUSD': 1, 'XAUUSD': 2, 'GBPUSD': 3}.get(symbol, 9)
        with Session(self._engine) as session:
            count = session.query(ForwardTestRun).filter_by(symbol=symbol).count()
        return self._demo_magic_base + symbol_offset * 100 + count + 1
