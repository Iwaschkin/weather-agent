"""Tests for drone assessment rendering and the drone domain summary."""

from dataclasses import replace
from datetime import UTC, date, datetime

import httpx
import pytest

from tests.time_helpers import LONDON_SUMMER_CONTEXT, aware, epoch, time_metadata
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
    Coordinates,
    DayAlmanac,
    DayOutlook,
    DroneAssessment,
    DroneFlightHour,
    FleetMember,
    FlightWindow,
    HourAssessment,
    KpForecastEntry,
    KpRowKind,
    MetarReport,
    SiteBriefing,
    Verdict,
)
from weather_agent.openaip import OpenAipClient
from weather_agent.results import render
from weather_agent.space_weather import SpaceWeatherClient
from weather_agent.weather import (
    SiteClients,
    UnsupportedJurisdictionError,
    _drone_kp_by_hour,
    _nearest_forecast_hour,
    _resolve_kp_by_hour,
    assess_fleet,
    drone_flight_summary,
    fleet_flight_summary,
)

# Fixed reference time aligned with the 09:00 UTC METAR and first 10:00 BST row.
_NOW = aware("2026-06-16T10:00")

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
    **time_metadata(),
    "elevation": 120.0,
    "hourly": {
        "time": [epoch("2026-06-16T10:00"), epoch("2026-06-16T11:00")],
        "wind_gusts_10m": [12.0, 60.0],
        "wind_speed_10m": [10.0, 40.0],
        "wind_speed_80m": [10.0, 40.0],
        "wind_speed_120m": [10.0, 40.0],
        "wind_speed_180m": [10.0, 40.0],
        "wind_max_0_500m_kmh": [15.0, 60.0],
        "temperature_2m": [16.0, 16.0],
        "apparent_temperature": [16.0, 16.0],
        "precipitation": [0.0, 0.0],
        "precipitation_probability": [0.0, 0.0],
        "visibility": [30000.0, 30000.0],
        "is_day": [1.0, 1.0],
        "cape": [0.0, 0.0],
        "freezing_level_height": [2500.0, 2500.0],
        "cloud_cover_low": [10.0, 10.0],
        "wind_speed_950hPa": [10.0, 40.0],
        "wind_speed_925hPa": [10.0, 40.0],
        "wind_speed_900hPa": [10.0, 40.0],
        "geopotential_height_950hPa": [550.0, 550.0],
        "geopotential_height_925hPa": [800.0, 800.0],
        "geopotential_height_900hPa": [1000.0, 1000.0],
    },
}
_ALMANAC_BODY: dict[str, object] = {
    **time_metadata(),
    "daily": {
        "time": [epoch("2026-06-16T00:00")],
        "sunrise": [epoch("2026-06-16T04:43")],
        "sunset": [epoch("2026-06-16T21:21")],
        "daylight_duration": [59880.0],
    },
}
_KP_CURRENT_BODY: list[object] = [
    {"time_tag": "2026-06-16T09:00:00", "Kp": 2.0},
]
_KP_FORECAST_BODY: list[object] = [
    {
        "time_tag": "2026-06-16T09:00:00",
        "kp": 2.0,
        "observed": "predicted",
        "noaa_scale": None,
    },
]
_METAR_BODY: list[object] = [
    {
        "icaoId": "EGCC",
        "lat": 53.35,
        "lon": -2.28,
        "reportTime": "2026-06-16T09:00:00Z",
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
        "reportTime": "2026-06-16T09:00:00Z",
        "wdir": 240,
        "wspd": 8,
        "wgst": 25,
        "visib": 6,
        "clouds": [{"cover": "FEW", "base": 4000}],
        "rawOb": "EGCC 160900Z 24008G25KT 6SM",
    },
]
_STALE_METAR_BODY: list[object] = [
    {
        "icaoId": "EGCC",
        "lat": 53.35,
        "lon": -2.28,
        "reportTime": "2026-06-16T06:00:00Z",
        "wdir": 240,
        "wspd": 8,
        "rawOb": "EGCC 160600Z 24008KT",
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


def _aviation_status(status: int) -> AviationClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    return AviationClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _openaip(api_key: str, body: object) -> OpenAipClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return OpenAipClient(
        api_key=api_key, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _space_weather(
    forecast_body: object = _KP_FORECAST_BODY,
    current_body: object = _KP_CURRENT_BODY,
    status: int = 200,
) -> SpaceWeatherClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = forecast_body if "forecast" in request.url.path else current_body
        return httpx.Response(status, json=body)

    return SpaceWeatherClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _site_clients(
    metar_body: object,
    airspace_body: object | None = None,
    space_weather: SpaceWeatherClient | None = None,
) -> SiteClients:
    # An empty key short-circuits the airspace lookup (no network) for tests that
    # do not care about it; a real key + body exercises the airspace path.
    if airspace_body is None:
        openaip = _openaip("", {"items": []})
    else:
        openaip = _openaip("test-key", airspace_body)
    return SiteClients(
        aviation=_aviation(metar_body),
        openaip=openaip,
        space_weather=space_weather if space_weather is not None else _space_weather(),
    )


def test_describe_drone_assessment_includes_all_sections() -> None:
    """The rendered assessment carries verdicts, CAA notes, tips, disclaimer."""
    assessment = DroneAssessment(
        drone_name="DJI Mini 5 Pro",
        place_label="Congleton, England",
        hours=(
            HourAssessment(aware("2026-06-16T10:00"), Verdict.GOOD, (), 4.0),
            HourAssessment(
                aware("2026-06-16T11:00"),
                Verdict.NO_FLY,
                ("gusts ~17 m/s exceed the limit",),
                17.0,
            ),
        ),
        best_window=FlightWindow(aware("2026-06-16T10:00"), aware("2026-06-16T10:00"), 1),
        time_context=LONDON_SUMMER_CONTEXT,
    )
    tips = (KnowledgeSection("Wind and gusts", "Mind the gusts.", frozenset({"gusts"})),)

    text = describe_drone_assessment(assessment, caa_guidance(MINI_5_PRO), tips)

    assert "DJI Mini 5 Pro at Congleton, England" in text
    assert "Best window: 2026-06-16 10:00 BST to 2026-06-16 10:00 BST" in text
    assert "NO-FLY - gusts" in text
    assert "UK CAA notes" in text
    assert "Wind and gusts: Mind the gusts." in text
    assert "not legal" in text.lower()


def test_describe_drone_assessment_renders_daylight_and_daily_outlook() -> None:
    """Sun times produce a daylight line and the daily outlook is listed."""
    assessment = DroneAssessment(
        drone_name="DJI Mini 5 Pro",
        place_label="Congleton, England",
        hours=(HourAssessment(aware("2026-06-16T10:00"), Verdict.GOOD, (), 4.0),),
        best_window=FlightWindow(aware("2026-06-16T10:00"), aware("2026-06-16T10:00"), 1),
        time_context=LONDON_SUMMER_CONTEXT,
        daily=(
            DayOutlook(
                date=date(2026, 6, 16),
                good_hours=1,
                best_window=FlightWindow(aware("2026-06-16T10:00"), aware("2026-06-16T10:00"), 1),
            ),
        ),
    )
    sun_times = (
        DayAlmanac(
            date=date(2026, 6, 16),
            sunrise=aware("2026-06-16T04:43"),
            sunset=aware("2026-06-16T21:21"),
            daylight_seconds=59880.0,
            time_context=LONDON_SUMMER_CONTEXT,
        ),
    )

    text = describe_drone_assessment(
        assessment, caa_guidance(MINI_5_PRO), (), SiteBriefing(sun_times=sun_times)
    )

    assert "Daylight: sunrise 04:43 BST, sunset 21:21 BST" in text
    assert "Daily outlook:" in text
    assert "2026-06-16: 1 good h, best 10:00 BST-10:00 BST" in text


def test_describe_drone_assessment_notes_empty_outlook() -> None:
    """When every hour has elapsed, the outlook says so instead of an empty list."""
    assessment = DroneAssessment(
        drone_name="DJI Mini 5 Pro",
        place_label="Congleton, England",
        hours=(),
        best_window=None,
        time_context=LONDON_SUMMER_CONTEXT,
    )

    text = describe_drone_assessment(assessment, caa_guidance(MINI_5_PRO), ())

    assert "No upcoming forecast hours in the assessment window." in text


def test_describe_drone_assessment_renders_unknown_hour() -> None:
    """Incomplete required data is visibly distinct from marginal and no-fly."""
    assessment = DroneAssessment(
        drone_name="DJI Mini 5 Pro",
        place_label="Congleton, England",
        hours=(
            HourAssessment(
                aware("2026-06-16T10:00"),
                Verdict.UNKNOWN,
                ("visibility data unavailable",),
                None,
            ),
        ),
        best_window=None,
        time_context=LONDON_SUMMER_CONTEXT,
    )

    text = describe_drone_assessment(assessment, caa_guidance(MINI_5_PRO), ())

    assert "2026-06-16 10:00 BST  UNKNOWN - visibility data unavailable" in text
    assert "no good-to-fly hours" in text


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
        if "daily" in request.url.params:
            return httpx.Response(200, json=_ALMANAC_BODY)
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


def test_drone_flight_summary_rejects_non_gb_location_before_weather_lookup() -> None:
    """UK legal guidance is never presented as applicable to another country."""
    weather_requested = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal weather_requested
        if request.url.host.startswith("geocoding"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Austin",
                            "country": "United States",
                            "country_code": "US",
                            "admin1": "Texas",
                            "latitude": 30.27,
                            "longitude": -97.74,
                            "timezone": "America/Chicago",
                        }
                    ]
                },
            )
        weather_requested = True
        return httpx.Response(200, json=_DRONE_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(drone_flight_summary("Austin, Texas", "Neo", client=client))

    assert "available only for Great Britain" in summary
    assert "United States" in summary
    assert weather_requested is False


def test_drone_flight_summary_applies_per_hour_kp_forecast() -> None:
    """The Kp forecast varies per hour: a later 3-hour bucket can flag a storm.

    Exercises the UK-local-to-UTC bucket alignment: 10:00 BST -> 09:00 UTC (quiet)
    is good, while 13:00 BST -> 12:00 UTC (Kp 6) is marginal for geomagnetic risk.
    """
    calm_body: dict[str, object] = {
        **time_metadata(),
        "elevation": 120.0,
        "hourly": {
            "time": [epoch("2026-06-16T10:00"), epoch("2026-06-16T13:00")],
            "wind_gusts_10m": [12.0, 12.0],
            "wind_speed_10m": [10.0, 10.0],
            "wind_speed_80m": [10.0, 10.0],
            "wind_speed_120m": [10.0, 10.0],
            "wind_speed_180m": [10.0, 10.0],
            "temperature_2m": [16.0, 16.0],
            "apparent_temperature": [16.0, 16.0],
            "precipitation": [0.0, 0.0],
            "precipitation_probability": [0.0, 0.0],
            "visibility": [30000.0, 30000.0],
            "is_day": [1.0, 1.0],
            "cape": [0.0, 0.0],
            "freezing_level_height": [2500.0, 2500.0],
            "cloud_cover_low": [10.0, 10.0],
            "wind_speed_950hPa": [10.0, 10.0],
            "wind_speed_925hPa": [10.0, 10.0],
            "wind_speed_900hPa": [10.0, 10.0],
            "geopotential_height_950hPa": [550.0, 550.0],
            "geopotential_height_925hPa": [800.0, 800.0],
            "geopotential_height_900hPa": [1000.0, 1000.0],
        },
    }
    kp_forecast: list[object] = [
        {
            "time_tag": "2026-06-16T09:00:00",
            "kp": 2.0,
            "observed": "predicted",
            "noaa_scale": None,
        },
        {
            "time_tag": "2026-06-16T12:00:00",
            "kp": 6.0,
            "observed": "predicted",
            "noaa_scale": "G2",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        return httpx.Response(200, json=calm_body)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(
        drone_flight_summary(
            "Congleton UK",
            "Mini 5 Pro",
            client=client,
            now=_NOW,
            site_clients=_site_clients([], space_weather=_space_weather(kp_forecast)),
        )
    )

    assert "2026-06-16 10:00 BST  GOOD" in summary
    assert "2026-06-16 13:00 BST  MARGINAL" in summary
    assert "geomagnetic" in summary


def test_drone_flight_summary_survives_kp_outage() -> None:
    """A NOAA Kp failure does not break the assessment (best-effort)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=_GEOCODE_BODY)
        return httpx.Response(200, json=_DRONE_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    summary = render(
        drone_flight_summary(
            "Congleton UK",
            "Neo",
            client=client,
            now=_NOW,
            site_clients=_site_clients([], space_weather=_space_weather(status=503)),
        )
    )

    assert "DJI Neo at Congleton, England" in summary
    assert "Source status: NOAA Kp unavailable" in summary


def test_best_effort_failure_is_visible_and_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A supplemental METAR outage produces one log and one structured status."""
    caplog.set_level("WARNING", logger="weather_agent.weather")
    site = SiteClients(
        aviation=_aviation_status(503),
        openaip=_openaip("", {"items": []}),
        space_weather=_space_weather(),
    )

    summary = render(
        drone_flight_summary(
            "Congleton UK",
            "Neo",
            client=_drone_client(),
            now=_NOW,
            site_clients=site,
        )
    )

    assert "Source status: METAR unavailable - lookup failed" in summary
    metar_logs = [
        record for record in caplog.records if "METAR lookup unavailable" in record.message
    ]
    assert len(metar_logs) == 1


def test_drone_flight_summary_exposes_malformed_kp_products() -> None:
    """Schema failures remain visible rather than looking like quiet Kp data."""
    summary = render(
        drone_flight_summary(
            "Congleton UK",
            "Neo",
            client=_drone_client(),
            now=_NOW,
            site_clients=_site_clients([], space_weather=_space_weather([], [])),
        )
    )

    assert "Source status: NOAA Kp malformed" in summary


def _fleet_members() -> tuple[FleetMember, ...]:
    return tuple(
        FleetMember(
            profile=profile,
            assessment=DroneAssessment(
                drone_name=profile.name,
                place_label="Congleton, England",
                hours=(HourAssessment(aware("2026-06-16T10:00"), Verdict.GOOD, (), 4.0),),
                best_window=FlightWindow(aware("2026-06-16T10:00"), aware("2026-06-16T10:00"), 1),
                time_context=LONDON_SUMMER_CONTEXT,
                daily=(
                    DayOutlook(
                        date(2026, 6, 16),
                        1,
                        FlightWindow(aware("2026-06-16T10:00"), aware("2026-06-16T10:00"), 1),
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

    assert "Fleet flight assessment - 5 drones at Congleton, England" in text
    assert "Fleet comparison" in text
    for profile in DRONE_PROFILES:
        assert profile.name in text
    # The dated source heading and disclaimer are shared, not repeated per configuration.
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

    assert "Fleet flight assessment - 5 drones at Congleton, England" in summary
    assert "DJI Neo" in summary
    assert "DJI Avata 2" in summary
    assert "DJI Mini 5 Pro" in summary
    # METAR and disclaimer are shared site context, rendered once for the fleet.
    assert summary.count("Nearest METAR") == 1
    assert "MANCHESTER CTR" in summary
    assert summary.count("not legal") == 1


def _flight_hour(gust_kmh: float | None, visibility_m: float | None) -> DroneFlightHour:
    return DroneFlightHour(
        time=aware("2026-06-16T10:00"),
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
        coordinates=Coordinates(53.35, -2.28),
        observed=datetime(2026, 6, 16, 9, tzinfo=UTC),
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


def test_metar_reconciliation_requires_nearby_forecast_instant() -> None:
    """A METAR outside the 90-minute comparison window is not reconciled."""
    hour = _flight_hour(36.0, 20000.0)

    assert _nearest_forecast_hour((hour,), datetime(2026, 6, 16, 10, 30, tzinfo=UTC)) is hour
    assert _nearest_forecast_hour((hour,), datetime(2026, 6, 16, 10, 31, tzinfo=UTC)) is None


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


def test_kp_forecast_does_not_extrapolate_outside_three_hour_bucket() -> None:
    """A high Kp bucket affects only its published three-hour UTC coverage."""
    hours = (
        replace(_flight_hour(10.0, 20000.0), time=aware("2026-06-16T10:00")),
        replace(_flight_hour(10.0, 20000.0), time=aware("2026-06-16T13:00")),
    )
    entries = (
        KpForecastEntry(
            datetime(2026, 6, 16, 9, tzinfo=UTC),
            6.0,
            KpRowKind.PREDICTED,
            "G2",
        ),
    )

    mapping = _resolve_kp_by_hour(hours, entries)

    assert mapping == {aware("2026-06-16T10:00"): 6.0}


def test_current_kp_fallback_is_not_copied_across_forecast() -> None:
    """A current-only observation covers its own bucket, never every future hour."""
    hours = (
        replace(_flight_hour(10.0, 20000.0), time=aware("2026-06-16T10:00")),
        replace(_flight_hour(10.0, 20000.0), time=aware("2026-06-16T13:00")),
    )
    space_weather = _space_weather(forecast_body=[], current_body=_KP_CURRENT_BODY)

    resolution = _drone_kp_by_hour(space_weather, hours)

    assert resolution.by_time == {aware("2026-06-16T10:00"): 2.0}
    assert resolution.status.state.value == "current_only"


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

    assert "Observed vs forecast at METAR time:" in summary
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
        "DJI Neo (FPV)",
        "DJI Avata 2",
        "DJI Mini 5 Pro",
        "DJI Mini 5 Pro (Plus Battery)",
    )
    assert all(member.assessment.hours for member in result.members)
    assert tuple(status.state.value for status in result.briefing.source_statuses) == (
        "available",
        "available",
        "available",
        "available",
    )


def test_assess_fleet_marks_stale_metar_without_reconciliation() -> None:
    """A stale observation stays visible as status but cannot act as current data."""
    result = assess_fleet(
        "Congleton UK",
        client=_drone_client(),
        now=_NOW,
        site_clients=_site_clients(_STALE_METAR_BODY, _AIRSPACE_BODY),
    )

    assert result is not None
    metar_status = next(
        status for status in result.briefing.source_statuses if status.source == "METAR"
    )
    assert metar_status.state.value == "stale"
    assert "180 minutes old" in metar_status.detail
    assert result.briefing.metar is None
    assert result.briefing.metar_vs_forecast == ""


def test_assess_fleet_unknown_location_is_none() -> None:
    """An unresolvable location yields None rather than raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json=_DRONE_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert assess_fleet("Nowheresville", client=client, site_clients=_site_clients([])) is None


def test_assess_fleet_rejects_non_gb_location() -> None:
    """The structured dashboard path enforces the same jurisdiction boundary."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Paris",
                        "country": "France",
                        "country_code": "FR",
                        "admin1": "Île-de-France",
                        "latitude": 48.86,
                        "longitude": 2.35,
                        "timezone": "Europe/Paris",
                    }
                ]
            },
        )

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(UnsupportedJurisdictionError, match="Great Britain"):
        _ = assess_fleet("Paris", client=client, site_clients=_site_clients([]))


@pytest.mark.parametrize("days", [0, 8])
def test_assess_fleet_rejects_out_of_range_days(days: int) -> None:
    """Day counts outside 1..7 are rejected before any network call."""
    with pytest.raises(ValueError, match="days must be between"):
        _ = assess_fleet("Congleton UK", days=days)
