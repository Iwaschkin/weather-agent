# weather_agent — Agent Instructions

This repository uses the `python-quality-baseline`: uv-managed, `src/` layout, strict Ruff linting and formatting, strict-but-scoped Pyright typing, pytest with coverage, and pre-commit hooks.

The baseline is intentionally opinionated. A large share of the code here is expected to be AI-generated, and the goal is to constrain that code into an explicit, reviewable, high-discipline subset of Python. Your job is to produce code that passes the checks by being well-structured, not by weakening the checks.

If a choice exists between clever code and obvious code, choose obvious code.

## Repository Facts

- Package name: `weather_agent`
- Repository type: application
- Python version: 3.14
- Tests enabled: yes
- Async enabled: yes
- Scripts present: no
- Runtime annotation frameworks present: yes (Reflex, under `web/`)

## Canonical Commands

- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Type check: `uv run pyright`
- Test: `uv run pytest`
- Web test: `uv run pytest tests/test_web_dashboard.py`
- Web import: `cd web && uv run python -c "from weather_dashboard.weather_dashboard import app"`
- Web build smoke test: `cd web && uv run reflex export --frontend-only --no-zip`

Run tools through uv (`uv run ...`) so they use the project's locked environment. Run `uv sync` after editing `pyproject.toml` directly. Use these repo-specific commands rather than generic guesses.

## Default Behaviour

1. Read the existing structure before editing, and preserve it unless the user explicitly asks for a restructure.
2. Preserve public APIs and documented workflows unless the task explicitly requires a contract change. When a public contract changes, update the relevant docs, examples, and tests in the same change.
3. Add or update tests for non-trivial logic with every code change.
4. Keep functions and modules narrow enough to review in one pass.
5. Make the smallest change that fully solves the problem, and keep each change scoped to one logical unit of work.
6. Do not add a runtime dependency, framework, or architectural layer unless it is explicitly requested.
7. Do not add speculative abstractions.
8. Do not add broad suppressions. Fix the code.
9. When a design decision is ambiguous but easily reversed, pick the simpler option and state the assumption. Stop and ask only when the decision affects external interfaces, persistence shape, security boundaries, or new runtime dependencies.
10. If the user supplies a plan or spec, treat it as authoritative for product scope, dependencies, entrypoint shape, and testing expectations — but subordinate to this repository's existing rules and CI contract; flag conflicts instead of siding with the plan.

## Typing

- Add explicit parameter and return types for functions and methods.
- Do not import `typing.Any` (Ruff bans it in this repo). Use a concrete type or a `Protocol` instead.
- Do not use `dict[str, Any]` for structured data. Prefer `dataclass`, `TypedDict`, `Protocol`, `Enum`, and `Literal` where shape matters.
- Keep typed boundaries at module, API, CLI, persistence, and integration edges.
- If a third-party library has weak typing, isolate that weakness at the boundary and keep the rest of the code strongly typed.
- Narrow optional values early instead of carrying `None` through the call graph.

## Docstrings

- Add useful docstrings for public modules, classes, and functions (Google convention).
- Docstrings must explain purpose, assumptions, important behaviour, edge cases, or non-obvious failure modes.
- Do not write tautological docstrings that only restate the name. `"""Calculate the total."""` on `calculate_total` satisfies the linter and is still wrong.

## Function And Module Design

- The Ruff caps (`max-args = 5`, `max-branches = 8`, `max-returns = 5`, `max-statements = 25`, `max-complexity = 8`) are a decomposition pressure system. Split code because readability improves, not to game the number.
- Avoid deeply nested control flow and boolean trap parameters.
- Prefer explicit names over clever compression.
- Keep modules narrow in scope. Do not dump unrelated code into `utils.py`, `helpers.py`, or similar catch-all files.
- For greenfield structure, prefer the minimal default: pure or domain logic modules, boundary adapters for I/O and integrations, and thin explicit entrypoints (CLI wiring, app startup).

## Data Design

- Make invalid states harder to represent.
- Validate and normalize input at the boundary; convert external payloads into typed internal models instead of passing raw dictionaries through the codebase.
- Prefer immutable value objects where practical.

## Error Handling

- Do not use broad `except Exception` unless handling at a true application boundary or re-raising with useful context.
- Catch specific exceptions, raise with context, and never silently swallow exceptions.
- Do not log and re-raise unless the duplicate signal is genuinely useful.

## Side Effects, Logging, And Time

- Keep I/O, network calls, subprocess use, environment access, and filesystem mutation at the edges of the system; keep pure logic separate.
- Avoid import-time side effects, and do not hide external calls inside low-level utility helpers.
- Do not use `print`. Use `logging` where operationally useful, with deferred formatting (`logger.info("x=%s", x)`), and without noisy logging in every helper.
- Use timezone-aware datetimes and explicit UTC handling for persisted or cross-system timestamps.

## Testing

What must be tested:

- Every function that transforms data, validates input, makes decisions, or handles errors.
- Every parser, serializer, and boundary adapter.
- Every bug fix: add a regression test that fails without the fix and passes with it.

What does not need tests:

- Pure type definitions (dataclasses, TypedDicts, Enums), re-exports, thin wrappers that only delegate, and CLI glue that only parses arguments and calls a tested function.

Rules:

- Test behaviour, not implementation trivia. Cover failure paths, not just happy paths.
- Keep tests deterministic: no network access, sleeping, timing assumptions, machine-local files, real environment variables, or current time unless the seam is explicitly controlled.
- Mock only at real boundaries (network, filesystem, subprocess, time, external services).
- Use parametrization for repeated input matrices.
- Keep integration tests focused on real seams with the smallest realistic fixture set.
- `skip` and `xfail` should be rare and include a reason.
- If a design is hard to test, simplify the design before weakening the test strategy.
- Do not generate decorative tests that only satisfy coverage.

## Do Not Invent Architecture

Do not add any of the following unless the user explicitly requests them:

- repository/service/manager/factory/controller layering
- async code or async frameworks unless concurrency is genuinely required
- web frameworks, ORMs, task queues, plugin systems, event buses, or dependency injection containers
- generic wrappers around stdlib features or compatibility layers for hypothetical future backends
- caching layers, background workers, or job schedulers
- Docker, Kubernetes, Terraform, or CI pipelines beyond the baseline workflow at `.github/workflows/ci.yml`
- abstract base classes with a single concrete implementation

Prefer stdlib, direct code, and one obvious dependency over abstraction for its own sake.

## Suppression Policy

Suppressions are allowed only when narrow, justified, and local: a specific `# pyright: ignore[...]` at a real third-party boundary, or a targeted `# noqa` naming the specific rule code, with a concrete reason.

Never as normal practice: blanket `# type: ignore`, blanket `# noqa`, `# pragma: no cover`, disabling rules because generated code does not pass, or weakening config instead of rewriting unclear code. If code fails linting or typing, fix the code first.

## Type-Checking Imports (`TC` Rules)

The `TC` rules move type-only imports behind `if TYPE_CHECKING:` blocks. This is usually correct, but annotation-driven frameworks (Pydantic, FastAPI, and similar) evaluate annotations at runtime. If a type is needed at runtime, keep it as a normal import. Prefer correct runtime behaviour over mechanical `TC` compliance when the two conflict.

## Known Rule Frictions And The Right Responses

Some strict rules have predictable, legitimate collisions. Resolve them as below — never by globally relaxing the rule.

| Rule | Legitimate trigger | Correct response |
| --- | --- | --- |
| `FBT001`/`FBT002` | Boolean CLI flags in typer/click/argparse wiring | Per-file-ignore `FBT` for the CLI wiring module only; keep boolean traps out of internal APIs |
| `B008` | FastAPI `Depends(...)` in parameter defaults | Per-file-ignore `B008` for route modules (FastAPI evaluates defaults intentionally) |
| `reportImportCycles` | `__init__.py` re-export hubs | Restructure: import from submodules directly and keep `__init__.py` thin |
| `S603`/`S607` | Legitimate subprocess use in a boundary adapter | Validate inputs, use list args and absolute paths, then a targeted `# noqa: S603` with a reason |
| `PLR0913` (max-args) | Config-style constructors | Group related parameters into a `dataclass` or `TypedDict` instead of raising the cap |
| `ARG001`/`ARG002` | Protocol/callback/override signatures with unused params | Prefix the unused parameter with an underscore |
| `TC001`–`TC003` | Pydantic/FastAPI runtime annotations | Keep runtime-needed imports as normal imports (see the section above) |
| `reportUnknown*` / `typing.Any` ban | boto3 and botocore return loosely typed values everywhere | Add `boto3-stubs` with the needed service extras (for example `uv add --dev "boto3-stubs[s3]"`) for typed clients, and keep AWS calls in boundary adapters; do not blanket-suppress |

## Keeping This File Current

These facts and the tool config decay together. Update both in the same change when the project crosses one of these lines:

- Introducing async code or async tests: run `uv add --dev pytest-asyncio`, add `asyncio_mode = "auto"` to `[tool.pytest.ini_options]`, and set `Async enabled: yes` above.
- Adding a `scripts/` directory or root-level entrypoints: add the paths to Pyright `include` and `strict`, and set `Scripts present: yes` above.
- Adding a runtime annotation framework (Pydantic, FastAPI, ...): set the fact above and apply the framework rows from the frictions table.
- Changing how the project is linted, typed, tested, or built: update `Canonical Commands` above.

## Completion Checklist

Before finishing any change, verify (in Claude Code, `/code-review` is a good final pass for substantive changes):

- [ ] Lint, format check, type check, and tests all pass via the canonical commands above
- [ ] Non-trivial logic changes have tests, including failure paths
- [ ] Public interfaces are typed and have useful docstrings
- [ ] No `print` statements, commented-out code, or broad suppressions were introduced
- [ ] No unrelated refactors were mixed into the change
- [ ] Side effects stay at boundaries, not inside pure logic

<!-- python-quality-baseline @ cee5284 -->

## Root-Cause Discipline (No Quick Fixes)

This is a hard constraint, not a preference. It overrides any default bias toward finishing quickly, touching less code, or producing the smallest diff. When the right fix is slower than the fast one, take the slower one.

When something is broken, failing, wrong, or in your way, your job is to find and remove its **root cause** — not to silence its **symptom**. A change that makes an error disappear without your understanding *why* the error occurred is not a fix. It is a deferral that hides the problem and makes the next failure harder to find. You may not trade correctness for speed unless the user explicitly tells you to.

### The Core Test

For every problem you touch, you must be able to state the causal chain:

> this input / condition → this code path → this specific flaw → this symptom

If your explanation contains "somehow", "for some reason", "it seems to", or "this makes it work", you have not found the root cause and you are not finished. Claiming "I found the root cause" is not the same as finding it. The chain is the evidence; produce it.

### What Counts As A Quick Fix

These are symptom-silencers. Recognize them. None is an acceptable response to a problem you do not understand:

- **Suppressing a diagnostic** instead of fixing what it flags: `# type: ignore`, `# noqa`, `# pyright: ignore`, `# pragma: no cover`, `@ts-ignore`, `eslint-disable`, `@SuppressWarnings`, `-Wno-*`, or widening a config to make a rule stop firing.
- **Swallowing an error**: catching an exception and continuing, returning a default on failure, or wrapping something in `try`/`catch` so it stops throwing — without understanding why it threw.
- **Weakening a type to escape a type error**: `Any`, `object`, `unknown`, `as`, `cast`, non-null assertions (`!`), or making a field optional to dodge a real nullability bug.
- **Masking a timing or concurrency bug**: adding a `sleep`, raising a timeout, adding retries, or reordering calls until it happens to pass.
- **Special-casing the symptom**: an `if` branch that handles the one input that breaks, instead of fixing the logic that mishandles it.
- **Hardcoding** a value that should be computed, derived, or configured, to make one case work.
- **Faking the test instead of the code**: loosening an assertion, mocking away the failing path, marking `skip`/`xfail` without a tracked reason, or commenting out a failing check.
- **Bypassing the guardrails**: `--force`, `--no-verify`, skipping hooks or CI, deleting a failing test.
- **Copy-pasting** a block instead of extracting and fixing the shared path.
- **Deferring in place**: leaving a `TODO`/`FIXME` and moving on, when the fix is in scope now.

### The Required Method

For any non-trivial fix:

1. **Reproduce / observe** the actual failure before changing anything. Do not fix by guessing.
2. **Trace to the source.** Follow the causal chain. Keep asking "why does this happen?" until the answer is a root cause you can point to — a specific line, contract, data shape, or assumption — not another symptom one layer down.
3. **Name the root cause explicitly** before you fix it. If you cannot name it, you have not found it: keep investigating.
4. **Fix at the right layer.** Change the thing that is actually wrong, at its source — even when that is farther from where the symptom surfaced, touches more code, or is harder than patching the surface.
5. **Verify the cause is gone.** The symptom must be absent *because* the cause is absent, and you must be able to explain the link. Re-run the failing case and the surrounding behavior.
6. **Clean up what the fix made unnecessary.** Remove dead branches, now-unused code, and the scaffolding the bug required.

### The Suppression / Workaround Gate

Before you suppress a diagnostic, swallow an error, widen a type, add a retry / sleep / timeout, special-case a symptom, or add any other workaround, you must be able to write — in the change itself — all three of:

1. **The root cause**, specifically. Not "something in the parser"; *which* logic and *why*.
2. **Why the correct fix is genuinely unavailable here** — for example, a confirmed third-party or platform bug you cannot reach. Link the upstream issue or document the quirk.
3. **What the correct fix would be**, so the debt is legible and removable.

If you cannot produce all three, you have not earned the workaround. Keep investigating. A workaround without this justification is forbidden.

### When The Right Fix Is Big Or Blocked

If the correct fix is genuinely out of scope, larger than the current change should be, or blocked by something you cannot resolve, the correct action is to **stop and report** — not to quietly apply a quick fix and move on.

State the root cause, the correct fix, and why it is blocked or large. Propose doing it properly. Surfacing the real problem is always allowed; burying it under a workaround is not. An explicit, tracked "this needs a proper fix, here is the diagnosis" is acceptable. An unexplained hack that hides the problem from the next person is not.

### Backwards Compatibility Nobody Asked For

Do not preserve old behavior, old signatures, or old code paths that nothing currently needs.

- When you change something, change it **fully**: update every caller and delete the old path.
- Do not add compatibility shims, versioned duplicates (`process_v2`, `handle_new`, `LegacyFoo`), deprecation layers, or "leave it just in case" code.
- Preserve an old contract only when a **real, current consumer** requires it. That is a stated requirement, not a default. When you are unsure whether such a consumer exists, **ask** — do not assume one into existence and build a shim for the assumption.

Git holds the history. The working tree is not an archive: delete commented-out code, dead functions, and speculative abstractions rather than carrying them.

### Legitimate Exceptions

A narrow, documented workaround is acceptable only when **all** of these hold:

- The root cause is genuinely outside your control (a third-party or platform bug), and you have linked the upstream issue or documented the quirk.
- The workaround is the **narrowest possible** — one line, one specific rule code, one call site — never blanket.
- A comment states the cause, why the workaround exists, and the condition under which it can be removed.

These are the logged, bounded exception — not the tool you reach for under time pressure. The existence of this section is not permission to relax; it is the definition of the only door.

### Self-Check Before Finishing

- [ ] I can state the root cause of every issue I addressed, as a causal chain — no "somehow".
- [ ] Each fix changes the source of the problem, not the place it surfaced.
- [ ] I added no suppression, swallowed error, widened type, retry, sleep, or special-case without the three-part justification above.
- [ ] I removed the code my fix made unnecessary; I left no commented-out or dead code.
- [ ] I preserved no old behavior, signature, or path that no current consumer needs.
- [ ] Anything I could not fix properly, I surfaced explicitly rather than hid.
