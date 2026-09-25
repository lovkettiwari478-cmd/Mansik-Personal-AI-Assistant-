"""Deterministic natural-language date parsing for local command routing.

Not an LLM — a small, well-tested parser covering common phrasings
("tomorrow 5pm", "next monday", "in 2 hours", "2026-01-02 15:00").
All results are timezone-aware (default UTC / user timezone).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_AMPM_RE = re.compile(r"(\d{1,2})\s*(am|pm)", re.IGNORECASE)
_IN_RE = re.compile(r"in\s+(\d+)\s*(minute|min|hour|hr|day|week)s?", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DAY_MONTH_RE = re.compile(r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})", re.IGNORECASE)


_TIME_AMPM_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)")
_TIME_AMPM_BARE_RE = re.compile(r"(\d{1,2})\s*(am|pm)")


def _find_time_of_day(text: str) -> tuple[int, int] | None:
    """Extract hour/minute from text, correctly combining 'H:MM' with am/pm
    (e.g. '3:15pm' → 15:15, '9am' → 9:00, '17:30' → 17:30)."""
    m = _TIME_AMPM_RE.search(text)
    if m:
        hour, minute, marker = int(m.group(1)), int(m.group(2)), m.group(3).lower()
        if marker == "pm" and hour != 12:
            hour += 12
        if marker == "am" and hour == 12:
            hour = 0
        if hour < 24:
            return hour, minute
    m = _TIME_AMPM_BARE_RE.search(text)
    if m:
        hour, marker = int(m.group(1)), m.group(2).lower()
        if marker == "pm" and hour != 12:
            hour += 12
        if marker == "am" and hour == 12:
            hour = 0
        if hour < 24:
            return hour, 0
    tm = _TIME_RE.search(text)
    if tm:
        return int(tm.group(1)), int(tm.group(2))
    return None


def parse_natural_datetime(
    text: str, *, now: datetime | None = None, tz: str = "UTC",
) -> datetime | None:
    """Parse a date/time expression. Returns an aware datetime or None."""
    try:
        tzinfo = ZoneInfo(tz)
    except Exception:
        tzinfo = timezone.utc
    now = now or datetime.now(tzinfo)
    text = text.lower().strip()
    if not text:
        return None

    # ISO datetime / date
    iso_match = _DATE_RE.search(text)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        try:
            base = datetime(y, m, d, tzinfo=tzinfo)
        except ValueError:
            return None
        tod = _find_time_of_day(text)
        if tod:
            base = base.replace(hour=tod[0], minute=tod[1])
        else:
            base = base.replace(hour=9, minute=0)
        return base

    # "in N unit"
    in_match = _IN_RE.search(text)
    if in_match:
        n = int(in_match.group(1))
        unit = in_match.group(2).lower()
        delta = {
            "minute": timedelta(minutes=n), "min": timedelta(minutes=n),
            "hour": timedelta(hours=n), "hr": timedelta(hours=n),
            "day": timedelta(days=n),
            "week": timedelta(weeks=n),
        }[unit]
        return now + delta

    # Relative days
    day: datetime | None = None
    if "day after tomorrow" in text:
        day = (now + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif "tomorrow" in text:
        day = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif "today" in text or "tonight" in text:
        day = now.replace(second=0, microsecond=0)

    # Next weekday
    for name, idx in WEEKDAYS.items():
        if f"next {name}" in text:
            days_ahead = (idx - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            day = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
            break
        if f"on {name}" in text or re.search(rf"\b{name}\b", text):
            days_ahead = (idx - now.weekday()) % 7
            if days_ahead == 0 and "next" not in text:
                days_ahead = 0  # today
            day = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
            break

    # "March 5" style
    dm = _DAY_MONTH_RE.search(text)
    if dm and day is None:
        month = MONTHS[dm.group(1).lower()]
        dnum = int(dm.group(2))
        try:
            candidate = datetime(now.year, month, dnum, 9, 0, tzinfo=tzinfo)
            if candidate < now:
                candidate = datetime(now.year + 1, month, dnum, 9, 0, tzinfo=tzinfo)
            day = candidate
        except ValueError:
            return None

    if day is not None:
        tod = _find_time_of_day(text)
        if tod:
            try:
                day = day.replace(hour=tod[0], minute=tod[1])
            except ValueError:
                return None
        elif "tonight" in text:
            day = day.replace(hour=20)
        return day

    # Bare clock time "at 5pm" / "at 17:30"
    tod = _find_time_of_day(text)
    if tod:
        try:
            candidate = now.replace(hour=tod[0], minute=tod[1], second=0, microsecond=0)
        except ValueError:
            return None
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    return None


def format_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()
