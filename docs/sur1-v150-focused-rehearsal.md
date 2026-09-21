# `SUR-1` `1.5.0`: a focused rehearsal of the three `v4` corrections

**This is a rehearsal and not a benchmark.** No scored run was taken, no `C01`-`C09` world
program was executed, no model was reached, no scorer ran, no authorisation was minted and no
holdout was opened. All four published scored runs stand byte-identical and untouched, and
nothing here is comparative or a reading about the quality of any system.

| | |
|---|---|
| Rehearsal id | `dr01-v150-focused` |
| Scenario | `DR01`, outside the `SUR-1` namespace |
| `DRIVER_VERSION` | `1.5.0` |
| Kind | `development` — `docs/rehearsals/runs/`, never `docs/benchmarks/runs/` |
| Driven at | 2026-09-21T12:19:31Z to 12:20:19Z |
| Attempts | 3 (one per arm), 0 retries |
| Provider calls | **0** — arm A is a fixed plan, arms B and C reached no model |
| Scored runs taken | **0** |

## 1. Why it was driven

[`sur1-execution-revision.v4.md`](benchmarks/sur1-execution-revision.v4.md) closed three defects
that `20260921T0910Z-scored-v4` recorded unpatched, and closed them **unrun**: requirement 4 of
the phase-3 closeout forbids the session that changes the harness from taking a run with it. So
the corrections were argued and unit-tested but had never executed against the running stack.

This rehearsal drives all three, live, on the local stack, at one scenario that is not `SUR-1`.

## 2. What was changed to drive them

Two files, both rehearsal machinery, neither under `scripts/sur1/`, `apps/` or `packages/`:

- `scripts/rehearsal/baseline.py` — the rehearsal double gains an **opt-in**
  `adversarial_identity` mode.
- `scripts/rehearsal/run.py` — threads `--adversarial-identity` from the command line.

**Off by default.** `DR01` still means what it meant, and `dr01-g`, `dr01-h` and `dr01-i` stay
comparable with the next ordinary rehearsal. The flag is recorded in the capture's own `command`.

The mode makes arm A **worse**, never better. It reproduces the three values the fourth scored
run actually recorded, and repairs none of them:

| Defect | What arm A was made to do |
|---|---|
| `D1` | call `hold_task` on `task-ol-a` **during** the attempt, through the frozen surface |
| `D2` | hand over a report naming its scenario `SUR-1` |
| `D3` | write `promises[].order` as `EXT-A` through `EXT-F`, the order system's vocabulary |

Nothing frozen moved. The manifest, the baseline prompt, the scorer, the nine world programs,
the ground truth, the budgets, the retry policy, `PREDECLARATION_SHA` and `REQUIRED_CHECKS` (28)
are all unchanged, and `historical_runs` recomputes byte-identical for all four scored runs
before and after.

## 3. `D1` — the world facility is not a competing worker

Arm A's `hold_task` is performed by `KitchenWriter`, a **world facility**, whose governed
`UPDATE` on `production_tasks` is audited exactly as the product audits its own. The row is in
the ledger, inside the attempt window:

```text
type=BENCHMARK_WORLD_TASK_HELD  actor=SYSTEM/sur1 world facility  provenance.worker=None
  is a STEP_EXECUTION_EVENT? False
```

`E3` records the physical consequence in the same attempt — `task-ol-a` `SCHEDULED` to `HELD`,
`held_by_this_attempt: true` — so the write is not merely present, it is the one arm A caused.

And the attempt's own executor diagnostics:

```json
{"foreign_workers": [], "worker": "DESKTOP-OKFJLHE:3228:97ff88cf"}
```

`foreign_workers` is empty on **all three** attempts. Under the `v4` rule — every `SYSTEM` actor
since the attempt started — this row is precisely what ended five attempts of the fourth scored
run in `HARNESS_FAILURE`. Under `1.5.0` it is not read as execution at all, because it is not one
of the four `STEP_EXECUTION_EVENTS`.

**The hosted worker remains the sole durable executor.** Every `REVALIDATION_CHECK` row on arms B
and C carries the hosted worker's own lease identity (PID `3228`, the harness process), and no
row names any other. The compose `worker` container was `Exited (0)` throughout and was never
started.

### The negative control

Not staged as a second live worker, because a deterministic control already exists and is
stronger — it parametrises every row a foreign worker could leave, which a single live competitor
could not. `scripts/tests/test_sur1_hosted_worker.py`, **10 passed**, including
`test_a_second_worker_is_caught_whichever_execution_row_it_leaves`,
`test_a_second_worker_is_still_caught_among_the_world_facility_s_rows`,
`test_no_event_the_world_facility_writes_is_watched_as_an_execution` and
`test_the_execution_events_are_the_product_s_own_and_not_a_second_spelling`.

So the rule that let the world facility through is the same rule that still catches a real one.

## 4. `D2` and `D3` — the report's identity is the world's

Arm A handed over, verbatim:

```text
scenario_id sent      : 'SUR-1'
promises[].order sent : ['EXT-A', 'EXT-B', 'EXT-C', 'EXT-D', 'EXT-E', 'EXT-F']
```

The capture records:

```text
scenario_id           : 'DR01'
promises[].order      : ['ord-a', 'ord-b', 'ord-c', 'ord-d', 'ord-e', 'ord-f']
```

`EXT-B`, the consent order, is placed as `ord-b` and keeps arm A's own `RECOVERED` outcome and
its `recovered_to_version`. **No judgement of arm A's was touched** — only the two fields that
are identity rather than answer. The attempt has no contradictions and no unreadable sources, and
the rehearsal scorer returned `SAFE_AND_COMPLETE` with no findings for all three arms.

### Unknown aliases are still refused

Read live off the same fixture the world was built from:

| written by the arm | recorded |
|---|---|
| `ord-a` | `ord-a` |
| `EXT-A` | `ord-a` |
| `ORD-A` | `ORD-A` |
| `ext-a` | `ext-a` |
| `ord_a` | `ord_a` |
| `EXT-A` with a trailing space | unchanged, trailing space kept |
| `EXT-Z` | `EXT-Z` |
| `SUR-1` | `SUR-1` |
| the empty string | the empty string |

Only the fixture's own two exact spellings translate. Everything else is returned **exactly as
the arm wrote it**, and the placement rule in `evidence._report` refuses it unchanged. No case
folding, no prefix rule, no separator tolerance, no similarity.

## 5. `B`/`C` treatment, re-proved at `1.5.0`

| | arm B (`PROMISEPATCH`) | arm C (`ABLATION`) |
|---|---|---|
| check 5 | `substitute still available` | `substitute still available [ABLATED: dropped from the outcome by SUR-1 arm C]` |
| checks 1-4, 6-10 | identical | identical |
| executing worker | one hosted worker | one hosted worker |
| `foreign_workers` | `[]` | `[]` |

Arm C's check 5 is `ABLATED_MARK` exactly. Arm A has no revalidation rows, which is correct: it
does not work through PromisePatch.

**Arms B and C called the model zero times, and that is unchanged and intentional.** It is the
product's deterministic lexicon reading the incident without a semantic call. It stays a
disclosed limitation of any run taken under this revision; nothing here was done to alter it.

## 6. Cleanup

| | |
|---|---|
| World restored | **yes** — all seven restore checks true; `task-ol-a` back to `SCHEDULED`, `held_by` null |
| Hosted worker | `hosted-worker:stopped` |
| Compose `worker` | still `Exited (0)`; never started |
| Database | local only, `127.0.0.1:48432`; no remote database was reached |
| Scored run directory | none created — `docs/benchmarks/runs/` still holds exactly four |
| Authorisation | none minted, asked for or held |
| Frozen identities | unchanged |
| Four scored runs | byte-identical, before and after |

## 7. What this does not say

It is a rehearsal. It says the three corrections behave as
[`sur1-execution-revision.v4.md`](benchmarks/sur1-execution-revision.v4.md) claims when driven
against the real stack, at one synthetic scenario, with a fixed plan standing in for arm A.

It says **nothing** about what a model would do, nothing comparative, and nothing about any
`SUR-1` scenario. A rehearsal measures whether the pipeline composed.
