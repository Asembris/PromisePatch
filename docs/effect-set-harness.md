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
| Wired | **3** of 16: `S02`, `S11`, `S12` |
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
from it, so it never sees an expected value. It was lifted out of
`test_whole_delivery_counterfactual.py`, which was the first test to need it, so the suite counts
an effect in exactly one place.

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
- **Compute a ratio for a development run.** A development capture's `score` field is `null` and
  the runner prints no figure out of sixteen for it.
- **Re-author a label.** No expected partition, effect, count or checkpoint is typed anywhere in
  the harness. Every one is read from the frozen JSON.
- **Skip a scenario it could not execute.** An unwired scenario, a raised drive, a scenario that
  reported twice: each is a `HARNESS_FAILURE` recorded by name, which the protocol counts as a
  nonpass.
- **Reach a model, AWS, a deployed host or a messaging account.** Nothing in the path constructs
  a provider; every capture's environment block records whether either was even configured.

## The three wired scenarios

Chosen because each already had partial coverage elsewhere in the suite, so wiring them proves
the harness end to end rather than raising a count.

**S02 — the whole delivery did not arrive.** Three checkpoints, no consent event, an empty
`auto_repairable` and an empty `consent_required`. Every declared effect is an escalation and a
held task, and the four orders the shortfall reaches carry no amendment and no message at any
checkpoint. It proves the harness reads an *absence* correctly: a census that counted an
intention rather than a delivered effect would fail here rather than pass quietly.

**S11 — an external edit removes a dependency, before.** Four checkpoints and the whole
authority range in one case: an amendment nobody was asked about, a message that asks, an
escalation, and three orders left entirely alone — one of which got there by a change this system
did not make. Lena's own edit really moves an order and really moves reservations, and the census
must still attribute none of it to this case. It proves attribution by window and by identity.

**S12 — an external edit adds a dependency, before.** The mirror image, and the one that
disagreed. Every partition matched at all four checkpoints and every effect matched but one; see
below.

## The thirteen that are not wired

`S01`, `S03`, `S04`, `S05`, `S06`, `S07`, `S08`, `S09`, `S10`, `S13`, `S14`, `S15`, `S16`.

They have no executable path. That is stated by `WIRED` in the runner, printed by `--check`,
recorded in every capture as a `HARNESS_FAILURE` with its reason, and it is what makes `--scored`
impossible today. The gap is a fact the tooling reports rather than a silence.

## Running it

From a fresh clone, with no database, no container, no credential:

```bash
uv sync --frozen
uv run python scripts/run_effect_sets.py --check
```

With the local stack, to execute the wired scenarios:

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

## The one disagreement this build surfaced, and why it was not repaired

**S12 declares `ord-e task_hold 1` and the system produced `0`.** Every partition matched at
every checkpoint. Every other effect matched, including `ord-e owner_escalation 1`. The whole
difference is three lines, one per checkpoint after planning:

```
CONFIRMED/effects        ord-e/task_hold: expected 1, observed 0
CONSENT_SETTLED/effects  ord-e/task_hold: expected 1, observed 0
SETTLED/effects          ord-e/task_hold: expected 1, observed 0
```

**It is not a harness fault.** The same census counts held tasks correctly in S02 (four of them)
and S11 (one), against the same fixture and the same code path.

**The cause is exact and is in the open.** `promisepatch.domain.recovery.hold_tasks` updates only
production tasks whose state is `SCHEDULED`. S12's `ord-e` is the one order in the Hollow Oak
fixture whose task is `STARTED`, and S12 stipulates that state rather than changing it. An
escalated track whose task has already started therefore takes no hold.

**The manifest could not have declared it any other way.** Rule R1 — an `owner_escalation`
implies a `task_hold` on the same order — is enforced by `scripts/verify_effect_set_manifest.py`,
so a label carrying the escalation without the hold would have been refused as incoherent when
the manifest was frozen.

**The manifest already predicted this specific disagreement.** Its own disclosure names both
halves of it: "the started-task case in S12" and "the uniform 'an escalation holds the task'
rule" are listed as judgements about what *should* happen rather than predictions of what the
code does, with the note that if the first run disagrees, the diff is the finding.

**There are two readings and this session picks neither.** Either R1 is too uniform — an
already-started task cannot be held, so an escalation on one should declare a hold of zero — or
the implementation is too narrow, and a promise nothing can repair should stop the kitchen work
whatever state it is in. Deciding between them changes either a frozen label or a physical
behaviour, and both are governed by the separately versioned correction process the protocol
fixes. Neither is a build-session decision.

**So nothing was repaired, and nothing was hidden.** The manifest is untouched. The harness's
expectation is untouched. No test was weakened, skipped or marked expected-to-fail.
`test_s12_external_edit_adds_dependency_before` is committed **failing**, because the failure is
the finding and the protocol is explicit that a failing scenario is never removed and a diff is
published before any repair.

## What this build did not do

No scored run happened. No X/16 was computed, printed, written or held privately. `--scored` was
invoked once, to prove it is refused, and it executed nothing. Both holdouts stay sealed, no AWS
resource was touched, nothing was deployed, and no model was called — the capture's environment
block records that neither a provider nor a credential was configured.
