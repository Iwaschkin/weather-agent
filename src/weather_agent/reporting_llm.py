"""Optional model commentary for deterministic drone assessments.

The application renders the verdict, windows, factors, source status, legal
context, and disclaimer directly from the typed assessment. This boundary asks a
local model only for two short explanatory fields and rejects output that is not
valid JSON, exceeds the field limits, or tries to make a flight decision. A
generation failure therefore removes optional commentary; it never removes or
replaces the authoritative result.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import httpx

if TYPE_CHECKING:
    from weather_agent.models import DroneAssessment, FleetMember, FlightWindow

_DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_DEFAULT_MODEL = "gemma4:12b"
_DEFAULT_TIMEOUT = 60.0
_MAX_SUMMARY_CHARS = 280
_MAX_PREFLIGHT_NOTE_CHARS = 180

_PROMPT = """You explain weather factors for a drone operator. The application, not you, \
owns and displays every verdict and recommendation. Using ONLY the FACTS below, return \
one JSON object with exactly these string fields:

- "summary": one or two factual sentences explaining the main measured constraints.
- "preflight_note": one factual reminder to recheck current observations or official \
airspace/NOTAM information.

Do not state or imply whether to fly. Do not use verdict labels, claim conditions are \
safe/unsafe or suitable/unsuitable, or recommend/advise/prohibit flight. Do not invent \
numbers or conditions. Keep summary under 280 characters and preflight_note under 180 \
characters. Output JSON only.

FACTS:
{facts}
"""

_ERR_BODY = "response body is not an object"
_ERR_MESSAGE = "missing message block"
_ERR_CONTENT = "missing message content"
_ERR_INVALID_JSON = "message content is not valid JSON"
_ERR_RESPONSE_JSON = "response is not valid JSON"
_ERR_NOT_JSON_OBJECT = "message content is not a JSON object"
_ERR_WRONG_KEYS = "JSON object must contain exactly summary and preflight_note"
_ERR_DECISION_LANGUAGE = "commentary contains prohibited decision language"
_COMMENTARY_KEYS = frozenset({"summary", "preflight_note"})
_PROHIBITED_DECISION_PATTERNS = (
    r"\bverdict\b",
    r"\bgood(?:-to-fly)?\b",
    r"\bmarginal\b",
    r"\bunknown\b",
    r"\bno[ -]?fly\b",
    r"\bfly(?:ing)?\b",
    r"\bsafe(?:ty)?\b",
    r"\bunsafe\b",
    r"\bsuitable\b",
    r"\bunsuitable\b",
    r"\brecommend(?:ed|ation|ing|s)?\b",
    r"\badvis(?:e|ed|able|ing)\b",
    r"\bproceed\b",
)


class ReportError(RuntimeError):
    """Raised when generated commentary violates the narrow response contract."""

    def __init__(self, context: str) -> None:
        """Build an error naming the part of the response that failed validation.

        Args:
            context: Short description of the missing or invalid field.
        """
        super().__init__(f"Malformed report response: {context}")


@dataclass(frozen=True, slots=True)
class GeneratedCommentary:
    """Validated, non-authoritative explanation shown after a fixed decision."""

    summary: str
    preflight_note: str

    @property
    def text(self) -> str:
        """Render both commentary fields without adding decision language."""
        return f"{self.summary}\n\nPre-flight note: {self.preflight_note}"


def _window_phrase(window: FlightWindow | None) -> str:
    if window is None:
        return "none"
    return f"{window.start_time.isoformat()} to {window.end_time.isoformat()} ({window.hours} h)"


def _limiting_factors(assessment: DroneAssessment) -> str:
    seen: dict[str, None] = {}
    for hour in assessment.hours:
        for factor in hour.limiting_factors:
            seen.setdefault(factor, None)
    return "; ".join(seen)


def facts_for_assessment(member: FleetMember) -> str:
    """Render deterministic weather facts for optional explanatory commentary.

    The model receives the engine's decision context so it can identify relevant
    measured constraints, but the output contract expressly prevents it from
    restating or selecting a verdict.

    Args:
        member: The drone's profile paired with its assessment.

    Returns:
        A compact facts block containing limits, windows, daily counts, and
        measured limiting factors.
    """
    profile = member.profile
    assessment = member.assessment
    lines = [
        f"Drone: {profile.name} (wind limit {profile.caution_gust_ms:.1f} m/s, "
        f"ideal below {profile.ideal_gust_ms:.1f} m/s).",
        f"Application-selected best window: {_window_phrase(assessment.best_window)}.",
    ]
    if assessment.daily:
        lines.append("Application-computed per-day counts:")
        lines.extend(
            f"- {day.date}: {day.good_hours} acceptable hours; selected window "
            f"{_window_phrase(day.best_window)}"
            for day in assessment.daily
        )
    factors = _limiting_factors(assessment)
    if factors:
        lines.append(f"Measured limiting factors: {factors}")
    return "\n".join(lines)


def _content(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ReportError(_ERR_BODY)
    message = cast("dict[str, object]", payload).get("message")
    if not isinstance(message, dict):
        raise ReportError(_ERR_MESSAGE)
    content = cast("dict[str, object]", message).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ReportError(_ERR_CONTENT)
    return content.strip()


def _field(payload: dict[str, object], name: str, limit: int) -> str:
    value = payload.get(name)
    if not isinstance(value, str):
        context = f"{name} must be a string"
        raise ReportError(context)
    normalized = " ".join(value.split())
    if not normalized:
        context = f"{name} must not be empty"
        raise ReportError(context)
    if len(normalized) > limit:
        context = f"{name} exceeds {limit} characters"
        raise ReportError(context)
    return normalized


def _reject_decision_claims(commentary: GeneratedCommentary) -> None:
    combined = f"{commentary.summary} {commentary.preflight_note}"
    for pattern in _PROHIBITED_DECISION_PATTERNS:
        if re.search(pattern, combined, flags=re.IGNORECASE):
            raise ReportError(_ERR_DECISION_LANGUAGE)


def parse_commentary(content: str) -> GeneratedCommentary:
    """Validate a model response against the commentary-only JSON contract.

    Args:
        content: Raw model message content.

    Returns:
        Normalized commentary when the JSON object has exactly the allowed fields.

    Raises:
        ReportError: If JSON, shape, fields, lengths, or language are invalid.
    """
    try:
        decoded = cast("object", json.loads(content))
    except json.JSONDecodeError as error:
        raise ReportError(_ERR_INVALID_JSON) from error
    if not isinstance(decoded, dict):
        raise ReportError(_ERR_NOT_JSON_OBJECT)
    payload = cast("dict[str, object]", decoded)
    if frozenset(payload) != _COMMENTARY_KEYS:
        raise ReportError(_ERR_WRONG_KEYS)
    commentary = GeneratedCommentary(
        summary=_field(payload, "summary", _MAX_SUMMARY_CHARS),
        preflight_note=_field(payload, "preflight_note", _MAX_PREFLIGHT_NOTE_CHARS),
    )
    _reject_decision_claims(commentary)
    return commentary


def generate_drone_report(
    member: FleetMember,
    *,
    host: str = _DEFAULT_OLLAMA_HOST,
    model: str = _DEFAULT_MODEL,
    timeout: float = _DEFAULT_TIMEOUT,
) -> GeneratedCommentary:
    """Generate optional, strictly validated commentary through local Ollama.

    The deterministic decision is rendered elsewhere and remains complete when
    this call fails. The model is asked for JSON-only explanatory fields and is
    never asked to select or restate a verdict.

    Args:
        member: The drone and assessment used as grounding.
        host: Base URL of the Ollama server.
        model: Ollama model tag to generate with.
        timeout: Per-request timeout in seconds.

    Returns:
        Validated commentary containing no flight-decision language.

    Raises:
        httpx.HTTPError: If the request fails or returns an error status.
        ReportError: If the response violates the commentary contract.
    """
    prompt = _PROMPT.format(facts=facts_for_assessment(member))
    response = httpx.post(
        f"{host}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
        timeout=timeout,
    )
    _ = response.raise_for_status()
    try:
        payload: object = response.json()
    except json.JSONDecodeError as error:
        raise ReportError(_ERR_RESPONSE_JSON) from error
    return parse_commentary(_content(payload))
