"""Tests for the NOAA planetary Kp provider boundary."""

from datetime import UTC, datetime

import httpx
import pytest

from weather_agent.models import KpRowKind
from weather_agent.space_weather import (
    SpaceWeatherClient,
    SpaceWeatherError,
    parse_kp,
    parse_kp_forecast,
)

_CURRENT_BODY: list[object] = [
    {"time_tag": "2026-07-11T15:00:00", "Kp": 1.33, "station_count": 8},
    {"time_tag": "2026-07-11T18:00:00", "Kp": 2.33, "station_count": 8},
]
_FORECAST_BODY: list[object] = [
    {
        "time_tag": "2026-07-11T18:00:00",
        "kp": 2.33,
        "observed": "observed",
        "noaa_scale": None,
    },
    {
        "time_tag": "2026-07-11T21:00:00",
        "kp": 2.0,
        "observed": "estimated",
        "noaa_scale": None,
    },
    {
        "time_tag": "2026-07-12T00:00:00",
        "kp": 5.0,
        "observed": "predicted",
        "noaa_scale": "G1",
    },
]


def test_parse_kp_returns_latest_object_row() -> None:
    """The current official object schema produces the newest typed reading."""
    reading = parse_kp(_CURRENT_BODY)

    assert reading.time == datetime(2026, 7, 11, 18, tzinfo=UTC)
    assert reading.kp == 2.33


def test_parse_kp_forecast_preserves_row_kind_and_scale() -> None:
    """Observed, estimated, and predicted classifications survive parsing."""
    entries = parse_kp_forecast(_FORECAST_BODY)

    assert tuple(entry.kind for entry in entries) == (
        KpRowKind.OBSERVED,
        KpRowKind.ESTIMATED,
        KpRowKind.PREDICTED,
    )
    assert entries[-1].time == datetime(2026, 7, 12, tzinfo=UTC)
    assert entries[-1].noaa_scale == "G1"


@pytest.mark.parametrize(
    "payload",
    [
        "not-an-array",
        [],
        [["time_tag", "Kp"]],
        [{"time_tag": "2026-07-11T18:00:00", "Kp": "2.33"}],
        [{"time_tag": "not-a-time", "Kp": 2.33}],
        [{"time_tag": "2026-07-11T18:00:00", "Kp": float("nan")}],
        [{"time_tag": "2026-07-11T18:00:00", "Kp": 10.0}],
    ],
)
def test_parse_kp_rejects_malformed_current_rows(payload: object) -> None:
    """The old shape and invalid values cannot enter the typed boundary."""
    with pytest.raises(SpaceWeatherError):
        _ = parse_kp(payload)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [{"time_tag": "2026-07-12T00:00:00", "kp": 2.0, "observed": "guessed"}],
        [{"time_tag": "2026-07-12T00:00:00", "kp": 2.0, "observed": "predicted"}],
        [
            {
                "time_tag": "2026-07-12T03:00:00",
                "kp": 2.0,
                "observed": "predicted",
                "noaa_scale": None,
            },
            {
                "time_tag": "2026-07-12T00:00:00",
                "kp": 2.0,
                "observed": "predicted",
                "noaa_scale": None,
            },
        ],
    ],
)
def test_parse_kp_forecast_rejects_malformed_rows(payload: object) -> None:
    """Forecast rows require the current fields and chronological ordering."""
    with pytest.raises(SpaceWeatherError):
        _ = parse_kp_forecast(payload)


def test_space_weather_client_targets_both_noaa_products() -> None:
    """The provider client owns both NOAA URLs and selects the matching parser."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        body = _FORECAST_BODY if "forecast" in request.url.path else _CURRENT_BODY
        return httpx.Response(200, json=body)

    client = SpaceWeatherClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert client.current_kp().kp == 2.33
    assert client.kp_forecast()[-1].kind is KpRowKind.PREDICTED
    assert len(paths) == 2
    assert all("noaa-planetary-k-index" in path for path in paths)


def test_space_weather_client_normalizes_invalid_json() -> None:
    """A successful HTTP response with invalid JSON is a typed NOAA failure."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not JSON")

    client = SpaceWeatherClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(SpaceWeatherError, match="valid JSON"):
        _ = client.current_kp()
