"""Tests for the NOAA planetary K-index parser and client method."""

import httpx
import pytest

from weather_agent.client import OpenMeteoClient
from weather_agent.parsing import SpaceWeatherError, parse_kp

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


def test_geomagnetic_kp_targets_noaa() -> None:
    """geomagnetic_kp() calls the NOAA SWPC host and parses the latest value."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "services.swpc.noaa.gov"
        return httpx.Response(200, json=_KP_BODY)

    client = OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    kp = client.geomagnetic_kp()

    assert kp.kp == 5.0
