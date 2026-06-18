# weather-agent web dashboard

A [Reflex](https://reflex.dev) dashboard over the `weather_agent` package: pick a
location and a horizon of up to 7 days, and see a graphical per-drone flyability
forecast with an AI-generated briefing for each drone.

It is a thin UI layer — all weather logic lives in the `weather_agent` package
(`assess_fleet` for the structured forecast, `generate_drone_report` for the
grounded LLM report). This app only renders.

## Prerequisites

- The `weather_agent` package installed with the `web` group:
  ```shell
  uv sync --group web
  ```
- A running [Ollama](https://ollama.com) server with the report model pulled
  (`ollama pull gemma4:12b`, then `ollama serve`). The charts and deterministic
  summaries work without it; only the AI briefing needs Ollama, and it degrades to
  a notice if the server is unreachable.

## Run

From this `web/` directory:

```shell
uv run reflex run
```

Then open <http://localhost:3000>. The first run downloads frontend tooling (bun)
and compiles the app, so it takes a little longer.

## What you see

- **Location** — free-text (e.g. `Congleton UK`, `Paris, France`); resolved by the
  same geocoder the CLI uses, with the matched place echoed in the results header.
- **Days** — 1 to 7 days of hourly forecast.
- **Metric toggle** — wind (with the drone's limit line), precipitation, temperature,
  or visibility.
- Per drone: an animated chart of the selected metric, a GOOD/MARGINAL/NO-FLY colour
  ribbon, the best flying window, and an AI briefing that appears once generated.

Decision support only — not legal or airworthiness advice. Always verify airspace,
Flight Restriction Zones, and NOTAMs before flying.
