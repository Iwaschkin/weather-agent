"""Flatten a structured FleetAssessment into typed Reflex view models.

Reflex state vars must be serializable and typed. Recharts wants its data as a list
of dicts, while ``foreach`` (the verdict ribbon) wants a plainly-typed list - so a
:class:`DroneView` carries both: ``rows`` for the chart and ``verdicts`` for the
ribbon. This module is a pure shape-shifter; all weather logic stays in the core
package.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from weather_agent.models import DataConfidence

if TYPE_CHECKING:
    from weather_agent.models import DroneAssessment, FleetAssessment, FleetMember


@dataclass
class DroneView:
    """One drone's render-ready forecast for the dashboard."""

    name: str
    limit: float
    best_window: str
    summary: str
    rows: list[dict[str, Any]]
    verdicts: list[str]
    incomplete_hours: int
    low_confidence_hours: int


def _round(value: float | None) -> float | None:
    return round(value, 1) if isinstance(value, (int, float)) else None


def _hour_label(iso_time: str) -> str:
    try:
        return datetime.fromisoformat(iso_time).strftime("%a %H:%M")
    except ValueError:
        return iso_time


def _rows(assessment: DroneAssessment) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
    counts = {"good": 0, "marginal": 0, "no_fly": 0}
    for hour in assessment.hours:
        counts[hour.verdict.value] = counts.get(hour.verdict.value, 0) + 1
    return counts


def _best_window(assessment: DroneAssessment) -> str:
    window = assessment.best_window
    if window is None:
        return "No good-to-fly window"
    start = _hour_label(window.start_time)
    end = _hour_label(window.end_time)
    return f"Best: {start} – {end} ({window.hours} h)"


def _summary(assessment: DroneAssessment) -> str:
    counts = _counts(assessment)
    return f"{counts['good']} good · {counts['marginal']} marginal · {counts['no_fly']} no-fly hours"


def drone_view(member: FleetMember) -> DroneView:
    """Build the typed view model for one drone."""
    assessment = member.assessment
    return DroneView(
        name=member.profile.name,
        limit=_wind_limit(member),
        best_window=_best_window(assessment),
        summary=_summary(assessment),
        rows=_rows(assessment),
        verdicts=[hour.verdict.value for hour in assessment.hours],
        incomplete_hours=sum(
            1 for hour in assessment.hours if hour.data_confidence is DataConfidence.INSUFFICIENT
        ),
        low_confidence_hours=sum(
            1 for hour in assessment.hours if hour.data_confidence is DataConfidence.DEGRADED
        ),
    )


def fleet_views(assessment: FleetAssessment) -> list[DroneView]:
    """Build the per-drone view models for a whole fleet assessment."""
    return [drone_view(member) for member in assessment.members]
