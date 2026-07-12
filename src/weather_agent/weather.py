"""Domain logic turning place names into human-readable weather summaries.

Kept separate from the Strands ``@tool`` wrappers so each function can be tested
directly with an injected client. Every public function resolves a location, runs
one or more open-meteo calls, and returns a typed
:class:`~weather_agent.results.LookupOutcome` - an answer, a "not found", an
invalid-input, or a failure - so the calling agent never sees a raw exception and
callers can compose outcomes safely. The tool layer renders the outcome to text.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx

from weather_agent.application import DroneResponse
from weather_agent.aviation import AviationClient
from weather_agent.caa import caa_guidance
from weather_agent.client import (
    ARCHIVE_START_DATE,
    CLIMATE_END_DATE,
    CLIMATE_START_DATE,
    MAX_DAILY_RANGE_DAYS,
    OpenMeteoClient,
)
from weather_agent.dates import resolve_day
from weather_agent.drone import DRONE_PROFILES, find_profile
from weather_agent.drone_report import (
    describe_drone_assessment,
    describe_fleet_assessment,
    describe_supported_drones,
    reconcile_metar,
)
from weather_agent.flyability import assess_forecast
from weather_agent.geocoding import parse_location, select_best_match
from weather_agent.knowledge import load_sections, retrieve
from weather_agent.models import (
    ClimateRequest,
    Coordinates,
    FleetAssessment,
    FleetMember,
    HistoricalRequest,
    KpForecastEntry,
    KpRowKind,
    SiteBriefing,
    SourceState,
    SourceStatus,
)
from weather_agent.openaip import OpenAipClient
from weather_agent.parsing import ExternalDataError, OpenMeteoError
from weather_agent.reporting import (
    DAILY_VARIABLES,
    FORECAST_DAILY_VARIABLES,
    SOLAR_DAILY_VARIABLES,
    describe_airspace,
    describe_comparison,
    describe_current_readings,
    describe_current_weather,
    describe_daily_forecast,
    describe_ensemble_spread,
    describe_forecast_day,
    describe_latest_values,
    describe_location_comparison,
    describe_metar,
    describe_period,
    describe_solar,
    describe_sun_times,
    describe_uv,
)
from weather_agent.results import Answer, Failed, Invalid, LookupOutcome, NotFound
from weather_agent.routing import (
    ARCHIVE_LATENCY_DAYS,
    FORECAST_HORIZON_DAYS,
    DataSource,
    select_data_source,
)
from weather_agent.space_weather import SpaceWeatherClient, SpaceWeatherError

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from weather_agent.models import (
        Airspace,
        CurrentWeather,
        DayAlmanac,
        DroneAssessment,
        DroneFlightHour,
        DroneForecast,
        DroneProfile,
        GeocodeResult,
        KpIndex,
        MetarReport,
    )

_DEFAULT_CLIMATE_MODEL = "EC_Earth3P_HR"
_DEFAULT_ENSEMBLE_MODEL = "icon_seamless"
_AIR_QUALITY_VARIABLES = ("pm2_5", "pm10", "ozone", "european_aqi")
_AIR_QUALITY_REQUEST = ",".join(_AIR_QUALITY_VARIABLES)
_MARINE_VARIABLES = ("wave_height", "wave_period")
_MARINE_REQUEST = ",".join(_MARINE_VARIABLES)
_RIVER_DISCHARGE_VARIABLES = ("river_discharge",)
_RIVER_DISCHARGE_REQUEST = ",".join(_RIVER_DISCHARGE_VARIABLES)
_POLLEN_VARIABLES = (
    "alder_pollen",
    "birch_pollen",
    "grass_pollen",
    "mugwort_pollen",
    "olive_pollen",
    "ragweed_pollen",
)
_POLLEN_REQUEST = ",".join(_POLLEN_VARIABLES)
_SOLAR_FORECAST_DAYS = 3
_ENSEMBLE_VARIABLE = "temperature_2m"
_METAR_MAX_AGE = timedelta(hours=2)
_METAR_MAX_FUTURE = timedelta(minutes=15)
_METAR_MAX_COMPARISON_GAP = timedelta(minutes=90)
_ROUTED_CLIMATE_CAVEAT = (
    "(This date is beyond the ~16-day forecast horizon, so the figures above are a "
    "long-range climate-model estimate, not a weather forecast.)"
)
logger = logging.getLogger(__name__)


class UnsupportedJurisdictionError(ValueError):
    """Raised when UK drone guidance is requested for a non-GB geocode result."""


def _place_label(place: GeocodeResult) -> str:
    parts = [place.name]
    if place.admin1 and place.admin1 != place.name:
        parts.append(place.admin1)
    if place.country:
        parts.append(place.country)
    return ", ".join(parts)


def _require_drone_jurisdiction(place: GeocodeResult) -> None:
    if place.country_code.upper() == "GB":
        return
    code = place.country_code or "unknown country"
    message = (
        "Drone decision support is currently available only for Great Britain "
        f"locations; resolved {_place_label(place)} ({code})."
    )
    raise UnsupportedJurisdictionError(message)


def _reference_date(today: date | None, timezone: str) -> date:
    return today if today is not None else datetime.now(ZoneInfo(timezone)).date()


def _validate_period(
    start: date,
    end: date,
    lower: date,
    upper: date,
    label: str,
) -> str | None:
    if start > end:
        return f"{label} start date must not follow its end date."
    if start < lower or end > upper:
        return f"{label} dates must be between {lower} and {upper}."
    if (end - start).days + 1 > MAX_DAILY_RANGE_DAYS:
        return f"{label} range must not exceed {MAX_DAILY_RANGE_DAYS} days."
    return None


def _resolve_place(active: OpenMeteoClient, location: str) -> GeocodeResult | None:
    """Geocode a free-text location to its best matching place, or None.

    Shared by the text summaries and the structured fleet assessment so both resolve
    locations identically.
    """
    query = parse_location(location)
    return select_best_match(active.geocode(query.name), query.qualifier)


def _summarize(
    location: str,
    client: OpenMeteoClient | None,
    describe: Callable[[OpenMeteoClient, GeocodeResult], str | Invalid],
) -> LookupOutcome:
    """Resolve a location and run ``describe`` with unified errors and lifecycle.

    Args:
        location: A city or place name to geocode.
        client: Optional client to reuse. When omitted, one is created and closed
            for the duration of the call.
        describe: Callback receiving the active client and the top geocoding
            match, returning the success summary text.

    Returns:
        An :class:`~weather_agent.results.Answer` wrapping the callback's summary,
        :class:`~weather_agent.results.NotFound` when the location cannot be
        resolved, or :class:`~weather_agent.results.Failed` when any lookup fails.
    """
    owns_client = client is None
    active = client if client is not None else OpenMeteoClient()
    try:
        place = _resolve_place(active, location)
        if place is None:
            return NotFound(location)
        summary = describe(active, place)
        return summary if isinstance(summary, Invalid) else Answer(summary)
    except UnsupportedJurisdictionError as error:
        return Invalid(str(error))
    except (httpx.HTTPError, ExternalDataError) as error:
        return Failed(location, str(error))
    finally:
        if owns_client:
            active.close()


def current_weather_summary(location: str, client: OpenMeteoClient | None = None) -> LookupOutcome:
    """Build a readable current-weather summary for a named location.

    Args:
        location: A city or place name, for example ``"Berlin"``.
        client: Optional client to use.

    Returns:
        An outcome wrapping a one-line summary of current conditions.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        weather = active.current_weather(place.coordinates)
        return describe_current_weather(_place_label(place), weather)

    return _summarize(location, client, describe)


def forecast_summary(
    location: str,
    days: int = 3,
    client: OpenMeteoClient | None = None,
) -> LookupOutcome:
    """Build a multi-day daily forecast summary for a named location.

    Args:
        location: A city or place name.
        days: Number of forecast days to request and report (1 to the forecast
            horizon).
        client: Optional client to use.

    Returns:
        An outcome wrapping a multi-line forecast summary, or an invalid-input
        outcome when ``days`` is outside the supported range.
    """
    if not 1 <= days <= FORECAST_HORIZON_DAYS:
        return Invalid(f"Forecast days must be between 1 and {FORECAST_HORIZON_DAYS} (got {days}).")

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        series = active.forecast_series(place.coordinates, FORECAST_DAILY_VARIABLES, days)
        return describe_daily_forecast(_place_label(place), series, days)

    return _summarize(location, client, describe)


def forecast_for_day(
    location: str,
    when: str,
    client: OpenMeteoClient | None = None,
    heading: str = "Forecast",
) -> LookupOutcome:
    """Build a single-day forecast summary for a specific calendar date.

    Fetches exactly the requested day from the forecast endpoint (by explicit
    date), which serves the recent past as well as the near future, so it works
    for both without index arithmetic.

    Args:
        location: A city or place name.
        when: The ISO-8601 date (``YYYY-MM-DD``) to report.
        client: Optional client to use.
        heading: Leading noun for the rendered line (``"Forecast"`` for today or
            the future, ``"Weather"`` for a recent past day).

    Returns:
        An outcome wrapping a one-line summary for that day.
    """
    try:
        requested_day = date.fromisoformat(when)
    except ValueError:
        return Invalid(f"'{when}' is not a valid ISO date (YYYY-MM-DD).")

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        series = active.forecast_day_series(
            place.coordinates, FORECAST_DAILY_VARIABLES, requested_day
        )
        return describe_forecast_day(_place_label(place), series, 0, heading)

    return _summarize(location, client, describe)


def historical_summary(
    location: str,
    period: tuple[str, str],
    client: OpenMeteoClient | None = None,
    today: date | None = None,
) -> LookupOutcome:
    """Build a historical (ERA5 archive) summary over a date range.

    Args:
        location: A city or place name.
        period: Inclusive ``(start, end)`` range; each endpoint is an ISO date
            (``YYYY-MM-DD``, from 1940) or a single-day phrase like ``"yesterday"``.
        client: Optional client to use.
        today: Reference date for relative phrases; defaults to the resolved
            location's current calendar date.

    Returns:
        An outcome wrapping a one-line summary of the range, or an invalid-input
        outcome when a date cannot be interpreted.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str | Invalid:
        reference = _reference_date(today, place.timezone)
        start = resolve_day(period[0], reference)
        end = resolve_day(period[1], reference)
        if start is None or end is None:
            return Invalid(f"Could not interpret the date range '{period[0]}' to '{period[1]}'.")
        archive_end = reference - timedelta(days=ARCHIVE_LATENCY_DAYS)
        problem = _validate_period(
            start,
            end,
            ARCHIVE_START_DATE,
            archive_end,
            "Historical weather",
        )
        if problem is not None:
            return Invalid(problem)
        request = HistoricalRequest(
            coordinates=place.coordinates,
            start_date=start,
            end_date=end,
            daily=DAILY_VARIABLES,
        )
        series = active.historical_series(request)
        return describe_period(_place_label(place), series, "Historical weather")

    return _summarize(location, client, describe)


def climate_summary(
    location: str,
    period: tuple[str, str],
    client: OpenMeteoClient | None = None,
    note: str = "",
    today: date | None = None,
) -> LookupOutcome:
    """Build a climate (CMIP6) projection summary over a date range.

    Args:
        location: A city or place name.
        period: Inclusive ``(start, end)`` range; each endpoint is an ISO date
            (``YYYY-MM-DD``, up to 2050) or a single-day phrase.
        client: Optional client to use.
        note: Optional trailing note appended only when an actual projection is
            produced (resolution and fetch succeed and the series has rows). Used
            by date routing to flag that a climate estimate stood in for a
            forecast, without leaking the note onto not-found or failure outcomes.
        today: Reference date for relative phrases; defaults to the resolved
            location's current calendar date.

    Returns:
        An outcome wrapping a one-line summary of the projection, or an
        invalid-input outcome when a date cannot be interpreted.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str | Invalid:
        reference = _reference_date(today, place.timezone)
        start = resolve_day(period[0], reference)
        end = resolve_day(period[1], reference)
        if start is None or end is None:
            return Invalid(f"Could not interpret the date range '{period[0]}' to '{period[1]}'.")
        problem = _validate_period(
            start,
            end,
            CLIMATE_START_DATE,
            CLIMATE_END_DATE,
            "Climate projection",
        )
        if problem is not None:
            return Invalid(problem)
        request = ClimateRequest(
            coordinates=place.coordinates,
            start_date=start,
            end_date=end,
            daily=DAILY_VARIABLES,
            models=_DEFAULT_CLIMATE_MODEL,
        )
        series = active.climate_projection(request)
        text = describe_period(_place_label(place), series, "Climate projection")
        return f"{text}\n{note}" if note and series.timestamps else text

    return _summarize(location, client, describe)


def air_quality_summary(location: str, client: OpenMeteoClient | None = None) -> LookupOutcome:
    """Build a current air-quality summary for a named location.

    Args:
        location: A city or place name.
        client: Optional client to use.

    Returns:
        An outcome wrapping a one-line summary of particulates, ozone, and AQI.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        readings = active.air_quality_current(place.coordinates, _AIR_QUALITY_REQUEST)
        return describe_current_readings(
            _place_label(place), readings, "Air quality", _AIR_QUALITY_VARIABLES
        )

    return _summarize(location, client, describe)


def marine_summary(location: str, client: OpenMeteoClient | None = None) -> LookupOutcome:
    """Build a current marine (wave) summary for a named location.

    Args:
        location: A coastal city or place name.
        client: Optional client to use.

    Returns:
        An outcome wrapping a one-line summary of wave height and period.
        Open-meteo returns an error for inland points, which is reported as such.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        readings = active.marine_current(place.coordinates, _MARINE_REQUEST)
        return describe_current_readings(
            _place_label(place), readings, "Marine conditions", _MARINE_VARIABLES
        )

    return _summarize(location, client, describe)


def river_discharge_summary(location: str, client: OpenMeteoClient | None = None) -> LookupOutcome:
    """Build a river-discharge (flood) summary for a named location.

    Args:
        location: A city or place name near a river.
        client: Optional client to use.

    Returns:
        An outcome wrapping a one-line summary of forecast river discharge.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        series = active.river_discharge_series(place.coordinates, _RIVER_DISCHARGE_REQUEST)
        return describe_latest_values(
            _place_label(place), series, "River discharge", _RIVER_DISCHARGE_VARIABLES
        )

    return _summarize(location, client, describe)


def ensemble_summary(location: str, client: OpenMeteoClient | None = None) -> LookupOutcome:
    """Build an ensemble-spread summary of near-term temperature for a location.

    Args:
        location: A city or place name.
        client: Optional client to use.

    Returns:
        An outcome wrapping a one-line summary of member count and temperature
        spread, conveying forecast uncertainty.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        series = active.ensemble_series(
            place.coordinates, _ENSEMBLE_VARIABLE, _DEFAULT_ENSEMBLE_MODEL
        )
        return describe_ensemble_spread(_place_label(place), series, "Ensemble temperature")

    return _summarize(location, client, describe)


def elevation_summary(location: str, client: OpenMeteoClient | None = None) -> LookupOutcome:
    """Build a terrain-elevation summary for a named location.

    Args:
        location: A city or place name.
        client: Optional client to use.

    Returns:
        An outcome wrapping a one-line elevation summary.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        elevation = active.elevation(place.coordinates)
        return f"Elevation of {_place_label(place)}: {elevation.meters:.0f} m above sea level."

    return _summarize(location, client, describe)


def uv_index_summary(location: str, client: OpenMeteoClient | None = None) -> LookupOutcome:
    """Build a UV-index summary (now and today's peak) for a named location.

    Args:
        location: A city or place name.
        client: Optional client to use.

    Returns:
        An outcome wrapping the current UV index and today's maximum with risk
        bands.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        uv = active.uv_index(place.coordinates)
        return describe_uv(_place_label(place), uv)

    return _summarize(location, client, describe)


def pollen_summary(location: str, client: OpenMeteoClient | None = None) -> LookupOutcome:
    """Build a pollen summary for a named location.

    Pollen comes from the CAMS European air-quality model, so values are reported
    for European locations; elsewhere the API returns no data and the figures show
    as ``n/a``.

    Args:
        location: A city or place name.
        client: Optional client to use.

    Returns:
        An outcome wrapping current pollen levels for the major allergenic taxa.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        readings = active.air_quality_current(place.coordinates, _POLLEN_REQUEST)
        return describe_current_readings(_place_label(place), readings, "Pollen", _POLLEN_VARIABLES)

    return _summarize(location, client, describe)


def solar_summary(
    location: str,
    days: int = _SOLAR_FORECAST_DAYS,
    client: OpenMeteoClient | None = None,
) -> LookupOutcome:
    """Build a daily solar-potential summary for a named location.

    Args:
        location: A city or place name.
        days: Number of forecast days to report (1 to the forecast horizon).
        client: Optional client to use.

    Returns:
        An outcome wrapping daily radiation, sunshine, and daylight, or an
        invalid-input outcome when ``days`` is out of range.
    """
    if not 1 <= days <= FORECAST_HORIZON_DAYS:
        return Invalid(f"Forecast days must be between 1 and {FORECAST_HORIZON_DAYS} (got {days}).")

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        series = active.forecast_series(place.coordinates, SOLAR_DAILY_VARIABLES, days)
        return describe_solar(_place_label(place), series, days)

    return _summarize(location, client, describe)


def sun_times_summary(
    location: str,
    days: int = 1,
    client: OpenMeteoClient | None = None,
) -> LookupOutcome:
    """Build a sunrise/sunset/daylight summary for a named location.

    Args:
        location: A city or place name.
        days: Number of days to report (1 to the forecast horizon).
        client: Optional client to use.

    Returns:
        An outcome wrapping daily sun times, or an invalid-input outcome when
        ``days`` is out of range.
    """
    if not 1 <= days <= FORECAST_HORIZON_DAYS:
        return Invalid(f"Days must be between 1 and {FORECAST_HORIZON_DAYS} (got {days}).")

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        almanac = active.daily_almanac(place.coordinates, days)
        return describe_sun_times(_place_label(place), almanac)

    return _summarize(location, client, describe)


def _coordinate_label(latitude: float, longitude: float) -> str:
    return f"{latitude:.4f}, {longitude:.4f}"


def current_weather_at_coordinates(
    latitude: float,
    longitude: float,
    client: OpenMeteoClient | None = None,
) -> LookupOutcome:
    """Build a current-weather summary for explicit coordinates (no geocoding).

    Bypasses name resolution so a raw latitude/longitude can be queried directly,
    labelling the result with the coordinates.

    Args:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
        client: Optional client to use.

    Returns:
        An outcome wrapping the current conditions at the coordinates.
    """
    owns_client = client is None
    active = client if client is not None else OpenMeteoClient()
    label = _coordinate_label(latitude, longitude)
    try:
        coordinates = Coordinates(latitude, longitude)
        weather = active.current_weather(coordinates)
        return Answer(describe_current_weather(label, weather))
    except ValueError as error:
        return Invalid(str(error))
    except (httpx.HTTPError, OpenMeteoError) as error:
        return Failed(label, str(error))
    finally:
        if owns_client:
            active.close()


def aviation_summary(
    location: str,
    client: OpenMeteoClient | None = None,
    aviation_client: AviationClient | None = None,
    now: datetime | None = None,
) -> LookupOutcome:
    """Build an observed-conditions (nearest METAR) summary for a named location.

    Args:
        location: A city or place name.
        client: Optional open-meteo client (used for geocoding).
        aviation_client: Optional aviation client; created and closed here when not
            provided.
        now: Aware reference instant used to reject stale or future observations.

    Returns:
        An outcome wrapping the nearest station's observed wind, visibility, and
        ceiling, or a note when no station reports nearby.
    """
    reference = now if now is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        return Invalid("now must be timezone-aware")
    owns_aviation = aviation_client is None
    aviation = aviation_client if aviation_client is not None else AviationClient()
    try:

        def describe(_active: OpenMeteoClient, place: GeocodeResult) -> str:
            report = aviation.nearest_metar(place.coordinates)
            if report is None:
                return f"No aviation weather station was found near {_place_label(place)}."
            status = _metar_status(report, reference)
            if status.state is SourceState.STALE:
                return (
                    f"Nearest METAR for {_place_label(place)} was not presented as current: "
                    f"{status.detail}."
                )
            return describe_metar(_place_label(place), report)

        return _summarize(location, client, describe)
    finally:
        if owns_aviation:
            aviation.close()


_NO_KEY_NOTE = "unavailable (no OPENAIP_API_KEY configured)"


def airspace_summary(
    location: str,
    client: OpenMeteoClient | None = None,
    openaip_client: OpenAipClient | None = None,
) -> LookupOutcome:
    """Build a nearby-airspace summary for a named location (decision support).

    Requires an OpenAIP API key; without one the summary reports that the check is
    unavailable rather than failing. Never authoritative - the rendered text always
    points the reader to official airspace/NOTAM sources.

    Args:
        location: A city or place name.
        client: Optional open-meteo client (used for geocoding).
        openaip_client: Optional OpenAIP client; created and closed here when not
            provided.

    Returns:
        An outcome wrapping the list of nearby drone-relevant airspaces, or a note
        when no key is configured.
    """
    owns_openaip = openaip_client is None
    openaip = openaip_client if openaip_client is not None else OpenAipClient()
    try:

        def describe(_active: OpenMeteoClient, place: GeocodeResult) -> str:
            if not openaip.has_key:
                return describe_airspace(_place_label(place), (), _NO_KEY_NOTE)
            airspaces = openaip.nearby_airspaces(place.coordinates)
            return describe_airspace(_place_label(place), airspaces)

        return _summarize(location, client, describe)
    finally:
        if owns_openaip:
            openaip.close()


def _weather_for_target(
    active: OpenMeteoClient,
    place: GeocodeResult,
    target: date,
    reference: date,
) -> str | Invalid:
    source = select_data_source(target, reference)
    if source is DataSource.ARCHIVE:
        problem = _validate_period(
            target,
            target,
            ARCHIVE_START_DATE,
            reference - timedelta(days=ARCHIVE_LATENCY_DAYS),
            "Historical weather",
        )
        if problem is not None:
            return Invalid(problem)
        series = active.historical_series(
            HistoricalRequest(
                place.coordinates,
                target,
                target,
                DAILY_VARIABLES,
            )
        )
        return describe_period(_place_label(place), series, "Historical weather")
    if source is DataSource.FORECAST:
        series = active.forecast_day_series(
            place.coordinates,
            FORECAST_DAILY_VARIABLES,
            target,
        )
        heading = "Forecast" if target >= reference else "Weather"
        return describe_forecast_day(_place_label(place), series, 0, heading)
    problem = _validate_period(
        target,
        target,
        CLIMATE_START_DATE,
        CLIMATE_END_DATE,
        "Climate projection",
    )
    if problem is not None:
        return Invalid(problem)
    series = active.climate_projection(
        ClimateRequest(
            place.coordinates,
            target,
            target,
            DAILY_VARIABLES,
            _DEFAULT_CLIMATE_MODEL,
        )
    )
    text = describe_period(_place_label(place), series, "Climate projection")
    return f"{text}\n{_ROUTED_CLIMATE_CAVEAT}" if series.timestamps else text


def weather_for_date(
    location: str,
    when: str,
    client: OpenMeteoClient | None = None,
    today: date | None = None,
) -> LookupOutcome:
    """Answer a single-date weather question by routing to the right data source.

    Parses the requested date, decides whether it falls in the archive, forecast,
    or climate window relative to ``today``, and delegates to the matching
    summary. This is the agent's "weather for a date" affordance.

    Args:
        location: A city or place name.
        when: The date of interest: an ISO date (``YYYY-MM-DD``) or a single-day
            phrase such as ``"tomorrow"`` or ``"next friday"``.
        client: Optional client to use.
        today: Reference current date; defaults to the resolved location's local
            calendar date.

    Returns:
        The outcome from the selected source, or an invalid-input outcome when the
        date cannot be interpreted. Beyond the forecast horizon the climate estimate
        is flagged as such, but only when it is a real projection.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str | Invalid:
        reference = _reference_date(today, place.timezone)
        target = resolve_day(when, reference)
        if target is None:
            return Invalid(
                f"'{when}' is not a date I can interpret (try YYYY-MM-DD or 'tomorrow')."
            )
        return _weather_for_target(active, place, target, reference)

    return _summarize(location, client, describe)


def compare_periods(
    location: str,
    period_a: tuple[str, str],
    period_b: tuple[str, str],
    client: OpenMeteoClient | None = None,
    today: date | None = None,
) -> LookupOutcome:
    """Compare historical mean daily high temperature between two date ranges.

    Fetches the ERA5 archive for both ranges and reports the difference, combining
    two boundary calls behind one location resolution.

    Args:
        location: A city or place name.
        period_a: Inclusive ``(start, end)`` baseline range; each endpoint is an ISO
            date or a single-day phrase.
        period_b: Inclusive ``(start, end)`` comparison range (ISO or phrases).
        client: Optional client to use.
        today: Reference date for relative phrases; defaults to the resolved
            location's current calendar date.

    Returns:
        An outcome wrapping a one-line comparison, or an invalid-input outcome when
        a date cannot be interpreted.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str | Invalid:
        reference = _reference_date(today, place.timezone)
        a_start = resolve_day(period_a[0], reference)
        a_end = resolve_day(period_a[1], reference)
        b_start = resolve_day(period_b[0], reference)
        b_end = resolve_day(period_b[1], reference)
        if a_start is None or a_end is None or b_start is None or b_end is None:
            return Invalid("Could not interpret one of the comparison dates.")
        archive_end = reference - timedelta(days=ARCHIVE_LATENCY_DAYS)
        for start, end in ((a_start, a_end), (b_start, b_end)):
            problem = _validate_period(
                start,
                end,
                ARCHIVE_START_DATE,
                archive_end,
                "Comparison",
            )
            if problem is not None:
                return Invalid(problem)
        series_a = active.historical_series(
            HistoricalRequest(
                coordinates=place.coordinates,
                start_date=a_start,
                end_date=a_end,
                daily=DAILY_VARIABLES,
            )
        )
        series_b = active.historical_series(
            HistoricalRequest(
                coordinates=place.coordinates,
                start_date=b_start,
                end_date=b_end,
                daily=DAILY_VARIABLES,
            )
        )
        label_a = f"{a_start.isoformat()}..{a_end.isoformat()}"
        label_b = f"{b_start.isoformat()}..{b_end.isoformat()}"
        return describe_comparison(_place_label(place), label_a, series_a, label_b, series_b)

    return _summarize(location, client, describe)


@dataclass(frozen=True, slots=True)
class _LocationMetric:
    """How to read and rank one current-weather metric across locations.

    Attributes:
        label: Human-readable metric name used in the heading.
        unit: Display unit appended to each value; empty when unitless.
        descending: True when a higher value ranks first (warmest, windiest);
            False when a lower value ranks first (least cloud / sunniest).
        read: Reads the metric from a current-weather reading, or None when the
            API did not supply it.
    """

    label: str
    unit: str
    descending: bool
    read: Callable[[CurrentWeather], float | None]


_LOCATION_METRICS: dict[str, _LocationMetric] = {
    "temperature": _LocationMetric(
        "temperature", "°C", descending=True, read=lambda w: w.temperature_celsius
    ),
    "wind": _LocationMetric("wind", "km/h", descending=True, read=lambda w: w.wind_speed_kmh),
    "cloud": _LocationMetric(
        "cloud cover", "%", descending=False, read=lambda w: w.cloud_cover_pct
    ),
    "humidity": _LocationMetric(
        "humidity", "%", descending=True, read=lambda w: w.relative_humidity_pct
    ),
}


def _measure_location(
    active: OpenMeteoClient,
    location: str,
    metric: _LocationMetric,
) -> tuple[str, float] | str:
    """Resolve one location and read its metric, or return a problem note string."""
    query = parse_location(location)
    place = select_best_match(active.geocode(query.name), query.qualifier)
    if place is None:
        return f"{location} (not found)"
    value = metric.read(active.current_weather(place.coordinates))
    if value is None:
        return f"{_place_label(place)} (no {metric.label})"
    return (_place_label(place), value)


def _collect_rankings(
    active: OpenMeteoClient,
    locations: tuple[str, ...],
    metric: _LocationMetric,
) -> tuple[list[tuple[str, float]], list[str]]:
    """Measure each location, splitting results into ranked values and problem notes."""
    measured: list[tuple[str, float]] = []
    problems: list[str] = []
    for location in locations:
        outcome = _measure_location(active, location, metric)
        if isinstance(outcome, str):
            problems.append(outcome)
        else:
            measured.append(outcome)
    return measured, problems


def rank_locations(
    locations: tuple[str, ...],
    metric: str,
    client: OpenMeteoClient | None = None,
) -> LookupOutcome:
    """Rank several locations by one current-weather metric in a single call.

    Does the multi-location fan-out in code (one geocode + current-weather lookup
    per place, then a deterministic sort) so the agent need not call a
    single-location tool once per place and rank the results itself.

    Args:
        locations: Place names to compare.
        metric: Metric key to rank by; see :data:`_LOCATION_METRICS`.
        client: Optional client to use.

    Returns:
        A ranked comparison answer, an invalid-input outcome for an unknown metric
        or empty input, a not-found outcome when no location resolved, or a failure
        outcome when a lookup errors.
    """
    spec = _LOCATION_METRICS.get(metric)
    if spec is None:
        choices = ", ".join(sorted(_LOCATION_METRICS))
        return Invalid(f"Unknown comparison metric '{metric}'. Choose from: {choices}.")
    if not locations:
        return Invalid("Give at least one location to compare.")
    owns_client = client is None
    active = client if client is not None else OpenMeteoClient()
    try:
        measured, problems = _collect_rankings(active, locations, spec)
    except (httpx.HTTPError, ExternalDataError) as error:
        return Failed("location comparison", str(error))
    finally:
        if owns_client:
            active.close()
    if not measured:
        return NotFound("; ".join(locations))
    measured.sort(key=lambda item: item[1], reverse=spec.descending)
    order = "highest" if spec.descending else "lowest"
    heading = f"Location comparison by {spec.label} ({order} first)"
    return Answer(
        describe_location_comparison(heading, spec.unit, tuple(measured), tuple(problems))
    )


_DRONE_FORECAST_DAYS = 5
_MAX_DRONE_FORECAST_DAYS = 7
_UK_TIMEZONE = ZoneInfo("Europe/London")
_KP_BUCKET_DURATION = timedelta(hours=3)


@dataclass(frozen=True, slots=True)
class SiteClients:
    """Optional injected boundary clients for the drone briefing's extra sources.

    Lets tests pass mock-transport clients for the aviation (and airspace) lookups
    without widening :func:`drone_flight_summary`'s signature. A ``None`` field
    means "create one internally for the call and close it afterwards".

    Attributes:
        aviation: Client for nearest-METAR observations.
        openaip: Client for nearby-airspace lookups (needs an API key).
        space_weather: Client for NOAA planetary Kp observations and forecasts.
    """

    aviation: AviationClient | None = None
    openaip: OpenAipClient | None = None
    space_weather: SpaceWeatherClient | None = None


@dataclass(frozen=True, slots=True)
class _KpResolution:
    """Per-hour Kp values plus the source state that produced them."""

    by_time: dict[datetime, float]
    status: SourceStatus


@contextmanager
def _open_site_clients(
    site_clients: SiteClients | None,
) -> Generator[tuple[AviationClient, OpenAipClient, SpaceWeatherClient]]:
    """Yield the aviation and airspace clients, closing any this call created.

    Tests inject mock-transport clients via ``site_clients`` and own their
    lifecycle; any client not injected is created here and closed on exit. Both
    the single-drone and fleet assessments share this so the open/close dance
    lives in one place.

    Args:
        site_clients: Optional pre-built clients; ``None`` (or a ``None`` field)
            means create that client internally and close it afterwards.

    Yields:
        The aviation, OpenAIP, and NOAA clients to use for the assessment.
    """
    site = site_clients if site_clients is not None else SiteClients()
    aviation = site.aviation if site.aviation is not None else AviationClient()
    openaip = site.openaip if site.openaip is not None else OpenAipClient()
    space_weather = site.space_weather if site.space_weather is not None else SpaceWeatherClient()
    try:
        yield aviation, openaip, space_weather
    finally:
        if site.aviation is None:
            aviation.close()
        if site.openaip is None:
            openaip.close()
        if site.space_weather is None:
            space_weather.close()


def _try_current_kp(client: SpaceWeatherClient) -> tuple[KpIndex | None, SourceState | None]:
    """Fetch current Kp while retaining the exact best-effort failure class."""
    try:
        return client.current_kp(), None
    except httpx.HTTPError as error:
        logger.warning("Current NOAA Kp lookup unavailable: %s", error)
        return None, SourceState.UNAVAILABLE
    except SpaceWeatherError as error:
        logger.warning("Current NOAA Kp response malformed: %s", error)
        return None, SourceState.MALFORMED


def _try_kp_forecast(
    client: SpaceWeatherClient,
) -> tuple[tuple[KpForecastEntry, ...] | None, SourceState | None]:
    """Fetch forecast Kp while retaining the exact best-effort failure class."""
    try:
        return client.kp_forecast(), None
    except httpx.HTTPError as error:
        logger.warning("NOAA Kp forecast lookup unavailable: %s", error)
        return None, SourceState.UNAVAILABLE
    except SpaceWeatherError as error:
        logger.warning("NOAA Kp forecast response malformed: %s", error)
        return None, SourceState.MALFORMED


def _best_effort_almanac(
    client: OpenMeteoClient,
    coordinates: Coordinates,
) -> tuple[tuple[DayAlmanac, ...], SourceStatus]:
    """Fetch sun times while retaining a visible best-effort source state."""
    try:
        values = client.daily_almanac(coordinates, _DRONE_FORECAST_DAYS)
        return values, SourceStatus("Open-Meteo sun times", SourceState.AVAILABLE)
    except httpx.HTTPError as error:
        logger.warning("Open-Meteo sun-time lookup unavailable: %s", error)
        return (), SourceStatus("Open-Meteo sun times", SourceState.UNAVAILABLE)
    except OpenMeteoError as error:
        logger.warning("Open-Meteo sun-time response malformed: %s", error)
        return (), SourceStatus("Open-Meteo sun times", SourceState.MALFORMED)


def _best_effort_metar(
    aviation: AviationClient,
    coordinates: Coordinates,
    now: datetime,
) -> tuple[MetarReport | None, SourceStatus]:
    """Fetch the nearest METAR while retaining absence and failure semantics."""
    try:
        report = aviation.nearest_metar(coordinates)
    except httpx.HTTPError as error:
        logger.warning("METAR lookup unavailable: %s", error)
        return None, SourceStatus("METAR", SourceState.UNAVAILABLE, "lookup failed")
    except ExternalDataError as error:
        logger.warning("METAR response malformed: %s", error)
        return None, SourceStatus("METAR", SourceState.MALFORMED, "response could not be used")
    if report is None:
        return None, SourceStatus("METAR", SourceState.UNAVAILABLE, "no nearby report found")
    status = _metar_status(report, now)
    return (None, status) if status.state is SourceState.STALE else (report, status)


def _metar_status(report: MetarReport, now: datetime) -> SourceStatus:
    """Classify one METAR against the application's current-observation window."""
    age = now.astimezone(UTC) - report.observed.astimezone(UTC)
    if age < -_METAR_MAX_FUTURE:
        minutes = round(-age.total_seconds() / 60)
        detail = f"observation timestamp is {minutes} minutes in the future"
        return SourceStatus("METAR", SourceState.STALE, detail)
    if age > _METAR_MAX_AGE:
        minutes = round(age.total_seconds() / 60)
        detail = f"observation is {minutes} minutes old (maximum 120 minutes)"
        return SourceStatus("METAR", SourceState.STALE, detail)
    detail = f"{report.station} observed {report.observed:%Y-%m-%d %H:%M UTC}"
    return SourceStatus("METAR", SourceState.AVAILABLE, detail)


def _best_effort_airspace(
    openaip: OpenAipClient,
    coordinates: Coordinates,
) -> tuple[tuple[Airspace, ...], str, SourceStatus]:
    """Fetch nearby airspace; return (airspaces, status_note), degrading safely.

    No key gives an "unavailable" note; a network or payload failure gives a
    "lookup failed" note. Either way the assessment continues.
    """
    if not openaip.has_key:
        status = SourceStatus("OpenAIP airspace", SourceState.NOT_CONFIGURED, "API key absent")
        return (), _NO_KEY_NOTE, status
    try:
        airspaces = openaip.nearby_airspaces(coordinates)
        return airspaces, "", SourceStatus("OpenAIP airspace", SourceState.AVAILABLE)
    except httpx.HTTPError as error:
        logger.warning("OpenAIP lookup unavailable: %s", error)
        status = SourceStatus("OpenAIP airspace", SourceState.UNAVAILABLE, "lookup failed")
        return (), "unavailable (airspace lookup failed)", status
    except ExternalDataError as error:
        logger.warning("OpenAIP response malformed: %s", error)
        status = SourceStatus(
            "OpenAIP airspace", SourceState.MALFORMED, "response could not be used"
        )
        return (), "unavailable (airspace response malformed)", status


def _kp_at(entries: tuple[KpForecastEntry, ...], when_utc: datetime) -> float | None:
    for entry in entries:
        if entry.time <= when_utc < entry.time + _KP_BUCKET_DURATION:
            return entry.kp
    return None


def _resolve_kp_by_hour(
    hours: tuple[DroneFlightHour, ...],
    entries: tuple[KpForecastEntry, ...],
) -> dict[datetime, float] | None:
    """Map each forecast hour's timestamp to the Kp predicted for that hour.

    The Kp forecast is in 3-hour UTC buckets; forecast hours are already aware
    instants and are converted directly to UTC for bucket lookup.
    """
    mapping: dict[datetime, float] = {}
    for hour in hours:
        kp = _kp_at(entries, hour.time.astimezone(UTC))
        if kp is not None:
            mapping[hour.time] = kp
    return mapping or None


def _current_kp_by_hour(
    hours: tuple[DroneFlightHour, ...], current: KpIndex
) -> dict[datetime, float]:
    entry = KpForecastEntry(current.time, current.kp, KpRowKind.OBSERVED, None)
    return _resolve_kp_by_hour(hours, (entry,)) or {}


def _kp_failure_status(
    forecast_error: SourceState | None,
    current_error: SourceState | None,
) -> SourceStatus:
    state = (
        SourceState.MALFORMED
        if SourceState.MALFORMED in (forecast_error, current_error)
        else SourceState.UNAVAILABLE
    )
    return SourceStatus("NOAA Kp", state, "forecast and current products could not be used")


def _drone_kp_by_hour(
    client: SpaceWeatherClient,
    hours: tuple[DroneFlightHour, ...],
) -> _KpResolution:
    """Resolve Kp only inside published coverage and preserve source state."""
    entries, forecast_error = _try_kp_forecast(client)
    forecast_values = _resolve_kp_by_hour(hours, entries) if entries is not None else None
    mapping = forecast_values or {}
    if len(mapping) == len(hours):
        return _KpResolution(mapping, SourceStatus("NOAA Kp", SourceState.AVAILABLE))

    current, current_error = _try_current_kp(client)
    if current is not None:
        mapping.update(_current_kp_by_hour(hours, current))
    if mapping:
        state = SourceState.CURRENT_ONLY if entries is None else SourceState.PARTIAL
        detail = f"covers {len(mapping)} of {len(hours)} forecast hours"
        return _KpResolution(mapping, SourceStatus("NOAA Kp", state, detail))
    if entries is not None:
        detail = "published forecast does not cover the requested weather hours"
        return _KpResolution({}, SourceStatus("NOAA Kp", SourceState.PARTIAL, detail))
    if current is not None:
        detail = "current observation does not overlap the requested weather hours"
        return _KpResolution({}, SourceStatus("NOAA Kp", SourceState.CURRENT_ONLY, detail))
    return _KpResolution({}, _kp_failure_status(forecast_error, current_error))


def _site_briefing(
    active: OpenMeteoClient,
    site: tuple[AviationClient, OpenAipClient, SpaceWeatherClient],
    place: GeocodeResult,
    now: datetime,
    source_statuses: tuple[SourceStatus, ...] = (),
) -> SiteBriefing:
    """Gather best-effort sun times, METAR, and airspace context for a site."""
    aviation, openaip, _space_weather = site
    sun_times, sun_status = _best_effort_almanac(active, place.coordinates)
    metar, metar_status = _best_effort_metar(aviation, place.coordinates, now)
    airspaces, airspace_note, airspace_status = _best_effort_airspace(openaip, place.coordinates)
    return SiteBriefing(
        sun_times=sun_times,
        metar=metar,
        airspace=airspaces,
        airspace_note=airspace_note,
        source_statuses=(*source_statuses, sun_status, metar_status, airspace_status),
    )


def _nearest_forecast_hour(
    hours: tuple[DroneFlightHour, ...],
    observed: datetime,
) -> DroneFlightHour | None:
    """Pick the forecast hour closest in time to a METAR observation (both in UTC)."""
    target = observed.astimezone(UTC)
    nearest: DroneFlightHour | None = None
    smallest_gap: float | None = None
    for hour in hours:
        when = hour.time.astimezone(UTC)
        gap = abs((when - target).total_seconds())
        if smallest_gap is None or gap < smallest_gap:
            nearest, smallest_gap = hour, gap
    if nearest is None or smallest_gap is None:
        return None
    return nearest if smallest_gap <= _METAR_MAX_COMPARISON_GAP.total_seconds() else None


def _with_metar_comparison(briefing: SiteBriefing, forecast: DroneForecast) -> SiteBriefing:
    """Attach an observed-vs-forecast note to the briefing when both are available."""
    if briefing.metar is None:
        return briefing
    hour = _nearest_forecast_hour(forecast.hours, briefing.metar.observed)
    if hour is None:
        statuses = tuple(
            replace(
                status,
                detail=f"{status.detail}; no forecast hour within 90 minutes",
            )
            if status.source == "METAR"
            else status
            for status in briefing.source_statuses
        )
        return replace(briefing, source_statuses=statuses)
    note = reconcile_metar(briefing.metar, hour)
    return briefing if note is None else replace(briefing, metar_vs_forecast=note)


def _drone_report(
    assessment: DroneAssessment,
    profile: DroneProfile,
    briefing: SiteBriefing,
) -> str:
    """Render the authoritative assessment with relevant deterministic tips."""
    factors = " ".join(factor for hour in assessment.hours for factor in hour.limiting_factors)
    tips = retrieve(factors or "pre-flight wind battery", load_sections())
    return describe_drone_assessment(assessment, caa_guidance(profile), tips, briefing)


def drone_flight_summary(
    location: str,
    drone: str,
    client: OpenMeteoClient | None = None,
    now: datetime | None = None,
    site_clients: SiteClients | None = None,
) -> LookupOutcome:
    """Assess flying a named drone at a location and return readable guidance.

    Resolves the drone profile, fetches a drone-tuned hourly forecast and the
    planetary Kp index, drops already-elapsed hours, runs the flyability rules,
    adds UK CAA guidance, and retrieves matching qualitative tips.

    Great-Britain-scoped: non-GB geocode results are rejected before weather I/O,
    and the accepted forecast is requested in UK local time with current CAA
    Open Category guidance.

    Args:
        location: A city or place name.
        drone: A supported drone name, for example ``"Mini 5 Pro"``.
        client: Optional client to use.
        now: Current aware instant; defaults to the actual Europe/London time.
            Hours before this are excluded so the outlook starts from now.
        site_clients: Optional injected aviation/airspace clients (tests pass
            mocks); created internally and closed afterwards when omitted.

    Returns:
        An outcome wrapping a full flight assessment, or - for an unrecognised
        drone - an answer listing the supported models.
    """
    return drone_flight_response(location, drone, client, now, site_clients).outcome


def drone_flight_response(
    location: str,
    drone: str,
    client: OpenMeteoClient | None = None,
    now: datetime | None = None,
    site_clients: SiteClients | None = None,
) -> DroneResponse:
    """Build the authoritative text and retain the typed fleet assessment."""
    profile = find_profile(drone)
    if profile is None:
        return DroneResponse(Answer(describe_supported_drones(DRONE_PROFILES)))
    try:
        assessment = assess_fleet(location, _DRONE_FORECAST_DAYS, client, now, site_clients)
    except UnsupportedJurisdictionError as error:
        return DroneResponse(Invalid(str(error)))
    except (httpx.HTTPError, ExternalDataError) as error:
        return DroneResponse(Failed(location, str(error)))
    if assessment is None:
        return DroneResponse(NotFound(location))
    member = next(member for member in assessment.members if member.profile.key == profile.key)
    report = _drone_report(member.assessment, member.profile, assessment.briefing)
    return DroneResponse(Answer(report), assessment)


def _fleet_report(
    members: tuple[FleetMember, ...],
    place_label: str,
    briefing: SiteBriefing,
) -> str:
    """Render the authoritative fleet assessment with shared deterministic tips."""
    factors = " ".join(
        factor
        for member in members
        for hour in member.assessment.hours
        for factor in hour.limiting_factors
    )
    tips = retrieve(factors or "pre-flight wind battery", load_sections())
    return describe_fleet_assessment(members, place_label, tips, briefing)


def _fleet_members(
    active: OpenMeteoClient,
    place: GeocodeResult,
    site: tuple[AviationClient, OpenAipClient, SpaceWeatherClient],
    reference: datetime,
    days: int = _DRONE_FORECAST_DAYS,
) -> tuple[tuple[FleetMember, ...], str, SiteBriefing]:
    """Assess every supported drone against one shared forecast, Kp, and briefing."""
    space_weather = site[2]
    forecast = active.drone_forecast(place.coordinates, days)
    kp = _drone_kp_by_hour(space_weather, forecast.hours)
    briefing = _with_metar_comparison(
        _site_briefing(active, site, place, reference, (kp.status,)), forecast
    )
    label = _place_label(place)
    members = tuple(
        FleetMember(
            profile=profile,
            assessment=assess_forecast(profile, forecast, label, kp.by_time, reference),
            guidance=caa_guidance(profile),
        )
        for profile in DRONE_PROFILES
    )
    return members, label, briefing


def fleet_flight_summary(
    location: str,
    client: OpenMeteoClient | None = None,
    now: datetime | None = None,
    site_clients: SiteClients | None = None,
) -> LookupOutcome:
    """Assess flying every supported drone at a location in one combined report.

    Fetches the drone-tuned hourly forecast, planetary Kp, and site briefing once,
    then runs the flyability rules for each supported drone against that shared
    data. A single request covers the whole fleet, so the agent need not call the
    per-drone tool repeatedly (which small models do unreliably), and the forecast
    is fetched once rather than per drone.

    Great-Britain-scoped like :func:`drone_flight_summary`: non-GB results are
    rejected, forecast hours are UK-local, and guidance follows current CAA rules.

    Args:
        location: A city or place name.
        client: Optional client to use.
        now: Current aware instant; defaults to the actual Europe/London time.
            Hours before this are excluded so the outlook starts from now.
        site_clients: Optional injected aviation/airspace clients (tests pass
            mocks); created internally and closed afterwards when omitted.

    Returns:
        An outcome wrapping a compact fleet assessment over all supported drones.
    """
    return fleet_flight_response(location, client, now, site_clients).outcome


def fleet_flight_response(
    location: str,
    client: OpenMeteoClient | None = None,
    now: datetime | None = None,
    site_clients: SiteClients | None = None,
) -> DroneResponse:
    """Build the authoritative fleet text and retain its typed assessment."""
    try:
        assessment = assess_fleet(location, _DRONE_FORECAST_DAYS, client, now, site_clients)
    except UnsupportedJurisdictionError as error:
        return DroneResponse(Invalid(str(error)))
    except (httpx.HTTPError, ExternalDataError) as error:
        return DroneResponse(Failed(location, str(error)))
    if assessment is None:
        return DroneResponse(NotFound(location))
    report = _fleet_report(assessment.members, assessment.place_label, assessment.briefing)
    return DroneResponse(Answer(report), assessment)


def assess_fleet(
    location: str,
    days: int = _DRONE_FORECAST_DAYS,
    client: OpenMeteoClient | None = None,
    now: datetime | None = None,
    site_clients: SiteClients | None = None,
) -> FleetAssessment | None:
    """Assess every supported drone at a location and return structured results.

    The typed counterpart to :func:`fleet_flight_summary` (which renders text):
    fetches the drone-tuned forecast, planetary Kp, and site briefing once, runs the
    flyability rules for each drone, and returns the per-drone assessments and shared
    briefing as objects for a caller that draws its own output (for example a UI).
    Both paths share one engine, so they never diverge.

    Args:
        location: A city or place name.
        days: Forecast horizon in days (1 to 7).
        client: Optional client to use.
        now: Current aware instant; hours before it are excluded.
        site_clients: Optional injected aviation/airspace clients.

    Returns:
        The structured fleet assessment, or ``None`` when the location does not
        resolve.

    Raises:
        ValueError: If ``days`` is outside 1 to 7.
        UnsupportedJurisdictionError: If geocoding resolves outside Great Britain.
        httpx.HTTPError: If a lookup fails or returns an error status.
        ExternalDataError: If an external payload is malformed.
    """
    if not 1 <= days <= _MAX_DRONE_FORECAST_DAYS:
        message = f"days must be between 1 and {_MAX_DRONE_FORECAST_DAYS} (got {days})."
        raise ValueError(message)
    reference = now if now is not None else datetime.now(_UK_TIMEZONE)
    if reference.tzinfo is None:
        message = "now must be timezone-aware"
        raise ValueError(message)
    owns_client = client is None
    active = client if client is not None else OpenMeteoClient()
    try:
        place = _resolve_place(active, location)
        if place is None:
            return None
        _require_drone_jurisdiction(place)
        with _open_site_clients(site_clients) as site:
            members, label, briefing = _fleet_members(active, place, site, reference, days)
        return FleetAssessment(place_label=label, members=members, briefing=briefing)
    finally:
        if owns_client:
            active.close()
