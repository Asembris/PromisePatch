# The head-of-line disposition: the correction is declined

*Written 2026-09-17, after [the measurement](g8-head-of-line-measurement.md) and separately from
it. That document is left byte-identical, as is
[its predeclaration](g8-head-of-line-predeclaration.md). This one decides the one thing the
measurement deliberately left to the owner, and decides nothing else.*

**No scheduling correction was made. No production code was changed by this decision, and none
was changed by the measurement either.** The roadmap's conditional is reached and the correction
is **declined** — not overlooked, not deferred for want of a reading, not lost between two
documents.

---

## 1. What is being decided

The roadmap's bullet, verbatim:

> *"Measure delayed semantic calls alongside unrelated ready work. No held DB transaction does not
> prove no head-of-line delay. Make the smallest scheduling correction only if observed
> responsiveness misses the gate."*

The first sentence is discharged: nine runs, three arms, one invocation, all nine captures
published unedited. The second is discharged in the negative — the measurement explicitly refuses
to let the no-held-transaction probe stand in for it. The third is a **conditional**, and the
measurement's §5 satisfies its antecedent on both delayed arms: `H_representative = 1545.8 ms`
and `H_treatment = 8173.4 ms` against `H ≤ 1000.0 ms`.

So the condition is met and a correction is permitted. **Permitted is not obliged.** §8 of the
measurement says the decision is the owner's after reading it, and this document is that decision.

## 2. The verdict rests on a figure this repository's own evidence disagrees about

The threshold did not move and is not in question: 1000.0 ms, taken from the worker's own
`IDLE_INTERVAL`, fixed before the harness existed. What decides the representative arm is
therefore `D_representative` alone, and `D_representative` is a **derived** number, not a measured
one. The predeclaration said so before any result existed, and published both derivations that
were available:

| derivation | reading | n | environment |
|---|---|---|---|
| taken (§14.2) | 1 487 ms and 1 444 ms → **1 500 ms**, rounded up | **2** | the deployed host, a real Bedrock call on the instance role |
| available and not taken (§14.3) | 20 `interpret_utterance` end-to-end calls, median **903.5 ms**; the 50-call benchmark's p50 of 818 ms beside it | **~20** | the operator's laptop |

Under the one-for-one propagation the measurement then observed, those two derivations **predict
opposite verdicts**: 1 500 ms predicts a fail, and roughly 900 ms predicts a pass. The
predeclaration wrote that down, in those words, before the run, precisely so that this moment
could not be argued either way after the fact.

The reasons it took the deployed pair are good ones and are not withdrawn here: it is the right
environment for a question about operation, it disagrees with the local body in a direction that
cannot be waved off — both deployed readings exceed *every one* of the twenty local model
latencies — and where evidence is ambiguous this repository fails closed. **Failing closed is the
right rule for deciding what to publish. It is the wrong rule for deciding what to rewrite.**
Publishing the pessimistic reading costs nothing if it is wrong. Re-architecting the worker's step
loop on it costs a change to the one loop every durable effect in this product passes through.

And the pessimistic reading is `n = 2`. Two calls, on one host, on one day, against roughly twenty
that say something else. That is not enough to call the local body wrong; it is exactly enough to
call the question **open**. **Correcting the worker's scheduling on the weaker of two disagreeing
readings is over-fitting** — tuning a concurrency design to two samples, when the same design
measured against the larger sample would have been declared fine.

## 3. The finding that does not depend on the figure, and is kept

Nothing above touches what the measurement actually established, which is not a latency at all:

> **`H` exceeds the injected delay by 2–3 % across a five-fold range of `D`, with service time
> flat.** `H_representative` is 45.8 ms above its 1 500 ms delay (3.1 %); `H_treatment` is 173.4 ms
> above its 8 000 ms delay (2.2 %). Per-item service time is 15.6–16.4 ms median in every arm,
> including the control.

That is a **structural** result, and it is the durable one. It says the worker's step loop
serialises: a semantic call held open for `D` does not slow the items behind it down, it simply
makes each of them wait `D` longer. **Delay propagates one for one to everything queued behind
it**, over a range of `D` from 1 500 to 8 000 ms, with the items' own execution unchanged. §8 of
the predeclaration predicted exactly this from reading `Worker.run_once`, before any instant
existed, and the numbers hold the prediction tightly.

**This finding survives any choice of `D`.** A reader who prefers the local derivation reads it
as: unrelated ready work waits about 0.9 s longer. A reader who prefers the deployed pair reads
it as: about 1.5 s longer. They disagree about the gate and agree completely about the mechanism.
The mechanism is what a future correction would have to address, and it is now recorded with
numbers behind it rather than inferred from source.

## 4. Why the correction is declined rather than made small

The roadmap says *smallest*, and the honest reading of what "smallest" would mean here is not
small. The worker's loop is sequential end to end; there is no scheduling knob to turn, so the
correction is a change to how steps are claimed and executed concurrently. That loop is the single
path through which every governed write, every dispatched effect and every state transition in
this product passes, and its serial shape is load-bearing for things measured elsewhere — the
`FOR UPDATE SKIP LOCKED` claim, the one-effecting-call-per-turn rule, the crash-point proofs at
`crash.AFTER_EXTERNAL_SUCCESS`. Changing it before release, to fix a wait whose size two bodies of
evidence disagree about by a factor the gate straddles, is the larger risk of the two.

Three smaller facts weigh the same way, and are stated rather than left to be found:

* **The measured configuration is one worker.** With a second replica, `FOR UPDATE SKIP LOCKED`
  gives it different rows, and a held semantic call blocks one worker rather than the queue. The
  deployment runs one replica today, so the measurement is of the deployed shape — but the
  cheapest correction, if one is ever wanted, is operational rather than architectural, and it is
  not being taken here either.
* **Nothing waiting behind a semantic call is a person.** §11 of the predeclaration bounds this to
  the worker's step loop. The orchestrator's `select_tool` runs in a separate client process with
  no durable queue behind it, so a worker's conversational turn is not what queues.
* **The gate is the worker's own word for "promptly", not an SLA.** `IDLE_INTERVAL` is how long
  ready work may reasonably sit before the loop looks again. Exceeding it by half a second on a
  background step is a responsiveness cost, and the measurement is careful never to call it
  anything more.

## 5. What this disposition is not

* **It is not a claim that there is no head-of-line delay.** There is, it was measured, it is
  published, and both arms failed the gate. Nothing here softens `FAIL`.
* **It is not a threshold change.** §8's 1000.0 ms is untouched, before and after.
* **It is not a re-reading of the measurement.** Every number quoted above is copied from it. No
  run was re-run, re-read, excluded or re-derived, and the arithmetic was not redone.
* **It is not a correction designed and shelved.** §11.6 of the predeclaration declined to design
  the correction before the measurement and §8 of the measurement declined after; this document
  declines too. What §4 above names is the *shape* the work would have, so that "declined" is a
  decision with a cost attached rather than a word.
* **It does not close G8.** Bullet four's measurement requirement is discharged by the measurement
  document; this one discharges its conditional. The rest of G8 is untouched, the immutable 11/16
  effect-set headline is unchanged, and both holdouts stay sealed.

## 6. Revisit if

* A larger body of **deployed** semantic latencies exists. The whole of §2 is an argument about
  `n = 2`. Ten deployed calls with a median above 1 000 ms would settle it, and the correction
  should then be made rather than argued about again.
* A person, rather than a background step, is ever put behind the worker's semantic call. The
  gate's tolerance for a 1.5-second wait is not the same question then.
* A second worker replica is run, which changes the measured configuration and makes the
  measurement's §7.3 disclosure load-bearing rather than a caveat.

---

*Nothing was built, run, deployed or called by this decision. No AWS resource was touched, no
model was called, no test was weakened, skipped, xfailed or deselected, no manifest, fixture label
or frozen document was changed, and no published run capture was altered.*
