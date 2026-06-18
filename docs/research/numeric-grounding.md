# Grounding the agent in what the numbers mean

*Research synthesis — 2026-06-17. Topic: how to help an LLM agent understand and
reason over the numeric/structured data this project's tools produce (what the
numbers mean, what is good/bad, and how a drone's own specs interact with the
weather numbers).*

## Provenance

Produced by the `deep-research` harness (fan-out web search → fetch → 3-vote
adversarial verification → synthesis). Two runs:

- **Run 1 (Threads 1–5):** 26 sources, 122 claims, 25 verified, 19 confirmed →
  7 findings. Threads 1–5 below.
- **Run 2 (focused, Threads 6–7):** 27 sources, 123 claims, 25 verified,
  **18 confirmed**; synthesis was hand-done (the harness's auto-merge hit a
  transient API error). Threads 6–7 below.

Confidence labels and votes are the harness's; "engineering inference" marks
recommendations that follow from the evidence but are not verbatim source
conclusions.

---

## TL;DR / recommendation

Keep the **deterministic rules engine as the decision-maker and verdict ground
truth**; use the LLM to **explain/justify and to reason about ambiguity and edge
cases**, never to perform the threshold arithmetic itself. This is warranted
because numeric weakness is documented across the **full** capability spectrum
(persists in frontier models, collapses on small local ones), and the dominant
evidence-backed mitigation is **compute-then-explain**: offload computation to
deterministic code, then have the model narrate over pre-computed, semantically
labelled values.

Carry meaning to the model **where it consumes the numbers**: emit
`raw value + unit + interpreted band + reference range + relative margin + the
gate's "why"` in tool output, and put units/definitions/enums in self-describing
schemas. Present **absolute and relative framings together** (relative alone
hurts novel-case generalization). Be explicit **but concise** — verbosity has a
real token cost that matters for the small local model.

---

## Verified findings (Threads 1–5)

1. **Numeric weakness persists even in frontier models** *(high, 3-0)*. Basic
   arithmetic, numerical retrieval, and magnitude/threshold comparison remain
   poor even for GPT-4/DeepSeek — so threshold decisions over raw tool numbers
   should not be left to the model. Sources: NumericBench
   ([arXiv:2502.11075](https://arxiv.org/pdf/2502.11075)), PAL
   ([arXiv:2211.10435](https://arxiv.org/abs/2211.10435)), A Fragile Number Sense
   ([arXiv:2509.06332](https://arxiv.org/html/2509.06332)).

2. **Small local models are dramatically worse** *(high, 3-0)*. 7B–8B models
   (Llama-2-7B, Mistral-7B, Qwen3-8B) verbalize cross-notation comparisons at
   **50–70%, near the 50% random baseline**, vs GPT-4.1 at ~94%. Mixed
   units/notations are the documented danger zone — exactly this project's
   m/s vs km/h, ft, SM, m. Game-of-24 shows a steep cliff (only o1 > 50% vs
   86–95% on basic ops). GSM-Symbolic shows >12–15% accuracy swings when only the
   numbers change. Sources:
   [arXiv:2602.07812](https://arxiv.org/pdf/2602.07812),
   [arXiv:2509.06332](https://arxiv.org/html/2509.06332),
   [GSM-Symbolic](https://machinelearning.apple.com/research/gsm-symbolic).

3. **The failure is structural → fix it architecturally, not by prompting
   harder** *(medium, 2-1)*. Autoregressive generation mismatches carry
   propagation. Held **narrowly**: proven for multi-operand addition on three
   7–8B models; the stronger "fundamentally blocks all numeric reasoning" version
   was **refuted 0-3**. Source:
   [arXiv:2502.19981](https://arxiv.org/pdf/2502.19981).

4. **Compute-then-explain (PAL) is the strongest evidence-backed mitigation**
   *(high, 3-0)*. The LLM decomposes; a deterministic interpreter computes
   (PAL beat PaLM-540B on GSM8K by ~15% absolute). **Maps directly to this repo:
   the typed-Python tool layer is the interpreter — it computes derived/
   interaction features and the verdict; the LLM narrates.** Source:
   [arXiv:2211.10435](https://arxiv.org/abs/2211.10435).

5. **Return high-signal semantic fields, not cryptic identifiers** *(high, 3-0)*.
   Interpreted band labels, reference ranges, and the gate's reasoning are the
   high-signal fields that drive correct explanation; resolving cryptic IDs to
   meaningful names measurably cut hallucinations in a controlled test (29–68
   errors → 5–7). Sources:
   [Anthropic — Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents),
   [BAML UUID-swap](https://boundaryml.com/blog/uuid-swap).

6. **Self-describing schemas — "onboard a new hire", but concise** *(high, 3-0)*.
   Put units, niche-term definitions, field relationships, and output semantics
   into descriptions + enums + JSON Schema, so a newly added drone/sensor carries
   its own context instead of growing the prompt. **Concision is load-bearing**:
   EASYTOOL cut tool-description tokens ~72% with no quality loss — be explicit
   but precise, especially for a small-context local model. Sources:
   [Anthropic](https://www.anthropic.com/engineering/writing-tools-for-agents),
   [OpenAI function calling](https://platform.openai.com/docs/guides/function-calling),
   [EASYTOOL arXiv:2401.06201](https://arxiv.org/abs/2401.06201).

7. **LLMs encode value *relatively*; relative framing helps but trades off
   generalization** *(high, 3-0)*. "Gust is 1.4× this drone's rating" / "12 °C of
   headroom" anchors meaning well, **but adding explicit comparisons measurably
   hurt transfer to novel problems (.734 vs .771, p<.001)**. Because edge/novel
   cases are a priority here, present **absolute + relative + reference range
   together**, not relative alone. (Evidence is from artificial bandit tasks on
   chat-tuned models, so application to weather thresholds is indirect.) Sources:
   [Relative Value Encoding in LLMs (MIT Open Mind)](https://direct.mit.edu/opmi/article/doi/10.1162/opmi_a_00209/131044/Relative-Value-Encoding-in-Large-Language-Models-A),
   [arXiv:2405.11422](https://arxiv.org/abs/2405.11422).

### Refuted / retracted — do **not** cite these

- "A single irrelevant clause causes up to 65% drops" — refuted 0-3.
- "LLMs don't genuinely reason, only memorize training steps" — refuted 0-3.
- "Arithmetic limits are fundamental and block all numeric generalization" —
  refuted 0-3 (keep the mechanism claim narrow to addition).
- "Hidden states linearly encode the ranking (>90%) while verbalizing 50–70%, so
  the bottleneck is purely verbalization" — **refuted 1-2 on the stricter pass**
  (it appeared in an earlier interim note; the mechanism is unsettled). The safe,
  robust position is purely behavioural: numeric/threshold reasoning is
  unreliable; don't make the model do it.
- "Root cause is surface token patterns, not continuous magnitude" — refuted 0-3.

---

## The layered design

Put each piece of context at the cheapest layer that makes it reliable.

| Layer | What lives here | Why here | Module(s) |
|---|---|---|---|
| **1. Tool output (typed)** | raw value + unit + interpreted band + reference range + **relative margin/ratio vs this drone** + the gate's "why" | The model should *read* the judgment, not compute it (Findings 1–4). Highest-leverage layer. | `flyability.py`, `models.py`, `reporting.py` |
| **2. Result/tool schema** | per-field descriptions, units, enums for the bands, reference ranges; concise | Self-describing data; new metrics/drones carry their own meaning (Finding 6) | `tools.py` docstrings, `models.py` |
| **3. System prompt** | stable role + **authority contract** (defer to gates; may raise caution, never lower it) + how to read the bands | Cheap, always present, rarely changes | `agent.py` |
| **4. Retrieval (RAG)** | definitional metacontext (what CAPE is, why Kp hits GNSS/compass, what a low freezing level implies) + drone tips | Large, occasionally-needed prose | `knowledge.py` + `data/drone_knowledge.md` |

Rule of thumb: **numeric/comparative → Layer 1 (precomputed)**; **definitional/
explanatory → Layer 4**; **authority/role → Layer 3**. **But for a *small static*
corpus like this glossary, "Layer 4" should mean exact, metric-keyed selection
(not similarity RAG), and for the small local model is often best collapsed into
Layer 1 — see [Retrieval of metacontext](#retrieval-of-metacontext-thread-6).**

---

## Concrete patterns, mapped to this codebase

`flyability.py` already returns the *why* as strings such as
`"gusts ~14 m/s exceed the 12 m/s limit"` — excellent for small models (they just
relay it). The upgrade is to **also emit it as structure** so stronger models can
reason and so explanations stay faithful.

**1. Structured gate judgment** (alongside the existing string):

```python
@dataclass(frozen=True, slots=True)
class GateReading:
    metric: str               # "wind_gust"
    value: float; unit: str   # 14.0, "m/s"
    threshold: float | None   # 12.0  (this drone's caution_gust_ms)
    ratio: float | None       # 1.17  (precomputed — never let the model divide)
    band: Verdict             # GOOD / MARGINAL / NO_FLY
    reason: str               # existing human string (small-model fallback)
```

Precompute `ratio`/margin deterministically (Finding 7 + Finding 1) — the model
never compares `14 m/s` to `12 m/s` itself. Emit **absolute + relative +
reference band** together (Finding 7's generalization caveat).

**2. A self-describing metric registry** so new drones/metrics carry context
instead of growing the prompt (Finding 6):

```python
@dataclass(frozen=True, slots=True)
class MetricInfo:
    key: str; unit: str
    blurb: str                 # "Convective potential; storm/turbulence risk."
    bands: tuple[Band, ...]    # good <1000, marginal 1000-2500, severe >2500
```

One catalog feeds Layer-1 labels, Layer-2 schema text, and Layer-4 retrieval.

**3. Asymmetric authority for edge/novel cases.** The engine's `NO_FLY` is
binding; let the LLM *add* caution for combinations the gates don't cover but
never downgrade. Return the un-gated signals (values present but below any single
threshold, or notable combinations) plus a system-prompt rule: *"You may raise
caution from the data; you may never report a verdict less restrictive than the
engine's."* This is the safe way to get LLM reasoning over novel cases without
trusting it with the safety call (Finding 4 backbone).

**4. Keep returning rendered text for portability.** Strings work for every
model; offer the structured `GateReading[]` *additionally* for stronger models.
Same pipeline, graceful degradation.

---

## Model-agnostic guidance (small local ↔ frontier)

| | Small local (Gemma/Ollama) | Frontier (Claude/GPT) |
|---|---|---|
| Numeric work | **100% precomputed**; model only relays pre-formed phrases | Precomputed too (safety); may reason over the structured readings |
| Comparisons/ratios | Never ask it; emit `ratio` + band label | Same — don't regress safety to save tokens |
| Edge-case reasoning | Constrain to "list the flagged factors" | Let it combine un-gated signals and weigh trade-offs |
| Schema/desc length | **Tight** — token budget is load-bearing (EASYTOOL) | Can afford richer descriptions |
| Relative framing | Provide, but always with absolute + reference range | Same |

The single design serving both: **rich typed output + pre-baked explanation
strings.** The small model reads the strings; the large model reads the
structure. No code fork.

---

## Retrieval of metacontext (Thread 6)

**Verdict: for a small static glossary, do not use similarity-based RAG — and for
the small local model, prefer baking the metacontext into tool output over
retrieving it.** The retrieval-noise evidence is consistent and strong:

- **Retrieval noise actively degrades answers — not just missing info.** Irrelevant
  passages distract the model into wrong answers
  ([2505.06914](https://arxiv.org/abs/2505.06914), 3-0); high-scoring near-miss
  chunks that don't contain the answer actively hurt
  ([2401.14887](https://arxiv.org/pdf/2401.14887), 3-0). Worst is **counterfactual**
  noise (topically related but wrong); plain off-topic noise is comparatively
  marginal ([2405.20978](https://arxiv.org/pdf/2405.20978), 3-0). A keyword-overlap
  retriever over a tiny drone glossary *is* a near-miss generator (pulls the "wind"
  tip for a gust limit, or another drone's tip) — exactly the damaging kind.
- **Distractors cause catastrophic drops (up to ~80%) and tool/agent pipelines
  amplify them** by over-trusting noisy tool output
  ([NoisyBench 2601.07226](https://arxiv.org/pdf/2601.07226), 3-0) — your exact
  setup. Counter-intuitively, more reasoning makes it *worse* in noisy settings
  (inverse scaling; attention locks onto distractor tokens).
- **Small models have a context-utilization bottleneck independent of retrieval
  quality.** Models ≤7B fail to extract the answer 85–100% of the time *even under
  oracle retrieval*, and **adding context destroys 42–100% of answers the model
  already knew** — distraction from the *presence* of context, not its quality
  ([2603.11513](https://arxiv.org/pdf/2603.11513), 3-0). Piling snippets onto Gemma
  can make it worse even when they're correct.
- **"Lost in the middle":** start/end info is used far more reliably than
  mid-context ([2307.03172](https://arxiv.org/pdf/2307.03172),
  [2510.10276](https://arxiv.org/pdf/2510.10276), 3-0). (The claim that larger
  models suffer this *less* was **refuted 0-3** — treat position sensitivity as
  universal.)

*(Caveat: "small models are hurt **far** more by noise" had only moderate support
— 7B-vs-13B F1 drop 12.5% vs 7%, 2-1 — and "RAG is net-negative below 7B" was
killed 1-2. Lean on the strongly-verified utilization-bottleneck and
presence-of-context findings, not a generic "small = noise-sensitive" claim.)*

**Recommendations:**
1. **Replace similarity retrieval with exact, metric-keyed selection.** Inject a
   definition only for the metric that is the *active limiting factor* (exact match
   off the engine's structured output), not top-k "similar" snippets. High
   precision → avoids the near-miss/counterfactual failure mode that hurts most.
2. **Inject little, at the edges.** Only the 1–3 definitions tied to the current
   verdict, placed at the start/end of the prompt.
3. **Small local model: collapse metacontext into Layer 1.** Pre-render the
   relevant "what/why" into the tool's *output text* (already grounded, no
   retrieval, no integration burden) rather than handing Gemma snippets to
   synthesize.
4. **Frontier model:** may inject more, but still gate by exact relevance.
5. **Static universal definitions** (units, field meaning) → schema/tool
   descriptions (always present, no retrieval lottery), kept concise — schema bloat
   is a real token tax ([layered.dev](https://layered.dev/mcp-tool-schema-bloat-the-hidden-token-tax-and-how-to-fix-it/);
   EASYTOOL, Run 1).

This reframes the current `knowledge.py` keyword retriever: keyword overlap over a
small glossary is the near-miss-distractor pattern the evidence warns against. Make
the trigger **exact** and the payload **minimal** — or, for the small model, move
definitions into tool output.

## Evaluating the agent (Thread 7)

A "symbolic-decides, LLM-explains" system needs two separate evaluations:

- **Decision (deterministic oracle):** the rules engine is ground truth for the
  verdict — already covered by `pytest`. No LLM needed.
- **Explanation quality (offline LLM-judge):** the verified, directly
  implementable recipe is **RAGAS-style faithfulness**
  ([2309.15217](https://arxiv.org/pdf/2309.15217), 3-0): decompose the explanation
  into atomic statements, check each is inferable from the tool-provided context
  (numbers + verdict + limiting factor), score = supported / total. It is
  **reference-free** (no human gold answers, 3-0) — fits an offline harness and
  catches fabrication and wrong-direction claims (e.g. calling a cold day "warm").
- **Validate the judge against humans** before trusting it: % agreement + Cohen's
  Kappa / Spearman, or precision/recall/F1 with human labels
  ([2411.15594](https://arxiv.org/pdf/2411.15594), 3-0). Hand-label ~20–50
  explanations once. *(The specific RAGAS-vs-human agreement figures, and "pairwise
  beats absolute scoring," did **not** survive verification — use the method, not
  those numbers.)*
- **Consistency (metamorphic):** perturb input numbers around thresholds; assert
  the verdict is monotonic (pure `pytest` on the engine) and the explanation still
  names the right limiting factor (judge). Motivated by the verified GSM-Symbolic
  variance result (Run 1).
- **Calibration / authority** *(standard practice; not strongly evidenced this
  pass)*: assert the model never reports a verdict less restrictive than the
  engine's; optionally track verbalized confidence vs correctness (ECE).

**Small vs frontier:** run the same harness on both; expect the small model to fail
faithfulness more often (distraction/over-trust) — that failure rate is itself the
signal for how much to pre-render vs let the model reason.

---

## Remaining open questions

- **Thread 5 refinement:** direct evidence that LLMs reason better over
  pre-combined interaction features than raw pairs (implied by the Game-of-24 cliff
  and relative-encoding findings, not directly tested for decision-support agents).
- **Calibration & metamorphic consistency** for this setting are only lightly
  evidenced — sources were fetched but their specific claims didn't survive
  verification; treat those eval recommendations as standard practice, not cited.
- **Pairwise vs absolute LLM-judge scoring** — a plausible reliability lever, but
  the claim was killed (1-2), so unverified here.
- **Reconciling relative framing with novel-case generalization** across model
  tiers (does absolute + relative + reference-range together fully preserve
  transfer?).

---

## Recommended increments (smallest first)

1. Add `GateReading` + precomputed absolute/relative/band fields in
   `flyability.py` (keep the strings). Pure, testable, model-agnostic — biggest
   payoff, lowest risk.
2. Add the `MetricInfo` catalog; wire blurbs into `knowledge.py` retrieval and
   tool docstrings (concise).
3. Add the system-prompt authority contract + return un-gated signals for
   edge-case narration.
4. Build the robustness + faithfulness eval harness (after Thread-7 research).

---

## Sources

**Verified (primary):** NumericBench [2502.11075](https://arxiv.org/pdf/2502.11075) ·
PAL [2211.10435](https://arxiv.org/abs/2211.10435) ·
Fragile Number Sense [2509.06332](https://arxiv.org/html/2509.06332) ·
Lookahead Limitation [2502.19981](https://arxiv.org/pdf/2502.19981) ·
Cross-notation comparison [2602.07812](https://arxiv.org/pdf/2602.07812) ·
GSM-Symbolic [Apple ML](https://machinelearning.apple.com/research/gsm-symbolic) ·
Anthropic [Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents) ·
OpenAI [function calling](https://platform.openai.com/docs/guides/function-calling) ·
EASYTOOL [2401.06201](https://arxiv.org/abs/2401.06201) ·
Relative Value Encoding [MIT Open Mind](https://direct.mit.edu/opmi/article/doi/10.1162/opmi_a_00209/131044/Relative-Value-Encoding-in-Large-Language-Models-A) ·
[2405.11422](https://arxiv.org/abs/2405.11422) · BAML [UUID-swap](https://boundaryml.com/blog/uuid-swap).

**Verified — Run 2 (Threads 6–7):** Lost-in-the-middle
[2307.03172](https://arxiv.org/pdf/2307.03172),
[2510.10276](https://arxiv.org/pdf/2510.10276) · RAG distractor noise
[2505.06914](https://arxiv.org/abs/2505.06914),
[2401.14887](https://arxiv.org/pdf/2401.14887),
[2405.20978](https://arxiv.org/pdf/2405.20978),
[2505.21870](https://arxiv.org/html/2505.21870v1) · NoisyBench
[2601.07226](https://arxiv.org/pdf/2601.07226) · small-model context utilization
[2603.11513](https://arxiv.org/pdf/2603.11513) · RAGAS faithfulness
[2309.15217](https://arxiv.org/pdf/2309.15217) · LLM-as-judge survey
[2411.15594](https://arxiv.org/pdf/2411.15594) · schema token-tax
[layered.dev](https://layered.dev/mcp-tool-schema-bloat-the-hidden-token-tax-and-how-to-fix-it/).

**Further reading (fetched, not individually verified):** CoT
[2201.11903](https://arxiv.org/pdf/2201.11903) · OCTree feature engineering
[2406.08527](https://arxiv.org/abs/2406.08527) · neuro-symbolic
[2305.12295](https://arxiv.org/abs/2305.12295),
[2311.08516v3](https://arxiv.org/pdf/2311.08516v3) · CRITIC self-correction
[2305.11738](https://arxiv.org/pdf/2305.11738) · evaluation/calibration
[2307.13702](https://arxiv.org/abs/2307.13702),
[2306.13063](https://arxiv.org/pdf/2306.13063),
[2505.18658v2](https://arxiv.org/html/2505.18658v2).
