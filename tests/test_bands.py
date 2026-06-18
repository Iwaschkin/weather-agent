"""Tests for the numeric-band interpretation seam."""

import pytest

from weather_agent.bands import UV_SCALE, BandScale, classify, render_reading

_SCALE = BandScale(unit="x", thresholds=((1.0, "low"), (2.0, "mid")), top_label="high")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "low"),
        (0.9, "low"),
        (1.0, "mid"),  # at a bound -> the next band (bounds are exclusive uppers)
        (1.9, "mid"),
        (2.0, "high"),  # at or above the last bound -> top label
        (5.0, "high"),
    ],
)
def test_classify_uses_exclusive_upper_bounds(value: float, expected: str) -> None:
    """A value takes the first band whose exclusive upper bound it falls below."""
    assert classify(_SCALE, value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2.9, "low"), (3.0, "moderate"), (7.9, "high"), (11.0, "extreme")],
)
def test_uv_scale_bands_match_who(value: float, expected: str) -> None:
    """The shared UV scale reproduces the WHO risk bands at their boundaries."""
    assert classify(UV_SCALE, value) == expected


def test_render_reading_bands_a_known_metric_with_unit() -> None:
    """A registered metric renders name, value, unit, and band."""
    assert render_reading("pm2_5", 12.0) == "PM2.5 12.0 µg/m³ (fair)"


def test_render_reading_bands_a_unitless_index() -> None:
    """A unitless index renders without a stray unit token."""
    assert render_reading("european_aqi", 85.0) == "European AQI 85.0 (very poor)"


def test_render_reading_humanizes_unknown_metric_without_band() -> None:
    """An unregistered variable is humanized and left unbanded."""
    assert render_reading("wave_period", 8.5) == "Wave period 8.5"


def test_render_reading_reports_missing_value() -> None:
    """A missing value is reported as n/a, not banded."""
    assert render_reading("pm10", None) == "PM10 n/a"
