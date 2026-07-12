"""Tests for drone profile lookup and the pure flyability engine."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from tests.time_helpers import LONDON_SUMMER_CONTEXT, aware
from weather_agent.drone import AVATA_2, MINI_5_PRO, MINI_5_PRO_PLUS, NEO, NEO_FPV, find_profile
from weather_agent.flyability import assess_forecast, assess_hour, best_window, daily_outlooks
from weather_agent.models import (
    DroneFlightHour,
    DroneForecast,
    DroneProfile,
    HourAssessment,
    Verdict,
)

_GOOD_HOUR = DroneFlightHour(
    time=aware("2026-06-16T10:00"),
    temperature_c=18.0,
    apparent_temperature_c=18.0,
    wind_gust_10m_kmh=10.0,
    wind_max_0_500m_kmh=12.0,
    precipitation_mm=0.0,
    precipitation_probability_pct=0.0,
    visibility_m=20000.0,
    cape=0.0,
    freezing_level_agl_m=2500.0,
    is_day=True,
    cloud_cover_low_pct=10.0,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("neo", NEO),
        ("DJI Neo", NEO),
        ("Neo FPV", NEO_FPV),
        ("Avata 2", AVATA_2),
        ("mini 5 pro", MINI_5_PRO),
        ("MINI5PRO", MINI_5_PRO),
        ("Mini 5 Pro Plus", MINI_5_PRO_PLUS),
    ],
)
def test_find_profile_resolves_aliases(name: str, expected: DroneProfile) -> None:
    """Known drone names and aliases resolve to the right profile."""
    assert find_profile(name) is expected


def test_find_profile_unknown_returns_none() -> None:
    """An unknown drone name resolves to None."""
    assert find_profile("Phantom 9") is None


def test_assess_hour_good_conditions() -> None:
    """Calm, mild, clear daytime conditions are good for the Mini 5 Pro."""
    result = assess_hour(MINI_5_PRO, _GOOD_HOUR)

    assert result.verdict is Verdict.GOOD
    assert result.limiting_factors == ()


def test_assess_hour_no_fly_on_strong_gusts() -> None:
    """Gusts above the rating are no-fly, citing the wind limit."""
    # 50 km/h ~ 13.9 m/s, above the Neo's 8 m/s limit.
    gusty = replace(_GOOD_HOUR, wind_gust_10m_kmh=50.0, wind_max_0_500m_kmh=50.0)
    result = assess_hour(NEO, gusty)

    assert result.verdict is Verdict.NO_FLY
    assert any("gusts" in factor for factor in result.limiting_factors)


def test_assess_hour_no_fly_on_precipitation() -> None:
    """Any expected precipitation is no-fly (not water-resistant)."""
    result = assess_hour(MINI_5_PRO, replace(_GOOD_HOUR, precipitation_mm=0.4))

    assert result.verdict is Verdict.NO_FLY
    assert any("precipitation" in factor for factor in result.limiting_factors)


@pytest.mark.parametrize(
    ("probability", "expected"),
    [
        (10.0, Verdict.GOOD),
        (20.0, Verdict.GOOD),  # at the marginal threshold, still good
        (35.0, Verdict.MARGINAL),
        (50.0, Verdict.NO_FLY),  # at the no-fly threshold
        (80.0, Verdict.NO_FLY),
    ],
)
def test_assess_hour_grades_precipitation_probability(
    probability: float, expected: Verdict
) -> None:
    """Precipitation chance grades good -> marginal -> no-fly, not binary."""
    hour = replace(_GOOD_HOUR, precipitation_probability_pct=probability)

    assert assess_hour(MINI_5_PRO, hour).verdict is expected


def test_assess_hour_no_fly_at_night() -> None:
    """Night-time hours are no-fly for daylight VLOS."""
    result = assess_hour(MINI_5_PRO, replace(_GOOD_HOUR, is_day=False))

    assert result.verdict is Verdict.NO_FLY
    assert any("night" in factor for factor in result.limiting_factors)


def test_assess_hour_marginal_when_cold() -> None:
    """Sub-5 C temperatures are marginal due to battery capacity loss."""
    result = assess_hour(MINI_5_PRO, replace(_GOOD_HOUR, temperature_c=2.0))

    assert result.verdict is Verdict.MARGINAL
    assert any("battery" in factor for factor in result.limiting_factors)


def test_assess_hour_marginal_when_feels_like_cold() -> None:
    """A cold apparent temperature triggers the caution even if dry-bulb is mild."""
    chilly = replace(_GOOD_HOUR, temperature_c=8.0, apparent_temperature_c=2.0)
    result = assess_hour(MINI_5_PRO, chilly)

    assert result.verdict is Verdict.MARGINAL
    assert any("feels like" in factor for factor in result.limiting_factors)


def test_assess_hour_marginal_when_feels_like_exactly_zero() -> None:
    """An apparent temperature of exactly 0.0 C still triggers the cold caution.

    Regression: a falsy-zero bug previously discarded a 0.0 C feels-like via
    ``apparent or temperature`` and reported GOOD on a freezing hour.
    """
    freezing = replace(_GOOD_HOUR, temperature_c=8.0, apparent_temperature_c=0.0)
    result = assess_hour(MINI_5_PRO, freezing)

    assert result.verdict is Verdict.MARGINAL
    assert any("feels like" in factor for factor in result.limiting_factors)


def test_assess_hour_marginal_on_icing_risk() -> None:
    """A freezing level within the flight ceiling flags icing risk."""
    icy = replace(_GOOD_HOUR, freezing_level_agl_m=200.0)
    result = assess_hour(MINI_5_PRO, icy)

    assert result.verdict is Verdict.MARGINAL
    assert any("icing" in factor for factor in result.limiting_factors)


def test_assess_hour_no_icing_when_freezing_level_high() -> None:
    """A high freezing level does not trigger the icing gate."""
    result = assess_hour(MINI_5_PRO, replace(_GOOD_HOUR, freezing_level_agl_m=2500.0))

    assert result.verdict is Verdict.GOOD


def test_assess_hour_fpv_tightens_gust_margin() -> None:
    """An FPV airframe goes no-fly at a gust its raw rating would only call marginal."""
    # ~9.5 m/s: below the Avata 2's 10.7 m/s rating, above its FPV-adjusted 9.1 m/s.
    windy = replace(_GOOD_HOUR, wind_gust_10m_kmh=34.2, wind_max_0_500m_kmh=34.2)

    fpv = assess_hour(AVATA_2, windy)
    non_fpv = assess_hour(replace(AVATA_2, is_fpv=False), windy)

    assert fpv.verdict is Verdict.NO_FLY
    assert any("FPV" in factor for factor in fpv.limiting_factors)
    assert non_fpv.verdict is Verdict.MARGINAL


def test_assess_hour_visibility_is_not_relaxed_by_onboard_sensing() -> None:
    """LiDAR and obstacle sensing cannot substitute for the pilot's visibility."""
    hazy = replace(_GOOD_HOUR, visibility_m=4000.0)

    neo = assess_hour(NEO, hazy)
    mini = assess_hour(MINI_5_PRO, hazy)

    assert neo.verdict is Verdict.MARGINAL
    assert mini.verdict is Verdict.MARGINAL
    assert any("visibility" in factor for factor in mini.limiting_factors)


def test_assess_hour_marginal_on_low_cloud() -> None:
    """Near-overcast low cloud flags a possible low ceiling to check."""
    cloudy = replace(_GOOD_HOUR, cloud_cover_low_pct=95.0)
    result = assess_hour(MINI_5_PRO, cloudy)

    assert result.verdict is Verdict.MARGINAL
    assert any("low cloud" in factor for factor in result.limiting_factors)


def test_assess_hour_marginal_on_high_kp() -> None:
    """A geomagnetic storm makes otherwise-good conditions marginal."""
    result = assess_hour(MINI_5_PRO, _GOOD_HOUR, kp_index=6.0)

    assert result.verdict is Verdict.MARGINAL
    assert any("geomagnetic" in factor for factor in result.limiting_factors)


def test_assess_hour_unknown_when_wind_unavailable() -> None:
    """Missing required wind data prevents a positive recommendation."""
    no_wind = replace(_GOOD_HOUR, wind_gust_10m_kmh=None, wind_max_0_500m_kmh=None)
    result = assess_hour(MINI_5_PRO, no_wind)

    assert result.verdict is Verdict.UNKNOWN
    assert result.governing_wind_ms is None


@pytest.mark.parametrize(
    "changes",
    [
        {"temperature_c": None},
        {"apparent_temperature_c": None},
        {"precipitation_mm": None},
        {"precipitation_probability_pct": None},
        {"visibility_m": None},
        {"cape": None},
        {"freezing_level_agl_m": None},
        {"is_day": None},
        {"cloud_cover_low_pct": None},
    ],
)
def test_assess_hour_unknown_for_each_missing_core_metric(
    changes: dict[str, float | bool | None],
) -> None:
    """Every required core sample fails closed to the explicit unknown state."""
    result = assess_hour(MINI_5_PRO, replace(_GOOD_HOUR, **changes))

    assert result.verdict is Verdict.UNKNOWN
    assert result.limiting_factors


def test_assess_hour_known_no_fly_overrides_unknown() -> None:
    """A measured hazard remains no-fly even when another required value is absent."""
    hour = replace(_GOOD_HOUR, precipitation_mm=1.0, visibility_m=None)

    assert assess_hour(MINI_5_PRO, hour).verdict is Verdict.NO_FLY


def test_assess_hour_does_not_create_good_kp_reading_when_unavailable() -> None:
    """Absent supplemental Kp is omitted rather than encoded as a quiet gate."""
    result = assess_hour(MINI_5_PRO, _GOOD_HOUR)

    assert all(reading.metric != "kp" for reading in result.readings)


def test_assess_hour_unknown_when_supporting_wind_sample_is_missing() -> None:
    """A partial aloft wind profile cannot yield GOOD from the values that remain."""
    hour = replace(_GOOD_HOUR, unavailable_metrics=("wind_speed_120m",))

    result = assess_hour(MINI_5_PRO, hour)

    assert result.verdict is Verdict.UNKNOWN
    assert "wind_speed_120m" in " ".join(result.limiting_factors)


def test_assess_hour_exposes_structured_readings() -> None:
    """Each hour carries structured gate readings with precomputed ratio and band."""
    gusty = replace(_GOOD_HOUR, wind_gust_10m_kmh=60.0, wind_max_0_500m_kmh=60.0)  # ~16.7 m/s
    result = assess_hour(MINI_5_PRO, gusty)

    wind = next(reading for reading in result.readings if reading.metric == "wind_gust")
    assert wind.band is Verdict.NO_FLY
    assert wind.value is not None
    assert wind.threshold == 12.0
    assert wind.ratio is not None  # precomputed value / threshold
    assert wind.ratio > 1.0
    assert wind.limiting is True
    assert "1.4x" in wind.reason  # absolute + relative + reference framing

    # A passing gate is present but not limiting, and a boolean/empty gate has no ratio.
    temperature = next(reading for reading in result.readings if reading.metric == "temperature")
    assert temperature.band is Verdict.GOOD
    assert temperature.limiting is False


def test_best_window_finds_longest_good_run() -> None:
    """The best window is the longest contiguous run of good hours."""
    hours = (
        HourAssessment(aware("2026-06-16T09:00"), Verdict.NO_FLY, ("rain",), 5.0),
        HourAssessment(aware("2026-06-16T10:00"), Verdict.GOOD, (), 5.0),
        HourAssessment(aware("2026-06-16T11:00"), Verdict.GOOD, (), 5.0),
        HourAssessment(aware("2026-06-16T12:00"), Verdict.MARGINAL, ("gusts",), 9.0),
        HourAssessment(aware("2026-06-16T13:00"), Verdict.GOOD, (), 5.0),
    )

    window = best_window(hours)

    assert window is not None
    assert window.start_time == aware("2026-06-16T10:00")
    assert window.end_time == aware("2026-06-16T11:00")
    assert window.hours == 2


def test_best_window_none_when_never_good() -> None:
    """No good hour yields no window."""
    hours = (HourAssessment(aware("2026-06-16T09:00"), Verdict.NO_FLY, ("rain",), 5.0),)

    assert best_window(hours) is None


def test_best_window_excludes_unknown_hours() -> None:
    """Incomplete hours cannot join or extend a good flying window."""
    hours = (
        HourAssessment(aware("2026-06-16T09:00"), Verdict.GOOD, (), 5.0),
        HourAssessment(
            aware("2026-06-16T10:00"), Verdict.UNKNOWN, ("visibility unavailable",), 5.0
        ),
        HourAssessment(aware("2026-06-16T11:00"), Verdict.GOOD, (), 5.0),
    )

    window = best_window(hours)

    assert window is not None
    assert window.hours == 1
    assert window.start_time == aware("2026-06-16T09:00")


def test_assess_forecast_builds_full_assessment() -> None:
    """A forecast is assessed hour-by-hour with a best window and labels."""
    forecast = DroneForecast(
        elevation_m=120.0,
        hours=(
            replace(_GOOD_HOUR, time=aware("2026-06-16T10:00")),
            replace(_GOOD_HOUR, time=aware("2026-06-16T11:00"), precipitation_mm=1.0),
        ),
        time_context=LONDON_SUMMER_CONTEXT,
    )

    assessment = assess_forecast(MINI_5_PRO, forecast, "Congleton, England")

    assert assessment.drone_name == "DJI Mini 5 Pro"
    assert assessment.place_label == "Congleton, England"
    assert assessment.hours[0].verdict is Verdict.GOOD
    assert assessment.hours[1].verdict is Verdict.NO_FLY
    assert assessment.best_window is not None
    assert assessment.best_window.start_time == aware("2026-06-16T10:00")


def test_assess_forecast_applies_per_hour_kp() -> None:
    """A per-hour Kp map flags only the storm-affected hour, not the whole window."""
    forecast = DroneForecast(
        elevation_m=120.0,
        hours=(
            replace(_GOOD_HOUR, time=aware("2026-06-16T10:00")),
            replace(_GOOD_HOUR, time=aware("2026-06-16T11:00")),
        ),
        time_context=LONDON_SUMMER_CONTEXT,
    )
    kp_by_time = {aware("2026-06-16T11:00"): 6.0}

    assessment = assess_forecast(MINI_5_PRO, forecast, "Congleton", kp_by_time=kp_by_time)

    assert assessment.hours[0].verdict is Verdict.GOOD
    assert assessment.hours[1].verdict is Verdict.MARGINAL
    assert any("geomagnetic" in factor for factor in assessment.hours[1].limiting_factors)


def test_assess_forecast_builds_daily_outlook() -> None:
    """The assessment carries a per-day outlook over the window."""
    forecast = DroneForecast(
        elevation_m=120.0,
        hours=(
            replace(_GOOD_HOUR, time=aware("2026-06-16T10:00")),
            replace(_GOOD_HOUR, time=aware("2026-06-17T10:00")),
        ),
        time_context=LONDON_SUMMER_CONTEXT,
    )

    assessment = assess_forecast(MINI_5_PRO, forecast, "Congleton")

    assert [day.date for day in assessment.daily] == [date(2026, 6, 16), date(2026, 6, 17)]


def test_daily_outlooks_groups_and_counts_good_hours() -> None:
    """Per-day outlooks group by date and count good hours with a best window."""
    hours = (
        HourAssessment(aware("2026-06-16T10:00"), Verdict.GOOD, (), 4.0),
        HourAssessment(aware("2026-06-16T11:00"), Verdict.NO_FLY, ("rain",), 4.0),
        HourAssessment(aware("2026-06-17T09:00"), Verdict.GOOD, (), 4.0),
    )

    outlooks = daily_outlooks(hours)

    assert [day.date for day in outlooks] == [date(2026, 6, 16), date(2026, 6, 17)]
    assert outlooks[0].good_hours == 1
    assert outlooks[0].best_window is not None
    assert outlooks[1].good_hours == 1


def test_assess_forecast_drops_elapsed_hours() -> None:
    """Hours before the current hour are excluded from the assessment."""
    forecast = DroneForecast(
        elevation_m=120.0,
        hours=(
            replace(_GOOD_HOUR, time=aware("2026-06-16T08:00")),
            replace(_GOOD_HOUR, time=aware("2026-06-16T09:00")),
            replace(_GOOD_HOUR, time=aware("2026-06-16T10:00")),
        ),
        time_context=LONDON_SUMMER_CONTEXT,
    )
    now = aware("2026-06-16T09:30")

    assessment = assess_forecast(MINI_5_PRO, forecast, "Congleton", now=now)

    # 09:00 (current hour) is kept; 08:00 is dropped.
    times = [hour.time for hour in assessment.hours]
    assert times == [aware("2026-06-16T09:00"), aware("2026-06-16T10:00")]


def test_assess_forecast_rejects_naive_now() -> None:
    """A naive cutoff cannot be compared to provider instants ambiguously."""
    forecast = DroneForecast(
        elevation_m=120.0,
        hours=(_GOOD_HOUR,),
        time_context=LONDON_SUMMER_CONTEXT,
    )
    now = datetime(2026, 6, 16, 9, 30)  # noqa: DTZ001

    with pytest.raises(ValueError, match="timezone-aware"):
        _ = assess_forecast(MINI_5_PRO, forecast, "Congleton", now=now)


def test_assess_forecast_all_past_yields_no_window() -> None:
    """When every hour has elapsed, there is no flight window."""
    forecast = DroneForecast(
        elevation_m=120.0,
        hours=(replace(_GOOD_HOUR, time=aware("2026-06-16T06:00")),),
        time_context=LONDON_SUMMER_CONTEXT,
    )
    now = aware("2026-06-16T20:00")

    assessment = assess_forecast(MINI_5_PRO, forecast, "Congleton", now=now)

    assert assessment.hours == ()
    assert assessment.best_window is None


def test_best_window_breaks_across_provider_gap() -> None:
    """Adjacent tuple rows two hours apart are not one continuous window."""
    hours = (
        HourAssessment(aware("2026-06-16T10:00"), Verdict.GOOD, (), 4.0),
        HourAssessment(aware("2026-06-16T12:00"), Verdict.GOOD, (), 4.0),
    )

    window = best_window(hours)

    assert window is not None
    assert window.hours == 1


def test_best_window_uses_instants_across_fall_back() -> None:
    """Both repeated UK 01:00 hours remain contiguous as distinct instants."""
    first = datetime(2026, 10, 25, 0, tzinfo=UTC).astimezone(_GOOD_HOUR.time.tzinfo)
    second = datetime(2026, 10, 25, 1, tzinfo=UTC).astimezone(_GOOD_HOUR.time.tzinfo)
    hours = (
        HourAssessment(first, Verdict.GOOD, (), 4.0),
        HourAssessment(second, Verdict.GOOD, (), 4.0),
    )

    window = best_window(hours)

    assert (first.strftime("%H:%M %Z"), second.strftime("%H:%M %Z")) == (
        "01:00 BST",
        "01:00 GMT",
    )
    assert window is not None
    assert window.hours == 2
