"""Domain logic turning place names into human-readable weather summaries.

Kept separate from the Strands ``@tool`` wrappers so each function can be tested
directly with an injected client. Every public function resolves a location, runs
one or more open-meteo calls, and returns a typed
:class:`~weather_agent.results.LookupOutcome` - an answer, a "not found", an
invalid-input, or a failure - so the calling agent never sees a raw exception and
callers can compose outcomes safely. The tool layer renders the outcome to text.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx

from weather_agent.caa import caa_guidance
from weather_agent.client import OpenMeteoClient
from weather_agent.drone import DRONE_PROFILES, find_profile
from weather_agent.drone_report import describe_drone_assessment, describe_supported_drones
from weather_agent.flyability import assess_forecast
from weather_agent.geocoding import parse_location, select_best_match
from weather_agent.knowledge import load_sections, retrieve
from weather_agent.models import ClimateRequest, HistoricalRequest
from weather_agent.parsing import OpenMeteoError, SpaceWeatherError
from weather_agent.reporting import (
    DAILY_VARIABLES,
    FORECAST_DAILY_VARIABLES,
    SOLAR_DAILY_VARIABLES,
    describe_comparison,
    describe_current_readings,
    describe_current_weather,
    describe_daily_forecast,
    describe_ensemble_spread,
    describe_forecast_day,
    describe_latest_values,
    describe_period,
    describe_solar,
    describe_uv,
)
from weather_agent.results import Answer, Failed, Invalid, LookupOutcome, NotFound
from weather_agent.routing import FORECAST_HORIZON_DAYS, DataSource, select_data_source

if TYPE_CHECKING:
    from collections.abc import Callable

    from weather_agent.models import GeocodeResult

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
_HTTP_BAD_REQUEST = 400
_ROUTED_CLIMATE_CAVEAT = (
    "(This date is beyond the ~16-day forecast horizon, so the figures above are a "
    "long-range climate-model estimate, not a weather forecast.)"
)


def _place_label(place: GeocodeResult) -> str:
    parts = [place.name]
    if place.admin1 and place.admin1 != place.name:
        parts.append(place.admin1)
    if place.country:
        parts.append(place.country)
    return ", ".join(parts)


def _summarize(
    location: str,
    client: OpenMeteoClient | None,
    describe: Callable[[OpenMeteoClient, GeocodeResult], str],
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
        query = parse_location(location)
        matches = active.geocode(query.name)
        place = select_best_match(matches, query.qualifier)
        if place is None:
            return NotFound(location)
        return Answer(describe(active, place))
    except (httpx.HTTPError, OpenMeteoError) as error:
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
        weather = active.current_weather(place.latitude, place.longitude)
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
        series = active.forecast_series(
            place.latitude, place.longitude, FORECAST_DAILY_VARIABLES, days
        )
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

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        series = active.forecast_day_series(
            place.latitude, place.longitude, FORECAST_DAILY_VARIABLES, when
        )
        return describe_forecast_day(_place_label(place), series, 0, heading)

    return _summarize(location, client, describe)


def historical_summary(
    location: str,
    start_date: str,
    end_date: str,
    client: OpenMeteoClient | None = None,
) -> LookupOutcome:
    """Build a historical (ERA5 archive) summary over a date range.

    Args:
        location: A city or place name.
        start_date: Inclusive ISO-8601 start date (``YYYY-MM-DD``), from 1940.
        end_date: Inclusive ISO-8601 end date (``YYYY-MM-DD``).
        client: Optional client to use.

    Returns:
        An outcome wrapping a one-line summary of the range.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        request = HistoricalRequest(
            latitude=place.latitude,
            longitude=place.longitude,
            start_date=start_date,
            end_date=end_date,
            daily=DAILY_VARIABLES,
        )
        series = active.historical_series(request)
        return describe_period(_place_label(place), series, "Historical weather")

    return _summarize(location, client, describe)


def climate_summary(
    location: str,
    start_date: str,
    end_date: str,
    client: OpenMeteoClient | None = None,
    note: str = "",
) -> LookupOutcome:
    """Build a climate (CMIP6) projection summary over a date range.

    Args:
        location: A city or place name.
        start_date: Inclusive ISO-8601 start date (``YYYY-MM-DD``), up to 2050.
        end_date: Inclusive ISO-8601 end date (``YYYY-MM-DD``).
        client: Optional client to use.
        note: Optional trailing note appended only when an actual projection is
            produced (resolution and fetch succeed and the series has rows). Used
            by date routing to flag that a climate estimate stood in for a
            forecast, without leaking the note onto not-found or failure outcomes.

    Returns:
        An outcome wrapping a one-line summary of the projection.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        request = ClimateRequest(
            latitude=place.latitude,
            longitude=place.longitude,
            start_date=start_date,
            end_date=end_date,
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
        readings = active.air_quality_current(place.latitude, place.longitude, _AIR_QUALITY_REQUEST)
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
        try:
            readings = active.marine_current(place.latitude, place.longitude, _MARINE_REQUEST)
        except httpx.HTTPStatusError as error:
            # Open-meteo's marine API returns 400 for inland (non-marine) points.
            if error.response.status_code == _HTTP_BAD_REQUEST:
                return f"{_place_label(place)} does not appear to be a coastal or marine location."
            raise
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
        series = active.river_discharge_series(
            place.latitude, place.longitude, _RIVER_DISCHARGE_REQUEST
        )
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
            place.latitude, place.longitude, _ENSEMBLE_VARIABLE, _DEFAULT_ENSEMBLE_MODEL
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
        elevation = active.elevation(place.latitude, place.longitude)
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
        uv = active.uv_index(place.latitude, place.longitude)
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
        readings = active.air_quality_current(place.latitude, place.longitude, _POLLEN_REQUEST)
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
        series = active.forecast_series(
            place.latitude, place.longitude, SOLAR_DAILY_VARIABLES, days
        )
        return describe_solar(_place_label(place), series, days)

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
        weather = active.current_weather(latitude, longitude)
        return Answer(describe_current_weather(label, weather))
    except (httpx.HTTPError, OpenMeteoError) as error:
        return Failed(label, str(error))
    finally:
        if owns_client:
            active.close()


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
        when: The date of interest in ISO format (``YYYY-MM-DD``).
        client: Optional client to use.
        today: Reference current date; defaults to the current UTC date.

    Returns:
        The outcome from the selected source, or an invalid-input outcome when the
        date cannot be parsed. Beyond the forecast horizon the climate estimate is
        flagged as such, but only when it is a real projection.
    """
    try:
        target = date.fromisoformat(when)
    except ValueError:
        return Invalid(f"'{when}' is not a valid ISO date (expected YYYY-MM-DD).")
    reference = today if today is not None else datetime.now(UTC).date()
    source = select_data_source(target, reference)
    if source is DataSource.ARCHIVE:
        return historical_summary(location, when, when, client)
    if source is DataSource.FORECAST:
        # The forecast endpoint serves recent past days too; label those as past
        # weather rather than a forecast.
        heading = "Forecast" if target >= reference else "Weather"
        return forecast_for_day(location, when, client, heading)
    # Beyond the forecast horizon there is no real forecast; the note is attached
    # by climate_summary only when an actual projection is produced, so it never
    # leaks onto a not-found or failure outcome.
    return climate_summary(location, when, when, client, note=_ROUTED_CLIMATE_CAVEAT)


def compare_periods(
    location: str,
    period_a: tuple[str, str],
    period_b: tuple[str, str],
    client: OpenMeteoClient | None = None,
) -> LookupOutcome:
    """Compare historical mean daily high temperature between two date ranges.

    Fetches the ERA5 archive for both ranges and reports the difference, combining
    two boundary calls behind one location resolution.

    Args:
        location: A city or place name.
        period_a: Inclusive ``(start_date, end_date)`` ISO range for the baseline.
        period_b: Inclusive ``(start_date, end_date)`` ISO range to compare.
        client: Optional client to use.

    Returns:
        An outcome wrapping a one-line comparison.
    """

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        series_a = active.historical_series(
            HistoricalRequest(
                latitude=place.latitude,
                longitude=place.longitude,
                start_date=period_a[0],
                end_date=period_a[1],
                daily=DAILY_VARIABLES,
            )
        )
        series_b = active.historical_series(
            HistoricalRequest(
                latitude=place.latitude,
                longitude=place.longitude,
                start_date=period_b[0],
                end_date=period_b[1],
                daily=DAILY_VARIABLES,
            )
        )
        label_a = f"{period_a[0]}..{period_a[1]}"
        label_b = f"{period_b[0]}..{period_b[1]}"
        return describe_comparison(_place_label(place), label_a, series_a, label_b, series_b)

    return _summarize(location, client, describe)


_DRONE_FORECAST_DAYS = 2
_UK_TIMEZONE = ZoneInfo("Europe/London")


def _best_effort_kp(client: OpenMeteoClient) -> float | None:
    """Fetch the latest planetary Kp, returning None on any failure.

    Geomagnetic data is a useful but non-essential signal, so a NOAA outage must
    not break the whole assessment. Note this is the single current Kp value used
    as a constant proxy across the forecast window, not a per-hour Kp forecast.
    """
    try:
        return client.geomagnetic_kp().kp
    except httpx.HTTPError:
        return None
    except SpaceWeatherError:
        return None


def drone_flight_summary(
    location: str,
    drone: str,
    client: OpenMeteoClient | None = None,
    now: datetime | None = None,
) -> LookupOutcome:
    """Assess flying a named drone at a location and return readable guidance.

    Resolves the drone profile, fetches a drone-tuned hourly forecast and the
    planetary Kp index, drops already-elapsed hours, runs the flyability rules,
    adds UK CAA guidance, and retrieves matching qualitative tips.

    UK-scoped: the forecast is requested in UK local time and the CAA guidance
    follows UK open-category rules, so hour labels for non-UK locations appear in
    UK time rather than the location's local time.

    Args:
        location: A city or place name.
        drone: A supported drone name, for example ``"Mini 5 Pro"``.
        client: Optional client to use.
        now: Current naive UK-local time; defaults to the actual current time.
            Hours before this are excluded so the outlook starts from now.

    Returns:
        An outcome wrapping a full flight assessment, or - for an unrecognised
        drone - an answer listing the supported models.
    """
    profile = find_profile(drone)
    if profile is None:
        return Answer(describe_supported_drones(DRONE_PROFILES))
    reference = now if now is not None else datetime.now(_UK_TIMEZONE).replace(tzinfo=None)

    def describe(active: OpenMeteoClient, place: GeocodeResult) -> str:
        forecast = active.drone_forecast(place.latitude, place.longitude, _DRONE_FORECAST_DAYS)
        kp_index = _best_effort_kp(active)
        assessment = assess_forecast(profile, forecast, _place_label(place), kp_index, reference)
        factors = " ".join(factor for hour in assessment.hours for factor in hour.limiting_factors)
        tips = retrieve(factors or "pre-flight wind battery", load_sections())
        return describe_drone_assessment(assessment, caa_guidance(profile), tips)

    return _summarize(location, client, describe)
