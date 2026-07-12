"""Command-line entrypoint for the open-meteo weather agent.

Supports a one-shot query (``weather-agent "..."``) and an interactive chat
session (``weather-agent chat``). The chat session reuses a single Strands
``Agent`` instance across turns, so the agent's built-in conversation history
provides short-term memory: earlier questions and answers stay in context until
the agent's sliding-window manager trims the oldest turns.
"""

import logging
import sys
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from weather_agent.agent import build_agent
from weather_agent.application import DECISION_CAPTURE_KEY, DecisionCapture

if TYPE_CHECKING:
    from collections.abc import Callable

_DEFAULT_PROMPT = "What is the current weather in Berlin?"
_CHAT_COMMAND = "chat"
_EXIT_COMMANDS = frozenset({"exit", "quit", ":q"})


def _is_exit_command(text: str) -> bool:
    """Return whether a chat input asks to end the session.

    Args:
        text: Raw line entered by the user.

    Returns:
        True when the trimmed, lower-cased input is a recognised exit command.
    """
    return text.strip().lower() in _EXIT_COMMANDS


def _run_once(prompt: str) -> None:
    """Run a single query against a fresh agent (no retained memory)."""
    agent = build_agent()
    response = _run_agent_turn(agent, prompt)
    if response:
        print(response)


def _run_agent_turn(agent: Callable[..., object], prompt: str) -> str:
    """Run one model turn and select application-owned output when captured.

    Drone tools populate a request-local capture with their typed deterministic
    result. In that case arbitrary model prose is not shown; for every other tool,
    the model's normal final response is returned.
    """
    capture = DecisionCapture()
    result = agent(prompt, invocation_state={DECISION_CAPTURE_KEY: capture})
    if capture.response is not None:
        return capture.response.text
    return str(result).strip()


def _run_chat() -> None:
    """Run an interactive chat loop backed by one memory-retaining agent.

    A single agent instance is reused for every turn, so its conversation
    history carries context forward. Each completed turn is rendered here so a
    captured deterministic drone decision takes authority over model prose.
    """
    agent = build_agent()
    print("Weather chat — ask about weather, climate, air quality, and more.")
    print("Type 'exit' or press Ctrl-C to quit.")
    while True:
        try:
            user_input = input("\nYou: ")
        except EOFError:
            break
        except KeyboardInterrupt:
            break
        if _is_exit_command(user_input):
            break
        if not user_input.strip():
            continue
        print("\nAssistant:")
        response = _run_agent_turn(agent, user_input)
        if response:
            print(response)
    print("\nGoodbye.")


def main() -> None:
    """Dispatch to the chat session or a one-shot query.

    ``weather-agent chat`` starts the interactive memory-retaining session;
    any other arguments are joined into a single prompt and answered once.
    Requires a reachable Ollama server, since the agent calls a local LLM.
    Loads variables from a local ``.env`` first, so an optional ``OPENAIP_API_KEY``
    (used only by the airspace tool) is available to the boundary that reads it.
    """
    logging.basicConfig(level=logging.WARNING)
    _ = load_dotenv()
    args = sys.argv[1:]
    if args and args[0] == _CHAT_COMMAND:
        _run_chat()
        return
    prompt = " ".join(args).strip() or _DEFAULT_PROMPT
    _run_once(prompt)
