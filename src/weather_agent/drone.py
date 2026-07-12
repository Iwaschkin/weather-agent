"""Drone model profiles and lookup for flyability assessment.

Specs come from the manufacturers' published figures (verified against DJI's
spec pages). This module is plain domain configuration: the profiles are data,
and the lookup is the only behaviour.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from weather_agent.models import DroneProfile, OpenSubcategory, RegulatoryMark

# Shared DJI consumer operating temperature envelope.
_MIN_TEMP_C = -10.0
_MAX_TEMP_C = 40.0
_REVIEWED_AS_OF = date(2026, 7, 12)
_EU_MARK_TRANSITION_END = date(2027, 12, 31)
_NEO_SOURCE = "https://www.dji.com/neo/specs"
_AVATA_2_SOURCE = "https://www.dji.com/avata-2/specs"
_MINI_5_PRO_SOURCE = "https://www.dji.com/mini-5-pro/specs"
_MINI_STANDARD_WEIGHT_G = 249.9
_MINI_STANDARD_BATTERY_G = 71.2
_MINI_PLUS_BATTERY_G = 117.0
_MINI_PLUS_WEIGHT_G = _MINI_STANDARD_WEIGHT_G - _MINI_STANDARD_BATTERY_G + _MINI_PLUS_BATTERY_G

NEO = DroneProfile(
    key="neo",
    name="DJI Neo",
    configuration="Standard battery, non-FPV operation",
    weight_g=135.0,
    regulatory_mark=RegulatoryMark.EU_C0,
    open_subcategory=OpenSubcategory.A1,
    mark_valid_until=_EU_MARK_TRANSITION_END,
    regulatory_source=_NEO_SOURCE,
    regulatory_reviewed_as_of=_REVIEWED_AS_OF,
    ideal_gust_ms=5.0,
    caution_gust_ms=8.0,  # Level 4 wind resistance.
    min_temp_c=_MIN_TEMP_C,
    max_temp_c=_MAX_TEMP_C,
    is_fpv=False,
    has_omni_sensing=False,
    low_light_capable=False,
)

NEO_FPV = replace(
    NEO,
    key="neofpv",
    name="DJI Neo (FPV)",
    configuration="Standard battery, FPV video/goggles operation",
    is_fpv=True,
)

AVATA_2 = DroneProfile(
    key="avata2",
    name="DJI Avata 2",
    configuration="Standard aircraft and battery, FPV video/goggles operation",
    weight_g=377.0,
    regulatory_mark=RegulatoryMark.EU_C1,
    open_subcategory=OpenSubcategory.A1,
    mark_valid_until=_EU_MARK_TRANSITION_END,
    regulatory_source=_AVATA_2_SOURCE,
    regulatory_reviewed_as_of=_REVIEWED_AS_OF,
    ideal_gust_ms=7.0,
    caution_gust_ms=10.7,  # Level 5 wind resistance.
    min_temp_c=_MIN_TEMP_C,
    max_temp_c=_MAX_TEMP_C,
    is_fpv=True,
    has_omni_sensing=False,
    low_light_capable=False,
)

MINI_5_PRO = DroneProfile(
    key="mini5pro",
    name="DJI Mini 5 Pro",
    configuration="Standard Intelligent Flight Battery (EU C0 aircraft)",
    weight_g=_MINI_STANDARD_WEIGHT_G,
    regulatory_mark=RegulatoryMark.EU_C0,
    open_subcategory=OpenSubcategory.A1,
    mark_valid_until=_EU_MARK_TRANSITION_END,
    regulatory_source=_MINI_5_PRO_SOURCE,
    regulatory_reviewed_as_of=_REVIEWED_AS_OF,
    ideal_gust_ms=8.0,
    caution_gust_ms=12.0,
    min_temp_c=_MIN_TEMP_C,
    max_temp_c=_MAX_TEMP_C,
    is_fpv=False,
    has_omni_sensing=True,
    low_light_capable=True,
)

MINI_5_PRO_PLUS = DroneProfile(
    key="mini5proplus",
    name="DJI Mini 5 Pro (Plus Battery)",
    configuration="Intelligent Flight Battery Plus (EU C1 aircraft/bundle)",
    weight_g=_MINI_PLUS_WEIGHT_G,
    regulatory_mark=RegulatoryMark.EU_C1,
    open_subcategory=OpenSubcategory.A1,
    mark_valid_until=_EU_MARK_TRANSITION_END,
    regulatory_source=_MINI_5_PRO_SOURCE,
    regulatory_reviewed_as_of=_REVIEWED_AS_OF,
    ideal_gust_ms=8.0,
    caution_gust_ms=12.0,
    min_temp_c=_MIN_TEMP_C,
    max_temp_c=_MAX_TEMP_C,
    is_fpv=False,
    has_omni_sensing=True,
    low_light_capable=True,
)

DRONE_PROFILES: tuple[DroneProfile, ...] = (
    NEO,
    NEO_FPV,
    AVATA_2,
    MINI_5_PRO,
    MINI_5_PRO_PLUS,
)

# Accept common aliases the model or user might produce.
_ALIASES = {
    "neo": NEO,
    "dji neo": NEO,
    "neo fpv": NEO_FPV,
    "dji neo fpv": NEO_FPV,
    "avata": AVATA_2,
    "avata2": AVATA_2,
    "avata 2": AVATA_2,
    "dji avata 2": AVATA_2,
    "mini": MINI_5_PRO,
    "mini5": MINI_5_PRO,
    "mini5pro": MINI_5_PRO,
    "mini 5 pro": MINI_5_PRO,
    "dji mini 5 pro": MINI_5_PRO,
    "mini plus": MINI_5_PRO_PLUS,
    "mini5proplus": MINI_5_PRO_PLUS,
    "mini 5 pro plus": MINI_5_PRO_PLUS,
    "mini 5 pro plus battery": MINI_5_PRO_PLUS,
    "dji mini 5 pro plus": MINI_5_PRO_PLUS,
}


def find_profile(name: str) -> DroneProfile | None:
    """Resolve a free-text drone name to a known profile.

    Args:
        name: A drone name or alias, for example ``"Mini 5 Pro"`` or ``"neo"``.

    Returns:
        The matching profile, or ``None`` when the name is not recognised.
    """
    return _ALIASES.get(name.strip().lower())
