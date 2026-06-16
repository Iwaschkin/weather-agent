"""Tests for rendering typed lookup outcomes to user-facing text."""

from weather_agent.results import Answer, Failed, Invalid, NotFound, render


def test_render_answer_returns_text_verbatim() -> None:
    """An answer renders to its formatted text unchanged."""
    assert render(Answer("Current weather in Berlin: 21 C.")) == "Current weather in Berlin: 21 C."


def test_render_not_found_names_the_location() -> None:
    """A not-found outcome renders a message naming the original location."""
    assert render(NotFound("Atlantis")) == "No location matching 'Atlantis' was found."


def test_render_failed_includes_detail() -> None:
    """A failure renders the location and the underlying error detail."""
    assert render(Failed("Berlin", "timeout")) == "Could not retrieve data for 'Berlin': timeout"


def test_render_invalid_returns_message_verbatim() -> None:
    """An invalid-input outcome renders its complete message unchanged."""
    assert render(Invalid("'x' is not a valid ISO date.")) == "'x' is not a valid ISO date."
