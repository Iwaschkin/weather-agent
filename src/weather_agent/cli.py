"""Command-line entrypoint for the open-meteo weather agent.

Supports a one-shot query (``weather-agent "..."``) and an interactive chat
session (``weather-agent chat``). The chat session reuses a single Strands
``Agent`` instance across turns, so the agent's built-in conversation history
provides short-term memory: earlier questions and answers stay in context until
the agent's sliding-window manager trims the oldest turns.
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from weather_agent.agent import build_agent
from weather_agent.benchmark import format_summary, run_benchmark
from weather_agent.benchmark_compare import compare_reports, format_comparison
from weather_agent.benchmark_report import (
    BenchmarkReportError,
    format_report_markdown,
    load_report,
    write_report,
)
from weather_agent.tracing import enable_console_tracing

_DEFAULT_PROMPT = "What is the current weather in Berlin?"
_CHAT_COMMAND = "chat"
_BENCHMARK_COMMAND = "benchmark"
_BENCHMARK_COMPARE = "compare"
_BENCHMARK_MARKDOWN = "markdown"
_BENCHMARK_DIR = Path("benchmarks")
_COMPARE_PATH_COUNT = 2
_TRACE_ENV_VAR = "WEATHER_AGENT_TRACE"
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


def _run_benchmark_command(args: list[str]) -> None:
    """Dispatch a benchmark sub-action: run (default), compare, or markdown."""
    if args and args[0] == _BENCHMARK_COMPARE:
        _benchmark_compare(args[1:])
        return
    if args and args[0] == _BENCHMARK_MARKDOWN:
        _benchmark_markdown(args[1:])
        return
    _benchmark_run()


def _benchmark_run() -> None:
    """Run the default benchmark, write a JSON report, and print the summary."""
    report = run_benchmark()
    path = write_report(report, _BENCHMARK_DIR)
    print(format_summary(report.summary))
    print(f"\nReport written to {path}")


def _benchmark_compare(paths: list[str]) -> None:
    """Print a metric-by-metric comparison of two saved report files."""
    if len(paths) != _COMPARE_PATH_COUNT:
        print("usage: weather-agent benchmark compare <baseline.json> <candidate.json>")
        return
    try:
        baseline = load_report(Path(paths[0]))
        candidate = load_report(Path(paths[1]))
    except (OSError, BenchmarkReportError) as error:
        print(f"Could not load report: {error}")
        return
    print(format_comparison(compare_reports(baseline, candidate)))


def _benchmark_markdown(paths: list[str]) -> None:
    """Print a saved report file rendered as a markdown table."""
    if len(paths) != 1:
        print("usage: weather-agent benchmark markdown <report.json>")
        return
    try:
        report = load_report(Path(paths[0]))
    except (OSError, BenchmarkReportError) as error:
        print(f"Could not load report: {error}")
        return
    print(format_report_markdown(report))


def main() -> None:
    """Dispatch to the chat session, the benchmark, or a one-shot query.

    ``weather-agent chat`` starts the interactive memory-retaining session;
    ``weather-agent benchmark`` runs the cost / tool-routing benchmark; any other
    arguments are joined into a single prompt and answered once. Requires a
    reachable Ollama server, since the agent calls a local LLM. Loads variables
    from a local ``.env`` first, so an optional ``OPENAIP_API_KEY`` (used only by
    the airspace tool) is available to the boundary that reads it. Set
    ``WEATHER_AGENT_TRACE`` to any value to print OpenTelemetry spans.
    """
    logging.basicConfig(level=logging.WARNING)
    _ = load_dotenv()
    if os.getenv(_TRACE_ENV_VAR):
        enable_console_tracing()
    args = sys.argv[1:]
    if args and args[0] == _CHAT_COMMAND:
        _run_chat()
        return
    if args and args[0] == _BENCHMARK_COMMAND:
        _run_benchmark_command(args[1:])
        return
    prompt = " ".join(args).strip() or _DEFAULT_PROMPT
    _run_once(prompt)
