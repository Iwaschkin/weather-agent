"""Tests for pure free-text location parsing and candidate selection."""

import pytest

from weather_agent.geocoding import LocationQuery, parse_location, select_best_match
from weather_agent.models import GeocodeResult


def _result(
    name: str,
    *,
    country: str = "",
    country_code: str = "",
    admin1: str = "",
    population: int | None = None,
) -> GeocodeResult:
    return GeocodeResult(
        name=name,
        country=country,
        country_code=country_code,
        admin1=admin1,
        population=population,
        latitude=0.0,
        longitude=0.0,
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Congleton UK", LocationQuery("Congleton", "UK")),
        ("Paris, Texas", LocationQuery("Paris", "Texas")),
        ("Kansas City USA", LocationQuery("Kansas City", "USA")),
        ("New York", LocationQuery("New York", "")),
        ("  Berlin  ", LocationQuery("Berlin", "")),
        ("Springfield, Illinois, USA", LocationQuery("Springfield, Illinois", "USA")),
        # Region words are NOT split off without a comma: they collide with real
        # multi-word names, so the whole string stays the name.
        ("New South Wales", LocationQuery("New South Wales", "")),
        ("Newcastle England", LocationQuery("Newcastle England", "")),
        # The comma form still carries a region qualifier.
        ("Newcastle, England", LocationQuery("Newcastle", "England")),
    ],
)
def test_parse_location_splits_qualifier(text: str, expected: LocationQuery) -> None:
    """Free-text input is split into a query name and a qualifier."""
    assert parse_location(text) == expected


def test_select_best_match_returns_none_for_empty() -> None:
    """No candidates yields no match."""
    assert select_best_match([], "UK") is None


def test_select_best_match_lets_dominant_namesake_override_relevance() -> None:
    """A vastly more populous namesake beats a higher-ranked obscure match."""
    small = _result("Paris", country="United States", population=25000)  # API's top hit
    big = _result("Paris", country="France", population=2_100_000)

    assert select_best_match([small, big], "") is big


def test_select_best_match_prefers_relevance_for_comparable_populations() -> None:
    """When populations are comparable, the API's most-relevant (first) match wins."""
    relevant = _result("Springfield", country="United States", population=160000)
    slightly_bigger = _result("Springfield", country="United States", population=170000)

    assert select_best_match([relevant, slightly_bigger], "") is relevant


def test_select_best_match_honours_country_alias() -> None:
    """A 'UK' qualifier matches a GB country code over a larger namesake."""
    us_town = _result("Congleton", country_code="US", population=300000)
    uk_town = _result("Congleton", country_code="GB", population=26482)

    assert select_best_match([us_town, uk_town], "UK") is uk_town


def test_select_best_match_honours_region_qualifier() -> None:
    """An admin1/region qualifier selects the matching candidate."""
    paris_fr = _result("Paris", country="France", admin1="Ile-de-France", population=2_100_000)
    paris_tx = _result("Paris", country="United States", admin1="Texas", population=25000)

    assert select_best_match([paris_fr, paris_tx], "Texas") is paris_tx


def test_select_best_match_falls_back_when_qualifier_unmatched() -> None:
    """An unmatched qualifier falls back to the most populous candidate."""
    a = _result("Townsville", country="Australia", population=180000)
    b = _result("Townsville", country="Australia", population=500)

    assert select_best_match([a, b], "Narnia") is a
