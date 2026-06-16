"""Tests for the drone-tuned forecast parser."""

import pytest

from weather_agent.parsing import OpenMeteoError, parse_drone_forecast


def _payload() -> dict[str, object]:
    return {
        "elevation": 120.0,
        "hourly": {
            "time": ["2026-06-16T09:00", "2026-06-16T10:00"],
            "temperature_2m": [14.0, 16.0],
            "apparent_temperature": [12.5, 14.5],
            "wind_gusts_10m": [18.0, 30.0],
            "wind_speed_10m": [11.0, 20.0],
            "wind_speed_80m": [25.0, 40.0],
            "wind_speed_120m": [28.0, 45.0],
            "wind_speed_180m": [30.0, 50.0],
            "precipitation": [0.0, 1.2],
            "precipitation_probability": [5.0, 60.0],
            "visibility": [24000.0, 8000.0],
            "cape": [10.0, 350.0],
            "freezing_level_height": [2600.0, 2550.0],
            "is_day": [1.0, 1.0],
            "wind_speed_950hPa": [35.0, 55.0],
            "wind_speed_925hPa": [60.0, 80.0],
            "wind_speed_900hPa": [70.0, 95.0],
            # 950 hPa ~ 540 m ASL -> 420 m AGL (in band); 925 ~ 760 -> 640 AGL (out);
            # 900 ~ 990 -> 870 AGL (out).
            "geopotential_height_950hPa": [540.0, 540.0],
            "geopotential_height_925hPa": [760.0, 760.0],
            "geopotential_height_900hPa": [990.0, 990.0],
        },
    }


def test_parse_drone_forecast_extracts_hours() -> None:
    """The parser yields one typed hour per timestamp with the elevation."""
    forecast = parse_drone_forecast(_payload())

    assert forecast.elevation_m == 120.0
    assert len(forecast.hours) == 2
    first = forecast.hours[0]
    assert first.time == "2026-06-16T09:00"
    assert first.temperature_c == 14.0
    assert first.precipitation_probability_pct == 5.0
    assert first.visibility_m == 24000.0
    assert first.is_day is True
    # Freezing level is reported above ground level: 2600 m ASL - 120 m elevation.
    assert first.freezing_level_agl_m == 2480.0


def test_parse_drone_forecast_derives_wind_to_500m() -> None:
    """0-500 m wind includes the in-band 950 hPa level but not higher levels."""
    forecast = parse_drone_forecast(_payload())

    # Hour 0 candidates: gust 18, heights 11/25/28/30, 950 hPa 35 (in band).
    # 925/900 hPa are above 500 m AGL and excluded.
    assert forecast.hours[0].wind_max_0_500m_kmh == 35.0
    assert forecast.hours[1].wind_max_0_500m_kmh == 55.0


def test_parse_drone_forecast_handles_missing_optional_columns() -> None:
    """Absent variables become None rather than raising."""
    payload: dict[str, object] = {
        "elevation": 50.0,
        "hourly": {"time": ["2026-06-16T09:00"], "wind_gusts_10m": [12.0]},
    }

    hour = parse_drone_forecast(payload).hours[0]

    assert hour.temperature_c is None
    assert hour.visibility_m is None
    assert hour.is_day is None
    assert hour.wind_max_0_500m_kmh == 12.0


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-mapping",
        {"hourly": {"time": ["t"]}},
        {"elevation": 10.0},
        {"elevation": "high", "hourly": {"time": ["t"]}},
    ],
)
def test_parse_drone_forecast_rejects_malformed(payload: object) -> None:
    """Malformed drone payloads raise a domain error."""
    with pytest.raises(OpenMeteoError):
        _ = parse_drone_forecast(payload)
