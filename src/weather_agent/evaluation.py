"""Deterministic evaluation of flyability explanations against the rules engine.

The agent is a "symbolic decides, LLM explains" system: the rules engine owns the
verdict (it is the decision ground truth), and the model produces the prose. This
module checks the *explanation* against that ground truth without needing an LLM,
so it runs in plain tests and can also act as a runtime guardrail.

:func:`check_hour_explanation` is a faithfulness/authority verifier: it confirms a
free-text explanation cites the hour's real limiting factors and never under-states
the risk (claims a less restrictive verdict than the engine reached). It is a
deterministic first cut of the research's "score the explanation, not the decision"
recommendation; a richer LLM-as-judge faithfulness score can be layered on top, but
the safety-critical check - "did the prose downgrade a NO-FLY?" - is rule-based here
on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from weather_agent.models import Verdict

if TYPE_CHECKING:
    from weather_agent.models import HourAssessment

# Keywords that show a gate's metric is actually referenced in the prose. A
# limiting metric whose keywords are all absent is an ungrounded omission.
_METRIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "wind_gust": ("gust", "wind"),
    "precip_probability": ("precip", "rain"),
    "precipitation": ("precip", "rain"),
    "temperature": ("temperature", "cold", "hot"),
    "feels_like": ("feels", "cold"),
    "freezing_level_agl": ("icing", "freezing"),
    "visibility": ("visibility",),
    "daylight": ("night", "daylight"),
    "cape": ("storm", "cape", "thunder"),
    "low_cloud": ("cloud",),
    "kp": ("geomagnetic", "kp", "gps", "compass"),
}

# Affirmative "go" phrases that would under-state a restrictive (non-GOOD) verdict.
_GO_PHRASES = (
    "good to fly",
    "safe to fly",
    "clear to fly",
    "fine to fly",
    "ok to fly",
    "good conditions",
)

# Restrictive phrasing whose presence shows the prose did convey the caution.
_RESTRICTIVE_PHRASES = (
    "no-fly",
    "no fly",
    "do not fly",
    "don't fly",
    "not safe",
    "unsafe",
    "marginal",
    "caution",
    "grounded",
    "avoid flying",
)


@dataclass(frozen=True, slots=True)
class GroundingResult:
    """The outcome of checking an explanation against an hour's verdict.

    Attributes:
        grounded: True when the explanation neither under-states the risk nor omits
            a limiting factor.
        understates_risk: True when the verdict is restrictive but the prose reads
            as a "go" without any cautionary wording (the safety-critical failure).
        missing_factors: Metric keys that drove the verdict but are not mentioned.
    """

    grounded: bool
    understates_risk: bool
    missing_factors: tuple[str, ...]


def check_hour_explanation(explanation: str, hour: HourAssessment) -> GroundingResult:
    """Verify a free-text explanation is grounded in an hour's structured verdict.

    Args:
        explanation: The model's prose explaining the hour.
        hour: The engine's assessment for that hour (the ground truth).

    Returns:
        A :class:`GroundingResult` flagging under-stated risk and any limiting
        factor the explanation failed to mention.
    """
    text = explanation.lower()
    missing = tuple(
        reading.metric
        for reading in hour.readings
        if reading.limiting
        and not any(keyword in text for keyword in _METRIC_KEYWORDS.get(reading.metric, ()))
    )
    understates = (
        hour.verdict is not Verdict.GOOD
        and any(phrase in text for phrase in _GO_PHRASES)
        and not any(phrase in text for phrase in _RESTRICTIVE_PHRASES)
    )
    return GroundingResult(
        grounded=not understates and not missing,
        understates_risk=understates,
        missing_factors=missing,
    )
