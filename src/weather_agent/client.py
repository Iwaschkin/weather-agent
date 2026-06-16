"""HTTP boundary adapter for the open-meteo geocoding and forecast APIs.

This module is the only place that performs network I/O. It converts raw JSON
responses into typed models via :mod:`weather_agent.parsing`, keeping the rest of
the codebase free of loosely typed payloads.
"""

from typing import TYPE_CHECKING

import httpx

from weather_agent.parsing import (
    DRONE_HOURLY_REQUEST,
    parse_current_readings,
    parse_current_weather,
    parse_drone_forecast,
    parse_elevation,
    parse_geocode_results,
    parse_kp,
    parse_time_series,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from weather_agent.models import (
        ClimateRequest,
        CurrentReadings,
        CurrentWeather,
        DroneForecast,
        Elevation,
        GeocodeResult,
        HistoricalRequest,
        KpIndex,
        TimeSeries,
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
_PLANETARY_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_TIMEZONE = "Europe/London"


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
    ) -> None:
        """Create the client.

        Args:
            client: An existing ``httpx.Client`` to use. When omitted, a new one
                is created with the given timeout.
            timeout: Per-request timeout in seconds for the internally created
                client. Ignored when ``client`` is provided.
        """
        self._client = client if client is not None else httpx.Client(timeout=timeout)

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
        """
        response = self._client.get(url, params=params)
        _ = response.raise_for_status()
        return response.json()

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

    def current_weather(self, latitude: float, longitude: float) -> CurrentWeather:
        """Fetch current weather for a coordinate.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.

        Returns:
            The current weather conditions at the coordinate.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _FORECAST_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,wind_speed_10m",
            },
        )
        return parse_current_weather(payload)

    def drone_forecast(
        self,
        latitude: float,
        longitude: float,
        forecast_days: int,
        timezone: str = _DEFAULT_TIMEZONE,
    ) -> DroneForecast:
        """Fetch a drone-tuned hourly forecast for a coordinate.

        Requests the full drone variable set plus pressure-level winds and
        geopotential heights needed to derive winds up to 500 m AGL. Timestamps
        and the daylight flag are localised via ``timezone``.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
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
                "latitude": latitude,
                "longitude": longitude,
                "hourly": DRONE_HOURLY_REQUEST,
                "forecast_days": forecast_days,
                "timezone": timezone,
            },
        )
        return parse_drone_forecast(payload)

    def geomagnetic_kp(self) -> KpIndex:
        """Fetch the latest planetary K-index from NOAA SWPC.

        Unlike the open-meteo endpoints this targets the NOAA Space Weather
        Prediction Center, but the request pattern is identical.

        Returns:
            The latest planetary K-index reading.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            SpaceWeatherError: If the response shape is unexpected.
        """
        payload = self._get_json(_PLANETARY_KP_URL, {})
        return parse_kp(payload)

    def forecast_series(
        self,
        latitude: float,
        longitude: float,
        daily: str,
        forecast_days: int,
    ) -> TimeSeries:
        """Fetch a multi-day daily forecast time series.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
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
                "latitude": latitude,
                "longitude": longitude,
                "daily": daily,
                "forecast_days": forecast_days,
                "timezone": "UTC",
            },
        )
        return parse_time_series(payload, "daily")

    def forecast_day_series(
        self,
        latitude: float,
        longitude: float,
        daily: str,
        day: str,
    ) -> TimeSeries:
        """Fetch one calendar day's daily forecast series by explicit date.

        Uses ``start_date``/``end_date`` so a specific day is returned, including
        the recent past that the ERA5 archive has not yet published. The forecast
        endpoint covers roughly the last 92 days through the forecast horizon.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
            daily: Comma-separated daily variable list.
            day: The ISO-8601 date (``YYYY-MM-DD``) to fetch.

        Returns:
            The daily forecast time series for that single day.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _FORECAST_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "daily": daily,
                "start_date": day,
                "end_date": day,
                "timezone": "UTC",
            },
        )
        return parse_time_series(payload, "daily")

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
        payload = self._get_json(
            _ARCHIVE_URL,
            {
                "latitude": request.latitude,
                "longitude": request.longitude,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "daily": request.daily,
                "timezone": "UTC",
            },
        )
        return parse_time_series(payload, "daily")

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
        payload = self._get_json(
            _CLIMATE_URL,
            {
                "latitude": request.latitude,
                "longitude": request.longitude,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "daily": request.daily,
                "models": request.models,
            },
        )
        return parse_time_series(payload, "daily")

    def air_quality_current(
        self,
        latitude: float,
        longitude: float,
        current: str,
    ) -> CurrentReadings:
        """Fetch current-hour air-quality readings.

        Uses the ``current`` block so the readings are for the present hour rather
        than the start of the day (which an hourly series would report at row 0).

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
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
            {"latitude": latitude, "longitude": longitude, "current": current, "timezone": "UTC"},
        )
        return parse_current_readings(payload)

    def marine_current(self, latitude: float, longitude: float, current: str) -> CurrentReadings:
        """Fetch current-hour marine (wave) readings.

        Uses the ``current`` block so the readings are for the present hour rather
        than the start of the day.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
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
            {"latitude": latitude, "longitude": longitude, "current": current, "timezone": "UTC"},
        )
        return parse_current_readings(payload)

    def river_discharge_series(self, latitude: float, longitude: float, daily: str) -> TimeSeries:
        """Fetch a daily river-discharge (flood) time series.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
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
            {"latitude": latitude, "longitude": longitude, "daily": daily},
        )
        return parse_time_series(payload, "daily")

    def ensemble_series(
        self,
        latitude: float,
        longitude: float,
        hourly: str,
        models: str,
    ) -> TimeSeries:
        """Fetch an hourly ensemble time series with per-member columns.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
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
                "latitude": latitude,
                "longitude": longitude,
                "hourly": hourly,
                "models": models,
                "timezone": "UTC",
            },
        )
        return parse_time_series(payload, "hourly")

    def elevation(self, latitude: float, longitude: float) -> Elevation:
        """Fetch terrain elevation for a coordinate.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.

        Returns:
            The terrain elevation at the coordinate.

        Raises:
            httpx.HTTPError: If the request fails or returns an error status.
            OpenMeteoError: If the response shape is unexpected.
        """
        payload = self._get_json(
            _ELEVATION_URL,
            {"latitude": latitude, "longitude": longitude},
        )
        return parse_elevation(payload)

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
