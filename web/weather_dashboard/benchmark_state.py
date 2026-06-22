"""Dashboard state for the cost / tool-routing benchmark panel.

The single background handler runs the (slow, Ollama-backed) benchmark off the
event loop via ``asyncio.to_thread`` and flattens the resulting summary into plain
table rows for rendering. All benchmark logic lives in the ``weather_agent``
package; this only orchestrates and shapes for display.
"""

from __future__ import annotations

import asyncio

import reflex as rx

from weather_agent.benchmark import BenchmarkSummary, run_benchmark

_BENCHMARK_UNAVAILABLE = "Benchmark failed — is Ollama running with the model pulled?"


def _metric_rows(summary: BenchmarkSummary) -> list[dict[str, str]]:
    """Flatten a summary into label/value rows for the metrics table."""
    return [
        {"label": "Runs", "value": str(summary.runs)},
        {"label": "Total tokens", "value": str(summary.total_tokens)},
        {"label": "Mean tokens/run", "value": f"{summary.mean_total_tokens:.0f}"},
        {"label": "Mean latency", "value": f"{summary.mean_latency_ms:.0f} ms"},
        {
            "label": "p50 / p95 latency",
            "value": f"{summary.p50_latency_ms:.0f} / {summary.p95_latency_ms:.0f} ms",
        },
        {
            "label": "Tool calls",
            "value": f"{summary.total_tool_calls} ({summary.failed_tool_calls} failed)",
        },
    ]


class BenchmarkState(rx.State):
    """UI state for the benchmark panel."""

    running: bool = False
    error: str = ""
    has_result: bool = False
    model_id: str = ""
    captured_at: str = ""
    metric_rows: list[dict[str, str]] = []
    tool_rows: list[dict[str, str]] = []

    @rx.event(background=True)
    async def run(self) -> None:
        """Run the benchmark off the event loop and fill the result tables."""
        async with self:
            self.running = True
            self.error = ""
            self.has_result = False
        try:
            report = await asyncio.to_thread(run_benchmark)
        except Exception as error:  # UI boundary: surface any failure, never crash the loop
            async with self:
                self.error = f"{_BENCHMARK_UNAVAILABLE} ({error})"
                self.running = False
            return
        summary = report.summary
        async with self:
            self.model_id = report.model_id
            self.captured_at = report.captured_at.isoformat()
            self.metric_rows = _metric_rows(summary)
            self.tool_rows = [
                {"name": name, "count": str(count)} for name, count in summary.tool_counts
            ]
            self.has_result = True
            self.running = False
