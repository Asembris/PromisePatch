# CLAUDE.md — PromisePatch operating contract

## Purpose

PromisePatch turns one spoken physical-world exception ("today's raspberry delivery didn't
arrive") into a correct, consent-respecting, selectively-applied set of customer-promise
recoveries, with the reasoning visible. Made-to-order bakery vertical.

## Current state

Deterministic engine, backend foundation, and PostgreSQL baseline schema are complete. The
P4.8 explanation quality gate is **closed**. Its two-run DEVELOPMENT allowance is spent, the one
bounded production repair with it, and the repaired run (`7172c7c894ae`) established that Nova's
verbalisation is safe -- every structural and semantic hard gate zero, faithfulness 5.00 -- and did
not establish that it is complete: nine of twenty-one passages cite a required fact and never say
it, and the judge scored causal completeness 5 on all nine.

P4.8 therefore closes with a selection rather than a further measurement. **User-facing explanations
are rendered deterministically by `promisepatch.domain.explanations.render`**, reached through
`verbalisation.explain`, with `PP_EXPLANATION_VERBALISATION` off by default. The bounded Nova
verbalisation path -- prompt, schema, validators, `prepare`, the dataset, the thresholds, the judge
and both DEVELOPMENT result files -- is preserved intact as evaluated-but-not-selected capability,
one variable away from a later phase with a repaired instrument or a different model. `prepare`
stays ungoverned by that setting so the evaluation harness keeps measuring the model it is pointed
at. Both holdouts -- explanation and customer-intent semantic -- remain sealed and unopened; the
explanation one stays sealed permanently for P4.8, because DEVELOPMENT already answered the shipping
question (see `docs/explanation-quality-gate.md`, *Closeout*).

**P4.9 is closed, and with it Phase 4.** The semantic layer was audited against a bounded threat
set -- injection, cross-kind contamination, adversarial structured output, invented entities and
authority, bootstrap failure, outage, timeout, bounded retry, stale and duplicated results,
replay, consent-authority attacks, late arrival, and both explanation paths. No authority or
correctness defect was found: nothing a model says, fails to say or fails to answer can reach a
write, a consent decision or a physical attestation. Four containment defects were found and
fixed, all of the same shape -- an untyped exception escaping the boundary's two-kind failure
vocabulary, past callers that catch only those two: an over-long worker statement, a Bedrock
response envelope of the wrong shape, an order-system display label too long for one fact, and a
persisted reading carrying none. Eight adversarial proofs were added, offline, zero model calls,
$0. Both holdouts remain sealed. See `docs/p4.9-semantic-failure-hardening.md`.

**P5 is open, and its G5 contract-locking work is done.** Before any P5 implementation, four
things were fixed and committed. The **frozen 16-scenario effect-set manifest**
(`docs/effect-sets/scenarios.v1.json`, `promisepatch-effect-sets` v1.0.0, manifest SHA
`d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc`) declares, per scenario, the
expected order partitions at every ordered checkpoint plus the exact operational effects and
refusals, hand-labelled from stipulated facts and never from engine output; it reuses the
Hollow Oak fixture universe and is structurally verified by
`scripts/verify_effect_set_manifest.py`, which imports no classifier. **ADR-0008** records the
superseding decision to remove the runtime apparent-intent classifier, keeping the literal
parser, the confirmation prompt and every historical measurement unedited. **The P5 product
contract** (`docs/p5-product-contract.md`) locks the conversational authority boundary, the
truthful `PLANNED`/`REQUESTED`/`RECOVERED` state vocabulary, the zero-incident-caused-effect
definition and the first case-workspace hierarchy. Labels precede the *remaining*
implementation, not the pre-existing engine, and that chronology is stated wherever the score
will be. Both holdouts stay sealed; P4.8 stays closed. See `docs/effect-set-manifest.md`.

## Authoritative documents

`PROMISEPATCH_PRODUCT_SPEC.md`, `ARCHITECTURE_PLAN.md` and `new_roadmap.md` are frozen, gitignored,
local-only and **authoritative whenever present**. `new_roadmap.md` is the locked P5-P9 roadmap and
its per-phase acceptance gates; reopening it requires a reproduced correctness or eligibility blocker,
or a documented official rule change. Read them before deciding anything they cover. Never
modify them unless explicitly asked. Never commit them.

## Core rule

**The model understands; the deterministic protocol authorizes.**

## Key invariants

- The LLM never authorizes a write and never produces a consent decision.
- Customer consent is only a literal `YES` / option code / `NO`; free text is at most a
  non-authoritative apparent intent that can trigger one confirmation prompt.
- Recovery selects only pre-authored `RecipeVersion`s named by `SubstitutionPolicy`. Nothing
  at runtime creates, derives or synthesizes a version.
- The external order system is the system of record for orders. PromisePatch has no order
  editor; it writes to an order only as a governed recovery amendment.
- Physical facts (received / not received / spoiled / equipment out) are authoritative
  independently of recovery authorization. Declining a plan never un-spoils anything; only an
  explicit correcting attestation reverses a fact.
- A commitment line is open (`EXPECTED`) or settled. Settlement posts its physical outcome to
  the ledger exactly once, and a settled line contributes zero to expected supply. Received
  supply is never also counted as expected.
- Unknown or conflicting state fails closed to `BLOCKED` — never `UNAFFECTED`, never
  `AUTO_RECOVERABLE`.
- Promises not reachable from the exception are untouched: no message, no write, no
  reservation change, no task hold, no audit event.

## Architecture summary

One Python backend (`api`, `worker`, `mcp` entrypoints), one pure engine package
(`promise_graph`), one React evidence UI, one separate External Order System simulator,
PostgreSQL as the single store, a persisted case state machine with a step ledger, Bedrock for
understanding only, MCP for the five intent tools, Telegram for the customer channel.
`promise_graph` depends on the standard library and Pydantic only, does no I/O, reads no
environment, and never calls the wall clock — time is passed in explicitly.

## Development rules

- One phase at a time. Never build Phase N+1 artifacts while in Phase N.
- Do not redesign frozen architecture; amend the ADR first if a decision must change.
- All gates must pass before a phase is complete: pytest with the coverage floor, the
  Hypothesis CI profile, mypy, ruff check, ruff format, import-linter.
- Never weaken, skip or delete a test to make code pass. Fix the code or fix the fixture data
  and say so.
- Secrets are never committed. No `.env`, no tokens, no credentials.
- No synthetic validation, no invented metrics, no performance or impact claims.

## Git

One-line Conventional Commit subjects. No body, no bullets, no trailers, no co-author line,
no generated-by line, no emoji. Example: `feat(engine): propagation`.
Never push unless explicitly asked.
