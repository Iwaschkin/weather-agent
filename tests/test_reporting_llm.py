"""Tests for the grounded LLM drone-report module (deterministic parts).

The pure facts-rendering, response parsing, and audit wrapping run always. The live
Ollama generation in ``generate_drone_report`` is exercised only when a server is
available and is not covered here (it is non-deterministic network I/O).
"""

import pytest

from weather_agent.caa import caa_guidance
from weather_agent.drone import MINI_5_PRO
from weather_agent.evaluation import SAFETY_BANNER
from weather_agent.models import (
    DroneAssessment,
    FleetMember,
    FlightWindow,
    HourAssessment,
    Verdict,
)
from weather_agent.reporting_llm import (
    ReportError,
    _content,
    apply_audit,
    facts_for_assessment,
)


def _member(
    verdict: Verdict,
    factors: tuple[str, ...],
    best: FlightWindow | None,
) -> FleetMember:
    hour = HourAssessment("2026-06-16T11:00", verdict, factors, None)
    assessment = DroneAssessment(MINI_5_PRO.name, "Congleton, England", (hour,), best)
    return FleetMember(profile=MINI_5_PRO, assessment=assessment, guidance=caa_guidance(MINI_5_PRO))


def test_facts_for_assessment_includes_limits_and_window() -> None:
    """The facts block names the drone, its limits, and the best window."""
    member = _member(Verdict.GOOD, (), FlightWindow("2026-06-16T06:00", "2026-06-16T11:00", 5))

    facts = facts_for_assessment(member)

    assert "DJI Mini 5 Pro" in facts
    assert "12.0 m/s" in facts
    assert "Best flying window: 2026-06-16T06:00 to 2026-06-16T11:00 (5 h)" in facts


def test_facts_for_assessment_reports_no_window_and_factors() -> None:
    """With no good window the facts say so and list the limiting factors."""
    member = _member(Verdict.NO_FLY, ("gusts over the limit",), None)

    facts = facts_for_assessment(member)

    assert "Best flying window: none" in facts
    assert "gusts over the limit" in facts


def test_apply_audit_prepends_banner_when_understated() -> None:
    """Prose that downgrades a no-fly verdict is prefixed with the safety banner."""
    member = _member(Verdict.NO_FLY, ("gusts over the limit",), None)

    out = apply_audit(member, "Great day, good to fly all day!")

    assert out.startswith(SAFETY_BANNER)


def test_apply_audit_passes_faithful_prose() -> None:
    """Faithful prose is returned unchanged."""
    member = _member(Verdict.NO_FLY, ("gusts over the limit",), None)
    prose = "NO-FLY: gusts are over the limit today."

    assert apply_audit(member, prose) == prose


@pytest.mark.parametrize(
    "payload", ["not-a-dict", {}, {"message": {}}, {"message": {"content": 5}}]
)
def test_content_rejects_malformed(payload: object) -> None:
    """Missing or non-string message content raises a report error."""
    with pytest.raises(ReportError):
        _ = _content(payload)


def test_content_extracts_and_trims_text() -> None:
    """A well-formed chat response yields the trimmed message text."""
    assert _content({"message": {"content": "  hello  "}}) == "hello"
