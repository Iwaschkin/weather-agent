"""Compare two benchmark reports metric by metric.

Turns two :class:`~weather_agent.benchmark.BenchmarkReport` runs (for example the
same query set on two models, or before and after a prompt change) into a flat
list of :class:`MetricDelta` rows covering cost, latency, and per-tool routing,
then renders them as a readable table. Pure: no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weather_agent.benchmark import BenchmarkReport, BenchmarkSummary


@dataclass(frozen=True, slots=True)
class MetricDelta:
    """One metric's baseline and candidate values.

    Attributes:
        name: The metric label.
        baseline: The baseline report's value.
        candidate: The candidate report's value.
    """

    name: str
    baseline: float
    candidate: float

    @property
    def delta(self) -> float:
        """The candidate value minus the baseline value."""
        return self.candidate - self.baseline


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    """Two benchmark runs compared metric by metric.

    Attributes:
        baseline_model: The baseline report's model id.
        candidate_model: The candidate report's model id.
        metrics: One :class:`MetricDelta` per compared metric.
    """

    baseline_model: str
    candidate_model: str
    metrics: tuple[MetricDelta, ...]


def compare_reports(baseline: BenchmarkReport, candidate: BenchmarkReport) -> BenchmarkComparison:
    """Compare two reports across cost, latency, and per-tool routing.

    Args:
        baseline: The reference report.
        candidate: The report to measure against the baseline.

    Returns:
        A comparison whose metrics cover the scalar summary figures followed by
        one row per tool seen in either report (ordered by tool name).
    """
    base = baseline.summary
    cand = candidate.summary
    scalar = [
        MetricDelta(name=name, baseline=base_value, candidate=cand_value)
        for name, base_value, cand_value in _scalar_metrics(base, cand)
    ]
    base_counts = dict(base.tool_counts)
    cand_counts = dict(cand.tool_counts)
    per_tool = [
        MetricDelta(
            name=f"tool {tool}",
            baseline=float(base_counts.get(tool, 0)),
            candidate=float(cand_counts.get(tool, 0)),
        )
        for tool in sorted(set(base_counts) | set(cand_counts))
    ]
    return BenchmarkComparison(
        baseline_model=baseline.model_id,
        candidate_model=candidate.model_id,
        metrics=tuple(scalar + per_tool),
    )


def _scalar_metrics(
    base: BenchmarkSummary, cand: BenchmarkSummary
) -> tuple[tuple[str, float, float], ...]:
    return (
        ("total tokens", float(base.total_tokens), float(cand.total_tokens)),
        ("mean tokens/run", base.mean_total_tokens, cand.mean_total_tokens),
        ("mean latency ms", base.mean_latency_ms, cand.mean_latency_ms),
        ("p50 latency ms", base.p50_latency_ms, cand.p50_latency_ms),
        ("p95 latency ms", base.p95_latency_ms, cand.p95_latency_ms),
        ("tool calls", float(base.total_tool_calls), float(cand.total_tool_calls)),
        ("failed tool calls", float(base.failed_tool_calls), float(cand.failed_tool_calls)),
    )


def format_comparison(comparison: BenchmarkComparison) -> str:
    """Render a comparison as a markdown table with a signed delta column.

    Args:
        comparison: The comparison to render.

    Returns:
        A multi-line table: one row per metric with baseline, candidate, delta.
    """
    lines = [
        f"benchmark comparison: {comparison.baseline_model} -> {comparison.candidate_model}",
        "",
        "| Metric | baseline | candidate | delta |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {metric.name} | {metric.baseline:.0f} | {metric.candidate:.0f} | {metric.delta:+.0f} |"
        for metric in comparison.metrics
    )
    return "\n".join(lines)
