"""Pure formatting of open-meteo time series into human-readable summaries.

These functions take typed :class:`~weather_agent.models.TimeSeries` data and
produce text. They perform no I/O and are safe to unit test directly. ``None``
samples (open-meteo gaps) are rendered as ``"n/a"`` and ignored in aggregates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weather_agent.weather_codes import describe_weather_code

if TYPE_CHECKING:
    from weather_agent.models import CurrentReadings, CurrentWeather, TimeSeries, UvIndex

_SECONDS_PER_HOUR = 3600.0
_SOLAR_RADIATION_SUM = "shortwave_radiation_sum"
_SUNSHINE_DURATION = "sunshine_duration"
_DAYLIGHT_DURATION = "daylight_duration"
SOLAR_DAILY_VARIABLES = f"{_SOLAR_RADIATION_SUM},{_SUNSHINE_DURATION},{_DAYLIGHT_DURATION}"

# UV index risk bands (WHO): (exclusive upper bound, label). The final band has
# no upper bound and catches everything above the previous threshold.
_UV_BANDS: tuple[tuple[float, str], ...] = (
    (3.0, "low"),
    (6.0, "moderate"),
    (8.0, "high"),
    (11.0, "very high"),
)
_UV_EXTREME = "extreme"

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
        f"{series.timestamps[index]}: {_forecast_body(series, index)}" for index in range(count)
    ]
    return f"Forecast for {place_label}:\n" + "\n".join(lines)


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
        f"{heading} for {place_label} on {series.timestamps[index]}: "
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
    return f"{period_label} for {place_label}: " + ", ".join(parts) + "."


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
        f"{variable} {_format_value(_cell(series, variable, 0))}" for variable in variables
    )
    return f"{label} for {place_label} (as of {series.timestamps[0]}): {readings}."


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
    return f"Current weather in {place_label}: " + ", ".join(parts) + f" (as of {weather.time})."


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
        f"{variable} {_format_value(readings.values.get(variable))}" for variable in variables
    )
    return f"{label} for {place_label} (as of {readings.time}): {rendered}."


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
        f"{label} for {place_label} (as of {series.timestamps[0]}): "
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


def _uv_band(value: float) -> str:
    for upper, label in _UV_BANDS:
        if value < upper:
            return label
    return _UV_EXTREME


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
        parts.append(f"now {uv.current:.1f} ({_uv_band(uv.current)})")
    if uv.today_max is not None:
        parts.append(f"today's max {uv.today_max:.1f} ({_uv_band(uv.today_max)})")
    return f"UV index for {place_label} (as of {uv.time}): " + ", ".join(parts) + "."


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
            f"{series.timestamps[index]}: "
            f"radiation {_format_value(_cell(series, _SOLAR_RADIATION_SUM, index))} MJ/m², "
            f"sunshine {_hours(_cell(series, _SUNSHINE_DURATION, index))}, "
            f"daylight {_hours(_cell(series, _DAYLIGHT_DURATION, index))}"
        )
        for index in range(count)
    ]
    return f"Solar potential for {place_label}:\n" + "\n".join(lines)


def _hours(seconds: float | None) -> str:
    return "n/a" if seconds is None else f"{seconds / _SECONDS_PER_HOUR:.1f} h"
