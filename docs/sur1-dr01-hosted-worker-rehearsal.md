# `DR01` through the hosted-worker seam: two ordering defects closed, one install defect found

**No `SUR-1` run was taken, no scored authorisation was minted, no `C01`–`C09` world program was
executed, no model was called, no AWS API beyond the credential chain was reached, no scored
capture or verdict was written, no holdout was opened, no published run was altered and no frozen
document was edited.** This record is the operator work
[`sur1-hosted-worker.md`](sur1-hosted-worker.md) §9.2 said was owed before `DR01`, the first real
scored preflight taken against a stack that has it, and the `DR01` attempt that followed.

| | |
|---|---|
| Written at | `e0f6e77`…this commit on `main`, 2026-09-20 |
| `DRIVER_VERSION` | `1.4.0` → **`1.4.1`** |
| `implementation_sha` / `PREDECLARATION_SHA` / `SCORER_VERSION` | **unmoved** |
| Manifest / prompt / scorer / world programs / budgets / retry policy / labels | **unmoved** |
| `REQUIRED_CHECKS` | **28**, unchanged |
| Scored preflight | **28/28 PASS in one report**, zero spend |
| `DR01` | **did not complete.** Failed at the first install; see §4 |
| Runs taken under `1.4.1` | none |

## 1. The stack, rebuilt

`sur1-hosted-worker.md` §9.2 read the local stack live and found it split: `worker` on
`promisepatch-backend:local`, `api` and `mcp` on a pinned image from before `source_digest`
existed, `pp runtime-identity` answering *No such command* inside `api`. That is the state this
session found and it is the state it changed.

The backend image was rebuilt from `HEAD`, `api` and `mcp` were recreated on it, and the compose
`worker` was stopped and left stopped. All three processes and the harness now publish one
computed digest:

```text
source_digest      6e09f012c6b35d1cc1b94e2645e64b4e7756c7b87988d3284662d0c1f09bb00c
migration_revision 0009_human_plan_approval
```

read from `api`, from `mcp`, from `promisepatch.runtime_identity.source_digest()` in the harness
process, and from the hosted worker. A tag is a claim about an image; this is each process's
answer about the bytes it loaded.

## 2. The runtime configuration, and what it is not

Three environment files were changed. They are generated, gitignored and local; nothing under
`apps/` or `packages/` was touched, and no benchmark seam was added to the product.

| File | Change | Why |
|---|---|---|
| `api.env` | `PP_DEMO_SESSION_ENABLED` `true` → `false` | `ensure_demo_case` otherwise opens a case inside every installed world before any arm acts — audit finding **F2**. The `worker` service reads this file too. |
| `api.env`, `mcp.env`, `host.env` | `PP_LLM_PROVIDER=bedrock` | The contract requires the product's semantic boundary to call the same model as the baseline arm. Unset, it resolved the deterministic fake — audit finding **F3**. |
| `mcp.env` | `PP_BAKERY_TZ`, `PP_ORDER_SYSTEM_BASE_URL` | `config_parity` compares both across every process serving a run. The MCP process holds no database and never uses the address; naming it is what lets the comparison be made rather than assumed. |

Model id, Region and temperature are the settings' own defaults and were **not** restated:
`us.amazon.nova-2-lite-v1:0`, `us-east-1`, `0.0`. No secret was read into any output; the
database is reported as `user@host:port/dbname` and a credential only as a boolean.

**The credential chain needed a Region in the environment, and that is not a code fact.** The
`promisepatch` profile assumes a role through a `credential_process`, and that subprocess exits
`NoRegion` unless `AWS_REGION` is set. Without it `product_model_identity` refuses the run —
correctly, and for a reason an operator would otherwise have spent time inside boto3 finding.
**No Bedrock call was made**: the chain is asked whether it resolves, never used.

## 3. Two defects in the corrected seam, found by driving it

Both were found the way `1.1.1`'s defect was — by exercising the thing rather than a stand-in —
and both are fixed here.

### 3.1 The gate asked about a worker nothing had started

`ablation_reach` and `sole_executor` ask their questions of a worker that is **running**:
`evaluates_in_process()` is false until a hosted life has imported the evaluator, and
`worker_identity()` is empty until one exists. Nothing started one. `InstallationLifecycle` first
resumes at the first install, which happens inside `drive` and therefore **after** the gate.

So a fully rebuilt, fully configured scored stack refused itself:

```text
- ablation_reach: the durable worker that decides revalidation is a separate process, and arm C's
  wrapper is installed in this one; arm C would be arm B and the ablation would measure nothing
- sole_executor: no hosted worker is running, so there is no identity for this run's governed
  writes to carry and nothing to compare a foreign one against
```

Both sentences are true about the ordering and false about the stack, which is the worst shape a
gate can fail in: it is indistinguishable from the defect it exists to catch. **No scored run
could have been authorised under `1.4.0` on any stack.**

Nothing was weakened to pass it. `execute` now hosts the worker the run will use *before* the
gate asks, and releases it when the run is refused or when the invocation was only a preflight —
so `--preflight` still puts back exactly what it found. A `resume` that refuses is deliberately
not raised past the gate: refusing while the containerised worker could compete is precisely what
`sole_executor` reports in its own words, and a traceback would tell the operator less.

**One test's expectation changed, and it was the defect written down.** `test_sur1_run.py` listed
`ablation_reach` as an unconditional preflight failure, on the reasoning that *no worker is hosted
in a preflight that drives nothing*. That was an accurate description of the code and of the bug.
It now sits with the other six checks whose answers depend on this machine's stack — where it
still fails on a machine with no stack at all. The assertion around it is unchanged.

### 3.2 `DR01` controlled no worker at all

`RehearsalWorld` never passed a `worker`, so it took `LiveScenarioWorld`'s default —
`UncontrolledWorker`. Every consequence of `ADR-0020` was therefore absent from the rehearsal:
arm C's wrapper rebound the evaluator in the harness while a container decided revalidation;
`driver.executor_evidence` returned nothing, because that control has neither
`executed_only_by_the_hosted_worker` nor `revalidation_witnesses`; and `await_quiescence`
answered *this worker control cannot be asked*. A rehearsal of the corrected seam would have
rehearsed the topology the correction replaced.

`DR01` is now wired to the same `HostedWorkerControl` a run gets, and quiesces it before the
restore — `reset-demo-state` empties forty-two tables and takes an exclusive lock on each, which
is the deadlock the installation lifecycle exists to remove.

## 4. The scored preflight: 28/28, and then `DR01` did not complete

**The preflight passed every required check in one report**, `kind: scored`, against real local
bindings and a real credential, with no inference and no authorisation minted. The checks this
session existed to move:

```text
build_identity   the harness, the hosted worker and api, mcp all run source 6e09f012c6b3
                 at migration 0009_human_plan_approval
config_parity    the hosted worker and api, mcp share one configuration, one database
                 (promisepatch_app@127.0.0.1:55432/promisepatch) and one order system
                 (http://127.0.0.1:48100)
sole_executor    the containerised worker is stopped and the hosted worker
                 DESKTOP-OKFJLHE:13772:c4a38cc4 is the only process that can execute this
                 run's durable work
ablation_reach   the process that decides revalidation is the one arm C's wrapper is
                 installed in, and the product's own audit rows can be read back
product_model_identity  the worker calls us.amazon.nova-2-lite-v1:0 at temperature 0.0 in
                 us-east-1, and a credential resolves there
demo_provisioning       the worker opens no demo case inside an installed world
historical_runs  3 published scored runs are byte-identical to what was taken
```

`DR01` was then driven and **failed at the first install**, before any arm was driven. No attempt
was captured, no verdict written and no run directory created.

### The defect, exactly

`InstallationLifecycle.fingerprint` reads

```sql
SELECT id, state FROM commitment_lines ORDER BY id
```

and `commitment_lines` has no `state` column. Its columns are `id, commitment_id, resource_id,
quantity, received_state, received_qty, settled_at, attested_by`. The intended column is
**`received_state`** — the neighbouring `production_tasks` query is correct, which is how the
mistake reads as a transposition rather than a misunderstanding.

```text
ReceiverUnreadableError: WORLD: UndefinedColumnError: column "state" does not exist
  scripts/sur1/bindings/lifecycle.py:433  in fingerprint
  scripts/sur1/bindings/lifecycle.py:403  in around
```

**It is fatal to every scored attempt.** `around` fingerprints on *every* install, for every arm
and every scenario, and the failure comes after the world has been installed and verified. A
scored run under `1.3.0` or `1.4.0` would have died at its first install, 27 times over.

**Nothing caught it, for one reason, and it is a reason worth stating.**
`preflight.world_integrity` proves the lifecycle by driving it — against dictionaries. Its own
docstring says so: *in-process and read-only: the stand-ins are dictionaries, no database is
opened*. `test_sur1_world_lifecycle.py` uses a stand-in database for the same reason. So the check
that exists to prove the world is re-read after the worker returns has never executed this
statement, and the live check in `sur1-hosted-worker.md` §9.1 started a worker without installing
a world. This is the third defect in this seam that only a live drive could find, after the
`sys.modules` lookup and the `58100` address.

**It is recorded and not fixed here.** The session that drove the rehearsal does not also patch
what the rehearsal found and re-drive it; that is how a rehearsal stops being a reading.

## 5. What `DR01` therefore does not say

Every item below was in scope for this rehearsal and **none of them was reached**. They stay owed.

- Nothing about `BASELINE`, `PROMISEPATCH` or `ABLATION`: no arm was driven.
- **No B/C treatment evidence.** Whether arm B's check 5 row carries the evaluator's own name and
  arm C's carries the ablation mark, and whether checks 1–4 and 6–10 are identical between them,
  is exactly as unproven as it was before this session.
- **No sole-executor proof from a driven attempt.** The preflight's `sole_executor` is a
  precondition; `driver.executor_evidence` reads the ledger after an attempt, and no attempt ran.
- No customer ask or reply, no governed effect, no `E1`/`E2`/`E3`/`E4` capture, no blind
  projection, no rehearsal scoring and no join.
- Nothing about receiver timing, because the quiescent settle was never exercised live.

## 6. Cleanup

The install had landed `DR01`'s world in both systems before the fingerprint failed, and the
rehearsal raised before its own restore. Both systems were put back through the rehearsal's own
`restore` and read back through its own `restored`:

```text
reset_demo_state   returncode 0, fixture hollow-oak, digest 321f378c…, rows 160
order_system_reset reset: true, orders: 6
restored           true
  no_settled_commitment_line, strawberries_back_to_fixture (2.000),
  no_harness_ledger_postings, no_cases, no_inbound_replies,
  every_order_at_version_one, every_line_back_to_its_pinned_version
```

`no_cases` is the honest post-reset state and not a fault: the canonical demo case is provisioned
at worker start-up, the compose `worker` is stopped, and `PP_DEMO_SESSION_ENABLED` is now false.
`pp ensure-demo-case` brings it back when a demo is wanted.

**The stack is left as this session configured it**: `api` and `mcp` recreated on the `HEAD`
image, the compose `worker` stopped, demo provisioning off, the provider Bedrock.

## 7. What is owed next

1. **Fix `fingerprint`'s column**, and give `world_integrity` or the lifecycle tests a reading
   that would have caught it — a stand-in that cannot fail on a real column name is the gap, not
   the typo.
2. **Drive `DR01` again**, in a later session, and get from it what §5 says this one did not.
3. Only then is a fourth scored run a question. It is not this session's and it is not the next
   one's either.

## 8. What was validated

Stated as what was run, not as what is believed.

- `pytest scripts/tests` — **1236 passed, 1 skipped**; the skip is the state-dependent challenger
  guard and predates this work. Two expectations in `test_sur1_run.py` changed, for the reason
  §3.1 gives; no test was skipped, deselected, deleted or weakened.
- `ruff check .`, `ruff format --check .` (555 files), `lint-imports` (**30 contracts kept, 0
  broken**), `mypy evals scripts` (145 files).
- The scored preflight itself, live: **28/28**, every name in `REQUIRED_CHECKS` present and
  passing in one report, including `historical_runs` — the three published scored runs recompute
  byte-identical to what was taken. Both evaluation holdouts are untouched; nothing under `evals/`
  was read, run or changed.

**GitHub CI is the broad regression authority and has not run on this work**, which has not been
pushed.

## 9. The re-freeze

`sur1-phase3-closeout.md` §8 requirement 4 holds: the session that changed the machinery does not
take the run, and no run was taken. The scope-freeze trees are re-recorded at this commit in
`sur1-phase3-closeout.md` §8, beside the previous ones rather than into them.
