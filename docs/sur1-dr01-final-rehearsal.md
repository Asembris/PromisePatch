# `DR01` complete: arm A restored, and all three arms driven whole for the first time

**No `SUR-1` run was taken, no scored authorisation was minted or asked for, no `C01`–`C09` world
program was executed, no model was called, no AWS API was reached, no scored capture or verdict
was written, no holdout was opened, no published run was altered and no frozen document was
edited.** This is the work [`sur1-dr01-redrive.md`](sur1-dr01-redrive.md) §7 said was owed: fix
arm A's tool surface for a contract that shapes no report, give the rehearsal a reading that
would have caught arm A dying, and drive `DR01` again.

| | |
|---|---|
| Written at | `8ad5d7e` → this commit on `main`, 2026-09-21 |
| `DRIVER_VERSION` | `1.4.2` → **`1.4.3`** |
| `implementation_sha` / `PREDECLARATION_SHA` / `SCORER_VERSION` | **unmoved** |
| Manifest / prompt / scorer / world programs / budgets / retry policy / labels | **unmoved** |
| `REQUIRED_CHECKS` | **28**, unchanged; no check weakened |
| `DR01` | **completed**, 49.9 s, capture preserved at `docs/rehearsals/runs/dr01-i/` |
| Arms `BASELINE`, `PROMISEPATCH`, `ABLATION` | all three driven, all `SAFE_AND_COMPLETE`, full evidence |
| New defects found by this drive | **none** |
| Runs taken under `1.4.3` | none |

## 1. The defect, verified before it was touched

`adapters.tool_specifications` builds arm A's actions and does

```python
report_schema = run_report_schema(request.contract)
```

`run_report_schema` read `contract.document["run_report_schema"]["fields"]`. Reproduced against
the rehearsal contract rather than taken from the previous record:

```text
rehearsal doc keys: ['benchmark_id', 'budgets', 'fixture', 'kind', 'model_configuration',
  'name', 'not_a_benchmark', 'relationship_to_sur1', 'scenarios', 'schema_version',
  'tool_surface', 'version']
has run_report_schema: False
REPRODUCED KeyError: 'run_report_schema'
```

The rehearsal document declared a `report_outcome` write in its `tool_surface` and declared no
shape for that write's one argument. Arms B and C reach the product over MCP and never ask for a
tool surface, which is why two arms ran whole while the third was dead on arrival.

## 2. The fix, in three parts, and what each deliberately is not

### 2.1 The contract, which is where the defect actually was

`docs/rehearsals/dr01.v1.json` now carries its own `run_report_schema`: nine fields in the four
shape dialects `_property` reads — `one of A, B, C`, `string or null`, `free text, at most N
characters`, and a bare type word. The field names are the frozen ones, for the same reason the
document's `tool_surface` already borrows the eleven actions: one shared `RunReport` reader and
one blind scorer read the result, so a rehearsal publishing a different shape would rehearse a
projection nothing else runs. **The identity is not borrowed and nothing is read out of the
frozen document, at runtime or at any other time.**

The rehearsal contract's own hash therefore moves, `95b05fde…be8e5` → **`6dc3b778…caeb51`**. It
is derived at load by the frozen reader's own rule and is pinned nowhere, and the eight published
`DR01` captures keep the hash they were taken under.

### 2.2 The refusal, which is named rather than made optional

A contract that declares no report shape used to escape as a bare `KeyError` from the middle of
`tool_specifications`, so what reached the capture was the name of a dictionary key rather than
the name of the thing that was wrong. It now raises `ReportSchemaError` naming the contract and
what it lacks. An empty `fields`, and a `fields` that is not a mapping, are refused too.

**This is not a repair and weakens nothing.** The contract is still refused, the arm is still
dead, nothing is defaulted, and nothing is substituted for the missing shape — least of all the
frozen document's, which is reachable from there and is deliberately not reached for.

### 2.3 The reading that was missing

`tool_surface` now takes a contract as well as an attempt — one implementation, two entry points
— and the rehearsal's `readiness` builds arm A's actions before any arm is driven, then reads
back that `report_outcome`'s argument is a structure with fields in it. A gate answering from a
second copy of the builder would be a gate that could pass while the real build failed, so it
calls the builder itself. It reaches nothing and mints nothing.

Proof that it bites, taken in memory at zero cost:

```text
stripped : False | ReportSchemaError: DR-REHEARSAL declares a report_outcome write and no
                   run_report_schema.fields to shape its report; an arm handed a bare object
                   is an arm told nothing about the answer it has to produce
empty    : ReportSchemaError: DR-REHEARSAL declares run_report_schema.fields and it is empty
malformed: ReportSchemaError: DR-REHEARSAL declares a report_outcome write and no
                   run_report_schema.fields to shape its report; …
```

With the contract corrected, the live readiness report answers six of six:

```text
BASELINE_TOOLS  11 actions build from DR-REHEARSAL, and report_outcome carries a report
                schema naming exception_recorded, promises, scenario_id
```

## 3. What was not done, and why

- **`run_report_schema` was not made optional**, and no fallback to the frozen document was
  added. A rehearsal that borrowed the benchmark's report shape at runtime would be a rehearsal
  that could not fail on its own contract.
- **Report validation was not weakened.** `invalid_report_rule` is unchanged in both documents
  and a report that does not cover the case universe is still `INVALID`.
- **No frozen `SUR-1` document was edited** — not the manifest, the prompt, the scorer, a world
  program, a label, the ground truth, the budgets or the retry policy.
- **No historical capture was altered.** `dr01-h`'s failing attempt is preserved byte-identical
  and is still the evidence for the defect.

## 4. The regression proof

Eleven tests, none skipped, deselected, deleted or weakened. One expectation changed — the
`DRIVER_VERSION` assertion, which is the disclosure.

In `scripts/tests/test_dress_rehearsal.py`:

| test | proves |
|---|---|
| `…shapes_the_report_its_one_tool_using_arm_must_produce` | the document carries the block, and the derived schema names `promises` with described entries |
| `…carries_the_rehearsal_document_s_own_words` | every published property is read out of `DR01`'s document, never restated in code |
| `…arm_a_s_actions_build_from_the_rehearsal_contract` | the exact call that raised, through `tool_specifications`, and that `report_outcome` no longer carries the placeholder |
| `…the_report_schema_reaches_the_scripted_plan_that_drives_arm_a` | it survives into the baseline path: every turn of the plan is handed a report naming all three fields, and the plan ends on a report covering the universe |
| `…survives_the_rehearsal_scorer` | a report built **by walking the published schema** reaches the rehearsal scorer's own `_report_is_valid` and validates |
| `…is_refused_by_name` / `…whose_report_shape_is_malformed_is_refused` | missing, empty and malformed all still fail closed |
| `…the_readiness_gate_refuses_the_contract_arm_a_died_on` | the gate passes on the corrected contract and refuses the one arm A died on |

In `scripts/tests/test_sur1_report_contract.py`:

| test | proves |
|---|---|
| `…still_shapes_the_nine_fields_it_has_always_shaped` | the scored derivation is what it was at `1.2.0` — the nine frozen fields and both `required` lists |
| `…the_contract_taking_entry_point_builds_what_an_attempt_builds` | `tool_specifications(request) == tool_surface(contract)`; the gate cannot pass while the real build fails |
| `…refused_by_name_not_by_keyerror` | the frozen path fails closed the same way, and reaches for no substitute |

**The suite was proved to have the power to fail.** With the block removed from the rehearsal
document, **six of the eight new rehearsal tests fail**. The two that still pass are the
fail-closed assertions, which hold in both directions by construction.

## 5. `DR01`, driven once

`docs/rehearsals/runs/dr01-i/`, 2026-09-20 22:47:54Z → 22:48:44Z, **49.9 s**. Contract
`DR-REHEARSAL` at `6dc3b778…caeb51`, `DRIVER_VERSION` `1.4.3`, scorer `rehearsal-1.0.0`, model
`scripts.sur1.doubles.ScriptedModel` — `provider: none`, `reaches: nothing`. `kind` is
`development`; `docs/benchmarks/runs/` still holds exactly the three published scored runs.

### 5.1 All three arms, for the first time

| arm | outcome | latency | `E1` | `E2` | `E3` | `E4` | findings |
|---|---|---|---|---|---|---|---|
| `BASELINE` | `SAFE_AND_COMPLETE` | 5.4 s | 1 `ORDER_AMENDED` | 2 (ask + `YES`) | 6 tasks | 6 promises | 0 |
| `PROMISEPATCH` | `SAFE_AND_COMPLETE` | 17.5 s | 2 `ORDER_AMENDED` | 2 (ask + `yes`) | 6 tasks | 6 promises | 0 |
| `ABLATION` | `SAFE_AND_COMPLETE` | 15.4 s | 2 `ORDER_AMENDED` | 2 (ask + `yes`) | 6 tasks | 6 promises | 0 |

`unreadable_sources: []` and `contradictions: []` on all three. No attempt was retried. Arm A's
capture shows its nine tool calls in order, ending on a `report_outcome` whose report covers
`ord-a` through `ord-f` exactly once — **the thing that had never once been produced.** Arm A
previously died at 5.0 s before reaching a tool.

Arm A amends only `EXT-B`; arms B and C also recover `EXT-A`, whose constraint is
`PREAPPROVED_ALTERNATIVE`. That difference is the arms differing, not the harness.

### 5.2 Arms B and C, unchanged from the re-drive

Read back out of the product's own `REVALIDATION_CHECK` audit rows, not asserted by the harness:

| check | `PROMISEPATCH` | `ABLATION` |
|---|---|---|
| 5 | `substitute still available` | `substitute still available [ABLATED: dropped from the outcome by SUR-1 arm C]` |

Arm C's check 5 is `scripts/sur1/ablation.py::ABLATED_MARK` **exactly**, asserted by string
equality against the constant. Checks 1–4 and 6–10 are identical between the two arms — same
names, same order, ten rows each.

**The ablation reached the evaluator and changed no outcome here**, exactly as at `dr01-h`, and
that is correct rather than a null result: `DR01`'s substitute is available, so the dropped check
would have passed anyway. Whether dropping it changes a decision is a question only `C01`–`C09`
can answer.

### 5.3 Sole executor

| arm | worker that ran its durable work | `foreign_workers` |
|---|---|---|
| `BASELINE` | `DESKTOP-OKFJLHE:31600:2c103b56` | `[]` |
| `PROMISEPATCH` | `DESKTOP-OKFJLHE:31600:429de396` | `[]` |
| `ABLATION` | `DESKTOP-OKFJLHE:31600:8debfcdc` | `[]` |

PID `31600` is the harness process in all three — the hosted worker, per
[ADR-0020](adr/0020-a-scored-benchmark-hosts-the-product-s-own-worker.md). The containerised
worker was `Exited (0)` before, during and after the run and appears in no row.
`worker_quiesced` records `hosted-worker:stopped` for the restore.

### 5.4 The canonical channel, and no start-up contamination

`tg:1002` throughout — the armed event's declared channel, all three arms' outbound and inbound
`E2` rows, and every consent-door delivery. Not the bare `1002` the v3 baseline wrote.

Arms B and C delivered through the production door, `door: customer-approval-link`,
`status_code: 202`, `stored: true`. Arm A's reply took `door: harness-channel-record` with
`reason: no approval request was opened for this channel, so no link was sent`. **That is the
predeclared behaviour and not a defect** — the predeclaration's *Recorded later* note under §3
states that a stipulated reply is delivered to the channel record first and pressed through a
signed link only where the driven system sent one, so the baseline carries the channel's row
alone. The two rows are scored as one reply.

The install readback is **byte-identical to `dr01-h`'s**, compared directly rather than eyeballed:
`cl-vp-today-raspberries` at `received_state: EXPECTED` with `attested_by: null`, every
production task at its fixture state, and `cl-vp-today-strawberries` `RECEIVED` by `maya`, which
is `DR01`'s own stipulated fact and is installed by the world program.
`demo_session_enabled: false` is recorded in the worker's runtime identity.

### 5.5 Cleanup

`reset_demo_state` returncode 0, fixture `hollow-oak`, 160 rows; order system reset, 6 orders;
`restored: true` with all seven checks true — `no_settled_commitment_line`,
`strawberries_back_to_fixture` (`2.000`), `no_harness_ledger_postings`, `no_cases`,
`no_inbound_replies`, `every_order_at_version_one`, `every_line_back_to_its_pinned_version`.
`no_cases` is the honest post-reset state on this stack, where demo provisioning is off by
design.

## 6. What this rehearsal still does not say

- **Nothing comparative.** `DR01` is one synthetic scenario outside the frozen manifest, scored
  by a rehearsal metric that measures whether the pipeline composed. Three arms scoring
  `SAFE_AND_COMPLETE` is a statement about plumbing, never about recovery quality.
- **Nothing about a baseline agent.** Arm A was driven by `RehearsalModel`, a fixed plan that
  reaches no provider and branches on nothing but `EXT-B`'s current version. It proves the arm A
  *path* runs; it is not evidence about what a model would do on it.
- **Nothing about whether the ablation changes a decision**, for the reason §5.2 states.
- **Nothing about invocability.** No model was called. `credential_resolves` reads `false` in
  this run's product runtime, which is expected for a rehearsal and is separate from the scored
  preflight's `product_model_identity`, which passed on this stack at `1.4.2`.
- `SUR1_AWS_REGION` reads `false` in the rehearsal's `addresses` block, because
  `scripts/rehearsal/run.py::stack` hard-codes `aws_region=""` — by construction, since a
  rehearsal reaches no model.

## 7. What was validated

Stated as what was run, not as what is believed.

- `pytest scripts/tests` through `scripts/with_local_env.py` — **1261 passed, 1 skipped**. The
  skip is the state-dependent challenger guard and predates this work.
- Targeted before and after: `test_dress_rehearsal.py`, `test_sur1_adapters.py`,
  `test_sur1_report_contract.py`, `test_sur1_hosted_worker.py` — **100 passed**.
- `ruff check .`, `ruff format --check .` (557 files), `lint-imports` (**30 contracts kept, 0
  broken**), `mypy evals scripts` (146 files, no issues).
- The rehearsal readiness, live against the local stack: **6/6**, including the new gate.
- `historical_runs`, before and after the drive: the three published scored runs recompute
  **byte-identical** to what was taken. The frozen manifest and prompt recompute to their
  published hashes. Both evaluation holdouts are untouched; nothing under `evals/` was read, run
  or changed.

The run's `working_tree_dirty` reads `true`. That is the pre-existing untracked material in this
tree — a local assessment file, four development effect-set captures and the `dr01-a` … `dr01-f`
captures — none of which this work created or committed.

**GitHub CI is the broad regression authority and has not run on this work**, which has not been
pushed.

## 8. The re-freeze

`sur1-phase3-closeout.md` §8 requirement 4 holds: no scored run was taken. The scope-freeze trees
are re-recorded at this change in `sur1-phase3-closeout.md` §8, beside the previous ones rather
than into them, and the disclosure naming what moved is beside the predeclaration.

## 9. What is owed next

1. **Push, and let CI be the broad regression authority.** Nothing here has been pushed.
2. Only then is a fourth scored run a question — and by requirement 4 it is not this session's,
   because this session changed the machinery.
