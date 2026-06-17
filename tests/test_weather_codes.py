"""Tests for the WMO weather-code descriptions."""

import pytest

from weather_agent.weather_codes import describe_weather_code


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0.0, "clear sky"),
        (3.0, "overcast"),
        (61.0, "slight rain"),
        (95.0, "thunderstorm"),
    ],
)
def test_describe_weather_code_known(code: float, expected: str) -> None:
    """Known WMO codes map to their condition phrase."""
    assert describe_weather_code(code) == expected


def test_describe_weather_code_none_is_unknown() -> None:
    """A missing code is reported as unknown, not crashed."""
    assert describe_weather_code(None) == "unknown"


def test_describe_weather_code_unrecognised_surfaces_the_value() -> None:
    """An unrecognised code is surfaced rather than silently dropped."""
    assert describe_weather_code(42.0) == "unknown (code 42)"
