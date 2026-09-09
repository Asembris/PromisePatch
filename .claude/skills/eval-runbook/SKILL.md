---
name: eval-runbook
description: Operating checklist for running a PromisePatch live evaluation.
disable-model-invocation: true
---

# eval-runbook

A checklist, not a runner. **This skill executes nothing and authorises nothing.** Loading it
must never cause a provider call, a paid inference, a budget change, or a holdout read. Every
live step below is performed deliberately by the operator, at a shell, with an authorisation
phrase they typed themselves.

It deliberately duplicates **no** price, hash, threshold, budget figure or dataset identity.
Those live in the files named below and are authoritative there; a copy here would drift and
become a hazard.

## Authoritative sources — read these, do not restate them

| Subject | File |
|---|---|
| Full evaluation protocol, commands, spending policy | `evals/README.md` |
| Explanation gate protocol | `docs/explanation-quality-gate.md` |
| Scope-bound authorisation and spend interlocks | `evals/authorisation.py` |
| Prices, ceilings, budget guard | `evals/budget.py`, `evals/explanation_budget.py` |
| Thresholds and gates | `evals/thresholds.py`, `evals/explanation_thresholds.py` |
| Dataset identity and manifests | `evals/dataset.py`, `evals/explanation_dataset.py`, `evals/datasets/*manifest.json` |
| Result persistence and resume | `evals/store.py`, `evals/explanation_store.py`, `evals/results.py`, `evals/explanation_results.py` |
| Live composition roots | `scripts/run_semantic_benchmark.py`, `scripts/run_intent_challenger.py`, `scripts/run_explanation_eval.py` |
| Prior runs and what they concluded | `docs/semantic-benchmark*.md`, `docs/*challenger*.md`, `docs/explanation-quality-gate.md` |

## 1. Preflight — before any money

- [ ] Working tree clean; commit recorded. A run is identified by the commit it ran at.
- [ ] Dataset agrees with production: `uv run python -m evals validate` /
      `uv run python -m evals explanation-validate`.
- [ ] Manifest current. If the dataset changed deliberately, regenerate with
      `--write` and commit that as its own change.
- [ ] Zero-call preflight passes: `uv run python -m evals explanation-plan`. It builds no
      client and calls nothing — confirm that is still what it reports.
- [ ] Offline replay is green: `uv run python -m evals replay` /
      `explanation-replay`, plus `uv run pytest evals/tests scripts/tests`.
- [ ] Thresholds reviewed and agreed **before** seeing any live result.

If offline replay is red, stop. A live run cannot be interpreted against a broken instrument.

## 2. Authorisation — a deliberate act, not a setting

- [ ] The scope-bound phrase is typed **on the command line only**. Never `.env`, never
      `Settings`, never an environment variable, never a default.
- [ ] The phrase names **this** scope. Approval for one split or stage is not approval for
      another.
- [ ] Authorisation is not a budget. Both are required: the deliberate decision *and* a hard
      ceiling that refuses the call which would cross it.
- [ ] A missing credential must refuse before a client exists — no fallback provider, no
      fallback model.
- [ ] `--live` names a code path. It is not permission to spend.

Confirm the exact phrase and flag shape from `evals/authorisation.py` and the runner's own
`--help`. Do not reconstruct it from memory.

## 3. Budget

- [ ] Explicit call cap and dollar cap passed at the invocation.
- [ ] Prices in `evals/budget.PRICES` current, with date and source recorded.
- [ ] Cheap model first. Small dataset first. No automatic broad challenger sweep.
- [ ] Raising a ceiling is a conscious act, recorded with the run.

## 4. Split discipline

- [ ] **Development split first**, always. A prompt is judged there and nowhere else.
- [ ] **HOLDOUT is separately authorised and sealed.** Read it once, for a decision that is
      already made. Never iterate a prompt against holdout results. Never open holdout prose
      to browse it.
- [ ] Holdout authorisation is its own scope. It is never implied by a development
      authorisation.

## 5. Execution

- [ ] Provider is passed *in* to the runner; the runner does not choose one. Everything it is
      handed is wrapped in the budget guard before it is asked anything.
- [ ] A call nobody answered is not a reading — check `execution_status`
      (`ANSWERED` / `PROVIDER_FAILURE` / `NOT_INVOKED`) before believing a score.
- [ ] Fallback rate and provider failures recorded, not silently averaged away.

## 6. Persistence, resume and cost accounting

- [ ] Results persisted as they are produced, so an interrupted run resumes instead of
      re-spending. Resume rather than restart.
- [ ] Rebuild a report from stored results with the runner's `--from-results` path — that
      makes **no** calls. Prefer it over re-running.
- [ ] No duplicate execution: a case already answered at this identity is not paid for twice.
- [ ] **Two accountings, never one counter.** Generation usage and judge usage are separate
      totals and must stay separate.
- [ ] Cost is `Decimal`. Never float.

## 7. Report

- [ ] Record: dataset version and hash, commit, prompt identity, provider, model, every
      metric, every gate, the operational numbers, and the spend.
- [ ] Write it up in `docs/` as its own change.
- [ ] No synthetic validation, no invented metrics, no performance or impact claims. Report
      what was measured, including what failed.

## Never

- Never let an agent, hook or automatic flow reach a live evaluation. Live inference stays an
  explicit, operator-typed, scope-bound act.
- Never store an authorisation phrase or an API key in a file, a setting, or a commit.
- Never iterate against holdout.
- Never weaken a threshold to make a run pass.
