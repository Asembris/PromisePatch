# The head-of-line correction

*Written 2026-09-18. The correction [the disposition declined](g8-head-of-line-disposition.md)
was made, at the project owner's direction. Neither that document nor
[the measurement](g8-head-of-line-measurement.md) nor
[its predeclaration](g8-head-of-line-predeclaration.md) is edited by this one, and none of the
nine published captures is touched. This is the later truth recorded beside them.*

**The gate did not move.** `H <= 1000.0 ms`, taken from the worker's own `IDLE_INTERVAL`, is
still the threshold and is now imported by the regression rather than restated anywhere.

---

## 1. What this supersedes, and what it does not

The disposition's §1 says *"No scheduling correction was made."* That sentence describes the
decision taken on 2026-09-17 and remains an accurate record of it. It is superseded here only in
the sense that the decision has since been reversed by the person whose decision it was.

**None of the disposition's reasoning is claimed to have been wrong.** Its §6 lists three
conditions that would oblige revisiting, and **none of them fired**: no larger body of deployed
semantic latencies was gathered, no person was put behind the worker's semantic call, and no
second replica was run. This correction was asked for, not triggered. What the disposition's §2
called open — whether the real latency is nearer 900 ms or 1 500 ms — is still open, and nothing
here settles it. The correction simply removes the coupling that made the answer matter.

The disposition's §3 finding is the one this work acts on, and it held at HEAD:

> **`H` exceeds the injected delay by 2–3 % across a five-fold range of `D`, with service time
> flat.**

## 2. The root cause, re-established at HEAD rather than assumed

`Worker.run_once` was one sequential pass — timers, one step, one outbound dispatch, one inbound
record, one order-system event — and `_execute_one_step` awaited `semantic_intake.prepare`
inline. For the whole length of a provider call, the process's single loop task was inside that
`await`. It claimed nothing, dispatched nothing and ingested nothing. The delay was therefore not
*added to* a queue; the queue simply stopped for its duration, which is why the published numbers
track `D` one for one.

Three things that were **not** the cause, checked rather than assumed:

* **No transaction is held across the call.** `semantic_intake.prepare` commits its hydration
  transaction before `provider.run` and opens a fresh one to store the reading. That was already
  correct and is unchanged.
* **No lock is held across the call.** The case row is taken by `execute_step`, after.
* **The claim is not the bottleneck.** `steps.claim_step` is a short transaction of its own with
  `FOR UPDATE SKIP LOCKED`.

The coupling was purely the shape of the loop: one task, one await.

## 3. Before

`apps/backend/tests/test_worker_responsiveness.py`, run against the unmodified worker at
`112f575`. Case A staged with its `INTERPRET_SEMANTICALLY` step pending; a 5 000 ms delay
injected in front of the fake provider; case B opened *after* the provider call had started. The
wait is `case_steps.started_at − case_steps.created_at` for B's first step, both written by the
product:

| | |
|---|---|
| injected delay | 5 000.0 ms |
| **B's measured wait** | **5 212.7 ms** |
| gate | 1 000.0 ms |
| verdict | **FAIL** |

The 212.7 ms above the delay is the same 2–3 % overshoot the nine published runs recorded, from
an independent harness. The mechanism the disposition described is the mechanism reproduced.

## 4. The model chosen

**A semantic preparation runs in a task beside the loop, and the loop never waits for one.** Up
to `DEFERRED_SEMANTIC_LIMIT` (4) of them at a time.

The claim is unchanged and goes with the work whole: the deferred task prepares and executes
under the very lease and fencing token the cycle wrote, in the same transactions, taken in the
same order, attributed to the same identity. What changed is which task is suspended inside
`await provider.run(request)`.

Two claim-time exclusions make the arrangement provable rather than argued. `claim_step` now
accepts:

* **`exclude_cases`** — a cycle never takes a second step of a case this process already has a
  preparation open on, so two steps of one case cannot reach `lock_case` in an order nobody
  chose.
* **`exclude_kinds`** — when all four slots are taken, the cycle stops claiming semantic steps
  and overtakes them instead of waiting for one or starting a fifth.

Both default to empty, both are recomputed on every sweep, and neither leaves the process. A row
one sweep passed over is ordinary claimable work to the next sweep and to every other worker in
the meantime. Nothing is durable about a skip.

### Why not simply run more workers

The disposition's §4 named this as *"the cheapest correction, if one is ever wanted"*. It is not
taken, because **it raises the bar by a constant and does not remove the coupling**. With `N`
identical workers, `N` concurrent slow sentences block everything again; the arrangement above
blocks nothing at any `N`, because the loop's own task never awaits a provider at all. Running
more workers remains available and remains safe, and is now an availability decision rather than
a latency workaround.

### What stays serialised, deliberately

* One cycle at a time per process. Timers, ordinary steps, outbox dispatch, inbox ingestion and
  order-mirror application are exactly as sequential as they were.
* All work of one case, by the case row lock in `execute_step` and by `exclude_cases` above.
* One outbound effect per cycle, unchanged.
* `run_once` — the form provisioning, the operator commands and every crash-point test use —
  **defers nothing**. What it starts, it finishes before it returns. Only `run_forever` defers.
  That is why no existing crash-safety proof changed shape.

## 5. The invariants, and where each is held

| invariant | what holds it now |
|---|---|
| unrelated cases progress independently | the loop never awaits a provider; §6's measurement |
| same-case ordering | `exclude_cases` at claim time, and the case row lock in `execute_step` |
| no double execution | unchanged: `FOR UPDATE SKIP LOCKED`, the lease, `(state, lease_owner, attempts)` |
| no duplicate external effects | unchanged: the outbox is swept by the loop, one per cycle, and no deferred task dispatches |
| stale workers cannot commit | unchanged fence, asserted under deferral by a test that ages the lease out mid-call |
| authority and revalidation | untouched. Nothing here reads, writes or reorders a consent record, a plan approval or a revalidation check |
| retries and restarts | unchanged. A deferred task that dies leaves an `IN_FLIGHT` row and an expiring lease, which is the same state a killed process leaves |
| bounded concurrency | `DEFERRED_SEMANTIC_LIMIT`, enforced at claim time rather than by queueing |
| one slow or failing preparation cannot stall the rest | the task swallows, records and logs; the loop is not in its call stack |
| no case looks complete before its work is | `settle()` on every exit from `run_forever`, including the error exit |

**The one behaviour that is genuinely new, stated plainly.** An exception inside a deferred
preparation no longer stops the worker. Before, anything other than `SQLAlchemyError` or
`OSError` escaping the step path left `run_forever`; that was the deliberate "a bug in a
transition should not run every second" rule. A deferred task has no cycle to abort and no caller
to raise into, and stopping the loop would stall every unrelated case — the exact coupling this
change exists to remove. So the failure is appended to `Worker.deferred_failures`, logged with
its traceback, and the step is left to the machinery that already handles a worker that stopped
in that window: the lease expires, the next sweep reclaims the row as the next attempt, and the
retry ladder ends in a terminal escalation like any other. Nothing a failed task had written was
authority.

## 6. After

Same test, same delay, same gate, same instants, taken from the product's own columns:

| | before | after |
|---|---|---|
| injected delay | 5 000.0 ms | 5 000.0 ms |
| **B's measured wait** | **5 212.7 ms** | **49.3 ms** |
| gate | 1 000.0 ms | 1 000.0 ms |
| verdict | **FAIL** | **PASS** |

**This is one run of one regression test, not a re-run of the nine-capture protocol.** It is
deliberately not offered as a replacement for the published measurement: that protocol's value
is that it was predeclared, and re-running it would need its own predeclared amendment. What this
number establishes is that the mechanism the measurement found is gone, measured the same way —
by subtracting two columns the product wrote.

Two honest caveats about the figure:

* **The worker under test uses a 50 ms idle interval, not 1 000 ms.** Ready work arriving one
  millisecond into an idle sleep would otherwise wait most of the gate before anything was
  claimed, which would make a 1 000 ms assertion a coin toss about when the test wrote a row.
  Turning the sampling down leaves head-of-line coupling as the only thing the measured wait can
  be made of. The gate itself is untouched and is imported from `IDLE_INTERVAL`.
* **`49.3 ms` is a laptop reading of a claim sweep, not a latency claim about the deployment.**
  What it is offered as is *nowhere near five seconds*.

## 7. Tests

All in `apps/backend/tests/test_worker_responsiveness.py`, all against the local PostgreSQL, all
with the fake provider plus an injected sleep. No model was called and no AWS resource was
touched.

| test | what it establishes |
|---|---|
| unrelated ready work does not wait behind a slow semantic preparation | the headline, against the imported gate |
| a stopped worker has finished what it deferred | `settle()`; no case is reported done while its task runs |
| several slow cases progress together and none of them twice | the bound holds *and* is really reached; one call and one attempt per case |
| a preparation that outlives its lease still commits nothing | the fence, under deferral: the reading on the row is the worker that took over |
| a preparation that raises does not stall unrelated work | the new failure mode, bounded: one recorded failure, loop alive, unrelated case served |
| a claim sweep leaves an excluded case alone | the exclusion, and that a skip writes nothing and is not durable |
| a claim sweep leaves an excluded kind alone | overtaking rather than queueing when slots are full |

Regression suites run alongside, all green: `test_step_execution`, `test_worker_recovery`,
`test_worker_boundary`, `test_semantic_provider`, `test_semantic_intake`, `test_exception_intake`,
`test_demo_case_provisioning`, `test_workflow_timers`, `test_workflow_outbox`,
`test_workflow_inbox`, `test_workflow_handlers`, `test_started_work_contract`,
`test_recovery_execution`, `test_recovery_revalidation`, `scripts/tests`. Plus `ruff check`,
`ruff format`, mypy groups A and C, and import-linter (30 contracts kept).

**No test was weakened, skipped, xfailed or deselected.** One call site in
`test_semantic_provider.py` was adapted to the new keyword-only `defer` parameter on the private
`_execute_one_step`; its assertions are byte-identical.

## 8. What was not done

* **The nine published captures were not re-run, re-read or re-derived**, and
  `scripts/run_head_of_line.py` is unchanged. A reader who wants the corrected worker measured
  under that protocol needs a predeclared amendment first.
* **The threshold was not moved**, in either direction.
* **No AWS resource was touched and no model was called.**
* **No manifest, fixture label, frozen document or published run capture was changed.** The
  11/16 effect-set headline is untouched and both evaluation holdouts stay sealed.
* **The deployment was not changed.** The deployed host still runs one replica and has not been
  redeployed; this correction is in the repository, not on the instance.
* **`IDLE_INTERVAL` and `LEASE_DURATION` were not tuned.** Neither was the cause.
