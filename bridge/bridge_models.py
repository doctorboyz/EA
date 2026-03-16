"""Pydantic models for REST Bridge file-IPC communication between Python and MT5 EA."""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ─── Exceptions ───────────────────────────────────────────────────────────────

class BridgeTimeoutError(Exception):
    """MT5 EA did not respond within timeout."""

class BridgeNotAvailableError(Exception):
    """Bridge EA is not running (ping failed)."""

class BridgeTradeError(Exception):
    """MT5 returned a trade error retcode."""
    def __init__(self, retcode: int, message: str):
        self.retcode = retcode
        self.message = message
        super().__init__(f"Trade error {retcode}: {message}")


# ─── Enums ────────────────────────────────────────────────────────────────────

class OrderType(str, Enum):
    BUY  = "buy"
    SELL = "sell"

class AccountType(str, Enum):
    DEMO = "demo"
    REAL = "real"

class TradeRegime(str, Enum):
    TRENDING = "trending"
    RANGING  = "ranging"
    VOLATILE = "volatile"
    UNKNOWN  = "unknown"


# ─── Response Models ──────────────────────────────────────────────────────────

class AccountInfo(BaseModel):
    balance:      float
    equity:       float
    margin:       float
    free_margin:  float
    currency:     str = "USD"
    leverage:     int = 100
    server:       str = ""
    account_type: str = ""


class Position(BaseModel):
    ticket:      int
    symbol:      str
    order_type:  OrderType
    volume:      float
    open_price:  float
    current_price: float
    sl:          float
    tp:          float
    profit:      float
    commission:  float = 0.0
    swap:        float = 0.0
    open_time:   datetime
    magic:       int
    comment:     str = ""


class ClosedTrade(BaseModel):
    ticket:      int
    symbol:      str
    order_type:  OrderType
    volume:      float
    open_price:  float
    close_price: float
    open_time:   datetime
    close_time:  datetime
    profit:      float
    commission:  float = 0.0
    swap:        float = 0.0
    pips:        float = 0.0
    magic:       int
    comment:     str = ""


class TradeResult(BaseModel):
    status:  str          # "ok" | "error"
    ticket:  Optional[int] = None
    retcode: Optional[int] = None
    message: str = ""


class Tick(BaseModel):
    symbol: str
    bid:    float
    ask:    float
    spread: float         # in pips
    time:   datetime


class PingResponse(BaseModel):
    status:      str      # "ok"
    server_time: datetime
    version:     str = "1.0"
    bridge_magic: int = 0


# ─── Request models (for internal use by BridgeClient) ───────────────────────

class OpenTradeRequest(BaseModel):
    symbol:  str
    order_type: OrderType
    volume:  float = Field(ge=0.01, le=100.0)
    sl:      float
    tp:      float
    magic:   int
    comment: str = "Aureus"


class ModifySlTpRequest(BaseModel):
    ticket: int
    sl:     float
    tp:     float


class CalendarEvent(BaseModel):
    """A single economic calendar event returned by MT5 get_calendar command."""
    name:       str
    time:       datetime
    currency:   str                    # "USD" | "EUR"
    importance: str = "high"
    actual:     Optional[float] = None
    forecast:   Optional[float] = None
    previous:   Optional[float] = None
