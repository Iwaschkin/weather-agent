"""Pure flyability rules engine turning forecast hours into drone verdicts.

Each weather factor is a small "gate" returning a structured
:class:`~weather_agent.models.GateReading` (raw value, threshold, precomputed
ratio, band, and a human reason). The worst gate decides the hour's overall
verdict, and the limiting gates' reasons become the limiting factors. All
functions are pure and unit-testable without network access. Thresholds are
deliberately conservative and named for tuning.

Missing-data policy: the safety-critical gates (wind, temperature, precipitation,
visibility, daylight) treat absent inputs as ``MARGINAL`` with a "data
unavailable" reason, never ``GOOD`` - incomplete data must not read as a
clear-to-fly window. The secondary caution gates (icing, storm, low cloud,
geomagnetic) fail open, because their inputs are frequently absent and are
proxies rather than hard limits, so degrading them would make almost every hour
marginal without adding safety.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

from weather_agent.models import (
    DataConfidence,
    DayOutlook,
    DroneAssessment,
    FlightWindow,
    GateReading,
    HourAssessment,
    Verdict,
)
from weather_agent.policy import DEFAULT_NIGHT_POLICY

if TYPE_CHECKING:
    from collections.abc import Mapping

    from weather_agent.models import DroneFlightHour, DroneForecast, DroneProfile, TimeSeries
    from weather_agent.policy import NightPolicy

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
# FPV airframes are flown faster and are less forgiving in gusts than the raw wind
# rating implies, so both gust thresholds are tightened for them (safety-biased).
_FPV_GUST_FACTOR = 0.85
# Reduced visibility is riskier without omnidirectional obstacle sensing and safer
# for a low-light-capable airframe (e.g. LiDAR), so the marginal visibility
# threshold adapts to the drone's sensing stack.
_NO_OMNI_VISIBILITY_PENALTY_M = 3000.0
_LOW_LIGHT_VISIBILITY_BONUS_M = 2000.0

_SEVERITY = {Verdict.GOOD: 0, Verdict.MARGINAL: 1, Verdict.NO_FLY: 2}
# A spread needs at least two members to be meaningful.
_MIN_ENSEMBLE_MEMBERS = 2


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


def _effective_gust_limits(profile: DroneProfile) -> tuple[float, float]:
    """Return (ideal, caution) gust limits, tightened for FPV airframes."""
    factor = _FPV_GUST_FACTOR if profile.is_fpv else 1.0
    return profile.ideal_gust_ms * factor, profile.caution_gust_ms * factor


def _wind_gate(profile: DroneProfile, governing_ms: float | None) -> GateReading:
    ideal, caution = _effective_gust_limits(profile)
    if governing_ms is None:
        return GateReading(
            "wind_gust", Verdict.MARGINAL, "wind data unavailable", unit="m/s", data_missing=True
        )
    fpv = " (FPV: reduced gust margin)" if profile.is_fpv else ""
    if governing_ms > caution:
        band = Verdict.NO_FLY
        reason = (
            f"gusts ~{governing_ms:.0f} m/s, {governing_ms / caution:.1f}x "
            f"the {caution:.0f} m/s limit{fpv}"
        )
    elif governing_ms > ideal:
        band = Verdict.MARGINAL
        reason = (
            f"gusts ~{governing_ms:.0f} m/s, {governing_ms / caution * 100:.0f}% "
            f"of the {caution:.0f} m/s limit{fpv}"
        )
    else:
        band, reason = Verdict.GOOD, ""
    return GateReading("wind_gust", band, reason, value=governing_ms, unit="m/s", threshold=caution)


def _precipitation_gate(hour: DroneFlightHour) -> GateReading:
    if hour.precipitation_mm is not None and hour.precipitation_mm > 0:
        return GateReading(
            "precipitation",
            Verdict.NO_FLY,
            "precipitation expected (drone is not water-resistant)",
            value=hour.precipitation_mm,
            unit="mm",
        )
    probability = hour.precipitation_probability_pct
    threshold = _PRECIP_PROBABILITY_NO_FLY_PCT
    if probability is None:
        # A measured amount of 0 mm is a real "no precipitation" signal, so the
        # missing probability is benign; only fully absent precipitation data
        # (no amount either) degrades to marginal rather than reading as good.
        if hour.precipitation_mm is None:
            return GateReading(
                "precip_probability",
                Verdict.MARGINAL,
                "precipitation data unavailable",
                unit="%",
                threshold=threshold,
                data_missing=True,
            )
        return GateReading("precip_probability", Verdict.GOOD, unit="%", threshold=threshold)
    if probability >= _PRECIP_PROBABILITY_NO_FLY_PCT:
        band = Verdict.NO_FLY
    elif probability > _PRECIP_PROBABILITY_MARGINAL_PCT:
        band = Verdict.MARGINAL
    else:
        band = Verdict.GOOD
    reason = "" if band is Verdict.GOOD else f"{probability:.0f}% chance of precipitation"
    return GateReading(
        "precip_probability", band, reason, value=probability, unit="%", threshold=threshold
    )


def _temperature_gate(profile: DroneProfile, hour: DroneFlightHour) -> GateReading:
    temperature = hour.temperature_c
    if temperature is None:
        return GateReading(
            "temperature",
            Verdict.MARGINAL,
            "temperature data unavailable",
            unit="C",
            data_missing=True,
        )
    if temperature < profile.min_temp_c or temperature > profile.max_temp_c:
        bound = profile.min_temp_c if temperature < profile.min_temp_c else profile.max_temp_c
        reason = (
            f"temperature {temperature:.0f} C outside the "
            f"{profile.min_temp_c:.0f} to {profile.max_temp_c:.0f} C range"
        )
        return GateReading(
            "temperature", Verdict.NO_FLY, reason, value=temperature, unit="C", threshold=bound
        )
    # Feels-like cold drains batteries faster than the dry-bulb figure suggests.
    # Guard on None explicitly: an apparent temperature of exactly 0.0 C is a real,
    # freezing value, and `or` would wrongly discard it as falsy.
    apparent = hour.apparent_temperature_c
    feels_like = min(temperature, apparent if apparent is not None else temperature)
    if feels_like < _COLD_CAUTION_C:
        reason = f"cold (feels like {feels_like:.0f} C) reduces battery capacity"
        return GateReading(
            "feels_like",
            Verdict.MARGINAL,
            reason,
            value=feels_like,
            unit="C",
            threshold=_COLD_CAUTION_C,
        )
    return GateReading("temperature", Verdict.GOOD, value=temperature, unit="C")


def _icing_gate(hour: DroneFlightHour) -> GateReading:
    freezing_level = hour.freezing_level_agl_m
    if freezing_level is not None and freezing_level <= _ICING_CEILING_M:
        reason = (
            f"icing risk (freezing level ~{freezing_level:.0f} m AGL, "
            f"at or below the {_ICING_CEILING_M:.0f} m ceiling)"
        )
        return GateReading(
            "freezing_level_agl",
            Verdict.MARGINAL,
            reason,
            value=freezing_level,
            unit="m",
            threshold=_ICING_CEILING_M,
        )
    return GateReading(
        "freezing_level_agl",
        Verdict.GOOD,
        value=freezing_level,
        unit="m",
        threshold=_ICING_CEILING_M,
    )


def _visibility_threshold(profile: DroneProfile) -> float:
    """Visibility (m) below which the hour is marginal, adapted to the drone's sensing."""
    threshold = _VISIBILITY_MARGINAL_M
    if not profile.has_omni_sensing:
        threshold += _NO_OMNI_VISIBILITY_PENALTY_M
    if profile.low_light_capable:
        threshold -= _LOW_LIGHT_VISIBILITY_BONUS_M
    return threshold


def _daylight_visibility_gate(
    profile: DroneProfile, hour: DroneFlightHour, night_policy: NightPolicy
) -> GateReading:
    if hour.is_day is False:
        return GateReading("daylight", night_policy.verdict, night_policy.note)
    if hour.is_day is None:
        return GateReading(
            "daylight", Verdict.MARGINAL, "daylight data unavailable", data_missing=True
        )
    threshold = _visibility_threshold(profile)
    visibility = hour.visibility_m
    if visibility is None:
        return GateReading(
            "visibility",
            Verdict.MARGINAL,
            "visibility data unavailable",
            unit="m",
            threshold=threshold,
            data_missing=True,
        )
    if visibility < threshold:
        reason = (
            f"reduced visibility ({visibility / 1000:.0f} km, "
            f"below the {threshold / 1000:.0f} km threshold)"
        )
        return GateReading(
            "visibility", Verdict.MARGINAL, reason, value=visibility, unit="m", threshold=threshold
        )
    return GateReading("visibility", Verdict.GOOD, value=visibility, unit="m", threshold=threshold)


def _storm_gate(hour: DroneFlightHour) -> GateReading:
    cape = hour.cape
    if cape is not None and cape >= _CAPE_MARGINAL:
        reason = (
            f"thunderstorm potential (CAPE {cape:.0f} J/kg, "
            f"{cape / _CAPE_MARGINAL:.1f}x the {_CAPE_MARGINAL:.0f} threshold)"
        )
        return GateReading(
            "cape", Verdict.MARGINAL, reason, value=cape, unit="J/kg", threshold=_CAPE_MARGINAL
        )
    return GateReading("cape", Verdict.GOOD, value=cape, unit="J/kg", threshold=_CAPE_MARGINAL)


def _cloud_gate(hour: DroneFlightHour) -> GateReading:
    low_cloud = hour.cloud_cover_low_pct
    if low_cloud is not None and low_cloud >= _LOW_CLOUD_MARGINAL_PCT:
        reason = f"near-overcast low cloud ({low_cloud:.0f}%); check the cloud base stays clear"
        return GateReading(
            "low_cloud",
            Verdict.MARGINAL,
            reason,
            value=low_cloud,
            unit="%",
            threshold=_LOW_CLOUD_MARGINAL_PCT,
        )
    return GateReading(
        "low_cloud", Verdict.GOOD, value=low_cloud, unit="%", threshold=_LOW_CLOUD_MARGINAL_PCT
    )


def _geomagnetic_gate(kp_index: float | None) -> GateReading:
    if kp_index is not None and kp_index >= _KP_CAUTION:
        reason = f"geomagnetic storm (Kp {kp_index:.0f}; GPS/compass risk)"
        return GateReading("kp", Verdict.MARGINAL, reason, value=kp_index, threshold=_KP_CAUTION)
    return GateReading("kp", Verdict.GOOD, value=kp_index, threshold=_KP_CAUTION)


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
    night_policy: NightPolicy = DEFAULT_NIGHT_POLICY,
) -> HourAssessment:
    """Assess a single forecast hour for one drone.

    Args:
        profile: The drone's flight limits.
        hour: The forecast metrics for the hour.
        kp_index: The planetary Kp index for the period, or ``None`` when unknown.
        night_policy: The dated policy deciding how a night-time hour is treated;
            defaults to the current UK Open Category rules.

    Returns:
        The hour's verdict and the limiting factors that produced it.
    """
    governing = _governing_wind_ms(hour)
    gates = (
        _wind_gate(profile, governing),
        _precipitation_gate(hour),
        _temperature_gate(profile, hour),
        _icing_gate(hour),
        _daylight_visibility_gate(profile, hour, night_policy),
        _storm_gate(hour),
        _cloud_gate(hour),
        _geomagnetic_gate(kp_index),
    )
    worst = max(_SEVERITY[gate.band] for gate in gates)
    # A gate is "limiting" when it set (tied for) the worst non-good verdict.
    readings = tuple(
        replace(gate, limiting=gate.band is not Verdict.GOOD and _SEVERITY[gate.band] == worst)
        for gate in gates
    )
    factors = tuple(reading.reason for reading in readings if reading.limiting and reading.reason)
    # Confidence is a separate axis from the verdict: a safety-critical gate that
    # degraded for *missing* data (not an out-of-limit value) caps the hour.
    confidence = (
        DataConfidence.INSUFFICIENT
        if any(reading.data_missing for reading in readings)
        else DataConfidence.ADEQUATE
    )
    return HourAssessment(
        time=hour.time,
        verdict=_worst_verdict(worst),
        limiting_factors=factors,
        governing_wind_ms=governing,
        readings=readings,
        data_confidence=confidence,
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


def hourly_gust_spread(series: TimeSeries) -> dict[str, float]:
    """Per-timestamp gust spread (max - min across ensemble members), in m/s.

    A measure of forecast uncertainty: a wide spread of member gusts means the
    members disagree about the wind for that hour. Timestamps with fewer than two
    present member values are omitted (no spread to measure).

    Args:
        series: An ensemble time series whose columns are per-member gust values
            (in km/h, as open-meteo returns them).

    Returns:
        A mapping of timestamp to gust spread in m/s.
    """
    spreads: dict[str, float] = {}
    for index, timestamp in enumerate(series.timestamps):
        members = [
            value
            for column in series.series.values()
            if index < len(column) and (value := column[index]) is not None
        ]
        if len(members) >= _MIN_ENSEMBLE_MEMBERS:
            spreads[timestamp] = (max(members) - min(members)) / _KMH_PER_MS
    return spreads


def _wind_threshold(hour: HourAssessment) -> float | None:
    """Return the wind gate's gust threshold for an hour, or None if absent."""
    for reading in hour.readings:
        if reading.metric == "wind_gust":
            return reading.threshold
    return None


def _apply_spread(hour: HourAssessment, spread: float | None) -> HourAssessment:
    if spread is None or spread <= 0 or hour.data_confidence is not DataConfidence.ADEQUATE:
        return hour
    wind = hour.governing_wind_ms
    threshold = _wind_threshold(hour)
    if wind is None or threshold is None:
        return hour
    if abs(threshold - wind) <= spread:
        return replace(hour, data_confidence=DataConfidence.DEGRADED)
    return hour


def downgrade_for_uncertainty(
    assessment: DroneAssessment,
    spread_by_time: Mapping[str, float],
) -> DroneAssessment:
    """Lower confidence to ``DEGRADED`` where the gust limit is within ensemble spread.

    Turns a point forecast into a decision under uncertainty: when an otherwise
    data-adequate hour has its governing wind within one ensemble gust-spread of the
    drone's gust limit, the members plausibly cross the limit, so the hour's
    confidence drops to ``DEGRADED``. The verdict is unchanged, and hours already
    ``INSUFFICIENT`` (missing data) are left as-is. The surface-gust spread is used
    as a proxy for the uncertainty band around the governing 0-500 m wind.

    Args:
        assessment: The per-hour assessment to annotate.
        spread_by_time: Per-hour gust spread (m/s) keyed by the hour's timestamp.

    Returns:
        The assessment with confidence downgraded on the uncertain hours. The
        verdicts, best window, and daily outlook are unchanged.
    """
    hours = tuple(_apply_spread(hour, spread_by_time.get(hour.time)) for hour in assessment.hours)
    return replace(assessment, hours=hours)
