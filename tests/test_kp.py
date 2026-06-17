"""Tests for the NOAA planetary K-index parser and client method."""

import httpx
import pytest

from weather_agent.client import OpenMeteoClient
from weather_agent.parsing import SpaceWeatherError, parse_kp, parse_kp_forecast

_KP_BODY: list[object] = [
    ["time_tag", "Kp", "Kp_fraction", "a_running", "station_count"],
    ["2026-06-16 03:00:00", "2", "2.00", "7", "8"],
    ["2026-06-16 06:00:00", "5", "5.33", "48", "8"],
]


def test_parse_kp_returns_latest_reading() -> None:
    """The parser returns the last (most recent) row's Kp value."""
    kp = parse_kp(_KP_BODY)

    assert kp.time == "2026-06-16 06:00:00"
    assert kp.kp == 5.0


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-list",
        [["time_tag", "Kp"]],
        [["time_tag", "Kp"], ["2026-06-16 06:00:00"]],
        [["time_tag", "Kp"], ["2026-06-16 06:00:00", "stormy"]],
    ],
)
def test_parse_kp_rejects_malformed(payload: object) -> None:
    """Malformed Kp payloads raise a space-weather error."""
    with pytest.raises(SpaceWeatherError):
        _ = parse_kp(payload)


_KP_FORECAST_BODY: list[object] = [
    ["time_tag", "kp", "observed", "noaa_scale"],
    ["2026-06-16 00:00:00", "3.00", "observed", None],
    ["2026-06-16 03:00:00", "4.67", "predicted", None],
    ["2026-06-16 06:00:00", "6.00", "predicted", None],
]


def test_parse_kp_forecast_returns_buckets() -> None:
    """The forecast parser yields one entry per predicted bucket, in order."""
    entries = parse_kp_forecast(_KP_FORECAST_BODY)

    assert len(entries) == 3
    assert entries[0].time == "2026-06-16 00:00:00"
    assert entries[-1].kp == 6.0


def test_parse_kp_forecast_empty_is_empty_tuple() -> None:
    """A header-only forecast payload yields no entries (best-effort, no raise)."""
    assert parse_kp_forecast([["time_tag", "kp"]]) == ()


def test_parse_kp_forecast_rejects_non_list() -> None:
    """A non-list forecast payload raises a space-weather error."""
    with pytest.raises(SpaceWeatherError):
        _ = parse_kp_forecast("not-a-list")


def test_geomagnetic_kp_forecast_targets_noaa() -> None:
    """geomagnetic_kp_forecast() calls the NOAA forecast product and parses it."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "services.swpc.noaa.gov"
        assert "forecast" in request.url.path
        return httpx.Response(200, json=_KP_FORECAST_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    entries = client.geomagnetic_kp_forecast()

    assert entries[-1].kp == 6.0


def test_geomagnetic_kp_targets_noaa() -> None:
    """geomagnetic_kp() calls the NOAA SWPC host and parses the latest value."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "services.swpc.noaa.gov"
        return httpx.Response(200, json=_KP_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    kp = client.geomagnetic_kp()

    assert kp.kp == 5.0
