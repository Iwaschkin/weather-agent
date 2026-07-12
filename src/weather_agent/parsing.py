"""Pure parsers that convert open-meteo JSON payloads into typed models.

These functions take already-decoded JSON (an ``object``) and validate its shape
explicitly, so the rest of the codebase never handles loosely typed payloads. They
perform no I/O and are safe to unit test without network access.
"""

import math
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather_agent.models import (
    Airspace,
    CloudLayer,
    Coordinates,
    CurrentReadings,
    CurrentWeather,
    DayAlmanac,
    DroneFlightHour,
    DroneForecast,
    Elevation,
    GeocodeResult,
    MetarReport,
    TimeContext,
    TimeSeries,
    UvIndex,
)

# Non-variable keys open-meteo includes in a ``current`` block.
_CURRENT_META_KEYS = frozenset({"time", "interval"})
_MAX_UTC_OFFSET_SECONDS = 18 * 60 * 60


class ExternalDataError(RuntimeError):
    """Base for "a third-party payload was missing or malformed" errors.

    Lets boundaries catch every external-payload failure (open-meteo, NOAA,
    aviation, OpenAIP) with one type while keeping a specific subclass per source.
    """


class OpenMeteoError(ExternalDataError):
    """Raised when an open-meteo payload is missing or has an unexpected shape."""

    def __init__(self, context: str) -> None:
        """Build an error naming the payload location that failed validation.

        Args:
            context: Short description of the field or block that was invalid.
        """
        super().__init__(f"Malformed open-meteo payload: {context}")


class AviationError(ExternalDataError):
    """Raised when an aviationweather.gov payload is missing or malformed."""

    def __init__(self, context: str) -> None:
        """Build an error naming the payload location that failed validation.

        Args:
            context: Short description of the field or block that was invalid.
        """
        super().__init__(f"Malformed aviation-weather payload: {context}")


class AirspaceError(ExternalDataError):
    """Raised when an OpenAIP airspace payload is missing or malformed."""

    def __init__(self, context: str) -> None:
        """Build an error naming the payload location that failed validation.

        Args:
            context: Short description of the field or block that was invalid.
        """
        super().__init__(f"Malformed OpenAIP payload: {context}")


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
    result = float(value)
    if not math.isfinite(result):
        raise OpenMeteoError(key)
    return result


def _require_int(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenMeteoError(key)
    return value


def _coerce_float_or_none(value: object, context: str) -> float | None:
    # Open-meteo emits JSON null for missing samples within a column.
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OpenMeteoError(context)
    result = float(value)
    if not math.isfinite(result):
        raise OpenMeteoError(context)
    return result


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
    timezone = _require_str(mapping, "timezone")
    try:
        _ = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        message = f"unknown geocoding timezone '{timezone}'"
        raise OpenMeteoError(message) from error
    try:
        coordinates = Coordinates(
            _require_float(mapping, "latitude"),
            _require_float(mapping, "longitude"),
        )
    except ValueError as error:
        raise OpenMeteoError(str(error)) from error
    return GeocodeResult(
        name=_require_str(mapping, "name"),
        country=_optional_str(mapping, "country"),
        country_code=_optional_str(mapping, "country_code"),
        admin1=_optional_str(mapping, "admin1"),
        population=_optional_int(mapping, "population"),
        coordinates=coordinates,
        timezone=timezone,
    )


def _parse_time_context(body: dict[str, object]) -> TimeContext:
    timezone = _require_str(body, "timezone")
    abbreviation = _require_str(body, "timezone_abbreviation")
    offset = _require_int(body, "utc_offset_seconds")
    if not abbreviation.strip():
        message = "timezone_abbreviation must not be empty"
        raise OpenMeteoError(message)
    if abs(offset) > _MAX_UTC_OFFSET_SECONDS:
        message = "utc_offset_seconds is outside the supported range"
        raise OpenMeteoError(message)
    try:
        _ = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        message = f"unknown timezone '{timezone}'"
        raise OpenMeteoError(message) from error
    return TimeContext(timezone, abbreviation, offset)


def _epoch_datetime(value: object, context: TimeContext, label: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenMeteoError(label)
    try:
        return datetime.fromtimestamp(value, UTC).astimezone(ZoneInfo(context.timezone))
    except (OverflowError, OSError, ValueError) as error:
        message = f"{label} is outside the supported datetime range"
        raise OpenMeteoError(message) from error


def _epoch_date(value: object, context: TimeContext, label: str) -> date:
    return _epoch_datetime(value, context, label).date()


def _time_sort_value(value: date | datetime) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value.toordinal())


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
    time_context = _parse_time_context(body)
    current = _require_mapping(body.get("current"), "current weather block")
    return CurrentWeather(
        time=_epoch_datetime(current.get("time"), time_context, "current weather time"),
        time_context=time_context,
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
            an unexpected shape, or the current time is not a valid Unix instant.
    """
    body = _require_mapping(payload, "uv response")
    time_context = _parse_time_context(body)
    current = _require_mapping(body.get("current"), "current uv block")
    daily = parse_time_series(payload, "daily")
    maxima = daily.series.get("uv_index_max", ())
    return UvIndex(
        time=_epoch_datetime(current.get("time"), time_context, "current uv time"),
        current=_coerce_float_or_none(current.get("uv_index"), "uv_index"),
        today_max=maxima[0] if maxima else None,
        time_context=time_context,
    )


def _datetime_column(
    raw: object,
    count: int,
    context: TimeContext,
    label: str,
) -> list[datetime | None]:
    values = _require_list(raw, label)
    if len(values) != count:
        message = f"{label} length mismatch"
        raise OpenMeteoError(message)
    return [None if value is None else _epoch_datetime(value, context, label) for value in values]


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

    Dates and sun times arrive as Unix instants. They bypass the numeric
    :class:`TimeSeries` because the sun-time columns are nullable datetimes rather
    than weather measurements.

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
    time_context = _parse_time_context(body)
    block = _require_mapping(body.get("daily"), "daily block")
    raw_dates = _require_list(block.get("time"), "daily time array")
    dates = [_epoch_date(value, time_context, "daily date") for value in raw_dates]
    sunrises = _datetime_column(block.get("sunrise"), len(dates), time_context, "sunrise")
    sunsets = _datetime_column(block.get("sunset"), len(dates), time_context, "sunset")
    daylight = _optional_float_column(block.get("daylight_duration"), len(dates))
    return tuple(
        DayAlmanac(
            date=dates[index],
            sunrise=sunrises[index],
            sunset=sunsets[index],
            daylight_seconds=daylight[index],
            time_context=time_context,
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
            an unexpected shape, or the time is not a valid Unix instant.
    """
    body = _require_mapping(payload, "current response")
    time_context = _parse_time_context(body)
    current = _require_mapping(body.get("current"), "current block")
    time = _epoch_datetime(current.get("time"), time_context, "current time")
    values = {
        key: _coerce_float_or_none(value, key)
        for key, value in current.items()
        if key not in _CURRENT_META_KEYS
    }
    return CurrentReadings(time=time, values=values, time_context=time_context)


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
    time_context = _parse_time_context(body)
    block_body = _require_mapping(body.get(block), f"{block} block")
    raw_time = _require_list(block_body.get("time"), f"{block} time array")
    parse_time = _epoch_date if block == "daily" else _epoch_datetime
    timestamps = tuple(parse_time(value, time_context, f"{block} timestamp") for value in raw_time)
    order = tuple(_time_sort_value(value) for value in timestamps)
    if any(current <= previous for previous, current in pairwise(order)):
        message = f"{block} timestamps must be strictly chronological"
        raise OpenMeteoError(message)
    series = {
        variable: _parse_column(raw_column, len(timestamps), variable)
        for variable, raw_column in block_body.items()
        if variable != "time"
    }
    return TimeSeries(timestamps=timestamps, series=series, time_context=time_context)


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

_DRONE_PERCENT_VARIABLES = frozenset({"precipitation_probability", "cloud_cover_low"})
_MAX_PERCENT = 100.0
_DRONE_NONNEGATIVE_VARIABLES = frozenset(
    {
        "wind_gusts_10m",
        "wind_speed_10m",
        "wind_speed_80m",
        "wind_speed_120m",
        "wind_speed_180m",
        "precipitation",
        "visibility",
        "cape",
        "wind_speed_950hPa",
        "wind_speed_925hPa",
        "wind_speed_900hPa",
    }
)


def _cell(series: TimeSeries, variable: str, index: int) -> float | None:
    column = series.series.get(variable)
    return column[index] if column is not None else None


def _require_drone_columns(series: TimeSeries) -> None:
    missing = [variable for variable in DRONE_HOURLY_VARIABLES if variable not in series.series]
    if missing:
        message = f"drone hourly columns missing: {', '.join(missing)}"
        raise OpenMeteoError(message)


def _validate_drone_timestamps(timestamps: tuple[date | datetime, ...]) -> None:
    if not timestamps:
        message = "drone hourly timestamps are empty"
        raise OpenMeteoError(message)
    for value in timestamps:
        if not isinstance(value, datetime) or value.tzinfo is None:
            message = "drone timestamps must be aware instants"
            raise OpenMeteoError(message)


def _validate_drone_value(variable: str, value: float | None) -> None:
    if value is None:
        return
    if variable in _DRONE_PERCENT_VARIABLES and not 0.0 <= value <= _MAX_PERCENT:
        message = f"value in '{variable}' must be between 0 and 100"
        raise OpenMeteoError(message)
    if variable in _DRONE_NONNEGATIVE_VARIABLES and value < 0.0:
        message = f"value in '{variable}' cannot be negative"
        raise OpenMeteoError(message)
    if variable == "is_day" and value not in (0.0, 1.0):
        message = "value in 'is_day' must be 0 or 1"
        raise OpenMeteoError(message)


def _validate_drone_values(series: TimeSeries) -> None:
    for variable in DRONE_HOURLY_VARIABLES:
        for value in series.column(variable):
            _validate_drone_value(variable, value)


def _unavailable_metrics(series: TimeSeries, index: int, elevation_m: float) -> tuple[str, ...]:
    unavailable = [
        variable
        for variable in DRONE_HOURLY_VARIABLES
        if _cell(series, variable, index) is None
        and not variable.startswith(("wind_speed_9", "geopotential_height_9"))
    ]
    for hpa in _PRESSURE_LEVELS_HPA:
        wind_name = f"wind_speed_{hpa}hPa"
        height_name = f"geopotential_height_{hpa}hPa"
        height = _cell(series, height_name, index)
        if height is None:
            unavailable.append(height_name)
        elif (
            0.0 <= height - elevation_m <= _MAX_AGL_METRES
            and _cell(series, wind_name, index) is None
        ):
            unavailable.append(wind_name)
    return tuple(unavailable)


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
    time = series.timestamps[index]
    if not isinstance(time, datetime):
        message = "drone timestamp must be an instant"
        raise OpenMeteoError(message)
    return DroneFlightHour(
        time=time,
        temperature_c=_cell(series, "temperature_2m", index),
        apparent_temperature_c=_cell(series, "apparent_temperature", index),
        wind_gust_10m_kmh=_cell(series, "wind_gusts_10m", index),
        wind_max_0_500m_kmh=_derive_wind_max_0_500m(series, index, elevation_m),
        precipitation_mm=_cell(series, "precipitation", index),
        precipitation_probability_pct=_cell(series, "precipitation_probability", index),
        visibility_m=_cell(series, "visibility", index),
        cape=_cell(series, "cape", index),
        freezing_level_agl_m=_freezing_level_agl(series, index, elevation_m),
        is_day=None if is_day_value is None else is_day_value == 1.0,
        cloud_cover_low_pct=_cell(series, "cloud_cover_low", index),
        unavailable_metrics=_unavailable_metrics(series, index, elevation_m),
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
    _require_drone_columns(series)
    _validate_drone_timestamps(series.timestamps)
    _validate_drone_values(series)
    hours = tuple(
        _parse_drone_hour(series, index, elevation_m) for index in range(len(series.timestamps))
    )
    return DroneForecast(elevation_m=elevation_m, hours=hours, time_context=series.time_context)


def _lenient_float(value: object) -> float | None:
    # Aviation fields arrive as numbers or strings (for example visibility "10+",
    # wind direction "VRB"); coerce numerics, salvage trailing-"+" strings.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("+"))
        except ValueError:
            return None
    return None


def _cloud_layers(raw: object) -> tuple[CloudLayer, ...]:
    if not isinstance(raw, list):
        return ()
    layers: list[CloudLayer] = []
    for item in cast("list[object]", raw):
        if not isinstance(item, dict):
            continue
        mapping = cast("dict[str, object]", item)
        cover = mapping.get("cover")
        if isinstance(cover, str):
            layers.append(CloudLayer(cover=cover, base_ft_agl=_lenient_float(mapping.get("base"))))
    return tuple(layers)


_CEILING_COVERS = frozenset({"BKN", "OVC", "OVX"})


def _ceiling_ft(layers: tuple[CloudLayer, ...]) -> float | None:
    bases = [
        layer.base_ft_agl
        for layer in layers
        if layer.cover in _CEILING_COVERS and layer.base_ft_agl is not None
    ]
    return min(bases) if bases else None


def _metar_from(mapping: dict[str, object]) -> MetarReport | None:
    station = mapping.get("icaoId")
    latitude = _lenient_float(mapping.get("lat"))
    longitude = _lenient_float(mapping.get("lon"))
    if not isinstance(station, str) or latitude is None or longitude is None:
        return None
    try:
        coordinates = Coordinates(latitude, longitude)
    except ValueError as error:
        raise AviationError(str(error)) from error
    layers = _cloud_layers(mapping.get("clouds"))
    observed = mapping.get("reportTime")
    if not isinstance(observed, str):
        message = "METAR reportTime must be an aware ISO-8601 string"
        raise AviationError(message)
    try:
        observed_at = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as error:
        message = "METAR reportTime is not ISO-8601"
        raise AviationError(message) from error
    if observed_at.tzinfo is None:
        message = "METAR reportTime must include a timezone"
        raise AviationError(message)
    raw = mapping.get("rawOb")
    return MetarReport(
        station=station,
        coordinates=coordinates,
        observed=observed_at.astimezone(UTC),
        wind_dir_deg=_lenient_float(mapping.get("wdir")),
        wind_speed_kt=_lenient_float(mapping.get("wspd")),
        wind_gust_kt=_lenient_float(mapping.get("wgst")),
        visibility_sm=_lenient_float(mapping.get("visib")),
        clouds=layers,
        ceiling_ft_agl=_ceiling_ft(layers),
        raw=raw if isinstance(raw, str) else "",
    )


def parse_metars(payload: object) -> tuple[MetarReport, ...]:
    """Parse an aviationweather.gov METAR (JSON) payload into typed reports.

    Lenient by design: the API returns a JSON array of station observations with
    mixed numeric/string fields; entries missing an id or coordinates are skipped
    rather than failing the whole batch.

    Args:
        payload: Decoded JSON from the METAR endpoint (``format=json``).

    Returns:
        The parsed reports (possibly empty).

    Raises:
        AviationError: If the payload is not a JSON array.
    """
    if not isinstance(payload, list):
        not_list_message = "metar response"
        raise AviationError(not_list_message)
    reports: list[MetarReport] = []
    for entry in cast("list[object]", payload):
        if isinstance(entry, dict):
            report = _metar_from(cast("dict[str, object]", entry))
            if report is not None:
                reports.append(report)
    return tuple(reports)


# OpenAIP numeric enums (from the Core API schema), mapped to short labels.
_AIRSPACE_TYPE_LABELS: dict[int, str] = {
    0: "Other",
    1: "Restricted",
    2: "Danger",
    3: "Prohibited",
    4: "CTR",
    5: "TMZ",
    6: "RMZ",
    7: "TMA",
    8: "TRA",
    9: "TSA",
    10: "FIR",
    11: "UIR",
    12: "ADIZ",
    13: "ATZ",
    14: "MATZ",
    15: "Airway",
    16: "MTR",
    17: "Alert Area",
    18: "Warning Area",
    19: "Protected Area",
    20: "HTZ",
    21: "Gliding Sector",
    22: "TRP",
    23: "TIZ",
    24: "TIA",
    25: "MTA",
    26: "CTA",
    27: "ACC Sector",
    28: "Sporting/Recreational",
    29: "Low Altitude Overflight Restriction",
    30: "MRT",
    31: "TFR",
    32: "VFR Sector",
    33: "FIS Sector",
    34: "LTA",
    35: "UTA",
    36: "MCTR",
}
_ICAO_CLASS_LABELS: dict[int, str] = {
    0: "A",
    1: "B",
    2: "C",
    3: "D",
    4: "E",
    5: "F",
    6: "G",
    8: "SUA",
}
_AIRSPACE_LIMIT_UNITS: dict[int, str] = {0: "m", 1: "ft", 6: "FL"}
_AIRSPACE_LIMIT_DATUMS: dict[int, str] = {0: "GND", 1: "MSL", 2: "STD"}


def _limit_label(raw: object) -> str:
    if not isinstance(raw, dict):
        return ""
    mapping = cast("dict[str, object]", raw)
    value = mapping.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    unit_code = mapping.get("unit")
    datum_code = mapping.get("referenceDatum")
    unit = _AIRSPACE_LIMIT_UNITS.get(unit_code, "") if isinstance(unit_code, int) else ""
    datum = _AIRSPACE_LIMIT_DATUMS.get(datum_code, "") if isinstance(datum_code, int) else ""
    if value == 0 and datum == "GND":
        return "GND"
    return " ".join(part for part in (f"{value:.0f}", unit, datum) if part)


def _airspace_from(mapping: dict[str, object]) -> Airspace | None:
    name = mapping.get("name")
    if not isinstance(name, str):
        return None
    type_code = mapping.get("type")
    icao_code = mapping.get("icaoClass")
    return Airspace(
        name=name,
        type_label=_AIRSPACE_TYPE_LABELS.get(type_code, f"type {type_code}")
        if isinstance(type_code, int)
        else "unknown",
        icao_class=_ICAO_CLASS_LABELS.get(icao_code, "") if isinstance(icao_code, int) else "",
        lower_limit=_limit_label(mapping.get("lowerLimit")),
    )


def parse_airspaces(payload: object) -> tuple[Airspace, ...]:
    """Parse an OpenAIP ``/airspaces`` list payload into typed airspace volumes.

    Args:
        payload: Decoded JSON from the OpenAIP airspaces endpoint.

    Returns:
        The parsed airspaces (possibly empty); entries without a name are skipped.

    Raises:
        AirspaceError: If the payload or its ``items`` array is missing or has an
            unexpected shape.
    """
    if not isinstance(payload, dict):
        not_dict_message = "airspace response"
        raise AirspaceError(not_dict_message)
    items = cast("dict[str, object]", payload).get("items")
    if not isinstance(items, list):
        items_message = "airspace items array"
        raise AirspaceError(items_message)
    airspaces: list[Airspace] = []
    for item in cast("list[object]", items):
        if isinstance(item, dict):
            airspace = _airspace_from(cast("dict[str, object]", item))
            if airspace is not None:
                airspaces.append(airspace)
    return tuple(airspaces)
