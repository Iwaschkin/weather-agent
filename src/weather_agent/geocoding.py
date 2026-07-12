"""Pure helpers for resolving free-text locations to the best geocoding match.

The open-meteo geocoding API matches on a bare place name, so a free-text input
like ``"Congleton UK"`` or ``"Paris, Texas"`` must be split into the name to
query and a country/region qualifier used to disambiguate the candidates it
returns. These helpers perform no I/O and are safe to unit test directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from weather_agent.models import GeocodeResult

# Common informal country qualifiers mapped to their ISO-3166 alpha-2 codes,
# so "Congleton UK" matches a result whose country_code is "GB".
_COUNTRY_ALIASES = {
    "uk": "gb",
    "u.k.": "gb",
    "united kingdom": "gb",
    "great britain": "gb",
    "britain": "gb",
    "england": "gb",
    "scotland": "gb",
    "wales": "gb",
    "usa": "us",
    "u.s.a.": "us",
    "united states": "us",
    "united states of america": "us",
    "america": "us",
    "uae": "ae",
}

# Single trailing tokens that signal a country qualifier when the input has no
# comma (for example the "UK" in "Congleton UK"). Restricted to abbreviations
# that essentially never end a real place name; full region words (England,
# Scotland, Wales, ...) are NOT split off here because they collide with genuine
# names ("New South Wales"), so those must be disambiguated with a comma
# ("Newcastle, England"). The comma form still resolves them via _COUNTRY_ALIASES.
_TRAILING_QUALIFIER_TOKENS = frozenset({"uk", "usa", "uae"})

# A trailing qualifier can only be split off when at least this many tokens
# remain, so a single-word input is never stripped to nothing.
_MIN_TOKENS_FOR_TRAILING_QUALIFIER = 2


@dataclass(frozen=True, slots=True)
class LocationQuery:
    """A free-text location split into a name to query and a qualifier.

    Attributes:
        name: The place name to send to the geocoding API.
        qualifier: A country or region hint used to pick among candidates, or an
            empty string when the input carried none.
    """

    name: str
    qualifier: str


def parse_location(text: str) -> LocationQuery:
    """Split free-text input into a query name and a disambiguating qualifier.

    A comma always separates the name from the qualifier (``"Paris, Texas"``).
    Without a comma, a recognised trailing token such as ``"UK"`` is treated as
    the qualifier (``"Congleton UK"``); otherwise the whole string is the name so
    multi-word places like ``"New York"`` stay intact.

    Args:
        text: The raw location string from the user.

    Returns:
        The parsed query; ``qualifier`` is empty when none was found.
    """
    cleaned = text.strip()
    if "," in cleaned:
        name, _, qualifier = cleaned.rpartition(",")
        return LocationQuery(name=name.strip(), qualifier=qualifier.strip())
    parts = cleaned.split()
    if (
        len(parts) >= _MIN_TOKENS_FOR_TRAILING_QUALIFIER
        and parts[-1].lower() in _TRAILING_QUALIFIER_TOKENS
    ):
        return LocationQuery(name=" ".join(parts[:-1]), qualifier=parts[-1])
    return LocationQuery(name=cleaned, qualifier="")


def _matches_qualifier(candidate: GeocodeResult, qualifier: str) -> bool:
    wanted = qualifier.strip().lower()
    wanted_code = _COUNTRY_ALIASES.get(wanted, wanted)
    return (
        candidate.country_code.lower() == wanted_code
        or candidate.country.lower() == wanted
        or candidate.admin1.lower() == wanted
    )


# How many times more populous a namesake must be to override the API's
# relevance order. Below this ratio the most-relevant (first) candidate wins; at
# or above it a clearly bigger place (a major city vs an obscure namesake) wins.
_DOMINANT_POPULATION_RATIO = 10.0


def _most_relevant(candidates: Sequence[GeocodeResult]) -> GeocodeResult:
    """Pick the API's top candidate unless a namesake clearly dwarfs it.

    open-meteo returns candidates in relevance order, so ``candidates[0]`` is the
    most relevant. It is kept unless another candidate is at least
    :data:`_DOMINANT_POPULATION_RATIO` times more populous, which lets a major
    city beat an obscure namesake the relevance order happened to rank first
    without letting population override relevance for comparable places.

    Args:
        candidates: A non-empty sequence of matches in the API's relevance order.

    Returns:
        The chosen match.
    """
    top = candidates[0]
    top_population = top.population
    known = [candidate for candidate in candidates if (candidate.population or 0) > 0]
    if top_population is None or top_population <= 0 or not known:
        return top
    most_populous = max(known, key=lambda candidate: candidate.population or 0)
    population = most_populous.population
    if population is not None and population >= _DOMINANT_POPULATION_RATIO * top_population:
        return most_populous
    return top


def select_best_match(
    candidates: Sequence[GeocodeResult],
    qualifier: str,
) -> GeocodeResult | None:
    """Choose the best geocoding candidate for an optional qualifier.

    When a qualifier is given, candidates matching it by country, country code, or
    region are preferred. Within the chosen set the API's most relevant match wins
    unless a namesake is overwhelmingly more populous (see :func:`_most_relevant`),
    which keeps well-known places ahead of obscure namesakes while still trusting
    the API's relevance for comparable candidates.

    Args:
        candidates: Geocoding matches in the API's relevance order.
        qualifier: A country or region hint, or an empty string.

    Returns:
        The best match, or ``None`` when ``candidates`` is empty.
    """
    if not candidates:
        return None
    if qualifier:
        matching = [c for c in candidates if _matches_qualifier(c, qualifier)]
        return _most_relevant(matching) if matching else None
    return _most_relevant(candidates)
