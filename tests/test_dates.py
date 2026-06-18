"""Tests for natural-language day resolution."""

from datetime import date

import pytest

from weather_agent.dates import resolve_day

# 2026-06-17 is a Wednesday; all expectations below are relative to it.
_TODAY = date(2026, 6, 17)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-12-25", date(2026, 12, 25)),
        ("today", _TODAY),
        ("Tomorrow", date(2026, 6, 18)),
        ("  yesterday ", date(2026, 6, 16)),
        ("day after tomorrow", date(2026, 6, 19)),
        ("in 3 days", date(2026, 6, 20)),
        ("in 1 week", date(2026, 6, 24)),
        ("2 weeks ago", date(2026, 6, 3)),
        ("5 days ago", date(2026, 6, 12)),
    ],
)
def test_resolve_day_offsets_and_iso(text: str, expected: date) -> None:
    """ISO dates and fixed/counted offsets resolve relative to today."""
    assert resolve_day(text, _TODAY) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("friday", date(2026, 6, 19)),  # the coming Friday
        ("wednesday", date(2026, 6, 24)),  # today's weekday -> next week, not today
        ("next monday", date(2026, 6, 22)),
        ("last friday", date(2026, 6, 12)),
    ],
)
def test_resolve_day_weekdays(text: str, expected: date) -> None:
    """Weekday phrases resolve to the next (or last) matching date."""
    assert resolve_day(text, _TODAY) == expected


@pytest.mark.parametrize("text", ["this weekend", "last summer", "someday", "", "next week"])
def test_resolve_day_rejects_unsupported(text: str) -> None:
    """Range phrases and unrecognised text return None for the caller to handle."""
    assert resolve_day(text, _TODAY) is None
