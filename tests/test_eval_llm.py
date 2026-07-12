"""Tests for the opt-in LLM-as-judge harness.

The pure parts (facts rendering, response parsing) run always; the live judge call
is opt-in - skipped unless WEATHER_AGENT_LLM_EVAL=1 and an Ollama server is running.
"""

import json
import os

import pytest

from tests.time_helpers import aware
from weather_agent.drone import MINI_5_PRO
from weather_agent.eval_llm import (
    JudgeError,
    JudgeVerdict,
    _parse_judge_response,
    facts_for_hour,
    ollama_faithfulness_judge,
)
from weather_agent.flyability import assess_hour
from weather_agent.models import DroneFlightHour

_GUSTY_HOUR = DroneFlightHour(
    time=aware("2026-06-16T11:00"),
    temperature_c=16.0,
    apparent_temperature_c=16.0,
    wind_gust_10m_kmh=60.0,  # ~16.7 m/s, over the Mini 5 Pro's 12 m/s limit
    wind_max_0_500m_kmh=60.0,
    precipitation_mm=0.0,
    precipitation_probability_pct=0.0,
    visibility_m=20000.0,
    cape=0.0,
    freezing_level_agl_m=2500.0,
    is_day=True,
    cloud_cover_low_pct=10.0,
)


def test_facts_for_hour_includes_verdict_and_metrics() -> None:
    """The facts block names the verdict and each gate metric (ground truth)."""
    facts = facts_for_hour(assess_hour(MINI_5_PRO, _GUSTY_HOUR))

    assert "verdict: no_fly" in facts
    assert "wind_gust" in facts


def test_parse_judge_response_reads_fields() -> None:
    """A well-formed Ollama chat response is parsed into a verdict."""
    content = json.dumps({"faithful": False, "understates_risk": True, "notes": "downplays gusts"})
    payload = {"message": {"content": content}}

    verdict = _parse_judge_response(payload)

    assert verdict == JudgeVerdict(faithful=False, understates_risk=True, notes="downplays gusts")


@pytest.mark.parametrize(
    "payload",
    ["not-a-dict", {}, {"message": {}}, {"message": {"content": "not json"}}],
)
def test_parse_judge_response_rejects_malformed(payload: object) -> None:
    """Missing or non-JSON judge responses raise a judge error."""
    with pytest.raises(JudgeError):
        _ = _parse_judge_response(payload)


@pytest.mark.parametrize(
    "content",
    [
        {"faithful": "false", "understates_risk": False, "notes": "wrong type"},
        {"faithful": False, "understates_risk": 0, "notes": "wrong type"},
        {"faithful": False, "understates_risk": True, "notes": ["not", "text"]},
        {"faithful": False, "understates_risk": True},
        {"faithful": False, "understates_risk": True, "notes": " ", "extra": 1},
    ],
)
def test_parse_judge_response_rejects_coercible_or_wrong_shape(
    content: dict[str, object],
) -> None:
    """Model values must have the exact JSON shape rather than Python truthiness."""
    payload = {"message": {"content": json.dumps(content)}}

    with pytest.raises(JudgeError):
        _ = _parse_judge_response(payload)


class _InvalidJsonResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        message = "invalid"
        document = "{"
        raise json.JSONDecodeError(message, document, 0)


def test_ollama_judge_normalizes_invalid_response_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid outer Ollama JSON is a typed judge failure."""

    def fake_post(_url: str, *, json: object, timeout: float) -> _InvalidJsonResponse:
        _ = (json, timeout)
        return _InvalidJsonResponse()

    monkeypatch.setattr("weather_agent.eval_llm.httpx.post", fake_post)

    with pytest.raises(JudgeError, match="response is not valid JSON"):
        _ = ollama_faithfulness_judge(
            "Measured gusts are high.",
            assess_hour(MINI_5_PRO, _GUSTY_HOUR),
        )


@pytest.mark.skipif(
    os.environ.get("WEATHER_AGENT_LLM_EVAL") != "1",
    reason="opt-in LLM eval: set WEATHER_AGENT_LLM_EVAL=1 and run an Ollama server",
)
def test_ollama_judge_flags_understatement() -> None:
    """A 'totally safe to fly' gloss over a no-fly hour is judged unfaithful."""
    hour = assess_hour(MINI_5_PRO, _GUSTY_HOUR)

    verdict = ollama_faithfulness_judge("Great day - totally safe to fly!", hour)

    assert verdict.understates_risk or not verdict.faithful
