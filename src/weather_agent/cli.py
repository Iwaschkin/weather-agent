"""Command-line entrypoint for the open-meteo weather agent.

Supports a one-shot query (``weather-agent "..."``) and an interactive chat
session (``weather-agent chat``). The chat session reuses a single Strands
``Agent`` instance across turns, so the agent's built-in conversation history
provides short-term memory: earlier questions and answers stay in context until
the agent's sliding-window manager trims the oldest turns.
"""

import logging
import sys

from weather_agent.agent import build_agent

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
    _ = agent(prompt)


def _run_chat() -> None:
    """Run an interactive chat loop backed by one memory-retaining agent.

    A single agent instance is reused for every turn, so its conversation
    history carries context forward. The agent streams its own responses to
    stdout; this loop only handles reading input and the exit conditions.
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
        _ = agent(user_input)
    print("\nGoodbye.")


def main() -> None:
    """Dispatch to the chat session or a one-shot query.

    ``weather-agent chat`` starts the interactive memory-retaining session;
    any other arguments are joined into a single prompt and answered once.
    Requires a reachable Ollama server, since the agent calls a local LLM.
    """
    logging.basicConfig(level=logging.WARNING)
    args = sys.argv[1:]
    if args and args[0] == _CHAT_COMMAND:
        _run_chat()
        return
    prompt = " ".join(args).strip() or _DEFAULT_PROMPT
    _run_once(prompt)
