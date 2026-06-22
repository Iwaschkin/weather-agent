"""Tests for benchmark report serialization, I/O round-trip, and markdown."""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from weather_agent.benchmark import BenchmarkReport, RunStat
from weather_agent.benchmark_report import (
    BenchmarkReportError,
    format_report_markdown,
    load_report,
    report_from_json,
    report_to_json,
    write_report,
)
from weather_agent.observability import ToolCall

if TYPE_CHECKING:
    from pathlib import Path

_REPORT = BenchmarkReport(
    model_id="gemma4:12b",
    host="http://localhost:11434",
    captured_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
    runs=(
        RunStat(
            query="q1",
            tool_calls=(ToolCall(name="get_forecast", duration_ms=10.0, succeeded=True),),
            input_tokens=90,
            output_tokens=30,
            total_tokens=120,
            model_latency_ms=200,
        ),
        RunStat(
            query="q2",
            tool_calls=(
                ToolCall(name="get_forecast", duration_ms=10.0, succeeded=True),
                ToolCall(name="get_air_quality", duration_ms=5.0, succeeded=False),
            ),
            input_tokens=180,
            output_tokens=60,
            total_tokens=240,
            model_latency_ms=400,
        ),
    ),
)


def test_json_round_trip_preserves_the_report() -> None:
    """Serializing then parsing a report reproduces it exactly."""
    assert report_from_json(report_to_json(_REPORT)) == _REPORT


def test_write_then_load_round_trip(tmp_path: Path) -> None:
    """A report written to disk loads back identically, at a model-named path."""
    path = write_report(_REPORT, tmp_path)

    assert path.parent == tmp_path
    assert "gemma4-12b" in path.name
    assert load_report(path) == _REPORT


def test_report_from_json_rejects_non_json() -> None:
    """A non-JSON payload raises a report error rather than propagating raw."""
    with pytest.raises(BenchmarkReportError):
        _ = report_from_json("not json")


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        '{"model_id": "m", "host": "h", "captured_at": "2026-06-19T12:00:00+00:00"}',
        '{"model_id": 1, "host": "h", "captured_at": "2026-06-19T12:00:00+00:00", "runs": []}',
        '{"model_id": "m", "host": "h", "captured_at": "not-a-date", "runs": []}',
    ],
)
def test_report_from_json_rejects_malformed(payload: str) -> None:
    """Missing fields, wrong types, and bad timestamps are rejected."""
    with pytest.raises(BenchmarkReportError):
        _ = report_from_json(payload)


@pytest.mark.parametrize(
    "runs",
    [
        ["not-a-dict"],
        [
            {
                "query": "q",
                "tool_calls": "x",
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 1,
                "model_latency_ms": 1,
            }
        ],
        [
            {
                "query": "q",
                "tool_calls": [],
                "input_tokens": "x",
                "output_tokens": 1,
                "total_tokens": 1,
                "model_latency_ms": 1,
            }
        ],
        [
            {
                "query": "q",
                "tool_calls": [{"name": "t", "duration_ms": "x", "succeeded": True}],
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 1,
                "model_latency_ms": 1,
            }
        ],
        [
            {
                "query": "q",
                "tool_calls": [{"name": "t", "duration_ms": 1.0, "succeeded": "yes"}],
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 1,
                "model_latency_ms": 1,
            }
        ],
    ],
)
def test_report_from_json_rejects_malformed_runs(runs: list[object]) -> None:
    """Wrong types inside runs and tool calls are rejected, not silently coerced."""
    payload = json.dumps(
        {"model_id": "m", "host": "h", "captured_at": "2026-06-19T12:00:00+00:00", "runs": runs}
    )
    with pytest.raises(BenchmarkReportError):
        _ = report_from_json(payload)


def test_format_report_markdown_renders_a_table() -> None:
    """The markdown rendering carries the headline cost, latency, and routing."""
    assert format_report_markdown(_REPORT) == (
        "## Benchmark: gemma4:12b\n"
        "\n"
        "_2 queries, captured 2026-06-19T12:00:00+00:00_\n"
        "\n"
        "| Metric | Value |\n"
        "| --- | --- |\n"
        "| Total tokens | 360 |\n"
        "| Mean tokens/run | 180 |\n"
        "| Mean latency | 300 ms |\n"
        "| p50 / p95 latency | 200 / 400 ms |\n"
        "| Tool calls | 3 (1 failed) |\n"
        "\n"
        "Tool breakdown: `get_forecast` x2, `get_air_quality` x1"
    )
