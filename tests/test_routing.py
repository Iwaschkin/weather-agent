"""Tests for pure date-based data-source routing."""

from datetime import date

import pytest

from weather_agent.routing import DataSource, select_data_source

_TODAY = date(2026, 6, 16)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        # Recent past (within the archive's publication lag) is served by forecast.
        (date(2026, 6, 15), DataSource.FORECAST),
        (date(2026, 6, 11), DataSource.FORECAST),  # exactly at the 5-day lag boundary
        (date(2026, 6, 10), DataSource.ARCHIVE),  # older than the lag -> archive
        (date(1990, 1, 1), DataSource.ARCHIVE),
        (date(2026, 6, 16), DataSource.FORECAST),
        (date(2026, 6, 20), DataSource.FORECAST),
        (date(2026, 7, 1), DataSource.FORECAST),
        (date(2026, 7, 2), DataSource.CLIMATE),
        (date(2045, 1, 1), DataSource.CLIMATE),
    ],
)
def test_select_data_source_boundaries(target: date, expected: DataSource) -> None:
    """The router maps past/near/far dates to archive/forecast/climate."""
    assert select_data_source(target, _TODAY) is expected
