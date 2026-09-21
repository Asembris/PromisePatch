# `SUR-1` execution revision `v4`: three defects the fourth scored run recorded unpatched

**No published scored run is superseded, replaced, reinterpreted or re-run by anything in this
document.** All four stand published and immutable: `20260919T2020Z-scored` **inconclusive**,
`20260920T1100Z-scored-corrected` **incomplete**, `20260920T1215Z-scored-v3` **invalid**, and
`20260921T0910Z-scored-v4` **comparatively empty**. Any run taken under this revision is a
*corrected execution beside all four* and must be published as such.

This is the disclosure [`sur1-phase3-closeout.md`](../sur1-phase3-closeout.md) §8 requires before
a change beneath `scripts/sur1/`: named defects with reproductions, a statement of what moved and
in which direction, and the re-frozen identities that cover the changed bytes. **No run was taken
to produce it, no rehearsal was driven, no model was called, no scorer ran, no AWS resource was
touched, nothing was deployed and no holdout was opened.**

Requirement 4 holds and is load-bearing: the session that made this change takes no run.

| | |
|---|---|
| Revision | `v4` |
| Supersedes | **nothing** |
| Corrects | the measurement system only |
| Prior runs preserved | all four, byte-identical at this revision — see §6 |
| `DRIVER_VERSION` | `1.4.3` → **`1.5.0`** |
| `implementation_sha` | **unmoved** at `c93b38a71296ba13744a7f0738394feaf3f2ae09ca61a939afa1ca3269e545f7` |
| `PREDECLARATION_SHA` / `SCORER_VERSION` | **unmoved** |
| Frozen benchmark elements | **all unchanged** — see §5 |
| Scored preflight | **28 checks, unchanged**; none weakened |
| Files under `apps/` or `packages/` | **none edited** |

## 1. The three defects

All three were observed in `20260921T0910Z-scored-v4` and recorded there unpatched. Its §3 is the
run's own statement of them; this is the correction.

| # | Defect | Attempts it cost | Arms |
|---|---|---|---|
| `D1` | the world facility read as a competing worker | 5 | all three, on `C06`; the baseline on `C01` and `C02` |
| `D2` | the baseline's `scenario_id` taken from the model | latent — masked by `D3` | arm A only |
| `D3` | the baseline's `E4` orders in the order system's vocabulary | 6 | arm A only |

Together `D1` and `D3` account for all nine unscored baseline attempts. `D2` was masked: placement
raised before validity was reached, so no verdict in that run recorded it. It would have made every
baseline report `INVALID` after `D3` alone was fixed.

### `D1` — `sur1 world facility` is not a second durable worker

**Observed.** Five attempts ended `HARNESS_FAILURE` with one reason, identical across all five:

```text
durable work in this attempt was executed by sur1 world facility as well as by the hosted
worker; part of it ran in a process arm C's wrapper does not reach, so this attempt is a
reading of no declared arm
```

**Root cause.** `HostedWorkerControl.executed_only_by_the_hosted_worker` selected every `SYSTEM`
actor in `audit_events` since the attempt started. The harness's own `GovernedWriter` writes
`Actor(SYSTEM, "sur1 world facility")`, because a stipulated kitchen hold is an `UPDATE` on
`production_tasks` and a stipulated stock movement is an `INSERT` into `inventory_ledger`, and
both tables are governed — the write is audited exactly as the product audits its own. Setup rows
carry a different actor (`sur1 world program`) and land before `started_at`, so only *during*-
attempt world writes collided. `C06` arms a stock movement, which is why all three arms were
refused there; `C01` and `C02` hold a kitchen task on arm A's behalf.

**Reproduction.** `scripts/tests/test_sur1_hosted_worker.py::test_the_world_facility_s_own_writes_are_not_a_competing_worker`,
which puts the three rows the world facility actually writes into a ledger stand-in that applies
the statement's own `WHERE` clause, and requires no fault.

**What was wrong with the rule.** Not the guard — ADR-0020 §5 is right that a second worker
executing benchmark steps makes an attempt unreadable. What was wrong is that *a governed write*
and *a worker executing a durable step* were treated as the same fact. They are not, and the
harness is the one thing in the system that performs the first without ever performing the second.

### `D2` — a scenario identifier is bookkeeping, not judgement

**Observed.** Arm A wrote `scenario_id: "SUR-1"` — the benchmark's name, taken from the frozen
prompt's header — and `_report_row` read `report.get("scenario_id", scenario_id)`, so the model's
value won and the world's was a fallback for an absent key.

**Root cause.** Arm A is never told a scenario identifier. The frozen prompt names the benchmark;
`get_incident` returns the reported utterance, the clarification and the answer, and no id. The
frozen `run_report_schema` asks for `scenario_id` as a string and nothing anywhere says which
string. So the only value the arm could send is a guess, and the harness believed it.

**Reproduction.** `scripts/tests/test_sur1_report_contract.py::test_the_scenario_id_recorded_is_the_attempt_s_and_not_the_model_s`
drives the exact value through the world's own `report_outcome`, the blinding projection and the
scorer's `_report_is_valid`.

### `D3` — `E4` in one vocabulary, the case universe in another

**Observed.** Six baseline attempts ended `HARNESS_FAILURE` at scoring with:

```text
the evidence could not be placed: E4 reported on 'EXT-A', which is not in the case universe
```

**Root cause.** The world's eleven frozen actions speak two names for one order. `get_orders` and
`amend_order` are the order system's surface and answer in its external ids (`EXT-A`);
`get_tasks` and `get_promise_graph` answer in the case universe's own (`ord-a`). Nothing in the
prompt or the schema says which one a report means. `E1` has been canonicalised through the frozen
fixture's bijection since the harness was built — `FixtureMap.order_for_external_id` — and `E4`
was not. Arms B and C never met this: their `E4` is projected by `predeclaration.worker_report`,
which is handed `order_for_external_id` and translates.

**Reproduction.** `scripts/tests/test_sur1_report_contract.py::test_an_external_order_id_is_placed_in_the_case_universe`,
and `test_the_report_v4_s_baseline_actually_produced_is_now_placed_and_valid`, which drives `D2`
and `D3` together in the shape the run recorded them.

## 2. What was changed

Three edits, in two files, both of them harness. Nothing under `apps/` or `packages/` was touched.

### 2.1 `scripts/sur1/bindings/hostedworker.py` — executor evidence

`executed_only_by_the_hosted_worker` now reads the four audit types the product writes when a
**worker executes something durable**, and the executing worker out of each row's
`provenance.worker`, which is `claim.lease_owner` — the lease the work was done under:

| Event | Written by | Carries |
|---|---|---|
| `WORKFLOW_STEP_EXECUTED` | `domain.steps._commit_transition` | `provenance.worker` |
| `WORKFLOW_STEP_FAILED` | `domain.steps._commit_transition` | `provenance.worker` |
| `WORKFLOW_EFFECT_FAILED` | `domain.outbox` | `provenance.worker` |
| `REVALIDATION_CHECK` | `domain.revalidation._record_checks` | `provenance.worker` |

`REVALIDATION_CHECK` is in the set because a check evaluated by a process arm C's wrapper never
reached is exactly the failure the guard exists for; it is now caught by the executor rule as well
as by the witnesses.

**This is not a string allowlist.** No identity is named as forgiven and `sur1 world facility`
appears nowhere in the harness's executor logic. What changed is *which rows are evidence that a
worker executed a step*. A competing worker that executes one step is caught by the same rule that
lets the world facility through, whichever of the four rows it leaves —
`test_a_second_worker_is_caught_whichever_execution_row_it_leaves` parametrises all four — and
`test_a_second_worker_is_still_caught_among_the_world_facility_s_rows` proves the two coexist.
`test_no_event_the_world_facility_writes_is_watched_as_an_execution` holds the structural property
down so a fourth world write cannot quietly become a competing worker.

**It fails closed twice over.** A ledger that cannot be read is a refusal, as before. A row that
names a step and names no worker is **also** a refusal — `HostedWorkerError` out of the reader,
which `driver.executor_evidence` turns into the same fault an unreadable ledger produces — because
*a step ran* and *nobody can say who ran it* is an unknown, not a pass. A control that has hosted
no worker still has an empty identity, and every execution row is foreign to it.

**What it does not cover, stated rather than implied.** A successful outbox delivery writes no
audit row of its own, so a process that delivered an effect and executed no step is not visible to
this reading. It would have had to claim a step to reach one, and every claim it executed is in
the four rows. What remains uncovered is a worker that delivered a message it never planned.

**The event names are the product's own**, asserted against `promisepatch.domain.model` and
`promisepatch.domain.revalidation` by
`test_the_execution_events_are_the_product_s_own_and_not_a_second_spelling`, and the column each
row fills is read out of the product's source by
`test_every_watched_event_carries_the_executing_worker_in_its_provenance`.

### 2.2 `scripts/sur1/bindings/world.py` — the attempt's own scenario id

`_report_row` records the world's `scenario_id` whatever the arm sent. The field is still
published to arm A, still asked for, and still part of the frozen schema: nothing is taken away
and nothing new is shown. Only the reading moves, from *the model's answer* to *the harness's
bookkeeping*.

### 2.3 `scripts/sur1/bindings/world.py` — the fixture's own bijection

`OrderVocabulary`, built from the fixture the world was constructed with, translates
`promises[].order` through the frozen fixture's two spellings and through nothing else:

- a canonical order of the case universe is returned unchanged;
- an **exact** fixture external id is translated to its order;
- anything else is returned **exactly as the arm wrote it**, and the placement rule in
  `evidence._report` refuses it unchanged. No case folding, no prefix rule, no separator
  tolerance, no similarity. `ORD-A`, `ext-a`, `ord_a` and `EXT-A ` are all left alone —
  `test_an_order_spelled_nearly_right_is_not_repaired_into_one_that_exists`.

A vocabulary that is not a bijection — two orders sharing an external id, or an external id that
is another order's canonical name — is **refused rather than resolved**, because a translator that
picked one would be deciding which order an arm meant. The frozen fixture is neither, and
`test_the_frozen_fixture_is_a_bijection_and_translates_both_ways` asserts that of the frozen
document itself.

`preflight.report_projection` builds its synthetic report in the case universe's own names and
passes no vocabulary, so the check it has always performed is unchanged.

## 3. What was deliberately not changed

- **Arms B and C called the model zero times in the fourth run, and nothing here changes that.**
  It is the product's deterministic lexicon reading *didn't arrive* and *went off* without a
  semantic call, and the frozen contract requires one model *configuration* across the arms, not
  one invocation count. Forcing a call would be authoring arm behaviour to make a number appear.
  It stays a disclosed limitation of any run taken under this revision.
- **No scorer rule.** `_report_is_valid`, the placement rule in `evidence._report`, the safety
  dimensions, the recovery and escalation denominators and `SCORER_VERSION` are untouched. The
  scorer still refuses an order that is not in the case universe, and still calls a report about
  another scenario `INVALID`.
- **No benchmark content.** Not the manifest, the baseline prompt, a world program, a label, the
  ground truth, the budgets or the retry policy.
- **Nothing arm A can read.** The prompt is byte-identical, the eleven actions are the eleven
  actions, the published report schema is derived from the same frozen block, and no benchmark
  information — no scenario id, no order vocabulary hint, no ground truth — is added to anything
  the arm sees.
- **`declaration.NO_ARM_EXECUTED` still says two scored runs have been driven under the
  world-program freeze, and four have.** Correcting that sentence would move the freeze document
  `docs/benchmarks/sur1-world-programs.v1.json`, which is frozen and compared byte-for-byte by
  `world_program_freeze`. It is recorded here as the later truth instead, which is what the
  operating contract requires of frozen evidence. The published run records are the authority on
  how many runs exist.
- **No preflight check was added, removed or weakened.** `REQUIRED_CHECKS` is 28.

## 4. Which arms each correction affects, and in which direction

| Correction | Arms | Direction |
|---|---|---|
| Executor evidence | **arm-blind** — one control, one rule, no parameter or branch by which an arm could reach a different one | From refusing five readable attempts to reading them. On `C06` it applied to all three arms equally, which is why the correction cannot be arm-correlated |
| `scenario_id` | **arm A only** | It can only turn a baseline report that would be `INVALID` into a placeable one. **It flatters arm A**, and is named for that |
| `promises[].order` | **arm A only** | It can only turn a baseline report that could not be placed into one that can. **It flatters arm A**, and is named for that |
| Pinning `v4` | none | A refusal, not a reading |

Both identity corrections move in the baseline's favour. That is the honest direction for a
harness defect that was costing the comparator its attempts, and it is stated before any run is
taken under it rather than explained after one.

## 5. Every frozen identity, recomputed

| Identity | Value | Moved? |
|---|---|---|
| `manifest_sha` | `5718340fbd19aa8ba1aedc2327c07a934e22b773271e996f13f0e8d87e70e84c` | no |
| `baseline_prompt_sha` | `772ba46025620a1aea4742fac3971c5906ec3252036d07725434e0a89ce47cb1` | no |
| `SCORER_VERSION` | `1.0.0` | no |
| `PREDECLARATION_SHA` | unmoved | no |
| `implementation_sha` | `c93b38a71296ba13744a7f0738394feaf3f2ae09ca61a939afa1ca3269e545f7` | no |
| `program_set_sha` and all nine world digests | unmoved | no |
| `DRIVER_VERSION` | `1.4.3` → `1.5.0` | **yes**, and it is the identity that covers driving and evidence collection |

Neither changed file is in `IMPLEMENTATION_MODULES`, which is why `implementation_sha` holds
still: `hostedworker.py` and `world.py` decide how an attempt is driven and read, not what a
program is or what its world looks like.

## 6. The four published runs

| Run | Files | Digest | State |
|---|---|---|---|
| `20260919T2020Z-scored` | 57 | `d599d644c6869fe5…` | inconclusive |
| `20260920T1100Z-scored-corrected` | 57 | `e2a46c35b53902c8…` | incomplete, zero spend |
| `20260920T1215Z-scored-v3` | 57 | `403622ecd45a3472…` | **invalid** |
| `20260921T0910Z-scored-v4` | 57 | `cb7197a4eceed73a…` | comparatively empty |

All four recompute byte-identical at this revision. The fourth is pinned in
`preflight.PUBLISHED_RUNS` and in `scripts/tests/test_sur1_database_target.py` for the first time
— two independent copies, each catching an edit to the other. The session that took it could not
pin it, because pinning edits a scope-frozen file; that is what its own record's §6 says is owed,
and this is the session that owes it.

**The correct response to one of these digests moving is to restore the run, never to update the
pin.**

## 7. What this revision does not do

- **It takes no run and no rehearsal.** No arm was driven, `C01`–`C09` were not executed, `DR01`
  was not driven, no model was called, no scorer was invoked and no capture was written.
- **It spends nothing.** No Bedrock, OpenAI or NVIDIA call was made.
- **It opens no holdout** and reads nothing under `evals/`.
- **It alters no historical capture, verdict or result.** Every published run is exactly as it
  was taken.
- **It touches no AWS resource** and deploys nothing.
- **It edits no file under `apps/` or `packages/`.**
- **It makes no comparative claim.** There is still no `SUR-1` result, and the next run is still
  a run whose outcome is whatever it says.
