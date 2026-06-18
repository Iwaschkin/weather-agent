"""Assemble the open-meteo weather agent."""

from strands import Agent
from strands.models.ollama import OllamaModel

from weather_agent.tools import (
    assess_drone_conditions,
    assess_fleet_conditions,
    compare_locations,
    compare_weather,
    get_air_quality,
    get_airspace,
    get_aviation_weather,
    get_climate_projection,
    get_current_weather,
    get_elevation,
    get_ensemble_forecast,
    get_forecast,
    get_historical_weather,
    get_marine_forecast,
    get_pollen,
    get_river_discharge,
    get_solar_potential,
    get_sun_times,
    get_uv_index,
    get_weather,
    get_weather_at_coordinates,
    list_supported_drones,
)

_SYSTEM_PROMPT = (
    "You are a weather assistant for open-meteo data. Always name the location you "
    "report on. Choose the tool that matches the question. For temperature and "
    "precipitation over time: get_current_weather (now), get_forecast (coming days), "
    "get_historical_weather (past dates, ERA5 from 1940), get_climate_projection "
    "(decade-scale future, CMIP6, to 2050). When the user names a single date and you "
    "are unsure which of those fits, use get_weather, which routes by date. Use "
    "compare_weather to compare two historical date ranges. To compare or rank "
    "several places by one metric (warmest, windiest, sunniest, most humid), use "
    "compare_locations rather than calling a single-location tool once per place. "
    "For other domains: "
    "get_air_quality (pollution and AQI), get_pollen (allergens, Europe), "
    "get_marine_forecast (waves, coastal points), get_river_discharge (flood "
    "indicator), get_ensemble_forecast (forecast uncertainty), get_uv_index (sun "
    "safety), get_solar_potential (solar energy outlook), get_sun_times (sunrise, "
    "sunset, daylight), get_aviation_weather (nearest airport observed METAR), "
    "get_airspace (nearby controlled/restricted airspace, decision support only - "
    "not authoritative), and get_elevation (terrain height). When the user gives a "
    "latitude and longitude instead of a place name, "
    "use get_weather_at_coordinates. For drone flying (DJI Neo, "
    "Avata 2, Mini 5 Pro) use assess_drone_conditions for one named drone, or "
    "assess_fleet_conditions when the user asks about all their drones or the whole "
    "fleet (do not call the single-drone tool once per drone); use "
    "list_supported_drones to see which models are covered. Always pass on the UK CAA "
    "notes and safety disclaimer, and never present it as legal or airworthiness "
    "authority. Date tools accept a natural day phrase ('today', 'tomorrow', 'in 3 "
    "days', 'next friday') or an ISO date (YYYY-MM-DD); pass the user's wording "
    "through and let the tool resolve it - do not compute dates yourself."
)
_DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_DEFAULT_MODEL_ID = "gemma4:12b"


def build_agent(
    host: str = _DEFAULT_OLLAMA_HOST,
    model_id: str = _DEFAULT_MODEL_ID,
) -> Agent:
    """Build a Strands agent wired with the open-meteo weather tool.

    The agent runs against a local Ollama server. Pull the model first with
    ``ollama pull <model_id>`` and ensure ``ollama serve`` is reachable at
    ``host``. The open-meteo tool itself needs no credentials.

    Args:
        host: Base URL of the Ollama server.
        model_id: Ollama model tag to use, for example ``"gemma4:12b"``.

    Returns:
        A configured agent ready to answer current-weather questions.
    """
    model = OllamaModel(host=host, model_id=model_id)
    return Agent(
        model=model,
        system_prompt=_SYSTEM_PROMPT,
        tools=[
            get_current_weather,
            get_forecast,
            get_historical_weather,
            get_climate_projection,
            get_weather,
            compare_weather,
            compare_locations,
            get_air_quality,
            get_pollen,
            get_marine_forecast,
            get_river_discharge,
            get_ensemble_forecast,
            get_uv_index,
            get_solar_potential,
            get_sun_times,
            get_aviation_weather,
            get_airspace,
            get_elevation,
            get_weather_at_coordinates,
            assess_drone_conditions,
            assess_fleet_conditions,
            list_supported_drones,
        ],
    )
