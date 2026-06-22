"""UI components for the benchmark panel."""

from __future__ import annotations

import reflex as rx

from weather_dashboard.benchmark_state import BenchmarkState


def _metric_table() -> rx.Component:
    return rx.table.root(
        rx.table.body(
            rx.foreach(
                BenchmarkState.metric_rows,
                lambda row: rx.table.row(
                    rx.table.row_header_cell(row["label"]),
                    rx.table.cell(row["value"]),
                ),
            )
        ),
        variant="surface",
        width="100%",
    )


def _tool_table() -> rx.Component:
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("Tool"),
                rx.table.column_header_cell("Calls"),
            )
        ),
        rx.table.body(
            rx.foreach(
                BenchmarkState.tool_rows,
                lambda row: rx.table.row(
                    rx.table.row_header_cell(row["name"]),
                    rx.table.cell(row["count"]),
                ),
            )
        ),
        variant="surface",
        width="100%",
    )


def _results() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading(BenchmarkState.model_id, size="5"),
            rx.spacer(),
            rx.text(BenchmarkState.captured_at, color_scheme="gray", size="2"),
            width="100%",
            align="center",
        ),
        _metric_table(),
        rx.cond(
            BenchmarkState.tool_rows.length() > 0,
            rx.vstack(
                rx.heading("Tool routing", size="4"),
                _tool_table(),
                spacing="2",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
        class_name="fade-in",
    )


def benchmark_index() -> rx.Component:
    """The benchmark panel page."""
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.heading("Benchmark", size="7"),
                rx.spacer(),
                rx.link("Forecast", href="/"),
                width="100%",
                align="center",
            ),
            rx.text(
                "Measure the local model's cost and tool routing over a fixed query set. "
                "Runs the agent for several queries, so it needs a running Ollama server.",
                color_scheme="gray",
            ),
            rx.button(
                "Run benchmark",
                on_click=BenchmarkState.run,
                disabled=BenchmarkState.running,
            ),
            rx.cond(
                BenchmarkState.error != "",
                rx.callout(BenchmarkState.error, icon="info", color_scheme="red"),
            ),
            rx.cond(
                BenchmarkState.running,
                rx.center(
                    rx.vstack(
                        rx.spinner(size="3"),
                        rx.text("Running benchmark…", color_scheme="gray", size="2"),
                        align="center",
                    ),
                    padding="3em",
                    width="100%",
                ),
            ),
            rx.cond(BenchmarkState.has_result, _results()),
            spacing="4",
            width="100%",
        ),
        size="3",
        padding_y="2em",
    )
