# weather-agent web dashboard

A [Reflex](https://reflex.dev) dashboard over the `weather_agent` package: pick a
location and a horizon of up to 7 days, and see a graphical per-drone flyability
forecast with the full deterministic decision and optional generated commentary.

It is a thin UI layer — all weather logic lives in the `weather_agent` package
(`assess_fleet` for the authoritative structured forecast,
`generate_drone_report` for commentary-only JSON). This app only renders.

## Prerequisites

- The system `unzip` command. Reflex uses it when installing Bun on the first
  build (`sudo apt-get install unzip` on Debian/Ubuntu).
- The `weather_agent` package installed with the `web` group:
  ```shell
  uv sync --group web
  ```
- A running [Ollama](https://ollama.com) server with the report model pulled
  (`ollama pull gemma4:12b`, then `ollama serve`). The charts and deterministic
  reports work without it; only optional commentary needs Ollama. Unavailable,
  malformed, or decision-making model output is omitted.

## Run

From this `web/` directory:

```shell
uv run reflex run
```

Then open <http://localhost:3000>. The first run downloads frontend tooling (bun)
and compiles the app, so it takes a little longer.

## Quality and production build

From the repository root, the dashboard is covered by the normal Ruff and Pyright
commands and by focused behavior tests:

```shell
uv run ruff check web tests/test_web_dashboard.py
uv run ruff format --check web tests/test_web_dashboard.py
uv run pyright
uv run pytest tests/test_web_dashboard.py
cd web && uv run python -c "from weather_dashboard.weather_dashboard import app"
cd web && uv run reflex export --frontend-only --no-zip
```

The last command performs the same production frontend smoke build as CI. It may
download Bun on a clean machine and therefore needs both network access and `unzip`.

## What you see

- **Location** — a Great Britain place (e.g. `Congleton UK`, `Edinburgh UK`); resolved by the
  same geocoder the CLI uses, with the matched place echoed in the results header.
- **Days** — 1 to 7 days of hourly forecast.
- **Metric toggle** — wind (with the drone's limit line), precipitation, temperature,
  or visibility.
- Per drone: an animated chart, a GOOD/MARGINAL/UNKNOWN/NO-FLY colour ribbon, the
  best window, and an application-rendered report containing factors, source status,
  UK CAA context, official links, and the standing disclaimer.
- A clearly labelled generated-commentary block may appear after that report. It is
  never the source of the verdict or recommendation.

Decision support only — not legal or airworthiness advice. Always verify airspace,
Flight Restriction Zones, and NOTAMs before flying.
