"""Tests for the open-meteo HTTP client using a mocked transport."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import httpx
import pytest

from tests.time_helpers import aware, epoch, time_metadata
from weather_agent.client import OpenMeteoClient
from weather_agent.models import ClimateRequest, Coordinates, HistoricalRequest
from weather_agent.parsing import OpenMeteoError

if TYPE_CHECKING:
    from collections.abc import Callable

_GEOCODE_BODY: dict[str, object] = {
    "results": [
        {
            "name": "Berlin",
            "country": "Germany",
            "latitude": 52.52,
            "longitude": 13.41,
            "timezone": "Europe/Berlin",
        },
    ],
}
_BERLIN = Coordinates(52.52, 13.41)
_FORECAST_BODY: dict[str, object] = {
    **time_metadata("Europe/Berlin", "CEST", 7200),
    "current": {
        "time": epoch("2026-06-15T12:00", "Europe/Berlin"),
        "temperature_2m": 21.3,
        "wind_speed_10m": 9.7,
    },
}
_DAILY_BODY: dict[str, object] = {
    **time_metadata("Europe/Berlin", "CEST", 7200),
    "daily": {
        "time": [
            epoch("2026-06-15T00:00", "Europe/Berlin"),
            epoch("2026-06-16T00:00", "Europe/Berlin"),
        ],
        "temperature_2m_max": [21.0, 23.5],
        "temperature_2m_min": [11.0, 12.5],
        "precipitation_sum": [0.0, 4.2],
    },
}


def _daily_body(*dates: str) -> dict[str, object]:
    count = len(dates)
    return {
        **time_metadata("Europe/Berlin", "CEST", 7200),
        "daily": {
            "time": [epoch(f"{day}T00:00", "Europe/Berlin") for day in dates],
            "temperature_2m_max": [21.0 + index for index in range(count)],
            "temperature_2m_min": [11.0 + index for index in range(count)],
            "precipitation_sum": [float(index) for index in range(count)],
        },
    }


def _client_with(handler: Callable[[httpx.Request], httpx.Response]) -> OpenMeteoClient:
    transport = httpx.MockTransport(handler)
    return OpenMeteoClient(
        client=httpx.Client(transport=transport),
        today=date(2026, 6, 16),
    )


def test_geocode_parses_response() -> None:
    """geocode() resolves a name into typed results."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["name"] == "Berlin"
        return httpx.Response(200, json=_GEOCODE_BODY)

    client = _client_with(handler)

    results = client.geocode("Berlin")

    assert results[0].coordinates.latitude == 52.52


def test_current_weather_parses_response() -> None:
    """current_weather() resolves a coordinate into typed conditions."""

    def handler(request: httpx.Request) -> httpx.Response:
        current = request.url.params["current"]
        assert "temperature_2m" in current
        assert "wind_speed_10m" in current
        assert "weather_code" in current
        assert request.url.params["timezone"] == "auto"
        assert request.url.params["timeformat"] == "unixtime"
        return httpx.Response(200, json=_FORECAST_BODY)

    client = _client_with(handler)

    weather = client.current_weather(_BERLIN)

    assert weather.temperature_celsius == 21.3
    assert weather.time == aware("2026-06-15T12:00", "Europe/Berlin")


def test_geocode_raises_on_error_status() -> None:
    """An error status surfaces as an httpx error."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = _client_with(handler)

    with pytest.raises(httpx.HTTPStatusError):
        _ = client.geocode("Berlin")


def test_client_normalizes_invalid_json() -> None:
    """A successful non-JSON response uses the Open-Meteo provider error type."""
    client = _client_with(lambda _request: httpx.Response(200, content=b"{"))

    with pytest.raises(OpenMeteoError, match="not valid JSON"):
        _ = client.current_weather(_BERLIN)


def test_forecast_series_parses_daily_block() -> None:
    """forecast_series() requests daily variables and parses the block."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["daily"] == "temperature_2m_max"
        assert request.url.params["forecast_days"] == "5"
        assert request.url.params["timezone"] == "auto"
        return httpx.Response(200, json=_DAILY_BODY)

    client = _client_with(handler)

    series = client.forecast_series(_BERLIN, "temperature_2m_max", 5)

    assert series.timestamps == (date(2026, 6, 15), date(2026, 6, 16))
    assert series.column("temperature_2m_max") == (21.0, 23.5)


def test_forecast_day_series_sends_explicit_date() -> None:
    """forecast_day_series() pins start and end to the requested day."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.startswith("api.open-meteo")
        assert request.url.params["start_date"] == "2026-06-14"
        assert request.url.params["end_date"] == "2026-06-14"
        return httpx.Response(200, json=_daily_body("2026-06-14"))

    client = _client_with(handler)

    series = client.forecast_day_series(_BERLIN, "temperature_2m_max", date(2026, 6, 14))

    assert series.timestamps == (date(2026, 6, 14),)


def test_historical_series_sends_date_range() -> None:
    """historical_series() targets the archive host with a date range."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.startswith("archive")
        assert request.url.params["start_date"] == "2020-01-01"
        assert request.url.params["end_date"] == "2020-01-31"
        return httpx.Response(200, json=_daily_body("2020-01-01", "2020-01-02"))

    client = _client_with(handler)
    request = HistoricalRequest(
        coordinates=_BERLIN,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 31),
        daily="temperature_2m_max",
    )

    series = client.historical_series(request)

    assert series.column("precipitation_sum") == (0.0, 1.0)


def test_climate_projection_sends_model() -> None:
    """climate_projection() targets the climate host with a model list."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.startswith("climate")
        assert request.url.params["models"] == "EC_Earth3P_HR"
        return httpx.Response(200, json=_daily_body("2040-01-01", "2040-01-02"))

    client = _client_with(handler)
    request = ClimateRequest(
        coordinates=_BERLIN,
        start_date=date(2040, 1, 1),
        end_date=date(2040, 12, 31),
        daily="temperature_2m_max",
        models="EC_Earth3P_HR",
    )

    series = client.climate_projection(request)

    assert series.timestamps == (date(2040, 1, 1), date(2040, 1, 2))


def test_drone_forecast_sends_uk_timezone_and_parses() -> None:
    """drone_forecast() requests the drone variables with a UK timezone."""
    body: dict[str, object] = {
        **time_metadata(),
        "elevation": 120.0,
        "hourly": {
            "time": [epoch("2026-06-16T09:00")],
            "wind_gusts_10m": [18.0],
            "wind_speed_10m": [10.0],
            "wind_speed_80m": [12.0],
            "wind_speed_120m": [14.0],
            "wind_speed_180m": [16.0],
            "temperature_2m": [14.0],
            "apparent_temperature": [13.0],
            "precipitation": [0.0],
            "precipitation_probability": [5.0],
            "visibility": [20000.0],
            "cape": [0.0],
            "freezing_level_height": [2500.0],
            "is_day": [1.0],
            "cloud_cover_low": [10.0],
            "wind_speed_950hPa": [20.0],
            "wind_speed_925hPa": [22.0],
            "wind_speed_900hPa": [24.0],
            "geopotential_height_950hPa": [550.0],
            "geopotential_height_925hPa": [800.0],
            "geopotential_height_900hPa": [1000.0],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["timezone"] == "Europe/London"
        assert request.url.params["timeformat"] == "unixtime"
        assert "wind_gusts_10m" in request.url.params["hourly"]
        assert "geopotential_height_950hPa" in request.url.params["hourly"]
        return httpx.Response(200, json=body)

    client = _client_with(handler)

    forecast = client.drone_forecast(Coordinates(53.16, -2.21), forecast_days=2)

    assert forecast.elevation_m == 120.0
    assert forecast.hours[0].wind_gust_10m_kmh == 18.0


def test_air_quality_current_requests_current_block() -> None:
    """air_quality_current() asks for the current block and parses the present hour."""
    body: dict[str, object] = {
        **time_metadata("Europe/Berlin", "CEST", 7200),
        "current": {
            "time": epoch("2026-06-15T13:00", "Europe/Berlin"),
            "interval": 3600,
            "pm2_5": 12.0,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.startswith("air-quality")
        assert request.url.params["current"] == "pm2_5,european_aqi"
        assert request.url.params["timezone"] == "auto"
        return httpx.Response(200, json=body)

    client = _client_with(handler)

    readings = client.air_quality_current(_BERLIN, "pm2_5,european_aqi")

    assert readings.time == aware("2026-06-15T13:00", "Europe/Berlin")
    assert readings.values["pm2_5"] == 12.0


def test_marine_current_requests_current_block() -> None:
    """marine_current() targets the marine host with a current block."""
    body: dict[str, object] = {
        **time_metadata("Pacific/Honolulu", "HST", -36000),
        "current": {
            "time": epoch("2026-06-15T13:00", "Pacific/Honolulu"),
            "interval": 3600,
            "wave_height": 1.4,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host.startswith("marine")
        assert request.url.params["current"] == "wave_height,wave_period"
        assert request.url.params["timezone"] == "auto"
        return httpx.Response(200, json=body)

    client = _client_with(handler)

    readings = client.marine_current(Coordinates(21.3, -157.8), "wave_height,wave_period")

    assert readings.values["wave_height"] == 1.4


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(35.68, 139.65), (34.05, -118.24), (51.51, -0.13)],
)
def test_worldwide_current_and_daily_requests_use_local_time(
    latitude: float,
    longitude: float,
) -> None:
    """Tokyo, Los Angeles, and London all delegate zone resolution to the provider."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_FORECAST_BODY if "current" in request.url.params else _DAILY_BODY,
        )

    client = _client_with(handler)

    coordinates = Coordinates(latitude, longitude)
    _ = client.current_weather(coordinates)
    _ = client.forecast_series(coordinates, "temperature_2m_max", 1)

    assert all(request.url.params["timezone"] == "auto" for request in requests)
    assert all(request.url.params["timeformat"] == "unixtime" for request in requests)


def test_forecast_day_rejects_unexpected_provider_date() -> None:
    """An explicit date cannot silently render a different returned row."""
    client = _client_with(lambda _request: httpx.Response(200, json=_daily_body("2026-06-15")))

    with pytest.raises(OpenMeteoError, match="did not contain exactly"):
        _ = client.forecast_day_series(
            _BERLIN,
            "temperature_2m_max",
            date(2026, 6, 14),
        )


def test_historical_range_is_validated_before_io() -> None:
    """A reversed range is rejected before an HTTP request can be sent."""
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_daily_body("2020-01-01"))

    request = HistoricalRequest(
        _BERLIN,
        date(2020, 1, 2),
        date(2020, 1, 1),
        "temperature_2m_max",
    )

    with pytest.raises(ValueError, match="start date"):
        _ = _client_with(handler).historical_series(request)

    assert called is False


def test_historical_response_rejects_out_of_range_date() -> None:
    """Provider rows outside the requested inclusive range are malformed data."""
    request = HistoricalRequest(
        _BERLIN,
        date(2020, 1, 1),
        date(2020, 1, 2),
        "temperature_2m_max",
    )
    client = _client_with(lambda _request: httpx.Response(200, json=_daily_body("2020-01-03")))

    with pytest.raises(OpenMeteoError, match="outside"):
        _ = client.historical_series(request)


def test_forecast_day_rejects_unsupported_date_before_io() -> None:
    """The forecast endpoint's dynamic date window is enforced before HTTP."""
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    with pytest.raises(ValueError, match="forecast dates"):
        _ = _client_with(handler).forecast_day_series(
            _BERLIN,
            "temperature_2m_max",
            date(2020, 1, 1),
        )

    assert called is False


def test_historical_bounds_are_validated_before_io() -> None:
    """Archive lower bounds and maximum range are client invariants."""
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = _client_with(handler)
    before_archive = HistoricalRequest(
        _BERLIN,
        date(1939, 12, 31),
        date(1940, 1, 1),
        "temperature_2m_max",
    )
    excessive = HistoricalRequest(
        _BERLIN,
        date(1940, 1, 1),
        date(1951, 1, 1),
        "temperature_2m_max",
    )

    with pytest.raises(ValueError, match="archive dates"):
        _ = client.historical_series(before_archive)
    with pytest.raises(ValueError, match="range must not exceed"):
        _ = client.historical_series(excessive)

    assert called is False


def test_climate_bounds_are_validated_before_io() -> None:
    """Climate fixed bounds are checked before an HTTP request."""
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    request = ClimateRequest(
        _BERLIN,
        date(2050, 1, 1),
        date(2050, 1, 2),
        "temperature_2m_max",
        "EC_Earth3P_HR",
    )

    with pytest.raises(ValueError, match="climate dates"):
        _ = _client_with(handler).climate_projection(request)

    assert called is False


def test_ensemble_targets_one_current_or_future_hour() -> None:
    """The uncertainty tool no longer assumes midnight row zero means now."""
    body: dict[str, object] = {
        **time_metadata("Asia/Tokyo", "JST", 32400),
        "hourly": {
            "time": [epoch("2026-06-16T14:00", "Asia/Tokyo")],
            "temperature_2m_member01": [24.0],
            "temperature_2m_member02": [26.0],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["forecast_hours"] == "1"
        assert request.url.params["timezone"] == "auto"
        assert request.url.params["timeformat"] == "unixtime"
        return httpx.Response(200, json=body)

    series = _client_with(handler).ensemble_series(
        Coordinates(35.68, 139.65),
        "temperature_2m",
        "icon_seamless",
    )

    assert series.timestamps == (aware("2026-06-16T14:00", "Asia/Tokyo"),)
