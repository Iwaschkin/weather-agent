"""LLM-written drone flight reports, grounded in the deterministic assessment.

The narrative companion to :mod:`weather_agent.drone_report` (which renders fixed
templates): it asks a local chat model to write a short operator-facing report for
one drone, with the engine's own facts supplied as the only grounding. The result is
run through the deterministic faithfulness audit
(:func:`weather_agent.evaluation.audit_drone_report`) and prefixed with the safety
banner if it under-states a restrictive verdict - so the LLM may phrase the briefing
but never softens a NO-FLY.

This performs network I/O against an Ollama server, so it is a boundary module: it
is not imported by pure logic, and the host/model are injectable. The deterministic
report and the structured assessment stay the source of truth; this only narrates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import httpx

from weather_agent.evaluation import SAFETY_BANNER, audit_drone_report

if TYPE_CHECKING:
    from weather_agent.models import DroneAssessment, FleetMember, FlightWindow

_DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_DEFAULT_MODEL = "gemma4:12b"
_DEFAULT_TIMEOUT = 60.0

_PROMPT = """You are a drone-flight assistant. Using ONLY the FACTS below, write a \
short, plain operator-facing report (3-5 sentences) on flying ONE drone over the \
forecast period. State the best window if there is one, the main limiting factors, \
and one practical recommendation. Do not invent numbers or conditions. Never make \
the conditions sound safer than the facts; if the best window is "none", say flying \
is not advisable in this period.

FACTS:
{facts}
"""

_ERR_BODY = "response body is not an object"
_ERR_MESSAGE = "missing message block"
_ERR_CONTENT = "missing message content"


class ReportError(RuntimeError):
    """Raised when the model's report response is missing or malformed."""

    def __init__(self, context: str) -> None:
        """Build an error naming the part of the response that failed validation.

        Args:
            context: Short description of the missing or invalid field.
        """
        super().__init__(f"Malformed report response: {context}")


def _window_phrase(window: FlightWindow | None) -> str:
    if window is None:
        return "none"
    return f"{window.start_time} to {window.end_time} ({window.hours} h)"


def _limiting_factors(assessment: DroneAssessment) -> str:
    seen: dict[str, None] = {}
    for hour in assessment.hours:
        for factor in hour.limiting_factors:
            seen.setdefault(factor, None)
    return "; ".join(seen)


def facts_for_assessment(member: FleetMember) -> str:
    """Render the engine's verdict facts for one drone as LLM grounding.

    Args:
        member: The drone's profile paired with its assessment.

    Returns:
        A compact, deterministic facts block (limits, best window, per-day outlook,
        and the limiting factors observed) to anchor the generated prose.
    """
    profile = member.profile
    assessment = member.assessment
    lines = [
        f"Drone: {profile.name} (wind limit {profile.caution_gust_ms:.1f} m/s, "
        f"ideal below {profile.ideal_gust_ms:.1f} m/s).",
        f"Best flying window: {_window_phrase(assessment.best_window)}.",
    ]
    if assessment.daily:
        lines.append("Per-day outlook:")
        lines.extend(
            f"- {day.date}: {day.good_hours} good hours, best {_window_phrase(day.best_window)}"
            for day in assessment.daily
        )
    factors = _limiting_factors(assessment)
    if factors:
        lines.append(f"Limiting factors observed: {factors}")
    return "\n".join(lines)


def _content(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ReportError(_ERR_BODY)
    message = cast("dict[str, object]", payload).get("message")
    if not isinstance(message, dict):
        raise ReportError(_ERR_MESSAGE)
    content = cast("dict[str, object]", message).get("content")
    if not isinstance(content, str):
        raise ReportError(_ERR_CONTENT)
    return content.strip()


def apply_audit(member: FleetMember, prose: str) -> str:
    """Prefix the safety banner if the prose under-states the drone's verdict.

    Args:
        member: The assessed drone (the decision ground truth).
        prose: The model-written report.

    Returns:
        The prose unchanged when faithful, or the banner followed by the prose when
        the deterministic audit flags an under-stated restrictive verdict.
    """
    if audit_drone_report(member.assessment, prose):
        return f"{SAFETY_BANNER}\n\n{prose}"
    return prose


def generate_drone_report(
    member: FleetMember,
    *,
    host: str = _DEFAULT_OLLAMA_HOST,
    model: str = _DEFAULT_MODEL,
    timeout: float = _DEFAULT_TIMEOUT,
) -> str:
    """Generate a grounded, audited narrative report for one drone via Ollama.

    Performs a blocking HTTP call to an Ollama ``/api/chat`` endpoint, so it is for
    contexts with a running server (a UI background task, scripts); a model must be
    pulled. The generated prose is audited and prefixed with the safety banner if it
    under-states the verdict.

    Args:
        member: The drone's profile paired with its assessment (the grounding).
        host: Base URL of the Ollama server.
        model: Ollama model tag to generate with.
        timeout: Per-request timeout in seconds.

    Returns:
        The audited operator-facing report.

    Raises:
        httpx.HTTPError: If the request fails or returns an error status.
        ReportError: If the model's response is missing or malformed.
    """
    prompt = _PROMPT.format(facts=facts_for_assessment(member))
    response = httpx.post(
        f"{host}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=timeout,
    )
    _ = response.raise_for_status()
    return apply_audit(member, _content(response.json()))
