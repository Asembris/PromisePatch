# The effect-set harness

**Built in a session that scored nothing.** The protocol it runs under was predeclared and
committed first — see [`effect-set-run-protocol.md`](effect-set-run-protocol.md) — and this
document describes only the machinery and what building it surfaced.

| | |
|---|---|
| Runner | `scripts/run_effect_sets.py`, version `1.0.0` |
| Judge | `apps/backend/tests/_effect_set_judge.py` |
| Observation | `apps/backend/tests/_effect_set_observation.py` |
| Manifest reader | `apps/backend/tests/_effect_sets.py` (pre-existing, unchanged) |
| Scenarios | `apps/backend/tests/test_effect_sets.py` |
| Wired | **16** of 16 |
| Disagreements | published below, unrepaired, by rule |
| Scored runs | **none.** No X/16 has been computed, printed or recorded |

## The four parts, and why they are four

The measurement is only worth taking if the expectation and the observation cannot come from the
same place. So they are separate modules with separate import surfaces, and the thing that
compares them can reach neither the system nor a hand-typed label.

**The reader** (`_effect_sets.py`) loads the frozen manifest and nothing else. It imports no
engine, no backend and no fixture, holds no opinion about whether a label is right, and asserts
the document's published SHA. It predates this work and is unchanged by it.

**The judge** (`_effect_set_judge.py`) implements the pass rule and only the pass rule. It takes
a scenario *identifier* — not a scenario, and not an expectation — and loads that scenario out of
the frozen document itself after checking the identity, so a caller cannot hand it a softened
label. It imports no engine, no backend, no database and no fixture.

**The observation layer** (`_effect_set_observation.py`) reads a running case: the four partitions
from the durable tracks, and the five effect kinds from durable conditions rather than from
intentions — an amendment the order system accepted, a message the provider took, a reservation
set that is no longer the one the window opened with, a task this case is holding, a track that
ended on the owner's desk. It reads the manifest's order table for identities and nothing else
from it, so it never sees an expected value.

**The runner** (`scripts/run_effect_sets.py`) orchestrates and judges nothing. It checks the
identity, invokes the scenario suite with a sink to report verdicts into, reconciles what came
back against the manifest's own list of sixteen, and writes the capture.

## What it asserts

- **The manifest's published identity, before anything else runs.** The runner refuses outright
  if the recomputed content hash is not
  `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc`, and the judge asserts the
  same hash on every call. A run against edited labels cannot happen quietly.
- **Exact order-set equality for all four partitions at every declared checkpoint.** Reported per
  partition rather than per order, so a misclassification shows both sides of itself.
- **Exact equality of the cumulative effect multiset at every declared checkpoint**, including
  every zero implied by absence. A pair the manifest does not declare must be observed as
  exactly zero; two amendments fail as surely as none.
- **Quiescence at each checkpoint.** A checkpoint is defined as a point where no step is
  runnable, so each reading asserts nothing is outstanding first. A partition read mid-step is
  not the one the manifest names.
- **That the denominator is the manifest's sixteen**, never the number of scenarios that
  reported. A wired scenario that reached no verdict is a `HARNESS_FAILURE`, not an absent row.

## What it refuses to do

- **Score a subset.** `--scored` exits non-zero, names the unwired scenarios, executes nothing
  and writes no capture while any of the sixteen is unwired. There is no flag that relaxes this.
  Every scenario is wired now, so the guarantee is proved against a deliberately narrowed wiring
  rather than against a gap that happens to exist.
- **Compute a ratio for a development run.** A development capture's `score` field is `null` and
  the runner prints no figure out of sixteen for it.
- **Re-author a label.** No expected partition, effect, count or checkpoint is typed anywhere in
  the harness. Every one is read from the frozen JSON.
- **Skip a scenario it could not execute.** An unwired scenario, a raised drive, a scenario that
  reported twice: each is a `HARNESS_FAILURE` recorded by name, which the protocol counts as a
  nonpass.
- **Reach a model, AWS, a deployed host or a messaging account.** Nothing in the path constructs
  a provider; every capture's environment block records whether either was even configured.

## All sixteen, and what each one's hardest checkpoint proves

`S02`, `S11` and `S12` were wired first, to prove the harness end to end against scenarios that
already had partial coverage. The other thirteen follow.

| | scenario | the checkpoint that carries it |
|---|---|---|
| **S01** | one ingredient of one delivery did not arrive | `CONSENT_SETTLED`. Tomas's amendment appears there and nowhere else, which is the whole of "an approval is authority and not application". A system that applied his change on the strength of the plan would reach the same `SETTLED` through a different history. |
| **S02** | the whole delivery did not arrive | `CONFIRMED`. Every declared effect is an escalation and a held task, and the four orders the shortfall reaches carry no amendment and no message. It proves the harness reads an *absence*: a census counting intentions rather than delivered effects fails here rather than passing quietly. |
| **S03** | a real physical exception that threatens nobody | `PLANNED`. The right answer is a case rather than silence: the fact is recorded, six promises are decided about, and all six are untouched. A system that opened no case leaves the same empty multiset and is wrong; one that held a task just in case leaves a different one. |
| **S04** | the substitute arrived and was unusable | `PLANNED`, reached through *two* physical facts in an order that matters — the strawberry line attested received and its six kilos posted, and only then the independent attestation that what arrived is unusable. Reaching the same four blocked promises by saying the strawberries never came is the conflation the manifest forbids. |
| **S05** | a recovery exists, is in stock, and the customer forbade it | `CONFIRMED`, and the wedding order's two lines in it. S01 blocks that order for two independent reasons; this scenario authors one of them away, so the surviving cause is provable. If the engine were blocking on the missing variant rather than the constraint, it shows here. |
| **S06** | the customer said yes, then changed the order | `CONSENT_SETTLED`, where his declared amendment count is zero. A recorded YES plus a moved order must not become a mutation. **Disagrees — see below.** |
| **S07** | the customer said yes, then the substitute was gone | `CONSENT_SETTLED`, the one place in the manifest where a partition legitimately moves. His promise goes from needing permission to needing its owner, because the re-plan finds no valid option at all. **Disagrees — see below.** |
| **S08** | a yes from the wrong person | `CONSENT_SETTLED`, where the partition has not moved at all and every count is what it was. Ahmed's own zero is as much the point as Tomas's refusal. **Disagrees — see below.** |
| **S09** | strawberries work | `CONSENT_SETTLED`: one message and no amendment. An agreeable sentence decides nothing and earns exactly one confirmation prompt; the literal YES that follows is what authorises the change. |
| **S10** | the same yes, delivered twice | `CONSENT_SETTLED`. The partition is identical to S01 at every checkpoint, so the whole content is the count: one decision and one amendment for an approval that arrived twice. |
| **S11** | an external edit removes a dependency, before | Four checkpoints and the whole authority range in one case. Lena's own edit really moves an order and real reservations, and the census must attribute none of it to this case. |
| **S12** | an external edit adds a dependency, before | The mirror image: membership of the threatened set is decided by stored state at the moment of the exception, in both directions. **Disagrees — see below.** |
| **S13** | the customer edited the order the plan was about | `CONFIRMED`, where Priya's declared amendment count is zero. An automatic recovery has nobody waiting on it, which makes it the easiest place to quietly claim success. **Disagrees — see below.** |
| **S14** | an unrelated external edit after the exception | `SETTLED`, where the cafe's order carries five zeros while its reservation rows demonstrably differ from the ones the incident opened with. A census that read the window and stopped there reports a false positive exactly here. |
| **S15** | the order system said yes and the worker died | `CONFIRMED`, where the declared count is one. The dangerous failure is a second cake rather than a lost one, and two fails it as surely as zero. |
| **S16** | the worker restarted while the customer was thinking | `CONSENT_SETTLED` — an approval accepted by a worker that never sent it, against a plan it did not make, on a deadline it did not set. It passes only if the restart is invisible in the result and visible in the worker identity that produced it, and both are asserted. |

## The four fault injections, and how each is made deliberate

G8 requires fixture setup and fault injection to be explicit operator actions rather than
accidents of timing. None of these four is a race that happened to go the right way.

**The foreign sender (S08).** The reply is put on the inbound transport carrying `ord-e`'s
approval channel as its sender, read out of the manifest's own order table. That is the single
thing about it that differs from the reply S01 sends: the same request, the same literal word,
a different identity.

**The replayed approval webhook (S10).** The first delivery's provider message id is captured
and the same reply is put on the transport a second time under it. That is exactly what a
provider retrying a delivery does, and the unique index on `(source, provider_event_id)` is what
absorbs it.

**The crash after external acceptance (S15).** `crash.AFTER_EXTERNAL_SUCCESS` is armed with a
guard that fires only once the order system's own event count shows Priya's amendment applied,
so the process stops inside the uncertain window itself rather than on whichever effect happened
to go first. `WorkerDied` derives from `BaseException`, so every `except Exception` in the worker
lets it through and the transaction rolls back — which is what a `SIGKILL` between two statements
leaves behind. The lease is then expired and a second worker, constructed with its own named
identity, retries under the same derived idempotency key.

**The restart while waiting for consent (S16).** The first worker is named, is used for
everything up to the confirmation, and is dropped; a second worker with a different boot identity
is constructed and does everything after it. The test asserts the two identities differ and that
the second one appears among the case's audit actors, so the restart is a fact about the run
rather than a description of it.

Two orderings are made deliberate the same way, and they are not faults. Several scenarios
stipulate *when* something happened relative to the case's own progress — an order edited after a
plan was confirmed and before its amendment reached the order system, a customer resizing their
order between a decision and the revalidation that would have acted on it. Both are races in a
deployment and neither may be a race in a measurement, so `work_held` pushes every step the case
has outstanding out of reach, lets the fact cross the boundary, and brings them back. The hold is
on steps and never on the boundary: webhooks still arrive, the inbox is still processed and the
mirror still moves, which is precisely the ordering being stipulated.

## Two things this work had to add, and one it had to disclose

**The order system could not express a quantity edit, and three frozen scenarios stipulate one.**
S06, S13 and S14 each turn on a customer changing the size of their own order — one cake becoming
two, twenty-four pastries becoming thirty — and the simulator's operator screen could only
re-point a line to a different item. So the screen gained a second control of its own, with its
own tests. It is deliberately *not* part of the amendment contract: a governed recovery amendment
re-points a line to another authored version and never changes how many of a thing a customer
bought, and the day it could would be the day this system started inventing orders.

**The census counted a reservation change by window alone, and the manifest predicted the false
positive.** Reservations are written in exactly one place — the order mirror, where a line's
claims are its pinned version times its quantity — so *every* reservation change arrives through
the same code path whether the order system was told to make it by this case or by the customer
who owns the order. Comparing sets against the baseline and stopping there would have counted
Cafe Marlow enlarging its own standing order, in the middle of an unrelated incident, as an
effect of that incident; S14's own rationale names that false positive before it happens. A
reservation change is now counted only when the change that produced it was **commanded by this
case**: the order-system event that moved the mirror carries the idempotency key of the amendment
PromisePatch sent, and that key belongs to one of this case's tracks. The rows still have to have
moved; the command is what says whose doing it was.

That repair is a **harness defect** fixed during development, which the protocol permits and
distinguishes carefully from a disagreement: the harness was asking the question wrongly, rather
than the system answering it wrongly. It changes nothing about S02, S11 or S12, whose reservation
changes are all commanded by their own cases or fall outside the window entirely.

**S04 diverges from one stipulated fact, and it is disclosed rather than hidden.** The manifest
says the two kilos of strawberries already on hand stay usable and only the delivered six are
lost. The deterministic interpreter has no way to attest a partial loss with a number — an
unqualified spoilage is all of it, and a qualified one without a quantity stops and asks a human
— so the attestation the scenario performs writes off the whole strawberry stock. It cannot reach
any label here: both candidate substitutions need more than the two kilos the manifest leaves
standing, so the promise is blocked on substitute stock at either figure. The *category* of the
fact, which is what S04 exists to keep distinct from S02, is exactly right: the delivery arrived
and what arrived was unusable.

## The five disagreements, published and unrepaired

Every one of the sixteen agrees with its frozen labels on **all four partitions at every declared
checkpoint**. Not one order is misclassified anywhere in the manifest. What diverges is effects,
in five scenarios, and every divergence is a missing `task_hold`, a missing `owner_escalation` or
a missing second `customer_message` — never an extra effect, never an unauthorised one, and never
a duplicate.

They are committed **failing**. The protocol was amended before a single scenario was wired to say
why: a harness defect may be diagnosed and fixed during development, and a disagreement between a
frozen label and the implementation's behaviour may not. It is recorded, published, and left
unresolved until the first scored run has been taken and its X/16 captured. Resolving them now
would make that run trivially sixteen out of sixteen and G8's "whatever the result" a performance.

Nothing below picks a side. Each one has two real readings and deciding between them changes
either a frozen label or a physical behaviour, both of which are governed by the separately
versioned correction process the protocol fixes.

### S12 — an escalation whose task had already started

```
CONFIRMED/effects        ord-e/task_hold: expected 1, observed 0
CONSENT_SETTLED/effects  ord-e/task_hold: expected 1, observed 0
SETTLED/effects          ord-e/task_hold: expected 1, observed 0
```

`promisepatch.domain.recovery.hold_tasks` updates only production tasks whose state is
`SCHEDULED`. S12's `ord-e` is the one order in the Hollow Oak fixture whose task is `STARTED`,
and S12 stipulates that state rather than changing it. Either rule R1 is too uniform — an
already-started task cannot be held, so an escalation on one should declare a hold of zero — or
the implementation is too narrow, and a promise nothing can repair should stop the kitchen work
whatever state it is in. The manifest predicted this specific disagreement in its own disclosure,
naming both halves of it.

### S08 — an escalation that came from a closed window

```
SETTLED/effects  ord-b/task_hold: expected 1, observed 0
```

The escalation itself is exactly as declared; only the hold is missing. The cause is that
PromisePatch holds tasks on *some* escalations and not others.
`promisepatch.domain.approvals._escalate` takes a `hold` flag and passes `hold=True` for §13.6's
refusal to ask into a window that is already closed — but `_close_request`, which is what an
approval request that *expires unanswered* goes through, escalates the track without holding
anything. So a customer who was asked and never replied leaves the kitchen work scheduled, while
a customer who could not be asked at all stops it. Either R1 is right and the expiry path should
hold, or holding is specific to never having asked, and R1 is stated more uniformly than the
system means it.

### S13 — a refused amendment that stayed refused

```
CONFIRMED/effects        ord-a/owner_escalation: expected 1, observed 0
CONFIRMED/effects        ord-a/task_hold:        expected 1, observed 0
CONSENT_SETTLED/effects  ord-a/owner_escalation: expected 1, observed 0
CONSENT_SETTLED/effects  ord-a/task_hold:        expected 1, observed 0
SETTLED/effects          ord-a/owner_escalation: expected 1, observed 0
SETTLED/effects          ord-a/task_hold:        expected 1, observed 0
```

**The thing S13 exists to test passes.** Priya's declared amendment count is zero and the observed
count is zero: her order moved, the fingerprint no longer matched, and nothing was written to a
cake nobody planned for. What differs is where the track came to rest. `recovery._apply` calls
`mark_stale`, which leaves the track `STALE` and the case `RECONCILING`; the manifest expects the
promise to reach the owner's desk with its task held. Re-planning is enqueued only from the
approval revalidation path, so an automatic recovery whose write was refused has no route onward
at all. Either a refused write should escalate — the manifest's reading, and the one that matches
"the track goes to the owner instead of claiming success" — or `STALE` is a distinct, correct
resting state that the manifest's five effect kinds simply cannot name.

### S06 and S07 — a re-plan nobody has confirmed

```
S06  CONSENT_SETTLED/effects  ord-b/customer_message:  expected 2, observed 1
S06  SETTLED/effects          ord-b/customer_message:  expected 2, observed 1
S06  SETTLED/effects          ord-b/owner_escalation:  expected 1, observed 0
S06  SETTLED/effects          ord-b/task_hold:         expected 1, observed 0
S07  SETTLED/effects          ord-b/owner_escalation:  expected 1, observed 0
S07  SETTLED/effects          ord-b/task_hold:         expected 1, observed 0
```

One disagreement wearing two hats, and the largest of the five. Both scenarios refuse a stale
approval correctly — S07's partition even moves from `consent_required` to `blocked` exactly as
declared, which means revalidation refused and the re-plan ran against the world as it now stands.
What neither reaches is the *consequence* the manifest declares for that re-plan.

`promisepatch.domain.analysis._replan` says so in its own docstring: "If the new plan still needs
asking, it is asked again, from `PLANNED`, **after a worker has confirmed it**." A re-planned case
returns to `PLANNED`, and confirmation is what sends asks and what escalates blocked tracks and
holds their production tasks. So S06's fresh ask is never sent and S07's re-planned blocked track
is never escalated — both are sitting, quiescent, waiting for a person.

The manifest's stipulated facts name no second confirmation. S01 and S05 stipulate Maya's
confirmation explicitly where it happens, so its absence here is a statement rather than an
omission, and the rationale for `ord-b` says plainly that "a fresh ask is sent". The scenarios
perform every fact they stipulate and nothing else — including S06's last one, which is performed
against whatever approval request is genuinely open and finds none, because none was sent.

Either a re-plan's consequences should follow from the revalidation that caused it, since no human
asked for the re-plan and there is no new decision for a worker to authorise — or a plan nobody
has seen must never act, in which case the manifest's `SETTLED` for these two describes a state
this system reaches only after a worker confirms, and the labels are a checkpoint early.

## Running it

From a fresh clone, with no database, no container, no credential:

```bash
uv sync --frozen
uv run python scripts/run_effect_sets.py --check
```

With the local stack, to execute the scenarios:

```bash
uv run python scripts/bootstrap_local_env.py
docker compose up --detach --wait
docker compose stop worker
uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py
```

The worker must be stopped: the containerised worker and the suite share the local database and
it will claim the steps a scenario just enqueued. The judge's own tests need nothing at all:

```bash
uv run pytest apps/backend/tests/test_effect_set_judge.py scripts/tests/test_run_effect_sets.py
```

## What this work did not do

No scored run happened. `--scored` was not invoked. **No X/16 was computed, printed, written or
held privately** — not in a document, not in a commit message, not in a report, and not as a
working figure that could later become a claim. The scenarios that disagree are named above with
their diffs in full, because the protocol requires a diff to be published before any repair; that
is a disclosure of findings and not a score. A score is what the first scored run produces, it has
not been produced, and it will not be produced by the session that wrote this code — the protocol
is explicit that the building session and the scoring session are different sessions.

Both holdouts stay sealed, no AWS resource was touched, nothing was deployed, and no model was
called.
