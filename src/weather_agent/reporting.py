"""Pure formatting of open-meteo time series into human-readable summaries.

These functions take typed :class:`~weather_agent.models.TimeSeries` data and
produce text. They perform no I/O and are safe to unit test directly. ``None``
samples (open-meteo gaps) are rendered as ``"n/a"`` and ignored in aggregates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weather_agent.models import CurrentReadings, TimeSeries

_TEMP_MAX = "temperature_2m_max"
_TEMP_MIN = "temperature_2m_min"
_PRECIP_SUM = "precipitation_sum"

DAILY_VARIABLES = f"{_TEMP_MAX},{_TEMP_MIN},{_PRECIP_SUM}"


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
        (
            f"{series.timestamps[index]}: "
            f"high {_format_value(_cell(series, _TEMP_MAX, index))} °C, "
            f"low {_format_value(_cell(series, _TEMP_MIN, index))} °C, "
            f"precip {_format_value(_cell(series, _PRECIP_SUM, index))} mm"
        )
        for index in range(count)
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
        f"high {_format_value(_cell(series, _TEMP_MAX, index))} °C, "
        f"low {_format_value(_cell(series, _TEMP_MIN, index))} °C, "
        f"precip {_format_value(_cell(series, _PRECIP_SUM, index))} mm."
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
