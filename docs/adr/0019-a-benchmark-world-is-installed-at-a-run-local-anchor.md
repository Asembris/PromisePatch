# ADR-0019 — A benchmark world is installed at a run-local anchor

**Status:** accepted
**Date:** 2026-09-19
**Supersedes:** nothing.
**Related:** [docs/safe-useful-recovery-benchmark.md](../safe-useful-recovery-benchmark.md),
[docs/sur1-world-programs.md](../sur1-world-programs.md),
[docs/sur1-dress-rehearsal.md](../sur1-dress-rehearsal.md) §13,
[docs/demo-fixture-anchoring.md](../demo-fixture-anchoring.md)

## Context

`SUR-1` has never been run. The dress rehearsal `DR01` proved the execution pipeline composes and
found thirteen defects; twelve were fixed and the thirteenth was left open as the largest blocker.

**The engine reads the clock and the install did not.**

`scripts/sur1/bindings/realisation._load` installed every scenario's canonical world at
`hollow_oak.ANCHOR` — `2026-03-04T07:00:00Z`, a fixed instant — and gave a correct reason: two
attempts at one scenario must be two attempts at one world, and an anchor that moved with the
clock would make them two worlds.

What that collides with is that nothing in the product reads the anchor. `physical.bakery_day`
buckets a commitment as *today* or *tomorrow* against the **real** clock, in the bakery's own
timezone, and `interpretation._commitment_candidates` narrows *today's raspberry delivery* to the
commitments falling inside that day. A world installed months after its anchor has **both** Valley
Produce deliveries in the past. Then:

* neither commitment falls in the bakery day, so the `today` narrowing selects nothing and is
  skipped entirely — both candidates survive;
* `interpretation._day_word` labels both `tomorrow`, because it labels anything outside the day
  that way;
* the scope question is never asked; the **commitment** question is asked instead, and both of its
  options carry the identical keywords `["valley", "produce", "tomorrow"]`;
* no answer can match one option rather than the other, the product's own answer ceiling is
  reached, and the case ends `NEEDS_HUMAN_INTERPRETATION`.

Reproduced at HEAD against the nine frozen world programs, with no database, no model and no arm
driven — all nine collapse, every one with two surviving candidates, zero in the bakery day and
one distinct option key where the scenario needs two. Every `SUR-1` scenario driven today would
end that way for `PROMISEPATCH` and `ABLATION`, and the comparative number would be a measurement
of the harness's calendar rather than of anything either arm did.

### Root cause

Not the fixed anchor, and not `bakery_day`. It is that **world identity and world placement were
conflated**. The freeze needs the first — *all three arms started from the same world* — and the
engine needs the second — *the world is happening now*. One constant was carrying both jobs, and
the two only agree during the week the anchor was chosen in.

The audit found they are already separable, and were separable before this ADR:

* **Every Hollow Oak timestamp is relative.** `promise_graph.examples.hollow_oak` takes an
  `anchor` from its caller and states every instant as an offset from it. `ANCHOR` itself is
  documented as *only used where a byte-stable hash is asserted*.
* **Every world digest is already anchor-normalised.** `worldsnapshot.offset` renders each instant
  as a whole number of seconds from the anchor, and the module says so in its second paragraph:
  *a run prepared at nine in the morning is the same world as one prepared at noon; a digest that
  disagreed with that would be measuring the clock.*
* **No frozen `SUR-1` fact is an absolute date.** `docs/benchmarks/sur1-world-programs.v1.json`
  contains no timestamp at all. `docs/benchmarks/safe-useful-recovery.v1.json` contains exactly
  one date, `authored_at`, which is the freeze's own provenance and not a scenario fact. Verified
  before anything was changed; had a scenario fact required March 2026, this work would have
  stopped and reported the conflict instead of rewriting it.

So the digest — the published identity of a starting world — is invariant under the anchor, and
was designed to be. The anchor was never the thing making two attempts one world; the digest was.

## Decision

**A `SUR-1` world is installed at a run-local anchor, chosen once per run, before any arm acts.
Production keeps the ordinary wall clock, unchanged.**

1. **One anchor per run.** `scripts/sur1/bindings/clock.run_anchor` computes it from `now` at the
   moment the run is composed, in `scripts.sur1.run.build`, which is before the preflight, before
   any arm is constructed and before any world is prepared. It is carried on the
   `LiveScenarioWorld` and used for every scenario and every attempt in that run.
2. **The rule is: the hour before the current one, floored.** The fixture places today's Valley
   Produce delivery at anchor + 60 minutes, so that delivery is between nought and sixty minutes
   in the past when the run starts. That is what makes the reported exception — *today's raspberry
   delivery didn't arrive* — a claim about a delivery that has already failed to arrive, rather
   than about one still due. Tomorrow's delivery is at anchor + 23 hours and lands on the next
   bakery day.
3. **It is checked, not assumed.** `run_anchor` verifies that today's delivery falls on the same
   bakery day as the run, in the bakery's own timezone, and **refuses by name** when it does not.
   The offsets are read off the fixture rather than written down, so a fixture that moved a
   delivery moves the check with it.
4. **Nothing about an arm reaches it.** The anchor is a property of the world, decided before the
   arms exist. There is no parameter, no branch and no configuration by which `BASELINE`,
   `PROMISEPATCH` and `ABLATION` could receive different anchors, and no trigger consults it.
5. **Production is untouched.** No engine, domain, API, worker or MCP module is changed by this
   ADR. `bakery_day` still reads the real clock; that is correct and is the behaviour under
   measurement.

### Alternatives rejected

**A — inject a benchmark clock into the product.** Give the backend a settable *now* that the
harness pins to the anchor. Rejected, and not narrowly: it puts a benchmark-only seam through
`physical.bakery_day`, the worker's daily check and every read that asks what time it is, so the
thing measured is no longer the thing deployed. A comparative benchmark whose subject was modified
to be measurable measures the modification. It would also be an authority-shaped change — a
request-supplied clock is exactly what the service-authentication invariant forbids on every
transport, and adding one for a benchmark would be the weakening that invariant exists to prevent.

**C — re-author the scenarios with relative dates.** They already are relative; there is nothing
to re-author, and editing the frozen manifest is forbidden and unnecessary.

**D — run `SUR-1` only in the week of March 2026.** Not an option in any sense: the date is past,
and a benchmark reproducible only during one week is not reproducible.

**E — recompute the anchor per attempt.** Rejected. It is defensible — the digest is invariant, so
per-attempt anchors still install the same world — but an attempt and its retry could then fall on
two different bakery days, and nothing in the capture would say which. One anchor per run costs
nothing and removes the question.

**B — chosen: rebase the prepared world to a run-local anchor.** Adds no benchmark-only decision
logic to the product, changes no declared fact, and moves no published digest.

## Clock semantics

* **The anchor is UTC.** `run_anchor` floors in UTC and returns a UTC instant. Every stored and
  recorded form is UTC ISO-8601.
* **The bakery day is not UTC.** Whether a commitment is *today* is a claim about the kitchen's
  calendar day, and it is read in the bakery's own timezone — the same `get_settings().bakery_tz`
  that `physical.bakery_day` reads, from the same settings object, so the harness cannot disagree
  with the engine about which day it is. A run whose backend is configured to one zone and whose
  harness assumed another is the failure this closes by construction rather than by convention.
* **Day boundaries fail closed.** The rule is refused, not silently corrected, when the computed
  anchor would put today's delivery on a different bakery day from the run. This differs
  deliberately from `demo.resolve_demo_anchor`, which nudges the demo by minutes so an operator
  resetting at 23:40 still gets a drivable demo. A demo should always work; a benchmark should
  never quietly move a stipulated fact to make itself runnable. The operator is told to start the
  run at another hour.
* **Retry.** An attempt and its retry are driven at **the same anchor**, because the anchor is
  captured on the world when the run is composed and is not recomputed per attempt or per
  scenario.
* **Resume.** A resumed run re-enters `build` and computes a fresh anchor for whatever it still has
  to drive. That is sound and it is bounded by the same check: attempts already captured are never
  re-driven — `RunDirectory.completed_attempts` skips them and scoring is a pure function of a
  file — so no captured attempt is ever reinterpreted under a second anchor, and any attempt that
  *is* driven on resume is driven at an anchor the check has passed for the day it runs on. The
  effective anchor of each invocation is recorded, so a run resumed on a later day says so in its
  own artefacts rather than leaving it to be assumed.
* **Reproducibility.** The reproducible object is the **world digest**, not the wall clock. Two
  runs at two anchors that publish the same nine digests started from the same nine worlds; that
  is the claim the freeze makes and the only one it needs. An absolute instant is recorded as
  provenance, never as an identity.

## What stays frozen

Everything that was frozen before, unchanged and verified after the correction:

| Frozen thing | Status |
|---|---|
| `docs/benchmarks/safe-useful-recovery.v1.json` (`SUR-1` manifest) | untouched |
| `docs/benchmarks/baseline-agent-prompt.v1.md` | untouched |
| `docs/benchmarks/sur1-world-programs.v1.json` and its three hashes | untouched |
| All nine published `world_digest` values | recomputed at the run-local anchor and **identical** |
| `ScenarioProgram.identity()` and `program_set_sha()` | unchanged — the anchor is not in `describes()` |
| `SNAPSHOT_SCHEMA_VERSION` | unchanged; the rendering did not move |
| `predeclaration.PREDECLARATION_SHA` | **deliberately unchanged** |
| `hollow_oak.ANCHOR` | unchanged, and still the default for every caller that passes none |
| Both evaluation holdouts | sealed |

`PREDECLARATION_SHA` is left where it is on purpose. It hashes the rules under which evidence is
*read* — the outbound classifier, the `E4` projection. How a world is *placed in time* before any
arm acts is a setup fact, not a reading rule, and folding it into that hash would make a scoring
freeze move for a reason that has nothing to do with scoring. The clock strategy is pinned instead
where it belongs: as a named, versioned constant the scored preflight refuses to proceed without.

## Why the scenarios still mean what they meant

Nothing about a scenario is stated as an absolute time, so nothing about a scenario is restated by
moving the anchor.

* **Every relative offset and every ordering is preserved.** The world is built by the same pure
  fold of the same steps over `hollow_oak(anchor)`; only the origin moves. The delta between any
  two instants in the canonical world is unchanged, asserted scenario by scenario.
* **No ground truth is touched.** Expected dispositions, authorised versions and effect ceilings
  live in the frozen manifest and are read by the scorer. Nothing on this path can see them —
  `preflight.ground_truth_reachable` already enforces that, and the clock module imports nothing
  that was not already imported on this path.
* **The incident is unchanged.** `get_incident` returns the same words to all three arms.
* **What changes is only whether the world is legible at all.** Before: the scope question is never
  asked and no answer resolves the case. After: the intended clarification is asked with distinct
  options, which is the scenario as authored.

## How the effective anchor is recorded

* `RunManifest.world_clock` carries the strategy, its version, the effective anchor and the bakery
  timezone, and is written into `run.json` at run start.
* `LiveScenarioWorld.identity()` names the clock strategy, so the run fingerprint that a scored
  authorisation binds covers it, and a world carrying an undeclared clock fingerprints differently
  from one that does not.
* `preflight.world_clock` refuses a scored run whose world carries **no** clock or an
  **unrecognised** strategy, and it is in `REQUIRED_CHECKS`, so no scored authorisation can be
  minted from a report that did not ask the question.

## Consequences

* `SUR-1` becomes temporally executable on any day, which it was not.
* One new module on the harness path, and small edits to thread one value through it.
* A run started in the two hours after the bakery's midnight — local `00:00` to `01:59`, swept at
  five-minute resolution — is refused rather than run. That is two hours in twenty-four, it is
  deliberate, and the refusal names which of the two facts failed.
* The harness now reads `get_settings().bakery_tz`. A harness run against a backend configured to
  a different zone than the harness's own environment is refused by the day check rather than
  producing a quietly wrong world.
* `DR01`'s `bakery_anchor` and this module are the same rule. The rehearsal delegates to it, so
  there is one statement of how a benchmark world is placed in time rather than two that can
  drift.
