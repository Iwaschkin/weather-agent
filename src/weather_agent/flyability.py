"""Pure flyability rules engine turning forecast hours into drone verdicts.

Each weather factor is a small "gate" returning a verdict and a short reason.
The worst gate decides the hour's overall verdict, and its reasons become the
limiting factors. All functions are pure and unit-testable without network
access. Thresholds are deliberately conservative and named for tuning.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from weather_agent.models import DayOutlook, DroneAssessment, FlightWindow, HourAssessment, Verdict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from weather_agent.models import DroneFlightHour, DroneForecast, DroneProfile

_KMH_PER_MS = 3.6
# Precipitation chance: a moderate chance is flyable-with-caution, a high chance
# is a no-fly (the drones are not water-resistant). Any *measured* precipitation
# is always a no-fly regardless of probability.
_PRECIP_PROBABILITY_MARGINAL_PCT = 20.0
_PRECIP_PROBABILITY_NO_FLY_PCT = 50.0
_VISIBILITY_MARGINAL_M = 5000.0
# Low-cloud cover is only a proxy for a low cloud base (open-meteo gives no base
# height); near-overcast low cloud flags a possible low ceiling to check.
_LOW_CLOUD_MARGINAL_PCT = 90.0
_CAPE_MARGINAL = 1000.0
_COLD_CAUTION_C = 5.0
_ICING_CEILING_M = 500.0
_KP_CAUTION = 5.0

_SEVERITY = {Verdict.GOOD: 0, Verdict.MARGINAL: 1, Verdict.NO_FLY: 2}

# A gate result: a verdict plus a reason (empty string when the gate is GOOD).
_Gate = tuple[Verdict, str]


def _parse_hour_or_none(time_str: str) -> datetime | None:
    """Parse an open-meteo naive-local hour timestamp, or None if unparseable.

    A total conversion: open-meteo returns ISO ``YYYY-MM-DDTHH:MM`` local
    timestamps, but an unexpected value must not crash the assessment, so it
    maps to ``None`` and the caller keeps the hour rather than dropping data.
    """
    try:
        return datetime.fromisoformat(time_str)
    except ValueError:
        return None


def _future_hours(
    hours: tuple[DroneFlightHour, ...],
    now: datetime | None,
) -> tuple[DroneFlightHour, ...]:
    """Drop hours that have already elapsed relative to ``now``.

    Args:
        hours: Forecast hours in chronological order.
        now: Current naive local time; when ``None`` no filtering happens.

    Returns:
        Only hours at or after the start of the current hour. Hours whose
        timestamp cannot be parsed are kept (fail-open, never hide data).
    """
    if now is None:
        return hours
    cutoff = now.replace(minute=0, second=0, microsecond=0)
    return tuple(
        hour
        for hour in hours
        if (parsed := _parse_hour_or_none(hour.time)) is None or parsed >= cutoff
    )


def _governing_wind_ms(hour: DroneFlightHour) -> float | None:
    # wind_max_0_500m already folds in the surface gust (the parser includes it),
    # so it is the single worst-case wind; fall back to the gust only if the
    # derived value is missing.
    worst_kmh = hour.wind_max_0_500m_kmh
    if worst_kmh is None:
        worst_kmh = hour.wind_gust_10m_kmh
    return worst_kmh / _KMH_PER_MS if worst_kmh is not None else None


def _wind_gate(profile: DroneProfile, governing_ms: float | None) -> _Gate:
    if governing_ms is None:
        return (Verdict.MARGINAL, "wind data unavailable")
    if governing_ms > profile.caution_gust_ms:
        return (
            Verdict.NO_FLY,
            f"gusts ~{governing_ms:.0f} m/s exceed the {profile.caution_gust_ms:.0f} m/s limit",
        )
    if governing_ms > profile.ideal_gust_ms:
        return (Verdict.MARGINAL, f"gusts ~{governing_ms:.0f} m/s near the wind limit")
    return (Verdict.GOOD, "")


def _precipitation_gate(hour: DroneFlightHour) -> _Gate:
    if hour.precipitation_mm is not None and hour.precipitation_mm > 0:
        return (Verdict.NO_FLY, "precipitation expected (drone is not water-resistant)")
    probability = hour.precipitation_probability_pct
    if probability is None:
        return (Verdict.GOOD, "")
    if probability >= _PRECIP_PROBABILITY_NO_FLY_PCT:
        return (Verdict.NO_FLY, f"{probability:.0f}% chance of precipitation")
    if probability > _PRECIP_PROBABILITY_MARGINAL_PCT:
        return (Verdict.MARGINAL, f"{probability:.0f}% chance of precipitation")
    return (Verdict.GOOD, "")


def _temperature_gate(profile: DroneProfile, hour: DroneFlightHour) -> _Gate:
    temperature = hour.temperature_c
    if temperature is None:
        return (Verdict.GOOD, "")
    if temperature < profile.min_temp_c or temperature > profile.max_temp_c:
        return (Verdict.NO_FLY, f"temperature {temperature:.0f} C outside operating range")
    # Feels-like cold drains batteries faster than the dry-bulb figure suggests.
    # Guard on None explicitly: an apparent temperature of exactly 0.0 C is a real,
    # freezing value, and `or` would wrongly discard it as falsy.
    apparent = hour.apparent_temperature_c
    feels_like = min(temperature, apparent if apparent is not None else temperature)
    if feels_like < _COLD_CAUTION_C:
        return (Verdict.MARGINAL, f"cold (feels like {feels_like:.0f} C) reduces battery capacity")
    return (Verdict.GOOD, "")


def _icing_gate(hour: DroneFlightHour) -> _Gate:
    freezing_level = hour.freezing_level_agl_m
    if freezing_level is not None and freezing_level <= _ICING_CEILING_M:
        return (
            Verdict.MARGINAL,
            f"icing risk (freezing level ~{freezing_level:.0f} m AGL, within flight ceiling)",
        )
    return (Verdict.GOOD, "")


def _daylight_visibility_gate(hour: DroneFlightHour) -> _Gate:
    if hour.is_day is False:
        return (Verdict.NO_FLY, "night-time (outside daylight visual line of sight)")
    visibility = hour.visibility_m
    if visibility is not None and visibility < _VISIBILITY_MARGINAL_M:
        return (Verdict.MARGINAL, f"reduced visibility ({visibility / 1000:.0f} km)")
    return (Verdict.GOOD, "")


def _storm_gate(hour: DroneFlightHour) -> _Gate:
    if hour.cape is not None and hour.cape >= _CAPE_MARGINAL:
        return (Verdict.MARGINAL, f"thunderstorm potential (CAPE {hour.cape:.0f})")
    return (Verdict.GOOD, "")


def _cloud_gate(hour: DroneFlightHour) -> _Gate:
    low_cloud = hour.cloud_cover_low_pct
    if low_cloud is not None and low_cloud >= _LOW_CLOUD_MARGINAL_PCT:
        return (
            Verdict.MARGINAL,
            f"near-overcast low cloud ({low_cloud:.0f}%); check the cloud base stays clear",
        )
    return (Verdict.GOOD, "")


def _geomagnetic_gate(kp_index: float | None) -> _Gate:
    if kp_index is not None and kp_index >= _KP_CAUTION:
        return (Verdict.MARGINAL, f"geomagnetic storm (Kp {kp_index:.0f}; GPS/compass risk)")
    return (Verdict.GOOD, "")


def _worst_verdict(severity: int) -> Verdict:
    if severity >= _SEVERITY[Verdict.NO_FLY]:
        return Verdict.NO_FLY
    if severity >= _SEVERITY[Verdict.MARGINAL]:
        return Verdict.MARGINAL
    return Verdict.GOOD


def assess_hour(
    profile: DroneProfile,
    hour: DroneFlightHour,
    kp_index: float | None = None,
) -> HourAssessment:
    """Assess a single forecast hour for one drone.

    Args:
        profile: The drone's flight limits.
        hour: The forecast metrics for the hour.
        kp_index: The planetary Kp index for the period, or ``None`` when unknown.

    Returns:
        The hour's verdict and the limiting factors that produced it.
    """
    governing = _governing_wind_ms(hour)
    gates = (
        _wind_gate(profile, governing),
        _precipitation_gate(hour),
        _temperature_gate(profile, hour),
        _icing_gate(hour),
        _daylight_visibility_gate(hour),
        _storm_gate(hour),
        _cloud_gate(hour),
        _geomagnetic_gate(kp_index),
    )
    worst = max(_SEVERITY[verdict] for verdict, _ in gates)
    factors = tuple(reason for verdict, reason in gates if _SEVERITY[verdict] == worst and reason)
    return HourAssessment(
        time=hour.time,
        verdict=_worst_verdict(worst),
        limiting_factors=factors,
        governing_wind_ms=governing,
    )


def best_window(hours: tuple[HourAssessment, ...]) -> FlightWindow | None:
    """Find the longest contiguous run of good-to-fly hours.

    Args:
        hours: Per-hour assessments in chronological order.

    Returns:
        The longest good window, or ``None`` when no hour is good. Ties keep the
        earliest window.
    """
    best: FlightWindow | None = None
    run_start: int | None = None
    for index, assessment in enumerate(hours):
        if assessment.verdict is not Verdict.GOOD:
            run_start = None
            continue
        if run_start is None:
            run_start = index
        length = index - run_start + 1
        if best is None or length > best.hours:
            best = FlightWindow(hours[run_start].time, assessment.time, length)
    return best


def daily_outlooks(hours: tuple[HourAssessment, ...]) -> tuple[DayOutlook, ...]:
    """Summarise per-hour assessments into one outlook per calendar day.

    Args:
        hours: Per-hour assessments in chronological order.

    Returns:
        One :class:`DayOutlook` per day present, in chronological order, each with
        that day's good-hour count and best contiguous good window.
    """
    by_date: dict[str, list[HourAssessment]] = {}
    for hour in hours:
        by_date.setdefault(hour.time[:10], []).append(hour)
    return tuple(
        DayOutlook(
            date=date,
            good_hours=sum(1 for hour in day_hours if hour.verdict is Verdict.GOOD),
            best_window=best_window(tuple(day_hours)),
        )
        for date, day_hours in by_date.items()
    )


def assess_forecast(
    profile: DroneProfile,
    forecast: DroneForecast,
    place_label: str,
    kp_by_time: Mapping[str, float] | None = None,
    now: datetime | None = None,
) -> DroneAssessment:
    """Assess every hour of a drone forecast and find the best window.

    Args:
        profile: The drone's flight limits.
        forecast: The parsed drone forecast.
        place_label: Human-readable location for the assessment.
        kp_by_time: Per-hour planetary Kp keyed by the hour's timestamp (so a Kp
            forecast varies across the window), or ``None`` when unknown.
        now: Current naive local time used to drop already-elapsed hours; when
            ``None`` every forecast hour is assessed.

    Returns:
        The full per-hour assessment over the remaining hours, with the best
        contiguous good window and a per-day outlook.
    """
    upcoming = _future_hours(forecast.hours, now)
    hours = tuple(
        assess_hour(profile, hour, kp_by_time.get(hour.time) if kp_by_time else None)
        for hour in upcoming
    )
    return DroneAssessment(
        drone_name=profile.name,
        place_label=place_label,
        hours=hours,
        best_window=best_window(hours),
        daily=daily_outlooks(hours),
    )
