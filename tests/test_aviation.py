"""Tests for the aviationweather.gov METAR client and domain summary."""

import httpx

from weather_agent.aviation import AviationClient
from weather_agent.client import OpenMeteoClient
from weather_agent.results import render
from weather_agent.weather import aviation_summary, taf_summary

_GEOCODE_BODY: dict[str, object] = {
    "results": [
        {
            "name": "Manchester",
            "country": "United Kingdom",
            "country_code": "GB",
            "latitude": 53.48,
            "longitude": -2.24,
        },
    ],
}


def _metar_body() -> list[object]:
    return [
        {
            "icaoId": "EGGP",
            "lat": 53.33,
            "lon": -2.85,
            "reportTime": "2026-06-16 12:00:00",
            "wdir": 250,
            "wspd": 8,
            "clouds": [{"cover": "FEW", "base": 3000}],
            "rawOb": "EGGP 161200Z 25008KT",
        },
        {
            "icaoId": "EGCC",
            "lat": 53.35,
            "lon": -2.28,
            "reportTime": "2026-06-16 12:00:00",
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
    report = _aviation_client(_metar_body()).nearest_metar(53.48, -2.24)

    assert report is not None
    assert report.station == "EGCC"
    assert report.wind_gust_kt == 20.0
    assert report.ceiling_ft_agl == 2500.0  # lowest BKN/OVC base


def test_nearest_metar_none_when_no_stations() -> None:
    """An empty result set yields no report rather than an error."""
    assert _aviation_client([]).nearest_metar(53.48, -2.24) is None


def test_aviation_summary_reports_observed_conditions() -> None:
    """The aviation summary renders the nearest station's observed conditions."""
    summary = render(
        aviation_summary(
            "Manchester",
            client=_geocoding_client(),
            aviation_client=_aviation_client(_metar_body()),
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
        )
    )

    assert "No aviation weather station" in summary


def _taf_body() -> list[object]:
    return [
        {
            "icaoId": "EGGP",
            "lat": 53.33,
            "lon": -2.85,
            "issueTime": "2026-06-16 11:30:00",
            "rawTAF": "TAF EGGP 161130Z 1612/1712 25008KT 9999 FEW030",
        },
        {
            "icaoId": "EGCC",
            "lat": 53.35,
            "lon": -2.28,
            "issueTime": "2026-06-16 11:30:00",
            "rawTAF": "TAF EGCC 161130Z 1612/1712 24012G22KT 6000 BKN012",
        },
    ]


def test_nearest_taf_picks_closest_station() -> None:
    """Among returned stations the geographically closest TAF is chosen."""
    report = _aviation_client(_taf_body()).nearest_taf(53.48, -2.24)

    assert report is not None
    assert report.station == "EGCC"
    assert "24012G22KT" in report.raw


def test_nearest_taf_none_when_no_stations() -> None:
    """An empty result set yields no forecast rather than an error."""
    assert _aviation_client([]).nearest_taf(53.48, -2.24) is None


def test_taf_summary_reports_nearest_forecast() -> None:
    """The TAF summary renders the nearest station's raw forecast."""
    summary = render(
        taf_summary(
            "Manchester",
            client=_geocoding_client(),
            aviation_client=_aviation_client(_taf_body()),
        )
    )

    assert "Nearest TAF for Manchester" in summary
    assert "EGCC" in summary
    assert "issued 2026-06-16 11:30:00" in summary


def test_taf_summary_notes_no_station() -> None:
    """When no station reports a TAF nearby, the summary says so."""
    summary = render(
        taf_summary(
            "Manchester",
            client=_geocoding_client(),
            aviation_client=_aviation_client([]),
        )
    )

    assert "No aviation forecast (TAF) station" in summary
