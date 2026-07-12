"""Tests for request-scoped deterministic drone response capture."""

from strands.types.tools import ToolContext

from weather_agent.application import DECISION_CAPTURE_KEY, DecisionCapture
from weather_agent.tools import assess_drone_conditions


def test_drone_tool_records_response_in_strands_invocation_state() -> None:
    """The context-enabled tool preserves its typed result outside model-visible text."""
    capture = DecisionCapture()
    context = ToolContext(
        tool_use={
            "toolUseId": "test-tool-use",
            "name": "assess_drone_conditions",
            "input": {},
        },
        agent=object(),
        invocation_state={DECISION_CAPTURE_KEY: capture},
    )

    tool_text = assess_drone_conditions(
        location="Congleton UK",
        drone="unsupported test drone",
        tool_context=context,
    )

    assert capture.response is not None
    assert capture.response.text == tool_text
    assert capture.response.assessment is None


def test_tool_context_is_not_exposed_in_model_schema() -> None:
    """Strands injects request state instead of asking the model to construct it."""
    schema = assess_drone_conditions.tool_spec["inputSchema"]["json"]
    properties = schema["properties"]

    assert set(properties) == {"location", "drone"}
