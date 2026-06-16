---
applyTo: "**/*.py"
description: "Review Python changes against the highest-signal rules of the python-quality-baseline."
excludeAgent: "coding-agent"
---

# Python Quality Baseline Review Rules

Keep feedback focused on correctness, reviewability, and missing tests.

## Highest-Signal Checks

- Require explicit parameter and return annotations on non-trivial functions.
- Reject imports of `typing.Any` and weak structured types such as `dict[str, Any]`.
- Require useful docstrings for public modules, classes, and functions; reject tautologies that only restate the name.
- Flag broad `except Exception`, silent exception swallowing, and vague re-raises.
- Flag `print` statements, commented-out code, and broad suppressions such as blanket `# noqa` or `# pyright: ignore`.
- Flag oversized or overly complex functions that should be decomposed under the baseline caps.
- Flag untested logic changes. Functions that transform data, validate input, make decisions, or handle errors should have tests.
- Flag bug fixes that lack a regression test.
- Flag new runtime dependencies, frameworks, or architectural layers that were not explicitly requested.
- Flag public API or documented-workflow changes that do not update the relevant docs, examples, or tests when those assets are part of the maintained surface.
- Prefer simple structure: pure or domain logic, clear boundary adapters, and thin entrypoints.

## Review Priorities

1. correctness regressions
2. missing or weak typing
3. missing or tautological docstrings
4. unsafe error handling
5. dependency or architecture creep
6. missing tests for non-trivial behavior
7. public contract changes without supporting updates
