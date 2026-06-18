"""Strands tools exposing open-meteo lookups to the agent."""

from strands import (
    tool,  # pyright: ignore[reportUnknownVariableType]  # strands' tool overload is partially untyped
)

from weather_agent.drone import DRONE_PROFILES
from weather_agent.drone_report import describe_supported_drones
from weather_agent.results import render
from weather_agent.weather import (
    air_quality_summary,
    airspace_summary,
    aviation_summary,
    climate_summary,
    compare_periods,
    current_weather_at_coordinates,
    current_weather_summary,
    drone_flight_summary,
    elevation_summary,
    ensemble_summary,
    fleet_flight_summary,
    forecast_summary,
    historical_summary,
    marine_summary,
    pollen_summary,
    river_discharge_summary,
    solar_summary,
    sun_times_summary,
    uv_index_summary,
    weather_for_date,
)


@tool
def get_current_weather(location: str) -> str:
    """Get the current weather for a named location.

    Args:
        location: A city or place name, for example "Berlin" or "Tokyo".

    Returns:
        A human-readable summary of the current temperature and wind speed, or an
        explanatory message when the location cannot be resolved.
    """
    return render(current_weather_summary(location))


@tool
def get_forecast(location: str, days: int = 3) -> str:
    """Get a multi-day daily weather forecast for a named location.

    Args:
        location: A city or place name, for example "Berlin" or "Tokyo".
        days: Number of forecast days to report (1-16).

    Returns:
        A multi-line forecast of daily high/low temperature and precipitation, or
        an explanatory message when the location cannot be resolved.
    """
    return render(forecast_summary(location, days))


@tool
def get_historical_weather(location: str, start_date: str, end_date: str) -> str:
    """Get historical (ERA5 archive) weather for a location and date range.

    Use this for past dates. ERA5 reanalysis data is available from 1940 onwards.

    Args:
        location: A city or place name, for example "Berlin" or "Tokyo".
        start_date: Inclusive start date in ISO format (YYYY-MM-DD).
        end_date: Inclusive end date in ISO format (YYYY-MM-DD).

    Returns:
        A summary of temperature extremes and total precipitation over the range,
        or an explanatory message when the location cannot be resolved.
    """
    return render(historical_summary(location, start_date, end_date))


@tool
def get_climate_projection(location: str, start_date: str, end_date: str) -> str:
    """Get climate-model (CMIP6) projections for a location and future date range.

    Use this for long-range, decade-scale future periods rather than a short
    forecast. Projections run to 2050.

    Args:
        location: A city or place name, for example "Berlin" or "Tokyo".
        start_date: Inclusive start date in ISO format (YYYY-MM-DD).
        end_date: Inclusive end date in ISO format (YYYY-MM-DD).

    Returns:
        A summary of projected temperature extremes and total precipitation, or an
        explanatory message when the location cannot be resolved.
    """
    return render(climate_summary(location, start_date, end_date))


@tool
def get_air_quality(location: str) -> str:
    """Get current air-quality readings for a named location.

    Args:
        location: A city or place name, for example "Beijing" or "Los Angeles".

    Returns:
        A summary of particulate matter (PM2.5, PM10), ozone, and the European
        AQI, or an explanatory message when the location cannot be resolved.
    """
    return render(air_quality_summary(location))


@tool
def get_marine_forecast(location: str) -> str:
    """Get current marine (wave) conditions for a coastal location.

    Args:
        location: A coastal city or place name, for example "Honolulu".

    Returns:
        A summary of wave height and period, or an explanatory message when the
        location cannot be resolved or is not a marine point.
    """
    return render(marine_summary(location))


@tool
def get_river_discharge(location: str) -> str:
    """Get forecast river discharge (flood indicator) for a named location.

    Args:
        location: A city or place name near a river, for example "Cologne".

    Returns:
        A summary of forecast river discharge from the GloFAS model, or an
        explanatory message when the location cannot be resolved.
    """
    return render(river_discharge_summary(location))


@tool
def get_ensemble_forecast(location: str) -> str:
    """Get an ensemble temperature spread, conveying forecast uncertainty.

    Args:
        location: A city or place name, for example "Berlin" or "Tokyo".

    Returns:
        A summary of the ensemble member count and temperature range/mean, or an
        explanatory message when the location cannot be resolved.
    """
    return render(ensemble_summary(location))


@tool
def get_elevation(location: str) -> str:
    """Get the terrain elevation of a named location.

    Args:
        location: A city or place name, for example "Denver" or "La Paz".

    Returns:
        A one-line elevation summary in metres above sea level, or an explanatory
        message when the location cannot be resolved.
    """
    return render(elevation_summary(location))


@tool
def get_uv_index(location: str) -> str:
    """Get the current UV index and today's peak for a named location.

    Args:
        location: A city or place name, for example "Nairobi" or "Sydney".

    Returns:
        A summary of the UV index now and today's maximum with WHO risk bands, or
        an explanatory message when the location cannot be resolved.
    """
    return render(uv_index_summary(location))


@tool
def get_pollen(location: str) -> str:
    """Get current pollen levels for a named location (Europe).

    Pollen is sourced from the European CAMS model, so coverage is European;
    elsewhere values report as not available.

    Args:
        location: A city or place name, for example "Paris" or "Berlin".

    Returns:
        A summary of grass, tree, and weed pollen levels, or an explanatory
        message when the location cannot be resolved.
    """
    return render(pollen_summary(location))


@tool
def get_solar_potential(location: str, days: int = 3) -> str:
    """Get a daily solar-energy potential outlook for a named location.

    Args:
        location: A city or place name, for example "Madrid" or "Reykjavik".
        days: Number of forecast days to report (1-16).

    Returns:
        A multi-day summary of solar radiation, sunshine, and daylight hours, or an
        explanatory message when the location cannot be resolved.
    """
    return render(solar_summary(location, days))


@tool
def get_airspace(location: str) -> str:
    """List nearby controlled or restricted airspace for a location (verify officially).

    Decision support only, not an authoritative airspace or NOTAM check: always
    confirm with CAA Drone Assist or an official source before flying. Needs an
    OpenAIP API key; without one it reports the check as unavailable.

    Args:
        location: A city or place name, for example "Congleton UK".

    Returns:
        A list of nearby drone-relevant airspace volumes, a "none found" note, or a
        message that the lookup is unavailable.
    """
    return render(airspace_summary(location))


@tool
def get_aviation_weather(location: str) -> str:
    """Get the nearest airport's observed weather (METAR) for a location.

    Reports real observed wind, visibility, and cloud ceiling from the closest
    reporting station - a reality check against the model forecast, useful for
    flying.

    Args:
        location: A city or place name, for example "Manchester".

    Returns:
        A summary of the nearest station's observed conditions, or an explanatory
        message when none is found or the location cannot be resolved.
    """
    return render(aviation_summary(location))


@tool
def get_sun_times(location: str, days: int = 1) -> str:
    """Get sunrise, sunset, and daylight length for a named location.

    Args:
        location: A city or place name, for example "Tromsø" or "Quito".
        days: Number of days to report (1-16).

    Returns:
        A day-by-day summary of sunrise, sunset, and daylight hours, or an
        explanatory message when the location cannot be resolved.
    """
    return render(sun_times_summary(location, days))


@tool
def get_weather_at_coordinates(latitude: float, longitude: float) -> str:
    """Get the current weather at explicit coordinates, skipping name lookup.

    Use this when the user gives a latitude and longitude rather than a place name.

    Args:
        latitude: Latitude in decimal degrees (-90 to 90).
        longitude: Longitude in decimal degrees (-180 to 180).

    Returns:
        A summary of current conditions at the coordinates, or an explanatory
        message when the lookup fails.
    """
    return render(current_weather_at_coordinates(latitude, longitude))


@tool
def get_weather(location: str, when: str) -> str:
    """Get weather for a location on a specific date, choosing the right source.

    Routes automatically: past dates use the historical archive, near-term dates
    use the forecast, and far-future dates use climate projections. Prefer this
    tool when the user names a single date and you are unsure which source fits.

    Args:
        location: A city or place name, for example "Berlin" or "Tokyo".
        when: The date of interest in ISO format (YYYY-MM-DD).

    Returns:
        A weather summary drawn from the appropriate data source, or an
        explanatory message when the date or location cannot be resolved.
    """
    return render(weather_for_date(location, when))


@tool
def compare_weather(
    location: str,
    period_a_start: str,
    period_a_end: str,
    period_b_start: str,
    period_b_end: str,
) -> str:
    """Compare historical mean daily high temperature between two date ranges.

    Args:
        location: A city or place name, for example "Berlin" or "Tokyo".
        period_a_start: Inclusive ISO start date of the baseline period.
        period_a_end: Inclusive ISO end date of the baseline period.
        period_b_start: Inclusive ISO start date of the comparison period.
        period_b_end: Inclusive ISO end date of the comparison period.

    Returns:
        A one-line comparison of mean daily high temperature with the delta, or an
        explanatory message when the location cannot be resolved.
    """
    return render(
        compare_periods(
            location,
            (period_a_start, period_a_end),
            (period_b_start, period_b_end),
        )
    )


@tool
def assess_drone_conditions(location: str, drone: str) -> str:
    """Assess whether weather is suitable for flying one specific drone today.

    Use this for a single named drone. To cover the whole fleet (for example
    "all my drones" or "every drone"), use ``assess_fleet_conditions`` instead -
    do not call this tool once per drone.

    Covers the DJI Neo, Avata 2, and Mini 5 Pro. Combines wind and gusts up to
    500 m, precipitation, temperature, visibility, daylight, thunderstorm
    potential, and geomagnetic (Kp) activity into an hour-by-hour verdict, then
    adds UK CAA guidance and practical tips. Always relay the safety disclaimer.

    This tool is UK-scoped: the guidance follows UK CAA open-category rules and
    hourly timestamps are reported in UK local time, so for non-UK locations the
    hour labels are in UK time rather than the location's local time.

    Args:
        location: A city or place name, for example "Congleton UK".
        drone: The drone model, for example "Mini 5 Pro", "Avata 2", or "Neo".

    Returns:
        A per-hour flyability assessment with the best window, UK CAA notes, and
        tips; or a list of supported drones when the model is not recognised.
    """
    return render(drone_flight_summary(location, drone))


@tool
def assess_fleet_conditions(location: str) -> str:
    """Assess flying conditions for every supported drone at once.

    Use this when the user asks about all of their drones (for example "all my
    drones", "the fleet", or "every drone") rather than naming one - it covers the
    DJI Neo, Avata 2, and Mini 5 Pro in a single combined report, so you do not
    need to call ``assess_drone_conditions`` once per drone.

    Returns a compact comparison: shared site context (daylight, observed METAR,
    nearby airspace) and UK CAA rules once, then each drone's wind limit, best
    flying window, and per-day outlook side by side. Always relay the disclaimer.

    UK-scoped like ``assess_drone_conditions``: hourly timestamps are UK local
    time and the guidance follows UK CAA open-category rules.

    Args:
        location: A city or place name, for example "Congleton UK".

    Returns:
        A compact side-by-side flyability comparison across all supported drones,
        with shared site context, UK CAA notes, and the safety disclaimer.
    """
    return render(fleet_flight_summary(location))


@tool
def list_supported_drones() -> str:
    """List the drones the flight-assessment tool supports and their key limits.

    Returns:
        A short list of supported drone models with wind ratings and weights.
    """
    return describe_supported_drones(DRONE_PROFILES)
