"""Keyword retrieval over the curated drone knowledge file (Option C).

This is the qualitative half of the hybrid design: the numeric flyability engine
decides verdicts, and this module surfaces relevant human-written tips to explain
them. Retrieval is a simple, dependency-free keyword overlap so it stays fast and
testable; the same ``retrieve`` interface could later be backed by embeddings
without changing callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

_HEADING_PATTERN = re.compile(r"^##\s+(.*)$", re.MULTILINE)
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_MIN_WORD_LENGTH = 3
_DEFAULT_LIMIT = 3
_DATA_PACKAGE = "weather_agent"
_KNOWLEDGE_FILE = "drone_knowledge.md"
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "you",
        "your",
        "are",
        "but",
        "not",
        "can",
        "from",
        "this",
        "that",
        "has",
        "have",
        "out",
        "off",
        "its",
        "into",
        "than",
        "more",
        "over",
        "under",
        "when",
        "what",
        "how",
        "any",
        "all",
        "use",
    }
)


@dataclass(frozen=True, slots=True)
class KnowledgeSection:
    """A single retrievable section of the knowledge file.

    Attributes:
        heading: The section heading.
        body: The section's prose.
        keywords: Significant lower-cased words for matching against queries.
    """

    heading: str
    body: str
    keywords: frozenset[str]


def _tokenize(text: str) -> frozenset[str]:
    return frozenset(
        word
        for word in _WORD_PATTERN.findall(text.lower())
        if len(word) >= _MIN_WORD_LENGTH and word not in _STOPWORDS
    )


def parse_sections(markdown: str) -> tuple[KnowledgeSection, ...]:
    """Split a knowledge markdown document into retrievable sections.

    Args:
        markdown: The document text, with sections under ``##`` headings.

    Returns:
        One section per non-empty ``##`` block, in document order.
    """
    headings = list(_HEADING_PATTERN.finditer(markdown))
    sections: list[KnowledgeSection] = []
    for position, match in enumerate(headings):
        heading = match.group(1).strip()
        start = match.end()
        end = headings[position + 1].start() if position + 1 < len(headings) else len(markdown)
        body = markdown[start:end].strip()
        if body:
            sections.append(
                KnowledgeSection(
                    heading=heading, body=body, keywords=_tokenize(f"{heading} {body}")
                )
            )
    return tuple(sections)


@lru_cache(maxsize=1)
def load_sections() -> tuple[KnowledgeSection, ...]:
    """Load and parse the packaged drone knowledge file.

    The packaged file is immutable at runtime, so the parsed result is memoised
    (this is a one-shot read of static data, not an architectural cache layer):
    repeated assessments reuse the same parsed sections instead of re-reading and
    re-parsing the file on every call.

    Returns:
        The parsed knowledge sections.
    """
    text = resources.files(_DATA_PACKAGE).joinpath("data", _KNOWLEDGE_FILE).read_text("utf-8")
    return parse_sections(text)


def retrieve(
    query: str,
    sections: tuple[KnowledgeSection, ...],
    limit: int = _DEFAULT_LIMIT,
) -> tuple[KnowledgeSection, ...]:
    """Return the sections most relevant to a query by keyword overlap.

    Args:
        query: Free text describing the topic, for example limiting factors.
        sections: The knowledge sections to search.
        limit: Maximum number of sections to return.

    Returns:
        Up to ``limit`` sections with at least one shared keyword, most relevant
        first; empty when nothing matches.
    """
    terms = _tokenize(query)
    if not terms:
        return ()
    scored = [
        (len(terms & section.keywords), order, section) for order, section in enumerate(sections)
    ]
    ranked = sorted(
        (entry for entry in scored if entry[0] > 0),
        key=lambda entry: (-entry[0], entry[1]),
    )
    return tuple(section for _, _, section in ranked[:limit])
