# Diagnosing the five failing effect-set scenarios

**Diagnosis only. Nothing here is repaired, rerun, reclassified or decided.**

| | |
|---|---|
| Diagnoses | the five `FAIL` verdicts of the first scored run |
| Against | capture [`20260915T163255509125+0000-scored.json`](effect-sets/runs/20260915T163255509125+0000-scored.json) |
| Implementation SHA it diagnoses | `e81b5aa3af101847fdceb0f0af6cb515909d40b2` |
| Manifest | `promisepatch-effect-sets` v1.0.0, SHA `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` |
| Headline it does not touch | **11/16**, immutable |
| Root causes found | **five**, of which **one** is left undecided |
| Scenarios repaired | **none** |

The scored run's headline stands exactly where it is. This document names causes and classifies
them; the correction process in
[`effect-set-run-protocol.md`](effect-set-run-protocol.md#if-a-frozen-label-turns-out-to-be-wrong)
governs what may follow, and none of it happens here.

## How this was done, and what it did not use

Every cause below was traced statically: from the diff in the capture, to the function that
produces the observed value, to the frozen text that produces the expected one. No scenario was
executed, no database was touched, and no score of any kind was computed — the diffs were already
reproduced twice, published in [`effect-set-harness.md`](effect-set-harness.md) before the run and
again by the run itself, so execution could only have re-observed what the capture already
records.

The decisive evidence is the frozen `PROMISEPATCH_PRODUCT_SPEC.md` and `ARCHITECTURE_PLAN.md`,
which are authoritative whenever present and which the harness's own published analysis did not
quote. Three of the five causes are settled outright by a sentence in §23 or §14.4 that neither
the manifest nor the implementation had been read against. That is why this document's
conclusions differ from the harness document's provisional framing in three places, each noted
where it occurs.

## The five causes, and the diffs each explains

| | cause | scenarios | classification |
|---|---|---|---|
| **A** | An approval that expires unanswered escalates without holding the kitchen work | S08, and S06 downstream | **IMPLEMENTATION DEFECT** |
| **B** | `hold_tasks` holds only a `SCHEDULED` task, never a `STARTED` one | S12 | **UNDECIDED — needs the owner** |
| **C** | A re-planned case waits for a confirmation that nothing bounds | S06, S07 | **IMPLEMENTATION DEFECT** |
| **D** | A refused amendment goes `STALE` with no route onward, and the case can never resolve | S13 | **IMPLEMENTATION DEFECT** |
| **E** | §14.4's "your order changed" message to the customer is not implemented at all | S06 | **IMPLEMENTATION DEFECT** |

Five causes, not the four the harness document's grouping implies. Its "one disagreement wearing
two hats" for S06 and S07 is two separate causes: S07 is cause **C** alone, and S06 is **C**,
**E** and **A** stacked, which is why S06 is the only scenario of the sixteen that no single
repair fixes.

---

## Cause A — the expiry path escalates without holding

### The code that produces the observed value

`promisepatch.domain.approvals._close_request` (`approvals.py:1415`) is the one ending for an
approval request that can no longer be answered; expiry and undeliverable transport both arrive
here. It escalates the track at `approvals.py:1461`:

```python
await set_track(write, track=track, state=TRACK_ESCALATED)
```

and never calls `hold_tasks`. Its sibling `_escalate` (`approvals.py:1490`) takes a `hold` flag
and does hold, at `approvals.py:1522` — but only one of its two call sites passes `hold=True`,
the §13.6 refusal to ask into a closed window at `approvals.py:511`.

S08's drive asserts the request was genuinely left open before expiring it
(`test_effect_sets.py:796`), so `_expire` → `_close_request` is the path taken. The census reads
`ProductionTask.held_by_case_id`, which only `hold_tasks` ever writes; nothing wrote it, so the
count is zero.

### The rule that produces the expected value

The manifest's labelling rule R1 — "Every escalation to the owner holds that order's production
task" — and S08's `SETTLED` effects, `ord-b owner_escalation 1` and `ord-b task_hold 1`.

R1 is not the strongest thing here, and it is not what settles this. **The frozen spec names this
exact path.** §23's failure-semantics table:

> | **Customer does not reply** | Deadline (≤24 h and ≥60 min before task start) → EXPIRED → ESCALATED; task HELD; owner notified on screen. |
> | **Approval expires** | As "customer does not reply". … |

and the row immediately above them, which is S08's own fault injection:

> | **Unauthorised actor attempts approval** | Sender identity ≠ order's approval channel → discarded, `UNAUTHORIZED_APPROVAL_ATTEMPT` audited, owner notified, track keeps waiting. |

Read in sequence, those three rows *are* S08: the foreign YES is discarded and the track keeps
waiting; Tomas never answers; the deadline passes; the track escalates **and the task is HELD**.
The label is the spec transcribed.

### The case that the implementation is wrong

The spec names the hold, on this path, in a table whose whole purpose is to fix failure
behaviour. The implementation performs the escalation half of that row and omits the other half.
There is no reading of "task HELD" in that cell that is satisfied by leaving the task
`SCHEDULED`.

The rationale is also identical to the one the implementation already accepts for the
closed-window case: a customer who was asked and did not answer in time and a customer who could
not be asked at all are in precisely the same position — nobody is coming, and the kitchen should
not start a cake nobody can ask about. `_close_request`'s own docstring says exactly that, "the
customer's position is identical in both", and then does not act on it.

### The case that the label is wrong

The strongest version: holding is a write, and §13.6 is careful to call the closed-window hold
"the only consequence a refusal to ask has" — a deliberately singular phrase. One could argue the
spec grants the hold where PromisePatch *chose not to contact* somebody, and that once a customer
has been asked, the deadline passing is the customer's silence rather than the system's refusal,
so the honest posture is an escalation and a person deciding.

And R1 is demonstrably broader than the spec elsewhere. Of the six escalation paths in the
codebase, the spec names a hold on only two — §13.6's closed window and §23's expiry. A literal
NO escalates with no hold in §23's "Customer rejects recovery" row (`approvals.py:1190`), and a
second non-literal reply escalates with no hold in §13.6 (`approvals.py:1093`), both correctly,
and R1 would wrongly require a hold for each.

That argument establishes that R1 is over-broad. It does not reach this cause, because on *this*
path R1 and the spec agree, and the spec is explicit. R1's over-breadth would matter if a
scenario declared a hold on a decline; none of the sixteen does.

### Classification: **IMPLEMENTATION DEFECT**

Not on R1's authority, on §23's. The frozen spec states the hold on the expiry path in so many
words. This supersedes the harness document's framing of S08, which offered "either R1 is right
and the expiry path should hold, or holding is specific to never having asked" as two live
readings. The spec answers it, and the second reading is not available.

### Consequence

**A person is not told, and a physical resource is consumed.** The kitchen's production task for
Tomas's cake stays `SCHEDULED` after the case has given up on him. The owner does see the
escalated promise on the case workspace — `needs_owner_attention` is set and the track renders as
`ESCALATED` with the owner as its action owner — so this is not a silent abandonment. What is
missing is the physical brake: the bakery may begin, or complete, a raspberry cake it has just
concluded it cannot make correctly and cannot get permission to change. Of the five causes this
is the one with the most direct route to wasted ingredients and a wrong cake in a box.

### Blast radius

- **Within the sixteen:** S08 becomes an exact match. S06 gains its missing `task_hold` **only if
  causes C and E are repaired first** — S06's fresh ask is never sent today, so there is no
  request for this path to expire. No currently passing scenario declares an expiry;
  `expire_open_ask` is called by exactly two scenarios, S06 and S08
  (`test_effect_sets.py:705`, `:796`).
- **Outside the sixteen:** no existing test asserts the *absence* of a hold on expiry.
  `test_an_unanswered_request_expires_when_its_timer_fires` (`test_customer_approval.py:842`) and
  `test_an_expired_request_hands_the_case_on_as_well` (`:860`) assert the request state, the
  track state, the audit type and the case state, and never read `physical.tasks()`. The repair
  is purely additive against the current suite.
- **A hazard worth naming:** `_close_request` also serves undeliverable transport, not only
  expiry. Holding there too is arguably right by the same reasoning and is *not* something §23
  states. A repair should decide that deliberately rather than inherit it from the shared
  function.

### What a repair would touch

**Domain, small.** One call to `hold_tasks` inside `_close_request`'s governed block, and the
held count carried onto the outcome's event payload and result the way `_escalate` already does
it at `approvals.py:1522`. No manifest change, no census change, no worker change.

---

## Cause B — a started task cannot be held

### The code that produces the observed value

`promisepatch.domain.recovery.hold_tasks` (`recovery.py:634`) updates only tasks whose state is
`SCHEDULED`, at `recovery.py:654`:

```text
ProductionTask.state == "SCHEDULED",
```

S12 stipulates that `ord-e`'s task is already `STARTED` and does not change it. That state is not
something the scenario arranges: it is in the frozen fixture itself, at `hollow_oak.py:692`
(`TaskState.STARTED`), and `ord-e` is the only order of the six whose task is not `SCHEDULED`.
The update matches zero rows, `held_by_case_id` stays null, and the census records zero.

The escalation itself is produced correctly, by `recovery.confirm`'s blocked-track loop at
`recovery.py:492-494`, which is why S12's `owner_escalation` matches and only the hold diverges.

### The rule that produces the expected value

R1, and S12's `CONFIRMED` effects, which declare `ord-e owner_escalation 1` and `ord-e task_hold
1`. S12's own rationale states the intent without hedging:

> "The started task is stipulated and does not change the label: with no valid option, the
> promise needs its owner whatever the kitchen has begun."

The spec, §13.5:

> A BLOCKED track never triggers a customer message and never touches the order. … The production
> task is placed on `HELD` so the kitchen does not start a cake that cannot be finished; this is
> the one write BLOCKED performs, and it is reversible by the owner.

### The case that the implementation is wrong

§13.5's rule carries **no task-state qualifier**. It says the production task is placed on `HELD`,
full stop, and calls that the one write a blocked track performs. The `SCHEDULED` predicate is an
unstated narrowing that appears nowhere in the frozen text. `TaskState` has a `HELD` member and
nothing in the model forbids reaching it from `STARTED`, so the narrowing is not forced.

And the purpose survives the transition. A cake that has been started and cannot be finished
correctly is *more* urgent to stop than one that has not begun: every further minute of work on
it is spent on something the system has just concluded it cannot deliver as promised. Reading "so
the kitchen does not start" as licensing the kitchen to *continue* inverts the sentence's intent
to save the narrower of two readings of one verb.

### The case that the label is wrong

The purpose clause is the rule's own stated reason, and it is about *starting*. A hold on a
`SCHEDULED` task prevents work; a hold on a `STARTED` task cannot un-bake anything. What it does
instead is make a claim about a physical fact — that this task is not in progress — which is
false, and this project's own core invariant is that physical facts are authoritative
independently of recovery authorization. There is a real reading in which the honest answer for a
started task is an escalation with no hold, precisely *because* the system may not overwrite a
physical state it did not cause.

That reading is materially strengthened by something the harness document did not surface. The
hold is reversible, and the reversal, `withdrawal._release_holds` at `withdrawal.py:590`, restores
unconditionally to `SCHEDULED` (`withdrawal.py:609`):

```python
.values(state="SCHEDULED", held_by_case_id=None)
```

The `HELD` row does not remember what the task was before the hold. So under a repaired
`hold_tasks`, a started task held by a case and then released by a withdrawal would come back as
`SCHEDULED` — the system would have silently rewritten a physical fact, turning a cake that was in
the oven into a cake that has not been started. That is not a side effect of the repair; it is the
repair colliding with a real gap in the model.

### Classification: **UNDECIDED — needs the owner**

The frozen rule is unqualified and the frozen rationale is not, and they point opposite ways. The
manifest predicted this disagreement in its own disclosure and named both halves of it, and the
protocol pre-registered it as the first case under the no-repair rule. Nothing found here breaks
the tie; what is new is that the repair is not the one-line predicate change it appears to be,
which is a cost to weigh rather than an answer.

It is listed as a question for the owner at the end of this document.

### Consequence

**Bookkeeping, unless the repair is taken — in which case a physical claim can become wrong.**
Today `ord-e` is escalated to the owner, appears on the workspace with `ESCALATED`, an owner and a
next action, and the kitchen carries on with a cake nobody can repair. Nobody is misinformed: no
screen claims the task is held, because it is not. The cost is that the owner learns about a
blocked promise while work on it continues, and has to stop it by hand.

The mirrored consequence of repairing it naively is worse in kind if not in frequency: a
withdrawal would report a started task as scheduled. That is the one category this project treats
as never acceptable.

### Blast radius

- **Within the sixteen:** S12 only, and only the `task_hold` rows. `ord-e` is the sole `STARTED`
  task in the fixture, and it is reachable from a track in exactly one scenario — S12, the only
  one where Ahmed's order is in the threatened set. In every other scenario `ord-e` is
  `UNAFFECTED`, has no track, and `hold_tasks` is never called for it.
- **Outside the sixteen:** `test_blocked_tracks_escalate_and_their_kitchen_work_is_held`
  (`test_recovery_execution.py:229`) asserts `set(moved) == {TASK_C, TASK_D}` exactly. Widening
  the predicate does not add `TASK_E` there, because no track in that case reaches `ol-e`. The
  test is safe. `test_a_closed_window_holds_the_kitchen_work` (`test_customer_approval.py:234`)
  is likewise unaffected — `ol-b`'s task is `SCHEDULED`.
- **The real risk is `DONE`.** Removing the predicate rather than widening it to
  `state.in_(("SCHEDULED", "STARTED"))` would hold finished tasks, which is plainly wrong and
  which the fixture would not catch, because it contains no `DONE` task.

### What a repair would touch

**Domain, small in code and not small in design.** One predicate at `recovery.py:654`, plus — if
the withdrawal hazard above is to be honoured — a way for a held task to remember the state it
came from, which is a schema column, a migration, a change to `hold_tasks` and a change to
`_release_holds`. Alternatively **the manifest**, under a separately versioned correction, with an
argument from S12's stipulated facts alone.

---

## Cause C — a re-planned case waits for a confirmation that nothing bounds

### The code that produces the observed value

`promisepatch.domain.analysis._replan` (`analysis.py:598`) returns a re-planned case to `PLANNED`,
at `analysis.py:661`:

```python
moved_to = CASE_PLANNED if plan is not None else CASE_RECONCILING
```

`_plan_for` (`analysis.py:792`) never returns `None`, and `_record_for` (`analysis.py:416`) gives
any non-`UNAFFECTED` classification — including `BLOCKED` — the state `PENDING`. So every re-plan
that finds the promise still threatened lands at `PLANNED` with a `PENDING` track, whatever it
concluded. Its own docstring says so at `analysis.py:619-620`:

> "If the new plan still needs asking, it is asked again, from `PLANNED`, after a worker has
> confirmed it."

Sending the fresh ask, escalating a blocked track and holding its task are all consequences of
`recovery.confirm` (`recovery.py:460` onward). No second confirmation arrives in S06 or S07, so
none of them happens. The case is quiescent, and the harness reads it there.

**And nothing ever ends that wait.** The only timer the domain arms is the approval deadline, at
`approvals.py:1548`; the only other `ArmTimer` in the tree is a test handler
(`handlers.py:160`). The worker's cycle (`worker.py:104`) is driven by timers, steps, the outbox,
the inbox and the order mirror, and sweeps no track state. A re-planned case at `PLANNED` waits
for a human, with no bound, for ever.

### The rule that produces the expected value

S07's `SETTLED` effects declare `ord-b owner_escalation 1` and `ord-b task_hold 1`; S06's declare
the same. S07's rationale: "the re-plan finds no valid option at all" — followed by §13.5's
escalation and hold for a blocked promise.

The frozen text the implementation is measured against here is **§14.1's own description of
`PLANNED`**:

> | PLANNED | Options validated; plan summary produced; awaiting worker "yes". **Auto-escalates to owner after 10 min.** | Yes |

and `ARCHITECTURE_PLAN.md:448`, which makes it a persisted row rather than a nicety:

> All deadlines are rows in `timers` created in the same transaction as the state they belong to:
> approval deadline (`kind = APPROVAL_DEADLINE`), clarification auto-cancel (10 min), **plan
> auto-escalation (10 min)**, step retry (`next_attempt_at`).

### The case that the implementation is wrong

The confirmation gate itself is **right**, and this is worth stating plainly because it is the
part that looks wrong at first glance. §14.1 defines `PLANNED` as "awaiting worker 'yes'", and
§14.2's re-planning outcome says "case returns to PLANNED for that track only". A re-planned case
sitting at `PLANNED` waiting for a worker is the spec, and a repair that made a re-plan act on its
own authority would be deleting a human authorization the architecture requires.

What is missing is the **bound**. The same sentence that defines `PLANNED` also says a case in it
auto-escalates to the owner after ten minutes, and the architecture lists that deadline as one of
four persisted timer kinds. Neither exists. The consequence is not "the case waits for a person",
which would be correct; it is "the case waits for a person indefinitely, and if nobody looks,
nothing ever happens to Tomas's promise". With the timer present, S07's re-planned blocked track
reaches the owner's desk with its task held — which is its frozen label — without any re-plan ever
acting unconfirmed.

This supersedes the harness document's framing of S06 and S07, which posed the choice as "either a
re-plan's consequences should follow from the revalidation that caused it — or a plan nobody has
seen must never act, in which case the labels are a checkpoint early". There is a third
possibility it did not consider, and it is the one the frozen documents describe: the plan is never
acted on unconfirmed **and** the wait is bounded, so the label is reachable without weakening the
authority boundary at all.

### The case that the label is wrong

The strongest version: the ten-minute auto-escalation is a real omission, but it is a *timer*, and
the manifest's checkpoints are defined by quiescence rather than by elapsed time — "`SETTLED`: the
case is terminal, or every track that is not terminal is on the owner's desk. Drained to
quiescence." A pending timer is arguably outstanding work, so a case with an unfired plan timer has
not reached `SETTLED` at all, and the label describes a state ten minutes further on than the
checkpoint the harness reads. On that reading the labels are not wrong so much as measuring a
different instant, and the honest correction is to the checkpoint rather than to either side.

That is a real objection to *how a repair would be observed*, and the harness would need to advance
the clock the way `expire_open_ask` already does for approval deadlines. It is not an argument that
the current behaviour is correct: an unbounded wait is not a defensible resting state under any
reading of §14.1.

### Classification: **IMPLEMENTATION DEFECT**

Not in the confirmation gate, which is correct and should stay. In the absence of §14.1's plan
auto-escalation and `ARCHITECTURE_PLAN.md`'s `timers` row for it, which leaves a re-planned case
waiting without limit.

### Consequence

**A promise is silently abandoned — but not invisibly.** The case sits at `PLANNED` with Tomas's
track `PENDING`. The workspace renders that as `PromiseState.PLANNED`, owner `ActionOwner.YOU`,
next action "Read the plan and confirm it, or leave it as it is." (`status_view.py:428`, `:495`,
`:519`), and the orchestrator offers `confirm` in that phase. So a worker who opens the case is
told, correctly, that there is a plan to confirm.

A worker who does not open it is told nothing further, ever. Tomas approved a change, the world
moved, his approval was correctly refused — and then his promise stops moving, with no deadline, no
escalation and no second message. In S07 the kitchen also keeps its scheduled task for a cake whose
recovery has just been found impossible. The spec's ten-minute rule exists precisely to stop that,
and it is not there.

### Blast radius

- **Within the sixteen:** S07 becomes an exact match. S06 gains its `owner_escalation` and, via
  cause A, its `task_hold`; it still fails on cause E. Re-planning is reached only from
  `revalidation._go_stale` (`revalidation.py:687`, the sole producer of a `REPLAN_TRACK` successor,
  at `revalidation.py:743`), which only S06 and S07 reach. No currently passing scenario re-plans.
- **The harness would have to move.** A timer-based escalation does not fire at quiescence, so
  S06's and S07's `SETTLED` readings would need the plan deadline advanced explicitly, exactly as
  `expire_open_ask` advances an approval deadline today. That is harness work in a scenario drive,
  and it is the one repair on this list that cannot be observed without it.
- **Every case that reaches `PLANNED` changes**, not only re-planned ones — including the canonical
  demo case, which today sits at `PLANNED` indefinitely waiting for a worker to confirm. A
  ten-minute auto-escalation would escalate it while a demo is being narrated. That is a genuine
  and non-obvious risk to currently passing work, and to `docs/demo-case-recipe.md`.

### What a repair would touch

**Domain and worker, medium.** A `timers` row armed when a case enters `PLANNED` (two or three call
sites), a fire handler that escalates the case's live tracks with §13.5's hold, the `TIMER_NOOP`
guard for a case that has since been confirmed, and the harness drives for S06 and S07. It is the
largest of the five and the only one that changes behaviour for cases that currently pass.

---

## Cause D — a refused amendment has nowhere to go, and the case can never resolve

### The code that produces the observed value

`promisepatch.domain.recovery._apply` (`recovery.py:770`) recomputes the fingerprint before writing
anything and, on a mismatch, calls `mark_stale` at `recovery.py:812`. That is S13 exactly: Priya's
own edit moved `ord-a`'s external version, the fingerprint no longer matches, and no amendment is
sent. **The part S13 exists to test passes** — her declared amendment count is zero and the
observed count is zero.

`recovery.mark_stale` (`recovery.py:1052`) sets the track `STALE`, escalates nothing, holds
nothing, **and returns no successor**. Compare `revalidation._go_stale` (`revalidation.py:687`),
which reaches the same track state and enqueues a `REPLAN_TRACK` step at `revalidation.py:743`. Of
the three paths that produce a `STALE` track, only the revalidation one has a route onward.

And `STALE` is **not terminal** — `db/types.py:106` lists `UNAFFECTED`, `RECOVERED`, `ESCALATED`,
`WITHDRAWN` and `LINKED`, and `cases.resolvable` (`cases.py:254`) is false while any non-terminal
track exists. `_settled_reconciling`'s own docstring (`cases.py:233`) spells it out: "a track still
`PENDING`, `APPLYING`, `WAITING_FOR_CUSTOMER` or `STALE` is a non-terminal track". The worker
sweeps no track states. So S13's case reaches `RECONCILING`, finds itself unresolvable, and **stays
there permanently**.

### The rule that produces the expected value

S13's `CONFIRMED` effects declare `ord-a owner_escalation 1` and `ord-a task_hold 1`, and its
rationale says what for:

> "The order has moved, so the amendment is refused on its version rather than applied to a cake
> nobody planned for. **The track goes to the owner instead of claiming success.**"

The frozen spec, §23, names this path and only this path:

> | **Recovery invalid before execution** | Revalidation fails → STALE → re-plan; nothing written. **Applies equally to AUTO tracks: validation is re-run at APPLYING, not only at PLANNED.** |

That second sentence is S13 verbatim — an `AUTO_RECOVERABLE` track whose validation is re-run at
`APPLYING` and fails. The spec's answer is `STALE` **→ re-plan**. The implementation delivers the
`STALE` and not the arrow.

### The case that the implementation is wrong

It fails both readings at once, which is what makes this the clearest of the five after cause A.

Against the **manifest**, the track never reaches the owner: `owner_escalation` is zero because the
census reads the track state and `STALE` is not `ESCALATED`.

Against the **spec**, which is the stronger charge, §23 requires a re-plan from exactly this path
and there is no code that can produce one. `mark_stale` emits no successor; the sole producer of
`REPLAN_TRACK` is in `revalidation.py`, on a path `_apply` does not take.

And the resting state is not a resting state. The case cannot resolve, cannot be reconciled, and
cannot be moved by any timer, step or sweep. Priya's promise stops, and her case stops with it. A
non-terminal track that nothing can ever advance is the "parked at a boundary with nothing enqueued
to carry it off again" failure that `cases.case_successors`'s own docstring cites §44 to forbid.

### The case that the label is wrong

The strongest version, and it is not weak. §23's "Recovery invalid before execution" also says
"**nothing written**", and a task hold is a write. `mark_stale`'s docstring cites §23 for exactly
that, and the behaviour is deliberately tested:
`test_a_plan_whose_inputs_moved_produces_no_external_effect`
(`test_recovery_execution.py:920`) asserts `track_a.state == recovery.TRACK_STALE` and that no
effect and no adapter call occurred. So `STALE` is a designed outcome with a spec citation and a
test, not an oversight — and the manifest's five effect kinds simply have no word for it, which
would make the label an artefact of the vocabulary rather than a claim about behaviour.

There is a further point in the label's disfavour. The spec's answer is `STALE → re-plan`, and the
manifest's answer is `ESCALATED + HELD`. **These are not the same answer.** The label matches the
spec only if the re-plan then finds no valid option — which is plausible for a doubled raspberry
order in a case whose raspberries did not arrive, but is not something this diagnosis verified, and
it depends on stock arithmetic at that instant. The manifest may be right about where the promise
ends up and wrong about the route, or right about both, and this document cannot tell which without
executing.

### Classification: **IMPLEMENTATION DEFECT**

Because the implementation matches *neither* the label nor the spec. §23 requires a re-plan from the
`APPLYING` revalidation path and none exists; the case parks unresolvable; and the "nothing written"
defence protects the `STALE` transition itself, not the absence of anything afterwards. Whether the
correct destination is the manifest's escalation-and-hold or the spec's re-plan is a question a
repair has to answer — but the current dead end is not either of them, and it is not defensible on
its own terms.

### Consequence

**A promise is silently abandoned, and the case never finishes.** `ord-a` renders on the workspace
as `PromiseState.STALE`, owned by `ActionOwner.OWNER`, with the next action *"The owner checks the
re-planned outcome before anything else is done."* (`status_view.py:503`, `:529`) — a sentence
describing a re-plan that never happened and never will. So the owner is pointed at an outcome that
does not exist.

Beneath that, the case is stuck at `RECONCILING` for the life of the database. It never reaches
`RESOLVED`, so any count of finished cases is permanently short by one, and any operator waiting for
this case to close waits for ever. Priya's cake, meanwhile, is still on the kitchen's schedule,
unheld, pinned to a recipe version whose raspberries did not arrive.

### Blast radius

- **Within the sixteen:** S13 only. `_apply` reaches `mark_stale` in no other scenario — S15's
  amendment succeeds externally and its retry is idempotency-keyed, and every other scenario's auto
  track applies cleanly. **S13 may not pass on this repair alone:** if the repair is the spec's
  re-plan, the re-planned track returns to `PLANNED` and is then subject to cause C, so S13 would
  need both.
- **Outside the sixteen:** `test_a_plan_whose_inputs_moved_produces_no_external_effect`
  (`test_recovery_execution.py:920`) asserts the `STALE` state directly and would fail under a
  repair that replaced `STALE` with `ESCALATED`. It would survive a repair that keeps `STALE` and
  adds a route onward — which is an argument for the additive shape.
  `test_a_stale_plan_is_not_quietly_replaced_by_another_one` (`:942`) constrains what a re-plan may
  do to the chosen option.
- `approvals._request` also calls `mark_stale` twice (`approvals.py:475`, `:488`) and has the same
  dead end. No scenario of the sixteen reaches it, but a repair at `mark_stale` would change it too,
  and a repair at `_apply`'s call sites would not.

### What a repair would touch

**Domain, medium.** Either a successor from `mark_stale` (or from `_apply`'s two calls to it at
`recovery.py:800` and `:812`) enqueuing `REPLAN_TRACK`, which is the spec's answer and reuses
machinery that already exists — or a terminal escalation-and-hold for a track that has no re-plan
available, which is the manifest's answer and is smaller. The first is more faithful and drags in
cause C; the second is self-contained and needs an argument that §23's arrow does not mean what it
says.

---

## Cause E — the re-plan message to the customer does not exist

### The code that produces the observed value

There is none, which is the finding. `promisepatch.domain.messaging` defines exactly two outbound
templates: `build_approval_request` (`messaging.py:89`) and `build_confirmation_prompt`
(`messaging.py:117`). There is no template for telling a customer that their order changed and
their previous request is void.

`_replan` emits no effect at all, and `_supersede_approval` (`analysis.py:741`) updates two columns
and says so: "An update of two columns and nothing else." S06 therefore observes the one message it
has ever sent — the original ask — and the count is one.

### The rule that produces the expected value

S06's `CONSENT_SETTLED` declares `ord-b customer_message 1` added, making two cumulative, and its
rationale says "a fresh ask is sent". The frozen spec is more specific than the manifest, in §14.4:

> Re-planning a STALE track re-runs propagation for that promise only against current state,
> producing a fresh classification. The old ApprovalRequest is marked SUPERSEDED; if the customer
> had already replied, the reply is recorded but not applied, and **the customer receives one
> message explaining that their order changed and a new request (if any) follows. This is the only
> place a customer may receive a second message in the MVP.**

and §23:

> | **Order changes while approval pending** | Order-system webhook → fingerprint mismatch → STALE → re-plan that promise only; old request SUPERSEDED; **customer told once**; new request if still needed. |

S06 is that row, fact for fact.

### The case that the implementation is wrong

§14.4 states the message unconditionally, as a consequence of re-planning after a customer has
replied, and goes out of its way to mark it as the MVP's single sanctioned second message. §23 says
"customer told once" in the row that describes S06's exact facts. The implementation performs every
other clause of §14.4 — supersede, unbind, record the reply without applying it, re-run propagation
for that promise only — and omits this one.

The consequence is asymmetric in the worst direction. Tomas was asked a question, answered it with a
literal YES, and heard nothing again. From where he stands his approval was accepted. It was not,
and nobody told him. That is the same category of failure as claiming an effect that did not happen,
run backwards.

This is **not** the same gap as cause C. The §14.4 message is a consequence of re-planning, not of
confirming a new plan, so it would be owed even in a build where the confirmation gate stays exactly
as it is.

### The case that the label is wrong

The strongest version: the manifest declares *one* additional message, and §14.4 and §23 arguably
describe *two* things — "one message explaining that their order changed" and "a new request (if
any) follows" / "new request if still needed". If both went out, the cumulative count at
`CONSENT_SETTLED` would be three, not the two S06 declares. So S06's label is defensible only if the
supersede notice and the fresh ask are one message, or if only one of them belongs at that
checkpoint. The manifest's rationale says "a fresh ask is sent" and does not mention a supersede
notice at all, which suggests it labelled the ask rather than the notice — in which case the label
is counting the thing that cause C blocks, and cause E is not S06's cause at all.

That is a genuine ambiguity about *which* message the label names. It is not a defence of sending
neither. Under every reading of §14.4 and §23, a customer in Tomas's position receives at least one
further message, and this build sends zero.

### Classification: **IMPLEMENTATION DEFECT**

An unbuilt capability rather than a gating bug, and recorded as such. Which of the two messages
S06's label names is a secondary question that a repair will have to settle; that no message at all
is sent is not in question.

### Consequence

**A person is not told**, and it is the customer rather than the operator — the only one of the five
causes that reaches outside the bakery. Tomas replied YES to a specific change and receives no
further word. His approval sits in the database correctly marked as authorising nothing, and he has
no way to know that. If the bakery later delivers something he did not approve, or nothing at all,
the last thing he was told by this system was a question he believes he answered.

### Blast radius

- **Within the sixteen:** S06 only. §14.4's message is owed only where a customer had already
  replied before a re-plan, which is S06 alone. S07 re-plans, but Tomas's reply there is refused on
  stock rather than on his order moving; whether §14.4's message is owed in S07 too is a question
  the repair must answer, and **if it is, repairing this would break S07**, whose `CONSENT_SETTLED`
  declares no message. That is the single most likely way a repair here turns a currently failing
  scenario into a different failure and puts a second one at risk.
- **Outside the sixteen:** no test asserts the absence of a supersede message, because no such
  message has ever existed. Tests that count outbound effects on a re-planned case would need
  reading.
- Also worth naming: §23's "please disregard" message on the withdrawal path is recorded in
  [`bounded-withdrawal.md`](bounded-withdrawal.md) as deliberately **not** built, with the owner
  handoff implemented instead. This is a second unbuilt customer message with the same shape.
  Whether the two should be decided together is a judgement for the owner.

### What a repair would touch

**Domain, small to medium.** A third template in `messaging.py` with its literals and its test, an
`EmitEffect` on `_replan`'s outcome with a derived idempotency key, and a decision about whether the
message is owed on every re-plan or only where the customer had already replied. Plus the S06 and
S07 harness readings, which currently declare one message each and cannot both stay right under
every answer.

---

## What this diagnosis did not establish

- **It ran nothing.** No scenario was executed and no test was run; every chain above is static.
  Where an outcome depends on state the code does not determine — most importantly, where S13's
  re-plan would land under §23's arrow — this document says so rather than guessing.
- **It did not verify that any repair makes its scenario pass.** Under the pass rule a scenario
  matches on every checkpoint and every partition or not at all, and three of the five scenarios
  need more than one repair. Nothing here predicts a score, and no score was computed.
- **It did not weigh the causes against each other.** Cause C changes behaviour for cases that
  currently pass, including the demo case; cause A does not. That difference is reported, not acted
  on.

## The question for the owner

One cause is left undecided. It is the one the manifest predicted and the protocol pre-registered,
and nothing found in the frozen documents breaks the tie.

### Cause B — should a blocked promise hold a task the kitchen has already started?

**S12, `ord-e task_hold`, expected 1 and observed 0 at three checkpoints.**

*The reading in which the implementation is wrong.* §13.5 says the production task is placed on
`HELD` and calls that the one write a blocked track performs, with no qualification by task state.
The `SCHEDULED` predicate at `recovery.py:654` is a narrowing that appears nowhere in the frozen
text, and `TaskState` permits `STARTED → HELD`. A cake already in progress that cannot be finished
correctly is the more urgent one to stop, not the less. S12's rationale states the intent directly:
"with no valid option, the promise needs its owner whatever the kitchen has begun."

*The reading in which the label is wrong.* §13.5's stated purpose is "so the kitchen does not
**start** a cake that cannot be finished", and a hold cannot un-start anything. Holding a started
task records a claim about a physical fact that is false, and this project's own invariant is that
physical facts are authoritative independently of recovery authorization. The repair also collides
with a real gap: `withdrawal._release_holds` (`withdrawal.py:590`) restores every released task to
`SCHEDULED` unconditionally, so a started task held and later released would come back as never
started — the system silently rewriting a physical fact. Honouring that turns a one-line predicate
change into a schema column and a migration.

**What a decision either way requires.** If the implementation is wrong, the repair is
`state.in_(("SCHEDULED", "STARTED"))` — never removal of the predicate, which would hold `DONE`
tasks — plus whatever is done about the release. If the label is wrong, it needs a separately
versioned manifest, its own hash, and a written argument from S12's stipulated facts alone that
stands without reference to any observed output. A correction whose only argument is that the
implementation disagreed is refused by the protocol, and nothing in this document supplies a better
one.

Either way it happens under
[the correction process](effect-set-run-protocol.md#if-a-frozen-label-turns-out-to-be-wrong), beside
the 11/16 headline and never over it.

## What was not done

No product code, test, fixture, label, expectation or manifest was changed. The scored run was not
repeated, no scenario was executed, and no `X/16` was computed, printed, written or held privately.
`docs/effect-sets/scenarios.v1.json`, the capture and every frozen document are byte-identical to
what the scored run was taken against. Nothing was deployed, no AWS resource was touched, no model
was called, and both holdouts stay sealed.

The five scenarios remain committed failing, in the suite, in the denominator, unweakened.
