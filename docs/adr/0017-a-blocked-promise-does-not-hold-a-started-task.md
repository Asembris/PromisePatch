# ADR-0017 — A blocked promise does not hold a task the kitchen has already started

Status: accepted
Date: 2026-09-17
Phase: 8

Decides the one cause [the effect-set failure diagnosis](../effect-set-failure-diagnosis.md) left
`UNDECIDED` and listed as a question for the owner: **cause B**, S12's `ord-e task_hold`, expected
`1` and observed `0` at three checkpoints. The diagnosis found nothing that broke the tie and said
so. This ADR breaks it, on a ground the diagnosis surfaced but did not weigh as decisive.

It reopens no frozen text. `docs/effect-sets/scenarios.v1.json` is byte-identical, its published
identity `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` is unchanged, and the
immutable **11/16** headline from the first scored run stands exactly as published.

## Context

`promisepatch.domain.recovery.hold_tasks` holds only tasks in `SCHEDULED`:

```text
ProductionTask.state == "SCHEDULED",
```

S12 stipulates that `ord-e`'s task is already `STARTED`, and that state is not something the
scenario arranges — it is in the frozen fixture itself, and `ord-e` is the only order of the six
whose task is not `SCHEDULED`. The update matches zero rows and the census records zero, against a
frozen label of `ord-e task_hold 1`. The escalation beside it is produced correctly, which is why
S12 diverges on the hold alone.

Two frozen readings point opposite ways, and both are real:

* **The rule is unqualified.** §13.5 says the production task is placed on `HELD` and calls that
  the one write a blocked track performs, with no qualification by task state. `TaskState` has a
  `HELD` member and nothing in the model forbids `STARTED → HELD`. S12's own rationale is direct:
  *"with no valid option, the promise needs its owner whatever the kitchen has begun."*
* **The rule's stated purpose is about starting.** §13.5's reason is *"so the kitchen does not
  **start** a cake that cannot be finished"*, and a hold cannot un-start anything.

The diagnosis weighed those against each other and could not separate them. What separates them is
not in §13.5 at all.

## Decision

**1. A blocked promise does not hold a kitchen task already in `STARTED`. The `SCHEDULED`
predicate stays exactly as it is, and no production code is changed by this decision.**

**2. The reason is the release path, not the hold.** There is exactly one way a held task is ever
released — `withdrawal._release_holds` — and it restores unconditionally:

```python
.values(state="SCHEDULED", held_by_case_id=None)
```

`production_tasks` has no column that remembers what the task was before the hold. `held_by_case_id`
records *who* holds it and nothing else. So a started task held by a case and then released by a
withdrawal comes back as **`SCHEDULED`**: the system would have asserted that begun work has not
begun. That is not a side effect of widening the predicate; it is the only exit the widened
predicate has.

**3. That is forbidden by this project's core invariant, not merely undesirable.** Physical facts
— received, not received, spoiled, equipment out, and a task the kitchen has started — are
authoritative independently of recovery authorization, and only an explicit correcting attestation
reverses one. A withdrawal is the opposite of a correcting attestation: it is a case standing down,
and it is required to reverse **no** physical fact. A withdrawal that silently rewrote a started
task into a scheduled one would be the single category this product treats as never acceptable,
reached by the code path whose whole documented promise is that it reverses only what is
reversible.

**4. So the frozen label and the invariant disagree, and the label is not changed.** S12 stays
committed **failing**, unrepaired, in the suite, in the denominator, with its diff published. The
manifest is not re-versioned, no expectation is edited, and nothing is skipped, xfailed or
deselected. Declining the repair and rewriting the label would both make S12 green; only one of
them is honest, and it is neither of them. The disagreement is a real one between a frozen label
and a frozen invariant, and it is recorded as a disagreement rather than resolved by whichever
document is easier to edit.

This is deliberately narrower than the protocol's correction process allows. That process would
admit a relabelling on a written argument from S12's stipulated facts alone — and such an argument
plausibly exists, since §13.5's purpose clause is about *starting*. **It is not made here**, because
a correction argued at the moment the implementation disagreed is the exact move the no-repair rule
exists to prevent, whatever its merits. The label stands; the behaviour stands; the gap between
them is published.

**5. The correct future repair is named, and it is a schema change.**

Widening the predicate to `state.in_(("SCHEDULED", "STARTED"))` is **not** the repair, on its own.
It is the defect. The repair is:

> **Add a column to `production_tasks` recording the state a task was in when it was held** — call
> it `held_from_state`, alongside the existing `held_by_case_id`, written by `recovery.hold_tasks`
> in the same statement that sets `HELD`, and read by `withdrawal._release_holds` so that a release
> restores the remembered state rather than the literal `SCHEDULED`. With an Alembic migration
> (`0009_*`) and `HEAD_REVISION` moved with it, since a deployed process reads that constant rather
> than the migration directory.

Only once release is truthful does holding a started task become truthful. Then, and only then, the
predicate widens to `SCHEDULED` and `STARTED` — never to no predicate at all, which would hold
`DONE` tasks and assert something worse than either reading here. The order is not an
implementation preference: the hold is the reversible write §13.5 promises, and a write is not
reversible before the thing that reverses it can tell the truth.

**6. It is not being made before release.** Three reasons, in order of weight:

* **It is a migration on the deployed host.** The deployment is live, holds durable cases that have
  survived a reboot, a stack update and a second reboot, and P6.2 records what a careless boot path
  costs — a re-seed that erased the very cases the deployment exists to prove outlive the host. A
  schema change plus a `HEAD_REVISION` move plus a rollout, taken to move one effect count on one
  benchmark scenario, is the wrong risk to accept in the week before a release.
* **It touches both halves of the hold, and one of them is the withdrawal.** The bounded withdrawal
  is proved by 70 targeted tests whose central claim is that it reverses no physical fact. Changing
  what its release statement writes means re-proving that claim, not adjusting it.
* **The benefit is bookkeeping.** Today `ord-e` is escalated to its owner with a reason and a next
  action, and appears on the workspace as `ESCALATED`. **No screen claims the task is held, because
  it is not**, and nobody is misinformed. The cost is that the owner learns of a blocked promise
  while work on it continues and must stop it by hand — real, and smaller by a distance than a
  withdrawal reporting a started task as scheduled.

## Consequences

* **S12 stays failing, permanently and on the record.** It runs whole in CI's
  `effect sets (expected red until 16/16)` job, unweakened. G8's 16/16 remains a separate release
  condition published beside the immutable 11/16, and this decision makes S12 one of the scenarios
  standing between the two.
* **`STARTED` work on a blocked promise continues until a person stops it.** Stated plainly because
  it is the cost being accepted: a cake that cannot be delivered as promised may keep being made
  for as long as it takes its owner to act on the escalation. The escalation is immediate; the
  stopping is manual.
* **The four other failing scenarios are untouched.** S06, S07, S12 and S13 remain committed
  failing with byte-identical diffs; cause A's repair stands; causes C, D and E are not addressed
  here and cause C still does not move until the demo narrative is settled.
* **The invariant gains a worked case.** "Physical facts are authoritative independently of
  recovery authorization" now has a concrete instance where it outranked an unqualified frozen rule
  and cost a benchmark point, which is a better record of what the invariant is worth than an
  instance where it cost nothing.

## Alternatives rejected

* **Widen the predicate and accept the release.** A withdrawal reports a started task as scheduled.
  Refused outright: it is the one category this project does not trade.
* **Widen the predicate and forbid releasing a started hold.** Turns the hold into something §13.5
  explicitly says it is not — *"reversible by the owner"* — and strands the task in `HELD` with no
  exit, which is a worse physical claim than the one it avoids.
* **Re-version the manifest so S12 expects `task_hold 0`.** Available under the correction process,
  and refused for now: see decision 4. A relabelling whose timing coincides with the implementation
  disagreeing is not distinguishable from a repair of the score, however good the argument, and the
  first scored run's denominator is permanently sixteen either way.
* **Take the schema change now.** The right repair at the wrong moment. Named in decision 5 so it
  is a scheduled piece of work rather than a discovery somebody makes again from the same three
  lines of SQL.

## Revisit if

* The release is taken and the deployment is no longer the binding constraint — at which point
  decision 5's schema change is the first thing to do about cause B, and it is already specified.
* A second release path for a held task is ever added. The whole argument rests on there being
  exactly one, and on that one having no memory; a second would have to carry `held_from_state`
  from the start.
* Someone writes the argument from S12's stipulated facts alone that decision 4 declines to write,
  after a scored run rather than before one. It belongs under
  [the correction process](../effect-set-run-protocol.md#if-a-frozen-label-turns-out-to-be-wrong),
  beside the 11/16 headline and never over it.

## Amendment — 17 September 2026, verifying this decision against HEAD

Every load-bearing claim above was re-checked against the implementation and holds. The decision
stands unchanged and no production code moved. Two facts were found that this ADR did not record.
Neither contradicts it; both were needed to close
[the started-work contract](../started-work-contract.md).

**1. The disagreement is with a manifest-wide rule, not with S12's label.** The frozen manifest's
`vocabulary.labelling_rules` declares **R1** — *every escalation to the owner holds that order's
production task* — unconditionally, and `scripts/verify_effect_set_manifest.py` refuses any
manifest in which an order escalates without a hold. S12's label is therefore R1 correctly applied
to the one fixture row where R1 is false, not an authoring slip. A v1 manifest expecting
`ord-e task_hold 0` would be structurally invalid by its own verifier, so the relabelling decision
4 declines was never available to be taken quietly. This strengthens decision 4 rather than
qualifying it, and it is why a revised benchmark contract has to revise R1 rather than one label.

**2. Decision 5's repair is insufficient as specified, and the missing part is a precondition.**
`held_from_state` repairs release. It does not repair reading. `revalidation._task_is_ours` treats
`HELD by our own case` as satisfying check 6, *"production task not started and still ahead"*, and
that equivalence is sound only because `hold_tasks` can hold nothing but a `SCHEDULED` task, which
makes `HELD` a faithful proxy for "was scheduled". Widening the predicate to `STARTED` breaks that
relation at its root while the check that depends on it reads only `state` and `held_by_case_id`.
So decision 5 gains a third part, ordered before the other two: `_task_is_ours` must refuse a hold
whose remembered state was `STARTED`. This is a hazard in a repair that has not been made, not a
defect at HEAD — no started task is ever `HELD`, so no current path reaches it.

One detail in decision 5 has since gone stale: it names the migration `0009_*`, and
`0009_human_plan_approval` now exists at HEAD, so the repair's migration is `0010_*`.

Neither finding reopens this decision. The consequence of both is that decision 5 costs more than
it appeared to, which makes decision 6's refusal to take it before the release stronger, not weaker.
