"""Pure formatting of drone flyability assessments into readable text.

Combines the numeric per-hour verdicts, the best flying window, UK CAA guidance,
and retrieved qualitative tips into one operator-facing summary. No I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weather_agent.models import Verdict
from weather_agent.reporting import format_clock

if TYPE_CHECKING:
    from weather_agent.drone import DroneProfile
    from weather_agent.knowledge import KnowledgeSection
    from weather_agent.models import (
        CaaGuidance,
        DayAlmanac,
        DayOutlook,
        DroneAssessment,
        FlightWindow,
        HourAssessment,
    )

_DEFAULT_MAX_HOURS = 12
_VERDICT_LABELS = {
    Verdict.GOOD: "GOOD",
    Verdict.MARGINAL: "MARGINAL",
    Verdict.NO_FLY: "NO-FLY",
}


def _render_best_window(window: FlightWindow | None) -> str:
    if window is None:
        return "Best window: no good-to-fly hours in the forecast period."
    return f"Best window: {window.start_time} to {window.end_time} ({window.hours} h good to fly)."


def _render_daylight(sun_times: tuple[DayAlmanac, ...]) -> list[str]:
    if not sun_times:
        return []
    today = sun_times[0]
    return [
        f"Daylight: sunrise {format_clock(today.sunrise)}, "
        f"sunset {format_clock(today.sunset)} - keep within daylight for visual line of sight."
    ]


def _render_hour(hour: HourAssessment) -> str:
    label = _VERDICT_LABELS[hour.verdict]
    if hour.limiting_factors:
        return f"  {hour.time}  {label} - {'; '.join(hour.limiting_factors)}"
    return f"  {hour.time}  {label}"


def _render_daily_outlook(daily: tuple[DayOutlook, ...]) -> list[str]:
    if not daily:
        return []
    lines = ["Daily outlook:"]
    for day in daily:
        if day.best_window is not None:
            window = day.best_window
            lines.append(
                f"  {day.date}: {day.good_hours} good h, "
                f"best {format_clock(window.start_time)}-{format_clock(window.end_time)}"
            )
        else:
            lines.append(f"  {day.date}: no good-to-fly hours")
    return lines


def _render_hours(hours: tuple[HourAssessment, ...], max_hours: int) -> list[str]:
    lines = ["Hourly outlook:"]
    if not hours:
        lines.append("  No upcoming forecast hours in the assessment window.")
        return lines
    lines.extend(_render_hour(hour) for hour in hours[:max_hours])
    if len(hours) > max_hours:
        lines.append(f"  ... ({len(hours) - max_hours} more hours)")
    return lines


def _render_caa(guidance: CaaGuidance) -> list[str]:
    lines = [f"UK CAA notes ({guidance.uk_class_label}, subcategory {guidance.subcategory}):"]
    lines.extend(f"  - {rule}" for rule in guidance.key_rules)
    lines.append(f"  Height: {guidance.height_limit_note}")
    if guidance.class_caveat:
        lines.append(f"  Caveat: {guidance.class_caveat}")
    return lines


def _render_tips(tips: tuple[KnowledgeSection, ...]) -> list[str]:
    lines = ["Tips:"]
    lines.extend(f"  {tip.heading}: {tip.body}" for tip in tips)
    return lines


def describe_drone_assessment(
    assessment: DroneAssessment,
    guidance: CaaGuidance,
    tips: tuple[KnowledgeSection, ...],
    sun_times: tuple[DayAlmanac, ...] = (),
    max_hours: int = _DEFAULT_MAX_HOURS,
) -> str:
    """Render a full drone flight assessment as operator-facing text.

    Args:
        assessment: The per-hour flyability assessment.
        guidance: UK CAA guidance for the drone.
        tips: Retrieved qualitative knowledge sections (may be empty).
        sun_times: Optional daily sun times; when present, today's sunrise/sunset
            are shown as the daylight window for visual line of sight.
        max_hours: Maximum number of hours to list.

    Returns:
        A multi-section summary ending with the CAA disclaimer.
    """
    lines = [
        f"Drone flight assessment - {assessment.drone_name} at {assessment.place_label}",
        "",
        _render_best_window(assessment.best_window),
        *_render_daylight(sun_times),
        "",
        *_render_hours(assessment.hours, max_hours),
    ]
    if assessment.daily:
        lines.extend(("", *_render_daily_outlook(assessment.daily)))
    lines.extend(("", *_render_caa(guidance)))
    if tips:
        lines.extend(("", *_render_tips(tips)))
    lines.extend(("", guidance.disclaimer))
    return "\n".join(lines)


def describe_supported_drones(profiles: tuple[DroneProfile, ...]) -> str:
    """Render the list of supported drones and their key flight limits.

    Args:
        profiles: The drone profiles to list.

    Returns:
        A short readable list of drones with wind ratings and weights.
    """
    lines = [
        f"- {profile.name}: wind limit {profile.caution_gust_ms:.1f} m/s, {profile.weight_g:.0f} g"
        for profile in profiles
    ]
    return "Supported drones:\n" + "\n".join(lines)
