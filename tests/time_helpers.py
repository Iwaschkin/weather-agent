"""Deterministic time values shared by provider-boundary tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from weather_agent.models import TimeContext

UTC_CONTEXT = TimeContext("UTC", "UTC", 0)
LONDON_SUMMER_CONTEXT = TimeContext("Europe/London", "BST", 3600)
BERLIN_SUMMER_CONTEXT = TimeContext("Europe/Berlin", "CEST", 7200)
TOKYO_CONTEXT = TimeContext("Asia/Tokyo", "JST", 32400)
LOS_ANGELES_SUMMER_CONTEXT = TimeContext("America/Los_Angeles", "PDT", -25200)


def aware(value: str, timezone: str = "Europe/London") -> datetime:
    """Parse an ISO wall time and attach the named zone for test construction."""
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(timezone))


def epoch(value: str, timezone: str = "Europe/London", *, fold: int = 0) -> int:
    """Convert a local test wall time into its unambiguous Unix timestamp."""
    local = datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(timezone), fold=fold)
    return int(local.timestamp())


def time_metadata(
    timezone: str = "Europe/London",
    abbreviation: str = "BST",
    offset_seconds: int = 3600,
) -> dict[str, object]:
    """Return the required top-level Open-Meteo time metadata."""
    return {
        "timezone": timezone,
        "timezone_abbreviation": abbreviation,
        "utc_offset_seconds": offset_seconds,
    }
