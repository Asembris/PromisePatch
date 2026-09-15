# The effect-set run protocol

**Predeclared. Written before the runner existed, in a session that scored nothing.**

| | |
|---|---|
| Fixes | how the sixteen frozen scenarios are executed, scored, captured and published |
| Manifest it scores | `promisepatch-effect-sets` v1.0.0, SHA `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` |
| Runner version at predeclaration | `1.0.0` |
| Scored runs so far | **none** |
| First-run headline so far | **none exists** |

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

## If a frozen label turns out to be wrong

Stop. Do not edit the manifest, do not adjust the harness's expectation, and do not "correct" a
label to match what was observed.

A genuine label error gets a **separately versioned manifest** with its own hash, a written
argument from that scenario's own stipulated facts that stands on its own without reference to
any observed output, and a **separate result** published beside the original. The original
labels and the original headline are immutable and stay exactly where they are.

A correction whose only argument is that the implementation disagreed is not a correction. It is
the precise failure the freeze exists to prevent, and it is refused.

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
