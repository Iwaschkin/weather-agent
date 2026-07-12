"""Boundary adapter for aviationweather.gov METAR observations.

A small synchronous client over the (key-free) aviationweather.gov data API. It
fetches METARs within a bounding box around a coordinate and returns the nearest
reporting station's observation, giving the drone assessment a real observed
reality check (wind, visibility, cloud ceiling) to sit beside the model forecast.
"""

from __future__ import annotations

import json
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import TYPE_CHECKING

import httpx

from weather_agent.parsing import AviationError, parse_metars

if TYPE_CHECKING:
    from weather_agent.models import Coordinates, MetarReport

_METAR_URL = "https://aviationweather.gov/api/data/metar"
_DEFAULT_TIMEOUT = 10.0
# Half-extent of the bounding box searched around the point, in degrees
# (~111 km), wide enough to catch a reporting airfield for most inhabited places.
_DEFAULT_SEARCH_DEGREES = 1.0
_MAX_SEARCH_DEGREES = 5.0
_EARTH_RADIUS_KM = 6371.0
_HTTP_NO_CONTENT = 204


def _haversine_km(origin: Coordinates, destination: Coordinates) -> float:
    """Return the great-circle distance between two coordinates, in kilometres."""
    d_lat = radians(destination.latitude - origin.latitude)
    d_lon = radians(destination.longitude - origin.longitude)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(origin.latitude)) * cos(radians(destination.latitude)) * sin(d_lon / 2) ** 2
    )
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
        coordinates: Coordinates,
        search_degrees: float = _DEFAULT_SEARCH_DEGREES,
    ) -> MetarReport | None:
        """Fetch the nearest reporting station's METAR to a coordinate.

        Args:
            coordinates: Validated WGS84 coordinate pair.
            search_degrees: Half-extent of the search box around the point.

        Returns:
            The closest station's observation, or ``None`` when no station reports
            within the search box.

        Raises:
            ValueError: If ``search_degrees`` is not finite and in ``(0, 5]``.
            httpx.HTTPError: If the request fails or returns an error status.
            AviationError: If the response is not a JSON array.
        """
        if not isfinite(search_degrees) or not 0 < search_degrees <= _MAX_SEARCH_DEGREES:
            message = f"search_degrees must be finite and in (0, {_MAX_SEARCH_DEGREES}]"
            raise ValueError(message)
        bbox = (
            f"{coordinates.latitude - search_degrees},"
            f"{coordinates.longitude - search_degrees},"
            f"{coordinates.latitude + search_degrees},"
            f"{coordinates.longitude + search_degrees}"
        )
        response = self._client.get(_METAR_URL, params={"format": "json", "bbox": bbox})
        _ = response.raise_for_status()
        if response.status_code == _HTTP_NO_CONTENT:
            return None
        try:
            payload: object = response.json()
        except json.JSONDecodeError as error:
            message = "response is not valid JSON"
            raise AviationError(message) from error
        reports = parse_metars(payload)
        if not reports:
            return None
        return min(
            reports,
            key=lambda report: _haversine_km(coordinates, report.coordinates),
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
