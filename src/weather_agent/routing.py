"""Pure date-based routing between open-meteo's time-scoped data sources.

The forecast, archive, and climate APIs each cover a different time window. This
module decides which one answers a question about a given date, so the agent can
expose a single "weather for a date" affordance backed by the right API.
"""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

FORECAST_HORIZON_DAYS = 16
# ERA5/ERA5T reanalysis publishes with a few days' lag, so the most recent days
# are not yet in the archive. The forecast endpoint carries that recent past
# (via explicit dates), so dates within this window route to FORECAST, not
# ARCHIVE, which would otherwise return "no data" for the last few days.
ARCHIVE_LATENCY_DAYS = 5


class DataSource(Enum):
    """The open-meteo data source that covers a requested date.

    Attributes:
        ARCHIVE: ERA5 reanalysis for past dates.
        FORECAST: Numerical forecast within the near-term horizon.
        CLIMATE: CMIP6 projection for dates beyond the forecast horizon.
    """

    ARCHIVE = "archive"
    FORECAST = "forecast"
    CLIMATE = "climate"


def select_data_source(target: date, today: date) -> DataSource:
    """Choose the data source that covers ``target`` relative to ``today``.

    Args:
        target: The date the question is about.
        today: The reference "current" date (timezone-aware UTC at the boundary).

    Returns:
        :attr:`DataSource.ARCHIVE` for dates older than the archive's publication
        lag (:data:`ARCHIVE_LATENCY_DAYS`); :attr:`DataSource.FORECAST` for the
        recent past, today, and the next 15 days (the forecast endpoint serves the
        recent past via explicit dates and the future within a 16-day horizon); and
        :attr:`DataSource.CLIMATE` beyond the forecast horizon.
    """
    if target < today - timedelta(days=ARCHIVE_LATENCY_DAYS):
        return DataSource.ARCHIVE
    if (target - today).days < FORECAST_HORIZON_DAYS:
        return DataSource.FORECAST
    return DataSource.CLIMATE
