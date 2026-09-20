# The `SUR-1` hosted worker: arm C reaches an evaluator for the first time

**No `SUR-1` run was taken, no `DR01` rehearsal was driven, no model was called, no scorer was
run, no AWS API was reached, no capture or verdict was written, no holdout was opened, no
published run was altered and no frozen document was edited.** This record is the
implementation of the one item [`sur1-parity-correction.md`](sur1-parity-correction.md) §4 left
open and refused, under the decision [ADR-0020](adr/0020-a-scored-benchmark-hosts-the-product-s-own-worker.md)
takes.

| | |
|---|---|
| Written at | `b889ab3`…this commit on `main`, 2026-09-20 |
| Closes | audit finding **F4** (`sur1-v3-forensic-audit.md` §5), correction item **2** (§7) |
| Authorised by | `ADR-0020` |
| `DRIVER_VERSION` | `1.3.0` → **`1.4.0`** |
| `implementation_sha` | **unmoved.** No file in `IMPLEMENTATION_MODULES` was touched |
| `PREDECLARATION_SHA` / `SCORER_VERSION` | **unmoved** |
| Manifest / prompt / scorer / world programs / budgets / retry policy / labels | **unmoved** |
| `REQUIRED_CHECKS` | 25 → **28** |
| Runs taken under `1.4.0` | none |

## 1. The defect, restated exactly

Arm C is *PromisePatch with revalidation check 5 dropped from the outcome derivation and nothing
else*, removed by *wrapping the evaluator at the benchmark boundary*. `scripts/sur1/ablation.py`
does precisely that: it rebinds `promisepatch.domain.revalidation.revalidate` for the length of
one attempt and restores it afterwards.

The rebinding happens in the harness process. The evaluator that decides ran in the `worker`
container. **The wrapper was never called.** `diagnostics.ablation` is `[]` on all nine ablation
captures of `20260920T1215Z-scored-v3` and all eight of `20260919T2020Z-scored`. Arm C was arm B
by construction on every topology this benchmark has ever run on, which is unmeasurable rather
than unmeasured.

`preflight.ablation_reach` has refused every such topology since the parity correction, so no
fourth run could be bought. What was missing was not a patch; it was a decision about what may
be changed. That is `ADR-0020`.

## 2. What was built

### 2.1 The hosted worker

`scripts/sur1/bindings/hostedworker.HostedWorkerControl` runs **the product's own durable
worker** inside the harness process: `promisepatch.worker.built(get_settings())` entered as the
async context manager it is, and `Worker.run_forever(stop, when_idle=…)` driven on a private
event loop in a background thread. There is no branch, no benchmark mode and no second
implementation of a worker; the two lines that matter are asserted by a test rather than
reviewed.

It satisfies the existing `WorkerControl` protocol, so the installation lifecycle, the preflight
and the run manifest reach it through the seam `ComposeWorkerControl` used. Nothing above it
learns the topology changed. What changes is the answer to `evaluates_in_process()`.

- **`quiesce()`** sets the stop event on the worker's own loop and joins the thread. Leaving
  `built()` is the point rather than a tidy-up: it awaits every deferred semantic preparation,
  closes the order-system client and disposes the database engine, so no pool is left holding
  connections in the way of the fixture load's `TRUNCATE`.
- **`resume()`** refuses while a container worker could compete, then starts a fresh life and
  waits for it to report started. Fresh rather than resumed, because a worker is stateless by
  design and a new identity per life is the product's own behaviour on every restart.
- **The deployment's `_DemoCaseKeeper` is not wired**, and cannot be: it lives in
  `promisepatch.worker.run`, not in the worker. A test asserts the hosted module imports nothing
  named `provisioning`. That is finding F2 closed a second way, structurally, beside the
  preflight check that already refuses a stack configured for it.

### 2.2 Both arms, or neither

Arms B and C hold **one** `PromisePatchArm`, which holds one surface and one world, which holds
one worker control. There is no parameter, flag or branch by which the two arms could reach
different workers. That is what keeps the topology change arm-blind between them, which is the
property the ablation comparison depends on and the property the v3 defects destroyed.

### 2.3 The wrapper is held until the work is quiescent

`AblationArm` wraps `PromisePatchArm.drive_through_surface`, and that method now ends by asking
the world to let the durable work finish before the receivers are read. So the wrapper spans the
wait. Without it, an arm whose surface loop returned while the worker was still executing steps
would take the wrapper out mid-attempt and ablate a *prefix* of the work, with nothing in the
capture to say which part.

Quiescence is a read, not a sleep. The loop's own `when_idle` hook — the production hook the
deployment uses for its demo keeper — marks a cycle that found nothing to do, and a mark is only
taken when no semantic preparation is outstanding beside the loop. `await_quiescence` waits for
two fresh marks. It never raises: an attempt whose work did not settle is a reading about that
attempt, and the sentence it returns is written into both arms' diagnostics identically.

**Arms B and C gain the wait together. Arm A is unaffected** — it drives the world directly and
has no durable case work of its own.

## 3. How the treatment is proved

Not by the harness's own log. The product writes one governed `REVALIDATION_CHECK` audit row per
check, inside the transaction that decides, carrying the check's index, its name and the worker
identity that produced it (`promisepatch.domain.revalidation._record_checks`).

| Arm | What its own audit rows say about check 5 |
|---|---|
| `PROMISEPATCH` | the evaluator's own name, `substitute still available` |
| `ABLATION` | `substitute still available [ABLATED: dropped from the outcome by SUR-1 arm C]` |

Checks 1–4 and 6–10 are byte-identical between the two. `HostedWorkerControl.revalidation_witnesses`
reads them back and `scripts/tests/test_sur1_hosted_worker.py` proves the two arms' rows differ
at exactly one index. The ablation mark is imported from `ablation.py` rather than restated, so
a proof cannot pass while the wrapper writes something else.

## 4. Sole executor

A second durable worker would claim benchmark steps and execute them **without** the wrapper.
Arm C would then be part arm B, in a proportion no artefact could recover. Three defences:

1. **Before the run.** `preflight.sole_executor` requires the compose `worker` to be stopped or
   absent, refuses a control that cannot say, refuses a state that is neither, and requires a
   hosted worker to be up with an identity that governed writes will carry.
2. **Before every resume.** `HostedWorkerControl.require_no_competing_worker()` re-asks compose,
   so a container worker restarted mid-run is caught at the next attempt's resume rather than at
   the end.
3. **After every attempt.** `driver.executor_evidence` reads `audit_events` for every `SYSTEM`
   actor since the attempt started. Any identity that is not the hosted worker's **fails the
   attempt closed** as `HARNESS_FAILURE`, and an audit ledger that could not be read fails it
   closed too — *nobody else did the work* and *nobody could tell* are different facts and only
   one of them is a reading.

## 5. Build and configuration parity

Two defects the artefacts proved, and one the local stack still had.

**`backend_build` cannot see a stale image.** It compares migration revisions and says so in its
own docstring: an image stale only in code that no migration accompanied reports the same
revision and passes. The first scored run was driven against exactly that, and the local
containers have no bind mounts — they serve the image, never the working tree.

So the product now computes a **`source_digest`** over the bytes of `promisepatch`,
`promise_graph` and `order_contract` as the process actually imported them, and publishes it on
`pp runtime-identity` beside the migration revision. `preflight.build_identity` requires the
harness, the hosted worker, `api` and `mcp` to publish one digest. A tag is a claim somebody
made about an image; a digest over the loaded bytes is a fact the process computes about itself.

**`config_parity`** compares the behaviour-relevant configuration across the same processes, and
compares it in two different ways because two kinds of value are involved.

| Covered | Compared by | Refuses |
|---|---|---|
| provider, model id, API, Region, temperature | equality | a split stack, one process on the frozen model and another on the fake |
| bakery timezone | equality | two notions of *today* in one run |
| demo provisioning, explanation verbalisation | equality | a scored stack configured for a demo |
| database | target | the hosted worker writing where the receivers do not read |
| order system | target | the address below |
| customer/consent origin | equality via `customer_link_base_url` | a consent link the product would mint at an address nothing serves |

Addresses are compared by **target**, not by string: a container reaches the order system at
`order-simulator:8100` and a host process reaches it on the published port. Both are correct and
they are different strings. So the hosted worker must name exactly the systems the harness's own
receivers read, and each container must name the service whose published port — read from
`docker compose port`, not from a convention — is the one the harness named.

### 5.1 `58100` versus `48100`

`docker/env/host.env` says `PP_ORDER_SYSTEM_BASE_URL=http://127.0.0.1:58100`. This machine's
`.env` sets `PROMISEPATCH_ORDER_SIMULATOR_PUBLISHED_PORT=48100`, so compose publishes the order
simulator on **48100** and has done for every run taken here. Nothing followed the move:
`bootstrap_local_env.published_port` resolved PostgreSQL's port only, and `with_local_env`
repointed connection strings only.

A hosted worker configured from that file would push **every governed amendment into a closed
socket**, while the receivers read an order system nothing had written to. Neither the amendment
nor its absence would appear anywhere except as an arm that achieved nothing — which is
indistinguishable from an arm that chose to do nothing.

Closed in two independent places, which is the shape the parity correction used for the same
reason:

- `with_local_env.repoint` now moves the loopback order-system URL onto the published port, by
  the same rule and the same precedence compose itself resolves it with. Loopback only: an
  address naming another host is left exactly as it was.
- `preflight.config_parity` refuses the run when the hosted worker's order system is not the one
  `E1` is read from, and refuses when compose publishes the simulator anywhere other than the
  port the harness named.

## 6. Model identity, of the process that does the work

`product_model_identity` already compared a published provider identity with the frozen block.
What it could not do was be sure it was asking the right process: it asked the `worker`
container, which a scored run now stops. The hosted control answers it from
`promisepatch.runtime_identity.runtime_identity` — **the product's own module, given the settings
this hosted worker was built from**, in the process that would make the call. No copy, no
description the harness maintains, and no inference: whether a credential resolves is asked of
the AWS credential chain, as a boolean, and no Bedrock call is made.

## 7. The preflight, 25 → 28

| # | Check | Refuses |
|---|---|---|
| 26 | `build_identity` | a stack whose processes are not all running the revision being measured |
| 27 | `config_parity` | a split configuration, or a database or order system the work and the evidence do not share |
| 28 | `sole_executor` | a second worker that could execute benchmark work without arm C's wrapper |

`ablation_reach` (25) is unchanged in name and strengthened in substance: reaching the evaluator
is necessary and is not sufficient, so it also requires the control to be able to read the
product's own record of which checks ran, and requires a hosted worker to be running now.

Every new check has a negative control in `scripts/tests/test_sur1_preflight.py` that proves it
bites, including one that shows `backend_build` **passes** on the stale image `build_identity`
refuses.

## 8. What is measured differently

Reproduced from `ADR-0020` because a disclosure that lives only in a decision record is not a
disclosure.

- **Arm C.** Its ablation reaches the evaluator for the first time — from no reading to a
  reading. Every prior arm C number is arm B's, and the three published runs stay as they are.
- **Arms B and C.** Driven at a worker in this process rather than in a container: same code,
  same wiring, same database, same surfaces, different process. And their receivers are read
  after the durable work settles, so **both may show effects that previously had not yet
  landed**. That can only increase what either arm is credited with and it applies to both
  equally, which is the only property the B-versus-C comparison depends on.
- **Arm A.** Nothing.
- **All three.** A split-revision or split-configuration stack is now refused rather than
  measured.

## 9. What was validated

Stated as what was run, not as what is believed.

- `pytest scripts/tests` — **1237 collected, all passing**, one state-dependent challenger guard
  skipped (unrelated, and skipped before this work). 41 of those are new: 31 in
  `test_sur1_hosted_worker.py` and 10 negative controls in `test_sur1_preflight.py`.
- `pytest apps/backend/tests/test_cli.py` — 57 passed, the `pp runtime-identity` surface.
- `ruff check .`, `ruff format --check .` (554 files), `lint-imports` (30 contracts kept, 0
  broken), `mypy packages/promise-graph packages/order-contract apps/backend` (281 files),
  `mypy evals scripts` (145 files).
- The frozen identities, inside the suite: `assert_frozen()`, `identity_sha()`,
  `declaration.differences()`, the nine world digests and all three published run digests.

### 9.1 The hosted worker was started once, live, and it found a defect

No unit test starts a worker, so the central mechanism of this change had no test that could
exercise it. It was therefore run once against the live local stack, with the compose `worker`
stopped and restarted afterwards: **no scenario, no world install, no arm, no model, no scorer
and no artefact.** What it printed:

```text
competing worker : stopped
resume           : hosted-worker:running
worker identity  : DESKTOP-OKFJLHE:36172:d1750bb8
reach after      : True
quiescence       : quiescent after 2 idle cycles
foreign workers  : ()
quiesce          : hosted-worker:stopped
```

The first run of it printed `reach after : False` **with a worker running in this process**.
`_run` read the evaluator module out of `sys.modules` before the worker was built, and the
worker reaches the evaluator lazily through a handler, so at that instant nothing had imported
it and the control could not say the wrapper reached the deciding name. The module is now
imported rather than looked up. Had this not been run, `ablation_reach` would have refused every
correctly configured scored run and the refusal would have looked exactly like the defect it
exists to catch.

The same run confirmed three parity facts from the process that would do the work:
`order_system_base_url` resolved to `http://127.0.0.1:48100` — the published port, not the
`58100` the host file names — `demo_session_enabled` was `False`, and `database_target` was
`promisepatch_app@127.0.0.1:55432/promisepatch` with no password in it.

### 9.2 The local stack is a split-revision stack right now, and the gate says so

Read live, without changing anything: `worker` runs `promisepatch-backend:local` while `api` and
`mcp` run the pinned image `1c0653c73dd6…`. `pp runtime-identity` inside `api` answers
*No such command*; inside `worker` it answers the pre-`source_digest` shape, with
`llm_provider: fake` and `demo_session_enabled: true`.

So on this machine today the new gates refuse a scored run for four separate true reasons —
`build_identity`, `config_parity`, `product_model_identity` and `demo_provisioning` — and
`backend_build` passes throughout, which is the gap `build_identity` was written to close.
**Rebuilding and recreating `api`, `mcp` and the worker image is operator work that is owed
before `DR01`**, and it is not done here.

GitHub CI is the broad regression authority and has not run on this work.

## 10. What this did not do

No `SUR-1` attempt was driven and no `DR01` rehearsal was run. No Bedrock, OpenAI or NVIDIA call
was made. No AWS API was called. No scorer ran against a new bundle. No capture, verdict, result,
arm map or scored artefact was written. No frozen document was edited. No published run was
altered. No holdout was opened. No scenario semantics changed and nothing was tuned against a
result. **No production ablation flag, setting or seam was added**: a test asserts that nothing
under `apps/` or `packages/` so much as names the benchmark.

`sur1-phase3-closeout.md` §8 requirement 4 holds: the session that made this change does not take
the run. **`DR01` through the corrected seam, against the live local stack, is still owed before
any spend**, and `sur1-v3-forensic-audit.md` §8 names the five facts it must show — to which this
change adds two: one source digest across the stack, and an ablated attempt whose `REVALIDATION_CHECK`
rows carry the mark.
