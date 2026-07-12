"""Flatten a structured FleetAssessment into typed Reflex view models.

Reflex state vars must be serializable and typed. Recharts wants its data as a list
of dicts, while ``foreach`` (the verdict ribbon) wants a plainly-typed list - so a
:class:`DroneView` carries both: ``rows`` for the chart and ``verdicts`` for the
ribbon. This module is a pure shape-shifter; all weather logic stays in the core
package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypedDict

from weather_agent.drone_report import describe_drone_assessment

if TYPE_CHECKING:
    from datetime import datetime

    from weather_agent.models import DroneAssessment, FleetAssessment, FleetMember, SiteBriefing


class ChartRow(TypedDict):
    """One typed Recharts row with explicit units defined by the component label."""

    time: str
    wind: float | None
    precip: float | None
    temp: float | None
    vis: float | None


@dataclass(frozen=True, slots=True)
class DroneView:
    """One drone's render-ready forecast for the dashboard."""

    name: str
    limit: float
    best_window: str
    best_window_available: bool
    best_window_color: Literal["grass", "gray"]
    summary: str
    timezone: str
    configuration: str
    caa_context: str
    source_statuses: list[str]
    airspace_status: str
    disclaimer: str
    authoritative_report: str
    rows: list[ChartRow]
    verdicts: list[str]


def _round(value: float | None) -> float | None:
    return round(value, 1) if isinstance(value, (int, float)) else None


def _hour_label(value: datetime) -> str:
    return value.strftime("%a %H:%M %Z")


def _rows(assessment: DroneAssessment) -> list[ChartRow]:
    rows: list[ChartRow] = []
    for hour in assessment.hours:
        values = {reading.metric: reading.value for reading in hour.readings}
        visibility_m = values.get("visibility")
        rows.append(
            {
                "time": _hour_label(hour.time),
                "wind": _round(hour.governing_wind_ms),
                "precip": _round(values.get("precip_probability")),
                "temp": _round(values.get("temperature")),
                "vis": _round(visibility_m / 1000 if visibility_m is not None else None),
            }
        )
    return rows


def _wind_limit(member: FleetMember) -> float:
    for hour in member.assessment.hours:
        for reading in hour.readings:
            if reading.metric == "wind_gust" and reading.threshold is not None:
                return round(reading.threshold, 1)
    return round(member.profile.caution_gust_ms, 1)


def _counts(assessment: DroneAssessment) -> dict[str, int]:
    counts = {"good": 0, "marginal": 0, "unknown": 0, "no_fly": 0}
    for hour in assessment.hours:
        counts[hour.verdict.value] = counts.get(hour.verdict.value, 0) + 1
    return counts


def _best_window(assessment: DroneAssessment) -> str:
    window = assessment.best_window
    if window is None:
        return "No good-to-fly window"
    start = _hour_label(window.start_time)
    end = _hour_label(window.end_time)
    return f"Best: {start} - {end} ({window.hours} h)"


def _summary(assessment: DroneAssessment) -> str:
    counts = _counts(assessment)
    return (
        f"{counts['good']} good · {counts['marginal']} marginal · "
        f"{counts['unknown']} unknown · {counts['no_fly']} no-fly hours"
    )


def _source_statuses(briefing: SiteBriefing | None) -> list[str]:
    if briefing is None:
        return []
    return [
        f"{status.source}: {status.state.value.replace('_', ' ')}"
        + (f" - {status.detail}" if status.detail else "")
        for status in briefing.source_statuses
    ]


def _airspace_status(briefing: SiteBriefing | None) -> str:
    if briefing is None:
        return "Airspace source unavailable; verify authoritative sources and NOTAMs."
    if briefing.airspace:
        return (
            f"{len(briefing.airspace)} nearby airspace record(s); verify authoritative "
            "sources and NOTAMs."
        )
    if briefing.airspace_note:
        return briefing.airspace_note
    return "No nearby OpenAIP records returned; verify authoritative sources and NOTAMs."


def _caa_context(member: FleetMember) -> str:
    guidance = member.guidance
    return (
        f"{guidance.jurisdiction}; {guidance.aircraft_class}; Open "
        f"{guidance.subcategory.value}; reviewed {guidance.reviewed_as_of.isoformat()}."
    )


def drone_view(member: FleetMember, briefing: SiteBriefing | None = None) -> DroneView:
    """Build the typed view model for one drone."""
    assessment = member.assessment
    return DroneView(
        name=member.profile.name,
        limit=_wind_limit(member),
        best_window=_best_window(assessment),
        best_window_available=assessment.best_window is not None,
        best_window_color="grass" if assessment.best_window is not None else "gray",
        summary=_summary(assessment),
        timezone=assessment.time_context.timezone,
        configuration=member.guidance.configuration,
        caa_context=_caa_context(member),
        source_statuses=_source_statuses(briefing),
        airspace_status=_airspace_status(briefing),
        disclaimer=member.guidance.disclaimer,
        authoritative_report=describe_drone_assessment(
            assessment,
            member.guidance,
            (),
            briefing=briefing,
        ),
        rows=_rows(assessment),
        verdicts=[hour.verdict.value for hour in assessment.hours],
    )


def fleet_views(assessment: FleetAssessment) -> list[DroneView]:
    """Build the per-drone view models for a whole fleet assessment."""
    return [drone_view(member, assessment.briefing) for member in assessment.members]
