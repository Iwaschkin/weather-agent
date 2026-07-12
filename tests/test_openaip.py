"""Tests for the OpenAIP airspace client and domain summary."""

import httpx
import pytest

from weather_agent.client import OpenMeteoClient
from weather_agent.models import Airspace, Coordinates
from weather_agent.openaip import OpenAipClient, relevant_airspaces
from weather_agent.parsing import AirspaceError
from weather_agent.results import render
from weather_agent.weather import airspace_summary

_GEOCODE_BODY: dict[str, object] = {
    "results": [
        {
            "name": "Congleton",
            "country": "United Kingdom",
            "country_code": "GB",
            "admin1": "England",
            "latitude": 53.16,
            "longitude": -2.21,
            "timezone": "Europe/London",
        },
    ],
}
_CONGLETON = Coordinates(53.16, -2.21)


def _airspace_body() -> dict[str, object]:
    return {
        "items": [
            {
                "name": "MANCHESTER CTR",
                "type": 4,
                "icaoClass": 3,
                "lowerLimit": {"value": 0, "unit": 1, "referenceDatum": 0},
            },
            {
                "name": "PENNINE TMA",
                "type": 7,  # TMA - high-level, filtered out for drones
                "icaoClass": 3,
                "lowerLimit": {"value": 6500, "unit": 1, "referenceDatum": 1},
            },
            {
                "name": "DANGER D123",
                "type": 2,
                "icaoClass": 8,
                "lowerLimit": {"value": 0, "unit": 1, "referenceDatum": 0},
            },
        ],
    }


def _openaip(api_key: str, body: object) -> OpenAipClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.core.openaip.net"
        assert request.headers["x-openaip-api-key"] == api_key
        assert request.url.params["pos"] == "53.16,-2.21"
        return httpx.Response(200, json=body)

    return OpenAipClient(
        api_key=api_key, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _geocoding_client() -> OpenMeteoClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_GEOCODE_BODY)

    return OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_has_key_reflects_configuration() -> None:
    """has_key is True only when a non-empty key is configured."""
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"items": []}))
    assert OpenAipClient(api_key="k", client=httpx.Client(transport=transport)).has_key
    assert not OpenAipClient(api_key="", client=httpx.Client(transport=transport)).has_key


def test_relevant_airspaces_drops_high_level_types() -> None:
    """The relevance filter keeps surface types and drops high-level ones."""
    ctr = Airspace(name="X CTR", type_label="CTR", icao_class="D", lower_limit="GND")
    tma = Airspace(name="Y TMA", type_label="TMA", icao_class="D", lower_limit="6500 ft MSL")

    assert relevant_airspaces((ctr, tma)) == (ctr,)


def test_nearby_airspaces_requests_and_filters() -> None:
    """The client sends pos/key and returns only drone-relevant airspaces."""
    spaces = _openaip("test-key", _airspace_body()).nearby_airspaces(_CONGLETON)

    names = [space.name for space in spaces]
    assert "MANCHESTER CTR" in names
    assert "DANGER D123" in names
    assert "PENNINE TMA" not in names


def test_nearby_airspaces_normalizes_invalid_json() -> None:
    """A successful non-JSON response uses the OpenAIP provider error type."""
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"{"))
    client = OpenAipClient(api_key="test", client=httpx.Client(transport=transport))

    with pytest.raises(AirspaceError, match="not valid JSON"):
        _ = client.nearby_airspaces(_CONGLETON)


def test_airspace_summary_lists_zones() -> None:
    """The airspace summary renders nearby zones with a verify reminder."""
    summary = render(
        airspace_summary(
            "Congleton",
            client=_geocoding_client(),
            openaip_client=_openaip("test-key", _airspace_body()),
        )
    )

    assert "MANCHESTER CTR (CTR, ICAO D, base GND)" in summary
    assert "verify" in summary.lower()


def test_airspace_summary_without_key_reports_unavailable() -> None:
    """With no key the summary reports the check is unavailable, not an error."""
    no_key = OpenAipClient(
        api_key="",
        client=httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200))),
    )

    summary = render(
        airspace_summary("Congleton", client=_geocoding_client(), openaip_client=no_key)
    )

    assert "unavailable (no OPENAIP_API_KEY configured)" in summary
