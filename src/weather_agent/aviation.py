"""Boundary adapter for aviationweather.gov METAR observations.

A small synchronous client over the (key-free) aviationweather.gov data API. It
fetches METARs within a bounding box around a coordinate and returns the nearest
reporting station's observation, giving the drone assessment a real observed
reality check (wind, visibility, cloud ceiling) to sit beside the model forecast.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import TYPE_CHECKING

import httpx

from weather_agent.parsing import parse_metars, parse_tafs

if TYPE_CHECKING:
    from weather_agent.models import MetarReport, TafReport

_METAR_URL = "https://aviationweather.gov/api/data/metar"
_TAF_URL = "https://aviationweather.gov/api/data/taf"
_DEFAULT_TIMEOUT = 10.0
# Half-extent of the bounding box searched around the point, in degrees
# (~111 km), wide enough to catch a reporting airfield for most inhabited places.
_DEFAULT_SEARCH_DEGREES = 1.0
_EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two coordinates, in kilometres."""
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(min(1.0, a)))


class AviationClient:
    """Thin synchronous client over the aviationweather.gov METAR API (no key)."""

    def __init__(
        self, client: httpx.Client | None = None, timeout: float = _DEFAULT_TIMEOUT
    ) -> None:
        """Create the client.

        Args:
            client: An existing ``httpx.Client`` to use (tests inject a mock
                transport). When omitted, one is created with the given timeout.
            timeout: Per-request timeout in seconds for the internally created
                client. Ignored when ``client`` is provided.
        """
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def nearest_metar(
        self,
        latitude: float,
        longitude: float,
        search_degrees: float = _DEFAULT_SEARCH_DEGREES,
    ) -> MetarReport | None:
        """Fetch the nearest reporting station's METAR to a coordinate.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
            search_degrees: Half-extent of the search box around the point.

        Returns:
            The closest station's observation, or ``None`` when no station reports
            within the search box.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            AviationError: If the response is not a JSON array.
        """
        bbox = (
            f"{latitude - search_degrees},{longitude - search_degrees},"
            f"{latitude + search_degrees},{longitude + search_degrees}"
        )
        response = self._client.get(_METAR_URL, params={"format": "json", "bbox": bbox})
        _ = response.raise_for_status()
        reports = parse_metars(response.json())
        if not reports:
            return None
        return min(
            reports,
            key=lambda report: _haversine_km(
                latitude, longitude, report.latitude, report.longitude
            ),
        )

    def nearest_taf(
        self,
        latitude: float,
        longitude: float,
        search_degrees: float = _DEFAULT_SEARCH_DEGREES,
    ) -> TafReport | None:
        """Fetch the nearest reporting station's TAF (aviation forecast) to a coordinate.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
            search_degrees: Half-extent of the search box around the point.

        Returns:
            The closest station's forecast, or ``None`` when no station reports
            within the search box.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            AviationError: If the response is not a JSON array.
        """
        bbox = (
            f"{latitude - search_degrees},{longitude - search_degrees},"
            f"{latitude + search_degrees},{longitude + search_degrees}"
        )
        response = self._client.get(_TAF_URL, params={"format": "json", "bbox": bbox})
        _ = response.raise_for_status()
        reports = parse_tafs(response.json())
        if not reports:
            return None
        return min(
            reports,
            key=lambda report: _haversine_km(
                latitude, longitude, report.latitude, report.longitude
            ),
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
