# The effect-set run protocol

**Predeclared. Written before the runner existed, in a session that scored nothing.**

| | |
|---|---|
| Fixes | how the sixteen frozen scenarios are executed, scored, captured and published |
| Manifest it scores | `promisepatch-effect-sets` v1.0.0, SHA `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` |
| Runner version at predeclaration | `1.0.0` |
| Scored runs so far | **one**, taken 15 September 2026 at `e81b5aa` |
| First-run headline so far | **11/16** — see [`effect-set-first-scored-run.md`](effect-set-first-scored-run.md) |

## Why a protocol, and why now

The manifest froze the *labels* before the runner existed, so nobody could tune an expectation
to an observed result. That freeze protects one half of the measurement. It does nothing about
the other half: **who decides which run counts**.

Without a rule fixed in advance, a build session ends with a number in it, and then every
subsequent decision — run it again, fix this first, call that one a rehearsal — is taken by
somebody who has already seen a score. That is the mechanism by which an honest measurement
becomes a best-of-N, and it does not require anybody to intend it. It only requires the
definition of "the run" to still be available for editing after the first result is known.

So the definition is settled here, before the harness is written and before any scenario has
been executed against the manifest with any intent to record. This is the same separation the
voice measurement needed and got: the ten turns were predeclared in one session and recorded in
another, and the building session's own runs were void by construction rather than by judgement.

**This document is the predeclaration. Nothing in it may be relaxed once a scored run exists.**

## The pass rule, which this protocol does not touch

The locked roadmap's G8 addition states it:

> A scenario passes only on exact order-set equality at every declared checkpoint AND exact
> expected logical operational effects, including no unauthorized/duplicate effects. Missing,
> extra or misclassified orders/effects fail the entire scenario.

The manifest's own committed `pass_rule` field says the same thing in the manifest's vocabulary:

> A scenario passes only on exact order-set equality for all four partitions at every declared
> checkpoint AND exact equality of the cumulative effect multiset at every declared checkpoint,
> including the zeros implied by absence. A missing, extra or misclassified order or effect
> fails the entire scenario. Rationale, notes and refusal fields are diagnostic, not pass
> criteria.

The harness implements that rule and nothing softer. This protocol governs *when a run counts*,
never *what passing means*. A partial credit, a nearly-right partition, a diff that is "only"
diagnostic: none of these exist, and no clause below creates one.

## Two kinds of run, and only two

### A SCORED run

A run is scored when **all three** of these hold:

1. It is the command below, exactly, with no scenario selection and no filter:

   ```bash
   uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py --scored
   ```

2. It executes **all sixteen** scenarios of the frozen manifest. The runner refuses `--scored`
   while any scenario is unwired, and exits non-zero without executing anything. A scored run
   over a subset is not a thing that can be produced.

3. It is invoked **with intent to record**: the invoker means its result to be the published
   number, and says so before pressing return. The runner takes that intent as an explicit
   argument — `--scored` is not a convenience flag and is not passed to see what happens.

A scored run writes its capture to `docs/effect-sets/runs/` and the capture is committed. Its
result is a number out of sixteen, and it is published whatever it says.

### A harness-development run

Everything else. Any invocation of the runner without `--scored`, any pytest invocation of the
scenario suite, any subset, any run during which the harness itself is being written or
repaired.

Harness-development runs:

- **are never scored**, in any sense, by anybody;
- **are never published as X/16**, not in a document, not in a commit message, not in a report,
  not in conversation, and not privately as a working figure that later becomes a claim;
- **may happen freely and as often as the work needs**, which is the whole point of naming
  them — a harness nobody may run is a harness nobody can debug;
- write a capture marked `development`, in the same format and with the same immutability, so
  the record shows what was run while the thing was being built rather than hiding it.

A development capture may record that some scenarios passed and some did not. That is a fact
about the harness under construction. It is not a score, it has no denominator of sixteen, and
the runner refuses to print one for it.

**The building session and the scoring session are different sessions.** A session that wrote
or changed harness code does not go on to take the measurement, because by then it has seen
outcomes and the choice of when to stop building is contaminated by them.

## What a development run may repair, and what it may not

Unlimited development runs are the right rule for a harness and the wrong rule for a label. A
harness that nobody may run is a harness nobody can debug, so the freedom to run and fix has to
exist. But that same freedom, pointed at a disagreement between a frozen label and what the
system does, quietly empties the headline: if every disagreement found while building is
resolved before the first scored run, that run is trivially sixteen out of sixteen, and G8's
"whatever the result" is theatre performed by somebody who already knew the result.

So the freedom is bounded, here, in advance:

> A harness defect may be diagnosed and fixed during development. A disagreement between a
> frozen label and the implementation's behaviour may not. It is recorded, published, and left
> unresolved until the first scored run has been taken and its X/16 captured. Resolution then
> follows G8's correction process.

The line between the two is not a matter of taste. A **harness defect** is a fault in the
machinery that observes: a fixture that will not build, a census that counts the wrong thing, a
checkpoint read before the system was quiescent, a drive that performs a different fact from
the one the scenario stipulates. It is a reason the harness cannot yet ask the question. A
**disagreement** is the harness asking the question correctly and getting an answer that
differs from the frozen label. It is the measurement, arriving early.

A disagreement is therefore not a bug report to be closed before the run. It is the finding,
and it is left where it is: the manifest untouched, the harness's expectation untouched, and
the failing scenario committed **failing**, never weakened, skipped, marked expected-to-fail or
removed. Whichever way it is eventually resolved -- a corrected label under a separately
versioned manifest, or a change to the implementation -- that resolution happens after the
first scored run has been taken and its number captured, under
[If a frozen label turns out to be wrong](#if-a-frozen-label-turns-out-to-be-wrong) and G8's
correction process, and is published beside the headline rather than over it.

**S12's `ord-e task_hold` is the first case, and it stays failing under this rule.** S12
declares `ord-e task_hold 1` at three checkpoints and the system produces `0`, because
`hold_tasks` holds only a `SCHEDULED` task and S12 stipulates a task already `STARTED`. The
harness is not at fault -- the same census counts held tasks correctly in S02 and S11 -- so
this is a disagreement and not a defect, and the two readings of it are both real. Neither is
chosen here. `test_s12_external_edit_adds_dependency_before` stays committed failing, the
diff stays published in `docs/effect-set-harness.md`, and nothing about either side of it is
repaired before the first scored run.

## The immutable capture

Every run, of either kind, writes one JSON capture file before anything may be repaired. A
capture records:

| field | why |
|---|---|
| `manifest_sha` | the canonical content hash, recomputed from the bytes on disk at run time |
| `manifest_version` | the manifest's own declared version |
| `implementation_sha` | `git rev-parse HEAD`, plus whether the working tree was dirty |
| `runner_version` | the harness's own version constant, bumped whenever its judging changes |
| `command` | the argument vector as invoked, verbatim |
| `started_at` / `finished_at` | UTC, from the machine that ran it |
| `kind` | `scored` or `development` |
| `outcomes` | one entry per scenario in the manifest, in manifest order, with its verdict |
| `diffs` | every difference between the frozen label and the observed result, in full |
| `environment` | Python version, platform, and whether a model or cloud credential was configured |

**The capture is written before any repair.** Not after the obvious cause has been found, not
after the one clearly-broken fixture has been corrected, not after a rerun confirms it. The
sequence is: run, capture, commit the capture, and only then diagnose. A capture that was
written after a fix is not a capture of the run it claims to be.

A capture file is never edited. A later diagnosis is a *new* document that references the
capture by its filename and by the implementation SHA it names.

### The three outcomes a scenario can have

- **`PASS`** — exact order-set equality for all four partitions at every declared checkpoint,
  and exact equality of the cumulative effect multiset at every declared checkpoint, including
  the zeros implied by absence.
- **`FAIL`** — the scenario ran and the result differs from the frozen label. The diff is
  recorded in full: which checkpoint, which partition or which `(order, kind)` pair, expected
  against observed.
- **`HARNESS_FAILURE`** — the scenario could not be executed to a verdict at all: the fixture
  would not build, the runner raised, a timeout, a crash, or an unwired scenario in a run that
  reached it.

**`HARNESS_FAILURE` is a nonpass and is counted in the denominator.** It is disclosed by name
in the capture and in every publication of the score. It is not a re-run, not an exclusion, and
not an asterisk. A harness that cannot execute a scenario has failed to demonstrate that
scenario, and the difference between "the system got it wrong" and "we could not tell" belongs
in the diagnosis, not in the number. The later diagnosis of every harness failure is recorded
and published alongside it.

## The headline, and what may never happen to it

**The first scored run's X/16 is the headline, whatever it says.**

- It is published as the headline in the README, the one-pager and the video, with the frozen
  manifest SHA and links to every diff.
- It is **never replaced by a repaired score.** Not when the repair is trivially correct, not
  when the failure was a harness bug, not when a later run reaches sixteen. Every fix gets its
  own commit SHA and its own separately published rerun, presented beside the headline and
  never in place of it.
- **No scenario is ever removed**, weakened, marked expected-to-fail, or excluded from the
  denominator. A failing scenario that stays failing stays in the suite and stays in the count.
- The denominator is always **16**. Not the number of scenarios that ran, not the number that
  produced a verdict, not the number that were wired at the time.

A release candidate is separately required to reach 16/16. That is a release condition and it is
reported as a release condition. It is a different sentence from the headline and appears next
to it, never over it.

## What passing CI means

The scenarios cannot pass CI until the disagreements are resolved, and this protocol forbids
every way of making them look as though they had. So the workflow separates the two questions
rather than letting one of them answer the other.

`.github/workflows/effect-sets.yml` runs the scenarios in a workflow of its own, in a job of its
own named **`effect sets (expected red until 16/16)`**, and the product gate --
`.github/workflows/pr.yml`, whose backend job is `backend + postgres` -- excludes them with
`--ignore`. Both workflows carry the same triggers and the same `paths-ignore` list, and their
`concurrency` groups are distinct so neither can cancel the other. Nothing is skipped, weakened,
deselected, removed or marked expected-to-fail: the scenarios run whole, in CI, on every trigger,
under the same command and against the same disposable database as before, and they fail with
exactly the diffs the published capture records. Only which job, and now which workflow, their red
colours has changed.

The reason is that a permanently red product job cannot report anything. A real regression
anywhere in the backend looked exactly like the failure that was already there, so the red that
was supposed to be informative was spoken for in advance. The move from one job to one file
finishes that separation at the place a reader actually looks: a status badge is per workflow
rather than per job, so while the benchmark sat beside the product jobs the repository advertised
a single red badge and a reader saw "broken" where the truth is "publishes its failures". There
are now two badges, and `README.md` says what the benchmark's red means before anybody has to
wonder.

**"The release SHA passes required CI" means the product gate**: every job in
`.github/workflows/pr.yml`. Branch protection requires those and not the effect-set workflow.

**G8's 16/16 on the benchmark remains a separate and still-required release condition.** It is
not satisfied by a green product gate, not waived by this separation, and reported as its own
sentence beside the headline exactly as
[The headline](#the-headline-and-what-may-never-happen-to-it) requires. A release needs both: the
product gate green, and the benchmark at sixteen out of sixteen.

The separation is asserted rather than trusted. `scripts/tests/test_ci_effect_set_job.py` fails
if the scenarios are put back into the product job, if their own job disappears, if its command
is narrowed with `-k` or `--deselect`, if it is allowed to pass with `continue-on-error`, or if
the scenario file acquires a skip or an xfail.

## If a frozen label turns out to be wrong

Stop. Do not edit the manifest, do not adjust the harness's expectation, and do not "correct" a
label to match what was observed.

A genuine label error gets a **separately versioned manifest** with its own hash, a written
argument from that scenario's own stipulated facts that stands on its own without reference to
any observed output, and a **separate result** published beside the original. The original
labels and the original headline are immutable and stay exactly where they are.

A correction whose only argument is that the implementation disagreed is not a correction. It is
the precise failure the freeze exists to prevent, and it is refused.

And it happens *after* the first scored run, never before it. A disagreement found while the
harness is being built is recorded and left unresolved until the headline exists; see
[What a development run may repair, and what it may not](#what-a-development-run-may-repair-and-what-it-may-not).

## What a run may not do

- It may not reach a live model. No scenario calls a provider; the capture's environment block
  records whether one was even configured.
- It may not reach AWS, a deployed host, or any database that is not this machine's disposable
  local one. The suite's existing `_database_safety` guard already refuses anything else.
- It may not require a messaging account. The customer channel is the local transport fixture,
  and every capture marks transport fixtures explicitly: local replay is not proof of live
  delivery, and the publication says so.
- It may not consult the sealed holdouts. They stay sealed.

## Prerequisites and the clean-clone command

Anyone with the repository, Docker and `uv` can reproduce a run. No AWS credential, no model
access, no messaging account, no hosted database.

From a fresh clone:

```bash
git clone <repository-url> promisepatch
cd promisepatch
uv sync --frozen
uv run python scripts/run_effect_sets.py --check
```

`--check` needs nothing but Python: it recomputes the manifest's identity against the published
hash, verifies the manifest's structural coherence, and prints which scenarios are wired. It
executes no scenario and touches no database, so it is the step that proves the clone is
complete and the identity is intact before anything heavier is attempted.

To execute scenarios, add the local stack:

```bash
uv run python scripts/bootstrap_local_env.py
docker compose up --detach --wait
docker compose stop worker
uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py
```

`docker compose stop worker` is not optional: the containerised worker and the suite share the
local database, and a running worker claims the steps a scenario just enqueued and finishes them
out from under it. The runner is a `development` run in that form. The scored form adds
`--scored` and is refused until all sixteen scenarios are wired.

Dependencies are pinned by `uv.lock` and installed with `--frozen`, so a clone resolves the
same tree the capture's environment block names.

## Status at predeclaration

Three of the sixteen scenarios are wired — **S02**, **S11**, **S12** — to prove the harness end
to end against scenarios that already had partial coverage. The other thirteen are **unwired
and declared as such**, by name, in the runner's own output and in every capture.

`--scored` is refused while that is true. No scored run has happened, and no X/16 exists.

*Since predeclaration:* the remaining thirteen have been wired, in a session that scored nothing,
and `--scored` is therefore no longer refused for want of an executable path — which is the only
thing that refusal was ever about. Several of the sixteen disagree with their frozen labels and
are committed failing, under the rule above. The two sentences that matter are unchanged: no
scored run has happened, and no X/16 exists. See
[`effect-set-harness.md`](effect-set-harness.md).

*Since then:* the first scored run has been taken, in a session that wrote no harness code, and
its headline is **11/16** with every diff published and nothing repaired. It supersedes the two
sentences immediately above and nothing else in this document — no rule here is relaxed, and
none may be. See [`effect-set-first-scored-run.md`](effect-set-first-scored-run.md) and the
capture at `docs/effect-sets/runs/20260915T163255509125+0000-scored.json`.
