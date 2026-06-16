"""Tests for the drone knowledge retriever."""

from weather_agent.knowledge import (
    KnowledgeSection,
    load_sections,
    parse_sections,
    retrieve,
)

_SAMPLE = """# Title

Intro text that is not a section.

## Wind and gusts

Gusts matter more than average wind for light drones.

## Cold weather and batteries

Cold reduces battery capacity and flight time.

## Empty section
"""


def test_parse_sections_splits_on_headings() -> None:
    """Each non-empty level-two block becomes a section, in order."""
    sections = parse_sections(_SAMPLE)

    headings = [section.heading for section in sections]
    assert headings == ["Wind and gusts", "Cold weather and batteries"]


def test_parse_sections_extracts_keywords() -> None:
    """Sections carry significant lower-cased keywords for matching."""
    sections = parse_sections(_SAMPLE)

    assert "gusts" in sections[0].keywords
    assert "the" not in sections[0].keywords  # stopword removed


def test_retrieve_ranks_by_keyword_overlap() -> None:
    """The most relevant section is returned first."""
    sections = parse_sections(_SAMPLE)

    results = retrieve("strong gusts and wind", sections)

    assert results[0].heading == "Wind and gusts"


def test_retrieve_returns_empty_for_no_match() -> None:
    """A query with no shared keywords returns nothing."""
    sections = parse_sections(_SAMPLE)

    assert retrieve("submarine periscope", sections) == ()


def test_retrieve_respects_limit() -> None:
    """The number of returned sections is capped by the limit."""
    sections = (
        KnowledgeSection("A", "wind gust", frozenset({"wind", "gust"})),
        KnowledgeSection("B", "wind cold", frozenset({"wind", "cold"})),
        KnowledgeSection("C", "wind rain", frozenset({"wind", "rain"})),
    )

    assert len(retrieve("wind", sections, limit=2)) == 2


def test_load_sections_reads_packaged_file() -> None:
    """The packaged knowledge file loads into multiple sections."""
    sections = load_sections()

    assert len(sections) > 3
    assert any("wind" in section.heading.lower() for section in sections)


def test_load_sections_is_memoised() -> None:
    """Repeated loads reuse one parse of the immutable packaged file."""
    assert load_sections() is load_sections()
