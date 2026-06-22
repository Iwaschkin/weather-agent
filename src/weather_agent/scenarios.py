"""Deterministic scenario checks for the agent's faithfulness and safety.

A small regression harness: each :class:`Scenario` names the terms an answer for a
representative query must contain and the claims it must never make (for example a
no-fly assessment must never read as "safe to fly"). The checks are pure
case-insensitive substring assertions over a rendered answer, so the suite runs in
CI without a live model; ``tests/test_scenarios.py`` wires each scenario to the real
engine with mocked network boundaries and fails the build on any breach.

This covers the deterministic dimensions the review asked for - required content,
forbidden (unsafe) claims, and safety breaches. Live route- and argument-accuracy
need an opt-in model run and are deliberately out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class Scenario:
    """A named expectation set for one representative query's answer.

    Attributes:
        name: Stable identifier for the scenario.
        description: What the scenario exercises.
        required_terms: Substrings the answer must contain (case-insensitive).
        forbidden_terms: Substrings the answer must never contain
            (case-insensitive), typically unsafe reassurances.
    """

    name: str
    description: str
    required_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """The outcome of checking one scenario against an answer.

    Attributes:
        name: The scenario's name.
        missing_terms: Required terms that were absent.
        leaked_terms: Forbidden terms that were present.
    """

    name: str
    missing_terms: tuple[str, ...]
    leaked_terms: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """True when nothing required was missing and nothing forbidden leaked."""
        return not self.missing_terms and not self.leaked_terms


def check_output(scenario: Scenario, output: str) -> ScenarioResult:
    """Check a rendered answer against a scenario's required and forbidden terms.

    Args:
        scenario: The expectation set.
        output: The rendered answer text.

    Returns:
        The result naming any missing required terms and any leaked forbidden terms.
    """
    text = output.lower()
    missing = tuple(term for term in scenario.required_terms if term.lower() not in text)
    leaked = tuple(term for term in scenario.forbidden_terms if term.lower() in text)
    return ScenarioResult(name=scenario.name, missing_terms=missing, leaked_terms=leaked)


def summarize(results: Sequence[ScenarioResult]) -> str:
    """Render a one-line-per-scenario scorecard with a pass/fail header.

    Args:
        results: The scenario results to summarise.

    Returns:
        A multi-line report: a ``passed/total`` header then one line per scenario.
    """
    passed = sum(1 for result in results if result.passed)
    lines = [f"scenarios: {passed}/{len(results)} passed"]
    for result in results:
        if result.passed:
            lines.append(f"  [PASS] {result.name}")
            continue
        problems: list[str] = []
        if result.missing_terms:
            problems.append(f"missing {', '.join(result.missing_terms)}")
        if result.leaked_terms:
            problems.append(f"forbidden {', '.join(result.leaked_terms)}")
        lines.append(f"  [FAIL] {result.name} - {'; '.join(problems)}")
    return "\n".join(lines)
