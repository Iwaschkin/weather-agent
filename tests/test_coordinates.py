"""Tests for the shared validated WGS84 coordinate boundary."""

import math

import httpx
import pytest

from weather_agent.aviation import AviationClient
from weather_agent.client import OpenMeteoClient
from weather_agent.models import Coordinates
from weather_agent.openaip import OpenAipClient
from weather_agent.results import Invalid
from weather_agent.weather import current_weather_at_coordinates


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(-90.0, -180.0), (0.0, 0.0), (90.0, 180.0)],
)
def test_coordinates_accept_wgs84_boundaries(latitude: float, longitude: float) -> None:
    """Inclusive WGS84 limits remain representable."""
    coordinates = Coordinates(latitude, longitude)

    assert coordinates.latitude == latitude
    assert coordinates.longitude == longitude


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (-90.1, 0.0),
        (90.1, 0.0),
        (0.0, -180.1),
        (0.0, 180.1),
        (math.nan, 0.0),
        (math.inf, 0.0),
        (0.0, -math.inf),
    ],
)
def test_coordinates_reject_nonfinite_or_out_of_range(
    latitude: float,
    longitude: float,
) -> None:
    """Invalid coordinate states fail at construction."""
    with pytest.raises(ValueError, match=r"latitude|longitude"):
        _ = Coordinates(latitude, longitude)


def test_public_coordinate_tool_rejects_before_http() -> None:
    """Invalid raw tool input becomes Invalid without reaching Open-Meteo."""
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    outcome = current_weather_at_coordinates(91.0, 0.0, client)

    assert isinstance(outcome, Invalid)
    assert called is False


@pytest.mark.parametrize("search_degrees", [0.0, -1.0, 5.1, math.inf])
def test_aviation_search_extent_is_validated_before_http(search_degrees: float) -> None:
    """Invalid METAR search extents cannot reach the provider."""
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = AviationClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(ValueError, match="search_degrees"):
        _ = client.nearest_metar(Coordinates(0.0, 0.0), search_degrees)

    assert called is False


@pytest.mark.parametrize("radius_m", [0, -1, 100_001, True])
def test_airspace_radius_is_validated_before_http(radius_m: int) -> None:
    """Invalid OpenAIP radii cannot reach the provider."""
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = OpenAipClient(
        api_key="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ValueError, match="radius_m"):
        _ = client.nearby_airspaces(Coordinates(0.0, 0.0), radius_m)

    assert called is False
