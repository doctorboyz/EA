"""
NewsFilterAgent (Agent 6) — Fetches ForexFactory economic calendar.

Fetches high-impact news events for EUR and USD (EURUSD pair).
Returns a list of blocked datetime windows (±hours around event).
These get injected into the generated MQL5 code or used to pause trading.

ForexFactory provides a public iCalendar (.ics) feed — no API key needed.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

# ForexFactory iCal feed (free, public)
FOREXFACTORY_ICAL_URL = "https://www.forexfactory.com/ff_cal_thisweek.xml"

# Currencies that affect EURUSD
EURUSD_CURRENCIES = {"USD", "EUR"}

# Only block HIGH impact events
HIGH_IMPACT_KEYWORDS = {
    "Non-Farm", "NFP", "FOMC", "Fed Rate", "Interest Rate",
    "CPI", "GDP", "Unemployment", "Retail Sales", "PMI Manufacturing",
    "ECB", "Federal Reserve",
}


@dataclass
class NewsEvent:
    """A single economic calendar event."""
    event_datetime: datetime
    currency: str
    impact: str          # "High", "Medium", "Low"
    title: str
    source: str = "ForexFactory"


@dataclass
class BlockedWindow:
    """A time window during which trading is suppressed."""
    start: datetime
    end: datetime
    reason: str


class NewsFilterAgent:
    """
    Agent 6: Economic calendar integration.

    Fetches upcoming high-impact events and returns blocked trading windows.
    Events are cached for the session to avoid repeated HTTP calls.
    Falls back gracefully (no blocking) if fetch fails.
    """

    def __init__(
        self,
        block_hours_before: int = 1,
        block_hours_after: int = 2,
        timeout_seconds: int = 10,
    ) -> None:
        self.block_hours_before = block_hours_before
        self.block_hours_after = block_hours_after
        self.timeout_seconds = timeout_seconds
        self._cached_events: Optional[list[NewsEvent]] = None
        self._cache_fetched_at: Optional[datetime] = None
        self._cache_ttl_hours: int = 6

    # ------------------------------------------------------------------
    # Main interface
    # ------------------------------------------------------------------

    def get_blocked_windows(
        self,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
    ) -> list[BlockedWindow]:
        """
        Get list of blocked trading windows for the given period.

        Args:
            from_dt: Start of period (default: now)
            to_dt:   End of period (default: now + 7 days)

        Returns:
            List of BlockedWindow objects. Empty list if fetch fails.
        """
        now = datetime.now(tz=timezone.utc)
        from_dt = from_dt or now
        to_dt = to_dt or (now + timedelta(days=7))

        events = self._get_events()
        windows: list[BlockedWindow] = []

        for event in events:
            event_dt = event.event_datetime
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)

            # Skip if outside the requested period
            if event_dt < from_dt - timedelta(hours=self.block_hours_before):
                continue
            if event_dt > to_dt + timedelta(hours=self.block_hours_after):
                continue

            windows.append(BlockedWindow(
                start=event_dt - timedelta(hours=self.block_hours_before),
                end=event_dt + timedelta(hours=self.block_hours_after),
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
            to_dt=dt + timedelta(hours=24),
        )
        for window in windows:
            start = window.start if window.start.tzinfo else window.start.replace(tzinfo=timezone.utc)
            end = window.end if window.end.tzinfo else window.end.replace(tzinfo=timezone.utc)
            if start <= dt <= end:
                return True, window.reason

        return False, ""

    def get_blocked_hours_for_mql5(
        self,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
    ) -> list[str]:
        """
        Return blocked hours as ISO datetime strings for injection into StrategyConfig.
        These get stored in config.news_block_hours and written to the EA.
        """
        windows = self.get_blocked_windows(from_dt, to_dt)
        result = []
        for window in windows:
            # Generate hourly slots within the window
            current = window.start.replace(minute=0, second=0, microsecond=0)
            while current <= window.end:
                result.append(current.isoformat())
                current += timedelta(hours=1)
        return sorted(set(result))

    # ------------------------------------------------------------------
    # Event fetching + caching
    # ------------------------------------------------------------------

    def _get_events(self) -> list[NewsEvent]:
        """Get events from cache or fetch fresh."""
        now = datetime.now(tz=timezone.utc)

        # Return cache if valid
        if (self._cached_events is not None and
                self._cache_fetched_at is not None and
                (now - self._cache_fetched_at).total_seconds() < self._cache_ttl_hours * 3600):
            return self._cached_events

        # Fetch fresh
        events = self._fetch_events()
        self._cached_events = events
        self._cache_fetched_at = now
        return events

    def _fetch_events(self) -> list[NewsEvent]:
        """
        Fetch events from ForexFactory XML feed.
        Falls back to empty list if fetch fails.
        """
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(FOREXFACTORY_ICAL_URL)
                resp.raise_for_status()
                return self._parse_xml(resp.text)
        except Exception as e:
            logger.warning("NewsFilter: fetch failed (%s) — no news blocking this session", e)
            return []

    def _parse_xml(self, xml_text: str) -> list[NewsEvent]:
        """Parse ForexFactory weekly XML calendar."""
        import xml.etree.ElementTree as ET
        events: list[NewsEvent] = []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning("NewsFilter: XML parse error: %s", e)
            return events

        for item in root.iter('event'):
            try:
                title_el    = item.find('title')
                currency_el = item.find('country')
                impact_el   = item.find('impact')
                date_el     = item.find('date')
                time_el     = item.find('time')

                if any(el is None for el in [title_el, currency_el, impact_el, date_el]):
                    continue

                title    = (title_el.text or '').strip()
                currency = (currency_el.text or '').strip().upper()
                impact   = (impact_el.text or '').strip()
                date_str = (date_el.text or '').strip()
                time_str = (time_el.text or '00:00am').strip() if time_el is not None else '12:00am'

                # Only process EURUSD-relevant high-impact events
                if currency not in EURUSD_CURRENCIES:
                    continue
                if impact.lower() not in ('high', '3'):
                    continue

                # Parse date + time
                event_dt = self._parse_ff_datetime(date_str, time_str)
                if event_dt is None:
                    continue

                events.append(NewsEvent(
                    event_datetime=event_dt,
                    currency=currency,
                    impact="High",
                    title=title,
                ))

            except Exception as e:
                logger.debug("NewsFilter: skipping malformed event: %s", e)
                continue

        logger.info("NewsFilter: parsed %d high-impact events", len(events))
        return events

    def _parse_ff_datetime(self, date_str: str, time_str: str) -> Optional[datetime]:
        """
        Parse ForexFactory date and time strings.
        FF format: date like 'Jan 13 2026', time like '8:30am'
        Returns UTC datetime or None on failure.
        """
        try:
            # Combine date and time
            combined = f"{date_str} {time_str}".strip()
            # Try various formats
            for fmt in ('%b %d %Y %I:%M%p', '%b %d %Y %I%p', '%Y-%m-%d %H:%M:%S'):
                try:
                    dt = datetime.strptime(combined, fmt)
                    # FF times are US Eastern
                    eastern = ZoneInfo("America/New_York")
                    dt_eastern = dt.replace(tzinfo=eastern)
                    return dt_eastern.astimezone(timezone.utc)
                except ValueError:
                    continue
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Convenience: inject blocked windows into MQL5 comment
    # ------------------------------------------------------------------

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
