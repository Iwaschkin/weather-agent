# weather-agent

A [Strands](https://github.com/strands-agents/sdk-python) agent that answers
weather, climate, and environmental questions, primarily using the free
[open-meteo.com](https://open-meteo.com) APIs (no key needed). It also draws on
NOAA space weather and aviationweather.gov (both key-free); only the airspace tool
needs a key (see [Configuration](#configuration)).

It is a technical demonstrator: open-meteo is really several APIs that share one
request/response grammar, so each capability is one Strands tool built on a single
shared time-series boundary (`TimeSeries` + `parse_time_series`).

## Tools

| Tool | open-meteo API | Purpose |
| --- | --- | --- |
| `get_current_weather` | Forecast | Conditions right now |
| `get_forecast` | Forecast | Multi-day daily forecast |
| `get_historical_weather` | Archive (ERA5) | Past dates, back to 1940 |
| `get_climate_projection` | Climate (CMIP6) | Decade-scale projections to 2050 |
| `get_weather` | routed | Picks archive/forecast/climate by date |
| `compare_weather` | Archive | Compare two historical date ranges |
| `get_weather_at_coordinates` | Forecast | Current conditions at a raw latitude/longitude (no geocoding) |
| `get_air_quality` | Air-Quality | PM2.5, PM10, ozone, European AQI (current hour) |
| `get_pollen` | Air-Quality (CAMS) | Grass, tree, and weed pollen (Europe) |
| `get_marine_forecast` | Marine | Wave height and period (coastal, current hour) |
| `get_river_discharge` | Flood (GloFAS) | River discharge / flood indicator |
| `get_ensemble_forecast` | Ensemble | Member spread (forecast uncertainty) |
| `get_uv_index` | Forecast | UV index now and today's peak, with WHO risk bands |
| `get_solar_potential` | Forecast | Daily solar radiation, sunshine, and daylight |
| `get_sun_times` | Forecast | Sunrise, sunset, and daylight length |
| `get_aviation_weather` | aviationweather.gov | Nearest airport's observed METAR (wind, visibility, ceiling) |
| `get_airspace` | OpenAIP (key) | Nearby controlled/restricted airspace (decision support) |
| `get_elevation` | Elevation | Terrain height |
| `assess_drone_conditions` | Forecast + NOAA Kp + METAR + OpenAIP | Per-hour drone flyability (DJI Neo, Avata 2, Mini 5 Pro) with UK CAA notes |
| `list_supported_drones` | (none) | The drone models the assessor covers |

Current conditions name the WMO condition (e.g. "light rain") and include humidity,
dew point, cloud cover, and pressure; the daily forecast adds rain chance and peak
gust.

## Drone flying assessment

`assess_drone_conditions` is a technical demonstrator of a hybrid design: a
deterministic rules engine plus a small retrieved knowledge file. It combines a
drone-tuned hourly forecast (gusts and winds up to 500 m above ground, derived
from fixed-height and pressure-level winds), precipitation, temperature,
visibility, daylight, low-cloud cover, thunderstorm potential (CAPE), and NOAA's
per-hour planetary Kp forecast into an hour-by-hour `GOOD` / `MARGINAL` /
`NO-FLY` verdict for a chosen drone, names the limiting factor, finds the best
flying window, and summarises a per-day outlook over a multi-day horizon. It adds
UK CAA open-category guidance, the day's sunrise/sunset window, the nearest
airport's observed METAR (a reality check on the model), and nearby airspace from
OpenAIP, plus matching tips.

It is decision support, not legal or airworthiness advice. The airspace section is
**not** authoritative and does **not** cover NOTAMs - always verify with CAA Drone
Assist / Altitude Angel before flying. The airspace lookup needs an OpenAIP key
(see Configuration); without one, every other part still works. Edit
`src/weather_agent/data/drone_knowledge.md` to tune the qualitative tips.

## Layout

- `weather_agent.models` — typed value objects (`TimeSeries`, request and result types).
- `weather_agent.parsing` — pure parsers that validate open-meteo, NOAA, aviation, and OpenAIP JSON into typed models.
- `weather_agent.weather_codes` — WMO weather-code to human-readable condition lookup.
- `weather_agent.client` — HTTP I/O for the open-meteo and NOAA endpoints (`OpenMeteoClient`).
- `weather_agent.aviation` — HTTP boundary for aviationweather.gov METARs (`AviationClient`).
- `weather_agent.openaip` — HTTP boundary for OpenAIP airspace (`OpenAipClient`, needs a key).
- `weather_agent.reporting` — pure formatting of time series into readable summaries.
- `weather_agent.routing` — pure date-based selection of the right data source.
- `weather_agent.drone` — drone model profiles (DJI Neo, Avata 2, Mini 5 Pro) and lookup.
- `weather_agent.flyability` — pure rules engine turning forecast hours into flight verdicts.
- `weather_agent.caa` — pure UK CAA open-category guidance and disclaimer.
- `weather_agent.knowledge` — keyword retrieval over the curated drone knowledge file.
- `weather_agent.drone_report` — pure formatting of drone flight assessments.
- `weather_agent.weather` — domain logic turning a place name into a readable summary.
- `weather_agent.results` — typed lookup outcomes (answer/not-found/invalid/failure), rendered to text at the tool boundary.
- `weather_agent.tools` — the Strands `@tool` wrappers exposing each capability.
- `weather_agent.agent` — builds the agent and wires in the tools.
- `weather_agent.cli` — command-line entrypoint.

## Running the agent

The agent runs against a local [Ollama](https://ollama.com) server using the
`gemma4:12b` model. Start Ollama and pull the model first:

```shell
ollama pull gemma4:12b
ollama serve
```

Then run a query:

```shell
uv run weather-agent "What is the weather in Tokyo right now?"
uv run weather-agent "What was the weather in Berlin on 2020-01-01?"
uv run weather-agent "Compare Madrid summers in 1990 and 2020"
uv run weather-agent "What is the air quality in Beijing?"
uv run weather-agent "Can I fly my DJI Mini 5 Pro in Congleton today?"
```

### Interactive chat (with memory)

Start a multi-turn session that remembers earlier turns:

```shell
uv run weather-agent chat
```

The chat reuses a single agent instance, so its conversation history carries
context across turns (a sliding window trims the oldest turns over time). Ask a
follow-up like "and what about tomorrow?" and it keeps the location from before.
Type `exit` or press Ctrl-C to quit.

The host and model tag can be overridden via `build_agent(host=..., model_id=...)`.

## Configuration

The weather, climate, air-quality, marine, and pollen tools need no API key. The
airspace tool is the only exception: it uses [OpenAIP](https://www.openaip.net),
which needs a free key. Copy `.env.example` to `.env` (git-ignored) and set:

```shell
OPENAIP_API_KEY=your-key-here
```

The CLI loads `.env` automatically. Without a key, every other tool works
normally and the airspace lookup degrades to an "unavailable" note.

## Development

This repository follows the `python-quality-baseline` (see `AGENTS.md`).

```shell
uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest
```
