"""Tests for the pure benchmark aggregation and formatting."""

import pytest

from weather_agent.benchmark import (
    BenchmarkSummary,
    RunStat,
    _percentile,
    aggregate_runs,
    format_summary,
)
from weather_agent.observability import ToolCall

_RUNS = (
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
    RunStat(
        query="q3",
        tool_calls=(),
        input_tokens=60,
        output_tokens=30,
        total_tokens=90,
        model_latency_ms=600,
    ),
)

_SUMMARY = BenchmarkSummary(
    runs=3,
    total_tokens=450,
    mean_total_tokens=150.0,
    mean_input_tokens=110.0,
    mean_output_tokens=40.0,
    mean_latency_ms=400.0,
    p50_latency_ms=400.0,
    p95_latency_ms=600.0,
    total_tool_calls=3,
    failed_tool_calls=1,
    tool_counts=(("get_forecast", 2), ("get_air_quality", 1)),
)


@pytest.mark.parametrize(
    ("values", "pct", "expected"),
    [
        ([], 50.0, 0.0),
        ([42.0], 95.0, 42.0),
        ([200.0, 400.0, 600.0], 50.0, 400.0),
        ([200.0, 400.0, 600.0], 95.0, 600.0),
        ([10.0, 20.0, 30.0, 40.0], 50.0, 20.0),
    ],
)
def test_percentile(values: list[float], pct: float, expected: float) -> None:
    """The nearest-rank percentile is order-independent and handles the empty case."""
    assert _percentile(values, pct) == expected


def test_aggregate_runs_computes_totals_means_and_tool_counts() -> None:
    """Runs aggregate into totals, means, latency percentiles, and tool counts."""
    assert aggregate_runs(_RUNS) == _SUMMARY


def test_aggregate_runs_handles_no_runs() -> None:
    """An empty input yields an all-zero summary with no tool counts."""
    summary = aggregate_runs([])

    assert summary.runs == 0
    assert summary.tool_counts == ()


def test_format_summary_renders_a_report() -> None:
    """A non-empty summary renders totals, latency, and the tool breakdown."""
    assert format_summary(_SUMMARY) == (
        "runs: 3\n"
        "tokens: 450 total, 150 mean/run (in 110, out 40)\n"
        "model latency: 400 ms mean, 400 ms p50, 600 ms p95\n"
        "tool calls: 3 total, 1 failed\n"
        "tool breakdown: get_forecast x2, get_air_quality x1"
    )


def test_format_summary_handles_no_runs() -> None:
    """An empty summary renders a plain marker rather than a malformed report."""
    assert format_summary(aggregate_runs([])) == "no runs"


def test_format_summary_omits_breakdown_when_no_tools_called() -> None:
    """A run that called no tools renders without a tool-breakdown line."""
    run = RunStat(
        query="q",
        tool_calls=(),
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        model_latency_ms=100,
    )

    report = format_summary(aggregate_runs([run]))

    assert "tool breakdown" not in report
    assert report.endswith("tool calls: 0 total, 0 failed")
