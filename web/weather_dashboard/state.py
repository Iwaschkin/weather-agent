"""Dashboard state: location/horizon inputs and the forecast + AI report flow.

The single background event handler (`run`) does the slow work off the event loop
via `asyncio.to_thread` (the core client is synchronous), filling the charts from
the structured assessment first and then streaming an LLM report per drone. State
holds only plain values; the structured `FleetMember` objects stay local to the
handler and feed the report generator directly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import reflex as rx

from weather_agent.parsing import ExternalDataError
from weather_agent.reporting_llm import ReportError, generate_drone_report
from weather_agent.weather import UnsupportedJurisdictionError, assess_fleet
from weather_dashboard.transform import DroneView, fleet_views

if TYPE_CHECKING:
    from weather_agent.models import FleetAssessment

_MIN_DAYS = 1
_MAX_DAYS = 7
_METRICS = frozenset({"wind", "precip", "temp", "vis"})


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Immutable input snapshot owned by one dashboard request generation."""

    generation: int
    query: str
    days: int


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
    request_generation: int = 0

    def set_query(self, value: str) -> None:
        """Set the location query text."""
        self.query = value

    def set_metric(self, value: str | list[str]) -> None:
        """Accept only a supported chart metric from the browser event boundary."""
        metric = value if isinstance(value, str) else next(iter(value), "")
        if metric not in _METRICS:
            self.error = "Choose wind, precipitation, temperature, or visibility."
            return
        self.metric = metric

    def set_days(self, value: str) -> None:
        """Validate the browser-provided forecast horizon before storing it."""
        try:
            days = int(value)
        except ValueError:
            self.error = f"Days must be between {_MIN_DAYS} and {_MAX_DAYS}."
            return
        if not _MIN_DAYS <= days <= _MAX_DAYS:
            self.error = f"Days must be between {_MIN_DAYS} and {_MAX_DAYS}."
            return
        self.days = days

    def _owns(self, generation: int) -> bool:
        return self.request_generation == generation

    async def _start_request(self) -> RunRequest | None:
        async with self:
            self.request_generation += 1
            request = RunRequest(self.request_generation, self.query.strip(), self.days)
            self.loading = False
            self.generating = False
            self.error = ""
            self.place_label = ""
            self.drones = []
            self.reports = {}
            if not request.query:
                self.error = "Enter a location first."
                return None
            if not _MIN_DAYS <= request.days <= _MAX_DAYS:
                self.error = f"Days must be between {_MIN_DAYS} and {_MAX_DAYS}."
                return None
            self.loading = True
            return request

    async def _publish_assessment(
        self,
        request: RunRequest,
        assessment: FleetAssessment,
    ) -> bool:
        async with self:
            if not self._owns(request.generation):
                return False
            self.place_label = assessment.place_label
            self.drones = fleet_views(assessment)
            self.loading = False
            self.generating = bool(assessment.members)
            return True

    async def _publish_report(self, generation: int, name: str, report: str) -> bool:
        async with self:
            if not self._owns(generation):
                return False
            self.reports = {**self.reports, name: report}
            return True

    async def _fail(self, generation: int, message: str) -> None:
        async with self:
            if self._owns(generation):
                self.error = message
                self.loading = False
                self.generating = False

    async def _finish(self, generation: int) -> None:
        async with self:
            if self._owns(generation):
                self.loading = False
                self.generating = False

    async def _still_active(self, generation: int) -> bool:
        async with self:
            return self._owns(generation)

    async def _generate_reports(
        self,
        request: RunRequest,
        assessment: FleetAssessment,
    ) -> None:
        for member in assessment.members:
            if not await self._still_active(request.generation):
                return
            try:
                commentary = await asyncio.to_thread(generate_drone_report, member)
            except httpx.HTTPError, ReportError:
                continue
            stored = await self._publish_report(
                request.generation,
                member.profile.name,
                commentary.text,
            )
            if not stored:
                return

    @rx.event(background=True)
    async def run(self) -> None:
        """Publish one request's deterministic result, then optional commentary."""
        request = await self._start_request()
        if request is None:
            return
        try:
            assessment = await asyncio.to_thread(assess_fleet, request.query, request.days)
            if assessment is None:
                await self._fail(request.generation, f"Couldn't find '{request.query}'.")
                return
            if not await self._publish_assessment(request, assessment):
                return
            await self._generate_reports(request, assessment)
        except UnsupportedJurisdictionError as error:
            await self._fail(request.generation, str(error))
        except (httpx.HTTPError, ExternalDataError) as error:
            await self._fail(request.generation, f"Lookup failed: {error}")
        finally:
            await self._finish(request.generation)
