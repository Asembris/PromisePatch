# The frozen 16-scenario effect-set manifest

**Authored in P5, before the runner exists. Frozen. Executed in P8.**

| | |
|---|---|
| Manifest | `promisepatch-effect-sets` v1.0.0 |
| File | [`docs/effect-sets/scenarios.v1.json`](effect-sets/scenarios.v1.json) |
| Manifest SHA (canonical content hash) | `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` |
| Scenarios | 16 |
| Case universe | 6 accepted orders (`ord-a` … `ord-f`) from `promise_graph.examples.hollow_oak` |
| Declared checkpoints | 60 across the suite |
| Frozen at commit | `9a7f4a899ade132507f015f65688c8be8b373827` |
| Verifier | `uv run python scripts/verify_effect_set_manifest.py` |

Recompute the identity yourself:

```bash
uv run python scripts/verify_effect_set_manifest.py
```

## Why this exists and why it is frozen now

The suite's headline number is **the first complete run against these original labels, X/16
exact effect-set matches, whatever the result**. That number means nothing unless the labels
were written down before anybody could see what the implementation would produce. So the labels
are committed first, in their own commit (`9a7f4a8`), with a published hash — and the runner that
executes them is authored later, in P7, and run later still, in P8.

This is the ordering the roadmap requires, and it is the only ordering under which a passing
score is evidence rather than a tautology.

**The chronology, stated honestly.** The deterministic engine was built in P1–P4 and already
classifies the canonical case. These labels precede the *remaining* implementation — the P7
fixtures and runner, the conversational and MCP surfaces, the effect attribution and the
counters — not the engine. What this manifest can prove is that nobody tuned the labels to
match an observed run, and that every scenario beyond the canonical one was specified before
its execution path existed. What it cannot prove is that the engine was written blind. Both
statements belong in any published account of the score.

## How the labels were kept independent of implementation output

1. **Every label is derived from the scenario's own stipulated facts**, which are written out in
   full in each scenario's `stipulated_facts` array: what the world contains, what the worker
   attested, what the customer did, what an external system changed and when. The rationale
   field then argues from those facts to the label in plain language, one entry per order per
   scenario — 96 arguments in total.
2. **No PromisePatch classification output was read, run, compared or reconciled** while
   authoring them. No engine call was made to produce a label, and no label was revised because
   an implementation disagreed.
3. **The verifier is structural, and deliberately cannot check correctness.** It validates the
   partition algebra, checkpoint ordering, effect vocabulary, the two labelling implications,
   and that every identifier exists in the canonical fixture. It imports nothing from
   `promisepatch` and nothing from `promise_graph` except the fixture module, so there is no
   path by which it could quietly turn into a mirror of the classifier.
4. **The suite reuses the canonical fixture universe rather than inventing one.** Every order,
   promise, line, recipe version, constraint and customer identifier names a real entity in
   `promise_graph.examples.hollow_oak`, and the verifier fails if one does not. This is one
   scenario universe, not a competing one, so a disagreement between manifest and engine is a
   disagreement about *judgement* rather than about which kitchen is being discussed.
5. **The labels are allowed to be wrong.** Several — the started-task case in S12, the
   uniform "an escalation holds the task" rule, the second ask in S06 — are considered
   judgements about what *should* happen, not predictions of what the code does. If the first
   run disagrees, the diff is the finding, and it is published before any repair.

## The partition algebra

```
threatened = auto_repairable ∪ consent_required ∪ blocked        (pairwise disjoint)
untouched  = case_universe \ threatened
```

Threatened is a **parent set**, never a fifth disjoint category. `untouched` is the complement
within that scenario's declared case universe — which is why the universe is declared per
scenario and asserted by the verifier rather than assumed.

| partition | meaning |
|---|---|
| `auto_repairable` | A pre-authored recovery exists and the order's recorded constraints already permit it. Nobody is asked. |
| `consent_required` | A pre-authored recovery exists but that order's constraints require the customer's permission first. |
| `blocked` | No recovery this system may take is available. It needs its owner. |
| `untouched` | The exception does not threaten this promise: unreachable, or its shortfall is already covered. |

## The ordered checkpoints

Each is a **quiescent** point — no runnable step remains — so a scenario never depends on
catching the system mid-step.

| # | checkpoint | reached when |
|---|---|---|
| 1 | `PLANNED` | Case opened, clarification answered, analysis complete. Waiting for the worker to confirm. |
| 2 | `CONFIRMED` | Worker confirmation recorded and everything it enqueued has run out. Waiting on a customer, a timer, or terminal. |
| 3 | `CONSENT_SETTLED` | The scenario's declared consent event has been delivered and drained. Where a scenario declares a fault instead of a decision, the fault lands here. |
| 4 | `SETTLED` | Terminal, or every non-terminal track is on the owner's desk. |

A scenario declares a strictly increasing subsequence of these, always beginning at `PLANNED`
and ending at `SETTLED`. S03 declares two; most declare four.

**Planning declares no operational effect anywhere in the suite.** That is asserted by the
verifier for all sixteen scenarios: analysis and planning are not permitted to have done
anything yet.

## Effects and refusals

Classifications alone would be an insufficient benchmark, because a sender fault or a replayed
webhook can leave the partition completely unchanged while changing what was authorized. S08 and
S10 are exactly that case: identical partitions to the canonical scenario, different authorized
outcomes. So every checkpoint also declares what was *done* and what was *refused*.

| effect kind | counted when |
|---|---|
| `order_amendment` | A governed recovery amendment reached the external order system and was applied there. |
| `customer_message` | An outbound message left PromisePatch towards that order's customer channel. |
| `reservation_change` | That order's reservations changed as a consequence of this case. |
| `task_hold` | That order's production task was held by this case. |
| `owner_escalation` | That order's track was escalated to the owner. |

Refusal kinds: `clarification_required`, `amendment_refused_stale_order_version`,
`approval_refused_stale_plan`, `consent_refused_foreign_sender`,
`consent_not_decided_nonliteral`, `duplicate_delivery_absorbed`,
`duplicate_amendment_suppressed`.

Effects are declared **incrementally** (`effects_added` per checkpoint); the cumulative set at a
checkpoint is the sum up to and including it. **Any (order, kind) pair absent from that sum is
expected to be exactly zero.** Omission is a claim, not a silence.

Only **incident-caused** effects are counted. An external edit a customer made in the order
system is attributed to that customer's own command and is never an incident-caused effect,
before or after the exception — S14 exists to make that distinction fail loudly if attribution
is sloppy. Case-track rows, analysis rows and audit rows record that a promise was *considered*;
they are evidence, not effects, and are never counted.

### Labelling rules applied uniformly

- **R1** — `owner_escalation` implies `task_hold` on the same order.
- **R2** — `order_amendment` implies `reservation_change` on the same order.
- **R3** — A partition says what the case *decided*. It does not move when a track later fails,
  expires or is refused; progress lives in effects.
- **R4** — A partition may change between checkpoints only where the scenario stipulates a fact
  that changed what is true. Exactly one scenario does this: S07.
- **R5** — Untouched orders receive no incident-caused operational effect of any kind, at any
  checkpoint.

R1, R2 and R5 are enforced by the verifier, so the manifest cannot silently contradict its own
stated rules.

## The sixteen scenarios

| # | id | scenario | threatened at `PLANNED` (auto / consent / blocked) | untouched | the point |
|---:|---|---|---|---:|---|
| 1 | S01 | single-ingredient canonical | A / B / C, D | 2 | One observation, three different authorities. |
| 2 | S02 | whole-delivery counterfactual | — / — / A, B, C, D | 2 | Scope changes substitute feasibility, not just breadth. |
| 3 | S03 | no dependent promises | — / — / — | 6 | A true exception that threatens nobody still produces a case. |
| 4 | S04 | substitute unavailable | — / — / A, B, C, D | 2 | Same partition as S02 from different physical facts. |
| 5 | S05 | constraints block substitution | A / B / C, D | 2 | The block is provably the constraint, not scarcity. |
| 6 | S06 | stale approved order version | A / B / C, D | 2 | A recorded YES plus a moved order is zero amendments. |
| 7 | S07 | stale approved stock state | A / B / C, D | 2 | The only legitimate partition change: B falls to `blocked`. |
| 8 | S08 | foreign sender | A / B / C, D | 2 | Identical partition, nothing authorized, and Ahmed's order still zero. |
| 9 | S09 | nonliteral apparent assent | A / B / C, D | 2 | "Strawberries work" decides nothing. One prompt, then a literal YES. |
| 10 | S10 | replayed approval webhook | A / B / C, D | 2 | Two deliveries, one decision, one amendment. |
| 11 | S11 | external edit removes dependency **before** | A / B / C | 3 | The demo order of events: Lena leaves the affected set. |
| 12 | S12 | external edit adds dependency **before** | A / B / C, D, E | 1 | The mirror image: Ahmed enters it. |
| 13 | S13 | related external edit **after** exception | A / B / C, D | 2 | The automatic track is refused and escalates rather than claiming success. |
| 14 | S14 | unrelated external edit **after** exception | A / B / C, D | 2 | A busy order book must not create a false positive. |
| 15 | S15 | crash after external acceptance | A / B / C, D | 2 | Exactly one amendment. Two fails as surely as zero. |
| 16 | S16 | restart while waiting for consent | A / B / C, D | 2 | The restart is invisible in the result and visible in the worker identity. |

Orders: **A** Priya (preapproved alternative) · **B** Tomas (ask before visible change) ·
**C** Okafor-Reyes wedding (no substitution) · **D** Lena · **E** Ahmed · **F** Cafe Marlow.

## The pass rule

A scenario passes **only** on:

- exact order-set equality for all four partitions at **every** declared checkpoint, **and**
- exact equality of the cumulative effect multiset at every declared checkpoint, including the
  zeros implied by absence.

A missing, extra or misclassified order or effect **fails the entire scenario**. Rationale,
notes and refusal fields are diagnostic and are not pass criteria — a run that reaches the right
answer for a recorded wrong reason still passes the scenario and should still be discussed.

## What happens next, and what may not

- **P7** authors the executable fixtures and runner against this manifest, in slack, without
  changing label semantics. It reuses the existing engine, workflow and simulator fixtures.
- **P8** executes it. The first complete scored run is the headline, **whatever the result**,
  captured immutably with this manifest SHA, the implementation SHA, the runner version, the
  command, the outputs and every diff *before* repairs. If a scored run happens during P7, that
  earlier run is the first run; P8 does not reset the history.
- Every fix gets its own SHA and its own separately published rerun. G8 requires 16/16 on the
  release candidate only. **The headline is never replaced by the repaired score, and no failing
  scenario is ever removed.**
- Harness failures are disclosed and count as nonpasses in the first-run denominator.
- A genuine label error receives a separately versioned, explained correction and a separate
  result. The original labels and the original headline are immutable. A "correction" that
  moves a label towards observed output, without an argument from the stipulated facts that
  stands on its own, is exactly the thing this freeze exists to prevent.

## Disclosure

These labels and this suite are **developer-authored, finite and public**. They are not an
independently validated benchmark and not a held-out one — the whole manifest is readable in
this repository, by design. Reproducibility makes the claims inspectable; it does not establish
universal correctness, real-world demand or return on investment. The engine predates the
labels. Say all of that wherever the number is published.
