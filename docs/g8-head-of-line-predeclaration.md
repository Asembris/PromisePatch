# Predeclaring the G8 head-of-line measurement

*Everything below was fixed **before** the harness existed and before any instant had been
recorded. **No measurement run has been taken, no wait has been computed, no `H` exists and there
is no pass or fail.** The only thing this document's harness has done is one throwaway smoke run,
declared in §12, whose numbers are evidence that the harness executes and are interpreted nowhere.
No AWS resource was touched, no model was called, no product code or test was changed, and both
holdouts stay sealed.*

**Why this document precedes the harness.** Run 1 of the G7 voice measurement was voided *after*
its number had been published, and [claims-audit.md](claims-audit.md) F2 records what that cost.
The rule this repository took from it is that nothing about a measurement is decided once a number
exists. So the scenario, the instants, the arithmetic, the threshold, the failure rule and the void
conditions are all settled here, in advance, and a later session runs the harness against this
document and computes the verdict from the capture it wrote.

**A predeclaration may be amended while no measured run exists, and never afterwards.** Any
amendment carries its date, its commit and its reason, and leaves the superseded text in place.

**Amendment 1 — 2026-09-16, written against `54c79ac`, while no measured run existed.** A **third
arm** is added, at a latency this repository has actually recorded from the real model. §14 holds
the whole of it: what the arm is for, the evidence the figure rests on and what it does not rest
on, the arithmetic generalised from two arms to three, and §8's prediction restated for each arm
before any number exists. §3, §4.2, §4.5, §7, §9, §10 and §12 carry its consequences, each with
its superseded text kept verbatim beside the replacement. **§8 is untouched.** The threshold is
`H ≤ 1000.0 ms`, it was not moved in either direction, and it applies to every arm identically.
§1, §2, §5, §6, §11 and §13 are unamended. The control arm and the 8 000 ms arm are unchanged in
every respect.

*Superseded on 2026-09-16, kept verbatim: "There are no amendments."*

---

## 1. The requirement, quoted

One line in `new_roadmap.md` §11 G8 carries it. It is not paraphrased here, and nothing below adds
a criterion it does not state.

`new_roadmap.md:367`:

> Measure delayed semantic calls alongside unrelated ready work. No held DB transaction does not
> prove no head-of-line delay. Make the smallest scheduling correction only if observed
> responsiveness misses the gate.

[g8-adversarial-proof-map.md](g8-adversarial-proof-map.md) §4 audited the repository for this and
recorded it **UNPROVEN**: the phrase *head-of-line* occurs exactly once in the whole tree, in the
requirement itself, and no run capture, document, script or test records the measurement. That
section also names the two artifacts nearest to it and says why neither is it — most importantly
`test_order_amendment.py::test_the_amendment_is_sent_with_no_database_transaction_held`, which is
**exactly** the evidence the requirement's second sentence names as insufficient.

### The claim, in one sentence

> **When one semantic call is held open, unrelated work that was already ready and durable is
> served no later than it would have been had that call returned at once.**

That is the thing measured. The second sentence of the requirement is what makes it necessary:
proving that no database transaction is held during the call says nothing about whether the
*worker* is held during it, and only a measurement can answer that.

---

## 2. What this document is

A protocol, fixed in advance, for one measurement, plus the harness that executes it. It is not a
benchmark, not a load test, not an SLA and not a claim about production. §11 states what it does
not establish, in full, before any number exists.

Three separations are deliberate and are what make the record worth anything:

* **The harness computes no verdict.** It records raw instants to a capture file and stops. Every
  subtraction, every median, `H`, and the comparison against the threshold are §9's arithmetic,
  applied by a later session to a capture it did not write.
* **The threshold is taken from a constant that already existed for another reason** (§8), so it
  cannot be accused of having been chosen to be met.
* **The building session is not the measuring session.** This one wrote the protocol and the
  harness and proved the harness runs. It did not take the measurement.

---

## 3. Where the delay goes, verified in the code before it was written down

There is exactly **one** provider call on the durable work path, and it is in the worker's step
loop. [worker.py:130-146](../apps/backend/src/promisepatch/worker.py) reads:

```python
async def _execute_one_step(self) -> str | None:
    claim = await steps.claim_step(self.database, worker=self.identity.value)
    if claim is None:
        return None
    if claim.kind == STEP_INTERPRET_SEMANTICALLY:
        await semantic_intake.prepare(self.database, self.semantic, claim=claim)
    result = await steps.execute_step(self.database, claim=claim, actor=self.actor)
```

and `_execute_one_step` is the second of five awaits in
[`Worker.run_once`](../apps/backend/src/promisepatch/worker.py), which runs
`timers.fire_due_timer`, then the step, then `outbox.dispatch_one`, then `inbox.process_one`, then
`order_mirror.process_one`, one after another, and returns.

**The delayed call is `SemanticJob.INTERPRET_UTTERANCE`**, reached through
`semantic_intake.prepare` → `grounding.question_for` → `provider.run` →
`StructuredSemanticProvider.invoke`. `prepare`'s own docstring names this as *"the only place in
the cycle where a provider call can be made with no transaction open"* — which is the property the
requirement's second sentence says is not enough.

### The delay is injected without touching production code

`Worker.semantic` is a constructor field typed to the `SemanticProvider` protocol, injected, and
defaulting to `FakeSemanticProvider`. `StructuredSemanticProvider` exists so that *"subclasses
implement `invoke` and nothing else"*. The harness therefore supplies its own provider — a subclass
of `FakeSemanticProvider` that awaits a stated number of milliseconds and then delegates to
`super().invoke(...)`, so the answer, the validation path and the stored reading are byte for byte
the ones the unmodified fake produces.

**Nothing in `apps/backend/src/` is changed, read differently, or configured differently by this
measurement.** The injection is a harness-side argument to a constructor the product already
exposes, and the delay is an explicit operator action: it is the number on the command line.

This settles the first NON-GO condition: the delay can be injected without a production change.

### What the delay may not exceed

*Amended 2026-09-16 by Amendment 1. The superseded paragraph is kept verbatim below it.*

`steps.LEASE_DURATION` is `timedelta(seconds=60)`. A held call longer than the lease would let the
step be reclaimed mid-call, which would measure lease recovery rather than scheduling. **The
injected delay must be well inside 60 seconds**; §4 fixes the longer of the two delayed arms at 8,
which is inside it by a factor of seven and a half, and the representative arm at 1.5, which is
inside it by a factor of forty.

> **Superseded 2026-09-16, verbatim:** `steps.LEASE_DURATION` is `timedelta(seconds=60)`. A held
> call longer than the lease would let the step be reclaimed mid-call, which would measure lease
> recovery rather than scheduling. **The injected delay must be well inside 60 seconds**; §4 fixes
> it at 8, which is inside it by a factor of seven and a half.

---

## 4. The scenario, fixed

### 4.1 The delayed semantic call — one, and exactly one

A case is opened with the sentence

> **the delivery situation is weird**

`interpretation.interpret` returns `HumanInterpretationRequired(reason=NO_CATEGORY, detail="no
supply, stock or equipment marker in the report")` for it. This was verified against the shipped
Hollow Oak dataset **before this sentence was declared**, by a pure call with no database in the
room, using the projection `test_physical_interpretation.py` builds. The sentence is not invented
for the occasion: it is `_intake_support.UNREADABLE`, already used by five test modules for exactly
this purpose.

A deterministic reading that cannot conclude enqueues a durable `INTERPRET_SEMANTICALLY` step
([physical.py:326-330](../apps/backend/src/promisepatch/domain/physical.py)), and that step is what
the worker claims and holds the provider call inside. The fake's unscripted answer for this job is
`{"clarification_needed": True}` — a valid answer, so no corrective retry is triggered and **the
run makes exactly one provider call**. The capture records the count; a run that made any other
number is void under §10.

**This case binds nothing.** It names no resource, no commitment and no order, so it is unrelated
to the eight below in the strongest sense available: there is no entity through which it could
reach them.

### 4.2 The delay, and how it is injected

*Amended 2026-09-16 by Amendment 1: a third arm at 1 500 ms. The 8 000 ms arm and the control arm
are unchanged, and the superseded text is kept verbatim at the end of this subsection. §14 derives
the new figure.*

| | fixed |
|---|---|
| **delay `D`** | **0 ms** in the `control` arm, **1 500 ms** in the `representative` arm, **8 000 ms** in the `treatment` arm |
| **where** | `StructuredSemanticProvider.invoke`, in a harness subclass of `FakeSemanticProvider` |
| **how** | `await asyncio.sleep(D / 1000)` before delegating to `super().invoke(...)` |
| **how many** | exactly one call per run (§4.1) |

**What each arm is for, one sentence each.** The **control** arm establishes the baseline — what
the eight unrelated items wait when nothing is held at the head of the queue. The
**representative** arm answers whether this matters in operation, by holding the call for as long
as this repository has actually recorded the real model holding it. The **treatment** arm isolates
whether delay propagates one for one, by holding it far longer than any recorded call so that a
proportional effect and a fixed overhead cannot be confused for one another.

**Why 8 000 ms.** Unchanged, and reproduced here because the arm is unchanged: two constraints and
one choice. It must be comfortably inside `LEASE_DURATION = 60 s` (§3). It must be large enough
that no plausible variation on a development machine could be mistaken for it: 8 000 ms is **eight
times** §8's threshold, so a signal at the threshold's scale and a signal at the delay's scale
cannot be confused for one another. And it must be small enough that nine runs are cheap. Nothing
about the number was chosen by looking at a measurement, because none exists.

**Why 1 500 ms.** §14, in full, with the recorded calls it rests on named, and the derivation it
was *not* given stated beside it.

**The control arm runs the identical code path** — the same harness provider class, the same
`await asyncio.sleep`, the same delegation — with the number set to zero. The three arms differ in
one integer and in nothing else.

> **Superseded 2026-09-16, verbatim:**
>
> | | fixed |
> |---|---|
> | **delay `D`** | **8 000 ms** in the treatment arm, **0 ms** in the control arm |
> | **where** | `StructuredSemanticProvider.invoke`, in a harness subclass of `FakeSemanticProvider` |
> | **how** | `await asyncio.sleep(D / 1000)` before delegating to `super().invoke(...)` |
> | **how many** | exactly one call per run (§4.1) |
>
> **Why 8 000 ms.** Two constraints and one choice. It must be comfortably inside
> `LEASE_DURATION = 60 s` (§3). It must be large enough that no plausible variation on a
> development machine could be mistaken for it: 8 000 ms is **eight times** §8's threshold, so a
> signal at the threshold's scale and a signal at the delay's scale cannot be confused for one
> another. And it must be small enough that six runs are cheap. Nothing about the number was
> chosen by looking at a measurement, because none exists.
>
> **The control arm runs the identical code path** — the same harness provider class, the same
> `await asyncio.sleep`, the same delegation — with the number set to zero. The two arms differ in
> one integer and in nothing else.

### 4.3 The unrelated ready work

**Eight cases**, opened in this fixed order, each from a distinct sentence the deterministic
interpreter resolves outright, each naming a **different** resource:

| # | sentence | reading | resource |
|---|---|---|---|
| 1 | `the deck oven is down` | `EQUIPMENT_UNAVAILABLE` | `res-deck-oven` |
| 2 | `the convection oven is down` | `EQUIPMENT_UNAVAILABLE` | `res-convection-oven` |
| 3 | `the butter spoiled` | `STOCK_UNUSABLE` | `res-butter` |
| 4 | `the mascarpone spoiled` | `STOCK_UNUSABLE` | `res-mascarpone` |
| 5 | `the lemon curd spoiled` | `STOCK_UNUSABLE` | `res-lemon-curd` |
| 6 | `the dark chocolate spoiled` | `STOCK_UNUSABLE` | `res-dark-chocolate` |
| 7 | `the ladyfingers spoiled` | `STOCK_UNUSABLE` | `res-ladyfingers` |
| 8 | `the cream in the walk-in went off` | `STOCK_UNUSABLE` | `res-heavy-cream` |

All eight readings were verified pure, against the shipped dataset, with no database, **before
this table was declared**. Sentence 1 is already asserted by
`test_exception_intake.py::test_equipment_down_records_an_outage_without_asking_anything`, and
sentence 8 by
`test_physical_interpretation.py::test_unqualified_spoilage_is_a_total_loss_and_says_so_by_attesting_no_quantity`.

**The tracked item for each is that case's first step** — its `BEGIN_INTERPRETATION` row, enqueued
inside the same transaction as the case by `intake.open_physical_exception`
([intake.py:201-205](../apps/backend/src/promisepatch/domain/intake.py)). Eight items, one per
case, all `PENDING` and claimable before the timed window opens.

**Why the first step and not the whole case.** `BEGIN_INTERPRETATION` is ready the instant the
case exists, so its readiness instant is unambiguous. Every later step of those cases becomes
ready *inside* the measured window, which makes its wait a mixture of queueing and of its own
predecessor's service time, and therefore not a clean reading of the thing being measured. Those
later steps are still recorded in the capture and are marked `tracked: false`; §9 excludes them
from the arithmetic, and they are excluded here rather than after anybody has seen them.

### 4.4 The ordering, which is the whole scenario

`steps.claim_step` selects `.order_by(CaseStep.created_at, CaseStep.id).limit(1)`. So the queue is
FIFO by row creation, and **the delayed step must be the oldest claimable row** or there is no head
of the line to block. The harness stages it in that order:

1. `pp reset-demo-state` — the existing operator command, unchanged.
2. Open the delayed case (§4.1).
3. Drive worker cycles with a provider that **raises if it is called at all**, stopping the instant
   a `PENDING INTERPRET_SEMANTICALLY` row exists for that case. It takes two cycles, and the cycle
   that creates the row has already spent its one claim, so nothing claims the semantic step during
   staging. A staging cycle that somehow reached the provider fails loudly instead of quietly
   spending the delay in the wrong place.
4. Open the eight unrelated cases, in the order of §4.3, each in its own transaction, so each row's
   `created_at` is strictly later than the semantic step's.
5. Record `T0` and assert the arrangement: the semantic step is `PENDING`; it is the oldest
   claimable row; the eight tracked rows are `PENDING`. A run whose arrangement fails this is void
   under §10.
6. Install the timed worker — same identity, delaying provider — and run `Worker.run_forever` until
   all eight tracked rows are terminal, or 120 seconds elapse.

**Nothing is rigged by this.** Head-of-line delay is the question of what happens to work queued
*behind* a slow item; putting the slow item at the head is the scenario, not a thumb on the scale.
A run in which the slow item were somewhere else would measure something the requirement does not
ask about.

### 4.5 Repetitions

*Amended 2026-09-16 by Amendment 1: three arms rather than two, so nine runs rather than six.
Three runs per arm is unchanged. Superseded text verbatim below.*

**Three runs per arm, nine in all, alternating `C R T C R T C R T`.** Alternating rather than
blocked so that any drift in the machine over the run falls on all three arms equally. Each run is
preceded by its own `pp reset-demo-state`, so no run inherits another's state, and the eight
sentences never collide with an attestation a previous run already made.

> **Superseded 2026-09-16, verbatim:** **Three runs per arm, six in all, alternating
> `C T C T C T`.** Alternating rather than blocked so that any drift in the machine over the ten
> minutes falls on both arms equally. Each run is preceded by its own `pp reset-demo-state`, so no
> run inherits another's state, and the eight sentences never collide with an attestation a
> previous run already made.

Items are identified across runs **by their sentence**, which is stable, and never by step id or
case id, which are new every run.

---

## 5. What is timed, and which code records each instant

Every instant used by §9's arithmetic is read from the **database's own clock** by **production
code**, and written to a column the product already keeps. The harness reads the columns
afterwards. It contributes no instant that any number depends on.

| symbol | column | written by | what it is |
|---|---|---|---|
| `ready(i)` | `case_steps.created_at` | the `server_default=func.now()` on [`CaseStep.created_at`](../apps/backend/src/promisepatch/db/models/workflow.py), stamped by the insert in [`steps.enqueue_step`](../apps/backend/src/promisepatch/domain/steps.py) | the start instant of the transaction that made the row exist |
| `served(i)` | `case_steps.started_at` | `started_at=now` in [`steps.claim_step`](../apps/backend/src/promisepatch/domain/steps.py), where `now` is `database_now(connection)` | the start instant of the transaction in which the worker took this row |
| `settled(i)` | `case_steps.done_at` | `done_at=now` in [`steps._settle`](../apps/backend/src/promisepatch/domain/steps.py), same `now` | the start instant of the transaction that finished it |

`database_now` is `SELECT now()`, which PostgreSQL defines as `transaction_timestamp()` — the
transaction's start. [clock.py](../apps/backend/src/promisepatch/db/clock.py) says why the product
reads it rather than the process clock, and the consequence here is that all three instants come
from one authority and none of them can be moved by the harness.

**The gate is measured on `served`, not on `settled`:**

```
wait_ms(i)    = (served(i)  - ready(i))  in milliseconds        ← the gate's number
service_ms(i) = (settled(i) - served(i)) in milliseconds        ← published beside it, not gated
```

`wait_ms` is queueing: how long a durable, ready, unrelated item sat there before the worker got to
it. That is exactly what head-of-line blocking is. `service_ms` is the item's own execution, which
the requirement does not ask about and which is published so that a reader can see it was not
folded into the other number.

### Two conservative choices, made here rather than later

* **`ready(i)` is the inserting transaction's *start*, not its commit.** The row is not claimable
  until that transaction commits, so the true readiness instant is slightly later than `ready(i)`,
  and **every `wait_ms` published under this protocol is therefore slightly longer than the truth.**
  The measurement is made harder on the product by this, not easier, which is why the available
  instant is used rather than a commit instant the product does not record.
* **No process clock appears in any published interval.** The harness records its own monotonic
  readings for the run's boundaries and for the provider's observed hold, and publishes them as
  context. No number in §9 is derived from them.

---

## 6. The environment

Fixed here; every field is read from the actual machine at run time and written into the capture.

| | fixed |
|---|---|
| **store** | the local `docker compose` **PostgreSQL only**, published on loopback. No AWS, no RDS, no deployed host. |
| **model** | **none.** The provider is `FakeSemanticProvider` plus an injected sleep. No Bedrock call, no credential, no network egress of any kind. |
| **order system** | **not used.** The worker is constructed with `FakeEffectAdapter` and `fetch_order=None`, so no run can be lengthened or shortened by the simulator's HTTP. Declared rather than discovered: the measurement is about scheduling inside the worker, and a second network dependency would be a second variable. |
| **worker processes** | **exactly one**, in the harness process, matching the deployed composition — `docker-compose.yml`'s `worker:` service declares no replicas. The compose `api`, `mcp` and `worker` containers must be **stopped**; §10 makes a second worker a void condition and §7 makes the harness refuse to start beside one. |
| **observation connection** | its own `RuntimeDatabase`, separate from the worker's, so the harness's polling never competes for the worker's pool. |
| **served commit** | the working tree at `HEAD`, clean. Recorded in the capture with `git rev-parse HEAD` and `git status --porcelain`. |
| **machine** | the development machine, Windows 10 Pro 19045. Platform, Python version and PostgreSQL `version()` are read at run time and published. |
| **other load** | no other application is driven on the machine during the six runs. |

---

## 7. The one command

From a clean checkout, with the local stack's PostgreSQL up and the `api`, `mcp` and `worker`
containers down:

```bash
uv run python scripts/with_local_env.py -- uv run python scripts/run_head_of_line.py
```

*Amended 2026-09-16 by Amendment 1. The command is unchanged; the number of runs it performs is
not. Superseded sentence verbatim below.*

That is the whole measurement: nine runs, `C R T C R T C R T`, each with its own fixture reset,
writing one capture file per run under `docs/head-of-line/runs/`. `--smoke` runs the shortened
shape of §12 instead, and writes captures labelled `smoke` that no arithmetic may read.

> **Superseded 2026-09-16, verbatim:** That is the whole measurement: six runs, `C T C T C T`,
> each with its own fixture reset, writing one capture file per run under
> `docs/head-of-line/runs/`. `--smoke` runs the shortened shape of §12 instead, and writes
> captures labelled `smoke` that no arithmetic may read.

The harness **refuses to start** rather than producing a record it cannot vouch for:

* if another worker process is live. It opens the delayed case, waits two seconds without running a
  cycle, and requires the case's first step to be still `PENDING` with `attempts == 0`. A running
  worker container claims it within its one-second idle interval.
* if the arrangement of §4.4 step 5 does not hold.
* if the injected provider was called any number of times other than once.

---

## 8. The pass condition, decided now

> **`H` ≤ 1000.0 ms**, where `H` is the largest added wait over the eight unrelated items (§9).

**1000.0 ms is `IDLE_INTERVAL`**, declared at
[worker.py:60](../apps/backend/src/promisepatch/worker.py) as `IDLE_INTERVAL: Final = 1.0`, with
the comment that it is *"short enough that a step enqueued by an API request is picked up
promptly"*.

It is used as the threshold for three reasons and no others:

1. **It is the worker's own statement of what "promptly" means.** The product already says, in a
   constant, how long ready work may reasonably sit before a cycle looks at it. Holding the worker
   to its own number is not a standard imported from outside.
2. **It predates this measurement by a long way and was written for an unrelated reason** — pacing
   an idle loop against the database. It cannot have been chosen to be met.
3. **It is eight times smaller than the injected delay** (§4.2), so the two scales cannot be
   confused, and a result near the threshold would be a real finding rather than noise.

Two edges, settled before any number exists:

* **One second is exactly 1000.0 milliseconds.** `H = 1000.0` passes; `H = 1000.1` does not. No
  rounding is applied before the comparison. Intervals are published to 0.1 ms.
* **A negative `H` passes.** Unrelated work served *sooner* under a held call than under a prompt
  one is not a head-of-line delay.

### What this document predicts, stated before the run rather than after

Reading `Worker.run_once` (§3), the five awaits are sequential and `_execute_one_step` holds the
provider call inside the second of them. Nothing in that loop is concurrent, and nothing claims a
second step while the first is in the provider. **The expected outcome of this measurement is
therefore a fail**, with `H` near 8 000 ms.

That prediction is written here deliberately. It is what stops the threshold from being read as
one chosen to be passable, and it is the honest position: the requirement's own wording —
*"make the smallest scheduling correction only if observed responsiveness misses the gate"* —
anticipates a fail and makes a correction conditional on one. A prediction is not a measurement,
carries no number, and settles nothing. **The threshold does not move when the result arrives**,
in either direction.

---

## 9. The arithmetic, worked on fabricated numbers

Every number in this section is **invented**. None of it was measured, none of it came from the
smoke run of §12, and it exists only so that no arithmetic decision is made after real numbers
exist.

*Amended 2026-09-16 by Amendment 1: the same arithmetic, applied once per delayed arm rather than
once. Nothing about how a wait, a median or an `H` is computed changed, and the threshold it is
compared against did not move. Superseded block verbatim at the end of this section.*

For each run `r` and each tracked item `i` in 1..8 (§4.3), from the capture:

```
wait_ms(r, i)    = (started_at(r, i) - created_at(r, i)) in milliseconds
service_ms(r, i) = (done_at(r, i)    - started_at(r, i)) in milliseconds

W_control(i)        = median{ wait_ms(r, i) : r in the 3 control runs }
W_representative(i) = median{ wait_ms(r, i) : r in the 3 representative runs }
W_treatment(i)      = median{ wait_ms(r, i) : r in the 3 treatment runs }

added_ms_representative(i) = W_representative(i) - W_control(i)
added_ms_treatment(i)      = W_treatment(i)      - W_control(i)

H_representative = max{ added_ms_representative(i) : i in 1..8 }
H_treatment      = max{ added_ms_treatment(i)      : i in 1..8 }
```

**The control arm has no `H` of its own.** It is the baseline both delayed arms are subtracted
from, which is what it was before this amendment; there is no third subtraction and the two
delayed arms are never subtracted from each other.

`H_representative` and `H_treatment` are each compared against §8's 1000.0 ms, separately, and
**each arm carries its own verdict**. §8's two edges apply to both unchanged: 1000.0 passes,
1000.1 does not, no rounding is applied before the comparison, and a negative `H` passes. Worked
examples A, B and C below are unamended and read as the arithmetic for one delayed arm; with two,
the same work is done twice against the same control column.

> **Superseded 2026-09-16, verbatim:**
>
> For each run `r` and each tracked item `i` in 1..8 (§4.3), from the capture:
>
> ```
> wait_ms(r, i)    = (started_at(r, i) - created_at(r, i)) in milliseconds
> service_ms(r, i) = (done_at(r, i)    - started_at(r, i)) in milliseconds
>
> W_control(i)   = median{ wait_ms(r, i) : r in the 3 control runs }
> W_treatment(i) = median{ wait_ms(r, i) : r in the 3 treatment runs }
>
> added_ms(i)    = W_treatment(i) - W_control(i)
> H              = max{ added_ms(i) : i in 1..8 }
> ```
>
> `H` is compared against §8's 1000.0 ms. That is the entire verdict.

### Worked example A — fabricated, fails

Fabricated `wait_ms`, three runs per arm, eight items:

| item | control r1 | r2 | r3 | **median** | treat. r1 | r2 | r3 | **median** | **added** |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 31.2 | 29.8 | 33.5 | **31.2** | 8031.9 | 8029.4 | 8034.6 | **8031.9** | **8000.7** |
| 2 | 78.4 | 80.1 | 76.9 | **78.4** | 8079.2 | 8081.7 | 8077.5 | **8079.2** | **8000.8** |
| 3 | 120.9 | 118.4 | 124.2 | **120.9** | 8122.5 | 8119.8 | 8125.1 | **8122.5** | **8001.6** |
| 4 | 166.1 | 170.5 | 168.0 | **168.0** | 8169.8 | 8171.2 | 8167.4 | **8169.8** | **8001.8** |
| 5 | 210.7 | 208.2 | 213.4 | **210.7** | 8214.0 | 8209.5 | 8216.8 | **8214.0** | **8003.3** |
| 6 | 259.3 | 262.7 | 257.8 | **259.3** | 8261.6 | 8264.1 | 8258.9 | **8261.6** | **8002.3** |
| 7 | 304.8 | 300.1 | 307.5 | **304.8** | 8306.3 | 8302.7 | 8309.2 | **8306.3** | **8001.5** |
| 8 | 351.0 | 349.6 | 353.2 | **351.0** | 8352.9 | 8350.4 | 8355.3 | **8352.9** | **8001.9** |

`H = max(added) = 8003.3 ms`. `8003.3 > 1000.0` → **the gate is missed**, and the requirement's
conditional *"make the smallest scheduling correction"* is reached. Note that the rising control
column is simple queue position — item 8 waits for seven predecessors' service even when nothing is
delayed — and that subtracting the control median is what removes it from `added_ms`.

### Worked example B — fabricated, passes

The same control column, with a fabricated treatment column from a worker that did not serialize:

| item | control median | treatment median | **added** |
|---|---|---|---|
| 1 | 31.2 | 44.1 | **12.9** |
| 2 | 78.4 | 90.2 | **11.8** |
| 3 | 120.9 | 133.7 | **12.8** |
| 4 | 168.0 | 180.5 | **12.5** |
| 5 | 210.7 | 223.9 | **13.2** |
| 6 | 259.3 | 271.4 | **12.1** |
| 7 | 304.8 | 316.0 | **11.2** |
| 8 | 351.0 | 362.8 | **11.8** |

`H = 13.2 ms`. `13.2 ≤ 1000.0` → **the gate is met**. Both branches are worked here so that
neither the pass path nor the fail path is written after a number exists.

### Worked example C — fabricated, a missing reading

Suppose in treatment run 2, item 5's row is still `PENDING` when the 120-second bound elapses, so
it has no `started_at`.

```
wait_ms(treatment r2, item 5) = +infinity
```

`+infinity` sorts last. The median of `{8214.0, +infinity, 8216.8}` is the middle of the sorted
triple `[8214.0, 8216.8, +infinity]`, which is **8216.8**, and the arithmetic proceeds. Had **two**
of the three been `+infinity`, the median would itself be `+infinity`, and `H = +infinity` → fail.

---

## 10. The failure rule, and the void conditions

### The failure rule

**Each of the six runs is attempted exactly once.**

* A run that fails for **any** reason — a step that never ran, a worker that stopped early, the
  120-second bound elapsing, a database error — is recorded with what happened, and its unmeasurable
  items take `wait_ms = +infinity` in §9's medians. There is no unmeasurable bucket and no
  exclusion: an item nobody can show was served promptly was not shown to be served promptly.
* **A control run's missing `wait_ms` reads as `0.0 ms`, not as `+infinity`.** A missing control
  reading makes `added_ms` larger, which is the reading strictest on the product. Fail-closed, in
  the same direction as every other unknown in this codebase.
* **No run is re-run and none is replaced.** There is no best-of, no discard, no "that one doesn't
  count", and no seventh run. All six captures are published whatever they contain.
* A fail is published with the same prominence as a pass, including `H` and every per-item number.

### When a whole measurement may be voided

A measurement may be voided only for a condition that makes the **record itself** untrustworthy,
and only when that condition is identified and announced **before any wait has been computed or
read**:

1. The working tree is not the clean `HEAD` recorded in the capture.
2. **A second worker touched the run.** Detected two ways, both required: the harness's preflight
   (§7) finds the delayed case's first step already claimed, or the capture's
   `WORKFLOW_STEP_EXECUTED` audit rows for the nine cases of a run carry any `actor_id` other than
   that run's single worker identity.
3. The arrangement of §4.4 step 5 did not hold — the semantic step was not `PENDING`, or was not
   the oldest claimable row, or a tracked row was not `PENDING`.
4. The injecting provider recorded any number of calls other than exactly one in a run, or recorded
   a nonzero hold in a control run, or a hold materially shorter than `D` in a delayed run.
   *Amended 2026-09-16 by Amendment 1: "in a treatment run" becomes "in a delayed run", so that
   the condition covers the representative arm on the same terms. Superseded verbatim: "or a hold
   materially shorter than `D` in a treatment run."*
5. A capture is internally inconsistent: a row reported terminal that carries no `started_at` or no
   `done_at`, or a `started_at` before its own `created_at`.

A step that simply never ran is a **measurement failure** under the failure rule above, scored
`+infinity`. It is not a void. The difference is whether the record is false or merely bad.

**Not grounds for voiding, ever:** a large `H`, a small `H`, a slow control arm, a busy machine, an
unwelcome verdict, or any reason discovered by looking at the numbers.

**A voided measurement is still published**, in full, with its captures, the condition that voided
it, and the measurement that replaced it. Nothing is deleted and nothing is unpublished. A second
measurement following a voided one is published as the second measurement it is. This is the rule
the G7 voice run took from F2, applied here in advance rather than after.

---

## 11. What this measurement does not establish

Eight things, stated before any number exists so that none of them can be quietly claimed later.

1. **It does not measure a real model's latency.** The provider is the fake plus a sleep, and `D` is
   chosen, not observed. Nothing here says how long a Bedrock Nova call takes. The per-call figures
   in [semantic-benchmark.md](semantic-benchmark.md) and its companions are single-call readings
   from the evaluation harness with nothing else running, and they are not this measurement either.
2. **It does not measure the deployed host.** It runs one in-process worker against local
   PostgreSQL. The deployment is a container against RDS across a network, and its numbers would be
   different. What carries over is the *shape* of the scheduling, which is the same code.
3. **It says nothing about more than one worker.** `FOR UPDATE SKIP LOCKED` means several workers
   take different rows, so a deployment running two would queue differently. The measured
   configuration is the deployed one — one replica — and a multi-worker result is not implied by it
   in either direction.
4. **It covers the worker's step loop only.** That is where the one provider call on the durable
   path lives. The orchestrator's `select_tool` call runs in a separate client process, outside the
   worker and outside this measurement.
5. **It is not a latency SLA and not a production reliability number.** Eight items, three runs an
   arm, one machine, one fixture.
6. **It does not establish that any correction is needed, or which one.** It answers whether the
   gate is met. The requirement's *"smallest scheduling correction"* is conditional work for a
   later session, and nothing here designs it.
7. **It does not measure what a person perceives.** It measures when durable work was served. No
   screen, no voice turn and no customer message is in the window.
8. **It does not supersede or repair anything.** [g8-adversarial-proof-map.md](g8-adversarial-proof-map.md)
   §4's UNPROVEN verdict stands until a measurement exists; this document is the protocol, not the
   proof. The immutable 11/16 effect-set headline is untouched by it.

---

## 12. What has happened, and what has not

**Not taken.** No measurement run has been taken. No `wait_ms`, no `service_ms`, no median, no
`added_ms` and no `H` has been computed, printed or held privately. There is no pass and no fail.
Nothing was deployed, no AWS resource was touched, no model was called, and no product code, test,
manifest, fixture label or frozen document was changed.

**Taken: one smoke run, and its numbers are not a result.** The harness was proved to execute with
a single throwaway invocation:

```bash
uv run python scripts/with_local_env.py -- uv run python scripts/run_head_of_line.py --smoke
```

The smoke run is deliberately **not** the measurement and cannot be mistaken for it: one run per
arm instead of three, a 500 ms delay instead of 8 000, and a capture whose `label` is `smoke` and
whose `protocol` field says in words that it is not the predeclared measurement. It was also taken
on a **dirty working tree** — this document and the harness were uncommitted while it ran — which is
§10's first void condition, and is a third reason it could not have been a measurement even had
anybody wanted it to be. **Its numbers are evidence that the harness runs and are interpreted
nowhere** — not in this document, not in any other, and not by §9's arithmetic, which reads captures
labelled `measurement` and no others.

Its two captures are committed unedited at `docs/head-of-line/runs/`, and what was read off them is
structural and nothing else: the arrangement of §4.4 held in both runs, the preflight found the
delayed case's first step untouched after its two quiet seconds, the injecting provider recorded
**exactly one** call in each run, all eight tracked items carried all three of §5's instants, and
every step of all nine cases was executed by **one** worker identity. No interval was computed from
them, here or anywhere.

*Amended 2026-09-16 by Amendment 1. Superseded sentence verbatim below.*

**The next session's job**, and the whole of it: run §7's command once from a clean tree, publish
the nine captures, apply §9's arithmetic to them, and publish `H_representative` and
`H_treatment`, each with its own verdict against §8 — whatever they are.

> **Superseded 2026-09-16, verbatim:** **The next session's job**, and the whole of it: run §7's
> command once from a clean tree, publish the six captures, apply §9's arithmetic to them, and
> publish `H` with its verdict against §8 — whatever it is.

**Amendment 1 changed none of this paragraph's other claims.** No measurement run has been taken
at the moment this amendment is written, no wait, median, `added_ms` or `H` has been computed,
printed or held privately, and the smoke run's two captures remain the only thing the harness has
ever produced. The amendment was written from committed documents and one local evaluation
capture, all of which predate it; no run of any kind was taken to decide it.

---

## 13. Gaps reported, not filled

Three, each of which this document declines to solve by inventing something.

**1. `ready(i)` is a transaction start, not a commit.** The product does not record the instant a
step row became visible to another transaction, so the readiness instant used is slightly early and
every published wait is slightly long (§5). Recording a commit instant would be product code, which
this session does not write. The bias is stated and runs against the product, which is the safe
direction.

**2. The measurement cannot reach the deployed host.** There is no documented on-demand reseed on
it — the same gap [g7-ten-turn-voice-predeclaration.md](g7-ten-turn-voice-predeclaration.md) §12
records as its gap 3 — and six runs each needing a fixture reset cannot be driven against a host
that offers none. The cost is stated in §11 rather than hidden.

**3. Only one of the product's provider calls is on the measured path.** The orchestrator's
`select_tool` runs in a client process that holds no durable queue, so there is no unrelated ready
work behind it to measure. The requirement names *"delayed semantic calls alongside unrelated ready
work"*, and the worker's step loop is the only place in this build where both halves of that
phrase exist at once. Recorded so that the scope is read as a finding about the architecture rather
than as a convenience.

---

## 14. Amendment 1 — the representative arm

*Written 2026-09-16, against `54c79ac`, while no measured run existed, no wait had been computed
and no `H` of any kind had been read. Everything in this section was decided from committed
documents and one local evaluation capture, every one of which predates it.*

### 14.1 Why the two declared arms are not enough

§4.2 declares one delayed arm, at 8 000 ms. §8 predicts that the worker serialises and that `H`
lands near it, which would be a fail by a factor of eight.

The difficulty is what that published number would then mean. **8 000 ms is not a latency this
product has ever exhibited.** It was chosen, and §4.2 says so in as many words: it is eight times
the threshold so that the two scales cannot be confused, and small enough that the runs are cheap.
A fail at 8 000 ms is therefore a true statement about the worker's scheduling *given an 8-second
call*, and the only thing a reader can safely take from it is the shape — that delay propagates —
not the magnitude. If the magnitude is the published headline, the headline is a property of the
injection.

The requirement itself is what makes this matter. `new_roadmap.md:367` conditions the correction
on *"observed responsiveness"* — an operational word. A number produced by holding a call eight
times longer than the model has ever held one does not observe responsiveness; it observes the
injection.

**A third arm fixes it without weakening anything.** The control arm and the 8 000 ms arm are
untouched, the threshold is untouched, and the 8 000 ms arm's verdict will be published in full
whatever it is. The representative arm is an addition, not a replacement.

### 14.2 The figure, and exactly what it rests on

> **`D_representative` = 1 500 ms.**

**What it rests on: two recorded Bedrock calls, of the same job this measurement delays, on the
deployed host.** [p6.2-first-deployment.md](p6.2-first-deployment.md) §7.1 publishes the first
real model call PromisePatch ever made from inside a container on the deployed host:

| | |
|---|---|
| job | `interpret_utterance` — **the same job §3 names as the one delayed call on the durable path** |
| model | `us.amazon.nova-2-lite-v1:0` |
| attempts | 1, no retry |
| first call | `input_tokens: 1931, output_tokens: 104, latency_ms: 1487` |
| repeated after a further reboot | `input_tokens: 1855, output_tokens: 71, latency_ms: 1444` |

That document calls the repetition *"a durable property of the deployment and not a one-off"*.

**1 500 ms is those two readings rounded up to the nearest hundred.** 1 487 and 1 444 both sit
under it. It is not an average, not a percentile of anything, and not a number that required a
model of the distribution: it is the smallest round figure at or above every recorded reading of
this job on the deployed host. Rounding up rather than down is the fail-closed direction, which is
the direction §5 already takes for `ready(i)` and §10 already takes for a missing control reading.

**What the figure is short of, stated rather than left to be found.** `latency_ms` on that event
is Bedrock's own `metrics.latencyMs`, read by `bedrock.read_usage` — **server-side model latency
only**. The worker also holds the network round trip, the client and the response parsing, for the
whole of `provider.run`. [semantic-benchmark-rerun.md](semantic-benchmark-rerun.md) measures that
gap on the operator's machine at *"~190 ms"* at p50. So 1 500 ms is, if anything, **short of** what
the deployed worker actually holds, and the arm is lenient by that much rather than strict.

### 14.3 The derivation that was available and was not taken

There is a second body of evidence, it is larger, and it points lower. It is named here because a
figure whose alternatives are hidden is a figure chosen rather than derived.

[semantic-benchmark-rerun.md](semantic-benchmark-rerun.md), run `36c1f008de80`, 50 Nova calls
against `us.amazon.nova-2-lite-v1:0`, publishes model latency p50 / p95 / max of
**628 / 912 / 1161 ms** and end-to-end semantic latency p50 / p95 / max of **818 / 1294 / 6079 ms**
— the maximum being the run's first call, which pays for the credential chain and the TLS
handshake. [semantic-benchmark.md](semantic-benchmark.md), the earlier run, publishes 746 / 1052 /
1052 ms and 919 / 6351 / 6351 ms on 14 calls.

That run's own capture — `.eval-results/development-us.amazon.nova-2-lite-v1_0.jsonl`, which is
gitignored and local rather than committed, and is named here as what it is — carries the per-call
rows behind those aggregates. Of its 20 `interpret_utterance` calls, on prompts of 1 989 to 2 007
input tokens, the model latencies run 451 to 1 161 ms with a median of **711.5 ms**, and the
end-to-end latencies run 646 to 6 079 ms with a median of **903.5 ms**.

**Taking that instead would have given roughly 900 ms**, and under §8's serialisation prediction
900 ms would have predicted a *pass* where 1 500 ms predicts a fail. It was not taken, for three
reasons, all of them settled before any number of this measurement exists:

1. **It is the wrong environment for the question the arm asks.** The arm exists to answer whether
   this matters *in operation*. Operation is the deployed host. The benchmark ran from the
   operator's laptop.
2. **It disagrees with the deployed evidence in a direction that cannot be dismissed.** The two
   deployed readings, 1 444 and 1 487 ms, are **larger than every one of the 20 local model
   latencies**, whose maximum is 1 161 ms — on prompts of the same size (1 855–1 931 input tokens
   deployed against 1 989–2 007 local). Two bodies of evidence disagree; the one from the product's
   own operating environment is taken.
3. **Where evidence is ambiguous this repository fails closed.** Choosing the lower figure because
   it is the one that passes is exactly the move every rule in this document exists to prevent.

**This is stated plainly because it is uncomfortable.** §8 predicts one-for-one serialisation. If
that prediction holds, the representative arm's verdict is decided by whether `D_representative`
exceeds 1 000 ms, and 1 500 does. So the arm as declared is **predicted to fail**, and a figure
this repository could also have defended would have been predicted to pass. Both are written down
here, before the run, so that whichever verdict arrives, nobody has to take on trust that the
number was not tuned to produce it.

### 14.4 §8's prediction, restated per arm, before any number exists

§8 is unedited. Its prediction reads, verbatim:

> Reading `Worker.run_once` (§3), the five awaits are sequential and `_execute_one_step` holds the
> provider call inside the second of them. Nothing in that loop is concurrent, and nothing claims a
> second step while the first is in the provider. **The expected outcome of this measurement is
> therefore a fail**, with `H` near 8 000 ms.

Applied to each arm, with no new reasoning and no new threshold:

| arm | `D` | what the arm is for | **predicted** |
|---|---|---|---|
| `control` | 0 ms | establishes the baseline the other two are subtracted from | no `H`; it is the baseline, not a result |
| `representative` | 1 500 ms | answers whether this matters at a latency the real model has been recorded at | **fail**, with `H_representative` near 1 500 ms — above 1 000.0 |
| `treatment` | 8 000 ms | isolates whether delay propagates one for one, at a scale nothing could be mistaken for noise | **fail**, with `H_treatment` near 8 000 ms |

**A prediction is not a measurement**, carries no number, and settles nothing. **The threshold does
not move when the result arrives**, in either direction, for either arm. If either arm's `H` comes
back below 1 000.0 ms, that arm passes and the prediction was simply wrong, which is the only
reason to have written it down in advance.

### 14.5 What Amendment 1 does not do

* **It does not move the threshold.** §8 is not edited. `H ≤ 1000.0 ms` applies to both delayed
  arms on identical terms.
* **It does not change the control arm or the 8 000 ms arm**, their delays, their repetitions,
  their sentences, their arrangement, their instants or their void conditions.
* **It does not make this a model-latency measurement.** §11.1 stands unamended: the provider is
  still the fake plus a sleep, and no Bedrock call, credential or network egress occurs in any run.
  The arm is named *representative* because its number was taken from recorded calls, not because
  the run makes one.
* **It does not measure the deployed host.** §11.2 stands. The figure comes from the deployed host;
  the run does not. A deployed run would carry the network between the worker and the database
  too, and this one does not.
* **It does not repair, supersede or soften anything.** §11.8 stands: the UNPROVEN verdict in
  [g8-adversarial-proof-map.md](g8-adversarial-proof-map.md) §4 holds until a measurement exists,
  and the immutable 11/16 effect-set headline is untouched.
* **It designs no scheduling correction.** §11.6 stands. Whether a fail on either arm obliges the
  requirement's *"smallest scheduling correction"* is a decision for the owner after reading the
  result, and nothing here makes it.

### 14.6 What the harness had to change, and what it did not

`scripts/run_head_of_line.py` gains one constant and one row in `sequence()`. `RUNNER_VERSION` goes
to `1.1.0`, which is what that constant is for.

**Nothing in `apps/backend/src/` is touched by this amendment**, exactly as §3 requires: the delay
is still an argument to a constructor field the product already exposes, and the new arm is still
one integer. The harness still computes no wait, no median, no `H`, no threshold and no verdict,
and `scripts/tests/test_run_head_of_line.py` still asserts that it does not — including that the
string `1000.0` appears nowhere in it.
