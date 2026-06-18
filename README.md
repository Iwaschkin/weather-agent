# weather-agent

A [Strands](https://github.com/strands-agents/sdk-python) agent over the free
[open-meteo.com](https://open-meteo.com) APIs (plus key-free NOAA space weather and
aviationweather.gov METARs) that answers weather, climate, and environmental
questions and — its centrepiece — gives **drone-flyability decision support**, both
on the command line and through a graphical [web dashboard](#web-dashboard). Only the
airspace tool needs a key (see [Configuration](#configuration)).

It is a technical demonstrator on two levels. open-meteo is really several APIs that
share one request/response grammar, so each capability is one Strands tool built on a
single shared time-series boundary (`TimeSeries` + `parse_time_series`). And the drone
assessment follows a "symbolic decides, LLM explains" design: a deterministic rules
engine owns the `GOOD` / `MARGINAL` / `NO-FLY` verdict, raw numbers are grounded in
labelled bands, and a faithfulness guardrail stops the model under-stating the risk.

## Tools

| Tool | open-meteo API | Purpose |
| --- | --- | --- |
| `get_current_weather` | Forecast | Conditions right now |
| `get_forecast` | Forecast | Multi-day daily forecast |
| `get_historical_weather` | Archive (ERA5) | Past dates, back to 1940 |
| `get_climate_projection` | Climate (CMIP6) | Decade-scale projections to 2050 |
| `get_weather` | routed | Picks archive/forecast/climate by date |
| `compare_weather` | Archive | Compare two historical date ranges |
| `compare_locations` | Forecast | Rank several places by warmest/windiest/sunniest/most humid |
| `get_weather_at_coordinates` | Forecast | Current conditions at a raw latitude/longitude (no geocoding) |
| `get_air_quality` | Air-Quality | PM2.5, PM10, ozone, European AQI (current hour), with EEA bands |
| `get_pollen` | Air-Quality (CAMS) | Grass, tree, and weed pollen (Europe) |
| `get_marine_forecast` | Marine | Wave height (WMO sea-state band) and period (coastal, current hour) |
| `get_river_discharge` | Flood (GloFAS) | River discharge / flood indicator |
| `get_ensemble_forecast` | Ensemble | Member spread (forecast uncertainty) |
| `get_uv_index` | Forecast | UV index now and today's peak, with WHO risk bands |
| `get_solar_potential` | Forecast | Daily solar radiation, sunshine, and daylight |
| `get_sun_times` | Forecast | Sunrise, sunset, and daylight length |
| `get_aviation_weather` | aviationweather.gov | Nearest airport's observed METAR (wind, visibility, ceiling) |
| `get_airspace` | OpenAIP (key) | Nearby controlled/restricted airspace (decision support) |
| `get_elevation` | Elevation | Terrain height |
| `assess_drone_conditions` | Forecast + NOAA Kp + METAR + OpenAIP | Per-hour flyability for one drone (DJI Neo, Avata 2, Mini 5 Pro) with UK CAA notes |
| `assess_fleet_conditions` | Forecast + NOAA Kp + METAR + OpenAIP | All supported drones compared side by side in one call |
| `list_supported_drones` | (none) | The drone models the assessor covers |

Current conditions name the WMO condition (e.g. "light rain") and include humidity,
dew point, cloud cover, and pressure; the daily forecast adds rain chance and peak
gust.

A few behaviours cut across the tools:

- **Interpreted bands.** Numbers that have a published scale are labelled, not left
  raw — e.g. `European AQI 33.0 (fair)`, `UV index 8.1 (very high)`,
  `Wave height 1.4 m (moderate)` — so the model is handed meaning, not bare figures.
- **Natural dates.** Date tools accept `today`, `tomorrow`, `in 3 days`,
  `next friday`, `2 weeks ago`, etc. as well as `YYYY-MM-DD`; the phrase is resolved
  in code, not by the model.
- **Multi-place and fleet requests** are single tool calls (`compare_locations`,
  `assess_fleet_conditions`): the fan-out and ranking happen deterministically
  rather than relying on the model to call a per-item tool repeatedly.

Every switch, variable, and tunable is catalogued in the
[Operators Manual](OPERATIONS.md).

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
airport's observed METAR (a reality check on the model, reconciled against the
forecast for like-for-like surface gust and visibility), and nearby airspace from
OpenAIP, plus matching tips.

`assess_fleet_conditions` runs the same assessment for every supported drone in a
single call, fetching the forecast once and showing the drones side by side, so
"how do all my drones look?" does not depend on the model calling the per-drone tool
three times.

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
- `weather_agent.bands` — pure classification of raw readings into labelled bands (UV, air quality, marine).
- `weather_agent.routing` — pure date-based selection of the right data source.
- `weather_agent.dates` — pure resolution of natural day phrases ("tomorrow", "next friday") to dates.
- `weather_agent.drone` — drone model profiles (DJI Neo, Avata 2, Mini 5 Pro) and lookup.
- `weather_agent.flyability` — pure rules engine turning forecast hours into flight verdicts.
- `weather_agent.caa` — pure UK CAA open-category guidance and disclaimer.
- `weather_agent.knowledge` — keyword retrieval over the curated drone knowledge file.
- `weather_agent.drone_report` — pure formatting of drone flight assessments (single and fleet).
- `weather_agent.evaluation` — deterministic faithfulness checks and the runtime under-statement guardrail.
- `weather_agent.eval_llm` — opt-in, offline LLM-as-judge faithfulness scoring (needs Ollama).
- `weather_agent.reporting_llm` — grounded, audited LLM-written drone reports (needs Ollama).
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
uv run weather-agent "What will the weather be in Berlin tomorrow?"
uv run weather-agent "What was the weather in Berlin 2 weeks ago?"
uv run weather-agent "Which is warmest: Paris, London, or Berlin?"
uv run weather-agent "What is the air quality in Beijing?"
uv run weather-agent "Can I fly all my drones in Congleton this weekend?"
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

The model and Ollama host default to `gemma4:12b` / `http://localhost:11434` and are
changed via `build_agent(host=..., model_id=...)` (there is no CLI flag or
environment variable for them). For the complete list of variables, tool
parameters, routing thresholds, drone profiles, band scales, and rules-engine
tunables, see the [Operators Manual](OPERATIONS.md).

## Web dashboard

A [Reflex](https://reflex.dev) dashboard in [`web/`](web/) gives the drone
assessment a graphical UI: pick a location and a horizon of up to 7 days, and see a
per-drone flyability chart (wind/precip/temp/visibility) with a GOOD/MARGINAL/NO-FLY
ribbon and an AI-generated briefing per drone. It is a thin layer over
`weather_agent.assess_fleet` (structured forecast) and
`weather_agent.reporting_llm.generate_drone_report` (the grounded LLM report).

```shell
uv sync --group web
cd web && uv run reflex run     # then open http://localhost:3000
```

The charts work without Ollama; the AI briefing needs a running Ollama server
(`ollama serve`, model pulled). See [`web/README.md`](web/README.md) for details.

## Development

This repository follows the `python-quality-baseline` (see `AGENTS.md`).

```shell
uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest
```
