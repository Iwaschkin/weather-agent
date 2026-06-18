"""Tests for the assembled weather agent's static wiring."""

from weather_agent.agent import _SYSTEM_PROMPT, _TOOLS


def test_system_prompt_names_every_wired_tool() -> None:
    """Every wired tool is named in the routing prompt.

    The system prompt is the model's only guide to which tool answers which
    question, so a tool that is registered but never mentioned is effectively
    invisible to it. This catches that drift when a tool is added or renamed
    without updating the routing table.
    """
    unmentioned = [t.tool_name for t in _TOOLS if t.tool_name not in _SYSTEM_PROMPT]
    assert unmentioned == []
