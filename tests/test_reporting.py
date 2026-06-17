"""Tests for the pure time-series reporting helpers."""

import pytest

from weather_agent.models import (
    Airspace,
    CloudLayer,
    CurrentReadings,
    CurrentWeather,
    DayAlmanac,
    MetarReport,
    TimeSeries,
    UvIndex,
)
from weather_agent.reporting import (
    describe_airspace,
    describe_comparison,
    describe_current_readings,
    describe_current_weather,
    describe_daily_forecast,
    describe_ensemble_spread,
    describe_forecast_day,
    describe_latest_values,
    describe_metar,
    describe_period,
    describe_solar,
    describe_sun_times,
    describe_uv,
    format_clock,
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


def test_describe_current_weather_names_condition_and_extras() -> None:
    """Current weather names the WMO condition and appends present optional fields."""
    weather = CurrentWeather(
        time="2026-06-15T12:00",
        temperature_celsius=21.3,
        wind_speed_kmh=9.7,
        weather_code=61.0,
        relative_humidity_pct=65.0,
        dew_point_celsius=14.2,
        surface_pressure_hpa=1013.0,
        cloud_cover_pct=90.0,
    )

    summary = describe_current_weather("Berlin", weather)

    assert "Current weather in Berlin: slight rain, 21.3 °C, wind 9.7 km/h" in summary
    assert "humidity 65%" in summary
    assert "cloud 90%" in summary


def test_describe_current_weather_omits_absent_optionals() -> None:
    """Optional fields that are None are left out of the line."""
    weather = CurrentWeather(
        time="2026-06-15T12:00",
        temperature_celsius=21.3,
        wind_speed_kmh=9.7,
        weather_code=None,
        relative_humidity_pct=None,
        dew_point_celsius=None,
        surface_pressure_hpa=None,
        cloud_cover_pct=None,
    )

    summary = describe_current_weather("Berlin", weather)

    assert "unknown, 21.3 °C, wind 9.7 km/h" in summary
    assert "humidity" not in summary


@pytest.mark.parametrize(
    ("value", "band"),
    [(1.0, "low"), (4.0, "moderate"), (7.0, "high"), (9.0, "very high"), (11.5, "extreme")],
)
def test_describe_uv_bands(value: float, band: str) -> None:
    """The UV index maps to the right WHO risk band."""
    uv = UvIndex(time="2026-06-15T12:00", current=value, today_max=value)

    assert band in describe_uv("Nairobi", uv)


def test_describe_uv_handles_no_data() -> None:
    """All-None UV yields an explanatory note."""
    uv = UvIndex(time="t", current=None, today_max=None)

    assert "No UV data" in describe_uv("Nairobi", uv)


@pytest.mark.parametrize(
    ("iso", "expected"),
    [
        ("2026-06-16T04:43", "04:43"),
        ("2026-06-16T21:21:00", "21:21"),
        ("2026-06-16", "n/a"),
        ("", "n/a"),
    ],
)
def test_format_clock(iso: str, expected: str) -> None:
    """A clock time is extracted from an ISO timestamp, or n/a when absent."""
    assert format_clock(iso) == expected


def test_describe_sun_times_reports_each_day() -> None:
    """Sun times render sunrise, sunset, and daylight per day."""
    almanac = (
        DayAlmanac(
            date="2026-06-16",
            sunrise="2026-06-16T04:43",
            sunset="2026-06-16T21:21",
            daylight_seconds=59880.0,
        ),
    )

    summary = describe_sun_times("London", almanac)

    assert "Sun times for London" in summary
    assert "sunrise 04:43" in summary
    assert "sunset 21:21" in summary
    assert "daylight 16.6 h" in summary


def test_describe_sun_times_handles_empty() -> None:
    """No almanac rows yields an explanatory note."""
    assert "No sun-time data" in describe_sun_times("London", ())


def test_describe_solar_reports_radiation_and_hours() -> None:
    """Solar potential reports radiation in MJ/m² and durations in hours."""
    series = TimeSeries(
        timestamps=("2026-06-15",),
        series={
            "shortwave_radiation_sum": (28.0,),
            "sunshine_duration": (36000.0,),
            "daylight_duration": (57600.0,),
        },
    )

    summary = describe_solar("Madrid", series, max_days=1)

    assert "radiation 28.0 MJ/m²" in summary
    assert "sunshine 10.0 h" in summary
    assert "daylight 16.0 h" in summary


def test_describe_metar_renders_observed_conditions() -> None:
    """METAR rendering names the station, wind, visibility, and ceiling."""
    report = MetarReport(
        station="EGCC",
        latitude=53.35,
        longitude=-2.28,
        observed="2026-06-16 12:00:00",
        wind_dir_deg=240.0,
        wind_speed_kt=12.0,
        wind_gust_kt=20.0,
        visibility_sm=10.0,
        clouds=(CloudLayer("OVC", 2500.0),),
        ceiling_ft_agl=2500.0,
        raw="EGCC 161200Z 24012G20KT",
    )

    summary = describe_metar("Manchester", report)

    assert "Nearest METAR for Manchester - EGCC" in summary
    assert "wind 240 deg at 12 kt gusting 20 kt" in summary
    assert "ceiling 2500 ft" in summary


def test_describe_metar_handles_no_ceiling() -> None:
    """A report with no broken/overcast layer shows 'no ceiling'."""
    report = MetarReport(
        station="EGCC",
        latitude=53.35,
        longitude=-2.28,
        observed="t",
        wind_dir_deg=None,
        wind_speed_kt=None,
        wind_gust_kt=None,
        visibility_sm=None,
        clouds=(),
        ceiling_ft_agl=None,
        raw="",
    )

    assert "no ceiling" in describe_metar("Manchester", report)


def test_describe_airspace_lists_zones() -> None:
    """Airspace rendering lists each zone with type and class, and a verify note."""
    airspaces = (
        Airspace(name="MANCHESTER CTR", type_label="CTR", icao_class="D", lower_limit="GND"),
    )

    summary = describe_airspace("Manchester", airspaces)

    assert "MANCHESTER CTR (CTR, ICAO D, base GND)" in summary
    assert "verify" in summary.lower()


def test_describe_airspace_uses_note_when_unavailable() -> None:
    """A status note replaces the list when the check could not run."""
    summary = describe_airspace("Manchester", (), note="unavailable (no OPENAIP_API_KEY)")

    assert "unavailable (no OPENAIP_API_KEY)" in summary


def test_describe_airspace_none_found() -> None:
    """No nearby airspace yields a reassuring-but-verify line."""
    assert "No notable airspace" in describe_airspace("Remote", ())


def test_describe_comparison_omits_delta_when_data_missing() -> None:
    """The delta is omitted when a period has no usable values."""
    warm = TimeSeries(timestamps=("2026-07-01",), series={"temperature_2m_max": (30.0,)})
    empty = TimeSeries(timestamps=("2026-01-01",), series={"temperature_2m_max": (None,)})

    summary = describe_comparison("Berlin", "summer", warm, "winter", empty)

    assert "delta" not in summary
    assert "n/a" in summary
