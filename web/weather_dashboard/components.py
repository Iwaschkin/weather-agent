"""UI components for the drone-flyability dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

import reflex as rx

from weather_dashboard.state import DashboardState

if TYPE_CHECKING:
    from weather_dashboard.transform import DroneView

_DAY_OPTIONS = [str(day) for day in range(1, 8)]
_RIBBON_TRANSITION = {"transition": "background 0.3s ease"}
_CARD_TRANSITION = {"transition": "transform 0.2s ease, box-shadow 0.2s ease"}


def _verdict_color(verdict: rx.Var[str]) -> rx.Var[str]:
    return rx.match(
        verdict,
        ("good", rx.color("grass", 9)),
        ("marginal", rx.color("amber", 9)),
        ("unknown", rx.color("gray", 9)),
        ("no_fly", rx.color("tomato", 9)),
        rx.color("gray", 6),
    )


def _controls() -> rx.Component:
    return rx.card(
        rx.flex(
            rx.input(
                placeholder="Location, e.g. Congleton UK",
                value=DashboardState.query,
                on_change=DashboardState.set_query,
                width="18em",
            ),
            rx.select(
                _DAY_OPTIONS,
                value=DashboardState.days.to_string(),
                on_change=DashboardState.set_days,
                width="5em",
            ),
            rx.segmented_control.root(
                rx.segmented_control.item("Wind", value="wind"),
                rx.segmented_control.item("Precip", value="precip"),
                rx.segmented_control.item("Temp", value="temp"),
                rx.segmented_control.item("Visibility", value="vis"),
                value=DashboardState.metric,
                on_change=DashboardState.set_metric,
            ),
            rx.button(
                "Get forecast",
                on_click=DashboardState.run,
                disabled=DashboardState.loading,
            ),
            gap="3",
            align="center",
            wrap="wrap",
        ),
    )


def _metric_label() -> rx.Var[str]:
    return rx.match(
        DashboardState.metric,
        ("wind", "Wind (m/s)"),
        ("precip", "Precipitation probability (%)"),
        ("temp", "Temperature (C)"),
        ("vis", "Visibility (km)"),
        "Metric",
    )


def _chart(drone: DroneView) -> rx.Component:
    return rx.vstack(
        rx.text(
            _metric_label(),
            " · Forecast times: ",
            drone.timezone,
            size="1",
            color_scheme="gray",
        ),
        rx.recharts.area_chart(
            rx.recharts.area(
                data_key=DashboardState.metric,
                stroke=rx.color("accent", 9),
                fill=rx.color("accent", 5),
                type_="monotone",
            ),
            rx.cond(
                DashboardState.metric == "wind",
                rx.recharts.reference_line(
                    y=drone.limit.to_string(),
                    stroke=rx.color("tomato", 9),
                    stroke_dasharray="4 4",
                ),
                rx.fragment(),
            ),
            rx.recharts.x_axis(data_key="time", interval=11, min_tick_gap=20),
            rx.recharts.y_axis(width=36),
            rx.recharts.cartesian_grid(stroke_dasharray="3 3", vertical=False),
            rx.recharts.graphing_tooltip(),
            data=drone.rows,
            height=180,
            width="100%",
        ),
        spacing="1",
        width="100%",
    )


def _ribbon(drone: DroneView) -> rx.Component:
    return rx.hstack(
        rx.foreach(
            drone.verdicts,
            lambda verdict: rx.box(
                height="10px",
                flex="1",
                border_radius="2px",
                background=_verdict_color(verdict),
                style=_RIBBON_TRANSITION,
            ),
        ),
        spacing="1",
        width="100%",
    )


def _report(drone: DroneView) -> rx.Component:
    return rx.box(
        rx.cond(
            DashboardState.reports.contains(drone.name),
            rx.vstack(
                rx.text("Generated commentary", weight="bold", size="2"),
                rx.text(DashboardState.reports[drone.name], size="2", class_name="fade-in"),
                spacing="1",
                align="start",
            ),
            rx.cond(
                DashboardState.generating,
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Generating analysis…", color_scheme="gray", size="2"),
                ),
                rx.fragment(),
            ),
        ),
        width="100%",
    )


def _authoritative_report(drone: DroneView) -> rx.Component:
    return rx.callout(
        rx.vstack(
            rx.text("Authoritative deterministic assessment", weight="bold", size="2"),
            rx.text("Configuration: ", drone.configuration, size="1"),
            rx.text("CAA context: ", drone.caa_context, size="1"),
            rx.foreach(
                drone.source_statuses,
                lambda status: rx.text("Source: ", status, size="1"),
            ),
            rx.text("Airspace: ", drone.airspace_status, size="1"),
            rx.text(
                drone.authoritative_report,
                size="1",
                white_space="pre-wrap",
            ),
            rx.callout(
                drone.disclaimer,
                icon="triangle-alert",
                color_scheme="amber",
                size="1",
                width="100%",
            ),
            align="start",
            spacing="2",
        ),
        icon="shield-check",
        color_scheme="gray",
        width="100%",
    )


def _legend() -> rx.Component:
    def swatch(label: str, scale: str) -> rx.Component:
        return rx.hstack(
            rx.box(width="12px", height="12px", border_radius="2px", background=rx.color(scale, 9)),
            rx.text(label, size="1", color_scheme="gray"),
            spacing="1",
            align="center",
        )

    return rx.hstack(
        swatch("Good", "grass"),
        swatch("Marginal", "amber"),
        swatch("Unknown", "gray"),
        swatch("No-fly", "tomato"),
        spacing="4",
    )


def _drone_card(drone: DroneView) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(drone.name, size="4"),
                rx.spacer(),
                rx.badge(
                    drone.best_window,
                    color_scheme=drone.best_window_color,
                    variant="soft",
                ),
                width="100%",
                align="center",
            ),
            rx.text(drone.summary, color_scheme="gray", size="2"),
            _chart(drone),
            _ribbon(drone),
            _authoritative_report(drone),
            _report(drone),
            spacing="3",
            width="100%",
        ),
        width="100%",
        style=_CARD_TRANSITION,
        _hover={"transform": "translateY(-2px)", "box_shadow": "var(--shadow-4)"},
    )


def index() -> rx.Component:
    """The single dashboard page."""
    return rx.container(
        rx.vstack(
            rx.heading("Drone Flyability Forecast", size="7"),
            rx.text(
                "Pick a location and horizon for deterministic per-drone decision support; "
                "generated commentary is optional.",
                color_scheme="gray",
            ),
            _controls(),
            rx.cond(
                DashboardState.error != "",
                rx.callout(DashboardState.error, icon="info", color_scheme="red"),
            ),
            rx.cond(
                DashboardState.place_label != "",
                rx.hstack(
                    rx.heading(DashboardState.place_label, size="5"),
                    rx.spacer(),
                    _legend(),
                    width="100%",
                    align="center",
                ),
            ),
            rx.cond(
                DashboardState.loading,
                rx.center(rx.spinner(size="3"), padding="4em", width="100%"),
            ),
            rx.foreach(DashboardState.drones, _drone_card),
            spacing="4",
            width="100%",
        ),
        size="3",
        padding_y="2em",
    )
