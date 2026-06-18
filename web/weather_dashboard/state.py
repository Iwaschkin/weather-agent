"""Dashboard state: location/horizon inputs and the forecast + AI report flow.

The single background event handler (`run`) does the slow work off the event loop
via `asyncio.to_thread` (the core client is synchronous), filling the charts from
the structured assessment first and then streaming an LLM report per drone. State
holds only plain values; the structured `FleetMember` objects stay local to the
handler and feed the report generator directly.
"""

from __future__ import annotations

import asyncio

import httpx
import reflex as rx

from weather_agent.parsing import ExternalDataError
from weather_agent.reporting_llm import ReportError, generate_drone_report
from weather_agent.weather import assess_fleet
from weather_dashboard.transform import DroneView, fleet_views

_REPORT_UNAVAILABLE = "AI analysis unavailable — is Ollama running with the model pulled?"


class DashboardState(rx.State):
    """All UI state for the drone-flyability dashboard."""

    query: str = ""
    days: int = 5
    metric: str = "wind"
    loading: bool = False
    generating: bool = False
    error: str = ""
    place_label: str = ""
    drones: list[DroneView] = []
    reports: dict[str, str] = {}

    def set_query(self, value: str) -> None:
        """Set the location query text."""
        self.query = value

    def set_metric(self, value: str | list[str]) -> None:
        """Set the charted metric (segmented control passes str or list[str])."""
        self.metric = value if isinstance(value, str) else next(iter(value), "wind")

    def set_days(self, value: str) -> None:
        """Set the forecast horizon from the day selector (string -> int)."""
        self.days = int(value)

    @rx.event(background=True)
    async def run(self) -> None:
        """Resolve the location, draw the fleet forecast, then stream AI reports."""
        query = self.query.strip()
        if not query:
            async with self:
                self.error = "Enter a location first."
            return
        async with self:
            self.loading = True
            self.error = ""
            self.drones = []
            self.reports = {}
        days = self.days

        try:
            assessment = await asyncio.to_thread(assess_fleet, query, days)
        except (httpx.HTTPError, ExternalDataError) as error:
            async with self:
                self.error = f"Lookup failed: {error}"
                self.loading = False
            return

        if assessment is None:
            async with self:
                self.error = f"Couldn't find '{query}'."
                self.loading = False
            return

        async with self:
            self.place_label = assessment.place_label
            self.drones = fleet_views(assessment)
            self.loading = False
            self.generating = True

        for member in assessment.members:
            try:
                prose = await asyncio.to_thread(generate_drone_report, member)
            except (httpx.HTTPError, ReportError):
                prose = _REPORT_UNAVAILABLE
            async with self:
                self.reports = {**self.reports, member.profile.name: prose}

        async with self:
            self.generating = False
