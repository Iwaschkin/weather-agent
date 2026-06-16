"""Tests for the Phase 3 open-meteo domain summaries (mocked transport)."""

import httpx

from weather_agent.client import OpenMeteoClient
from weather_agent.results import render
from weather_agent.weather import (
    air_quality_summary,
    elevation_summary,
    ensemble_summary,
    marine_summary,
    river_discharge_summary,
)

_GEOCODE_BODY: dict[str, object] = {
    "results": [
        {"name": "Berlin", "country": "Germany", "latitude": 52.52, "longitude": 13.41},
    ],
}
_AIR_QUALITY_BODY: dict[str, object] = {
    "current": {
        "time": "2026-06-15T13:00",
        "interval": 3600,
        "pm2_5": 12.0,
        "pm10": 20.0,
        "ozone": 60.0,
        "european_aqi": 33.0,
    },
}
_MARINE_BODY: dict[str, object] = {
    "current": {
        "time": "2026-06-15T13:00",
        "interval": 3600,
        "wave_height": 1.4,
        "wave_period": 6.0,
    },
}
_FLOOD_BODY: dict[str, object] = {
    "daily": {"time": ["2026-06-15"], "river_discharge": [120.0]},
}
_ENSEMBLE_BODY: dict[str, object] = {
    "hourly": {
        "time": ["2026-06-15T00:00"],
        "temperature_2m_member01": [10.0],
        "temperature_2m_member02": [14.0],
    },
}
_ELEVATION_BODY: dict[str, object] = {"elevation": [38.0]}


def _client_for(host_prefix: str, body: object) -> OpenMeteoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        assert request.url.host.startswith(host_prefix)
        return httpx.Response(200, json=body)

    return OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_air_quality_summary_reports_readings() -> None:
    """Air-quality summary reports particulates and AQI from the current hour."""
    summary = render(
        air_quality_summary("Berlin", client=_client_for("air-quality", _AIR_QUALITY_BODY))
    )

    assert "Air quality for Berlin, Germany" in summary
    # Reports the present hour from the current block, not the start of the day.
    assert "(as of 2026-06-15T13:00)" in summary
    assert "pm2_5 12.0" in summary
    assert "european_aqi 33.0" in summary


def test_marine_summary_reports_waves() -> None:
    """Marine summary reports wave height and period."""
    summary = render(marine_summary("Honolulu", client=_client_for("marine", _MARINE_BODY)))

    assert "Marine conditions for Berlin, Germany" in summary
    assert "wave_height 1.4" in summary


def test_marine_summary_reports_inland_as_non_coastal() -> None:
    """An open-meteo 400 (inland point) becomes a friendly non-coastal message."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        return httpx.Response(400)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(marine_summary("Berlin", client=client))

    assert "does not appear to be a coastal or marine location" in summary


def test_marine_summary_reports_other_errors_generically() -> None:
    """A non-400 marine error flows to the generic failure message."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        return httpx.Response(503)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(marine_summary("Berlin", client=client))

    assert "Could not retrieve data" in summary


def test_river_discharge_summary_reports_discharge() -> None:
    """Flood summary reports forecast river discharge."""
    summary = render(river_discharge_summary("Cologne", client=_client_for("flood", _FLOOD_BODY)))

    assert "River discharge for Berlin, Germany" in summary
    assert "river_discharge 120.0" in summary


def test_ensemble_summary_reports_spread() -> None:
    """Ensemble summary conveys member spread."""
    summary = render(ensemble_summary("Berlin", client=_client_for("ensemble", _ENSEMBLE_BODY)))

    assert "Ensemble temperature for Berlin, Germany" in summary
    assert "2 members" in summary
    assert "range 10.0-14.0" in summary


def test_elevation_summary_reports_metres() -> None:
    """Elevation summary reports metres above sea level."""
    summary = render(
        elevation_summary("Berlin", client=_client_for("api.open-meteo", _ELEVATION_BODY))
    )

    assert "Elevation of Berlin, Germany: 38 m above sea level." in summary
