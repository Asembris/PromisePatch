---
name: fast-validate
description: Select and run the smallest correct validation set for the files that changed in the PromisePatch monorepo, instead of the full suite. Use after editing code, before committing, or when asked what to run for a change.
---

# fast-validate

Pick the least work that could actually catch a defect in **what changed**, run that, and say
what you skipped.

Every command below is the one CI already runs, from `.github/workflows/pr.yml`,
`pyproject.toml` and `README.md`. Derive from those files; do not invent a variation.

> **GitHub CI remains the broad regression authority.** This skill is a fast local signal, not
> a substitute for `pr.yml`. A green fast-validate never means "the change is fully validated";
> it means nothing obvious is broken in the area that moved. Say so when you report.

## Step 1 — see what changed

```bash
git status --short && git diff --stat HEAD
```

Map each changed path to a row below. Run the union of the matched rows, nothing more.

## Step 2 — always, on any changed Python **or Markdown**

Cheap enough to be unconditional. Scope it to the changed paths.

```bash
uv run ruff check <changed paths>
uv run ruff format --check <changed paths>
```

**Markdown counts, and this is the one people forget.** CI runs `ruff format --check .` over the
*whole repository*, and since ruff 0.16 the formatter reaches inside fenced ` ```python ` blocks
in `.md` files. A docs-only change that never runs Step 2 is the single most common way a green
local run turns into a red push. `ruff check` (the linter) does **not** read Markdown — it
reports *"No Python files found"* — so on a docs-only change run the format check alone:

```bash
uv run ruff format --check <changed .md paths>
```

**The trap inside the trap: a fenced fragment is not Python.** Lifting a few lines out of a call
and fencing them as `python` makes the formatter parse them as top-level statements, and it
rewrites them. Two bare keyword arguments become tuple assignments:

```text
exclude_cases=tuple(self._deferred),      →   exclude_cases = (tuple(self._deferred),)
```

Fence a **complete, parseable** snippet — the whole call, the whole function — or, when the
extract genuinely cannot stand alone, fence it as ` ```text ` and leave the formatter out of it.
Never silence this by excluding `docs/**` from ruff: formatted, parseable examples in the
documentation are the point of the check.

## Step 3 — changed area to minimal validation

### `packages/promise-graph/src/promise_graph/**`

```bash
uv run pytest packages/promise-graph
```

Add the property suite when the change touches an engine invariant — classification,
propagation, availability, settlement, fingerprinting:

```bash
HYPOTHESIS_PROFILE=ci uv run pytest packages/promise-graph/tests/properties
```

CI enforces `--cov-fail-under=95` on this package. Add
`--cov=promise_graph --cov-branch --cov-fail-under=95` only when the change adds or removes
engine branches.

### `packages/order-contract/**` or `apps/order-simulator/**`

No database, no network, no credential.

```bash
uv run pytest packages/order-contract apps/order-simulator
```

### `apps/backend/src/promisepatch/semantic/**`, `domain/grounding.py`, `domain/interpretation.py`, `domain/observation.py`, `domain/explanations.py`, `domain/verbalisation.py`

The semantic boundary runs with **no database and no AWS account**. Prefer this over the
backend suite — it is the fast path.

```bash
uv run pytest \
  apps/backend/tests/test_semantic_contracts.py \
  apps/backend/tests/test_semantic_provider.py \
  apps/backend/tests/test_semantic_grounding.py \
  apps/backend/tests/test_explanations.py \
  apps/backend/tests/test_bedrock_semantic.py \
  apps/backend/tests/test_openai_semantic.py \
  apps/backend/tests/test_nvidia_semantic.py
```

### `apps/backend/src/promisepatch/{api,db,graph,worker,integrations,fixtures}/**` or `domain` workflow handlers

These need the local PostgreSQL. **Stop the worker first** — it shares the local database with
the suite and will claim the steps a workflow test just enqueued:

```bash
docker compose stop worker
uv run python scripts/with_local_env.py -- uv run pytest apps/backend/tests/<the targeted files>
docker compose start worker
```

Name the test files that cover the change. **Do not run the whole `apps/backend` suite for a
small or unrelated change** — it is the slowest gate here, needs the stack up, and CI runs it
in full on every push anyway. The order-system boundary proof is one file:

```bash
uv run python scripts/with_local_env.py -- uv run pytest apps/backend/tests/test_order_system_boundary.py
```

### `evals/**`

Offline only. No credential, no network.

```bash
uv run pytest evals/tests
```

When the dataset, its manifest, or a production rule the dataset asserts against changed:

```bash
uv run python -m evals validate
uv run python -m evals replay
```

For the explanation gate specifically:

```bash
uv run python -m evals explanation-validate
uv run python -m evals explanation-plan      # zero-call preflight
uv run python -m evals explanation-replay
```

For anything beyond replay — a live run, a budget, an authorisation, a split — use the
`eval-runbook` skill. Do not improvise a live invocation here.

### `scripts/**`

```bash
uv run pytest scripts/tests
```

### `apps/frontend/**`

```bash
cd apps/frontend && npm run typecheck && npm run lint && npm test
```

`npm ci` only when `package-lock.json` changed. Leave `npm run build` and the Playwright `e2e`
suite to CI unless the change is in the build config or the browser flow itself.

## Step 4 — mypy, in its three separate groups

The groups are **not** interchangeable and must not be merged. Run only the group that covers
the changed paths.

```bash
uv run mypy packages/promise-graph packages/order-contract apps/backend   # group A
uv run mypy apps/order-simulator                                          # group B
uv run mypy evals scripts                                                 # group C
```

Group B is separate because both test directories carry a `conftest`. Group C is separate
because it needs the `evals` dependency group, which the backend type-check job does not
install — `uv sync --frozen --all-packages --group evals` first if it is missing.

## Step 5 — import-linter, only when boundaries warrant it

```bash
uv run lint-imports
```

Run it when, and only when, the change:

- adds or removes an `import` in a module named in a `[[tool.importlinter.contracts]]` entry;
- adds a new module to a layered package (`promise_graph`, `promisepatch`, `promisepatch.semantic`, `evals`, the explanation stack);
- moves code between packages, or adds a third-party dependency;
- touches anything at a guarded seam — engine purity, the semantic boundary, consent, the
  outbound adapter, the vendor SDK bans, or measurement-never-becomes-production.

It needs the evals group installed (`--group evals`), because two contracts are about that
package. Skip it for a body-only edit that adds no import.

## Step 6 — report

State plainly:

- what you ran and the result;
- what you deliberately skipped and why;
- that CI remains the broad regression authority.

If something failed, fix the code or the fixture data and say which. Never weaken, skip or
delete a test to make it pass.
