"""Opt-in LLM-as-judge faithfulness scoring for flyability explanations.

The richer, non-deterministic companion to :mod:`weather_agent.evaluation`: it asks
a chat model whether a free-text explanation is faithful to the engine's structured
facts (a RAGAS-style groundedness check). It performs network I/O against an Ollama
server and is therefore *offline / opt-in* - it is never exercised by the normal
test suite, only when explicitly run against a model.

Typical use: generate an explanation (from the agent, or by hand), then judge it
against the ground-truth hour::

    from weather_agent.eval_llm import ollama_faithfulness_judge
    verdict = ollama_faithfulness_judge(explanation, hour)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import httpx

if TYPE_CHECKING:
    from weather_agent.models import HourAssessment

_DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_DEFAULT_MODEL = "gemma4:12b"
_DEFAULT_TIMEOUT = 60.0

_PROMPT = """You grade whether an EXPLANATION is faithful to the FACTS about one \
drone-flight hour. The FACTS come from a deterministic rules engine and are ground \
truth.

FACTS:
{facts}

EXPLANATION:
{explanation}

Reply with JSON only, no prose:
{{"faithful": true_or_false, "understates_risk": true_or_false, "notes": "one short sentence"}}
- "faithful" is true only if every claim in the explanation is supported by the facts.
- "understates_risk" is true if the explanation makes conditions sound safer than the verdict.
"""


_ERR_BODY = "response body is not an object"
_ERR_MESSAGE = "missing message block"
_ERR_CONTENT = "missing message content"
_ERR_NOT_JSON = "message content is not JSON"
_ERR_NOT_OBJECT = "message content is not a JSON object"


class JudgeError(RuntimeError):
    """Raised when the judge model's response is missing or malformed."""

    def __init__(self, context: str) -> None:
        """Build an error naming the part of the response that failed validation.

        Args:
            context: Short description of the missing or invalid field.
        """
        super().__init__(f"Malformed judge response: {context}")


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """An LLM judge's faithfulness ruling on one explanation.

    Attributes:
        faithful: Whether every claim is supported by the facts.
        understates_risk: Whether the explanation downplays the verdict's risk.
        notes: The judge's one-sentence rationale.
    """

    faithful: bool
    understates_risk: bool
    notes: str


def facts_for_hour(hour: HourAssessment) -> str:
    """Render an hour's verdict and gate readings as ground-truth facts for judging.

    Args:
        hour: The engine's assessment for the hour.

    Returns:
        A compact, deterministic facts block (the verdict plus one line per gate
        reading with its value, threshold, and band).
    """
    lines = [f"verdict: {hour.verdict.value}"]
    for reading in hour.readings:
        value = "n/a" if reading.value is None else f"{reading.value:.1f} {reading.unit}".strip()
        threshold = "" if reading.threshold is None else f", threshold {reading.threshold:.1f}"
        lines.append(f"- {reading.metric}: {value}{threshold}, band {reading.band.value}")
    return "\n".join(lines)


def _parse_judge_response(payload: object) -> JudgeVerdict:
    if not isinstance(payload, dict):
        raise JudgeError(_ERR_BODY)
    message = cast("dict[str, object]", payload).get("message")
    if not isinstance(message, dict):
        raise JudgeError(_ERR_MESSAGE)
    content = cast("dict[str, object]", message).get("content")
    if not isinstance(content, str):
        raise JudgeError(_ERR_CONTENT)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise JudgeError(_ERR_NOT_JSON) from error
    if not isinstance(parsed, dict):
        raise JudgeError(_ERR_NOT_OBJECT)
    data = cast("dict[str, object]", parsed)
    return JudgeVerdict(
        faithful=bool(data.get("faithful")),
        understates_risk=bool(data.get("understates_risk")),
        notes=str(data.get("notes", "")),
    )


def ollama_faithfulness_judge(
    explanation: str,
    hour: HourAssessment,
    *,
    host: str = _DEFAULT_OLLAMA_HOST,
    model: str = _DEFAULT_MODEL,
    timeout: float = _DEFAULT_TIMEOUT,
) -> JudgeVerdict:
    """Judge whether an explanation is faithful to an hour's verdict, via Ollama.

    Performs a blocking HTTP call to an Ollama ``/api/chat`` endpoint, so it is for
    offline evaluation only (a running server with ``model`` pulled is required).

    Args:
        explanation: The free-text explanation to grade.
        hour: The engine's assessment for the hour (ground truth).
        host: Base URL of the Ollama server.
        model: Ollama model tag to judge with.
        timeout: Per-request timeout in seconds.

    Returns:
        The judge's faithfulness verdict.

    Raises:
        httpx.HTTPError: If the request fails or returns an error status.
        JudgeError: If the model's response is missing or malformed.
    """
    prompt = _PROMPT.format(facts=facts_for_hour(hour), explanation=explanation)
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
    return _parse_judge_response(response.json())
