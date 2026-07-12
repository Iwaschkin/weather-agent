"""Resolve natural-language day expressions to calendar dates.

Lets the date-accepting tools take phrases like ``"tomorrow"`` or ``"next monday"``
as well as an ISO date, so a small local model never has to do calendar arithmetic
(a known weak spot). Pure and deterministic: the reference "today" is always passed
in, never read from a clock here.

Scope is single days. Range phrases ("this weekend", "last summer") return ``None``
on purpose - they map to a date range, not one day, and belong with the range
tools. Weekday handling is intentionally simple: ``"monday"``/``"this monday"``/
``"next monday"`` all mean the next occurrence after today, and ``"last monday"``
the most recent one before today.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_DAYS_PER_WEEK = 7
# Natural-language offsets are user convenience, not an unbounded date-arithmetic
# interface. One hundred years covers the product's provider ranges with room to
# spare while rejecting pathological integer and timedelta inputs early.
MAX_RELATIVE_DAYS = 36_525

# Exact phrases mapping to a fixed offset in days from the reference date.
_OFFSETS: dict[str, int] = {
    "today": 0,
    "tonight": 0,
    "tomorrow": 1,
    "yesterday": -1,
    "day after tomorrow": 2,
    "overmorrow": 2,
    "day before yesterday": -2,
}

_WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_IN_RE = re.compile(r"in (\d+) (day|week)s?")
_AGO_RE = re.compile(r"(\d+) (day|week)s? ago")
_WEEKDAY_RE = re.compile(r"(?:(next|this|last) )?(\w+)")


def _count_delta(match: re.Match[str]) -> timedelta | None:
    try:
        count = int(match.group(1))
    except ValueError:
        return None
    span = _DAYS_PER_WEEK if match.group(2) == "week" else 1
    days = count * span
    return timedelta(days=days) if days <= MAX_RELATIVE_DAYS else None


def _apply_delta(today: date, delta: timedelta) -> date | None:
    try:
        return today + delta
    except OverflowError:
        return None


def _relative_count(text: str, today: date) -> date | None:
    forward = _IN_RE.fullmatch(text)
    if forward is not None:
        delta = _count_delta(forward)
        return None if delta is None else _apply_delta(today, delta)
    backward = _AGO_RE.fullmatch(text)
    if backward is not None:
        delta = _count_delta(backward)
        return None if delta is None else _apply_delta(today, -delta)
    return None


def _next_weekday(today: date, weekday: int) -> date | None:
    ahead = (weekday - today.weekday()) % _DAYS_PER_WEEK or _DAYS_PER_WEEK
    return _apply_delta(today, timedelta(days=ahead))


def _previous_weekday(today: date, weekday: int) -> date | None:
    behind = (today.weekday() - weekday) % _DAYS_PER_WEEK or _DAYS_PER_WEEK
    return _apply_delta(today, timedelta(days=-behind))


def _weekday(text: str, today: date) -> date | None:
    match = _WEEKDAY_RE.fullmatch(text)
    if match is None:
        return None
    weekday = _WEEKDAYS.get(match.group(2))
    if weekday is None:
        return None
    if match.group(1) == "last":
        return _previous_weekday(today, weekday)
    return _next_weekday(today, weekday)


def _try_iso(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def resolve_day(text: str, today: date) -> date | None:
    """Resolve a day expression (or ISO date) to a calendar date.

    Args:
        text: An ISO date (``YYYY-MM-DD``) or a single-day phrase such as
            ``"today"``, ``"tomorrow"``, ``"in 3 days"``, ``"2 weeks ago"``, or a
            weekday like ``"friday"`` / ``"last friday"``.
        today: The reference date relative phrases are measured from.

    Returns:
        The resolved date, or ``None`` when the text is not a recognised single-day
        expression (including range phrases like ``"this weekend"``).
    """
    cleaned = " ".join(text.strip().lower().split())
    iso = _try_iso(cleaned)
    if iso is not None:
        return iso
    offset = _OFFSETS.get(cleaned)
    if offset is not None:
        return _apply_delta(today, timedelta(days=offset))
    counted = _relative_count(cleaned, today)
    if counted is not None:
        return counted
    return _weekday(cleaned, today)
