"""Pure formatting of drone flyability assessments into readable text.

Combines the numeric per-hour verdicts, the best flying window, UK CAA guidance,
and retrieved qualitative tips into one operator-facing summary. No I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weather_agent.models import SiteBriefing, Verdict
from weather_agent.reporting import describe_airspace, describe_metar, format_clock

if TYPE_CHECKING:
    from weather_agent.drone import DroneProfile
    from weather_agent.knowledge import KnowledgeSection
    from weather_agent.models import (
        CaaGuidance,
        DayAlmanac,
        DayOutlook,
        DroneAssessment,
        FleetMember,
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


def _render_briefing(place_label: str, briefing: SiteBriefing) -> list[str]:
    lines = list(_render_daylight(briefing.sun_times))
    if briefing.metar is not None:
        lines.append(describe_metar(place_label, briefing.metar))
    if briefing.airspace or briefing.airspace_note:
        lines.append(describe_airspace(place_label, briefing.airspace, briefing.airspace_note))
    return lines


def _render_hour(hour: HourAssessment) -> str:
    label = _VERDICT_LABELS[hour.verdict]
    if hour.limiting_factors:
        return f"  {hour.time}  {label} - {'; '.join(hour.limiting_factors)}"
    return f"  {hour.time}  {label}"


def _daily_rows(daily: tuple[DayOutlook, ...]) -> list[str]:
    rows: list[str] = []
    for day in daily:
        if day.best_window is not None:
            window = day.best_window
            rows.append(
                f"{day.date}: {day.good_hours} good h, "
                f"best {format_clock(window.start_time)}-{format_clock(window.end_time)}"
            )
        else:
            rows.append(f"{day.date}: no good-to-fly hours")
    return rows


def _render_daily_outlook(daily: tuple[DayOutlook, ...]) -> list[str]:
    if not daily:
        return []
    return ["Daily outlook:", *(f"  {row}" for row in _daily_rows(daily))]


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
    briefing: SiteBriefing | None = None,
    max_hours: int = _DEFAULT_MAX_HOURS,
) -> str:
    """Render a full drone flight assessment as operator-facing text.

    Args:
        assessment: The per-hour flyability assessment.
        guidance: UK CAA guidance for the drone.
        tips: Retrieved qualitative knowledge sections (may be empty).
        briefing: Optional environmental context (sun times, observed METAR, nearby
            airspace); omitted sections are simply not shown.
        max_hours: Maximum number of hours to list.

    Returns:
        A multi-section summary ending with the CAA disclaimer.
    """
    if briefing is None:
        briefing = SiteBriefing()
    lines = [
        f"Drone flight assessment - {assessment.drone_name} at {assessment.place_label}",
        "",
        _render_best_window(assessment.best_window),
        *_render_briefing(assessment.place_label, briefing),
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


def _window_summary(window: FlightWindow | None) -> str:
    if window is None:
        return "no good-to-fly hours"
    return f"{window.start_time} to {window.end_time} ({window.hours} h)"


def _render_fleet_comparison(members: tuple[FleetMember, ...]) -> list[str]:
    lines = ["Fleet comparison (wind limit - best window):"]
    lines.extend(
        f"  {member.profile.name}: {member.profile.caution_gust_ms:.1f} m/s - "
        f"{_window_summary(member.assessment.best_window)}"
        for member in members
    )
    return lines


def _render_fleet_member(member: FleetMember) -> list[str]:
    guidance = member.guidance
    lines = [f"{member.profile.name} ({guidance.uk_class_label} {guidance.subcategory}):"]
    lines.extend(f"  {row}" for row in _daily_rows(member.assessment.daily))
    if guidance.key_rules:
        # key_rules[0] is the class-specific people rule; [1:] are shared (rendered once).
        lines.append(f"  People: {guidance.key_rules[0]}")
    if guidance.class_caveat:
        lines.append(f"  Caveat: {guidance.class_caveat}")
    return lines


def _render_shared_caa(reference: CaaGuidance) -> list[str]:
    lines = ["UK CAA notes (all drones, open category):"]
    lines.extend(f"  - {rule}" for rule in reference.key_rules[1:])
    lines.append(f"  Height: {reference.height_limit_note}")
    return lines


def describe_fleet_assessment(
    members: tuple[FleetMember, ...],
    place_label: str,
    tips: tuple[KnowledgeSection, ...] = (),
    briefing: SiteBriefing | None = None,
) -> str:
    """Render a compact side-by-side flyability report for a fleet of drones.

    Shows the shared site context (daylight, METAR, airspace) and the universal
    UK CAA rules once, then a per-drone comparison and daily outlook, so a single
    request covers the whole fleet without repeating common context per drone.

    Args:
        members: Each drone paired with its assessment and CAA guidance; all share
            one site and forecast. An empty tuple yields a short "nothing to
            assess" line.
        place_label: Human-readable location the assessment is for.
        tips: Retrieved qualitative knowledge sections shared across drones.
        briefing: Optional environmental context; omitted sections are not shown.

    Returns:
        A multi-section fleet summary ending with the CAA disclaimer.
    """
    if not members:
        return f"No supported drones to assess at {place_label}."
    if briefing is None:
        briefing = SiteBriefing()
    reference = members[0].guidance
    lines = [f"Fleet flight assessment - {len(members)} drones at {place_label}"]
    briefing_lines = _render_briefing(place_label, briefing)
    if briefing_lines:
        lines.extend(("", *briefing_lines))
    lines.extend(("", *_render_fleet_comparison(members)))
    lines.extend(("", "Per-drone outlook:"))
    for member in members:
        lines.extend(("", *(f"  {row}" for row in _render_fleet_member(member))))
    lines.extend(("", *_render_shared_caa(reference)))
    if tips:
        lines.extend(("", *_render_tips(tips)))
    lines.extend(("", reference.disclaimer))
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
