"""Drone model profiles and lookup for flyability assessment.

Specs come from the manufacturers' published figures (verified against DJI's
spec pages). This module is plain domain configuration: the profiles are data,
and the lookup is the only behaviour.
"""

from __future__ import annotations

from weather_agent.models import DroneProfile

# Shared DJI consumer operating temperature envelope.
_MIN_TEMP_C = -10.0
_MAX_TEMP_C = 40.0

NEO = DroneProfile(
    key="neo",
    name="DJI Neo",
    weight_g=135.0,
    ideal_gust_ms=5.0,
    caution_gust_ms=8.0,  # Level 4 wind resistance.
    min_temp_c=_MIN_TEMP_C,
    max_temp_c=_MAX_TEMP_C,
    is_fpv=True,
    has_omni_sensing=False,
    low_light_capable=False,
)

AVATA_2 = DroneProfile(
    key="avata2",
    name="DJI Avata 2",
    weight_g=377.0,
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
    weight_g=249.9,
    ideal_gust_ms=8.0,
    caution_gust_ms=12.0,
    min_temp_c=_MIN_TEMP_C,
    max_temp_c=_MAX_TEMP_C,
    is_fpv=False,
    has_omni_sensing=True,
    low_light_capable=True,
)

DRONE_PROFILES: tuple[DroneProfile, ...] = (NEO, AVATA_2, MINI_5_PRO)

# Accept common aliases the model or user might produce.
_ALIASES = {
    "neo": NEO,
    "dji neo": NEO,
    "avata": AVATA_2,
    "avata2": AVATA_2,
    "avata 2": AVATA_2,
    "dji avata 2": AVATA_2,
    "mini": MINI_5_PRO,
    "mini5": MINI_5_PRO,
    "mini5pro": MINI_5_PRO,
    "mini 5 pro": MINI_5_PRO,
    "dji mini 5 pro": MINI_5_PRO,
}


def find_profile(name: str) -> DroneProfile | None:
    """Resolve a free-text drone name to a known profile.

    Args:
        name: A drone name or alias, for example ``"Mini 5 Pro"`` or ``"neo"``.

    Returns:
        The matching profile, or ``None`` when the name is not recognised.
    """
    return _ALIASES.get(name.strip().lower())
