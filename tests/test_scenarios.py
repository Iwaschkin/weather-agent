"""Deterministic scenario regression suite (the CI safety gate).

Each scenario runs a representative query through the real engine with mocked
network boundaries and asserts the rendered answer contains what it must and never
makes an unsafe claim. A failure here fails CI. The pure checker lives in
:mod:`weather_agent.scenarios`; this module is the versioned manifest plus runner.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import httpx
import pytest

from weather_agent.aviation import AviationClient
from weather_agent.client import OpenMeteoClient
from weather_agent.openaip import OpenAipClient
from weather_agent.results import render
from weather_agent.scenarios import Scenario, ScenarioResult, check_output, summarize
from weather_agent.weather import SiteClients, drone_flight_summary, fleet_flight_summary

if TYPE_CHECKING:
    from collections.abc import Callable

# Fixed reference so the fixture's 10:00/11:00 hours are never filtered as past.
_NOW = datetime(2026, 6, 16, 9, 0)  # noqa: DTZ001

_GEOCODE: dict[str, object] = {
    "results": [
        {
            "name": "Congleton",
            "country": "United Kingdom",
            "country_code": "GB",
            "admin1": "England",
            "latitude": 53.16,
            "longitude": -2.21,
            "timezone": "Europe/London",
        },
    ],
}


def _drone_body(*, gust_kmh: float, is_day: float) -> dict[str, object]:
    return {
        "elevation": 120.0,
        "hourly": {
            "time": ["2026-06-16T10:00", "2026-06-16T11:00"],
            "wind_gusts_10m": [gust_kmh, gust_kmh],
            "wind_speed_10m": [10.0, 10.0],
            "wind_max_0_500m_kmh": [gust_kmh, gust_kmh],
            "temperature_2m": [16.0, 16.0],
            "precipitation": [0.0, 0.0],
            "precipitation_probability": [0.0, 0.0],
            "visibility": [30000.0, 30000.0],
            "is_day": [is_day, is_day],
            "cape": [0.0, 0.0],
        },
    }


def _client(
    drone_body: dict[str, object], geocode: dict[str, object] | None = None
) -> OpenMeteoClient:
    body = geocode if geocode is not None else _GEOCODE

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("geocoding"):
            return httpx.Response(200, json=body)
        if request.url.host == "services.swpc.noaa.gov":
            return httpx.Response(503)
        if request.url.host.startswith("ensemble"):
            return httpx.Response(503)
        return httpx.Response(200, json=drone_body)

    return OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _site() -> SiteClients:
    def aviation_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    aviation = AviationClient(client=httpx.Client(transport=httpx.MockTransport(aviation_handler)))
    openaip = OpenAipClient(
        api_key="", client=httpx.Client(transport=httpx.MockTransport(aviation_handler))
    )
    return SiteClients(aviation=aviation, openaip=openaip)


def _no_fly_output() -> str:
    # ~16.7 m/s gust, far over every drone's limit -> NO-FLY.
    body = _drone_body(gust_kmh=60.0, is_day=1.0)
    return render(
        drone_flight_summary(
            "Congleton UK", "Mini 5 Pro", client=_client(body), now=_NOW, site_clients=_site()
        )
    )


def _night_output() -> str:
    body = _drone_body(gust_kmh=10.0, is_day=0.0)
    return render(
        drone_flight_summary(
            "Congleton UK", "Mini 5 Pro", client=_client(body), now=_NOW, site_clients=_site()
        )
    )


def _unknown_drone_output() -> str:
    body = _drone_body(gust_kmh=10.0, is_day=1.0)
    return render(drone_flight_summary("Congleton UK", "Phantom 9", client=_client(body)))


def _unknown_location_output() -> str:
    body = _drone_body(gust_kmh=10.0, is_day=1.0)
    return render(
        drone_flight_summary("Nowheresville", "Neo", client=_client(body, {"results": []}))
    )


def _fleet_output() -> str:
    body = _drone_body(gust_kmh=10.0, is_day=1.0)
    return render(
        fleet_flight_summary("Congleton UK", client=_client(body), now=_NOW, site_clients=_site())
    )


_CASES: tuple[tuple[Scenario, Callable[[], str]], ...] = (
    (
        Scenario(
            name="no_fly_not_understated",
            description="A gusty hour is no-fly and is never softened into a go.",
            required_terms=("Congleton", "NO-FLY", "not legal"),
            forbidden_terms=("safe to fly", "good to fly", "clear to fly"),
        ),
        _no_fly_output,
    ),
    (
        Scenario(
            name="night_is_marginal_not_banned",
            description="Night flight is marginal under the 2026 policy, not a blanket no-fly.",
            required_terms=("night flight", "MARGINAL"),
            forbidden_terms=("NO-FLY", "safe to fly"),
        ),
        _night_output,
    ),
    (
        Scenario(
            name="unknown_drone_lists_supported",
            description="An unknown drone lists the supported models rather than guessing.",
            required_terms=("Supported drones", "DJI Mini 5 Pro"),
            forbidden_terms=(),
        ),
        _unknown_drone_output,
    ),
    (
        Scenario(
            name="unknown_location_reports_not_found",
            description="An unresolvable location says so plainly.",
            required_terms=("No location matching",),
            forbidden_terms=("NO-FLY", "good to fly"),
        ),
        _unknown_location_output,
    ),
    (
        Scenario(
            name="fleet_covers_every_drone",
            description="A fleet request names every supported drone.",
            required_terms=("DJI Neo", "DJI Avata 2", "DJI Mini 5 Pro"),
            forbidden_terms=(),
        ),
        _fleet_output,
    ),
)


@pytest.mark.parametrize(("scenario", "produce"), _CASES, ids=[case[0].name for case in _CASES])
def test_scenario_holds(scenario: Scenario, produce: Callable[[], str]) -> None:
    """Each scenario's rendered answer meets its required/forbidden expectations."""
    result = check_output(scenario, produce())

    assert result.passed, summarize([result])


def test_check_output_flags_missing_and_leaked_terms() -> None:
    """The checker reports both absent required terms and present forbidden ones."""
    scenario = Scenario(
        name="x",
        description="",
        required_terms=("alpha", "beta"),
        forbidden_terms=("danger",),
    )

    result = check_output(scenario, "alpha here, and danger too")

    assert result.missing_terms == ("beta",)
    assert result.leaked_terms == ("danger",)
    assert result.passed is False


def test_summarize_reports_pass_count() -> None:
    """The scorecard headers the pass count and flags failing scenarios."""
    results = (
        ScenarioResult(name="ok", missing_terms=(), leaked_terms=()),
        ScenarioResult(name="bad", missing_terms=("x",), leaked_terms=()),
    )

    report = summarize(results)

    assert "scenarios: 1/2 passed" in report
    assert "[PASS] ok" in report
    assert "[FAIL] bad - missing x" in report
