# Operators Manual

A complete reference to every switch, variable, and tunable in `weather-agent`.

There are three kinds of knob, and this manual is organised around the distinction:

1. **Runtime configuration** — environment variables and CLI arguments you set when
   you run the agent. This is the only configuration that changes behaviour without
   editing code.
2. **Per-call parameters** — arguments on the tools and Python functions, used when
   driving the agent or its domain functions programmatically.
3. **Code-level tunables** — named constants in the source. There is no config file
   for these; to change one you edit the constant and re-run (`uv run ...` picks up
   the change; no reinstall needed for an editable source tree). Each is listed with
   its file, default, and effect.

There is **no** settings file, no CLI flags beyond the `chat` subcommand, and no
environment variable for the model or host (see [LLM / Ollama](#3-llm--ollama-weather_agentagent)).

---

## 1. Command line (`weather_agent.cli`)

| Invocation | Effect |
| --- | --- |
| `uv run weather-agent "<prompt>"` | One-shot: all arguments are joined into a single prompt, answered once with a fresh agent (no retained memory). |
| `uv run weather-agent chat` | Interactive multi-turn session; one agent instance is reused so conversation history carries context across turns. |
| `uv run weather-agent` | No arguments → uses the default prompt below. |

| Constant | File | Default | Effect |
| --- | --- | --- | --- |
| `_DEFAULT_PROMPT` | `cli.py` | `"What is the current weather in Berlin?"` | Used when no prompt arguments are given. |
| `_CHAT_COMMAND` | `cli.py` | `"chat"` | The first argument that triggers chat mode. |
| `_EXIT_COMMANDS` | `cli.py` | `exit`, `quit`, `:q` | Chat inputs that end the session (case-insensitive). Ctrl-C and EOF also exit. |
| log level | `cli.py` | `logging.WARNING` | Set once via `logging.basicConfig`. There is no flag; edit the call to raise/lower verbosity. |

Requires a reachable Ollama server (the agent calls a local LLM). The CLI loads
`.env` on startup before building the agent.

---

## 2. Environment variables

| Variable | Required | Default | Read by | Effect |
| --- | --- | --- | --- | --- |
| `OPENAIP_API_KEY` | No | `""` (empty) | `OpenAipClient` (`openaip.py`) | Enables the airspace lookup (`get_airspace` and the drone assessment's airspace section). Without it, `has_key` is `False` and airspace degrades to an "unavailable" note; everything else works. |
| `WEATHER_AGENT_LLM_EVAL` | No | unset | `tests/test_eval_llm.py` | Set to `"1"` to run the opt-in live LLM-as-judge test (needs a running Ollama). Any other value (or unset) skips it. Does not affect the application itself. |

Notes:

- The CLI calls `load_dotenv()`, so variables in a git-ignored `.env` file are picked
  up. Copy `.env.example` to `.env` to set `OPENAIP_API_KEY`. **Never commit `.env`.**
- Time zones come from the `tzdata` package (a dependency), so no system tz database
  is required. Drone forecasts and CAA guidance use `Europe/London` (see below).

---

## 3. LLM / Ollama (`weather_agent.agent`)

The model and host are **not** exposed via the CLI or an environment variable. They
are parameters of `build_agent(...)`, defaulting to the constants below. To change
them, either edit the constants or call `build_agent` from your own code.

| Constant / parameter | File | Default | Effect |
| --- | --- | --- | --- |
| `_DEFAULT_OLLAMA_HOST` / `build_agent(host=...)` | `agent.py` | `http://localhost:11434` | Base URL of the Ollama server. |
| `_DEFAULT_MODEL_ID` / `build_agent(model_id=...)` | `agent.py` | `gemma4:12b` | Ollama model tag. Must be pulled first (`ollama pull <tag>`). |
| `_SYSTEM_PROMPT` | `agent.py` | (long string) | The agent's system prompt: tool-selection guidance, drone/CAA framing, and the date-phrase instruction. Edit to change tool routing behaviour. |

To run a different model:

```python
from weather_agent.agent import build_agent
agent = build_agent(model_id="qwen3:30b-a3b", host="http://localhost:11434")
```

Conversation memory in `chat` mode is a sliding window managed by the Strands
`Agent`; its size is not configured here.

---

## 4. HTTP boundary clients

All three clients take an optional pre-built `httpx.Client` (used by tests to inject
a mock transport) and a `timeout`. Defaults below apply to the internally created
client.

| Client | File | `timeout` | Other per-call defaults |
| --- | --- | --- | --- |
| `OpenMeteoClient` | `client.py` | `10.0` s | `geocode(count=10)` — number of candidate matches requested. |
| `AviationClient` | `aviation.py` | `10.0` s | `nearest_metar(search_degrees=1.0)` — half-extent of the search box (~111 km). |
| `OpenAipClient` | `openaip.py` | `10.0` s | `nearby_airspaces(radius_m=15000)`; `_MAX_RESULTS=50`; key from `api_key=` or `OPENAIP_API_KEY`. |

| Constant | File | Default | Effect |
| --- | --- | --- | --- |
| `_DEFAULT_TIMEZONE` | `client.py` | `Europe/London` | Time zone requested for forecast endpoints, so hourly timestamps are UK-local. |
| `_DEFAULT_SEARCH_DEGREES` | `aviation.py` | `1.0` | METAR search box half-extent in degrees. |
| `_DEFAULT_RADIUS_M` | `openaip.py` | `15000` | Airspace search radius in metres. |
| `_MAX_RESULTS` | `openaip.py` | `50` | Max airspace volumes requested. |
| `_RELEVANT_TYPE_LABELS` | `openaip.py` | Restricted, Danger, Prohibited, CTR, TMZ, RMZ, ATZ, MATZ, MCTR, HTZ | Airspace types kept (low-level, drone-relevant); others are filtered out. |

### Endpoint base URLs (`client.py`, `aviation.py`, `openaip.py`)

All key-free except OpenAIP. Change only if proxying or self-hosting.

| Constant | URL |
| --- | --- |
| `_GEOCODING_URL` | `https://geocoding-api.open-meteo.com/v1/search` |
| `_FORECAST_URL` | `https://api.open-meteo.com/v1/forecast` |
| `_ARCHIVE_URL` | `https://archive-api.open-meteo.com/v1/archive` |
| `_CLIMATE_URL` | `https://climate-api.open-meteo.com/v1/climate` |
| `_AIR_QUALITY_URL` | `https://air-quality-api.open-meteo.com/v1/air-quality` |
| `_MARINE_URL` | `https://marine-api.open-meteo.com/v1/marine` |
| `_FLOOD_URL` | `https://flood-api.open-meteo.com/v1/flood` |
| `_ENSEMBLE_URL` | `https://ensemble-api.open-meteo.com/v1/ensemble` |
| `_ELEVATION_URL` | `https://api.open-meteo.com/v1/elevation` |
| `_PLANETARY_KP_URL` | `https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json` |
| `_PLANETARY_KP_FORECAST_URL` | `https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json` |
| `_METAR_URL` | `https://aviationweather.gov/api/data/metar` |
| `_AIRSPACES_URL` | `https://api.core.openaip.net/api/airspaces` |

---

## 5. Data-source routing (`weather_agent.routing`)

`get_weather` picks archive / forecast / climate by comparing the target date to
today using these two constants.

| Constant | File | Default | Effect |
| --- | --- | --- | --- |
| `FORECAST_HORIZON_DAYS` | `routing.py` | `16` | Dates within this many days ahead use the forecast; beyond it, the climate projection. Also the upper bound for the `days` parameter on `get_forecast`, `get_solar_potential`, and `get_sun_times`. |
| `ARCHIVE_LATENCY_DAYS` | `routing.py` | `5` | Dates older than this use the ERA5 archive; more recent past dates are served by the forecast endpoint (ERA5 publication lag). |

---

## 6. Tools and their parameters

Every tool returns text. `location` accepts a place name (optionally with a country
qualifier, e.g. `"Congleton UK"`). Date parameters accept an ISO date **or** a
natural day phrase (see [section 7](#7-date-phrases-weather_agentdates)).

| Tool | Parameters (defaults) | Notes |
| --- | --- | --- |
| `get_current_weather` | `location` | |
| `get_forecast` | `location`, `days=3` | `days` 1–16. |
| `get_historical_weather` | `location`, `start_date`, `end_date` | ERA5 from 1940. |
| `get_climate_projection` | `location`, `start_date`, `end_date` | CMIP6 to 2050. |
| `get_weather` | `location`, `when` | Routes by date. |
| `compare_weather` | `location`, `period_a_start`, `period_a_end`, `period_b_start`, `period_b_end` | Two historical ranges. |
| `compare_locations` | `locations` (list), `metric="temperature"` | Ranks places; see [metrics](#8-location-comparison-metrics-weather_agentweather). |
| `get_weather_at_coordinates` | `latitude`, `longitude` | No geocoding. |
| `get_air_quality` | `location` | Banded (see [section 9](#9-interpreted-value-bands-weather_agentbands)). |
| `get_pollen` | `location` | Europe (CAMS); currently unbanded. |
| `get_marine_forecast` | `location` | Wave height banded. |
| `get_river_discharge` | `location` | Currently unbanded. |
| `get_ensemble_forecast` | `location` | Temperature spread. |
| `get_uv_index` | `location` | WHO bands. |
| `get_solar_potential` | `location`, `days=3` | `days` 1–16. |
| `get_sun_times` | `location`, `days=1` | `days` 1–16. |
| `get_aviation_weather` | `location` | Nearest METAR. |
| `get_airspace` | `location` | Needs `OPENAIP_API_KEY`. |
| `get_elevation` | `location` | |
| `assess_drone_conditions` | `location`, `drone` | One drone; see [drone names](#11-drone-profiles-weather_agentdrone). |
| `assess_fleet_conditions` | `location` | All supported drones in one call. |
| `list_supported_drones` | (none) | |

### Programmatic-only parameters

These are not exposed on the `@tool` wrappers but exist on the underlying domain
functions and clients (useful for tests or embedding):

| Parameter | Where | Default | Effect |
| --- | --- | --- | --- |
| `client` | every `*_summary` / domain function | `None` | Inject an `OpenMeteoClient` (or mock); created and closed per call when omitted. |
| `today` | `weather_for_date`, `historical_summary`, `climate_summary`, `compare_periods` | current UTC date | Reference date for resolving relative phrases (deterministic tests). |
| `now` | `drone_flight_summary`, `fleet_flight_summary` | current UK-local time | Hours before this are dropped from the outlook. |
| `site_clients` | `drone_flight_summary`, `fleet_flight_summary` | `None` | Inject `AviationClient` / `OpenAipClient` for the METAR and airspace lookups. |
| `count` | `OpenMeteoClient.geocode` | `10` | Candidate matches requested for disambiguation. |

---

## 7. Date phrases (`weather_agent.dates`)

`resolve_day(text, today)` accepts any of the following (case-insensitive, extra
whitespace collapsed). Unrecognised input returns `None`, and the calling tool
reports an invalid-input message rather than guessing.

| Form | Examples |
| --- | --- |
| ISO date | `2026-12-25` |
| Fixed offsets | `today`, `tonight`, `tomorrow`, `yesterday`, `day after tomorrow`, `overmorrow`, `day before yesterday` |
| Counted offsets | `in 3 days`, `in 1 week`, `5 days ago`, `2 weeks ago` |
| Weekdays | `friday`, `next monday`, `this friday`, `last tuesday` |

| Constant | File | Default | Effect |
| --- | --- | --- | --- |
| `_OFFSETS` | `dates.py` | the fixed-offset table above | Maps each exact phrase to a day offset. |
| `_WEEKDAYS` | `dates.py` | Mon–Sun | Recognised weekday names. |

Weekday rule: `monday` / `this monday` / `next monday` all mean the **next**
occurrence after today; `last monday` means the most recent before today. Range
phrases (`this weekend`, `last summer`, `next week`) are intentionally **not**
supported — they describe a range, not a single day.

---

## 8. Location comparison metrics (`weather_agent.weather`)

`compare_locations` / `rank_locations` ranks places by one current-weather metric.

| `metric` value | Ranks by | Order |
| --- | --- | --- |
| `temperature` (default) | air temperature | warmest first |
| `wind` | wind speed | windiest first |
| `cloud` | cloud cover | least cloud (sunniest) first |
| `humidity` | relative humidity | most humid first |

Defined in the `_LOCATION_METRICS` registry (`weather.py`). A location that cannot
be geocoded, or lacks the metric, is listed under "Not compared" rather than failing
the whole request.

---

## 9. Interpreted value bands (`weather_agent.bands`)

Raw numbers are classified into labelled bands so the model is given meaning rather
than bare values. Thresholds are **exclusive upper bounds** ascending; a value takes
the first band it falls below, otherwise the top label.

| Scale | Constant | Thresholds → labels | Source |
| --- | --- | --- | --- |
| UV index | `UV_SCALE` | `<3` low, `<6` moderate, `<8` high, `<11` very high, else extreme | WHO |
| European AQI | `_EUROPEAN_AQI` | `<20` good, `<40` fair, `<60` moderate, `<80` poor, `<100` very poor, else extremely poor | EEA |
| PM2.5 (µg/m³) | `_PM2_5` | `<10` good, `<20` fair, `<25` moderate, `<50` poor, `<75` very poor, else extremely poor | EEA EAQI |
| PM10 (µg/m³) | `_PM10` | `<20` / `<40` / `<50` / `<100` / `<150`, else extremely poor | EEA EAQI |
| Ozone (µg/m³) | `_OZONE` | `<50` / `<100` / `<130` / `<240` / `<380`, else extremely poor | EEA EAQI |
| Wave height (m) | `_WAVE_HEIGHT` | `<0.1` calm … `<14` very high, else phenomenal | WMO sea state |

Variables without a registered scale (e.g. pollen taxa, river discharge, wave
period) render with a humanised name and no band. To add a band, add an entry to
`_METRICS` in `bands.py`.

---

## 10. Drone flyability rules engine (`weather_agent.flyability`)

Every threshold that turns a forecast hour into a `GOOD` / `MARGINAL` / `NO-FLY`
verdict. These are the safety-relevant switches; edit with care.

| Constant | Default | Effect |
| --- | --- | --- |
| `_PRECIP_PROBABILITY_MARGINAL_PCT` | `20.0` | Above this rain chance → MARGINAL. |
| `_PRECIP_PROBABILITY_NO_FLY_PCT` | `50.0` | At/above this rain chance → NO-FLY. Any *measured* precipitation (> 0 mm) is always NO-FLY. |
| `_VISIBILITY_MARGINAL_M` | `5000.0` | Base visibility (m) below which the hour is MARGINAL (adjusted by sensing, below). |
| `_LOW_CLOUD_MARGINAL_PCT` | `90.0` | Low-cloud cover at/above this → MARGINAL (low-ceiling proxy). |
| `_CAPE_MARGINAL` | `1000.0` | CAPE (J/kg) above this → MARGINAL (storm potential). |
| `_COLD_CAUTION_C` | `5.0` | At/below this temperature → cold caution (battery). Outside the profile's `min/max_temp_c` envelope is NO-FLY. |
| `_ICING_CEILING_M` | `500.0` | Freezing level (AGL) below this → icing caution. |
| `_KP_CAUTION` | `5.0` | Planetary Kp at/above this → GNSS/compass caution. |
| `_FPV_GUST_FACTOR` | `0.85` | FPV airframes get both gust limits multiplied by this (tighter, safety-biased). |
| `_NO_OMNI_VISIBILITY_PENALTY_M` | `3000.0` | Added to the marginal-visibility threshold for drones without omnidirectional sensing. |
| `_LOW_LIGHT_VISIBILITY_BONUS_M` | `2000.0` | Subtracted from it for low-light-capable drones. |
| `_KMH_PER_MS` | `3.6` | km/h ↔ m/s conversion (winds are reported in km/h, limits in m/s). |

Wind verdict (per drone, after the FPV factor): governing wind `>` caution limit →
NO-FLY; `>` ideal limit → MARGINAL; else GOOD. The governing wind is the worst wind
across 0–500 m AGL.

---

## 11. Drone profiles (`weather_agent.drone`)

The per-drone data the engine reads. All three share the DJI consumer temperature
envelope `_MIN_TEMP_C=-10.0` / `_MAX_TEMP_C=40.0`.

| Field | DJI Neo | DJI Avata 2 | DJI Mini 5 Pro |
| --- | --- | --- | --- |
| `weight_g` | 135.0 | 377.0 | 249.9 |
| `ideal_gust_ms` | 5.0 | 7.0 | 8.0 |
| `caution_gust_ms` | 8.0 | 10.7 | 12.0 |
| `is_fpv` | yes | yes | no |
| `has_omni_sensing` | no | no | yes |
| `low_light_capable` | no | no | yes |

Accepted names/aliases (`_ALIASES`, case-insensitive): `neo` / `dji neo`;
`avata` / `avata2` / `avata 2` / `dji avata 2`; `mini` / `mini5` / `mini5pro` /
`mini 5 pro` / `dji mini 5 pro`.

To add a drone: define a `DroneProfile`, append it to `DRONE_PROFILES`, and add its
aliases to `_ALIASES`. UK CAA category follows automatically from `weight_g`.

| Constant | File | Default | Effect |
| --- | --- | --- | --- |
| `_DRONE_FORECAST_DAYS` | `weather.py` | `5` | Days of hourly forecast assessed for drone flyability. |

---

## 12. METAR ↔ forecast reconciliation (`weather_agent.drone_report`)

The "observed vs forecast" line in the drone report. Only like-for-like surface
quantities are compared (10 m gust and visibility); the engine's 0–500 m governing
wind is deliberately not compared.

| Constant | Default | Effect |
| --- | --- | --- |
| `_GUST_AGREE_MS` | `2.5` | Observed/forecast gusts within this many m/s read as "close". |
| `_VIS_AGREE_RATIO` | `0.5` | Observed visibility within this ratio of the forecast (and its inverse) reads as "close". |
| `_MS_PER_KT` | `0.514444` | knots → m/s. |
| `_KM_PER_SM` | `1.60934` | statute miles → km. |
| `_KMH_PER_MS` | `3.6` | km/h → m/s. |

---

## 13. Knowledge retrieval (`weather_agent.knowledge`)

Keyword retrieval over the curated drone tips file.

| Constant / parameter | Default | Effect |
| --- | --- | --- |
| `retrieve(..., limit=_DEFAULT_LIMIT)` / `_DEFAULT_LIMIT` | `3` | Number of tip sections returned. |
| `_MIN_WORD_LENGTH` | `3` | Shorter query words are ignored. |
| `_STOPWORDS` | common words | Ignored during matching. |
| `_KNOWLEDGE_FILE` | `drone_knowledge.md` | The tips corpus, in `src/weather_agent/data/`. **Edit this file to change the qualitative tips** — no code change needed. |

---

## 14. Evaluation harnesses

Two independent ways to check explanation quality.

### Deterministic guardrail (`weather_agent.evaluation`) — always on

- `check_hour_explanation(explanation, hour)` flags prose that understates a verdict
  or omits a limiting factor.
- `audit_drone_report(assessment, report)` runs that across an assessment; the drone
  report prepends a safety banner if it fires (`_SAFETY_BANNER` in `weather.py`).
  No configuration; runs as part of normal report generation and the test suite.

### Opt-in LLM-as-judge (`weather_agent.eval_llm`) — offline only

Network I/O against Ollama; never runs in normal CI.

| Constant / parameter | File | Default | Effect |
| --- | --- | --- | --- |
| `ollama_faithfulness_judge(host=...)` / `_DEFAULT_OLLAMA_HOST` | `eval_llm.py` | `http://localhost:11434` | Ollama server for the judge. |
| `ollama_faithfulness_judge(model=...)` / `_DEFAULT_MODEL` | `eval_llm.py` | `gemma4:12b` | Judge model tag. |
| `ollama_faithfulness_judge(timeout=...)` / `_DEFAULT_TIMEOUT` | `eval_llm.py` | `60.0` s | Per-request timeout. |
| `WEATHER_AGENT_LLM_EVAL` | env | unset | `"1"` enables the live judge test. |

The request is sent with `format=json` and `temperature=0` for deterministic-ish
grading.

---

## 15. Developer / quality gates (`pyproject.toml`)

Canonical commands (run through `uv` so they use the locked environment):

```shell
uv run ruff check .     # lint
uv run ruff format .    # format
uv run pyright          # type check
uv run pytest           # tests + coverage
```

| Setting | Value | Where |
| --- | --- | --- |
| `line-length` | `100` | `[tool.ruff]` |
| `max-args` / `max-branches` / `max-returns` / `max-statements` | `5` / `8` / `5` / `25` | `[tool.ruff.lint.pylint]` |
| `max-complexity` | `8` | `[tool.ruff.lint.mccabe]` |
| docstring convention | `google` | `[tool.ruff.lint.pydocstyle]` |
| `typing.Any` | banned | `[tool.ruff.lint.flake8-tidy-imports.banned-api]` |
| Pyright mode | `standard`, `strict` on `src` | `[tool.pyright]` |
| Python version | `3.14` | `[tool.pyright]` / `requires-python` |
| Coverage | branch coverage, term-missing report | `[tool.pytest.ini_options]` |

Per-file rule relaxations: `print` is allowed in `cli.py` only; tests drop
`S101`/`PLR2004`/`S105`/`S106`. See `AGENTS.md` for the full policy.

---

## 16. Web dashboard (`web/`)

An optional [Reflex](https://reflex.dev) UI over `assess_fleet` and
`generate_drone_report`. It is a separate app outside the strict `src/` baseline
(`web/` is ruff-excluded and outside the Pyright include).

| Knob | Where | Default | Effect |
| --- | --- | --- | --- |
| `web` dependency group | `pyproject.toml` | `reflex` | Installed with `uv sync --group web`; not part of the core runtime. |
| `app_name` | `web/rxconfig.py` | `weather_dashboard` | Reflex resolves the app from `weather_dashboard/weather_dashboard.py`. |
| `days` selector | `web/.../components.py` | 1–7 (default 5) | Forecast horizon; passed to `assess_fleet`, capped at `_MAX_DRONE_FORECAST_DAYS`. |
| `metric` toggle | dashboard UI | `wind` | Charted metric: `wind` (with limit line), `precip`, `temp`, `vis`. |
| theme | `web/.../weather_dashboard.py` | dark / cyan | `rx.theme(appearance=..., accent_color=...)`; edit to restyle. |
| LLM host/model | `reporting_llm` defaults | `http://localhost:11434` / `gemma4:12b` | The dashboard calls `generate_drone_report` with the module defaults; needs Ollama running for the AI briefing (charts work without it). |

Run it:

```shell
uv sync --group web
cd web && uv run reflex run     # http://localhost:3000
```

The first run downloads the frontend toolchain (bun) and compiles, so it is slower.
