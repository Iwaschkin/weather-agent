"""Tests for the pure UK CAA guidance module."""

from weather_agent.caa import caa_guidance
from weather_agent.drone import AVATA_2, MINI_5_PRO, NEO


def test_caa_guidance_classifies_sub_250g_as_c0() -> None:
    """A sub-250 g drone is C0 in subcategory A1."""
    guidance = caa_guidance(NEO)

    assert guidance.uk_class_label.startswith("C0")
    assert guidance.subcategory == "A1"
    assert guidance.class_caveat == ""


def test_caa_guidance_classifies_avata2_as_c1() -> None:
    """A 377 g drone falls in the sub-900 g (C1) band."""
    guidance = caa_guidance(AVATA_2)

    assert guidance.uk_class_label.startswith("C1")


def test_caa_guidance_includes_height_clause_and_disclaimer() -> None:
    """Guidance carries the terrain height clause and a disclaimer."""
    guidance = caa_guidance(NEO)

    assert "120 m" in guidance.height_limit_note
    assert "valley floor" in guidance.height_limit_note
    assert "not legal" in guidance.disclaimer.lower()
    assert any("visual line of sight" in rule for rule in guidance.key_rules)


def test_caa_guidance_notes_mini5pro_plus_battery_caveat() -> None:
    """The Mini 5 Pro carries the Plus-battery class caveat."""
    guidance = caa_guidance(MINI_5_PRO)

    assert "Battery Plus" in guidance.class_caveat
    assert "250 g" in guidance.class_caveat
