"""Tests for the pure time-series reporting helpers."""

from weather_agent.models import CurrentReadings, TimeSeries
from weather_agent.reporting import (
    describe_comparison,
    describe_current_readings,
    describe_daily_forecast,
    describe_ensemble_spread,
    describe_forecast_day,
    describe_latest_values,
    describe_period,
)


def _series() -> TimeSeries:
    return TimeSeries(
        timestamps=("2026-06-14", "2026-06-15", "2026-06-16"),
        series={
            "temperature_2m_max": (21.0, 23.5, None),
            "temperature_2m_min": (11.0, 12.5, 13.0),
            "precipitation_sum": (0.0, 4.2, 1.0),
        },
    )


def test_describe_daily_forecast_lists_requested_days() -> None:
    """The forecast description lists one line per requested day."""
    summary = describe_daily_forecast("Berlin", _series(), max_days=2)

    assert "Berlin" in summary
    assert "2026-06-14" in summary
    assert "2026-06-15" in summary
    assert "2026-06-16" not in summary


def test_describe_daily_forecast_renders_missing_as_na() -> None:
    """A None sample is rendered as n/a rather than crashing."""
    summary = describe_daily_forecast("Berlin", _series(), max_days=3)

    assert "n/a" in summary


def test_describe_forecast_day_renders_single_day() -> None:
    """The single-day renderer shows only the requested day."""
    summary = describe_forecast_day("Berlin", _series(), index=1)

    assert "Forecast for Berlin on 2026-06-15:" in summary
    assert "high 23.5" in summary
    assert "2026-06-14" not in summary
    assert "2026-06-16" not in summary


def test_describe_forecast_day_out_of_range_is_noted() -> None:
    """An out-of-range index yields a no-data note, not an error."""
    assert "No forecast data" in describe_forecast_day("Berlin", _series(), index=9)


def test_describe_daily_forecast_handles_empty_series() -> None:
    """An empty series yields an explanatory note, not an exception."""
    empty = TimeSeries(timestamps=(), series={})

    assert "No forecast data" in describe_daily_forecast("Berlin", empty, max_days=3)


def test_describe_period_aggregates_extremes_and_totals() -> None:
    """Period aggregation ignores None and reports extremes and totals."""
    summary = describe_period("Berlin", _series(), "Historical weather")

    assert "Historical weather for Berlin" in summary
    assert "3 day(s)" in summary
    assert "max 23.5 °C" in summary
    assert "min 11.0 °C" in summary
    assert "total precipitation 5.2 mm" in summary


def test_describe_period_handles_empty_series() -> None:
    """An empty series yields an explanatory note."""
    empty = TimeSeries(timestamps=(), series={})

    assert "No historical weather data" in describe_period("Berlin", empty, "Historical weather")


def test_describe_latest_values_reports_first_row() -> None:
    """The latest-values helper reports the first row of named variables."""
    series = TimeSeries(
        timestamps=("2026-06-15T00:00", "2026-06-15T01:00"),
        series={"pm2_5": (12.0, 13.0), "pm10": (20.0, None)},
    )

    summary = describe_latest_values("Berlin", series, "Air quality", ("pm2_5", "pm10"))

    assert "Air quality for Berlin (as of 2026-06-15T00:00)" in summary
    assert "pm2_5 12.0" in summary
    assert "pm10 20.0" in summary


def test_describe_latest_values_handles_empty_series() -> None:
    """An empty series yields an explanatory note."""
    empty = TimeSeries(timestamps=(), series={})

    summary = describe_latest_values("Berlin", empty, "Air quality", ("pm2_5",))
    assert "No air quality data" in summary


def test_describe_current_readings_reports_present_hour() -> None:
    """Current readings render the present-hour values with their own timestamp."""
    readings = CurrentReadings(
        time="2026-06-15T13:00",
        values={"pm2_5": 12.0, "pm10": 20.0, "european_aqi": None},
    )

    summary = describe_current_readings(
        "Berlin", readings, "Air quality", ("pm2_5", "pm10", "european_aqi")
    )

    assert "Air quality for Berlin (as of 2026-06-15T13:00)" in summary
    assert "pm2_5 12.0" in summary
    assert "european_aqi n/a" in summary


def test_describe_ensemble_spread_reports_range_and_mean() -> None:
    """The ensemble helper aggregates member columns at the first row."""
    series = TimeSeries(
        timestamps=("2026-06-15T00:00",),
        series={
            "temperature_2m_member01": (10.0,),
            "temperature_2m_member02": (14.0,),
            "temperature_2m_member03": (12.0,),
        },
    )

    summary = describe_ensemble_spread("Berlin", series, "Ensemble temperature")

    assert "3 members" in summary
    assert "range 10.0-14.0" in summary
    assert "mean 12.0" in summary


def test_describe_ensemble_spread_handles_empty_series() -> None:
    """An empty series yields an explanatory note."""
    empty = TimeSeries(timestamps=(), series={})

    summary = describe_ensemble_spread("Berlin", empty, "Ensemble temperature")
    assert "No ensemble temperature data" in summary


def test_describe_comparison_reports_delta() -> None:
    """The comparison helper reports both periods and the temperature delta."""
    warm = TimeSeries(timestamps=("2026-07-01",), series={"temperature_2m_max": (30.0,)})
    cool = TimeSeries(timestamps=("2026-01-01",), series={"temperature_2m_max": (5.0,)})

    summary = describe_comparison("Berlin", "summer", warm, "winter", cool)

    assert "summer 30.0 °C vs winter 5.0 °C" in summary
    assert "delta -25.0 °C" in summary


def test_describe_comparison_omits_delta_when_data_missing() -> None:
    """The delta is omitted when a period has no usable values."""
    warm = TimeSeries(timestamps=("2026-07-01",), series={"temperature_2m_max": (30.0,)})
    empty = TimeSeries(timestamps=("2026-01-01",), series={"temperature_2m_max": (None,)})

    summary = describe_comparison("Berlin", "summer", warm, "winter", empty)

    assert "delta" not in summary
    assert "n/a" in summary
