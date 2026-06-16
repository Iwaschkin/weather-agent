"""Tests for the CLI's pure helpers."""

import pytest

from weather_agent.cli import _is_exit_command


@pytest.mark.parametrize("text", ["exit", "QUIT", "  :q  ", "Exit\n"])
def test_is_exit_command_recognises_exits(text: str) -> None:
    """Recognised exit words are matched regardless of case and whitespace."""
    assert _is_exit_command(text) is True


@pytest.mark.parametrize("text", ["", "weather in Berlin", "exits", "quitter"])
def test_is_exit_command_ignores_other_input(text: str) -> None:
    """Ordinary chat input is not treated as an exit command."""
    assert _is_exit_command(text) is False
