"""Pure parsers that convert open-meteo JSON payloads into typed models.

These functions take already-decoded JSON (an ``object``) and validate its shape
explicitly, so the rest of the codebase never handles loosely typed payloads. They
perform no I/O and are safe to unit test without network access.
"""

from typing import cast

from weather_agent.models import (
    CurrentReadings,
    CurrentWeather,
    DayAlmanac,
    DroneFlightHour,
    DroneForecast,
    Elevation,
    GeocodeResult,
    KpForecastEntry,
    KpIndex,
    TimeSeries,
    UvIndex,
)

# Non-variable keys open-meteo includes in a ``current`` block.
_CURRENT_META_KEYS = frozenset({"time", "interval"})


class OpenMeteoError(RuntimeError):
    """Raised when an open-meteo payload is missing or has an unexpected shape."""

    def __init__(self, context: str) -> None:
        """Build an error naming the payload location that failed validation.

        Args:
            context: Short description of the field or block that was invalid.
        """
        super().__init__(f"Malformed open-meteo payload: {context}")


class SpaceWeatherError(RuntimeError):
    """Raised when a NOAA SWPC payload is missing or has an unexpected shape."""

    def __init__(self, context: str) -> None:
        """Build an error naming the payload location that failed validation.

        Args:
            context: Short description of the field or row that was invalid.
        """
        super().__init__(f"Malformed space-weather payload: {context}")


def _require_mapping(value: object, context: str) -> dict[str, object]:
    # Decoded JSON objects are dict[str, Any]; narrow the validated value to the
    # repo-wide typed shape at this boundary so callers stay strongly typed.
    if not isinstance(value, dict):
        raise OpenMeteoError(context)
    return cast("dict[str, object]", value)


def _require_list(value: object, context: str) -> list[object]:
    # JSON arrays decode to list[Any]; narrow to list[object] at the boundary.
    if not isinstance(value, list):
        raise OpenMeteoError(context)
    return cast("list[object]", value)


def _require_str(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise OpenMeteoError(key)
    return value


def _require_float(mapping: dict[str, object], key: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OpenMeteoError(key)
    return float(value)


def _coerce_float_or_none(value: object, context: str) -> float | None:
    # Open-meteo emits JSON null for missing samples within a column.
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OpenMeteoError(context)
    return float(value)


def _optional_str(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    return value if isinstance(value, str) else ""


def _optional_int(mapping: dict[str, object], key: str) -> int | None:
    value = mapping.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _parse_geocode_entry(entry: object) -> GeocodeResult:
    mapping = _require_mapping(entry, "geocoding result entry")
    return GeocodeResult(
        name=_require_str(mapping, "name"),
        country=_optional_str(mapping, "country"),
        country_code=_optional_str(mapping, "country_code"),
        admin1=_optional_str(mapping, "admin1"),
        population=_optional_int(mapping, "population"),
        latitude=_require_float(mapping, "latitude"),
        longitude=_require_float(mapping, "longitude"),
    )


def parse_geocode_results(payload: object) -> list[GeocodeResult]:
    """Parse a geocoding-API payload into geocode results.

    Args:
        payload: Decoded JSON from the open-meteo geocoding endpoint.

    Returns:
        The list of matches, which is empty when the API reports no results.

    Raises:
        OpenMeteoError: If the payload is not an object or a result entry has an
            unexpected shape.
    """
    body = _require_mapping(payload, "geocoding response")
    raw_results = body.get("results")
    if raw_results is None:
        return []
    entries = _require_list(raw_results, "geocoding results")
    return [_parse_geocode_entry(entry) for entry in entries]


def parse_current_weather(payload: object) -> CurrentWeather:
    """Parse a forecast-API payload into the current weather block.

    Args:
        payload: Decoded JSON from the open-meteo forecast endpoint, requested
            with ``current=temperature_2m,wind_speed_10m``.

    Returns:
        The current weather conditions.

    Raises:
        OpenMeteoError: If the payload or its ``current`` block is missing or has
            an unexpected shape.
    """
    body = _require_mapping(payload, "forecast response")
    current = _require_mapping(body.get("current"), "current weather block")
    return CurrentWeather(
        time=_require_str(current, "time"),
        temperature_celsius=_require_float(current, "temperature_2m"),
        wind_speed_kmh=_require_float(current, "wind_speed_10m"),
        weather_code=_coerce_float_or_none(current.get("weather_code"), "weather_code"),
        relative_humidity_pct=_coerce_float_or_none(
            current.get("relative_humidity_2m"), "relative_humidity_2m"
        ),
        dew_point_celsius=_coerce_float_or_none(current.get("dew_point_2m"), "dew_point_2m"),
        surface_pressure_hpa=_coerce_float_or_none(
            current.get("surface_pressure"), "surface_pressure"
        ),
        cloud_cover_pct=_coerce_float_or_none(current.get("cloud_cover"), "cloud_cover"),
    )


def parse_uv_index(payload: object) -> UvIndex:
    """Parse a forecast payload requested for UV (current value + daily maximum).

    Expects ``current=uv_index`` and ``daily=uv_index_max``; reads the present
    value from the ``current`` block and today's peak from the first ``daily`` row.

    Args:
        payload: Decoded JSON from the forecast endpoint.

    Returns:
        The current UV index and today's maximum (each ``None`` when absent).

    Raises:
        OpenMeteoError: If the payload or its ``current`` block is missing or has
            an unexpected shape, or the current ``time`` is absent or non-string.
    """
    body = _require_mapping(payload, "uv response")
    current = _require_mapping(body.get("current"), "current uv block")
    daily = parse_time_series(payload, "daily")
    maxima = daily.series.get("uv_index_max", ())
    return UvIndex(
        time=_require_str(current, "time"),
        current=_coerce_float_or_none(current.get("uv_index"), "uv_index"),
        today_max=maxima[0] if maxima else None,
    )


def _string_at(items: list[object], index: int) -> str:
    if index < len(items):
        value = items[index]
        if isinstance(value, str):
            return value
    return ""


def _string_column(raw: object, count: int) -> list[str]:
    # Sun times are ISO strings, not floats, so they bypass the numeric series.
    # A missing or short column degrades to empty strings rather than raising.
    if not isinstance(raw, list):
        return [""] * count
    items = cast("list[object]", raw)
    return [_string_at(items, index) for index in range(count)]


def _optional_float_column(raw: object, count: int) -> list[float | None]:
    if not isinstance(raw, list):
        return [None] * count
    items = cast("list[object]", raw)
    return [
        _coerce_float_or_none(items[i], "daylight_duration") if i < len(items) else None
        for i in range(count)
    ]


def parse_daily_almanac(payload: object) -> tuple[DayAlmanac, ...]:
    """Parse a daily sun-times payload (sunrise/sunset/daylight) into almanac rows.

    Sunrise and sunset arrive as ISO strings, so they bypass the numeric
    :class:`TimeSeries` and are read directly here.

    Args:
        payload: Decoded JSON from the forecast endpoint requested with
            ``daily=sunrise,sunset,daylight_duration``.

    Returns:
        One :class:`DayAlmanac` per day, in chronological order.

    Raises:
        OpenMeteoError: If the payload, its ``daily`` block, or the ``time`` array
            is missing or has an unexpected shape.
    """
    body = _require_mapping(payload, "almanac response")
    block = _require_mapping(body.get("daily"), "daily block")
    raw_dates = _require_list(block.get("time"), "daily time array")
    dates = [_require_str_value(value, "daily date") for value in raw_dates]
    sunrises = _string_column(block.get("sunrise"), len(dates))
    sunsets = _string_column(block.get("sunset"), len(dates))
    daylight = _optional_float_column(block.get("daylight_duration"), len(dates))
    return tuple(
        DayAlmanac(
            date=dates[index],
            sunrise=sunrises[index],
            sunset=sunsets[index],
            daylight_seconds=daylight[index],
        )
        for index in range(len(dates))
    )


def parse_current_readings(payload: object) -> CurrentReadings:
    """Parse the ``current`` block shared by the air-quality and marine APIs.

    These endpoints, when queried with ``current=<variables>``, return
    ``{"current": {"time": ..., "interval": ..., "<variable>": <scalar>, ...}}``
    reporting the present hour. This validates that shape and extracts every
    variable scalar (ignoring the ``time``/``interval`` metadata), so callers get
    "now" instead of the first row of an hourly series.

    Args:
        payload: Decoded JSON from an endpoint queried with ``current=...``.

    Returns:
        The current-hour readings; a variable whose value is ``null`` maps to
        ``None``.

    Raises:
        OpenMeteoError: If the payload or its ``current`` block is missing or has
            an unexpected shape, or the ``time`` field is absent or non-string.
    """
    body = _require_mapping(payload, "current response")
    current = _require_mapping(body.get("current"), "current block")
    time = _require_str(current, "time")
    values = {
        key: _coerce_float_or_none(value, key)
        for key, value in current.items()
        if key not in _CURRENT_META_KEYS
    }
    return CurrentReadings(time=time, values=values)


def _parse_column(raw: object, row_count: int, variable: str) -> tuple[float | None, ...]:
    values = _require_list(raw, f"time-series column '{variable}'")
    if len(values) != row_count:
        message = f"time-series column '{variable}' length mismatch"
        raise OpenMeteoError(message)
    return tuple(_coerce_float_or_none(value, f"value in '{variable}'") for value in values)


def parse_time_series(payload: object, block: str) -> TimeSeries:
    """Parse a column-oriented time-series block shared by open-meteo APIs.

    The forecast, archive, climate, air-quality, marine, flood, and ensemble
    endpoints all return ``{block: {"time": [...], "<variable>": [...], ...}}``
    where every variable column is parallel to ``time``. This validates that
    shape and converts it into a :class:`TimeSeries`.

    Args:
        payload: Decoded JSON from any open-meteo time-series endpoint.
        block: The block name to extract, for example ``"hourly"`` or ``"daily"``.

    Returns:
        The parsed time series with one column per non-``time`` variable.

    Raises:
        OpenMeteoError: If the payload, the block, the ``time`` array, or any
            variable column is missing or has an unexpected shape (including a
            column whose length does not match ``time``).
    """
    body = _require_mapping(payload, f"{block} response")
    block_body = _require_mapping(body.get(block), f"{block} block")
    raw_time = _require_list(block_body.get("time"), f"{block} time array")
    timestamps = tuple(_require_str_value(value, f"{block} timestamp") for value in raw_time)
    series = {
        variable: _parse_column(raw_column, len(timestamps), variable)
        for variable, raw_column in block_body.items()
        if variable != "time"
    }
    return TimeSeries(timestamps=timestamps, series=series)


def _require_str_value(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise OpenMeteoError(context)
    return value


def parse_elevation(payload: object) -> Elevation:
    """Parse an elevation-API payload into a typed elevation.

    Args:
        payload: Decoded JSON from the open-meteo elevation endpoint, which
            returns ``{"elevation": [<metres>]}``.

    Returns:
        The terrain elevation for the requested coordinate.

    Raises:
        OpenMeteoError: If the payload or its ``elevation`` array is missing or
            has an unexpected shape.
    """
    body = _require_mapping(payload, "elevation response")
    values = _require_list(body.get("elevation"), "elevation array")
    if not values:
        empty_message = "empty elevation array"
        raise OpenMeteoError(empty_message)
    meters = _coerce_float_or_none(values[0], "elevation value")
    if meters is None:
        null_message = "null elevation value"
        raise OpenMeteoError(null_message)
    return Elevation(meters=meters)


# Drone forecast: fixed-height winds within the 0-500 m AGL band, plus
# pressure levels that bracket ~500 m AGL at low UK elevations. The pressure
# levels are only counted when their geopotential height falls inside the band.
_GUST_VARIABLE = "wind_gusts_10m"
_FIXED_HEIGHT_WIND_VARIABLES = (
    "wind_speed_10m",
    "wind_speed_80m",
    "wind_speed_120m",
    "wind_speed_180m",
)
_PRESSURE_LEVELS_HPA = (950, 925, 900)
_MAX_AGL_METRES = 500.0

DRONE_HOURLY_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "wind_gusts_10m",
    "wind_speed_10m",
    "wind_speed_80m",
    "wind_speed_120m",
    "wind_speed_180m",
    "precipitation",
    "precipitation_probability",
    "visibility",
    "cape",
    "freezing_level_height",
    "is_day",
    "cloud_cover_low",
    "wind_speed_950hPa",
    "wind_speed_925hPa",
    "wind_speed_900hPa",
    "geopotential_height_950hPa",
    "geopotential_height_925hPa",
    "geopotential_height_900hPa",
)
# Hourly variables requested for a drone forecast (the parser reads these).

DRONE_HOURLY_REQUEST = ",".join(DRONE_HOURLY_VARIABLES)
# Comma-joined form of DRONE_HOURLY_VARIABLES for the query string.


def _cell(series: TimeSeries, variable: str, index: int) -> float | None:
    column = series.series.get(variable)
    return column[index] if column is not None else None


def _derive_wind_max_0_500m(series: TimeSeries, index: int, elevation_m: float) -> float | None:
    # Deliberately conservative (safety-biased): the surface *gust* is compared
    # against *sustained* winds aloft and the strongest wins, so the result over-
    # rather than under-states the wind a drone must hold against. Do not "fix".
    candidates: list[float] = []
    for variable in (_GUST_VARIABLE, *_FIXED_HEIGHT_WIND_VARIABLES):
        value = _cell(series, variable, index)
        if value is not None:
            candidates.append(value)
    for hpa in _PRESSURE_LEVELS_HPA:
        wind = _cell(series, f"wind_speed_{hpa}hPa", index)
        height = _cell(series, f"geopotential_height_{hpa}hPa", index)
        if (
            wind is not None
            and height is not None
            and 0.0 <= height - elevation_m <= _MAX_AGL_METRES
        ):
            candidates.append(wind)
    return max(candidates) if candidates else None


def _freezing_level_agl(series: TimeSeries, index: int, elevation_m: float) -> float | None:
    raw = _cell(series, "freezing_level_height", index)
    return None if raw is None else raw - elevation_m


def _parse_drone_hour(series: TimeSeries, index: int, elevation_m: float) -> DroneFlightHour:
    is_day_value = _cell(series, "is_day", index)
    return DroneFlightHour(
        time=series.timestamps[index],
        temperature_c=_cell(series, "temperature_2m", index),
        apparent_temperature_c=_cell(series, "apparent_temperature", index),
        wind_gust_10m_kmh=_cell(series, "wind_gusts_10m", index),
        wind_max_0_500m_kmh=_derive_wind_max_0_500m(series, index, elevation_m),
        precipitation_mm=_cell(series, "precipitation", index),
        precipitation_probability_pct=_cell(series, "precipitation_probability", index),
        visibility_m=_cell(series, "visibility", index),
        cape=_cell(series, "cape", index),
        freezing_level_agl_m=_freezing_level_agl(series, index, elevation_m),
        is_day=None if is_day_value is None else bool(is_day_value),
        cloud_cover_low_pct=_cell(series, "cloud_cover_low", index),
    )


def parse_drone_forecast(payload: object) -> DroneForecast:
    """Parse a drone-tuned forecast payload into typed per-hour flight metrics.

    Reads the model surface ``elevation`` and the ``hourly`` block (validated via
    :func:`parse_time_series`), then derives each hour's worst 0-500 m AGL wind
    from the fixed-height and in-band pressure-level winds.

    Args:
        payload: Decoded JSON from the open-meteo forecast endpoint requested with
            :data:`DRONE_HOURLY_REQUEST` and pressure-level wind variables.

    Returns:
        The parsed drone forecast.

    Raises:
        OpenMeteoError: If the payload, its ``elevation``, or its ``hourly`` block
            is missing or has an unexpected shape.
    """
    body = _require_mapping(payload, "drone forecast response")
    elevation_m = _require_float(body, "elevation")
    series = parse_time_series(payload, "hourly")
    hours = tuple(
        _parse_drone_hour(series, index, elevation_m) for index in range(len(series.timestamps))
    )
    return DroneForecast(elevation_m=elevation_m, hours=hours)


def _coerce_kp_value(value: object) -> float:
    message = "non-numeric Kp value"
    if isinstance(value, bool):
        raise SpaceWeatherError(message)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as error:
            raise SpaceWeatherError(message) from error
    raise SpaceWeatherError(message)


def parse_kp(payload: object) -> KpIndex:
    """Parse a NOAA SWPC planetary K-index payload into the latest reading.

    The endpoint returns a CSV-style array of arrays whose first row is a header
    (``["time_tag", "Kp", ...]``) and whose remaining rows are observations in
    chronological order. The most recent row is the last one.

    Args:
        payload: Decoded JSON from the NOAA planetary K-index product.

    Returns:
        The latest planetary K-index reading.

    Raises:
        SpaceWeatherError: If the payload has no data rows or an unexpected shape.
    """
    if not isinstance(payload, list):
        not_list_message = "planetary Kp response"
        raise SpaceWeatherError(not_list_message)
    rows = cast("list[object]", payload)
    data_rows = rows[1:]
    if not data_rows:
        empty_message = "empty planetary Kp data"
        raise SpaceWeatherError(empty_message)
    last = _require_kp_row(data_rows[-1])
    time_value = last[0]
    if not isinstance(time_value, str):
        time_message = "non-string Kp timestamp"
        raise SpaceWeatherError(time_message)
    return KpIndex(time=time_value, kp=_coerce_kp_value(last[1]))


_MIN_KP_ROW_FIELDS = 2


def _require_kp_row(value: object) -> list[object]:
    if not isinstance(value, list) or len(cast("list[object]", value)) < _MIN_KP_ROW_FIELDS:
        message = "malformed planetary Kp row"
        raise SpaceWeatherError(message)
    return cast("list[object]", value)


def parse_kp_forecast(payload: object) -> tuple[KpForecastEntry, ...]:
    """Parse the NOAA SWPC 3-day planetary K-index forecast.

    Same array-of-arrays shape as the nowcast: a header row followed by one row
    per 3-hour bucket (``[time_tag, kp, ...]``) in UTC and chronological order.

    Args:
        payload: Decoded JSON from the NOAA planetary K-index forecast product.

    Returns:
        The predicted buckets in chronological order; empty when none are present.

    Raises:
        SpaceWeatherError: If the payload is not a list or a row is malformed.
    """
    if not isinstance(payload, list):
        not_list_message = "planetary Kp forecast response"
        raise SpaceWeatherError(not_list_message)
    rows = cast("list[object]", payload)
    entries: list[KpForecastEntry] = []
    for row in rows[1:]:
        fields = _require_kp_row(row)
        time_value = fields[0]
        if not isinstance(time_value, str):
            time_message = "non-string Kp forecast timestamp"
            raise SpaceWeatherError(time_message)
        entries.append(KpForecastEntry(time=time_value, kp=_coerce_kp_value(fields[1])))
    return tuple(entries)
