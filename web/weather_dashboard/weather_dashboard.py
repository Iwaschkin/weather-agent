"""Reflex app entry point for the drone-flyability dashboard.

Reflex resolves the app from ``weather_dashboard.weather_dashboard:app`` (see
``rxconfig.py``). This module wires the theme, global stylesheet, and the single
page; all logic lives in :mod:`weather_dashboard.state` and the core
``weather_agent`` package.
"""

import reflex as rx

from weather_dashboard.components import index

app = rx.App(
    theme=rx.theme(appearance="dark", accent_color="cyan", radius="large", scaling="100%"),
    stylesheets=["styles.css"],
)
app.add_page(index, title="Drone Flyability Forecast")
