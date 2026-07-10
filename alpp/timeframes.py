"""Timeframe presets and auto bar-size selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class RangeSpec:
    """Resolved analysis window + Alpaca bar timeframe."""

    label: str
    start: datetime
    end: datetime
    bar: str  # Alpaca timeframe string, e.g. "1Day", "15Min"
    description: str


# User aliases → internal keys
ALIASES: dict[str, str] = {
    "d": "1d",
    "1d": "1d",
    "day": "1d",
    "today": "1d",
    "5d": "5d",
    "w": "5d",
    "week": "5d",
    "1w": "5d",
    "1m": "1m",
    "m": "1m",
    "month": "1m",
    "3m": "3m",
    "q": "3m",
    "quarter": "3m",
    "6m": "6m",
    "ytd": "ytd",
    "y": "ytd",
    "1y": "1y",
    "year": "1y",
    "2y": "2y",
    "5y": "5y",
    "max": "max",
    "all": "max",
}


def normalize_tf(raw: str) -> str:
    key = raw.strip().lower()
    if key not in ALIASES:
        supported = ", ".join(sorted(set(ALIASES.values())))
        raise SystemExit(f"Unknown timeframe {raw!r}. Use one of: {supported}")
    return ALIASES[key]


def _now_et() -> datetime:
    return datetime.now(tz=ET)


def resolve_range(tf: str, now: datetime | None = None) -> RangeSpec:
    """Map a human timeframe to start/end + bar size."""
    key = normalize_tf(tf)
    now = now or _now_et()
    end = now

    if key == "1d":
        # Regular session start (or prior calendar day if premarket)
        start = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now.hour < 4:
            start -= timedelta(days=1)
        return RangeSpec(key, start, end, "5Min", "intraday 5-minute bars")

    if key == "5d":
        start = end - timedelta(days=7)  # include weekend buffer
        return RangeSpec(key, start, end, "15Min", "5 trading days · 15-minute bars")

    if key == "1m":
        start = end - timedelta(days=35)
        return RangeSpec(key, start, end, "1Hour", "1 month · hourly bars")

    if key == "3m":
        start = end - timedelta(days=100)
        return RangeSpec(key, start, end, "1Day", "3 months · daily bars")

    if key == "6m":
        start = end - timedelta(days=200)
        return RangeSpec(key, start, end, "1Day", "6 months · daily bars")

    if key == "ytd":
        start = datetime(now.year, 1, 1, 0, 0, 0, tzinfo=ET)
        return RangeSpec(key, start, end, "1Day", "year-to-date · daily bars")

    if key == "1y":
        start = end - timedelta(days=365)
        return RangeSpec(key, start, end, "1Day", "1 year · daily bars")

    if key == "2y":
        start = end - timedelta(days=730)
        return RangeSpec(key, start, end, "1Day", "2 years · daily bars")

    if key == "5y":
        start = end - timedelta(days=365 * 5 + 5)
        return RangeSpec(key, start, end, "1Week", "5 years · weekly bars")

    # max
    start = datetime(2016, 1, 1, tzinfo=ET)
    return RangeSpec(key, start, end, "1Week", "max history · weekly bars")


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(timezone.utc)


def as_date(dt: datetime) -> date:
    return dt.astimezone(ET).date()
