"""Tests for the pure open-meteo payload parsers."""

import pytest

from weather_agent.parsing import (
    AirspaceError,
    AviationError,
    OpenMeteoError,
    parse_airspaces,
    parse_current_readings,
    parse_current_weather,
    parse_daily_almanac,
    parse_elevation,
    parse_geocode_results,
    parse_metars,
    parse_time_series,
    parse_uv_index,
)


def test_parse_geocode_results_extracts_fields() -> None:
    """A well-formed geocoding payload yields a typed result."""
    payload: dict[str, object] = {
        "results": [
            {
                "name": "Berlin",
                "country": "Germany",
                "latitude": 52.52,
                "longitude": 13.41,
            },
        ],
    }

    results = parse_geocode_results(payload)

    assert len(results) == 1
    assert results[0].name == "Berlin"
    assert results[0].country == "Germany"
    assert results[0].latitude == 52.52
    assert results[0].longitude == 13.41


def test_parse_geocode_results_extracts_disambiguation_fields() -> None:
    """Country code, region, and population are parsed when present."""
    payload: dict[str, object] = {
        "results": [
            {
                "name": "Congleton",
                "country": "United Kingdom",
                "country_code": "GB",
                "admin1": "England",
                "population": 26482,
                "latitude": 53.16,
                "longitude": -2.21,
            },
        ],
    }

    result = parse_geocode_results(payload)[0]

    assert result.country_code == "GB"
    assert result.admin1 == "England"
    assert result.population == 26482


def test_parse_geocode_results_defaults_disambiguation_fields() -> None:
    """Missing disambiguation fields fall back to empty/None."""
    payload: dict[str, object] = {
        "results": [{"name": "Nowhere", "latitude": 0.0, "longitude": 0.0}],
    }

    result = parse_geocode_results(payload)[0]

    assert result.country_code == ""
    assert result.admin1 == ""
    assert result.population is None


def test_parse_geocode_results_missing_results_is_empty() -> None:
    """The geocoding API omits 'results' when nothing matches."""
    assert parse_geocode_results({}) == []


def test_parse_geocode_results_defaults_missing_country() -> None:
    """A match without a country falls back to an empty string."""
    payload: dict[str, object] = {
        "results": [{"name": "Nowhere", "latitude": 0.0, "longitude": 0.0}],
    }

    results = parse_geocode_results(payload)

    assert results[0].country == ""


_MALFORMED_GEOCODE: list[object] = [
    "not-a-mapping",
    {"results": "not-a-list"},
    {"results": [{"name": "X", "latitude": "nan", "longitude": 0.0}]},
    {"results": [{"latitude": 1.0, "longitude": 2.0}]},
]


@pytest.mark.parametrize("payload", _MALFORMED_GEOCODE)
def test_parse_geocode_results_rejects_malformed(payload: object) -> None:
    """Malformed geocoding payloads raise a domain error."""
    with pytest.raises(OpenMeteoError):
        _ = parse_geocode_results(payload)


def test_parse_current_weather_extracts_fields() -> None:
    """A well-formed forecast payload yields typed current weather."""
    payload: dict[str, object] = {
        "current": {
            "time": "2026-06-15T12:00",
            "temperature_2m": 21.3,
            "wind_speed_10m": 9.7,
        },
    }

    weather = parse_current_weather(payload)

    assert weather.time == "2026-06-15T12:00"
    assert weather.temperature_celsius == 21.3
    assert weather.wind_speed_kmh == 9.7


_MALFORMED_FORECAST: list[object] = [
    {},
    {"current": {"temperature_2m": 1.0, "wind_speed_10m": 2.0}},
    {"current": {"time": "t", "temperature_2m": True, "wind_speed_10m": 2.0}},
]


@pytest.mark.parametrize("payload", _MALFORMED_FORECAST)
def test_parse_current_weather_rejects_malformed(payload: object) -> None:
    """Malformed forecast payloads raise a domain error."""
    with pytest.raises(OpenMeteoError):
        _ = parse_current_weather(payload)


def test_parse_current_weather_reads_optional_fields() -> None:
    """Condition code and the richer optional fields are parsed when present."""
    payload: dict[str, object] = {
        "current": {
            "time": "2026-06-15T12:00",
            "temperature_2m": 21.3,
            "wind_speed_10m": 9.7,
            "weather_code": 61,
            "relative_humidity_2m": 65,
            "dew_point_2m": 14.2,
            "surface_pressure": 1013.0,
            "cloud_cover": 90,
        },
    }

    weather = parse_current_weather(payload)

    assert weather.weather_code == 61.0
    assert weather.relative_humidity_pct == 65.0
    assert weather.cloud_cover_pct == 90.0


def test_parse_current_weather_optional_fields_default_none() -> None:
    """Absent optional fields are None, not errors."""
    payload: dict[str, object] = {
        "current": {"time": "t", "temperature_2m": 1.0, "wind_speed_10m": 2.0},
    }

    weather = parse_current_weather(payload)

    assert weather.weather_code is None
    assert weather.surface_pressure_hpa is None


def test_parse_metars_extracts_fields_and_ceiling() -> None:
    """METAR parsing reads wind/visibility/clouds and derives the ceiling."""
    payload: list[object] = [
        {
            "icaoId": "EGCC",
            "lat": 53.35,
            "lon": -2.28,
            "reportTime": "2026-06-16 12:00:00",
            "wdir": 240,
            "wspd": 12,
            "wgst": 20,
            "visib": "10+",
            "clouds": [{"cover": "SCT", "base": 1800}, {"cover": "OVC", "base": 2500}],
            "rawOb": "EGCC 161200Z 24012G20KT",
        },
    ]

    reports = parse_metars(payload)

    assert reports[0].station == "EGCC"
    assert reports[0].visibility_sm == 10.0
    assert reports[0].wind_gust_kt == 20.0
    # Ceiling is the lowest BKN/OVC layer (OVC 2500), not the SCT layer.
    assert reports[0].ceiling_ft_agl == 2500.0


def test_parse_metars_skips_entries_without_coordinates() -> None:
    """Entries missing an id or coordinates are skipped, not fatal."""
    payload: list[object] = [{"icaoId": "EGCC"}, "junk", {"lat": 1.0, "lon": 2.0}]

    assert parse_metars(payload) == ()


def test_parse_metars_rejects_non_list() -> None:
    """A non-array METAR payload raises an aviation error."""
    with pytest.raises(AviationError):
        _ = parse_metars({"not": "a list"})


def test_parse_airspaces_maps_codes_and_limits() -> None:
    """Airspace parsing maps type/class codes to labels and renders the lower limit."""
    payload: dict[str, object] = {
        "items": [
            {
                "name": "MANCHESTER CTR",
                "type": 4,
                "icaoClass": 3,
                "lowerLimit": {"value": 0, "unit": 1, "referenceDatum": 0},
            },
            {
                "name": "DANGER D123",
                "type": 2,
                "icaoClass": 8,
                "lowerLimit": {"value": 1500, "unit": 1, "referenceDatum": 1},
            },
            {"no": "name here"},
        ],
    }

    airspaces = parse_airspaces(payload)

    assert len(airspaces) == 2  # the unnamed entry is skipped
    assert airspaces[0].type_label == "CTR"
    assert airspaces[0].icao_class == "D"
    assert airspaces[0].lower_limit == "GND"
    assert airspaces[1].type_label == "Danger"
    assert airspaces[1].lower_limit == "1500 ft MSL"


def test_parse_airspaces_rejects_missing_items() -> None:
    """A payload without an items array raises an airspace error."""
    with pytest.raises(AirspaceError):
        _ = parse_airspaces({"no": "items"})


def test_parse_daily_almanac_reads_sun_times() -> None:
    """The almanac parser reads string sunrise/sunset and numeric daylight."""
    payload: dict[str, object] = {
        "daily": {
            "time": ["2026-06-16", "2026-06-17"],
            "sunrise": ["2026-06-16T04:43", "2026-06-17T04:43"],
            "sunset": ["2026-06-16T21:21", "2026-06-17T21:22"],
            "daylight_duration": [59880.0, 59940.0],
        },
    }

    almanac = parse_daily_almanac(payload)

    assert len(almanac) == 2
    assert almanac[0].date == "2026-06-16"
    assert almanac[0].sunrise == "2026-06-16T04:43"
    assert almanac[0].daylight_seconds == 59880.0


def test_parse_daily_almanac_tolerates_missing_columns() -> None:
    """Missing sun columns degrade to empty strings and None, not errors."""
    payload: dict[str, object] = {"daily": {"time": ["2026-06-16"]}}

    almanac = parse_daily_almanac(payload)

    assert almanac[0].sunrise == ""
    assert almanac[0].daylight_seconds is None


def test_parse_uv_index_reads_current_and_today_max() -> None:
    """UV parsing reads the current value and today's daily maximum."""
    payload: dict[str, object] = {
        "current": {"time": "2026-06-15T12:00", "uv_index": 4.2},
        "daily": {"time": ["2026-06-15"], "uv_index_max": [7.8]},
    }

    uv = parse_uv_index(payload)

    assert uv.time == "2026-06-15T12:00"
    assert uv.current == 4.2
    assert uv.today_max == 7.8


def test_parse_uv_index_missing_daily_max_is_none() -> None:
    """An empty daily block leaves today's max as None."""
    payload: dict[str, object] = {
        "current": {"time": "t", "uv_index": 1.0},
        "daily": {"time": []},
    }

    assert parse_uv_index(payload).today_max is None


def test_parse_current_readings_extracts_present_hour() -> None:
    """The current block yields the present-hour scalars, ignoring metadata."""
    payload: dict[str, object] = {
        "current": {
            "time": "2026-06-15T13:00",
            "interval": 3600,
            "pm2_5": 12.0,
            "european_aqi": 33.0,
            "ozone": None,
        },
    }

    readings = parse_current_readings(payload)

    assert readings.time == "2026-06-15T13:00"
    assert readings.values == {"pm2_5": 12.0, "european_aqi": 33.0, "ozone": None}
    assert "interval" not in readings.values


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-mapping",
        {},
        {"current": {"pm2_5": 1.0}},
        {"current": {"time": 12, "pm2_5": 1.0}},
    ],
)
def test_parse_current_readings_rejects_malformed(payload: object) -> None:
    """A missing or malformed current block raises a domain error."""
    with pytest.raises(OpenMeteoError):
        _ = parse_current_readings(payload)


def test_parse_time_series_extracts_columns() -> None:
    """A well-formed block yields aligned timestamps and variable columns."""
    payload: dict[str, object] = {
        "daily": {
            "time": ["2026-06-14", "2026-06-15"],
            "temperature_2m_max": [21.0, 23.5],
            "precipitation_sum": [0.0, 4.2],
        },
    }

    series = parse_time_series(payload, "daily")

    assert series.timestamps == ("2026-06-14", "2026-06-15")
    assert series.column("temperature_2m_max") == (21.0, 23.5)
    assert series.column("precipitation_sum") == (0.0, 4.2)
    assert "time" not in series.series


def test_parse_time_series_preserves_null_gaps() -> None:
    """Open-meteo emits null for missing samples, preserved as None."""
    payload: dict[str, object] = {
        "hourly": {"time": ["2026-06-14T00:00", "2026-06-14T01:00"], "cloud_cover": [55.0, None]},
    }

    series = parse_time_series(payload, "hourly")

    assert series.column("cloud_cover") == (55.0, None)


_MALFORMED_TIME_SERIES: list[object] = [
    {},
    {"hourly": "not-a-mapping"},
    {"hourly": {"temperature_2m": [1.0]}},
    {"hourly": {"time": "not-a-list", "temperature_2m": [1.0]}},
    {"hourly": {"time": ["t1", "t2"], "temperature_2m": [1.0]}},
    {"hourly": {"time": ["t1"], "temperature_2m": ["warm"]}},
    {"hourly": {"time": [1, 2], "temperature_2m": [1.0, 2.0]}},
]


@pytest.mark.parametrize("payload", _MALFORMED_TIME_SERIES)
def test_parse_time_series_rejects_malformed(payload: object) -> None:
    """Malformed or ragged time-series payloads raise a domain error."""
    with pytest.raises(OpenMeteoError):
        _ = parse_time_series(payload, "hourly")


def test_parse_elevation_extracts_first_value() -> None:
    """A well-formed elevation payload yields the first metre value."""
    assert parse_elevation({"elevation": [38.0, 39.0]}).meters == 38.0


_MALFORMED_ELEVATION: list[object] = [
    {},
    {"elevation": "not-a-list"},
    {"elevation": []},
    {"elevation": [None]},
    {"elevation": ["high"]},
]


@pytest.mark.parametrize("payload", _MALFORMED_ELEVATION)
def test_parse_elevation_rejects_malformed(payload: object) -> None:
    """Malformed elevation payloads raise a domain error."""
    with pytest.raises(OpenMeteoError):
        _ = parse_elevation(payload)
