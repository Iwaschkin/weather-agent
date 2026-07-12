"""Pure formatting of open-meteo time series into human-readable summaries.

These functions take typed :class:`~weather_agent.models.TimeSeries` data and
produce text. They perform no I/O and are safe to unit test directly. ``None``
samples (open-meteo gaps) are rendered as ``"n/a"`` and ignored in aggregates.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from weather_agent.bands import UV_SCALE, classify, render_reading
from weather_agent.weather_codes import describe_weather_code

if TYPE_CHECKING:
    from datetime import date

    from weather_agent.models import (
        Airspace,
        CurrentReadings,
        CurrentWeather,
        DayAlmanac,
        MetarReport,
        TimeContext,
        TimeSeries,
        UvIndex,
    )

_SECONDS_PER_HOUR = 3600.0
_SOLAR_RADIATION_SUM = "shortwave_radiation_sum"
_SUNSHINE_DURATION = "sunshine_duration"
_DAYLIGHT_DURATION = "daylight_duration"
SOLAR_DAILY_VARIABLES = f"{_SOLAR_RADIATION_SUM},{_SUNSHINE_DURATION},{_DAYLIGHT_DURATION}"

_TEMP_MAX = "temperature_2m_max"
_TEMP_MIN = "temperature_2m_min"
_PRECIP_SUM = "precipitation_sum"
_WEATHER_CODE = "weather_code"
_PRECIP_PROB_MAX = "precipitation_probability_max"
_WIND_GUST_MAX = "wind_gusts_10m_max"

# Lean daily set shared by the archive and climate endpoints, which do not
# support condition/probability/gust daily aggregates.
DAILY_VARIABLES = f"{_TEMP_MAX},{_TEMP_MIN},{_PRECIP_SUM}"
# Richer daily set for the forecast endpoint only (adds condition, rain chance,
# and peak gust); kept separate so it is never sent to archive/climate.
FORECAST_DAILY_VARIABLES = f"{DAILY_VARIABLES},{_WEATHER_CODE},{_PRECIP_PROB_MAX},{_WIND_GUST_MAX}"


def _present(values: tuple[float | None, ...]) -> list[float]:
    return [value for value in values if value is not None]


def _mean(values: tuple[float | None, ...]) -> float | None:
    present = _present(values)
    return sum(present) / len(present) if present else None


def _format_value(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _time_label(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M %Z")
    return value.isoformat()


def _zone_label(context: TimeContext) -> str:
    return f"{context.timezone} ({context.abbreviation})"


def _cell(series: TimeSeries, variable: str, index: int) -> float | None:
    column = series.series.get(variable)
    if column is None or index >= len(column):
        return None
    return column[index]


def _forecast_body(series: TimeSeries, index: int) -> str:
    """Render the condition/temperature/precipitation body for one forecast day.

    Condition is always shown; rain chance and peak gust are appended only when
    the series carries those columns (the forecast endpoint does; the archive does
    not), so the same renderer serves forecast and recent-past days.

    Args:
        series: Daily time series for the day's row.
        index: Zero-based row to render.

    Returns:
        A body string without the leading date or trailing period.
    """
    condition = describe_weather_code(_cell(series, _WEATHER_CODE, index))
    body = (
        f"{condition}, "
        f"high {_format_value(_cell(series, _TEMP_MAX, index))} °C, "
        f"low {_format_value(_cell(series, _TEMP_MIN, index))} °C, "
        f"precip {_format_value(_cell(series, _PRECIP_SUM, index))} mm"
    )
    probability = _cell(series, _PRECIP_PROB_MAX, index)
    if probability is not None:
        body += f" ({probability:.0f}% chance)"
    gust = _cell(series, _WIND_GUST_MAX, index)
    if gust is not None:
        body += f", gust {gust:.0f} km/h"
    return body


def describe_daily_forecast(place_label: str, series: TimeSeries, max_days: int) -> str:
    """Render up to ``max_days`` daily forecast rows as readable lines.

    Args:
        place_label: Human-readable location name to head the summary.
        series: Daily time series containing temperature and precipitation columns.
        max_days: Maximum number of leading days to include.

    Returns:
        A multi-line summary, or a note when the series has no rows.
    """
    count = min(max_days, len(series.timestamps))
    if count == 0:
        return f"No forecast data available for {place_label}."
    lines = [
        f"{_time_label(series.timestamps[index])}: {_forecast_body(series, index)}"
        for index in range(count)
    ]
    return (
        f"Forecast for {place_label} (local dates: {_zone_label(series.time_context)}):\n"
        + "\n".join(lines)
    )


def describe_forecast_day(
    place_label: str,
    series: TimeSeries,
    index: int,
    heading: str = "Forecast",
) -> str:
    """Render a single daily row (the day at ``index``) as one line.

    Args:
        place_label: Human-readable location name.
        series: Daily time series containing temperature and precipitation columns.
        index: Zero-based row to render.
        heading: Leading noun for the line, for example ``"Forecast"`` for a
            future day or ``"Weather"`` for a recent past day served by the same
            endpoint, so past data is not mislabelled as a forecast.

    Returns:
        A one-line summary of that day, or a note when the day is out of range.
    """
    if not 0 <= index < len(series.timestamps):
        return f"No {heading.lower()} data available for {place_label}."
    return (
        f"{heading} for {place_label} on {_time_label(series.timestamps[index])} "
        f"({_zone_label(series.time_context)}): "
        f"{_forecast_body(series, index)}."
    )


def describe_period(place_label: str, series: TimeSeries, period_label: str) -> str:
    """Aggregate a daily time series over its whole range into one line.

    Args:
        place_label: Human-readable location name.
        series: Daily time series spanning the period of interest.
        period_label: Label describing the period, for example
            ``"Historical weather"`` or ``"Climate projection"``.

    Returns:
        A single-line summary of day count, temperature extremes, and total
        precipitation, omitting any aggregate whose column is entirely missing.
    """
    days = len(series.timestamps)
    if days == 0:
        return f"No {period_label.lower()} data available for {place_label}."
    highs = _present(series.series.get(_TEMP_MAX, ()))
    lows = _present(series.series.get(_TEMP_MIN, ()))
    precip = _present(series.series.get(_PRECIP_SUM, ()))
    parts = [f"{days} day(s)"]
    if highs:
        parts.append(f"max {max(highs):.1f} °C")
    if lows:
        parts.append(f"min {min(lows):.1f} °C")
    if precip:
        parts.append(f"total precipitation {sum(precip):.1f} mm")
    return (
        f"{period_label} for {place_label} (local dates: {_zone_label(series.time_context)}): "
        + ", ".join(parts)
        + "."
    )


def describe_latest_values(
    place_label: str,
    series: TimeSeries,
    label: str,
    variables: tuple[str, ...],
) -> str:
    """Render the first row of named variables from a time series.

    Reports ``series`` row 0, not the chronologically latest row. This is correct
    for a *daily* series with no past days, where row 0 is the current day (as used
    for river discharge). It is the wrong choice for an hourly series, whose row 0
    is the start of the day rather than the current hour - hourly "now" lookups use
    the API's ``current`` block instead (see :func:`describe_current_readings`).

    Args:
        place_label: Human-readable location name.
        series: Time series whose first row is the reading of interest.
        label: Label describing the data, for example ``"River discharge"``.
        variables: Variable names to report, in order.

    Returns:
        A single-line summary of the first row's values, or a note when the
        series has no rows.
    """
    if not series.timestamps:
        return f"No {label.lower()} data available for {place_label}."
    readings = ", ".join(
        render_reading(variable, _cell(series, variable, 0)) for variable in variables
    )
    return (
        f"{label} for {place_label} (as of {_time_label(series.timestamps[0])}; "
        f"{_zone_label(series.time_context)}): {readings}."
    )


def describe_current_weather(place_label: str, weather: CurrentWeather) -> str:
    """Render current conditions as a one-line summary naming the WMO condition.

    Always includes the condition, temperature, and wind; humidity, dew point,
    cloud cover, and pressure are appended only when the API supplied them.

    Args:
        place_label: Human-readable location name.
        weather: The parsed current-weather reading.

    Returns:
        A single-line current-conditions summary.
    """
    parts = [
        describe_weather_code(weather.weather_code),
        f"{weather.temperature_celsius:.1f} °C",
        f"wind {weather.wind_speed_kmh:.1f} km/h",
    ]
    if weather.relative_humidity_pct is not None:
        parts.append(f"humidity {weather.relative_humidity_pct:.0f}%")
    if weather.dew_point_celsius is not None:
        parts.append(f"dew point {weather.dew_point_celsius:.1f} °C")
    if weather.cloud_cover_pct is not None:
        parts.append(f"cloud {weather.cloud_cover_pct:.0f}%")
    if weather.surface_pressure_hpa is not None:
        parts.append(f"pressure {weather.surface_pressure_hpa:.0f} hPa")
    return (
        f"Current weather in {place_label}: "
        + ", ".join(parts)
        + f" (as of {_time_label(weather.time)}; {_zone_label(weather.time_context)})."
    )


def describe_current_readings(
    place_label: str,
    readings: CurrentReadings,
    label: str,
    variables: tuple[str, ...],
) -> str:
    """Render current-hour readings of named variables for a location.

    Args:
        place_label: Human-readable location name.
        readings: The current-hour readings from the API's ``current`` block.
        label: Label describing the data, for example ``"Air quality"``.
        variables: Variable names to report, in order.

    Returns:
        A single-line summary of the present-hour values, timestamped with the
        reading's own time.
    """
    rendered = ", ".join(
        render_reading(variable, readings.values.get(variable)) for variable in variables
    )
    return (
        f"{label} for {place_label} (as of {_time_label(readings.time)}; "
        f"{_zone_label(readings.time_context)}): {rendered}."
    )


def describe_ensemble_spread(place_label: str, series: TimeSeries, label: str) -> str:
    """Summarise the spread across ensemble member columns at the first row.

    Args:
        place_label: Human-readable location name.
        series: Ensemble time series whose columns are per-member values.
        label: Label describing the data, for example ``"Ensemble forecast"``.

    Returns:
        A single-line summary of member count and value range, or a note when no
        member values are present.
    """
    if not series.timestamps:
        return f"No {label.lower()} data available for {place_label}."
    members = _present(tuple(column[0] for column in series.series.values() if column))
    if not members:
        return f"No {label.lower()} member values available for {place_label}."
    mean = sum(members) / len(members)
    return (
        f"{label} for {place_label} (valid {_time_label(series.timestamps[0])}; "
        f"{_zone_label(series.time_context)}): "
        f"{len(members)} members, range {min(members):.1f}-{max(members):.1f}, "
        f"mean {mean:.1f}."
    )


def describe_comparison(
    place_label: str,
    label_a: str,
    series_a: TimeSeries,
    label_b: str,
    series_b: TimeSeries,
) -> str:
    """Compare mean daily high temperature between two daily time series.

    Args:
        place_label: Human-readable location name.
        label_a: Label for the first period, for example a date range.
        series_a: Daily time series for the first period.
        label_b: Label for the second period.
        series_b: Daily time series for the second period.

    Returns:
        A single-line comparison of mean daily high temperature, including the
        delta when both periods have data.
    """
    temp_a = _mean(series_a.series.get(_TEMP_MAX, ()))
    temp_b = _mean(series_b.series.get(_TEMP_MAX, ()))
    line = (
        f"Comparison for {place_label}: mean daily high "
        f"{label_a} {_format_value(temp_a)} °C vs {label_b} {_format_value(temp_b)} °C"
    )
    if temp_a is not None and temp_b is not None:
        line += f" (delta {temp_b - temp_a:+.1f} °C)"
    return line + "."


def _metar_wind(report: MetarReport) -> str:
    if report.wind_speed_kt is None:
        return ""
    if report.wind_dir_deg is not None:
        wind = f"wind {report.wind_dir_deg:.0f} deg at {report.wind_speed_kt:.0f} kt"
    else:
        wind = f"wind {report.wind_speed_kt:.0f} kt"
    if report.wind_gust_kt is not None:
        wind += f" gusting {report.wind_gust_kt:.0f} kt"
    return wind


def describe_metar(place_label: str, report: MetarReport) -> str:
    """Render the nearest station's observed conditions as one line.

    Args:
        place_label: Human-readable location name.
        report: The nearest METAR observation.

    Returns:
        A single-line observed-conditions summary (wind, visibility, ceiling).
    """
    ceiling = (
        f"ceiling {report.ceiling_ft_agl:.0f} ft"
        if report.ceiling_ft_agl is not None
        else "no ceiling"
    )
    parts = [_metar_wind(report)]
    if report.visibility_sm is not None:
        parts.append(f"visibility {report.visibility_sm:.0f} SM")
    parts.append(ceiling)
    body = ", ".join(part for part in parts if part) or "no data"
    observed = report.observed.strftime("%Y-%m-%d %H:%M UTC")
    return f"Nearest METAR for {place_label} - {report.station} (as of {observed}): {body}."


def describe_airspace(place_label: str, airspaces: tuple[Airspace, ...], note: str = "") -> str:
    """Render nearby airspace volumes as decision-support text (not authoritative).

    Args:
        place_label: Human-readable location name.
        airspaces: Nearby drone-relevant airspaces.
        note: A status line used instead of a list when the check was unavailable.

    Returns:
        A multi-line list of nearby airspace, a status note, or a "none found"
        line - always reminding the reader to verify officially.
    """
    if note:
        return f"Airspace near {place_label}: {note}"
    if not airspaces:
        return f"No notable airspace found near {place_label} (always verify officially)."
    lines = [f"Airspace near {place_label} (verify on CAA Drone Assist / official sources):"]
    for airspace in airspaces:
        klass = f", ICAO {airspace.icao_class}" if airspace.icao_class else ""
        base = f", base {airspace.lower_limit}" if airspace.lower_limit else ""
        lines.append(f"  - {airspace.name} ({airspace.type_label}{klass}{base})")
    return "\n".join(lines)


def describe_location_comparison(
    heading: str,
    unit: str,
    ranked: tuple[tuple[str, float], ...],
    problems: tuple[str, ...] = (),
) -> str:
    """Render a ranked, side-by-side comparison of locations by one metric.

    Args:
        heading: The comparison heading, including the ranking direction (for
            example ``"Location comparison by temperature (highest first)"``).
        unit: Unit appended to each value; empty for a unitless metric.
        ranked: ``(label, value)`` pairs already sorted into ranking order.
        problems: Notes for locations that could not be ranked (for example not
            found, or the metric was unavailable).

    Returns:
        A multi-line ranked list, with a trailing note for any skipped locations.
    """
    unit_suffix = f" {unit}" if unit else ""
    lines = [f"{heading}:"]
    lines.extend(
        f"  {position}. {label}: {value:.1f}{unit_suffix}"
        for position, (label, value) in enumerate(ranked, start=1)
    )
    if problems:
        lines.append(f"Not compared: {'; '.join(problems)}.")
    return "\n".join(lines)


def describe_uv(place_label: str, uv: UvIndex) -> str:
    """Render the UV index now and today's peak with WHO risk bands.

    Args:
        place_label: Human-readable location name.
        uv: The current UV index and today's maximum.

    Returns:
        A single-line UV summary, naming the risk band for each value present.
    """
    if uv.current is None and uv.today_max is None:
        return f"No UV data available for {place_label}."
    parts: list[str] = []
    if uv.current is not None:
        parts.append(f"now {uv.current:.1f} ({classify(UV_SCALE, uv.current)})")
    if uv.today_max is not None:
        parts.append(f"today's max {uv.today_max:.1f} ({classify(UV_SCALE, uv.today_max)})")
    return (
        f"UV index for {place_label} (as of {_time_label(uv.time)}; "
        f"{_zone_label(uv.time_context)}): " + ", ".join(parts) + "."
    )


def describe_solar(place_label: str, series: TimeSeries, max_days: int) -> str:
    """Render daily solar potential: radiation, sunshine, and daylight.

    Args:
        place_label: Human-readable location name.
        series: Daily time series with solar radiation and duration columns.
        max_days: Maximum number of leading days to include.

    Returns:
        A multi-line solar summary, or a note when the series has no rows.
    """
    count = min(max_days, len(series.timestamps))
    if count == 0:
        return f"No solar data available for {place_label}."
    lines = [
        (
            f"{_time_label(series.timestamps[index])}: "
            f"radiation {_format_value(_cell(series, _SOLAR_RADIATION_SUM, index))} MJ/m², "
            f"sunshine {_hours(_cell(series, _SUNSHINE_DURATION, index))}, "
            f"daylight {_hours(_cell(series, _DAYLIGHT_DURATION, index))}"
        )
        for index in range(count)
    ]
    return (
        f"Solar potential for {place_label} (local dates: "
        f"{_zone_label(series.time_context)}):\n" + "\n".join(lines)
    )


def _hours(seconds: float | None) -> str:
    return "n/a" if seconds is None else f"{seconds / _SECONDS_PER_HOUR:.1f} h"


def format_clock(value: datetime | None) -> str:
    """Format a local aware timestamp as a clock time and abbreviation.

    Args:
        value: Aware local timestamp, or ``None`` when unavailable.

    Returns:
        A ``HH:MM ZZZ`` label, or ``"n/a"`` when unavailable.
    """
    return "n/a" if value is None else value.strftime("%H:%M %Z")


def describe_sun_times(place_label: str, almanac: tuple[DayAlmanac, ...]) -> str:
    """Render daily sunrise, sunset, and daylight length for a location.

    Args:
        place_label: Human-readable location name.
        almanac: One row per day, in chronological order.

    Returns:
        A multi-line sun-times summary, or a note when no rows are available.
    """
    if not almanac:
        return f"No sun-time data available for {place_label}."
    lines = [
        (
            f"{day.date.isoformat()}: sunrise {format_clock(day.sunrise)}, "
            f"sunset {format_clock(day.sunset)}, "
            f"daylight {_hours(day.daylight_seconds)}"
        )
        for day in almanac
    ]
    return f"Sun times for {place_label} ({_zone_label(almanac[0].time_context)}):\n" + "\n".join(
        lines
    )
