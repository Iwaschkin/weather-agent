"""Tests for the explanation-grounding verifier and engine consistency.

Two evaluation strands from the numeric-grounding research:
- metamorphic consistency: the rules engine (decision oracle) must respond
  monotonically and predictably as a number crosses a threshold;
- explanation grounding: prose must cite the real limiting factors and never
  under-state a restrictive verdict.
"""

from dataclasses import replace

import pytest

from weather_agent.drone import MINI_5_PRO
from weather_agent.evaluation import check_hour_explanation
from weather_agent.flyability import assess_hour
from weather_agent.models import DroneFlightHour, Verdict

_SEVERITY = {Verdict.GOOD: 0, Verdict.MARGINAL: 1, Verdict.NO_FLY: 2}

_CALM_HOUR = DroneFlightHour(
    time="2026-06-16T12:00",
    temperature_c=18.0,
    apparent_temperature_c=18.0,
    wind_gust_10m_kmh=10.0,
    wind_max_0_500m_kmh=10.0,
    precipitation_mm=0.0,
    precipitation_probability_pct=0.0,
    visibility_m=20000.0,
    cape=0.0,
    freezing_level_agl_m=2500.0,
    is_day=True,
    cloud_cover_low_pct=10.0,
)


def _hour_with_gust(gust_kmh: float) -> DroneFlightHour:
    return replace(_CALM_HOUR, wind_gust_10m_kmh=gust_kmh, wind_max_0_500m_kmh=gust_kmh)


def test_verdict_is_monotonic_in_wind() -> None:
    """Raising the only varying factor (gust) never improves the verdict."""
    severities = [
        _SEVERITY[assess_hour(MINI_5_PRO, _hour_with_gust(gust)).verdict]
        for gust in (0.0, 20.0, 28.0, 30.0, 40.0, 43.0, 50.0, 70.0)
    ]

    assert severities == sorted(severities)
    assert severities[0] == _SEVERITY[Verdict.GOOD]
    assert severities[-1] == _SEVERITY[Verdict.NO_FLY]


def test_threshold_flip_is_predictable() -> None:
    """Crossing the Mini 5 Pro's 12 m/s (~43.2 km/h) rating flips marginal to no-fly."""
    # 43 km/h ~ 11.9 m/s (at/below limit); 44 km/h ~ 12.2 m/s (above limit).
    assert assess_hour(MINI_5_PRO, _hour_with_gust(43.0)).verdict is Verdict.MARGINAL
    assert assess_hour(MINI_5_PRO, _hour_with_gust(44.0)).verdict is Verdict.NO_FLY


def test_grounding_accepts_a_faithful_explanation() -> None:
    """An explanation that names the verdict and limiting factor is grounded."""
    hour = assess_hour(MINI_5_PRO, _hour_with_gust(60.0))  # no-fly on wind
    explanation = "No-fly: the gusts are well over this drone's wind limit."

    result = check_hour_explanation(explanation, hour)

    assert result.grounded
    assert not result.understates_risk
    assert result.missing_factors == ()


def test_grounding_flags_understated_risk() -> None:
    """A 'good to fly' gloss over a no-fly verdict is flagged as understating risk."""
    hour = assess_hour(MINI_5_PRO, _hour_with_gust(60.0))

    result = check_hour_explanation("Conditions look good to fly today.", hour)

    assert result.understates_risk
    assert not result.grounded


def test_grounding_flags_missing_limiting_factor() -> None:
    """An explanation that omits the limiting factor is reported as ungrounded."""
    hour = assess_hour(MINI_5_PRO, _hour_with_gust(60.0))

    result = check_hour_explanation("It is a no-fly hour, unfortunately.", hour)

    assert "wind_gust" in result.missing_factors
    assert not result.grounded


def test_grounding_passes_a_good_hour() -> None:
    """A good hour has no limiting factors and cannot under-state risk."""
    hour = assess_hour(MINI_5_PRO, _CALM_HOUR)

    result = check_hour_explanation("Good conditions - clear to fly.", hour)

    assert result.grounded
    assert result.missing_factors == ()


@pytest.mark.parametrize("phrase", ["fly with caution", "marginal conditions", "this is a no-fly"])
def test_grounding_restrictive_phrasing_is_not_understating(phrase: str) -> None:
    """Cautionary wording alongside a 'go' phrase is not treated as understating."""
    hour = assess_hour(MINI_5_PRO, _hour_with_gust(60.0))

    result = check_hour_explanation(f"Gusts are high; {phrase}, not good to fly.", hour)

    assert not result.understates_risk
