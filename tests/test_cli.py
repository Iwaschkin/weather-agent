"""Tests for CLI helpers and the application-owned final response boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from weather_agent.application import DECISION_CAPTURE_KEY, DecisionCapture, DroneResponse
from weather_agent.cli import _is_exit_command, _run_agent_turn
from weather_agent.results import Answer


@pytest.mark.parametrize("text", ["exit", "QUIT", "  :q  ", "Exit\n"])
def test_is_exit_command_recognises_exits(text: str) -> None:
    """Recognised exit words are matched regardless of case and whitespace."""
    assert _is_exit_command(text) is True


@pytest.mark.parametrize("text", ["", "weather in Berlin", "exits", "quitter"])
def test_is_exit_command_ignores_other_input(text: str) -> None:
    """Ordinary chat input is not treated as an exit command."""
    assert _is_exit_command(text) is False


def test_agent_turn_returns_normal_model_answer_without_drone_capture() -> None:
    """Non-drone turns retain the ordinary Strands final response."""

    def model(prompt: str, *, invocation_state: dict[str, object]) -> object:
        assert prompt == "weather now"
        assert isinstance(invocation_state[DECISION_CAPTURE_KEY], DecisionCapture)
        return "  Model weather answer  "

    assert _run_agent_turn(model, "weather now") == "Model weather answer"


def test_agent_turn_discards_contradictory_model_drone_answer() -> None:
    """A captured no-fly report remains visible even if final model prose lowers it."""
    deterministic = "NO-FLY: gusts exceed the limit.\n\nDecision-support disclaimer."

    def model(_prompt: str, *, invocation_state: dict[str, object]) -> object:
        capture = invocation_state[DECISION_CAPTURE_KEY]
        assert isinstance(capture, DecisionCapture)
        capture.record(DroneResponse(Answer(deterministic)))
        return "Great weather; flying is recommended."

    result = _run_agent_turn(model, "Can I fly?")

    assert result == deterministic
    assert "recommended" not in result
    assert "disclaimer" in result


def test_agent_turn_capture_is_isolated_across_concurrent_requests() -> None:
    """Concurrent turns cannot read or overwrite another request's captured result."""
    barrier = Barrier(2)
    captures: list[DecisionCapture] = []

    def model(prompt: str, *, invocation_state: dict[str, object]) -> object:
        capture = invocation_state[DECISION_CAPTURE_KEY]
        assert isinstance(capture, DecisionCapture)
        captures.append(capture)
        _ = barrier.wait()
        capture.record(DroneResponse(Answer(f"authoritative {prompt}")))
        return f"model {prompt}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = tuple(pool.map(lambda prompt: _run_agent_turn(model, prompt), ("one", "two")))

    assert outputs == ("authoritative one", "authoritative two")
    assert len(captures) == 2
    assert captures[0] is not captures[1]
