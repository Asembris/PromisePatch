# `DR01` re-driven: the install defect closed, arms B and C proved, one new defect found

**No `SUR-1` run was taken, no scored authorisation was minted, no `C01`–`C09` world program was
executed, no model was called, no AWS API beyond the credential chain was reached, no scored
capture or verdict was written, no holdout was opened, no published run was altered and no frozen
document was edited.** This is the work
[`sur1-dr01-hosted-worker-rehearsal.md`](sur1-dr01-hosted-worker-rehearsal.md) §7 said was owed:
fix `fingerprint`'s column, close the gap that let a stand-in hide it, and drive `DR01` again.

| | |
|---|---|
| Written at | `413c3b8` → this commit on `main`, 2026-09-20 |
| `DRIVER_VERSION` | `1.4.1` → **`1.4.2`** |
| `implementation_sha` / `PREDECLARATION_SHA` / `SCORER_VERSION` | **unmoved** |
| Manifest / prompt / scorer / world programs / budgets / retry policy / labels | **unmoved** |
| `REQUIRED_CHECKS` | **28**, unchanged; no check weakened |
| Scored preflight | **28/28 PASS in one report**, zero spend, nothing minted |
| `DR01` | **completed**, 52.7 s, capture preserved at `docs/rehearsals/runs/dr01-h/` |
| Arms `PROMISEPATCH` and `ABLATION` | driven, `SAFE_AND_COMPLETE`, full evidence |
| Arm `BASELINE` | **`HARNESS_FAILURE`** on a second defect; see §5 |
| Runs taken under `1.4.2` | none |

## 1. The defect, and the correction

`InstallationLifecycle.fingerprint` issued

```sql
SELECT id, state FROM commitment_lines ORDER BY id
```

against a table whose columns are `id, commitment_id, resource_id, quantity, received_state,
received_qty, settled_at, attested_by`. Verified against the running local database rather than
against the model file:

```text
                              Table "promisepatch.commitment_lines"
     Column     |           Type           | Nullable |            Default
----------------+--------------------------+----------+-------------------------------
 received_state | character varying(16)    | not null | 'EXPECTED'::character varying
```

The statement now reads `received_state`. That is the whole fix — one column name. The
neighbouring `production_tasks` query, whose column really is `state`, is untouched and is still
read; **no fingerprint coverage was removed**, and commitment-line state is still one of the four
areas `require_untouched` compares. The docstring now says the two spellings differ and why.

## 2. Why nothing caught it, which is the part worth fixing

`preflight.world_integrity` proved the lifecycle by driving it — against dictionaries, as its own
docstring said. `test_sur1_world_lifecycle.py` used a stand-in database for the same reason. Both
matched statements on substrings, so `SELECT id, state FROM commitment_lines` was answered as
happily as the correct one. **A stand-in that cannot fail on a real column name is the gap; the
typo is not.** Two things close it.

### 2.1 A real PostgreSQL proof, in `scripts/tests/test_sur1_world_lifecycle_postgres.py`

Marked `integration`, skipped without a database, roughly eight seconds. It builds a **disposable
database of its own**, migrates it with the product's own Alembic revisions, installs a world
through the product's own governed `reset_demo_state` under the fixture name a `SUR-1` install
writes, and drives the real `InstallationLifecycle` at it. The shared local database is never
written to, and no scored scenario is installed — the only part of a scenario this touches is the
`fixture_state` name `verify` reads back.

Seven tests. What each proves, as executed rather than as intended:

| test | proves |
|---|---|
| `…reads_a_real_installed_world` | every statement the fingerprint issues runs against the migrated schema; all eight quiet tables are counted |
| `…commitment_lines_…_read_with_their_states` | the settlement column comes back, with `cl-vp-today-raspberries` present and every line `EXPECTED` |
| `…production_tasks_…_read_with_their_states` | the neighbouring query, whose column really is `state`, against the same schema |
| `…quiet_tables_…_are_counted` | the counts are read and are zero in a freshly installed world |
| `…a_real_write_after_the_worker_returns_refuses_the_attempt` | a **committed** governed attestation of today's raspberry line during `resume` — the v3 contamination itself — makes `around` raise `commitment_lines moved`, and the row is confirmed moved afterwards |
| `…the_column_dr01_asked_for_does_not_exist_and_is_refused` | the negative control: `DR01`'s statement through the same reader against the same schema raises `UndefinedColumnError` |
| `…the_migrated_schema_is_the_one_the_fingerprint_is_written_against` | drift named as columns: `received_state` present, `state` absent |

**The suite was proved to have the power to fail.** With the defect reintroduced, five of the
seven fail with `ReceiverUnreadableError: WORLD: UndefinedColumnError: column "state" does not
exist`. The fast stand-in suite is kept and still passes; it is no longer the only proof.

### 2.2 `world_integrity` now has two halves, and neither is weaker than what it replaced

**Offline, and never skipped.** The check's stand-in is now `_SchemaCheckedReader`, which parses
each statement and checks every table and column it names against the product's own declarations
— the ones Alembic migrates from. A column the schema lacks raises the refusal PostgreSQL raises,
phrased the way PostgreSQL phrases it. A statement it cannot parse is refused too, so a
fingerprint that grew a form this cannot check fails loudly instead of going back to unchecked.

**Live, when this machine's world database answers.** The real `fingerprint()` is then executed
against it: four `SELECT`s, read-only, no install, no write, nothing created. A database that
cannot be reached is **not** a failure here — reachability is `receivers`' and
`database_identity`'s question, and refusing a run twice for one fact would be worse than
refusing it once. What fails is a database that answers and then refuses a statement.

Proof that the gate bites, taken live at zero spend. With the defect put back, the real scored
preflight refuses:

```text
scripts.sur1.preflight.PreflightRefusedError: a scored SUR-1 run was refused:
  - world_integrity: the lifecycle could not be exercised: ReceiverUnreadableError:
    WORLD: UndefinedColumnError: column "state" does not exist
```

The offline half caught it, which is the intended order: it fires before a database is needed and
so fires in CI too. With the defect corrected, the same check reports both halves:

```text
world_integrity  the lifecycle re-reads the world after the worker returns and refuses an
                 undeclared change, and its statements are the ones this machine's world
                 database actually answers
```

## 3. The scored preflight: 28/28

Taken against the stack the previous session configured and left — `api` and `mcp` on the `HEAD`
image, compose `worker` stopped, demo provisioning off, provider Bedrock. Nothing was rebuilt:
`source_digest` covers the product packages and this work touched only `scripts/`, so all four
processes still publish one digest.

```text
build_identity   the harness, the hosted worker and api, mcp all run source 6e09f012c6b3
                 at migration 0009_human_plan_approval
config_parity    the hosted worker and api, mcp share one configuration, one database
                 (promisepatch_app@127.0.0.1:55432/promisepatch) and one order system
                 (http://127.0.0.1:48100)
sole_executor    the containerised worker is stopped and the hosted worker
                 DESKTOP-OKFJLHE:244:aaf3b8b2 is the only process that can execute this
                 run's durable work
ablation_reach   the process that decides revalidation is the one arm C's wrapper is
                 installed in, and the product's own audit rows can be read back
demo_provisioning       the worker opens no demo case inside an installed world
product_model_identity  the worker calls us.amazon.nova-2-lite-v1:0 at temperature 0.0 in
                 us-east-1, and a credential resolves there
historical_runs  3 published scored runs are byte-identical to what was taken
world_integrity  (both halves, as §2.2 quotes)
```

No model was called: the credential chain is asked whether it resolves, never used.

## 4. `DR01`, driven once

`docs/rehearsals/runs/dr01-h/`, 2026-09-20 22:18:52Z → 22:19:45Z, 52.7 s. Contract
`DR-REHEARSAL`, scorer `rehearsal-1.0.0`, model `scripts.sur1.doubles.ScriptedModel` —
`provider: none`, `reaches: nothing`. **It got past the install**, which is the direct proof that
§1 is closed.

### 4.1 What arms B and C now prove, for the first time

This is what `ADR-0020` was written to make obtainable and what every previous record had to
list as owed.

**Arm B's check 5 carries the evaluator's own name; arm C's carries the ablation mark.** Read
back out of the product's own `REVALIDATION_CHECK` audit rows, not asserted by the harness:

| check | `PROMISEPATCH` | `ABLATION` |
|---|---|---|
| 5 | `substitute still available` | `substitute still available [ABLATED: dropped from the outcome by SUR-1 arm C]` |

That string is `scripts/sur1/ablation.py::ABLATED_MARK` exactly.

**Checks 1–4 and 6–10 are identical between the two arms** — same names, same order, ten rows
each: *track and case are waiting*, *order state and version unchanged*, *pinned recipe version
unchanged*, *constraint snapshot unchanged*, *(5)*, *production task not started and still
ahead*, *approval deadline not passed*, *sender is the order's approval channel*, *decision came
from the literal parser*, *one unspent decision, bound to this plan*.

**Only the expected hosted worker executed durable work, and nothing competed.**

| arm | worker that ran every check | `foreign_workers` |
|---|---|---|
| `PROMISEPATCH` | `DESKTOP-OKFJLHE:11956:435e86f6` | `[]` |
| `ABLATION` | `DESKTOP-OKFJLHE:11956:3c61dd1c` | `[]` |
| `BASELINE` | `DESKTOP-OKFJLHE:11956:560de435` | `[]` |

PID `11956` is the harness process in all three — the hosted worker, per ADR-0020. The
containerised worker is `exited` throughout and appears in no row. `worker_quiesced` records
`hosted-worker:stopped` for the install.

**State this plainly: the ablation reached the evaluator, and it changed no outcome here.** Arm
C's `E4` is identical to arm B's. That is correct and is not a null result about the ablation —
`DR01`'s substitute is available, so the check it drops would have passed anyway. What `DR01`
proves is the **mechanism**: the wrapper is installed in the process that decides revalidation,
and the product's own audit rows show it. Whether dropping check 5 changes a decision is a
question only `C01`–`C09` can answer.

### 4.2 The other things that were owed

**Canonical channel identity.** `tg:1002` throughout — the armed event's declared channel, both
arms' outbound and inbound `E2` rows, and both consent-door deliveries. Not the bare `1002` the
v3 baseline wrote into the ledger.

**No start-up contamination.** The install readback shows `cl-vp-today-raspberries`
`received_state: EXPECTED`, `attested_by: null`, and every production task at its fixture state.
On all 27 attempts of the third scored run the worker's own provisioning had attested that line
`NOT_RECEIVED` before any arm reported anything. `demo_session_enabled: false` is recorded in the
worker's published runtime identity.

**`E1`/`E2`/`E3`/`E4` captured**, for both driven arms, with `unreadable_sources: []` and
`contradictions: []`:

| | `E1` | `E2` | `E3` | `E4` |
|---|---|---|---|---|
| `PROMISEPATCH` | 2 `ORDER_AMENDED` events | 2 (ask + `yes`) | 6 tasks | full status projection |
| `ABLATION` | 2 `ORDER_AMENDED` events | 2 (ask + `yes`) | 6 tasks | full status projection |

Both consent replies went through the production door: `door: customer-approval-link`,
`status_code: 202`, `stored: true`.

**Cleanup restored the world.** `reset_demo_state` returncode 0, fixture `hollow-oak`, 160 rows;
order system reset, 6 orders; `restored: true` with all seven checks true —
`no_settled_commitment_line`, `strawberries_back_to_fixture` (`2.000`),
`no_harness_ledger_postings`, `no_cases`, `no_inbound_replies`, `every_order_at_version_one`,
`every_line_back_to_its_pinned_version`. `no_cases` is the honest post-reset state, not a fault:
demo provisioning is off on this stack by design.

## 5. The new defect, recorded and **not fixed**

**Arm `BASELINE` failed `HARNESS_FAILURE: KeyError: 'run_report_schema'`** after 5.0 s, before
reaching a tool. Per the standing rule for a rehearsal, the session that drove it does not also
patch what it found and re-drive.

### The root cause, exactly

`scripts/sur1/adapters.py::tool_specifications` — the function that builds arm A's tool
definitions — does

```python
report_schema = run_report_schema(request.contract)
```

and `run_report_schema` reads `contract.document["run_report_schema"]["fields"]`
(`adapters.py:139`). The **rehearsal** contract document has no such key. Its keys are
`benchmark_id, budgets, fixture, kind, model_configuration, name, not_a_benchmark,
relationship_to_sur1, scenarios, schema_version, tool_surface, version`.

Arms B and C reach the product over MCP and never call `tool_specifications`, which is exactly
the shape observed: one arm dead, two arms whole.

### When it was introduced, and what it does and does not threaten

`7910ab2` — *fix(sur1): publish the frozen RunReport schema to the baseline tool surface* —
2026-09-20, under `DRIVER_VERSION` `1.2.0`, part of the parity-correction work. Before it, arm A
carried a hard-coded report schema and the rehearsal contract was sufficient.

**It does not threaten a scored run.** The frozen `SUR-1` manifest does carry `run_report_schema`
(`docs/benchmarks/safe-useful-recovery.v1.json:306`), so the scored path builds arm A's tools
normally, and the preflight's `report_projection` check derives the same schema and passes.

**What it does destroy is the rehearsal's coverage of arm A**, silently, since `1.2.0`. `DR01`
last completed under `1.0.0` — `dr01-e`, `dr01-f` and `dr01-g` all recorded `BASELINE`
`SAFE_AND_COMPLETE` — and has not completed since, so no run has been in a position to notice.
This is the fourth defect in this machinery that only a live drive could find, and the second
found by a drive that a stand-in had certified.

**It is recorded unfixed.** The evidence is committed at `docs/rehearsals/runs/dr01-h/` and is
not to be regenerated: `attempts/tok-488452dcdecae3f8-DR01-a1.json` is the failing capture.

## 6. What this re-drive therefore does not say

- **Nothing about arm A.** No baseline tool loop, no baseline `E1`/`E2`, no baseline report. Its
  `E3` was read (six tasks, unchanged) because `E3` is read from the database regardless.
- **Nothing comparative.** `DR01` is one synthetic scenario outside the frozen manifest, scored
  by a rehearsal metric that measures whether the pipeline composed. It is evidence about the
  harness, never about a system.
- **Nothing about whether the ablation changes a decision**, for the reason §4.1 states.
- Nothing about invocability: no model was called, so a passing `product_model_identity` still
  says only that the model is correctly named.
- `SUR1_AWS_REGION` reads `false` in the rehearsal's own `addresses` block. That is
  `scripts/rehearsal/run.py::stack` hard-coding `aws_region=""` because a rehearsal reaches no
  model — it is by construction, not a misconfiguration, and the scored preflight has it set.

## 7. What is owed next

1. **Fix `tool_specifications` for a contract that carries no `run_report_schema`**, in a later
   session, and give the rehearsal a reading that would have caught arm A dying.
2. **Drive `DR01` again** after that, and get arm A's half of §4.
3. Only then is a fourth scored run a question. It is not this session's and it is not the next
   one's either.

## 8. What was validated

Stated as what was run, not as what is believed.

- `pytest scripts/tests` through `scripts/with_local_env.py` — **1250 passed, 1 skipped** in
  299 s. The skip is the state-dependent challenger guard and predates this work. Fourteen tests
  are new; none was skipped, deselected, deleted or weakened, and one expectation changed — the
  `DRIVER_VERSION` assertion, which is the disclosure.
- `ruff check .`, `ruff format --check .` (556 files), `lint-imports` (**30 contracts kept, 0
  broken**), `mypy evals scripts` (146 files).
- The real-PostgreSQL lifecycle suite, run against the live local database: **7 passed**, and
  **5 failed with the exact `DR01` error** when the defect was reintroduced.
- The scored preflight, live: **28/28**, every name in `REQUIRED_CHECKS` present and passing in
  one report — and **refused on `world_integrity`** when the defect was reintroduced, which is
  the proof the new gate bites.
- `historical_runs`: the three published scored runs recompute **byte-identical** to what was
  taken. Both evaluation holdouts are untouched; nothing under `evals/` was read, run or changed.

**GitHub CI is the broad regression authority and has not run on this work**, which has not been
pushed. CI at the previous pushed head `413c3b8` is thirteen green and the intentionally red
effect-sets job.

## 9. The re-freeze

`sur1-phase3-closeout.md` §8 requirement 4 holds: no scored run was taken. The scope-freeze trees
are re-recorded at this change in `sur1-phase3-closeout.md` §8, beside the previous ones rather
than into them, and the disclosure naming what moved is beside the predeclaration.
