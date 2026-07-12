"""Tests for the optional, commentary-only Ollama boundary."""

from __future__ import annotations

import json

import pytest

from tests.time_helpers import LONDON_SUMMER_CONTEXT, aware
from weather_agent.caa import caa_guidance
from weather_agent.drone import MINI_5_PRO
from weather_agent.models import (
    DroneAssessment,
    FleetMember,
    FlightWindow,
    HourAssessment,
    Verdict,
)
from weather_agent.reporting_llm import (
    GeneratedCommentary,
    ReportError,
    _content,
    facts_for_assessment,
    generate_drone_report,
    parse_commentary,
)


def _member(
    verdict: Verdict,
    factors: tuple[str, ...],
    best: FlightWindow | None,
) -> FleetMember:
    hour = HourAssessment(aware("2026-06-16T11:00"), verdict, factors, None)
    assessment = DroneAssessment(
        MINI_5_PRO.name,
        "Congleton, England",
        (hour,),
        best,
        LONDON_SUMMER_CONTEXT,
    )
    return FleetMember(profile=MINI_5_PRO, assessment=assessment, guidance=caa_guidance(MINI_5_PRO))


def test_facts_for_assessment_includes_limits_and_window() -> None:
    """The facts block names limits and the application-selected window."""
    member = _member(
        Verdict.GOOD,
        (),
        FlightWindow(aware("2026-06-16T06:00"), aware("2026-06-16T11:00"), 5),
    )

    facts = facts_for_assessment(member)

    assert "DJI Mini 5 Pro" in facts
    assert "12.0 m/s" in facts
    assert (
        "Application-selected best window: 2026-06-16T06:00:00+01:00 to "
        "2026-06-16T11:00:00+01:00 (5 h)" in facts
    )


def test_facts_for_assessment_reports_no_window_and_factors() -> None:
    """With no selected window the facts retain the measured limiting factors."""
    member = _member(Verdict.NO_FLY, ("gusts 13.0 m/s exceed the 12.0 m/s limit",), None)

    facts = facts_for_assessment(member)

    assert "Application-selected best window: none" in facts
    assert "gusts 13.0 m/s exceed the 12.0 m/s limit" in facts


@pytest.mark.parametrize(
    "payload", ["not-a-dict", {}, {"message": {}}, {"message": {"content": 5}}]
)
def test_content_rejects_malformed(payload: object) -> None:
    """Missing or non-string message content raises a report error."""
    with pytest.raises(ReportError):
        _ = _content(payload)


def test_content_extracts_and_trims_text() -> None:
    """A well-formed chat response yields the trimmed message text."""
    assert _content({"message": {"content": "  {}  "}}) == "{}"


def test_parse_commentary_accepts_exact_contract_and_normalizes_whitespace() -> None:
    """Only the two explanatory fields survive as a typed value."""
    result = parse_commentary(
        '{"summary":" Gusts rise  after 14:00. ",'
        '"preflight_note":"Recheck current observations and official NOTAM sources."}'
    )

    assert result == GeneratedCommentary(
        summary="Gusts rise after 14:00.",
        preflight_note="Recheck current observations and official NOTAM sources.",
    )
    assert result.text.endswith("official NOTAM sources.")


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        '{"summary":"Wind rises."}',
        '{"summary":"Wind rises.","preflight_note":"Recheck.","verdict":"good"}',
        '{"summary":5,"preflight_note":"Recheck."}',
        '{"summary":"Wind rises.","preflight_note":"   "}',
    ],
)
def test_parse_commentary_rejects_malformed_contract(content: str) -> None:
    """Malformed JSON and structural drift are rejected rather than displayed."""
    with pytest.raises(ReportError):
        _ = parse_commentary(content)


@pytest.mark.parametrize(
    "claim",
    [
        "Flying is recommended throughout the day.",
        "Conditions are safe this afternoon.",
        "This is a no-fly period.",
        "The verdict is marginal.",
        "Proceed after lunch.",
    ],
)
def test_parse_commentary_rejects_decision_claims(claim: str) -> None:
    """Commentary cannot acquire authority through ordinary recommendation phrases."""
    content = f'{{"summary":"Gusts rise after 14:00.","preflight_note":"{claim}' + '"}'

    with pytest.raises(ReportError, match="prohibited decision language"):
        _ = parse_commentary(content)


def test_parse_commentary_does_not_confuse_window_with_wind() -> None:
    """Token-boundary validation does not repeat the old window/wind substring bug."""
    result = parse_commentary(
        '{"summary":"The clearest window is before 14:00.",'
        '"preflight_note":"Recheck current observations and NOTAM sources."}'
    )

    assert result.summary == "The clearest window is before 14:00."


def test_parse_commentary_rejects_overlong_fields() -> None:
    """Bounded fields prevent unstructured prose from escaping the narrow panel."""
    content = '{"summary":"' + ("wind " * 60) + '","preflight_note":"Recheck observations."}'

    with pytest.raises(ReportError, match="exceeds 280 characters"):
        _ = parse_commentary(content)


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return {
            "message": {
                "content": (
                    '{"summary":"Gusts increase after 14:00.",'
                    '"preflight_note":"Recheck observations and NOTAM sources."}'
                )
            }
        }


class _InvalidJsonResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        message = "invalid"
        document = "{"
        raise json.JSONDecodeError(message, document, 0)


def test_generate_drone_report_requests_json_without_delegating_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Ollama request asks only for explanatory JSON and validates the result."""
    captured: dict[str, object] = {}

    def fake_post(url: str, *, json: object, timeout: float) -> _FakeResponse:
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("weather_agent.reporting_llm.httpx.post", fake_post)

    result = generate_drone_report(
        _member(Verdict.NO_FLY, ("gusts exceed the limit",), None),
        host="http://ollama.test",
        model="local-model",
        timeout=3.0,
    )

    assert result.summary == "Gusts increase after 14:00."
    assert captured["url"] == "http://ollama.test/api/chat"
    request = captured["json"]
    assert isinstance(request, dict)
    assert request["format"] == "json"
    messages = request["messages"]
    assert isinstance(messages, list)
    first = messages[0]
    assert isinstance(first, dict)
    prompt = first["content"]
    assert isinstance(prompt, str)
    assert "application, not you" in prompt.lower()
    assert "do not state or imply whether to fly" in prompt.lower()


def test_generate_drone_report_normalizes_invalid_response_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid outer Ollama JSON is a typed report failure."""

    def fake_post(_url: str, *, json: object, timeout: float) -> _InvalidJsonResponse:
        _ = (json, timeout)
        return _InvalidJsonResponse()

    monkeypatch.setattr("weather_agent.reporting_llm.httpx.post", fake_post)

    with pytest.raises(ReportError, match="response is not valid JSON"):
        _ = generate_drone_report(_member(Verdict.GOOD, (), None))
