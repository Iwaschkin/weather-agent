"""Pure UK CAA open-category guidance for the supported drones.

This encodes the practical UK rules a recreational pilot needs: class/weight
banding, the 120 m height limit and its terrain clause (which is what lets you
fly higher above a valley floor near hills), visual-line-of-sight, and ID
requirements. It is decision support, not legal advice, and it deliberately does
not check airspace, Flight Restriction Zones, or NOTAMs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weather_agent.models import CaaGuidance

if TYPE_CHECKING:
    from weather_agent.models import DroneProfile

_C0_MAX_G = 250.0
_C1_MAX_G = 900.0

_HEIGHT_LIMIT_NOTE = (
    "Stay within 120 m (400 ft) of the closest point of the surface. Near terrain "
    "or obstacles the 120 m is measured from the highest point of the nearest "
    "obstacle within 50 m horizontally, so over a hill you can be well above the "
    "valley floor (up to ~500 m) while still legal - provided you stay within "
    "120 m of the hilltop and keep the drone in visual line of sight."
)

_UNIVERSAL_RULES = (
    "Keep the drone within unaided visual line of sight at all times.",
    "Do not fly in airport/airfield Flight Restriction Zones without permission.",
    "These drones have cameras: register for an Operator ID, label the drone, and "
    "pass the Flyer ID test before flying.",
    "Do not fly over crowds or assemblies of people.",
)

_DISCLAIMER = (
    "This is flight-planning decision support, not legal or airworthiness advice. "
    "You, the remote pilot, remain responsible for the flight. Always check live "
    "airspace, Flight Restriction Zones, and NOTAMs (for example CAA Drone Assist "
    "or Altitude Angel) before flying, and confirm the current Drone and Model "
    "Aircraft Code rules, which can change."
)

_MINI_5_PRO_KEY = "mini5pro"
_MINI_5_PRO_PLUS_CAVEAT = (
    "With the Intelligent Flight Battery Plus (available in the UK) the Mini 5 Pro "
    "exceeds 250 g, loses its C0 marking, and must then keep greater separation "
    "from uninvolved people; treat it as a sub-900 g drone in that configuration."
)


def _class_band(weight_g: float) -> tuple[str, str, str]:
    if weight_g < _C0_MAX_G:
        return (
            "C0 (sub-250 g)",
            "A1",
            "Lightest band: you may fly over (but never intentionally close above) "
            "uninvolved people, and not over crowds.",
        )
    if weight_g < _C1_MAX_G:
        return (
            "C1 (sub-900 g)",
            "A1",
            "Do not fly over uninvolved people; keep a safe horizontal distance.",
        )
    return (
        "C2 or heavier",
        "A2/A3",
        "Keep well clear of uninvolved people per A2/A3 separation distances.",
    )


def caa_guidance(profile: DroneProfile) -> CaaGuidance:
    """Build UK CAA open-category guidance for a drone.

    Args:
        profile: The drone to produce guidance for.

    Returns:
        The class band, subcategory, height rule, universal rules, any
        model-specific caveat, and the standing disclaimer.
    """
    class_label, subcategory, people_rule = _class_band(profile.weight_g)
    caveat = _MINI_5_PRO_PLUS_CAVEAT if profile.key == _MINI_5_PRO_KEY else ""
    return CaaGuidance(
        drone_name=profile.name,
        uk_class_label=class_label,
        subcategory=subcategory,
        height_limit_note=_HEIGHT_LIMIT_NOTE,
        key_rules=(people_rule, *_UNIVERSAL_RULES),
        class_caveat=caveat,
        disclaimer=_DISCLAIMER,
    )
