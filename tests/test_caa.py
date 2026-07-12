"""Tests for sourced, configuration-aware UK CAA guidance."""

from dataclasses import replace
from datetime import date

import pytest

from weather_agent.caa import caa_guidance
from weather_agent.drone import AVATA_2, MINI_5_PRO, MINI_5_PRO_PLUS, NEO, NEO_FPV
from weather_agent.models import DroneProfile, OpenSubcategory, RegulatoryMark


@pytest.mark.parametrize(
    ("profile", "expected_mark"),
    [
        (NEO, RegulatoryMark.EU_C0),
        (NEO_FPV, RegulatoryMark.EU_C0),
        (AVATA_2, RegulatoryMark.EU_C1),
        (MINI_5_PRO, RegulatoryMark.EU_C0),
        (MINI_5_PRO_PLUS, RegulatoryMark.EU_C1),
    ],
)
def test_every_supported_configuration_has_explicit_current_provenance(
    profile: DroneProfile,
    expected_mark: RegulatoryMark,
) -> None:
    """Every shipped aircraft configuration fixes its mark, source, and review date."""
    guidance = caa_guidance(profile)

    assert profile.regulatory_mark is expected_mark
    assert guidance.aircraft_class.startswith(expected_mark.value)
    assert guidance.source_urls[0] == profile.regulatory_source
    assert profile.regulatory_reviewed_as_of == date(2026, 7, 12)
    assert guidance.reviewed_as_of == date(2026, 7, 12)
    assert "1 January 2028" in guidance.remote_id_note


def test_guidance_uses_explicit_eu_c0_mark() -> None:
    """A configured EU C0 mark is reported with its dated UK transition."""
    guidance = caa_guidance(NEO)

    assert NEO.regulatory_mark is RegulatoryMark.EU_C0
    assert "EU C0" in guidance.aircraft_class
    assert "31 December 2027" in guidance.aircraft_class
    assert guidance.subcategory is OpenSubcategory.A1


def test_weight_change_does_not_manufacture_a_different_mark() -> None:
    """Mass is not used to infer or rewrite an aircraft conformity mark."""
    changed_weight = replace(AVATA_2, weight_g=100.0)

    guidance = caa_guidance(changed_weight)

    assert changed_weight.regulatory_mark is RegulatoryMark.EU_C1
    assert "EU C1" in guidance.aircraft_class


def test_mini_batteries_are_distinct_regulatory_configurations() -> None:
    """Standard and Plus configurations carry their actual separate marks."""
    standard = caa_guidance(MINI_5_PRO)
    plus = caa_guidance(MINI_5_PRO_PLUS)

    assert MINI_5_PRO.regulatory_mark is RegulatoryMark.EU_C0
    assert MINI_5_PRO_PLUS.regulatory_mark is RegulatoryMark.EU_C1
    assert MINI_5_PRO.weight_g < 250.0 < MINI_5_PRO_PLUS.weight_g
    assert standard.configuration != plus.configuration
    assert "1 January 2028" in standard.remote_id_note
    assert "1 January 2028" in plus.remote_id_note


def test_eu_c1_does_not_inherit_the_uk1_remote_id_deadline() -> None:
    """Operational class equivalence does not turn an EU C1 mark into a UK1 mark."""
    eu_guidance = caa_guidance(AVATA_2)
    uk_guidance = caa_guidance(
        replace(
            AVATA_2,
            regulatory_mark=RegulatoryMark.UK1,
            mark_valid_until=None,
        )
    )

    assert "1 January 2028" in eu_guidance.remote_id_note
    assert "1 January 2026" not in eu_guidance.remote_id_note
    assert "1 January 2026" in uk_guidance.remote_id_note


def test_guidance_states_exact_height_and_structure_conditions() -> None:
    """The ordinary terrain rule is separate from the commissioned-structure exception."""
    note = caa_guidance(NEO).height_limit_note

    assert "closest point" in note
    assert "over 105 m" in note
    assert "within 50 m" in note
    assert "15 m above" in note
    assert "asks you" in note
    assert "valley floor" not in note


def test_fpv_configuration_includes_observer_rule() -> None:
    """FPV operation requires the co-located observer workflow in deterministic text."""
    fpv_rules = " ".join(caa_guidance(NEO_FPV).key_rules)
    standard_rules = " ".join(caa_guidance(NEO).key_rules)

    assert "observer beside you" in fpv_rules
    assert "observer beside you" not in standard_rules


def test_guidance_includes_night_registration_remote_id_and_scope() -> None:
    """Current requirements and provenance are carried as structured guidance."""
    guidance = caa_guidance(AVATA_2)
    rules = " ".join(guidance.key_rules)

    assert guidance.jurisdiction == "Great Britain"
    assert "green flashing light" in rules
    assert "Flyer ID" in rules
    assert "Operator ID" in rules
    assert "1 January 2028" in guidance.remote_id_note
    assert guidance.reviewed_as_of == date(2026, 7, 12)
    assert guidance.source_urls
    assert all(url.startswith("https://") for url in guidance.source_urls)


def test_guidance_labels_onboard_sensing_as_not_replacing_vlos() -> None:
    """Aircraft sensors never relax the remote pilot's direct-sight rule."""
    rules = " ".join(caa_guidance(MINI_5_PRO).key_rules)

    assert "onboard sensing does not replace VLOS" in rules
