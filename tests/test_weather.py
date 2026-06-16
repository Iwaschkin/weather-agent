"""Tests for the current-weather summary domain logic."""

from datetime import date

import httpx

from weather_agent.client import OpenMeteoClient
from weather_agent.results import render
from weather_agent.weather import (
    climate_summary,
    compare_periods,
    current_weather_summary,
    forecast_summary,
    historical_summary,
    weather_for_date,
)

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


def _client_returning(geocode_body: object) -> OpenMeteoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=geocode_body)
        return httpx.Response(200, json=_FORECAST_BODY)

    return OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _daily_client() -> OpenMeteoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        return httpx.Response(200, json=_DAILY_BODY)

    return OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_summary_formats_resolved_weather() -> None:
    """A resolvable location produces a readable one-line summary."""
    summary = render(current_weather_summary("Berlin", client=_client_returning(_GEOCODE_BODY)))

    assert "Berlin, Germany" in summary
    assert "21.3" in summary
    assert "9.7" in summary


def test_summary_reports_unknown_location() -> None:
    """An unmatched location produces a not-found message, not an error."""
    summary = render(current_weather_summary("Atlantis", client=_client_returning({"results": []})))

    assert "Atlantis" in summary
    assert "No location" in summary


def test_summary_resolves_small_town_with_country_qualifier() -> None:
    """A 'Town UK' query strips the qualifier and selects the GB candidate."""
    candidates: dict[str, object] = {
        "results": [
            {
                "name": "Congleton",
                "country": "United States",
                "country_code": "US",
                "population": 300000,
                "latitude": 40.0,
                "longitude": -83.0,
            },
            {
                "name": "Congleton",
                "country": "United Kingdom",
                "country_code": "GB",
                "admin1": "England",
                "population": 26482,
                "latitude": 53.16,
                "longitude": -2.21,
            },
        ],
    }
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            captured["name"] = request.url.params["name"]
            return httpx.Response(200, json=candidates)
        return httpx.Response(200, json=_FORECAST_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(current_weather_summary("Congleton UK", client=client))

    assert captured["name"] == "Congleton"
    assert "Congleton, England, United Kingdom" in summary


def test_summary_reports_lookup_failure() -> None:
    """A transport failure is converted into an explanatory message."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(current_weather_summary("Berlin", client=client))

    assert "Could not retrieve data" in summary


def test_forecast_summary_lists_days() -> None:
    """forecast_summary renders the requested daily rows."""
    summary = render(forecast_summary("Berlin", days=2, client=_daily_client()))

    assert "Forecast for Berlin, Germany" in summary
    assert "2026-06-15" in summary
    assert "2026-06-16" in summary


def test_historical_summary_aggregates_range() -> None:
    """historical_summary reports an aggregate over the date range."""
    summary = render(
        historical_summary("Berlin", "2020-01-01", "2020-01-02", client=_daily_client())
    )

    assert "Historical weather for Berlin, Germany" in summary
    assert "max 23.5 °C" in summary


def test_climate_summary_aggregates_range() -> None:
    """climate_summary reports an aggregate over the projection range."""
    summary = render(climate_summary("Berlin", "2040-01-01", "2040-12-31", client=_daily_client()))

    assert "Climate projection for Berlin, Germany" in summary
    assert "total precipitation 4.2 mm" in summary


def test_forecast_summary_reports_unknown_location() -> None:
    """An unmatched location yields a not-found message across tools."""
    summary = render(forecast_summary("Atlantis", client=_client_returning({"results": []})))

    assert "No location" in summary


def test_weather_for_date_routes_past_to_history() -> None:
    """A past date is answered from the historical archive."""
    summary = render(
        weather_for_date("Berlin", "2020-01-01", client=_daily_client(), today=date(2026, 6, 16))
    )

    assert "Historical weather for Berlin, Germany" in summary


def test_weather_for_date_routes_near_future_to_forecast() -> None:
    """A near-future date is answered as a single forecast day, not a range."""
    summary = render(
        weather_for_date("Berlin", "2026-06-16", client=_daily_client(), today=date(2026, 6, 16))
    )

    # Offset 0 renders only the first day; the second day must not leak in.
    assert "Forecast for Berlin, Germany on 2026-06-15:" in summary
    assert "2026-06-16" not in summary


def test_weather_for_date_routes_recent_past_to_forecast() -> None:
    """A recent past date (within the archive lag) is served by the forecast endpoint.

    Regression for the ERA5 publication lag: such dates previously routed to the
    archive and came back as "no data". They now resolve and are labelled as past
    weather, not a forecast.
    """
    summary = render(
        weather_for_date("Berlin", "2026-06-14", client=_daily_client(), today=date(2026, 6, 16))
    )

    assert "Weather for Berlin, Germany on" in summary
    assert "Historical weather" not in summary
    assert "Forecast for" not in summary


def test_weather_for_date_rejects_invalid_date() -> None:
    """A malformed date yields an explanatory message, not an exception."""
    summary = render(weather_for_date("Berlin", "not-a-date", client=_daily_client()))

    assert "not a valid ISO date" in summary


def test_weather_for_date_far_future_flags_climate_estimate() -> None:
    """A date beyond the forecast horizon is labelled a model estimate."""
    summary = render(
        weather_for_date("Berlin", "2030-07-01", client=_daily_client(), today=date(2026, 6, 16))
    )

    assert "Climate projection for Berlin, Germany" in summary
    assert "not a weather forecast" in summary


def test_compare_periods_reports_comparison() -> None:
    """compare_periods reports a comparison across two archive ranges."""
    summary = render(
        compare_periods(
            "Berlin",
            ("1990-07-01", "1990-07-31"),
            ("2020-07-01", "2020-07-31"),
            client=_daily_client(),
        )
    )

    assert "Comparison for Berlin, Germany" in summary
    assert "delta" in summary


def test_weather_for_date_far_future_unresolved_omits_caveat() -> None:
    """A climate-routed but unresolved location must not gain the estimate caveat.

    Regression: the caveat was appended unconditionally, so a "not found" answer
    falsely claimed there were climate figures above it.
    """
    summary = render(
        weather_for_date(
            "Atlantis",
            "2030-07-01",
            client=_client_returning({"results": []}),
            today=date(2026, 6, 16),
        )
    )

    assert "No location matching 'Atlantis' was found." in summary
    assert "climate-model estimate" not in summary


def test_weather_for_date_far_future_empty_projection_omits_caveat() -> None:
    """A climate route returning no rows must not gain the figures caveat."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        return httpx.Response(200, json={"daily": {"time": []}})

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(
        weather_for_date("Berlin", "2030-07-01", client=client, today=date(2026, 6, 16))
    )

    assert "No climate projection data available" in summary
    assert "climate-model estimate" not in summary


def test_forecast_summary_rejects_out_of_range_days() -> None:
    """Out-of-range day counts are rejected before any network call."""
    summary = render(forecast_summary("Berlin", days=40, client=_daily_client()))

    assert "Forecast days must be between 1 and 16" in summary
