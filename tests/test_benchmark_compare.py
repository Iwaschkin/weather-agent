"""Tests for comparing two benchmark reports."""

from datetime import UTC, datetime

from weather_agent.benchmark import BenchmarkReport, RunStat
from weather_agent.benchmark_compare import compare_reports, format_comparison
from weather_agent.observability import ToolCall


def _report(model_id: str, *, tokens: int, latency_ms: int, tool: str) -> BenchmarkReport:
    """Build a one-run report with a single successful tool call."""
    return BenchmarkReport(
        model_id=model_id,
        host="http://localhost:11434",
        captured_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
        runs=(
            RunStat(
                query="q",
                tool_calls=(ToolCall(name=tool, duration_ms=1.0, succeeded=True),),
                input_tokens=tokens // 2,
                output_tokens=tokens - tokens // 2,
                total_tokens=tokens,
                model_latency_ms=latency_ms,
            ),
        ),
    )


def test_compare_reports_records_named_deltas() -> None:
    """Scalar metrics and per-tool counts become baseline/candidate deltas."""
    baseline = _report("gemma4:12b", tokens=200, latency_ms=400, tool="get_forecast")
    candidate = _report("qwen3:30b", tokens=120, latency_ms=250, tool="get_air_quality")

    comparison = compare_reports(baseline, candidate)
    deltas = {metric.name: metric.delta for metric in comparison.metrics}

    assert comparison.baseline_model == "gemma4:12b"
    assert comparison.candidate_model == "qwen3:30b"
    assert deltas["total tokens"] == -80.0
    assert deltas["mean latency ms"] == -150.0
    # A tool used only by the baseline shows a drop; one only by the candidate, a gain.
    assert deltas["tool get_forecast"] == -1.0
    assert deltas["tool get_air_quality"] == 1.0


def test_format_comparison_renders_signed_deltas() -> None:
    """The rendered table headers the models and signs each delta."""
    baseline = _report("gemma4:12b", tokens=200, latency_ms=400, tool="get_forecast")
    candidate = _report("qwen3:30b", tokens=120, latency_ms=250, tool="get_forecast")

    report = format_comparison(compare_reports(baseline, candidate))

    assert "benchmark comparison: gemma4:12b -> qwen3:30b" in report
    assert "| total tokens | 200 | 120 | -80 |" in report
