"""Typed NOAA SWPC boundary for planetary Kp observations and forecasts.

NOAA is deliberately separate from the Open-Meteo adapter: it has different
hosts, payload contracts, timestamps, and failure semantics. Raw JSON is
validated here before the assessment layer sees it.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from itertools import pairwise
from typing import cast

import httpx

from weather_agent.models import KpForecastEntry, KpIndex, KpRowKind
from weather_agent.parsing import ExternalDataError

_CURRENT_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
_FORECAST_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
_DEFAULT_TIMEOUT = 10.0
_MIN_KP = 0.0
_MAX_KP = 9.0


class SpaceWeatherError(ExternalDataError):
    """Raised when a NOAA request body is not valid for the advertised product."""

    def __init__(self, context: str) -> None:
        """Build an error naming the provider field or boundary that failed."""
        super().__init__(f"Malformed NOAA space-weather payload: {context}")


def _rows(payload: object, product: str) -> list[object]:
    if not isinstance(payload, list):
        message = f"{product} response must be an array"
        raise SpaceWeatherError(message)
    rows = cast("list[object]", payload)
    if not rows:
        message = f"{product} response contains no rows"
        raise SpaceWeatherError(message)
    return rows


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        message = f"{context} must be an object"
        raise SpaceWeatherError(message)
    return cast("dict[str, object]", value)


def _timestamp(mapping: dict[str, object], context: str) -> datetime:
    value = mapping.get("time_tag")
    if not isinstance(value, str):
        message = f"{context}.time_tag must be a string"
        raise SpaceWeatherError(message)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        message = f"{context}.time_tag is not ISO-8601"
        raise SpaceWeatherError(message) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _kp(mapping: dict[str, object], key: str, context: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        message = f"{context}.{key} must be numeric"
        raise SpaceWeatherError(message)
    result = float(value)
    if not math.isfinite(result) or not _MIN_KP <= result <= _MAX_KP:
        message = f"{context}.{key} must be finite and between 0 and 9"
        raise SpaceWeatherError(message)
    return result


def _require_chronological(times: list[datetime], product: str) -> None:
    if any(current <= previous for previous, current in pairwise(times)):
        message = f"{product} rows must be strictly chronological"
        raise SpaceWeatherError(message)


def parse_kp(payload: object) -> KpIndex:
    """Parse NOAA's current object-row product and return its newest reading.

    NOAA publishes historical rows in chronological order. Every row is checked
    so a malformed tail or ordering drift cannot silently select the wrong
    observation.
    """
    readings: list[KpIndex] = []
    for index, raw in enumerate(_rows(payload, "current Kp")):
        context = f"current Kp row {index}"
        row = _mapping(raw, context)
        readings.append(KpIndex(time=_timestamp(row, context), kp=_kp(row, "Kp", context)))
    _require_chronological([reading.time for reading in readings], "current Kp")
    return readings[-1]


def _row_kind(row: dict[str, object], context: str) -> KpRowKind:
    value = row.get("observed")
    if not isinstance(value, str):
        message = f"{context}.observed must be a string"
        raise SpaceWeatherError(message)
    try:
        return KpRowKind(value)
    except ValueError as error:
        message = f"{context}.observed has an unknown value"
        raise SpaceWeatherError(message) from error


def _noaa_scale(row: dict[str, object], context: str) -> str | None:
    if "noaa_scale" not in row:
        message = f"{context}.noaa_scale is required"
        raise SpaceWeatherError(message)
    value = row.get("noaa_scale")
    if value is None:
        return None
    if not isinstance(value, str):
        message = f"{context}.noaa_scale must be a string or null"
        raise SpaceWeatherError(message)
    return value


def parse_kp_forecast(payload: object) -> tuple[KpForecastEntry, ...]:
    """Parse NOAA's object-row forecast product into typed three-hour buckets."""
    entries: list[KpForecastEntry] = []
    for index, raw in enumerate(_rows(payload, "Kp forecast")):
        context = f"Kp forecast row {index}"
        row = _mapping(raw, context)
        entries.append(
            KpForecastEntry(
                time=_timestamp(row, context),
                kp=_kp(row, "kp", context),
                kind=_row_kind(row, context),
                noaa_scale=_noaa_scale(row, context),
            )
        )
    _require_chronological([entry.time for entry in entries], "Kp forecast")
    return tuple(entries)


class SpaceWeatherClient:
    """Small synchronous client for NOAA's two planetary Kp products."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        """Create the client, optionally using an injected test transport."""
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def _get_json(self, url: str) -> object:
        response = self._client.get(url)
        _ = response.raise_for_status()
        try:
            payload: object = response.json()
        except json.JSONDecodeError as error:
            message = "response is not valid JSON"
            raise SpaceWeatherError(message) from error
        return payload

    def current_kp(self) -> KpIndex:
        """Fetch and validate the latest NOAA planetary Kp observation."""
        return parse_kp(self._get_json(_CURRENT_KP_URL))

    def kp_forecast(self) -> tuple[KpForecastEntry, ...]:
        """Fetch and validate NOAA's observed/estimated/predicted Kp buckets."""
        return parse_kp_forecast(self._get_json(_FORECAST_KP_URL))

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
