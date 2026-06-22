"""Reflex app entry point for the drone-flyability dashboard.

Reflex resolves the app from ``weather_dashboard.weather_dashboard:app`` (see
``rxconfig.py``). The theme is configured there via ``RadixThemesPlugin``; this
module wires the global stylesheet and the single page. All logic lives in
:mod:`weather_dashboard.state` and the core ``weather_agent`` package.
"""

import reflex as rx

from weather_dashboard.benchmark_components import benchmark_index
from weather_dashboard.components import index

app = rx.App(stylesheets=["styles.css"])
app.add_page(index, title="Drone Flyability Forecast")
app.add_page(benchmark_index, route="/benchmark", title="Benchmark")
