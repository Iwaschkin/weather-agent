"""Tests for the multi-location comparison domain logic."""

import httpx

from weather_agent.client import OpenMeteoClient
from weather_agent.reporting import describe_location_comparison
from weather_agent.results import render
from weather_agent.weather import rank_locations

# name -> (latitude, longitude, temperature_c, cloud_cover_pct)
_CITIES: dict[str, tuple[float, float, float, float]] = {
    "Tokyo": (35.68, 139.69, 30.0, 80.0),
    "Berlin": (52.52, 13.41, 21.0, 40.0),
    "London": (51.51, -0.13, 17.0, 10.0),
}


def _multi_client() -> OpenMeteoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            name = request.url.params["name"]
            city = _CITIES.get(name)
            if city is None:
                return httpx.Response(200, json={"results": []})
            lat, lon, _, _ = city
            return httpx.Response(
                200,
                json={
                    "results": [{"name": name, "country": "X", "latitude": lat, "longitude": lon}]
                },
            )
        latitude = float(request.url.params["latitude"])
        temp, cloud = next(
            (t, c) for (lat, _, t, c) in _CITIES.values() if abs(lat - latitude) < 0.01
        )
        return httpx.Response(
            200,
            json={
                "current": {
                    "time": "2026-06-17T12:00",
                    "temperature_2m": temp,
                    "wind_speed_10m": 5.0,
                    "cloud_cover": cloud,
                }
            },
        )

    return OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_rank_locations_orders_by_temperature_descending() -> None:
    """The warmest location is ranked first when ranking by temperature."""
    summary = render(
        rank_locations(("Tokyo", "Berlin", "London"), "temperature", client=_multi_client())
    )

    assert "Location comparison by temperature (highest first)" in summary
    assert summary.index("Tokyo") < summary.index("Berlin") < summary.index("London")
    assert "1. Tokyo" in summary
    assert "30.0 °C" in summary


def test_rank_locations_cloud_orders_ascending() -> None:
    """Ranking by cloud puts the least-cloudy (sunniest) location first."""
    summary = render(rank_locations(("Tokyo", "London"), "cloud", client=_multi_client()))

    assert "(lowest first)" in summary
    assert summary.index("London") < summary.index("Tokyo")


def test_rank_locations_notes_unresolved_place() -> None:
    """A location that cannot be geocoded is noted, not fatal to the comparison."""
    summary = render(rank_locations(("Tokyo", "Atlantis"), "temperature", client=_multi_client()))

    assert "1. Tokyo" in summary
    assert "Not compared: Atlantis (not found)." in summary


def test_rank_locations_rejects_unknown_metric() -> None:
    """An unknown metric is rejected before any network call."""
    summary = render(rank_locations(("Tokyo",), "spiciness"))

    assert "Unknown comparison metric" in summary


def test_rank_locations_all_unresolved_is_not_found() -> None:
    """When no location resolves, the outcome is a not-found message."""
    summary = render(rank_locations(("Atlantis",), "temperature", client=_multi_client()))

    assert "No location" in summary


def test_describe_location_comparison_renders_rank_and_problems() -> None:
    """The renderer numbers entries in order and appends a problems note."""
    text = describe_location_comparison(
        "Location comparison by wind (highest first)",
        "km/h",
        (("Berlin, X", 30.0), ("London, X", 12.0)),
        ("Atlantis (not found)",),
    )

    assert "1. Berlin, X: 30.0 km/h" in text
    assert "2. London, X: 12.0 km/h" in text
    assert "Not compared: Atlantis (not found)." in text
