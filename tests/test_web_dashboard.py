"""Behavior tests for the typed Reflex dashboard boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
import pytest
import weather_dashboard.state as state_module
from weather_dashboard.components import index
from weather_dashboard.state import DashboardState
from weather_dashboard.transform import fleet_views

from weather_agent.caa import caa_guidance
from weather_agent.drone import DRONE_PROFILES
from weather_agent.models import (
    Airspace,
    DroneAssessment,
    FleetAssessment,
    FleetMember,
    FlightWindow,
    GateReading,
    HourAssessment,
    SiteBriefing,
    SourceState,
    SourceStatus,
    TimeContext,
    Verdict,
)
from weather_agent.reporting_llm import GeneratedCommentary, ReportError

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from types import TracebackType

_PROFILE = DRONE_PROFILES[0]
_TIME_CONTEXT = TimeContext("Europe/London", "BST", 3600)
_HOUR = datetime(2026, 7, 12, 9, tzinfo=UTC).astimezone(ZoneInfo("Europe/London"))


def _fleet(
    place: str = "Congleton, England, United Kingdom",
    verdict: Verdict = Verdict.GOOD,
) -> FleetAssessment:
    reading = GateReading(
        metric="wind_gust",
        band=verdict,
        reason="wind sample incomplete" if verdict is Verdict.UNKNOWN else "",
        value=None if verdict is Verdict.UNKNOWN else 4.2,
        unit="m/s",
        threshold=8.0,
        limiting=verdict is not Verdict.GOOD,
    )
    hour = HourAssessment(
        time=_HOUR,
        verdict=verdict,
        limiting_factors=(reading.reason,) if reading.reason else (),
        governing_wind_ms=reading.value,
        readings=(reading,),
    )
    window = None if verdict is not Verdict.GOOD else FlightWindow(_HOUR, _HOUR, 1)
    assessment = DroneAssessment(
        drone_name=_PROFILE.name,
        place_label=place,
        hours=(hour,),
        best_window=window,
        time_context=_TIME_CONTEXT,
    )
    member = FleetMember(_PROFILE, assessment, caa_guidance(_PROFILE))
    briefing = SiteBriefing(
        airspace=(Airspace("MANCHESTER CTR", "CTR", "D", "GND"),),
        source_statuses=(
            SourceStatus("NOAA Kp", SourceState.PARTIAL, "coverage ends at 12:00 UTC"),
            SourceStatus("METAR", SourceState.AVAILABLE, "EGCC observation"),
        ),
    )
    return FleetAssessment(place, (member,), briefing)


def _patch_state_context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def enter(state: DashboardState) -> DashboardState:
        return state

    async def exit_context(
        _state: DashboardState,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    async def immediate_to_thread(function: object, *args: object) -> object:
        if not callable(function):
            message = "background target must be callable"
            raise TypeError(message)
        return function(*args)

    monkeypatch.setattr(DashboardState, "__aenter__", enter)
    monkeypatch.setattr(DashboardState, "__aexit__", exit_context)
    monkeypatch.setattr(state_module.asyncio, "to_thread", immediate_to_thread)


async def _invoke_run(state: DashboardState) -> None:
    handler = DashboardState.__dict__["run"]
    await handler.fn(state)


def _run(coroutine: Coroutine[object, object, None]) -> None:
    asyncio.run(coroutine)


def test_fleet_views_preserve_deterministic_safety_context() -> None:
    """The chart view retains time, source, CAA, airspace, and disclaimer context."""
    view = fleet_views(_fleet())[0]

    assert view.best_window_available is True
    assert view.best_window_color == "grass"
    assert view.timezone == "Europe/London"
    assert view.rows == [
        {"time": "Sun 10:00 BST", "wind": 4.2, "precip": None, "temp": None, "vis": None}
    ]
    assert view.source_statuses == [
        "NOAA Kp: partial - coverage ends at 12:00 UTC",
        "METAR: available - EGCC observation",
    ]
    assert "NOTAMs" in view.airspace_status
    assert "reviewed 2026-07-12" in view.caa_context
    assert view.disclaimer in view.authoritative_report
    assert "Official sources:" in view.authoritative_report


def test_no_window_view_is_neutral_and_unknown_is_visible() -> None:
    """An incomplete outlook cannot acquire the dashboard's success styling."""
    view = fleet_views(_fleet(verdict=Verdict.UNKNOWN))[0]

    assert view.best_window == "No good-to-fly window"
    assert view.best_window_available is False
    assert view.best_window_color == "gray"
    assert view.verdicts == ["unknown"]
    assert "1 unknown" in view.summary


def test_compiled_page_contains_application_owned_safety_sections() -> None:
    """The component tree includes deterministic content independently of Ollama."""
    page = str(index())

    assert "Authoritative deterministic assessment" in page
    assert "CAA context:" in page
    assert "Airspace:" in page
    assert "Generated commentary" in page
    assert "generated commentary is optional" in page


def test_input_events_reject_unsupported_days_and_metrics() -> None:
    """Browser event values cannot create unsupported dashboard state."""
    state = DashboardState()

    state.set_days("many")
    assert state.days == 5
    assert "between 1 and 7" in state.error
    state.set_days("8")
    assert state.days == 5
    state.set_days("3")
    assert state.days == 3

    state.set_metric("pressure")
    assert state.metric == "wind"
    assert "Choose wind" in state.error
    state.set_metric([])
    assert state.metric == "wind"
    state.set_metric("temp")
    assert state.metric == "temp"


def test_empty_query_settles_without_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty request is invalidated and never leaves a lifecycle flag set."""
    _patch_state_context(monkeypatch)
    state = DashboardState()

    _run(_invoke_run(state))

    assert state.error == "Enter a location first."
    assert state.loading is False
    assert state.generating is False
    assert state.request_generation == 1


def test_success_publishes_result_before_optional_commentary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful run retains deterministic output and validated commentary."""
    _patch_state_context(monkeypatch)
    assessment = _fleet()

    def assess(_query: str, _days: int) -> FleetAssessment:
        return assessment

    def report(_member: FleetMember) -> GeneratedCommentary:
        return GeneratedCommentary(
            "Measured wind remained below the profile limit.",
            "Check NOTAMs.",
        )

    monkeypatch.setattr(state_module, "assess_fleet", assess)
    monkeypatch.setattr(state_module, "generate_drone_report", report)
    state = DashboardState()
    state.query = "Congleton UK"

    _run(_invoke_run(state))

    assert state.place_label == assessment.place_label
    assert len(state.drones) == 1
    assert state.reports[_PROFILE.name].startswith("Measured wind")
    assert state.loading is False
    assert state.generating is False


def test_commentary_failure_keeps_complete_deterministic_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama failure omits only optional prose and settles generation state."""
    _patch_state_context(monkeypatch)
    assessment = _fleet()

    def assess(_query: str, _days: int) -> FleetAssessment:
        return assessment

    def report(_member: FleetMember) -> GeneratedCommentary:
        message = "invalid JSON"
        raise ReportError(message)

    monkeypatch.setattr(state_module, "assess_fleet", assess)
    monkeypatch.setattr(state_module, "generate_drone_report", report)
    state = DashboardState()
    state.query = "Congleton UK"

    _run(_invoke_run(state))

    assert len(state.drones) == 1
    assert state.reports == {}
    assert state.error == ""
    assert state.loading is False
    assert state.generating is False


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (httpx.ConnectError("offline"), "Lookup failed: offline"),
        (state_module.UnsupportedJurisdictionError("Great Britain only"), "Great Britain only"),
    ],
)
def test_expected_lookup_failure_settles_state(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    message: str,
) -> None:
    """Typed lookup failures become UI errors without a stuck spinner."""
    _patch_state_context(monkeypatch)

    def assess(_query: str, _days: int) -> FleetAssessment:
        raise failure

    monkeypatch.setattr(state_module, "assess_fleet", assess)
    state = DashboardState()
    state.query = "Somewhere"

    _run(_invoke_run(state))

    assert state.error == message
    assert state.loading is False
    assert state.generating is False


def test_unexpected_failure_propagates_after_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unexpected defects remain observable while lifecycle cleanup still runs."""
    _patch_state_context(monkeypatch)

    def assess(_query: str, _days: int) -> FleetAssessment:
        message = "unexpected defect"
        raise RuntimeError(message)

    monkeypatch.setattr(state_module, "assess_fleet", assess)
    state = DashboardState()
    state.query = "Somewhere"

    with pytest.raises(RuntimeError, match="unexpected defect"):
        _run(_invoke_run(state))

    assert state.loading is False
    assert state.generating is False


def test_cancellation_cleans_up_active_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancellation propagates after the active request's flags are settled."""
    _patch_state_context(monkeypatch)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_to_thread(
        _function: object,
        *_args: object,
    ) -> FleetAssessment:
        started.set()
        await release.wait()
        return _fleet()

    monkeypatch.setattr(state_module.asyncio, "to_thread", blocked_to_thread)
    state = DashboardState()
    state.query = "Congleton UK"

    async def scenario() -> None:
        task = asyncio.create_task(_invoke_run(state))
        await started.wait()
        assert state.loading is True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _run(scenario())

    assert state.loading is False
    assert state.generating is False


class _OverlapHarness:
    """Control two overlapping state runs without sleeping or real threads."""

    def __init__(self) -> None:
        self.first = _fleet(place="First place")
        self.second = _fleet(place="Second place")
        self.first_report_started = asyncio.Event()
        self.release_first_report = asyncio.Event()
        self.assess_call: Callable[[str, int], FleetAssessment] = self._assess
        self.report_call: Callable[[FleetMember], GeneratedCommentary] = self._report

    @staticmethod
    def _assess(_query: str, _days: int) -> FleetAssessment:
        message = "to_thread should intercept this function"
        raise AssertionError(message)

    @staticmethod
    def _report(_member: FleetMember) -> GeneratedCommentary:
        message = "to_thread should intercept this function"
        raise AssertionError(message)

    async def to_thread(
        self,
        function: object,
        *args: object,
    ) -> FleetAssessment | GeneratedCommentary:
        if function is self.assess_call:
            query = args[0]
            assert isinstance(query, str)
            return self.first if query == "First" else self.second
        if function is self.report_call:
            member = args[0]
            assert isinstance(member, FleetMember)
            if member.assessment.place_label == "First place":
                self.first_report_started.set()
                await self.release_first_report.wait()
                return GeneratedCommentary("First commentary.", "First note.")
            return GeneratedCommentary("Second commentary.", "Second note.")
        message = "unexpected background function"
        raise AssertionError(message)

    async def run(self, state: DashboardState) -> None:
        """Run the second request while the first commentary call is paused."""
        state.query = "First"
        first_task = asyncio.create_task(_invoke_run(state))
        await self.first_report_started.wait()
        state.query = "Second"
        second_task = asyncio.create_task(_invoke_run(state))
        await second_task
        assert state.place_label == "Second place"
        assert state.reports[_PROFILE.name].startswith("Second commentary")
        self.release_first_report.set()
        await first_task


def test_stale_generation_cannot_overwrite_newer_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delayed first report cannot mutate the second request's result or flags."""
    _patch_state_context(monkeypatch)
    harness = _OverlapHarness()
    monkeypatch.setattr(state_module, "assess_fleet", harness.assess_call)
    monkeypatch.setattr(state_module, "generate_drone_report", harness.report_call)
    monkeypatch.setattr(state_module.asyncio, "to_thread", harness.to_thread)
    state = DashboardState()

    _run(harness.run(state))

    assert state.request_generation == 2
    assert state.place_label == "Second place"
    assert state.reports[_PROFILE.name].startswith("Second commentary")
    assert state.loading is False
    assert state.generating is False
