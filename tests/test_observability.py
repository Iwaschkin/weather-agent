"""Tests for the tool-call observability hook."""

from typing import TYPE_CHECKING, Literal

import pytest
from strands.agent import AgentResult
from strands.hooks import (
    AfterInvocationEvent,
    AfterToolCallEvent,
    BeforeToolCallEvent,
    HookRegistry,
)
from strands.telemetry import EventLoopMetrics

from weather_agent.agent import build_agent
from weather_agent.observability import (
    ToolCall,
    ToolCallObserver,
    summarize_tool_calls,
    summarize_usage,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from strands import Agent


@pytest.fixture
def agent() -> Agent:
    """A real, offline agent used only to satisfy the event's agent field.

    ``OllamaModel`` construction performs no I/O, so this needs no running server.
    """
    return build_agent()


def _sequence_clock(ticks: list[float]) -> Callable[[], float]:
    """Return a clock that yields each tick in turn, for deterministic timing."""
    values = iter(ticks)

    def clock() -> float:
        return next(values)

    return clock


def _before(agent: Agent, name: str, use_id: str) -> BeforeToolCallEvent:
    """Build a BeforeToolCallEvent for the named tool."""
    return BeforeToolCallEvent(
        agent=agent,
        selected_tool=None,
        tool_use={"name": name, "toolUseId": use_id, "input": {}},
        invocation_state={},
    )


def _after(
    agent: Agent,
    name: str,
    use_id: str,
    status: Literal["success", "error"] = "success",
) -> AfterToolCallEvent:
    """Build an AfterToolCallEvent for the named tool with the given status."""
    return AfterToolCallEvent(
        agent=agent,
        selected_tool=None,
        tool_use={"name": name, "toolUseId": use_id, "input": {}},
        invocation_state={},
        result={"status": status, "toolUseId": use_id, "content": []},
    )


def _invocation_end(agent: Agent, *, with_result: bool) -> AfterInvocationEvent:
    """Build an AfterInvocationEvent, optionally carrying an AgentResult."""
    result = (
        AgentResult(
            stop_reason="end_turn",
            message={"role": "assistant", "content": []},
            metrics=EventLoopMetrics(),
            state={},
        )
        if with_result
        else None
    )
    return AfterInvocationEvent(agent=agent, result=result)


@pytest.mark.parametrize(
    ("calls", "expected"),
    [
        ([], "no tool calls"),
        (
            [ToolCall(name="get_forecast", duration_ms=120.0, succeeded=True)],
            "1 tool call, 120.0 ms total, 0 failed: get_forecast x1 (120.0 ms)",
        ),
        (
            [
                ToolCall(name="get_forecast", duration_ms=100.0, succeeded=True),
                ToolCall(name="assess_drone_conditions", duration_ms=50.0, succeeded=False),
                ToolCall(name="get_forecast", duration_ms=200.0, succeeded=True),
            ],
            "3 tool calls, 350.0 ms total, 1 failed: "
            "get_forecast x2 (300.0 ms), assess_drone_conditions x1 (50.0 ms)",
        ),
    ],
)
def test_summarize_tool_calls(calls: list[ToolCall], expected: str) -> None:
    """The summary groups tools in first-seen order with counts and totals."""
    assert summarize_tool_calls(calls) == expected


def test_summarize_usage() -> None:
    """Token counts and model latency render as a compact line."""
    summary = summarize_usage(
        input_tokens=120, output_tokens=45, total_tokens=165, model_latency_ms=900
    )
    assert summary == "tokens in=120 out=45 total=165, model latency 900 ms"


def test_observer_times_and_records_a_successful_tool_call(agent: Agent) -> None:
    """A before/after pair is recorded as one timed, successful tool call.

    The invocation carries a result so the token-metrics branch is exercised.
    """
    observer = ToolCallObserver(clock=_sequence_clock([0.0, 1.0]))
    registry = HookRegistry()
    observer.register_hooks(registry)

    _ = registry.invoke_callbacks(_before(agent, "get_forecast", "t1"))
    _ = registry.invoke_callbacks(_after(agent, "get_forecast", "t1"))
    _ = registry.invoke_callbacks(_invocation_end(agent, with_result=True))

    assert observer.calls == (ToolCall(name="get_forecast", duration_ms=1000.0, succeeded=True),)


def test_observer_marks_a_failed_tool_call(agent: Agent) -> None:
    """An error status is recorded as a failed tool call."""
    observer = ToolCallObserver(clock=_sequence_clock([0.0, 0.5]))
    registry = HookRegistry()
    observer.register_hooks(registry)

    _ = registry.invoke_callbacks(_before(agent, "get_airspace", "t1"))
    _ = registry.invoke_callbacks(_after(agent, "get_airspace", "t1", status="error"))
    _ = registry.invoke_callbacks(_invocation_end(agent, with_result=False))

    assert observer.calls == (ToolCall(name="get_airspace", duration_ms=500.0, succeeded=False),)


def test_observer_resets_state_between_invocations(agent: Agent) -> None:
    """Each invocation starts clean, so calls reflect only the latest run."""
    observer = ToolCallObserver(clock=_sequence_clock([0.0, 1.0, 10.0, 12.0]))
    registry = HookRegistry()
    observer.register_hooks(registry)

    _ = registry.invoke_callbacks(_before(agent, "get_forecast", "t1"))
    _ = registry.invoke_callbacks(_after(agent, "get_forecast", "t1"))
    _ = registry.invoke_callbacks(_invocation_end(agent, with_result=False))

    _ = registry.invoke_callbacks(_before(agent, "get_current_weather", "t2"))
    _ = registry.invoke_callbacks(_after(agent, "get_current_weather", "t2"))
    _ = registry.invoke_callbacks(_invocation_end(agent, with_result=False))

    assert observer.calls == (
        ToolCall(name="get_current_weather", duration_ms=2000.0, succeeded=True),
    )
