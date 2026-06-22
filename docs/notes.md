## Main recommendation

Make it **less agentic at the control plane**.

You already have the hard part in place: typed adapters, deterministic flyability rules, structured outputs, retrieval, observability, a benchmark, an LLM narrative layer, and a basic faithfulness audit. The next gains will come from constraining the local model rather than adding more tools.

```text
User query
  -> typed intent / action plan
  -> validate slots, dates, limits and policy
  -> deterministic executor
  -> typed evidence bundle
  -> deterministic renderer or tightly bounded prose renderer
```

Use the LLM primarily for extracting intent, resolving ambiguity, and phrasing. Do not let it own routing, arithmetic, safety decisions, or final factual authority.

## Highest-value additions

### 1. A typed action compiler

Have the model produce a constrained `ActionPlan`, not arbitrary tool calls:

```python
class ActionPlan(BaseModel):
    action: Literal[
        "current_weather",
        "forecast",
        "drone_assessment",
        "location_comparison",
        ...
    ]
    location: str | None = None
    drone: str | None = None
    when: str | None = None
    days: int | None = None
```

Validate it before execution. On invalid output, allow one repair attempt with the validation error. On continued failure, ask a targeted clarification or fall back to a conservative route.

This removes a large failure surface from small models. Your current agent exposes a sizeable tool catalogue and relies on the system prompt to ensure one correct call, while the tool wrappers already do most of the actual work.

### 2. A proper scenario and regression harness

The present benchmark measures token use, latency, call counts, failures, and per-tool totals. That is useful, but it cannot tell you whether the model selected the *right* tool, extracted the right arguments, or gave a faithful final answer.

Add a versioned scenario manifest:

```yaml
- name: drone-tomorrow-with-location
  query: "Can I fly my Neo in Congleton tomorrow?"
  expected_plan:
    action: drone_assessment
    drone: neo
    location: Congleton UK
  allowed_tools: [assess_drone_conditions]
  required_output_terms: [Congleton, disclaimer]
  forbidden_claims: ["safe to fly"]
```

Include cases for:

* Missing required slots: “Can I fly later?”
* Ambiguous place names: Paris, Georgia vs Paris, France
* Date arithmetic and timezone boundaries
* Tool failures and malformed upstream payloads
* Prompt-injection style instructions
* Invalid drone aliases
* Repeated or wasteful tool calls
* Safety-critical contradiction: forecast says marginal, prose says “good to fly”

Measure route accuracy, argument accuracy, duplicate-call rate, unsupported-claim rate, clarification quality, and safety breaches. Make regressions fail CI.

### 3. Introduce an explicit `UNKNOWN` / `INSUFFICIENT_DATA` state

This is the most important safety improvement.

Several gates currently treat absent values as `GOOD`, including some temperature, precipitation, visibility, and daylight cases. That can create a “good-to-fly” window from incomplete data. Treat missing or stale safety-critical data as a distinct outcome, not as benign weather.

A useful split is:

| Dimension             | Example result                      |
| --------------------- | ----------------------------------- |
| Weather               | Good / marginal / no-fly            |
| Data confidence       | Adequate / degraded / insufficient  |
| Regulatory status     | Checked / unverified / restricted   |
| Operational readiness | Suitable / requires pilot judgement |

Then a report can say: “Weather appears suitable, but airspace and current visibility are unverified” instead of collapsing everything into “GOOD”.

### 4. Separate weather safety from legal eligibility

At present, CAA guidance, airspace, weather and drone capability are presented in one assessment. Keep them separate in the model and combine only in the final display.

A weather-safe hour is not necessarily legal. An airspace check may be unavailable. The pilot may lack permissions, observer support, a launch-site permission, or required equipment.

Use a versioned `PolicyPack` with:

* Jurisdiction
* Effective date
* Source revision
* Assumptions
* Rules that require user confirmation
* Explicit unsupported conditions

This is especially worthwhile because UK drone rules changed on 1 January 2026, including a green flashing-light requirement for Open Category night flights. The CAA does not impose a blanket ban on flying at night, although maintaining VLOS and night visibility remains critical. Your current engine classifies every night hour as `NO_FLY`, so that rule should become a configurable operational policy, not a universal legal assertion. ([Civil Aviation Authority][1])

### 5. Use progressive tool exposure

Do not present all tools to every model invocation.

A lightweight deterministic or small-model classifier can assign the request to a tool family:

* Weather and forecasts
* Historical and climate
* Environmental conditions
* Drone assessment
* Comparison and ranking

Then expose only the 2-5 relevant actions. For routine routes, bypass the general agent entirely.

This should reduce prompt tokens, wrong-tool selection, duplicate calls, and latency. It also makes each model's capability boundary much clearer.

### 6. Add an evidence envelope and provenance-first rendering

Instead of sending a final text blob back into the model, return structured evidence:

```python
@dataclass
class Evidence:
    source: str
    retrieved_at: datetime
    observation_time: datetime | None
    location: ResolvedLocation
    freshness: Freshness
    values: dict[str, float | str | None]
    caveats: list[str]
```

Then render from this object. Every displayed conclusion should be traceable to a source, timestamp and location.

This matters particularly for METAR reconciliation. A nearby airport observation may be old, far from the launch site, or inconsistent with the forecast. That should affect confidence and potentially suppress a positive recommendation, not merely appear as an informational note.

### 7. Integrate forecast uncertainty into drone assessment

You already have an ensemble forecast endpoint, but it appears as a separate information tool rather than feeding the flight decision.

Use it to produce a confidence-aware result:

* “Likely good window: 10:00-12:00, but gust threshold is close and ensemble spread is high.”
* “No recommendation: probability of crossing the gust limit is too high.”
* “Stable forecast: high confidence.”

That is much more valuable than another weather endpoint. It converts a point forecast into a decision under uncertainty.

### 8. Persist replayable traces, not just aggregate metrics

The existing benchmark report preserves model ID, host, token counts, latency and tool-call names, but not the plan, arguments, tool responses, final answer, prompt revision, model digest, quantisation, hardware, or tool schema version.

Store redacted run traces locally, perhaps in SQLite:

* Raw query
* Resolved intent plan
* Validation failures and repairs
* Available tool subset
* Tool arguments
* Tool result hash and evidence
* Final answer
* Model digest and quantisation
* Prompt and policy version
* Token, latency and failure metrics

That gives you reproducible regressions and useful model capability cards rather than vague impressions that Model A “feels better”.

### 9. Add execution budgets and a cache

Set hard limits such as:

* Maximum one planning repair
* Maximum one tool call for simple queries
* Maximum three calls for composed briefings
* Duplicate tool-call detection
* Timeout and retry policy only for retryable provider failures
* TTL cache for geocoding, forecasts and static airspace lookups
* Stale-if-error behaviour, always labelled as stale

The observer currently tells you after the fact that the model behaved wastefully. A budget layer prevents waste before it happens.

### 10. Add structured session state

Your chat session relies on retained model conversation history. That is fragile for cheap local models and will degrade as the context window trims old turns.

Keep a small explicit state object:

```python
SessionState(
    selected_location="Congleton, GB",
    selected_drone="neo",
    timezone="Europe/London",
    last_assessment_at=...,
)
```

Then “What about tomorrow?” becomes deterministic slot completion rather than a memory test.

## Fix before expanding further

1. **Do not treat missing safety data as good data.** Add `UNKNOWN` and fail conservatively.

2. **Use the location’s timezone for forecast hours.** UK legal guidance can remain UK-scoped, but a forecast for Tokyo should not be labelled in UK time.

3. **Turn drone rules into dated policy packs.** Avoid hardcoding legal assertions in Python constants.

4. **Strengthen the LLM audit.** Phrase matching is a useful tripwire, but it is not a factual verifier. Prefer constrained claim extraction or template rendering from structured facts.

5. **Harden judge parsing.** `bool(data.get("faithful"))` treats strings such as `"false"` as truthy. Require actual booleans.

## What I would not add yet

Do not add a vector database, broad RAG, multiple autonomous agents, or a larger selection of external APIs. Your keyword retrieval is adequate for the narrow drone knowledge corpus, and your bottleneck is control reliability, not retrieval sophistication.

[1]: https://www.caa.co.uk/drones/open-category/getting-started-with-drones-and-model-aircraft/flying-at-night-in-the-open-category/?utm_source=chatgpt.com "Flying at night in the Open Category"

## Where to expand

You already have a broad weather catalogue - forecasts, ensemble data, air quality, marine, rivers, solar, METAR, airspace, and a composite drone assessment. The useful gap is **operational pre-flight information**, not more generic weather endpoints.

| Priority | API / source                                            | Tool to expose                                              | Distinct value                                                                                                                                                                                                                                                                                                          |
| -------- | ------------------------------------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1        | Met Office severe-weather warnings                      | `get_weather_warnings(location)`                            | Separates an official active warning from “forecast looks unpleasant”. The NSWWS feed is machine-readable and updates when warnings are issued, changed, cancelled or expire. ([Met Office GitHub][1])                                                                                                                  |
| 2        | AviationWeather TAF endpoint                            | `get_nearest_taf(location, when)`                           | Your METAR is an observation. A TAF adds an aviation forecast, including forecast wind, visibility and significant weather, for the nearest reporting airfield. It is a useful independent check against the model forecast. ([Aviation Weather Center][2])                                                             |
| 3        | NATS AIS / NOTAM briefing                               | `get_temporary_airspace_restrictions(location, start, end)` | OpenAIP gives nearby airspace context. This adds time-bounded restrictions: events, emergency zones, cranes, balloons, military activity and similar temporary hazards. The CAA explicitly says NATS AIS is the primary UK source and restrictions must be checked before every flight. ([Civil Aviation Authority][3]) |
| 4        | Met Office Weather DataHub                              | `crosscheck_uk_forecast(location, when)`                    | A UK-specific independent forecast and observation source. Use it when your forecast sits near a safety threshold, not as another interchangeable weather tool. It offers land observations and a site-specific blended probabilistic forecast. ([datahub.metoffice.gov.uk][4])                                         |
| 5        | Ordnance Survey Features API                            | `get_launch_site_context(location, radius_m)`               | Static ground-risk context: roads, rivers, buildings, hospitals, playing fields and greenspace. This supports launch-site judgement without pretending to decide whether a site is lawful or suitable. ([OS Docs][5])                                                                                                   |
| 6        | Environment Agency Flood Monitoring and Tide Gauge APIs | `get_water_edge_conditions(location)`                       | Useful only near rivers, coasts or after sustained rain. It can surface active flood alerts, river level/flow, rainfall measurements and tide gauges - relevant to access, launch/landing and coastal filming. ([Defra Data Services][6])                                                                               |

## The best three to build first

### 1. Weather warnings

This is clean tool-discovery territory:

```text
Question: "Any severe weather warnings around Snowdonia tomorrow?"
Tool: get_weather_warnings
```

It is semantically distinct from `get_forecast`, and the model should not confuse a forecast probability with an active official warning.

Output should be structured:

```python
WeatherWarning(
    severity="amber",
    phenomena=("wind",),
    valid_from=...,
    valid_to=...,
    area_name=...,
    source_url=...,
)
```

### 2. TAF alongside your existing METAR

This is probably the highest-value low-effort addition because you already have the AviationWeather client. Your current architecture uses METAR as a real-world check beside forecast data. A TAF completes that pair:

```text
METAR = what the nearest station observed
TAF   = what the nearest station expects
Model forecast = gridded forecast at the launch location
```

Do not let the LLM “vote” between them. Have deterministic code classify:

```text
agreement
minor disagreement
material disagreement
insufficient local aviation coverage
```

Then downgrade confidence when there is material disagreement.

### 3. Temporary restriction / NOTAM briefing

This is the most valuable test of tool orchestration because it is:

* Spatial
* Time-bounded
* Semantically dense
* High consequence
* Not reliably reducible to a single keyword

The CAA identifies NATS AIS as the primary source for UK temporary restrictions. ([Civil Aviation Authority][3]) NATS does expose a contingency PIB data file, but warns that its XML has no declared schema and can change with little notice. Treat this as an experimental adapter with aggressive validation, not infrastructure you silently trust. ([NATS][7])

The tool must never report “airspace clear”. It should return:

```text
No matching restrictions found in retrieved data.
Manual AIS check still required before flight.
```

## The most interesting tool-discovery set

I would add these four as a deliberate test bundle:

```python
get_weather_warnings(location, when)
get_nearest_taf(location, when)
get_temporary_airspace_restrictions(location, start, end)
get_launch_site_context(location, radius_m=250)
```

They answer four genuinely different questions:

| Tool                   | Question it owns                                                  |
| ---------------------- | ----------------------------------------------------------------- |
| Weather warnings       | Is there an official meteorological alert?                        |
| TAF                    | Does nearby aviation forecasting support the expected conditions? |
| Temporary restrictions | Is there a time-specific airspace constraint?                     |
| Site context           | Does the ground environment raise static operational concerns?    |

That is better for evaluating discovery than adding six subtly overlapping forecast APIs.

Your current agent already exposes 22 tools, including both specialised lookups and composite drone reports.  Add these in stages and compare:

1. Flat tool list.
2. Tool families exposed only after a deterministic intent classifier.
3. Retrieved “tool cards” where the model sees only the best 4-6 candidates.
4. A composite `preflight_briefing` that calls the underlying sources without asking the model to orchestrate every low-level step.

Measure correct-tool recall, unnecessary calls, missed mandatory calls, argument correctness, and unsafe false reassurance.

## Worth adding later

**Protected-area context** can be useful for wildlife-sensitive filming. Natural England publishes spatial datasets for SSSIs and National Nature Reserves. It should only say “protected designation nearby - check local restrictions and seasonal guidance”, not infer a flight ban. ([Defra Data Services][8])

## Avoid

Do not add:

* A second generic weather API merely because it exists.
* A live ADS-B aircraft-position tool as a consumer-drone safety decision-maker.
* A “can I legally fly here?” tool.
* A “find me a safe launch site” tool.

Those last two overclaim. Static map data cannot establish landowner permission, crowd density, local bylaws, temporary events, wildlife disturbance, or real-time aircraft activity.

One small correction to my earlier suggestion: your code already fetches and incorporates NOAA Kp data into drone assessments, so a standalone space-weather API is not the next addition.

[1]: https://metoffice.github.io/nswws-public-api/?utm_source=chatgpt.com "Introduction | Met Office NSWWS Public API"
[2]: https://aviationweather.gov/data/api/?utm_source=chatgpt.com "Data API"
[3]: https://www.caa.co.uk/drones/open-category/moving-on-to-more-advanced-flying/airspace/airspace-restrictions/?utm_source=chatgpt.com "Airspace restrictions | UK Civil Aviation Authority"
[4]: https://datahub.metoffice.gov.uk/?utm_source=chatgpt.com "Weather DataHub | Home"
[5]: https://docs.os.uk/os-apis/accessing-os-apis/os-features-api?utm_source=chatgpt.com "OS Features API - OS Docs! - Ordnance Survey"
[6]: https://environment.data.gov.uk/flood-monitoring/doc/reference?utm_source=chatgpt.com "Environment Agency Real Time flood-monitoring API"
[7]: https://www.nats.aero/do-it-online/pre-flight-information-bulletins/?utm_source=chatgpt.com "NATS AIS Internet Briefing System Contingency"
[8]: https://environment.data.gov.uk/dataset/ba8dc201-66ef-4983-9d46-7378af21027e?utm_source=chatgpt.com "Sites of Special Scientific Interest (England)"
