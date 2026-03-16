"""
NewsFilterAgent (Agent 6) — Economic calendar via MT5 built-in calendar.

Source: MT5 CalendarValueHistory() via RestBridgeEA (get_calendar command).
If bridge is unavailable, returns empty list (no blocking — safe default).

Returns blocked datetime windows (±minutes around high-impact EUR/USD events).
Events are stored in the database for market feedback learning.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class NewsEvent:
    """A single economic calendar event."""
    event_datetime: datetime
    currency:       str
    impact:         str           # "High"
    title:          str
    source:         str = "MT5"
    actual:         Optional[float] = None
    forecast:       Optional[float] = None
    previous:       Optional[float] = None


@dataclass
class BlockedWindow:
    """A time window during which trading is suppressed."""
    start:  datetime
    end:    datetime
    reason: str


class NewsFilterAgent:
    """
    Agent 6: Economic calendar integration.

    Fetch order:
      1. MT5 bridge (get_calendar command) — real-time, official MetaQuotes data
      2. ForexFactory XML feed — fallback if bridge not available

    Events are cached per session (TTL: 6h). Fetching never blocks the loop —
    if both sources fail, returns empty list (no blocking, safe default).
    """

    def __init__(
        self,
        block_minutes_before: int = 60,
        block_minutes_after:  int = 120,
        timeout_seconds:      int = 10,
    ) -> None:
        self.block_minutes_before = block_minutes_before
        self.block_minutes_after  = block_minutes_after
        self.timeout_seconds      = timeout_seconds
        self._cached_events:      Optional[list[NewsEvent]] = None
        self._cache_fetched_at:   Optional[datetime]        = None
        self._cache_ttl_hours:    int = 6
        # Stale cache: last successful fetch — used as fallback if bridge fails
        self._stale_events:       Optional[list[NewsEvent]] = None
        self._stale_fetched_at:   Optional[datetime]        = None

    # ------------------------------------------------------------------
    # Main interface
    # ------------------------------------------------------------------

    def get_blocked_windows(
        self,
        from_dt: Optional[datetime] = None,
        to_dt:   Optional[datetime] = None,
    ) -> list[BlockedWindow]:
        """
        Get blocked trading windows for the given period.

        Returns empty list if fetch fails (safe default — never blocks the loop).
        """
        now     = datetime.now(tz=timezone.utc)
        from_dt = from_dt or now
        to_dt   = to_dt   or (now + timedelta(days=7))

        events  = self._get_events()
        windows: list[BlockedWindow] = []

        for event in events:
            event_dt = event.event_datetime
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)

            window_start = event_dt - timedelta(minutes=self.block_minutes_before)
            window_end   = event_dt + timedelta(minutes=self.block_minutes_after)

            if window_end   < from_dt: continue
            if window_start > to_dt:   continue

            windows.append(BlockedWindow(
                start=window_start,
                end=window_end,
                reason=f"{event.currency} {event.title}",
            ))

        logger.info("NewsFilter: %d blocked windows from %d events", len(windows), len(events))
        return windows

    def is_blocked(self, dt: Optional[datetime] = None) -> tuple[bool, str]:
        """
        Check if a specific datetime falls within a blocked window.

        Returns:
            (True, reason) if blocked, (False, "") if clear
        """
        dt = dt or datetime.now(tz=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        windows = self.get_blocked_windows(
            from_dt=dt - timedelta(hours=24),
            to_dt=dt   + timedelta(hours=24),
        )
        for window in windows:
            start = window.start if window.start.tzinfo else window.start.replace(tzinfo=timezone.utc)
            end   = window.end   if window.end.tzinfo   else window.end.replace(tzinfo=timezone.utc)
            if start <= dt <= end:
                return True, window.reason

        return False, ""

    def get_raw_events(self) -> list[NewsEvent]:
        """Return all cached events (for database storage)."""
        return self._get_events()

    def format_for_log(self, windows: list[BlockedWindow]) -> str:
        """Format blocked windows for display in logs."""
        if not windows:
            return "No news blocks this period"
        lines = [f"News blocks ({len(windows)}):"]
        for w in windows:
            lines.append(
                f"  {w.start.strftime('%Y-%m-%d %H:%M')} → "
                f"{w.end.strftime('%H:%M')} UTC — {w.reason}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Event fetching + caching
    # ------------------------------------------------------------------

    def _get_events(self) -> list[NewsEvent]:
        """
        Return cached events or fetch fresh.

        Fallback priority on fetch failure:
          1. Stale cache (last successful fetch, any age) — preferred, real data
          2. Empty list — only if no stale data exists at all
        """
        now = datetime.now(tz=timezone.utc)

        # Return live cache if still fresh
        if (self._cached_events is not None
                and self._cache_fetched_at is not None
                and (now - self._cache_fetched_at).total_seconds() < self._cache_ttl_hours * 3600):
            return self._cached_events

        events = self._fetch_from_bridge()

        if events:
            # Success — update both live cache and stale backup
            self._cached_events    = events
            self._cache_fetched_at = now
            self._stale_events     = events
            self._stale_fetched_at = now
        else:
            # Fetch failed — fall back to stale cache if available
            if self._stale_events is not None:
                age_h = (now - self._stale_fetched_at).total_seconds() / 3600
                logger.warning(
                    "NewsFilter: bridge fetch failed — using stale cache "
                    "(%.1fh old, %d events)", age_h, len(self._stale_events)
                )
                # Keep live cache pointing at stale data so next tick doesn't re-fetch immediately
                self._cached_events    = self._stale_events
                self._cache_fetched_at = now
            else:
                logger.warning("NewsFilter: bridge failed and no stale cache — no blocking this session")
                self._cached_events    = []
                self._cache_fetched_at = now

        return self._cached_events

    # ------------------------------------------------------------------
    # Source: MT5 Bridge
    # ------------------------------------------------------------------

    def _fetch_from_bridge(self) -> list[NewsEvent]:
        """
        Fetch events from MT5 built-in calendar via RestBridgeEA.
        Returns empty list if bridge is not running.
        """
        try:
            from bridge.rest_bridge_client import BridgeClient
            bridge = BridgeClient()
            if not bridge.ping():
                logger.debug("NewsFilter: bridge not available")
                return []

            raw = bridge.get_calendar(hours_ahead=168)   # 7 days
            events: list[NewsEvent] = []
            for e in raw:
                events.append(NewsEvent(
                    event_datetime=e.time if e.time.tzinfo else e.time.replace(tzinfo=timezone.utc),
                    currency=e.currency,
                    impact="High",
                    title=e.name,
                    source="MT5",
                    actual=e.actual,
                    forecast=e.forecast,
                    previous=e.previous,
                ))

            logger.info("NewsFilter: %d high-impact events from MT5 bridge", len(events))
            return events

        except Exception as exc:
            logger.warning("NewsFilter: bridge fetch error: %s", exc)
            return []

