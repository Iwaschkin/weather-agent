"""Typed outcomes for location-scoped lookups.

Every domain function in :mod:`weather_agent.weather` resolves a location and runs
one or more open-meteo calls. Rather than encoding success, "not found", invalid
input, and failure all as bare strings (which makes them indistinguishable and
unsafe to compose), each function returns one of these typed outcomes. The text a
user sees is produced once, at the tool boundary, by :func:`render`.

This lets callers compose safely - for example, only annotating a *successful*
answer with a caveat - without inspecting message prefixes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Answer:
    """A successful lookup whose ``text`` is the formatted, user-facing answer.

    Attributes:
        text: The fully formatted summary to show the user.
    """

    text: str


@dataclass(frozen=True, slots=True)
class NotFound:
    """The requested location could not be resolved by geocoding.

    Attributes:
        location: The original location string the user supplied.
    """

    location: str


@dataclass(frozen=True, slots=True)
class Failed:
    """A lookup failed at the network or payload boundary.

    Attributes:
        location: The original location string the user supplied.
        detail: A short description of the underlying error.
    """

    location: str
    detail: str


@dataclass(frozen=True, slots=True)
class Invalid:
    """The request itself was malformed (for example a bad date or out-of-range count).

    Attributes:
        message: A complete, user-facing explanation of why the input was rejected.
    """

    message: str


# The result of a location-scoped lookup, rendered to text by `render`.
LookupOutcome = Answer | NotFound | Failed | Invalid


def render(outcome: LookupOutcome) -> str:
    """Render a lookup outcome into the user-facing text for a tool to return.

    Args:
        outcome: The typed outcome produced by a domain function.

    Returns:
        The text to surface to the user.
    """
    match outcome:
        case Answer(text):
            return text
        case NotFound(location):
            return f"No location matching '{location}' was found."
        case Failed(location, detail):
            return f"Could not retrieve data for '{location}': {detail}"
        case Invalid(message):
            return message
