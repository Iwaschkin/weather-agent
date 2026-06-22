"""Dated, jurisdiction-scoped operational policy for the flyability engine.

Some flight constraints are regulatory or operational rather than meteorological -
notably whether night flight is permitted - and the rules change over time. Holding
them as dated policy values rather than hardcoded verdicts keeps the legal
assumptions explicit and updatable, and stops the engine asserting a universal
legal rule that is really jurisdiction- and date-specific.
"""

from __future__ import annotations

from dataclasses import dataclass

from weather_agent.models import Verdict


@dataclass(frozen=True, slots=True)
class NightPolicy:
    """How night-time hours are treated, as dated, jurisdiction-scoped policy.

    Attributes:
        jurisdiction: The regulatory scope the policy reflects.
        effective_date: ISO date of the rules this policy encodes.
        verdict: The verdict a night-time hour receives under this policy.
        note: The operational requirement / reason shown to the operator.
        source: Human reference for the rule.
    """

    jurisdiction: str
    effective_date: str
    verdict: Verdict
    note: str
    source: str = ""


# UK Open Category night rules effective 2026-01-01: night flight is permitted with
# a green flashing light and maintained visual line of sight, so a night hour is
# MARGINAL (flyable with specific requirements), not a blanket NO-FLY. Before this
# change the engine asserted a universal night ban, which is no longer accurate.
UK_OPEN_CATEGORY_NIGHT = NightPolicy(
    jurisdiction="UK Open Category",
    effective_date="2026-01-01",
    verdict=Verdict.MARGINAL,
    note=(
        "night flight (UK Open Category, from 2026-01-01): permitted with a green "
        "flashing light and maintained visual line of sight; night competency assumed"
    ),
    source="CAA - Flying at night in the Open Category",
)

DEFAULT_NIGHT_POLICY = UK_OPEN_CATEGORY_NIGHT
