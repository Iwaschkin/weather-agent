"""Tests for the open-meteo HTTP client using a mocked transport."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from weather_agent.client import OpenMeteoClient
from weather_agent.models import ClimateRequest, HistoricalRequest

if TYPE_CHECKING:
    from collections.abc import Callable

_GEOCODE_BODY: dict[str, object] = {
    "results": [
        {"name": "Berlin", "country": "Germany", "latitude": 52.52, "longitude": 13.41},
    ],
}
_FORECAST_BODY: dict[str, object] = {
    "current": {"time": "2026-06-15T12:00", "temperature_2m": 21.3, "wind_speed_10m": 9.7},
}
_DAILY_BODY: dict[str, object] = {
    "daily": {
        "time": ["2026-06-15", "2026-06-16"],
        "temperature_2m_max": [21.0, 23.5],
        "temperature_2m_min": [11.0, 12.5],
        "precipitation_sum": [0.0, 4.2],
    },
}


def _client_with(handler: Callable[[httpx.Request], httpx.Response]) -> OpenMeteoClient:
    transport = httpx.MockTransport(handler)
    return OpenMeteoClient(client=httpx.Client(transport=transport))


def test_geocode_parses_response() -> None:
    """geocode() resolves a name into typed results."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["name"] == "Berlin"
        return httpx.Response(200, json=_GEOCODE_BODY)

    client = _client_with(handler)

    results = client.geocode("Berlin")

    assert results[0].latitude == 52.52


def test_current_weather_parses_response() -> None:
    """current_weather() resolves a coordinate into typed conditions."""

    def handler(request: httpx.Request) -> httpx.Response:
        current = request.url.params["current"]
        assert "temperature_2m" in current
        assert "wind_speed_10m" in current
        assert "weather_code" in current
        return httpx.Response(200, json=_FORECAST_BODY)

    client = _client_with(handler)

    weather = client.current_weather(52.52, 13.41)

    assert weather.temperature_celsius == 21.3


def test_geocode_raises_on_error_status() -> None:
    """An error status surfaces as an httpx error."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = _client_with(handler)

    with pytest.raises(httpx.HTTPStatusError):
        _ = client.geocode("Berlin")


def test_forecast_series_parses_daily_block() -> None:
    """forecast_series() requests daily variables and parses the block."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["daily"] == "temperature_2m_max"
        assert request.url.params["forecast_days"] == "5"
        return httpx.Response(200, json=_DAILY_BODY)

    client = _client_with(handler)

    series = client.forecast_series(52.52, 13.41, "temperature_2m_max", 5)

    assert series.timestamps == ("2026-06-15", "2026-06-16")
    assert series.column("temperature_2m_max") == (21.0, 23.5)


def test_forecast_day_series_sends_explicit_date() -> None:
    """forecast_day_series() pins start and end to the requested day."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.startswith("api.open-meteo")
        assert request.url.params["start_date"] == "2026-06-14"
        assert request.url.params["end_date"] == "2026-06-14"
        return httpx.Response(200, json=_DAILY_BODY)

    client = _client_with(handler)

    series = client.forecast_day_series(52.52, 13.41, "temperature_2m_max", "2026-06-14")

    assert series.timestamps == ("2026-06-15", "2026-06-16")


def test_historical_series_sends_date_range() -> None:
    """historical_series() targets the archive host with a date range."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.startswith("archive")
        assert request.url.params["start_date"] == "2020-01-01"
        assert request.url.params["end_date"] == "2020-01-31"
        return httpx.Response(200, json=_DAILY_BODY)

    client = _client_with(handler)
    request = HistoricalRequest(
        latitude=52.52,
        longitude=13.41,
        start_date="2020-01-01",
        end_date="2020-01-31",
        daily="temperature_2m_max",
    )

    series = client.historical_series(request)

    assert series.column("precipitation_sum") == (0.0, 4.2)


def test_climate_projection_sends_model() -> None:
    """climate_projection() targets the climate host with a model list."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.startswith("climate")
        assert request.url.params["models"] == "EC_Earth3P_HR"
        return httpx.Response(200, json=_DAILY_BODY)

    client = _client_with(handler)
    request = ClimateRequest(
        latitude=52.52,
        longitude=13.41,
        start_date="2040-01-01",
        end_date="2040-12-31",
        daily="temperature_2m_max",
        models="EC_Earth3P_HR",
    )

    series = client.climate_projection(request)

    assert series.timestamps == ("2026-06-15", "2026-06-16")


def test_drone_forecast_sends_uk_timezone_and_parses() -> None:
    """drone_forecast() requests the drone variables with a UK timezone."""
    body: dict[str, object] = {
        "elevation": 120.0,
        "hourly": {
            "time": ["2026-06-16T09:00"],
            "wind_gusts_10m": [18.0],
            "temperature_2m": [14.0],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["timezone"] == "Europe/London"
        assert "wind_gusts_10m" in request.url.params["hourly"]
        assert "geopotential_height_950hPa" in request.url.params["hourly"]
        return httpx.Response(200, json=body)

    client = _client_with(handler)

    forecast = client.drone_forecast(53.16, -2.21, forecast_days=2)

    assert forecast.elevation_m == 120.0
    assert forecast.hours[0].wind_gust_10m_kmh == 18.0


def test_air_quality_current_requests_current_block() -> None:
    """air_quality_current() asks for the current block and parses the present hour."""
    body: dict[str, object] = {
        "current": {"time": "2026-06-15T13:00", "interval": 3600, "pm2_5": 12.0},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.startswith("air-quality")
        assert request.url.params["current"] == "pm2_5,european_aqi"
        return httpx.Response(200, json=body)

    client = _client_with(handler)

    readings = client.air_quality_current(52.52, 13.41, "pm2_5,european_aqi")

    assert readings.time == "2026-06-15T13:00"
    assert readings.values["pm2_5"] == 12.0


def test_marine_current_requests_current_block() -> None:
    """marine_current() targets the marine host with a current block."""
    body: dict[str, object] = {
        "current": {"time": "2026-06-15T13:00", "interval": 3600, "wave_height": 1.4},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.startswith("marine")
        assert request.url.params["current"] == "wave_height,wave_period"
        return httpx.Response(200, json=body)

    client = _client_with(handler)

    readings = client.marine_current(21.3, -157.8, "wave_height,wave_period")

    assert readings.values["wave_height"] == 1.4
