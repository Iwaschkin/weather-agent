"""Boundary adapter for OpenAIP airspace data (requires an API key).

A small synchronous client over the OpenAIP Core API. It returns nearby airspace
volumes relevant to low-level (drone) flight, so the assessment can warn about
controlled or restricted airspace to verify before flying. This is decision
support, not an authoritative airspace or NOTAM check.

The API key is read from the ``OPENAIP_API_KEY`` environment variable (loaded
from ``.env`` at the CLI boundary) unless one is passed explicitly. When no key is
available, :attr:`OpenAipClient.has_key` is ``False`` and callers degrade to an
"unavailable" note rather than failing.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import httpx

from weather_agent.parsing import AirspaceError, parse_airspaces

if TYPE_CHECKING:
    from weather_agent.models import Airspace, Coordinates

_AIRSPACES_URL = "https://api.core.openaip.net/api/airspaces"
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_RADIUS_M = 15000
_MAX_RADIUS_M = 100000
_MAX_RESULTS = 50
_API_KEY_ENV = "OPENAIP_API_KEY"

# Airspace type labels (see weather_agent.parsing) relevant to low-level flight;
# higher-altitude structural airspace (TMA, FIR, airways, ...) is filtered out so
# the drone briefing is not buried in irrelevant volumes.
_RELEVANT_TYPE_LABELS = frozenset(
    {"Restricted", "Danger", "Prohibited", "CTR", "TMZ", "RMZ", "ATZ", "MATZ", "MCTR", "HTZ"}
)


def relevant_airspaces(airspaces: tuple[Airspace, ...]) -> tuple[Airspace, ...]:
    """Keep only airspaces whose type matters near the surface for drones."""
    return tuple(a for a in airspaces if a.type_label in _RELEVANT_TYPE_LABELS)


class OpenAipClient:
    """Thin synchronous client over the OpenAIP airspaces API (needs an API key)."""

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        """Create the client.

        Args:
            api_key: The OpenAIP API key; when omitted, read from the
                ``OPENAIP_API_KEY`` environment variable.
            client: An existing ``httpx.Client`` (tests inject a mock transport).
                When omitted, one is created with the given timeout.
            timeout: Per-request timeout in seconds for the internally created
                client. Ignored when ``client`` is provided.
        """
        self._api_key = api_key if api_key is not None else os.environ.get(_API_KEY_ENV, "")
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    @property
    def has_key(self) -> bool:
        """Whether an API key is configured (required for any lookup)."""
        return bool(self._api_key)

    def nearby_airspaces(
        self,
        coordinates: Coordinates,
        radius_m: int = _DEFAULT_RADIUS_M,
    ) -> tuple[Airspace, ...]:
        """Fetch drone-relevant airspaces within a radius of a coordinate.

        Args:
            coordinates: Validated WGS84 coordinate pair.
            radius_m: Search radius around the point, in metres.

        Returns:
            Nearby airspaces filtered to low-level drone-relevant types.

        Raises:
            ValueError: If ``radius_m`` is not an integer from 1 to 100000 metres.
            httpx.HTTPError: If the request fails or returns an error status.
            AirspaceError: If the response shape is unexpected.
        """
        if isinstance(radius_m, bool) or not 1 <= radius_m <= _MAX_RADIUS_M:
            message = f"radius_m must be between 1 and {_MAX_RADIUS_M}"
            raise ValueError(message)
        params: dict[str, str | int] = {
            "pos": f"{coordinates.latitude},{coordinates.longitude}",
            "dist": radius_m,
            "limit": _MAX_RESULTS,
        }
        response = self._client.get(
            _AIRSPACES_URL, params=params, headers={"x-openaip-api-key": self._api_key}
        )
        _ = response.raise_for_status()
        try:
            payload: object = response.json()
        except json.JSONDecodeError as error:
            message = "response is not valid JSON"
            raise AirspaceError(message) from error
        return relevant_airspaces(parse_airspaces(payload))

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
