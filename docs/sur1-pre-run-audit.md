# The `SUR-1` pre-run audit: one blocker, and everything that held

**No arm was driven, no model called, no scorer run and no comparative number exists.** `SUR-1`
is still unrun, `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` is unspent, both evaluation holdouts
stay sealed, and no `SUR-1` result directory was opened. This audit read the proof machinery and
changed none of it.

This is the audit taken before the first scored run, asking whether the machinery could be frozen
and left alone. It could not. One defect is material and arm-correlated, and it is recorded here
rather than fixed, because the session that finds a confound is not the session that should
redesign the thing it was auditing.

The audit's own vocabulary was *phase 3 / phase 4*. That is the execution workstream's framing and
is **not** the roadmap's gate structure: `new_roadmap.md` runs `G5`–`G9` and `G8` is the open gate.

| | |
|---|---|
| Benchmark | `SUR-1` v1.0.0, manifest SHA `5718340f…e70e84c`, **unchanged** |
| Baseline prompt | SHA `772ba460…9ce47cb1`, **unchanged** |
| Scorer | `scripts/score_safe_useful_recovery.py` v1.0.0, pinning the same manifest, **unchanged** |
| Predeclaration rules | SHA `c53d267a…1d1e1927`, **unchanged** |
| World programs | `program_set_sha` `88db566c…ab1de649`, `implementation_sha` `76eda88e…5300e883`, **both unchanged** |
| `C01`–`C09` | all nine program hashes and world digests agree with the declaration |
| Effect sets | `11/16` stands, manifest hash unchanged, `S12` stays committed failing |
| Runs taken | **none** |

Every hash above was recomputed from the bytes on disk during this audit and agrees with its
published value. `declaration.differences()` is empty.

## The blocker: the scored path has no customer-consent ingress

A stipulated customer reply is delivered, on the scored path, **only to an in-memory Python
list**. PromisePatch never receives it.

| | |
|---|---|
| `scripts/sur1/run.py` | builds `ChannelLedger()` and hands it to `LiveScenarioWorld` |
| `scripts/sur1/bindings/world.py` | `_sink()` returns `LiveWorldSink(channel=self.ledger, …)` |
| `scripts/sur1/bindings/worldsink.py` | `deliver_reply()` calls `self.channel.accept(…)` and nothing else |
| `scripts/sur1/bindings/receivers.py` | `ChannelLedger.messages` is a `list[ChannelMessage]` |

`POST /api/customer/approval/{token}` is reachable from exactly one place under `scripts/`:
`scripts/rehearsal/world.py`, in the **rehearsal** package, which the scored package never
imports. `LiveScenarioWorld` has no sink field and no door field, so there is no seam an execution
session could bind one through either.

**What that does to arms B and C.** No `approval_request` is bound, the sender is never compared
against the channel the request was sent to, no deadline is checked against the database's clock,
`consent.read_literal` never runs and no consent decision is written. The case waits for a
customer who was never asked, in the product's own terms.

**Why it is not symmetric, which is what makes it a confound rather than a limitation.** Arm A is
not PromisePatch and has no consent protocol: it needs the reply only to *exist* as `E2` evidence,
and it does exist, on the channel the receiver reads. So the same missing door leaves the baseline
whole and stops arms B and C recovering anything that needs a customer's yes.

Eight of the nine scenarios carry an authorising consent fact, and seven — `C01`, `C02`, `C03`,
`C05`, `C07`, `C08`, `C09` — hold a `CONSENT_REQUIRED` order whose recovery requires that literal
yes to be parsed. A scored run taken today would understate `complete_allowed_recovery` and
`recoverable_recovered`, the benchmark's primary metric, in an arm-correlated direction that
favours the baseline.

**This was already named.** [`sur1-world-events.md`](sur1-world-events.md) says of the reply
arriving through the product's own signed-possession-link path that it "is a real question this
work does **not** answer. It is the next thing to settle before a scored run, and it is not
settled here." `DR01` then answered it — in the rehearsal package only. The scored `deliver_reply`
is covered by one test, as a channel append; no scored-path test asks for ingress and no preflight
check requires it.

**What is not wrong with it.** `BindingConfig` already carries `api_base_url`, so the door is
buildable from what a scored run already holds. This is a wiring gap, not a missing capability,
and the rehearsal has a working implementation of the door to read. Nothing about the finding
asks for a frozen artefact to move.

## What held

**Frozen identities.** All seven recompute to their published values, as tabled above. No `SUR-1`
capture, verdict or run directory exists anywhere in the tree.

**Execution safety.** A scored run is driven under a `ScoredAuthorisation` minted only by a
preflight naming every one of the thirteen `REQUIRED_CHECKS`, and `drive(kind="scored")` refuses a
caller-supplied contract or scorer outright. `RETRYABLE` is `frozenset({"VOID"})` against
`MAX_ATTEMPTS` of two; `BUDGET_EXHAUSTED` and `HARNESS_FAILURE` are recorded directly and never
become a void. The binding's own deadline is 240s inside the frozen 300s ceiling, measured at
10.64s of actual waiting. `E1` is read from the order system's own endpoints, read-only, through
one reader for all three arms.

**Isolation, everywhere it is structural.** The arm label lives on the adapter and has nowhere to
go in an `ArmAttempt`; `blind_bundle` takes no arm, no latency and no cost as parameters, so the
scorer's `EvidenceBundle` has nowhere to carry one. The ablation calls the real evaluator
unchanged and re-derives the outcome from the evaluator's own imported mapping. `settle()` answers
the message rather than the sender, which is what keeps event timing arm-blind.

**World and realisation.** All nine worlds install into the live local PostgreSQL and the order
simulator at the [ADR-0019](adr/0019-a-benchmark-world-is-installed-at-a-run-local-anchor.md)
run-local anchor, with committed rows read back and compared against the canonical snapshot; every
scenario agrees on all six facts, arms its events without firing one, and leaves the residue
tables clean. `C01` installed a second time after the other eight reads back byte-identical.

**CI.** At `abad6f9`, the `pr` workflow is green across all thirteen jobs and
`effect sets (expected red until 16/16)` fails at the step *The sixteen frozen scenarios* — the
designed failure and not an infrastructure one. `scripts/tests` is 1075 passed, one skip that
depends on this machine having already run the challenger.

## What this audit did not do

- **It drove nothing and called nothing.** No arm, no model, no AWS call, no deployment.
- **It edited no frozen artefact.** The manifest, the prompt, the scorer, the predeclaration, the
  world-program declaration and every effect-set artefact are byte-identical.
- **It did not fix the blocker.** Wiring an ingress door is a change to how a measurement reaches
  the deciding system, and it belongs to a session that can design it, disclose it against the
  predeclaration and re-freeze what it moves.
- **It froze nothing.** The harness is not scope-frozen, because a freeze over a known confound
  would be the freeze that made it permanent.

## What has to be true before a scored run

1. **The consent-ingress blocker above is closed**, and whatever closes it is disclosed, because
   it changes what arms B and C receive.
2. **A model this account can invoke**, and the spend authorisation, which is unspent.
3. **A different session.** The contract's freeze block is explicit that the building session is
   not the scoring session.
4. **The scored preflight has never been run against real bindings with a region set.**
   `model_identity` and the AWS half of `configuration` need an account this audit did not touch.
