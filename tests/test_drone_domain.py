"""Tests for drone assessment rendering and the drone domain summary."""

from datetime import datetime

import httpx
import pytest

from weather_agent.aviation import AviationClient
from weather_agent.caa import caa_guidance
from weather_agent.client import OpenMeteoClient
from weather_agent.drone import DRONE_PROFILES, MINI_5_PRO
from weather_agent.drone_report import (
    describe_drone_assessment,
    describe_fleet_assessment,
    describe_supported_drones,
    reconcile_metar,
)
from weather_agent.knowledge import KnowledgeSection
from weather_agent.models import (
    DataConfidence,
    DayAlmanac,
    DayOutlook,
    DroneAssessment,
    DroneFlightHour,
    FleetMember,
    FlightWindow,
    HourAssessment,
    MetarReport,
    SiteBriefing,
    Verdict,
)
from weather_agent.openaip import OpenAipClient
from weather_agent.results import render
from weather_agent.weather import (
    SiteClients,
    assess_fleet,
    drone_flight_summary,
    fleet_flight_summary,
)

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
            "timezone": "Europe/London",
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
# Ensemble gusts (UTC) aligned to the 10:00/11:00 BST forecast hours; tight member
# spread, so it never triggers a forecast-confidence downgrade in the shared tests.
_ENSEMBLE_BODY: dict[str, object] = {
    "hourly": {
        "time": ["2026-06-16T09:00", "2026-06-16T10:00"],
        "wind_gusts_10m_member01": [10.0, 10.0],
        "wind_gusts_10m_member02": [11.0, 11.0],
    },
}
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
# A METAR reporting a gust and visibility, for the observed-vs-forecast check.
_METAR_WITH_GUST: list[object] = [
    {
        "icaoId": "EGCC",
        "lat": 53.35,
        "lon": -2.28,
        "reportTime": "2026-06-16 09:00:00",
        "wdir": 240,
        "wspd": 8,
        "wgst": 25,
        "visib": 6,
        "clouds": [{"cover": "FEW", "base": 4000}],
        "rawOb": "EGCC 160900Z 24008G25KT 6SM",
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


def test_describe_drone_assessment_flags_incomplete_data() -> None:
    """An hour capped at marginal for missing data adds a data-confidence caveat."""
    assessment = DroneAssessment(
        drone_name="DJI Mini 5 Pro",
        place_label="Congleton, England",
        hours=(
            HourAssessment(
                "10:00",
                Verdict.MARGINAL,
                ("visibility data unavailable",),
                4.0,
                data_confidence=DataConfidence.INSUFFICIENT,
            ),
        ),
        best_window=None,
    )

    text = describe_drone_assessment(assessment, caa_guidance(MINI_5_PRO), ())

    assert "Data confidence: 1 hour had incomplete safety data" in text


def test_describe_drone_assessment_omits_confidence_caveat_when_complete() -> None:
    """A fully-adequate assessment carries no data-confidence caveat."""
    assessment = DroneAssessment(
        drone_name="DJI Mini 5 Pro",
        place_label="Congleton, England",
        hours=(HourAssessment("10:00", Verdict.GOOD, (), 4.0),),
        best_window=FlightWindow("10:00", "10:00", 1),
    )

    text = describe_drone_assessment(assessment, caa_guidance(MINI_5_PRO), ())

    assert "Data confidence:" not in text


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
        if request.url.host.startswith("ensemble"):
            return httpx.Response(200, json=_ENSEMBLE_BODY)
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
        if request.url.host.startswith("ensemble"):
            return httpx.Response(200, json=_ENSEMBLE_BODY)
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


def test_drone_flight_summary_flags_forecast_uncertainty() -> None:
    """A wide ensemble spread near the gust limit surfaces a forecast-confidence caveat."""
    near_limit_body: dict[str, object] = {
        "elevation": 120.0,
        "hourly": {
            "time": ["2026-06-16T10:00"],
            "wind_gusts_10m": [40.0],
            "wind_speed_10m": [30.0],
            "wind_max_0_500m_kmh": [40.0],  # ~11.1 m/s, just under the 12 m/s limit
            "temperature_2m": [16.0],
            "precipitation": [0.0],
            "precipitation_probability": [0.0],
            "visibility": [30000.0],
            "is_day": [1.0],
            "cape": [0.0],
        },
    }
    wide_ensemble: dict[str, object] = {
        "hourly": {
            "time": ["2026-06-16T09:00"],
            "wind_gusts_10m_member01": [20.0],
            "wind_gusts_10m_member02": [60.0],  # ~11 m/s spread, far wider than the margin
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        if request.url.host == "services.swpc.noaa.gov":
            return httpx.Response(200, json=_KP_BODY)
        if request.url.host.startswith("ensemble"):
            return httpx.Response(200, json=wide_ensemble)
        return httpx.Response(200, json=near_limit_body)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(
        drone_flight_summary(
            "Congleton UK", "Mini 5 Pro", client=client, now=_NOW, site_clients=_site_clients([])
        )
    )

    assert "Forecast confidence:" in summary
    assert "ensemble spread" in summary


def test_drone_flight_summary_requests_location_timezone() -> None:
    """The drone forecast is requested in the resolved location's own timezone."""
    requested: dict[str, str] = {}
    tokyo_geocode: dict[str, object] = {
        "results": [
            {
                "name": "Tokyo",
                "country": "Japan",
                "country_code": "JP",
                "admin1": "Tokyo",
                "latitude": 35.68,
                "longitude": 139.76,
                "timezone": "Asia/Tokyo",
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=tokyo_geocode)
        if request.url.host == "services.swpc.noaa.gov":
            return httpx.Response(503)
        if request.url.host.startswith("ensemble"):
            return httpx.Response(503)
        if "hourly" in request.url.params:  # the drone forecast, not the sun-times almanac
            requested["timezone"] = request.url.params.get("timezone", "")
        return httpx.Response(200, json=_DRONE_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    _ = render(
        drone_flight_summary(
            "Tokyo", "Neo", client=client, now=_NOW, site_clients=_site_clients([])
        )
    )

    assert requested["timezone"] == "Asia/Tokyo"


def test_drone_flight_summary_survives_kp_outage() -> None:
    """A NOAA Kp failure does not break the assessment (best-effort)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        if request.url.host == "services.swpc.noaa.gov":
            return httpx.Response(503)
        if request.url.host.startswith("ensemble"):
            return httpx.Response(200, json=_ENSEMBLE_BODY)
        return httpx.Response(200, json=_DRONE_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(
        drone_flight_summary(
            "Congleton UK", "Neo", client=client, now=_NOW, site_clients=_site_clients([])
        )
    )

    assert "DJI Neo at Congleton, England" in summary


def _fleet_members() -> tuple[FleetMember, ...]:
    return tuple(
        FleetMember(
            profile=profile,
            assessment=DroneAssessment(
                drone_name=profile.name,
                place_label="Congleton, England",
                hours=(HourAssessment("2026-06-16T10:00", Verdict.GOOD, (), 4.0),),
                best_window=FlightWindow("2026-06-16T10:00", "2026-06-16T10:00", 1),
                daily=(
                    DayOutlook(
                        "2026-06-16",
                        1,
                        FlightWindow("2026-06-16T10:00", "2026-06-16T10:00", 1),
                    ),
                ),
            ),
            guidance=caa_guidance(profile),
        )
        for profile in DRONE_PROFILES
    )


def test_describe_fleet_assessment_covers_every_drone_with_shared_context() -> None:
    """The fleet report names every drone but renders shared context only once."""
    text = describe_fleet_assessment(_fleet_members(), "Congleton, England")

    assert "Fleet flight assessment - 3 drones at Congleton, England" in text
    assert "Fleet comparison" in text
    for profile in DRONE_PROFILES:
        assert profile.name in text
    # The CAA rules and disclaimer are shared, not repeated per drone.
    assert text.count("UK CAA notes (all drones") == 1
    assert text.count("not legal") == 1


def test_describe_fleet_assessment_handles_no_members() -> None:
    """An empty fleet yields a short message rather than an empty report."""
    assert "No supported drones" in describe_fleet_assessment((), "Congleton")


def test_fleet_flight_summary_assesses_all_supported_drones() -> None:
    """One fleet call covers every drone with the site context fetched once."""
    summary = render(
        fleet_flight_summary(
            "Congleton UK",
            client=_drone_client(),
            now=_NOW,
            site_clients=_site_clients(_METAR_BODY, _AIRSPACE_BODY),
        )
    )

    assert "Fleet flight assessment - 3 drones at Congleton, England" in summary
    assert "DJI Neo" in summary
    assert "DJI Avata 2" in summary
    assert "DJI Mini 5 Pro" in summary
    # METAR and disclaimer are shared site context, rendered once for the fleet.
    assert summary.count("Nearest METAR") == 1
    assert "MANCHESTER CTR" in summary
    assert summary.count("not legal") == 1


def _flight_hour(gust_kmh: float | None, visibility_m: float | None) -> DroneFlightHour:
    return DroneFlightHour(
        time="2026-06-16T10:00",
        temperature_c=16.0,
        apparent_temperature_c=16.0,
        wind_gust_10m_kmh=gust_kmh,
        wind_max_0_500m_kmh=gust_kmh or 0.0,
        precipitation_mm=0.0,
        precipitation_probability_pct=0.0,
        visibility_m=visibility_m,
        cape=0.0,
        freezing_level_agl_m=2500.0,
        is_day=True,
        cloud_cover_low_pct=10.0,
    )


def _metar(gust_kt: float | None = None, vis_sm: float | None = None) -> MetarReport:
    return MetarReport(
        station="EGCC",
        latitude=53.35,
        longitude=-2.28,
        observed="2026-06-16 09:00:00",
        wind_dir_deg=240.0,
        wind_speed_kt=8.0,
        wind_gust_kt=gust_kt,
        visibility_sm=vis_sm,
        clouds=(),
        ceiling_ft_agl=None,
        raw="EGCC 160900Z",
    )


def test_reconcile_metar_flags_close_gust() -> None:
    """A gust within tolerance of the forecast gust reads as close."""
    # 20 kt ~ 10.3 m/s; 36 km/h = 10.0 m/s -> within 2.5 m/s.
    note = reconcile_metar(_metar(gust_kt=20.0), _flight_hour(36.0, None))

    assert note is not None
    assert "gusts" in note
    assert "(close)" in note


def test_reconcile_metar_flags_diverging_gust() -> None:
    """A much stronger observed gust is reported with the direction of the gap."""
    # 30 kt ~ 15.4 m/s vs 18 km/h = 5 m/s.
    note = reconcile_metar(_metar(gust_kt=30.0), _flight_hour(18.0, None))

    assert note is not None
    assert "stronger" in note


def test_reconcile_metar_flags_lower_visibility() -> None:
    """Observed visibility well below the forecast is flagged as lower."""
    # 3 SM ~ 4.8 km vs 20 km forecast.
    note = reconcile_metar(_metar(vis_sm=3.0), _flight_hour(None, 20000.0))

    assert note is not None
    assert "visibility" in note
    assert "observed lower" in note


def test_reconcile_metar_returns_none_when_nothing_comparable() -> None:
    """With no observed gust and no visibility, there is nothing to reconcile."""
    assert reconcile_metar(_metar(), _flight_hour(36.0, 20000.0)) is None


def test_drone_flight_summary_reconciles_metar_with_forecast() -> None:
    """A gust-and-visibility METAR yields an observed-vs-forecast line in the report."""
    summary = render(
        drone_flight_summary(
            "Congleton UK",
            "Mini 5 Pro",
            client=_drone_client(),
            now=_NOW,
            site_clients=_site_clients(_METAR_WITH_GUST, _AIRSPACE_BODY),
        )
    )

    assert "Observed vs forecast (now):" in summary
    assert "gusts" in summary
    assert "visibility" in summary


def test_assess_fleet_returns_structured_members() -> None:
    """The structured path returns typed per-drone assessments, not text."""
    result = assess_fleet(
        "Congleton UK",
        days=7,
        client=_drone_client(),
        now=_NOW,
        site_clients=_site_clients(_METAR_BODY, _AIRSPACE_BODY),
    )

    assert result is not None
    assert "Congleton, England" in result.place_label
    assert tuple(member.profile.name for member in result.members) == (
        "DJI Neo",
        "DJI Avata 2",
        "DJI Mini 5 Pro",
    )
    assert all(member.assessment.hours for member in result.members)


def test_assess_fleet_unknown_location_is_none() -> None:
    """An unresolvable location yields None rather than raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json=_DRONE_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert assess_fleet("Nowheresville", client=client, site_clients=_site_clients([])) is None


@pytest.mark.parametrize("days", [0, 8])
def test_assess_fleet_rejects_out_of_range_days(days: int) -> None:
    """Day counts outside 1..7 are rejected before any network call."""
    with pytest.raises(ValueError, match="days must be between"):
        _ = assess_fleet("Congleton UK", days=days)
