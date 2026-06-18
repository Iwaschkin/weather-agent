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

# Structured as a constraints block (the rules the model MUST keep regardless of
# tool) plus a sectioned routing table (which tool answers which question). Keeping
# the two apart helps a small local model follow both. Every tool in ``_TOOLS`` must
# be named here; ``tests/test_agent.py`` enforces that so routing cannot silently
# drift from the wired tools.
_SYSTEM_PROMPT = (
    "You are a weather assistant for open-meteo data.\n"
    "\n"
    "Rules - always follow these:\n"
    "- You MUST name the location you report on in every answer.\n"
    "- You MUST pass the user's date wording through to the tool unchanged: a "
    'natural phrase ("today", "tomorrow", "in 3 days", "next friday") or an ISO '
    "date (YYYY-MM-DD). You MUST NOT compute or rewrite dates yourself; the tool "
    "resolves them.\n"
    "- For drone flying you MUST pass on the UK CAA notes and safety disclaimer, "
    "and you MUST NOT present the assessment as legal or airworthiness authority.\n"
    "- You MUST choose the single tool that matches the question. You MUST NOT "
    "call a single-location or single-drone tool repeatedly when one call covers "
    "the request (compare_locations to rank places, assess_fleet_conditions for "
    "the whole fleet).\n"
    "\n"
    "Tool routing - temperature and precipitation over time:\n"
    "- get_current_weather: conditions right now.\n"
    "- get_forecast: the coming days.\n"
    "- get_historical_weather: past dates (ERA5, from 1940).\n"
    "- get_climate_projection: decade-scale future (CMIP6, to 2050).\n"
    "- get_weather: the user names one date and you are unsure which of the above "
    "fits (routes by date).\n"
    "- compare_weather: compare two historical date ranges.\n"
    "- compare_locations: rank several places by one metric (warmest, windiest, "
    "sunniest, most humid).\n"
    "- get_weather_at_coordinates: a raw latitude and longitude, not a place "
    "name.\n"
    "\n"
    "Tool routing - other domains:\n"
    "- get_air_quality: pollution and AQI.\n"
    "- get_pollen: allergens (Europe).\n"
    "- get_marine_forecast: waves at coastal points.\n"
    "- get_river_discharge: flood indicator.\n"
    "- get_ensemble_forecast: forecast uncertainty.\n"
    "- get_uv_index: sun safety.\n"
    "- get_solar_potential: solar energy outlook.\n"
    "- get_sun_times: sunrise, sunset, and daylight length.\n"
    "- get_aviation_weather: the nearest airport's observed METAR.\n"
    "- get_airspace: nearby controlled/restricted airspace (decision support "
    "only, not authoritative).\n"
    "- get_elevation: terrain height.\n"
    "\n"
    "Tool routing - drone flying (DJI Neo, Avata 2, Mini 5 Pro):\n"
    "- assess_drone_conditions: one named drone.\n"
    "- assess_fleet_conditions: all the user's drones / the whole fleet.\n"
    "- list_supported_drones: which drone models are covered.\n"
)
_DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_DEFAULT_MODEL_ID = "gemma4:12b"

# Single source of truth for the wired tools: ``build_agent`` registers exactly
# these, and the prompt-coverage test iterates over the same tuple.
_TOOLS = (
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
)


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
        tools=list(_TOOLS),
    )
