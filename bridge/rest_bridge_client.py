"""
REST Bridge Client — File-based IPC between Python (macOS) and MT5 RestBridgeEA.

How it works:
  1. Python writes a JSON request file to bridge/requests/{uuid}.json
  2. MT5 EA polls that folder via OnTimer(), processes the command, deletes request
  3. MT5 EA writes bridge/responses/{uuid}.json
  4. Python polls for response file, reads + deletes it
  5. Timeout if no response within `timeout_seconds`

All paths are macOS paths; the EA sees them as C:\\bridge\\... inside Wine.
"""

import json
import os
import time
import uuid
import logging
import yaml
from datetime import datetime
from typing import Optional

from bridge.bridge_models import (
    AccountInfo, Position, ClosedTrade, TradeResult, Tick, PingResponse,
    OpenTradeRequest, OrderType, CalendarEvent,
    BridgeTimeoutError, BridgeNotAvailableError, BridgeTradeError,
)

logger = logging.getLogger(__name__)

# ─── Load config ──────────────────────────────────────────────────────────────

def _load_bridge_cfg() -> dict:
    cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
    with open(cfg_path) as f:
        return yaml.safe_load(f).get('bridge', {})


# ─── Client ───────────────────────────────────────────────────────────────────

class BridgeClient:
    """
    File-IPC client for RestBridgeEA running inside MT5 (Wine/macOS).

    Usage:
        bridge = BridgeClient()
        if bridge.ping():
            info = bridge.account_info()
            print(info.balance)
    """

    def __init__(self, cfg: dict = None):
        cfg = cfg or _load_bridge_cfg()
        self.request_dir:  str   = cfg.get('request_dir', '')
        self.response_dir: str   = cfg.get('response_dir', '')
        self.timeout:      float = float(cfg.get('timeout_seconds', 10))
        self.poll_ms:      float = float(cfg.get('poll_interval_ms', 200)) / 1000.0

        os.makedirs(self.request_dir,  exist_ok=True)
        os.makedirs(self.response_dir, exist_ok=True)

    # ─── Core IPC ─────────────────────────────────────────────────────────────

    def _send(self, payload: dict) -> dict:
        """Write request, wait for response, return parsed dict."""
        req_id = str(uuid.uuid4())
        payload['id'] = req_id

        req_path  = os.path.join(self.request_dir,  f"{req_id}.json")
        resp_path = os.path.join(self.response_dir, f"{req_id}.json")

        # Write request
        with open(req_path, 'w') as f:
            json.dump(payload, f)

        logger.debug("Bridge request: %s → %s", payload.get('cmd'), req_path)

        # Poll for response
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if os.path.exists(resp_path):
                try:
                    with open(resp_path) as f:
                        data = json.load(f)
                    os.remove(resp_path)
                    logger.debug("Bridge response: %s", data)
                    return data
                except (json.JSONDecodeError, OSError):
                    time.sleep(self.poll_ms)
                    continue
            time.sleep(self.poll_ms)

        # Cleanup stale request if EA never processed it
        if os.path.exists(req_path):
            os.remove(req_path)

        raise BridgeTimeoutError(
            f"No response within {self.timeout}s for cmd={payload.get('cmd')} id={req_id}"
        )

    def _check_status(self, data: dict) -> dict:
        """Raise BridgeTradeError if response status is 'error'."""
        if data.get('status') == 'error':
            raise BridgeTradeError(
                retcode=data.get('retcode', -1),
                message=data.get('message', 'Unknown error'),
            )
        return data

    # ─── Public Commands ──────────────────────────────────────────────────────

    def ping(self) -> bool:
        """Returns True if bridge EA is alive."""
        try:
            data = self._send({'cmd': 'ping'})
            return data.get('status') == 'ok'
        except (BridgeTimeoutError, Exception):
            return False

    def account_info(self) -> AccountInfo:
        """Get account balance, equity, margin."""
        data = self._check_status(self._send({'cmd': 'account_info'}))
        return AccountInfo(**data)

    def get_positions(self, magic: int = None) -> list[Position]:
        """Get all currently open positions, optionally filtered by magic number."""
        payload = {'cmd': 'get_positions'}
        if magic is not None:
            payload['magic'] = magic
        data = self._check_status(self._send(payload))
        return [Position(**p) for p in data.get('positions', [])]

    def get_history(
        self,
        from_dt: datetime,
        to_dt: datetime,
        magic: int = None,
    ) -> list[ClosedTrade]:
        """Get closed trades in date range."""
        payload = {
            'cmd':  'get_history',
            'from': from_dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'to':   to_dt.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        if magic is not None:
            payload['magic'] = magic
        data = self._check_status(self._send(payload))
        trades = []
        for t in data.get('trades', []):
            try:
                trades.append(ClosedTrade(**t))
            except Exception as e:
                logger.warning("Could not parse trade %s: %s", t, e)
        return trades

    def open_trade(
        self,
        symbol: str,
        order_type: OrderType,
        volume: float,
        sl: float,
        tp: float,
        magic: int,
        comment: str = "Aureus",
    ) -> TradeResult:
        """Open a new trade. Returns TradeResult with ticket on success."""
        payload = {
            'cmd':        'open_trade',
            'symbol':     symbol,
            'order_type': order_type.value,
            'volume':     volume,
            'sl':         sl,
            'tp':         tp,
            'magic':      magic,
            'comment':    comment,
        }
        data = self._check_status(self._send(payload))
        return TradeResult(**data)

    def close_trade(self, ticket: int) -> bool:
        """Close a specific trade by ticket number."""
        data = self._check_status(self._send({'cmd': 'close_trade', 'ticket': ticket}))
        return data.get('status') == 'ok'

    def close_all(self, magic: int) -> int:
        """Close all open positions with given magic number. Returns count closed."""
        data = self._check_status(self._send({'cmd': 'close_all', 'magic': magic}))
        return int(data.get('closed', 0))

    def modify_sl_tp(self, ticket: int, sl: float, tp: float) -> bool:
        """Modify SL/TP of an open position."""
        data = self._check_status(self._send({
            'cmd':    'modify_sl_tp',
            'ticket': ticket,
            'sl':     sl,
            'tp':     tp,
        }))
        return data.get('status') == 'ok'

    def get_tick(self, symbol: str) -> Tick:
        """Get current bid/ask/spread for a symbol."""
        data = self._check_status(self._send({'cmd': 'get_tick', 'symbol': symbol}))
        return Tick(**data)

    def get_calendar(self, hours_ahead: int = 168) -> list[CalendarEvent]:
        """
        Fetch upcoming high-impact EUR+USD events from MT5 built-in economic calendar.

        Args:
            hours_ahead: How many hours forward to look (default 168 = 7 days)

        Returns:
            List of CalendarEvent. Empty list if bridge unavailable or no events.
        """
        try:
            data = self._check_status(self._send({
                'cmd':         'get_calendar',
                'hours_ahead': hours_ahead,
            }))
            events = []
            for e in data.get('events', []):
                try:
                    events.append(CalendarEvent(**e))
                except Exception as exc:
                    logger.warning("Could not parse calendar event %s: %s", e, exc)
            return events
        except (BridgeTimeoutError, BridgeTradeError) as exc:
            logger.warning("get_calendar failed: %s — returning empty list", exc)
            return []
