"""Tests for drone assessment rendering and the drone domain summary."""

from datetime import datetime

import httpx

from weather_agent.aviation import AviationClient
from weather_agent.caa import caa_guidance
from weather_agent.client import OpenMeteoClient
from weather_agent.drone import DRONE_PROFILES, MINI_5_PRO
from weather_agent.drone_report import describe_drone_assessment, describe_supported_drones
from weather_agent.knowledge import KnowledgeSection
from weather_agent.models import (
    DayAlmanac,
    DayOutlook,
    DroneAssessment,
    FlightWindow,
    HourAssessment,
    SiteBriefing,
    Verdict,
)
from weather_agent.openaip import OpenAipClient
from weather_agent.results import render
from weather_agent.weather import SiteClients, drone_flight_summary

# Fixed reference time so the fixture's 10:00/11:00 hours are never filtered as past.
_NOW = datetime(2026, 6, 16, 9, 0)  # noqa: DTZ001

_GEOCODE_BODY: dict[str, object] = {
    "results": [
        {
            "name": "Congleton",
            "country": "United Kingdom",
            "country_code": "GB",
            "admin1": "England",
            "latitude": 53.16,
            "longitude": -2.21,
        },
    ],
}
_DRONE_BODY: dict[str, object] = {
    "elevation": 120.0,
    "hourly": {
        "time": ["2026-06-16T10:00", "2026-06-16T11:00"],
        "wind_gusts_10m": [12.0, 60.0],
        "wind_speed_10m": [10.0, 40.0],
        "wind_max_0_500m_kmh": [15.0, 60.0],
        "temperature_2m": [16.0, 16.0],
        "precipitation": [0.0, 0.0],
        "precipitation_probability": [0.0, 0.0],
        "visibility": [30000.0, 30000.0],
        "is_day": [1.0, 1.0],
        "cape": [0.0, 0.0],
    },
}
_KP_BODY: list[object] = [
    ["time_tag", "Kp"],
    ["2026-06-16 09:00:00", "2"],
]
_METAR_BODY: list[object] = [
    {
        "icaoId": "EGCC",
        "lat": 53.35,
        "lon": -2.28,
        "reportTime": "2026-06-16 09:00:00",
        "wdir": 240,
        "wspd": 8,
        "clouds": [{"cover": "FEW", "base": 4000}],
        "rawOb": "EGCC 160900Z 24008KT",
    },
]


_AIRSPACE_BODY: dict[str, object] = {
    "items": [
        {
            "name": "MANCHESTER CTR",
            "type": 4,
            "icaoClass": 3,
            "lowerLimit": {"value": 0, "unit": 1, "referenceDatum": 0},
        },
    ],
}


def _aviation(body: object) -> AviationClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return AviationClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _openaip(api_key: str, body: object) -> OpenAipClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return OpenAipClient(
        api_key=api_key, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _site_clients(metar_body: object, airspace_body: object | None = None) -> SiteClients:
    # An empty key short-circuits the airspace lookup (no network) for tests that
    # do not care about it; a real key + body exercises the airspace path.
    if airspace_body is None:
        openaip = _openaip("", {"items": []})
    else:
        openaip = _openaip("test-key", airspace_body)
    return SiteClients(aviation=_aviation(metar_body), openaip=openaip)


def test_describe_drone_assessment_includes_all_sections() -> None:
    """The rendered assessment carries verdicts, CAA notes, tips, disclaimer."""
    assessment = DroneAssessment(
        drone_name="DJI Mini 5 Pro",
        place_label="Congleton, England",
        hours=(
            HourAssessment("10:00", Verdict.GOOD, (), 4.0),
            HourAssessment("11:00", Verdict.NO_FLY, ("gusts ~17 m/s exceed the limit",), 17.0),
        ),
        best_window=FlightWindow("10:00", "10:00", 1),
    )
    tips = (KnowledgeSection("Wind and gusts", "Mind the gusts.", frozenset({"gusts"})),)

    text = describe_drone_assessment(assessment, caa_guidance(MINI_5_PRO), tips)

    assert "DJI Mini 5 Pro at Congleton, England" in text
    assert "Best window: 10:00 to 10:00" in text
    assert "NO-FLY - gusts" in text
    assert "UK CAA notes" in text
    assert "Wind and gusts: Mind the gusts." in text
    assert "not legal" in text.lower()


def test_describe_drone_assessment_renders_daylight_and_daily_outlook() -> None:
    """Sun times produce a daylight line and the daily outlook is listed."""
    assessment = DroneAssessment(
        drone_name="DJI Mini 5 Pro",
        place_label="Congleton, England",
        hours=(HourAssessment("2026-06-16T10:00", Verdict.GOOD, (), 4.0),),
        best_window=FlightWindow("2026-06-16T10:00", "2026-06-16T10:00", 1),
        daily=(
            DayOutlook(
                date="2026-06-16",
                good_hours=1,
                best_window=FlightWindow("2026-06-16T10:00", "2026-06-16T10:00", 1),
            ),
        ),
    )
    sun_times = (
        DayAlmanac(
            date="2026-06-16",
            sunrise="2026-06-16T04:43",
            sunset="2026-06-16T21:21",
            daylight_seconds=59880.0,
        ),
    )

    text = describe_drone_assessment(
        assessment, caa_guidance(MINI_5_PRO), (), SiteBriefing(sun_times=sun_times)
    )

    assert "Daylight: sunrise 04:43, sunset 21:21" in text
    assert "Daily outlook:" in text
    assert "2026-06-16: 1 good h, best 10:00-10:00" in text


def test_describe_drone_assessment_notes_empty_outlook() -> None:
    """When every hour has elapsed, the outlook says so instead of an empty list."""
    assessment = DroneAssessment(
        drone_name="DJI Mini 5 Pro",
        place_label="Congleton, England",
        hours=(),
        best_window=None,
    )

    text = describe_drone_assessment(assessment, caa_guidance(MINI_5_PRO), ())

    assert "No upcoming forecast hours in the assessment window." in text


def test_describe_supported_drones_lists_all() -> None:
    """The supported-drones listing names every profile."""
    text = describe_supported_drones(DRONE_PROFILES)

    assert "DJI Neo" in text
    assert "DJI Avata 2" in text
    assert "DJI Mini 5 Pro" in text


def _drone_client() -> OpenMeteoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        if request.url.host == "services.swpc.noaa.gov":
            return httpx.Response(200, json=_KP_BODY)
        return httpx.Response(200, json=_DRONE_BODY)

    return OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_drone_flight_summary_assesses_known_drone() -> None:
    """A known drone at a resolvable place yields a full assessment with METAR."""
    summary = render(
        drone_flight_summary(
            "Congleton UK",
            "Mini 5 Pro",
            client=_drone_client(),
            now=_NOW,
            site_clients=_site_clients(_METAR_BODY, _AIRSPACE_BODY),
        )
    )

    assert "DJI Mini 5 Pro at Congleton, England" in summary
    assert "Hourly outlook" in summary
    assert "UK CAA notes" in summary
    assert "Nearest METAR" in summary
    assert "EGCC" in summary
    assert "Airspace near" in summary
    assert "MANCHESTER CTR" in summary


def test_drone_flight_summary_rejects_unknown_drone() -> None:
    """An unknown drone lists the supported models without any lookup."""
    summary = render(drone_flight_summary("Congleton UK", "Phantom 9", client=_drone_client()))

    assert "Supported drones" in summary
    assert "DJI Mini 5 Pro" in summary


def test_drone_flight_summary_applies_per_hour_kp_forecast() -> None:
    """The Kp forecast varies per hour: a later 3-hour bucket can flag a storm.

    Exercises the UK-local-to-UTC bucket alignment: 10:00 BST -> 09:00 UTC (quiet)
    is good, while 11:00 BST -> 10:00 UTC (Kp 6) is marginal for geomagnetic risk.
    """
    calm_body: dict[str, object] = {
        "elevation": 120.0,
        "hourly": {
            "time": ["2026-06-16T10:00", "2026-06-16T11:00"],
            "wind_gusts_10m": [12.0, 12.0],
            "wind_speed_10m": [10.0, 10.0],
            "temperature_2m": [16.0, 16.0],
            "precipitation": [0.0, 0.0],
            "precipitation_probability": [0.0, 0.0],
            "visibility": [30000.0, 30000.0],
            "is_day": [1.0, 1.0],
            "cape": [0.0, 0.0],
        },
    }
    kp_forecast: list[object] = [
        ["time_tag", "kp", "observed", "noaa_scale"],
        ["2026-06-16 09:00:00", "2.00", "predicted", None],
        ["2026-06-16 10:00:00", "6.00", "predicted", None],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        if request.url.host == "services.swpc.noaa.gov":
            return httpx.Response(200, json=kp_forecast)
        return httpx.Response(200, json=calm_body)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(
        drone_flight_summary(
            "Congleton UK",
            "Mini 5 Pro",
            client=client,
            now=_NOW,
            site_clients=_site_clients([]),
        )
    )

    assert "2026-06-16T10:00  GOOD" in summary
    assert "2026-06-16T11:00  MARGINAL" in summary
    assert "geomagnetic" in summary


def test_drone_flight_summary_survives_kp_outage() -> None:
    """A NOAA Kp failure does not break the assessment (best-effort)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        if request.url.host == "services.swpc.noaa.gov":
            return httpx.Response(503)
        return httpx.Response(200, json=_DRONE_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(
        drone_flight_summary(
            "Congleton UK", "Neo", client=client, now=_NOW, site_clients=_site_clients([])
        )
    )

    assert "DJI Neo at Congleton, England" in summary
