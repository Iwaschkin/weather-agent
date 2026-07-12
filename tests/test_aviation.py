"""Tests for the aviationweather.gov METAR client and domain summary."""

from datetime import UTC, datetime

import httpx
import pytest

from weather_agent.aviation import AviationClient
from weather_agent.client import OpenMeteoClient
from weather_agent.models import Coordinates
from weather_agent.parsing import AviationError
from weather_agent.results import render
from weather_agent.weather import aviation_summary

_GEOCODE_BODY: dict[str, object] = {
    "results": [
        {
            "name": "Manchester",
            "country": "United Kingdom",
            "country_code": "GB",
            "latitude": 53.48,
            "longitude": -2.24,
            "timezone": "Europe/London",
        },
    ],
}
_MANCHESTER = Coordinates(53.48, -2.24)


def _metar_body(observed: str = "2026-06-16T12:00:00Z") -> list[object]:
    return [
        {
            "icaoId": "EGGP",
            "lat": 53.33,
            "lon": -2.85,
            "reportTime": observed,
            "wdir": 250,
            "wspd": 8,
            "clouds": [{"cover": "FEW", "base": 3000}],
            "rawOb": "EGGP 161200Z 25008KT",
        },
        {
            "icaoId": "EGCC",
            "lat": 53.35,
            "lon": -2.28,
            "reportTime": observed,
            "wdir": 240,
            "wspd": 12,
            "wgst": 20,
            "visib": "10+",
            "clouds": [{"cover": "BKN", "base": 2500}, {"cover": "OVC", "base": 4000}],
            "rawOb": "EGCC 161200Z 24012G20KT",
        },
    ]


def _aviation_client(body: object) -> AviationClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "aviationweather.gov"
        return httpx.Response(200, json=body)

    return AviationClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _geocoding_client() -> OpenMeteoClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_GEOCODE_BODY)

    return OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_nearest_metar_picks_closest_station() -> None:
    """Among returned stations the geographically closest one is chosen."""
    report = _aviation_client(_metar_body()).nearest_metar(_MANCHESTER)

    assert report is not None
    assert report.station == "EGCC"
    assert report.wind_gust_kt == 20.0
    assert report.ceiling_ft_agl == 2500.0  # lowest BKN/OVC base


def test_nearest_metar_none_when_no_stations() -> None:
    """An empty result set yields no report rather than an error."""
    assert _aviation_client([]).nearest_metar(_MANCHESTER) is None


def test_nearest_metar_handles_documented_no_content() -> None:
    """The provider's documented 204 response means no recent report, not malformed JSON."""
    transport = httpx.MockTransport(lambda _request: httpx.Response(204))
    client = AviationClient(client=httpx.Client(transport=transport))

    assert client.nearest_metar(_MANCHESTER) is None


def test_nearest_metar_normalizes_invalid_json() -> None:
    """A successful non-JSON response uses the aviation provider error type."""
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"{"))
    client = AviationClient(client=httpx.Client(transport=transport))

    with pytest.raises(AviationError, match="not valid JSON"):
        _ = client.nearest_metar(_MANCHESTER)


def test_aviation_summary_reports_observed_conditions() -> None:
    """The aviation summary renders the nearest station's observed conditions."""
    summary = render(
        aviation_summary(
            "Manchester",
            client=_geocoding_client(),
            aviation_client=_aviation_client(_metar_body()),
            now=datetime(2026, 6, 16, 12, 30, tzinfo=UTC),
        )
    )

    assert "Nearest METAR for Manchester" in summary
    assert "EGCC" in summary
    assert "ceiling 2500 ft" in summary


def test_aviation_summary_notes_no_station() -> None:
    """When no station reports nearby, the summary says so."""
    summary = render(
        aviation_summary(
            "Manchester",
            client=_geocoding_client(),
            aviation_client=_aviation_client([]),
            now=datetime(2026, 6, 16, 12, 30, tzinfo=UTC),
        )
    )

    assert "No aviation weather station" in summary


@pytest.mark.parametrize(
    ("observed", "now", "expected"),
    [
        (
            "2026-06-16T09:00:00Z",
            datetime(2026, 6, 16, 12, tzinfo=UTC),
            "180 minutes old",
        ),
        (
            "2026-06-16T13:00:00Z",
            datetime(2026, 6, 16, 12, tzinfo=UTC),
            "60 minutes in the future",
        ),
    ],
)
def test_aviation_summary_rejects_noncurrent_observation(
    observed: str,
    now: datetime,
    expected: str,
) -> None:
    """Stale and materially future METARs are never presented as current."""
    summary = render(
        aviation_summary(
            "Manchester",
            client=_geocoding_client(),
            aviation_client=_aviation_client(_metar_body(observed)),
            now=now,
        )
    )

    assert "not presented as current" in summary
    assert expected in summary
    assert "ceiling 2500 ft" not in summary
