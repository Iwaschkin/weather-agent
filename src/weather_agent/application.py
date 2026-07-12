"""Application-owned response types for deterministic drone decisions.

The model may choose a tool and produce commentary, but it never owns the drone
decision shown to a user. A request-scoped :class:`DecisionCapture` carries the
typed assessment from a Strands tool back to the CLI without global state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from weather_agent.results import render

if TYPE_CHECKING:
    from weather_agent.models import FleetAssessment
    from weather_agent.results import LookupOutcome

DECISION_CAPTURE_KEY = "weather_agent_decision_capture"


@dataclass(frozen=True, slots=True)
class DroneResponse:
    """A deterministic drone outcome and its typed assessment when successful."""

    outcome: LookupOutcome
    assessment: FleetAssessment | None = None

    @property
    def text(self) -> str:
        """Render the authoritative application-owned text."""
        return render(self.outcome)


@dataclass(slots=True)
class DecisionCapture:
    """Mutable request-local slot populated only by drone tool calls."""

    response: DroneResponse | None = None

    def record(self, response: DroneResponse) -> None:
        """Retain the most recent drone decision within this invocation only."""
        self.response = response
