# `SUR-1` corrected scored run: taken, preserved, and refused before any arm acted

**The corrected `SUR-1` scored comparative run was executed on 2026-09-20 under execution
revision `v2` at `DRIVER_VERSION` `1.1.1`, and is preserved exactly as it came out.** All 27 of
its attempts ended `HARNESS_FAILURE` in world preparation, before an arm was constructed and
before a model was reached. **No Bedrock inference was performed and nothing was spent.**

`20260919T2020Z-scored` is untouched, byte-identical and still published inconclusive. This run
sits beside it and replaces nothing. Neither run is superseded by the other.

This document records the run and its cause. It is **not** the analytical publication narrative,
and there is nothing here to interpret comparatively — see §5.

Nothing was patched, nothing was re-run, no frozen artefact moved, no code changed, no holdout
was opened and no AWS resource was mutated.

| | |
|---|---|
| Run id | `20260920T1100Z-scored-corrected` |
| Artefacts | `docs/benchmarks/runs/20260920T1100Z-scored-corrected/` |
| Implementation SHA | `7dafc6d6581b969a6b792a5d3416d8ce50e1c415` (`main`, the expected HEAD) |
| `DRIVER_VERSION` | `1.1.1` |
| Driven | `2026-09-20T10:59:47Z` to `11:03:26Z`, 3 min 39 s wall clock |
| Model | `us.amazon.nova-2-lite-v1:0`, `bedrock-runtime` Converse, temperature `0.0`, `us-east-1` |
| Preflight | all seventeen `REQUIRED_CHECKS` passed in one report, `passed: true` |
| Attempts | 27 of 27, every one at `a1`; **0 retries, 0 `VOID`, 0 `BUDGET_EXHAUSTED`** |
| Outcomes | `HARNESS_FAILURE` 27 |
| Model calls | **0**. Input tokens 0, output tokens 0, tool calls 0 |

## 1. What the run did

Nine scenarios `C01`–`C09` across three arms, driven through `scripts.sur1.run --kind scored`,
which ran the preflight in-process, minted the scored authorisation from the passing report, and
called `drive`. No `drive()` bypass, no manual arm invocation, no scenario omitted or reordered,
no benchmark edited.

Every attempt raised `PreparationError` inside `realisation._write` and was classified
`HARNESS_FAILURE` with the reason recorded on the capture. `HARNESS_FAILURE` is not retryable —
`RETRYABLE` is `{"VOID"}` — so the policy permitted no retry and none was taken. Every attempt
was captured before any of this was read.

Verdicts were written blinded and stayed blinded: each carries `arm_token` and no `arm`, no
`latency_seconds` and no `cost`. Blinding was asserted over all 27 verdict files **before**
`join` was called; the join then added exactly those three fields and wrote `result.json`.

## 2. The cause

**The in-process fixture load and the evidence receivers named two different databases, and the
harness refused rather than driving.** The recorded reason, identical on all 27 attempts:

```
PreparationError: the fixture load resolved aws-1-eu-west-1.pooler.supabase.com:5432/postgres
and the receivers read 127.0.0.1:55432/promisepatch; installing a world into one database and
reading evidence out of another would produce readings about a world that was never installed.
Load the local environment (scripts/with_local_env.py) so both name the same database.
```

The repository's root `.env` points `PP_DATABASE_URL` and `PP_MIGRATION_DATABASE_URL` at a
hosted Supabase instance. `pydantic-settings` reads `.env` from the working directory, so
`promisepatch.config.get_settings()` — which is what the governed fixture load resolves its
connection from — returned the hosted URL. The `SUR1_*` variables the harness itself reads were
correct and local throughout; only the product settings the load consults were not.

**This is an operator fault in the invocation, not a defect in the benchmark.** The run was
driven without `scripts/with_local_env.py`, which exists for exactly this, loads
`docker/env/host.env` into the real environment, and takes precedence over `.env`. The error
message names that remedy verbatim.

### 2.1 The guard worked, and what it prevented

`realisation._write` raises **before** `build_engine` is called, so no connection was opened to
the hosted database and `reset_demo_state` never ran against it. Had the guard not been there,
each of 27 attempts would have run `pp reset-demo-state` — a `TRUNCATE` across forty-two
tables — against a hosted Supabase database, and then read evidence out of the local one.

That is a fail-closed refusal behaving exactly as the authority invariants require, and it is
recorded here as a success of the machinery rather than as a failure of it.

## 3. Where this was not caught

**The scored preflight asked seventeen questions and passed all seventeen while the mismatch
existed.** None of them asks *whether the database the fixture load will resolve is the database
the receivers read.*

`backend_build` comes closest and does not cover it. It asks the running API for its migration
revision and checks that against the source tree, and it checks the *signature* of the governed
fixture load — that it accepts a stated `snapshot` and `fixture_name`. It does not resolve the
load's connection string, and it does not compare it with `SUR1_DATABASE_URL`.

This is structurally the same shape as the `v1` defect that
[`sur1-execution-revision.v2.md`](benchmarks/sur1-execution-revision.v2.md) §3.1 corrected:
reachability and capability were both asked, and the one question that would have refused the
run early was not.

**It is a named, reproducible gap in the preflight, recorded here and not fixed in this
session.** Under [`sur1-phase3-closeout.md`](sur1-phase3-closeout.md) §8 a change beneath
`scripts/sur1/` requires a named defect, a disclosure beside the predeclaration, a re-frozen
identity, and a different session from the one that takes a run. This document is the first;
the rest are not this session's to do.

## 4. What the run does establish

Three things were exercised live across 27 consecutive cycles, and all three held. None of them
is a comparative result.

- **The `1.1.1` lifecycle survived 27 quiesce/resume cycles.** `docker compose stop worker` and
  `up -d --wait --no-deps --no-recreate worker` ran once per attempt. All four containers were
  `running / healthy` afterwards, on the validated images.
- **A failed install still hands the worker back.** Every one of the 27 installs failed, and the
  worker was returned each time rather than left down — the behaviour
  `sur1-execution-revision.v2.md` §3.2 specifies for exactly this case.
- **The three first-run failure signatures did not recur.** No `missing idempotency_key`, no
  `ungoverned write` / `InsufficientPrivilegeError`, and no `DeadlockDetectedError` appears
  anywhere in the 27 captures or the 27 verdicts. The run did not reach the code paths where the
  first two arose, so this is an absence rather than a positive proof of their repair.

## 5. What this run does not say

**It says nothing comparative, and less than the first run did.** All 27 attempts failed in
preparation, for a reason that has nothing to do with what any arm decided. No arm was
constructed, no model was called, no tool was invoked, no evidence row was collected, and no
scenario produced a scored verdict of any kind.

Every safety counter is zero across all three arms because no attempt reached the scorer with
anything to score, and **a zero that was never measured is not a clean safety record.** The
frozen primary metric has an empty denominator on every arm: `recoverable_denominator` and
`escalation_denominator` are `0` everywhere. No thesis was tested and no falsification was
attempted.

## 6. Disclosures carried forward, unchanged

The `C02` disclosure from [`sur1-consent-ingress.md`](sur1-consent-ingress.md) and
[`sur1-phase3-closeout.md`](sur1-phase3-closeout.md) §2 stands exactly as published and is
untouched by this run: on `C02` the apparent-assent hazard is posed to the baseline and not to
arms B and C, so a `C02` `consent_violations` reading for B and C may be vacuous rather than
earned. `C02` produced no verdict here, so the question did not arise.

The two observations `sur1-execution-revision.v2.md` §6 recorded as *not fixed* both recur
unchanged: `estimated_usd` is `unavailable` on all 27 attempts, and `run.json` carries
`finished_at: null`.

Both evaluation holdouts remain sealed. The `SUR-1` scored path imports no `evals` module.

## 7. What was not done

- **Nothing was patched and nothing was re-run.** The stale invocation was left exactly as it
  was, and no second run was taken in this session.
- **No frozen artefact moved.** All five identities were verified before the run and match:
  manifest `5718340f…`, prompt `772ba460…`, `PREDECLARATION_SHA` `c53d267a…`, `program_set_sha`
  `88db566c…`, `implementation_sha` `cb1686bf…`. `declaration.differences()` is empty, and all
  nine `C01`–`C09` program hashes and world digests agree.
- **No code was modified**, before or after the run.
- **`20260919T2020Z-scored` is byte-identical.** Its tree is
  `080fceda57a56cb36b1c32088eb74822c2fb7ebd`, all 57 files are present, and `git status` reports
  no modification under it.
- **No replacement result exists.** `result.json` is written by `write_once` in both runs and
  neither can be rewritten.
- **Nothing was deployed and nothing was pushed.** No sensitivity model was run.
- **No holdout was opened**, and no hosted database was contacted.
