# ADR-0020 — A scored benchmark hosts the product's own worker

**Status:** accepted
**Date:** 2026-09-20
**Supersedes:** nothing.
**Amends:** the execution topology `SUR-1` arms B and C are driven at. It does not amend the
frozen contract, the manifest, the prompt, the scorer, a world program, a budget or a label.
**Related:** [docs/sur1-v3-forensic-audit.md](../sur1-v3-forensic-audit.md) §5 and §7 item 2,
[docs/sur1-parity-correction.md](../sur1-parity-correction.md) §4,
[docs/sur1-execution-harness.md](../sur1-execution-harness.md),
[ADR-0019](0019-a-benchmark-world-is-installed-at-a-run-local-anchor.md)

## Context

`SUR-1` arm C is defined by the frozen contract as PromisePatch with **revalidation check 5
dropped from the outcome derivation and nothing else changed**, and the contract fixes how it is
dropped: the arm *wraps the evaluator at the benchmark boundary*. The harness implements that
literally — `scripts/sur1/ablation.ablation()` rebinds `promisepatch.domain.revalidation.revalidate`
for the length of one attempt and restores it afterwards.

**The rebinding reaches nothing.** It happens in the harness process. The evaluator that decides
runs inside the `worker` container, which is a different process with its own import table.
`diagnostics.ablation` is `[]` on all nine ablation captures of `20260920T1215Z-scored-v3` and all
eight of `20260919T2020Z-scored`. **Arm C has been arm B by construction on every topology this
benchmark has ever run on.** That is unmeasurable rather than unmeasured: the ablated arm is not
a weak reading, it is not a reading at all.

`preflight.ablation_reach` was added by the parity correction and refuses every topology that
exists today. A fourth scored run therefore cannot be bought until this is decided, which is why
this ADR exists rather than a patch.

### What rules the obvious repair out

The frozen contract's `ABLATION.what_is_not_touched` includes:

> Every file under `packages/` and `apps/`. The wrapper lives in the benchmark harness and no
> deployed process can reach it.

A governed ablation seam inside the product would be a file under `apps/`, would be reachable by
a deployed process, and would be benchmark-only behaviour in a system whose own constraints
forbid it. It is not a candidate and is not proposed here.

### What the audit found feasible

`promisepatch.worker.built()` is a clean async context manager that wires a worker exactly as the
`worker` entrypoint does; the product imports cleanly into the harness's environment; and
`WorkerControl` is already the seam a different topology plugs into. Running the product's own
durable worker **inside the harness process** keeps every clause of the sentence above literally
true: the wrapper still lives in the benchmark harness, no file under `apps/` or `packages/`
changes, and no deployed process can reach the wrapper — because for the length of a scored run
there is no deployed worker.

## Decision

**For a scored `SUR-1` run, the product's own durable worker runs inside the harness process, and
the containerised worker is down for the whole run.**

Six clauses, each load-bearing, each proved rather than asserted.

1. **Both arms, or neither.** Arms B **and** C are driven at the hosted worker. Arm C alone would
   be an arm-correlated topology change, which is precisely the class of defect the parity
   correction exists to remove. `PromisePatchArm` is one object and both arms hold it; there is no
   parameter, flag or branch by which the two could reach different workers.

2. **Production worker semantics, unbranched.** The hosted worker is built by
   `promisepatch.worker.built()` and driven by `Worker.run_forever()` — the same wiring, the same
   claim, lease and fence protocol, the same effect adapters, the same semantic provider
   resolution. The harness supplies settings and a stop event and nothing else. It does **not**
   install the deployment's `_DemoCaseKeeper`, which is a judge-entry convenience that lives in
   the `run()` entrypoint rather than in the worker, and which a scored stack is independently
   refused for by `preflight.demo_provisioning`.

3. **Arm C differs from arm B by the removal of check 5 and by nothing else.** The wrapper is the
   unchanged `scripts/sur1/ablation.ablation()`; `assert_only_check_five_moved` continues to
   assert the claim on every evaluator call. What changes is only that the process it rebinds in
   is now the process that calls it.

4. **The wrapper stays installed until the attempt's work is quiescent.** An arm whose surface
   loop returned while the worker was still executing steps would take the wrapper out mid-attempt
   and ablate a prefix of the work. `PromisePatchArm.drive_through_surface` now waits for the
   durable worker to go idle before the receivers are read, and arm C's context manager wraps that
   wait because it wraps that method. **Arms B and C gain the wait identically**; arm A does not
   drive the product and is unaffected.

5. **No competing worker.** A second worker claiming benchmark steps would execute them without
   the wrapper, and the ablation would silently cover a fraction of an attempt that nobody could
   recover from the artefacts. The compose `worker` service must be down before a scored run is
   authorised, must stay down, and any benchmark work executed by an identity that is not the
   hosted worker's **fails the run closed**.

6. **Worker-side evidence proves the treatment.** Not the harness's own log. The product writes
   one governed `REVALIDATION_CHECK` audit row per check, carrying the check's index, its name and
   the worker identity that produced it. Arm B's row for check 5 carries the real check name; arm
   C's carries `ABLATED_MARK`. That is the product's own append-only ledger saying which arm ran,
   read back after the attempt, and it is the artefact a later reader checks the ablation against.

### What is deliberately not decided here

- **No production ablation flag, setting, environment variable or seam.** Nothing under `apps/` or
  `packages/` learns that `SUR-1` exists. The one product change that accompanies this ADR is a
  read-only identity surface (`pp runtime-identity`), which is an operator surface and is not
  benchmark-only behaviour.
- **Nothing about what is scored.** The manifest, the prompt, the scorer, the nine world programs,
  the ground truth, the budgets, the retry policy, the reading rules and `PREDECLARATION_SHA` are
  untouched, and `implementation_sha` does not move: no file in `IMPLEMENTATION_MODULES` is edited.
- **No run.** This ADR authorises a topology. It takes no attempt, calls no model and produces no
  artefact.

## What is measured differently, and in which direction

Stated plainly, because a change to what a frozen benchmark measures is disclosed before it is
taken, never explained afterwards.

| Who | What moves | Direction |
|---|---|---|
| Arm C | Its ablation reaches the evaluator for the first time | **From no reading to a reading.** Every prior arm C number is arm B's. Nothing is recovered; the prior runs stay published as they are |
| Arms B and C | Driven at a worker in the harness process rather than in a container | Same code, same wiring, same database, same surfaces. Different process, different host network position, and no container scheduler between the loop and the work |
| Arms B and C | The receivers are read after the durable work goes quiescent | **Both may show effects that previously had not yet landed** when the attempt was collected. This can only increase what either arm is credited with, and it applies to both equally |
| Arm A | Nothing | It drives the world directly and has no durable case work of its own |
| All three | The scored stack must prove one source revision and one behaviour-relevant configuration across `api`, `mcp` and the hosted worker | Refusals, not readings. A split stack is refused rather than measured |

The third row is the only one that could flatter PromisePatch, and it is named for that reason.
It is arm-blind between B and C, which is the property the ablation comparison depends on.

## How it is proved rather than asserted

* `HostedWorkerControl` implements the existing `WorkerControl` protocol, so the installation
  lifecycle, the preflight and the run manifest reach it through the seam they already used.
* `preflight.ablation_reach` requires the process that decides revalidation to be the process the
  wrapper is installed in. `ComposeWorkerControl.evaluates_in_process()` is `False` and stays
  `False`; the hosted control answers `True` and proves it by installing the wrapper and calling
  the product's own resolved evaluator binding.
* `preflight.sole_executor` requires the compose `worker` to be absent or stopped, refuses a
  control that cannot say, and records the container's state so a restart during the run is
  detectable.
* `preflight.build_identity` requires `api`, `mcp` and the hosted worker to publish one
  `source_digest` and one `migration_revision`.
* `preflight.config_parity` requires one behaviour-relevant configuration across the three, and
  requires the database and the order system each process names to be the same system the
  harness's own receivers read.
* `HostedWorkerControl.executed_only_by_the_hosted_worker()` reads the product's governed audit
  rows back and refuses any benchmark work attributed to another identity.

## Consequences

* A scored run now depends on the product importing cleanly into the harness's environment, which
  it already did, and on the harness's environment carrying host-reachable addresses for the
  database and the order system. That is configuration, and `config_parity` refuses it when it is
  wrong rather than measuring it.
* The compose `worker` is stopped for the length of a scored run. Anything else on the machine
  expecting a durable worker is not served during it.
* `DRIVER_VERSION` moves to `1.4.0`. `implementation_sha`, `PREDECLARATION_SHA`, `SCORER_VERSION`
  and every frozen document are unmoved.
* `sur1-phase3-closeout.md` §8 requirement 4 continues to hold: **the session that makes this
  change does not take the run**, and `DR01` must be driven through the corrected seam before any
  spend — by a session other than the one that takes the scored run.
