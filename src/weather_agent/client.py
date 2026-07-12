"""HTTP boundary adapter for the open-meteo geocoding and forecast APIs.

This module is the only place that performs network I/O. It converts raw JSON
responses into typed models via :mod:`weather_agent.parsing`, keeping the rest of
the codebase free of loosely typed payloads.
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import httpx

from weather_agent.parsing import (
    DRONE_HOURLY_REQUEST,
    OpenMeteoError,
    parse_current_readings,
    parse_current_weather,
    parse_daily_almanac,
    parse_drone_forecast,
    parse_elevation,
    parse_geocode_results,
    parse_time_series,
    parse_uv_index,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from weather_agent.models import (
        ClimateRequest,
        Coordinates,
        CurrentReadings,
        CurrentWeather,
        DayAlmanac,
        DroneForecast,
        Elevation,
        GeocodeResult,
        HistoricalRequest,
        TimeSeries,
        UvIndex,
    )

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_CLIMATE_URL = "https://climate-api.open-meteo.com/v1/climate"
_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
_FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
_ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_TIMEZONE = "Europe/London"
_CURRENT_WEATHER_REQUEST = (
    "temperature_2m,wind_speed_10m,weather_code,"
    "relative_humidity_2m,dew_point_2m,surface_pressure,cloud_cover"
)
_TIME_PARAMETERS: dict[str, str] = {"timezone": "auto", "timeformat": "unixtime"}
ARCHIVE_START_DATE = date(1940, 1, 1)
CLIMATE_START_DATE = date(1950, 1, 1)
CLIMATE_END_DATE = date(2050, 1, 1)
MAX_DAILY_RANGE_DAYS = 3660
_FORECAST_PAST_DAYS = 92
_FORECAST_FUTURE_DAYS = 16
_ARCHIVE_LATENCY_DAYS = 5


def _daily_dates(series: TimeSeries) -> tuple[date, ...]:
    dates: list[date] = []
    for value in series.timestamps:
        if isinstance(value, datetime):
            message = "daily response contains an instant instead of a calendar date"
            raise OpenMeteoError(message)
        dates.append(value)
    return tuple(dates)


def _validate_daily_range(series: TimeSeries, start: date, end: date) -> None:
    dates = _daily_dates(series)
    if any(day < start or day > end for day in dates):
        message = f"daily response contains dates outside {start} to {end}"
        raise OpenMeteoError(message)


def _validate_request_range(
    start: date,
    end: date,
    lower: date,
    upper: date,
    label: str,
) -> None:
    if start > end:
        msg = "start date must not follow end date"
        raise ValueError(msg)
    if start < lower or end > upper:
        message = f"{label} dates must be between {lower} and {upper}"
        raise ValueError(message)
    if (end - start).days + 1 > MAX_DAILY_RANGE_DAYS:
        message = f"{label} range must not exceed {MAX_DAILY_RANGE_DAYS} days"
        raise ValueError(message)


class OpenMeteoClient:
    """Thin synchronous client over the open-meteo REST APIs.

    The open-meteo APIs require no API key. A pre-configured ``httpx.Client`` may
    be injected to control transport and timeouts, which is how tests avoid real
    network access.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        today: date | None = None,
    ) -> None:
        """Create the client.

        Args:
            client: An existing ``httpx.Client`` to use. When omitted, a new one
                is created with the given timeout.
            timeout: Per-request timeout in seconds for the internally created
                client. Ignored when ``client`` is provided.
            today: Optional UTC reference date for dynamic provider windows. Tests
                inject this seam; production defaults to the actual UTC date.
        """
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._today = today if today is not None else datetime.now(UTC).date()

    def _get_json(self, url: str, params: Mapping[str, str | int | float]) -> object:
        """Issue a GET request and return the decoded JSON body.

        Centralises the request/raise/decode pattern so every endpoint method
        differs only by URL and query parameters.

        Args:
            url: Absolute endpoint URL (open-meteo hosts differ per API).
            params: Query parameters for the request.

        Returns:
            The decoded JSON body as an untyped object for a parser to validate.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If a successful response is not valid JSON.
        """
        response = self._client.get(url, params=params)
        _ = response.raise_for_status()
        try:
            payload: object = response.json()
        except json.JSONDecodeError as error:
            message = "response is not valid JSON"
            raise OpenMeteoError(message) from error
        return payload

    def geocode(self, name: str, count: int = 10) -> list[GeocodeResult]:
        """Resolve a place name to candidate coordinates.

        Several candidates are requested by default so callers can disambiguate
        namesakes (for example small towns sharing a name) rather than blindly
        taking the first hit.

        Args:
            name: The place name to look up, for example ``"Berlin"``.
            count: Maximum number of matches to request.

        Returns:
            Matching locations ordered by relevance; empty when none match.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _GEOCODING_URL,
            {"name": name, "count": count, "format": "json"},
        )
        return parse_geocode_results(payload)

    def current_weather(self, coordinates: Coordinates) -> CurrentWeather:
        """Fetch current weather for a coordinate.

        Args:
            coordinates: Validated WGS84 coordinate pair.

        Returns:
            The current weather conditions at the coordinate.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _FORECAST_URL,
            {
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "current": _CURRENT_WEATHER_REQUEST,
                **_TIME_PARAMETERS,
            },
        )
        return parse_current_weather(payload)

    def daily_almanac(
        self,
        coordinates: Coordinates,
        forecast_days: int = 1,
        timezone: str = "auto",
    ) -> tuple[DayAlmanac, ...]:
        """Fetch daily sun times (sunrise/sunset/daylight) for a coordinate.

        Uses ``timezone=auto`` by default so the sun times are the location's local
        times rather than UTC.

        Args:
            coordinates: Validated WGS84 coordinate pair.
            forecast_days: Number of days to fetch (today onward).
            timezone: IANA timezone name, or ``"auto"`` for the location's zone.

        Returns:
            One almanac row per day, in chronological order.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _FORECAST_URL,
            {
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "daily": "sunrise,sunset,daylight_duration",
                "forecast_days": forecast_days,
                "timezone": timezone,
                "timeformat": "unixtime",
            },
        )
        return parse_daily_almanac(payload)

    def uv_index(self, coordinates: Coordinates) -> UvIndex:
        """Fetch the current UV index and today's maximum for a coordinate.

        Uses ``timezone=auto`` so "today" and its peak are aligned to the
        location's local day rather than UTC.

        Args:
            coordinates: Validated WGS84 coordinate pair.

        Returns:
            The current UV index and today's forecast maximum.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _FORECAST_URL,
            {
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "current": "uv_index",
                "daily": "uv_index_max",
                "forecast_days": 1,
                **_TIME_PARAMETERS,
            },
        )
        return parse_uv_index(payload)

    def drone_forecast(
        self,
        coordinates: Coordinates,
        forecast_days: int,
        timezone: str = _DEFAULT_TIMEZONE,
    ) -> DroneForecast:
        """Fetch a drone-tuned hourly forecast for a coordinate.

        Requests the full drone variable set plus pressure-level winds and
        geopotential heights needed to derive winds up to 500 m AGL. Timestamps
        and the daylight flag are localised via ``timezone``.

        Args:
            coordinates: Validated WGS84 coordinate pair.
            forecast_days: Number of forecast days to request (the drone domain
                passes its own short window rather than a client-side default).
            timezone: IANA timezone name for localised timestamps.

        Returns:
            The parsed drone forecast.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _FORECAST_URL,
            {
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "hourly": DRONE_HOURLY_REQUEST,
                "forecast_days": forecast_days,
                "timezone": timezone,
                "timeformat": "unixtime",
            },
        )
        return parse_drone_forecast(payload)

    def forecast_series(
        self,
        coordinates: Coordinates,
        daily: str,
        forecast_days: int,
    ) -> TimeSeries:
        """Fetch a multi-day daily forecast time series.

        Args:
            coordinates: Validated WGS84 coordinate pair.
            daily: Comma-separated daily variable list.
            forecast_days: Number of forecast days to request.

        Returns:
            The daily forecast time series.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _FORECAST_URL,
            {
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "daily": daily,
                "forecast_days": forecast_days,
                **_TIME_PARAMETERS,
            },
        )
        return parse_time_series(payload, "daily")

    def forecast_day_series(
        self,
        coordinates: Coordinates,
        daily: str,
        day: date,
    ) -> TimeSeries:
        """Fetch one calendar day's daily forecast series by explicit date.

        Uses ``start_date``/``end_date`` so a specific day is returned, including
        the recent past that the ERA5 archive has not yet published. The forecast
        endpoint covers roughly the last 92 days through the forecast horizon.

        Args:
            coordinates: Validated WGS84 coordinate pair.
            daily: Comma-separated daily variable list.
            day: The ISO-8601 date (``YYYY-MM-DD``) to fetch.

        Returns:
            The daily forecast time series for that single day.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        _validate_request_range(
            day,
            day,
            self._today - timedelta(days=_FORECAST_PAST_DAYS),
            self._today + timedelta(days=_FORECAST_FUTURE_DAYS),
            "forecast",
        )
        payload = self._get_json(
            _FORECAST_URL,
            {
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "daily": daily,
                "start_date": day.isoformat(),
                "end_date": day.isoformat(),
                **_TIME_PARAMETERS,
            },
        )
        series = parse_time_series(payload, "daily")
        dates = _daily_dates(series)
        if dates != (day,):
            message = f"explicit-day response did not contain exactly {day}"
            raise OpenMeteoError(message)
        return series

    def historical_series(self, request: HistoricalRequest) -> TimeSeries:
        """Fetch a daily historical (ERA5 archive) time series.

        Args:
            request: The validated archive query parameters.

        Returns:
            The daily historical time series for the requested date range.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        _validate_request_range(
            request.start_date,
            request.end_date,
            ARCHIVE_START_DATE,
            self._today - timedelta(days=_ARCHIVE_LATENCY_DAYS),
            "archive",
        )
        payload = self._get_json(
            _ARCHIVE_URL,
            {
                "latitude": request.coordinates.latitude,
                "longitude": request.coordinates.longitude,
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "daily": request.daily,
                **_TIME_PARAMETERS,
            },
        )
        series = parse_time_series(payload, "daily")
        _validate_daily_range(series, request.start_date, request.end_date)
        return series

    def climate_projection(self, request: ClimateRequest) -> TimeSeries:
        """Fetch a daily climate (CMIP6) projection time series.

        Args:
            request: The validated climate query parameters.

        Returns:
            The daily projected time series for the requested date range.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        _validate_request_range(
            request.start_date,
            request.end_date,
            CLIMATE_START_DATE,
            CLIMATE_END_DATE,
            "climate",
        )
        payload = self._get_json(
            _CLIMATE_URL,
            {
                "latitude": request.coordinates.latitude,
                "longitude": request.coordinates.longitude,
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "daily": request.daily,
                "models": request.models,
                **_TIME_PARAMETERS,
            },
        )
        series = parse_time_series(payload, "daily")
        _validate_daily_range(series, request.start_date, request.end_date)
        return series

    def air_quality_current(
        self,
        coordinates: Coordinates,
        current: str,
    ) -> CurrentReadings:
        """Fetch current-hour air-quality readings.

        Uses the ``current`` block so the readings are for the present hour rather
        than the start of the day (which an hourly series would report at row 0).

        Args:
            coordinates: Validated WGS84 coordinate pair.
            current: Comma-separated variable list (for example
                ``"pm2_5,pm10,ozone,european_aqi"``).

        Returns:
            The current-hour air-quality readings.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _AIR_QUALITY_URL,
            {
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "current": current,
                **_TIME_PARAMETERS,
            },
        )
        return parse_current_readings(payload)

    def marine_current(self, coordinates: Coordinates, current: str) -> CurrentReadings:
        """Fetch current-hour marine (wave) readings.

        Uses the ``current`` block so the readings are for the present hour rather
        than the start of the day.

        Args:
            coordinates: Validated WGS84 coordinate pair.
            current: Comma-separated variable list (for example
                ``"wave_height,wave_period"``).

        Returns:
            The current-hour marine readings.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _MARINE_URL,
            {
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "current": current,
                **_TIME_PARAMETERS,
            },
        )
        return parse_current_readings(payload)

    def river_discharge_series(self, coordinates: Coordinates, daily: str) -> TimeSeries:
        """Fetch a daily river-discharge (flood) time series.

        Args:
            coordinates: Validated WGS84 coordinate pair.
            daily: Comma-separated daily variable list (for example
                ``"river_discharge"``).

        Returns:
            The daily river-discharge time series.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _FLOOD_URL,
            {
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "daily": daily,
                **_TIME_PARAMETERS,
            },
        )
        return parse_time_series(payload, "daily")

    def ensemble_series(
        self,
        coordinates: Coordinates,
        hourly: str,
        models: str,
    ) -> TimeSeries:
        """Fetch an hourly ensemble time series with per-member columns.

        Args:
            coordinates: Validated WGS84 coordinate pair.
            hourly: Comma-separated hourly variable list (for example
                ``"temperature_2m"``).
            models: Ensemble model identifier (for example ``"icon_seamless"``).

        Returns:
            The hourly ensemble time series; columns include per-member variants.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _ENSEMBLE_URL,
            {
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "hourly": hourly,
                "models": models,
                "forecast_hours": 1,
                **_TIME_PARAMETERS,
            },
        )
        return parse_time_series(payload, "hourly")

    def elevation(self, coordinates: Coordinates) -> Elevation:
        """Fetch terrain elevation for a coordinate.

        Args:
            coordinates: Validated WGS84 coordinate pair.

        Returns:
            The terrain elevation at the coordinate.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _ELEVATION_URL,
            {"latitude": coordinates.latitude, "longitude": coordinates.longitude},
        )
        return parse_elevation(payload)

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
