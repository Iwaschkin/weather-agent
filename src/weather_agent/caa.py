"""Dated UK CAA Open Category guidance for supported aircraft configurations.

The aircraft mark is configuration data supplied by :mod:`weather_agent.drone`;
this module never manufactures a conformity mark from mass. Guidance is concise
decision support for Great Britain and links back to the current official rules.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from weather_agent.models import CaaGuidance, OpenSubcategory, RegulatoryMark

if TYPE_CHECKING:
    from weather_agent.models import DroneProfile

_REVIEWED_AS_OF = date(2026, 7, 12)
_CLASS_MARKS_URL = (
    "https://www.caa.co.uk/drones/open-category/getting-started-with-drones-and-model-aircraft/"
    "class-marks/"
)
_WHERE_YOU_CAN_FLY_URL = (
    "https://www.caa.co.uk/drones/open-category/getting-started-with-drones-and-model-aircraft/"
    "where-you-can-fly/"
)
_HEIGHT_URL = (
    "https://www.caa.co.uk/drones/open-category/drone-code/less-common-flying-points-37-to-39/"
)
_FPV_URL = (
    "https://www.caa.co.uk/drones/open-category/moving-on-to-more-advanced-flying/"
    "first-person-view-fpv/"
)
_REGISTRATION_URL = (
    "https://www.caa.co.uk/drones/open-category/getting-started-with-drones-and-model-aircraft/"
    "registering-to-fly-drones-and-model-aircraft/"
)
_NIGHT_URL = (
    "https://www.caa.co.uk/drones/open-category/getting-started-with-drones-and-model-aircraft/"
    "flying-at-night-in-the-open-category/"
)
_REMOTE_ID_URL = (
    "https://www.caa.co.uk/drones/open-category/moving-on-to-more-advanced-flying/remote-id-rid/"
)
_DRONE_CODE_URL = "https://www.caa.co.uk/drones/open-category/drone-code/"

_HEIGHT_LIMIT_NOTE = (
    "For ordinary drone flight, stay within 120 m (400 ft) of the closest point of the "
    "earth's surface. The separate tall-structure exception applies only when the person or "
    "organisation responsible for an artificial structure over 105 m asks you to perform a "
    "task related to it: while within 50 m horizontally, you may fly no more than 15 m above "
    "that structure."
)
_A1_PEOPLE_RULE = (
    "Current A1 rules allow flight closer than 50 m to, and over, uninvolved people, but never "
    "over crowds; avoid deliberate overflight and always keep a safe distance."
)
_A2_PEOPLE_RULE = (
    "Do not overfly uninvolved people and follow the current A2 horizontal separation required "
    "for the aircraft and operating mode."
)
_A3_PEOPLE_RULE = (
    "Do not overfly uninvolved people; remain at least 50 m from them and 150 m from residential, "
    "recreational, commercial, or industrial areas."
)
_PEOPLE_RULES = {
    OpenSubcategory.A1: _A1_PEOPLE_RULE,
    OpenSubcategory.A2: _A2_PEOPLE_RULE,
    OpenSubcategory.A3: _A3_PEOPLE_RULE,
}
_UNIVERSAL_RULES = (
    "Keep the aircraft in direct, unaided visual line of sight with a full view of surrounding "
    "airspace; onboard sensing does not replace VLOS.",
    "Do not fly in restricted airspace or an airport/airfield Flight Restriction Zone without "
    "the required permission, and check live airspace and NOTAMs before flight.",
    "For these camera-equipped aircraft over 100 g, the remote pilot needs a Flyer ID and the "
    "operator needs an Operator ID; label the aircraft as required.",
    "At night, keep a green flashing light activated throughout the Open Category flight and "
    "continue to maintain VLOS.",
)
_FPV_RULE = (
    "When flying by FPV video or goggles, have an observer beside you who can communicate with "
    "you; at least one of you must maintain direct sight and a full view of surrounding airspace."
)
_DISCLAIMER = (
    "This is Great Britain flight-planning decision support, not legal or airworthiness advice. "
    "You, the remote pilot, remain responsible for the flight. Verify the current CAA Drone and "
    "Model Aircraft Code, aircraft marking/configuration, airspace, Flight Restriction Zones, "
    "and NOTAMs before flying."
)


def _class_label(profile: DroneProfile) -> str:
    mark = profile.regulatory_mark
    if mark is RegulatoryMark.EU_C0:
        return "EU C0 (recognised as corresponding UK0 through 31 December 2027)"
    if mark is RegulatoryMark.EU_C1:
        return "EU C1 (recognised as corresponding UK1 through 31 December 2027)"
    return mark.value


def _remote_id_note(profile: DroneProfile) -> str:
    mark = profile.regulatory_mark
    if mark is RegulatoryMark.UK1:
        return (
            "Remote ID has been mandatory for UK1 operations since "
            "1 January 2026; enter the operator's Remote ID and keep it enabled whenever flying."
        )
    return (
        "For this camera-equipped aircraft over 100 g, Remote ID becomes mandatory by "
        "1 January 2028; the CAA recommends enabling it earlier where supported."
    )


def _transition_rule(profile: DroneProfile) -> str | None:
    if profile.mark_valid_until is None:
        return None
    return (
        f"The {profile.regulatory_mark.value} transition ends after "
        f"{profile.mark_valid_until:%d %B %Y}; from the next day, re-check the aircraft's UK "
        "status and weight-based legacy rules before flying."
    )


def _rules(profile: DroneProfile) -> tuple[str, ...]:
    rules = [_PEOPLE_RULES[profile.open_subcategory], *_UNIVERSAL_RULES]
    if profile.is_fpv:
        rules.append(_FPV_RULE)
    transition = _transition_rule(profile)
    if transition is not None:
        rules.append(transition)
    return tuple(rules)


def caa_guidance(profile: DroneProfile) -> CaaGuidance:
    """Build sourced UK guidance from an explicit aircraft configuration.

    Args:
        profile: Supported aircraft configuration with an actual mark and dated
            manufacturer source.

    Returns:
        Deterministic Great Britain Open Category guidance reviewed on the date
        carried in the result.
    """
    return CaaGuidance(
        drone_name=profile.name,
        configuration=profile.configuration,
        jurisdiction="Great Britain",
        aircraft_class=_class_label(profile),
        subcategory=profile.open_subcategory,
        height_limit_note=_HEIGHT_LIMIT_NOTE,
        key_rules=_rules(profile),
        remote_id_note=_remote_id_note(profile),
        reviewed_as_of=_REVIEWED_AS_OF,
        source_urls=(
            profile.regulatory_source,
            _CLASS_MARKS_URL,
            _WHERE_YOU_CAN_FLY_URL,
            _HEIGHT_URL,
            _FPV_URL,
            _REGISTRATION_URL,
            _NIGHT_URL,
            _REMOTE_ID_URL,
            _DRONE_CODE_URL,
        ),
        disclaimer=_DISCLAIMER,
    )
