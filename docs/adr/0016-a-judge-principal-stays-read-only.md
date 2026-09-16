# ADR-0016 — A judge principal stays read-only, because a report is authority over the bakery

Status: accepted
Date: 2026-09-16
Phase: 7

[ADR-0013](0013-read-only-observer-principal.md) created the `observer` role and decided it may
read and may write nothing. It recorded four reasons, and **none of them is the binding one**.
This ADR supplies the reasoning ADR-0013 lacked, established by running the system rather than by
reading it.

It does not supersede ADR-0013. Nothing in that decision changes, no check is altered, and no
principal gains or loses anything here. What changes is that the decision now has a reason that
survives the obvious objection to it.

## Context

The complaint is real and is stated accurately: the demo session mints an observer, an observer
may say nothing, and so a judge who follows the judge entry cannot take a single one of the turns
[§5 of the judge UX contract](../p7.1-judge-ux-contract.md) designs the conversation panel around.
A judge watches a conversation they cannot hold.

ADR-0013's recorded reasoning is about impersonation and about not weakening a shared check: no
published credentials, no session as `maya` or `jo`, no `scope` column on a worker session, no
removal of the gate from the read path. Every one of those still holds.

**But all four are satisfied by a design ADR-0013 does not answer**: a fresh `guest` principal per
demo session, admitted to nothing but the case it opens itself. That needs no change to
`require_permitted` — its existing opener branch already refuses one guest another guest's case,
and `test_another_baker_may_not_speak_on_somebody_elses_case` already pins it. It names no real
worker, publishes no credential, and leaves the actor server-derived and the `plan_id` binding
untouched. Read against ADR-0013 alone, a per-visitor guest is the obviously correct next step.

It is not, and the reason is in the domain rather than in the permission surface.

## Decision

**A judge principal stays read-only.** Not because a visitor cannot be confined to their own case
— they can — but because the first turn of the journey is not a case-local act.

### 1. A report is a physical attestation, so a judge turn is authority over the shared bakery

The journey's first verb is `report`, and `report` is `intake.open_physical_exception`: a worker
putting a claim about the kitchen on the record. The core invariant is explicit that such a claim
is not case-local:

> Physical facts (received / not received / spoiled / equipment out) are authoritative
> independently of recovery authorization. Declining a plan never un-spoils anything; only an
> explicit correcting attestation reverses a fact.

A commitment line is open or settled, and settling one posts its physical outcome to the ledger
exactly once. So a visitor's first sentence does not create a private world for them to explore —
it moves the one shared physical record every other visitor's case is then classified against.
**Granting a judge that turn is widening what a principal may do beyond its own case**, which is
the standing refusal, reached from a frozen invariant rather than from preference.

Withholding `confirm` does not save it. The damage is done by intake, not by authorisation.

### 2. The evidence: the second judge condemns a delivery that has not happened yet

Three successive principals were driven through the canonical journey against one shared Hollow
Oak fixture, through the real services and a real worker process, offline, with the deterministic
semantic provider — report, drain, the clarifying answer, drain — reading `commitment_lines`
between each. The full run is in
[the authority assessment](../judge-write-authority-assessment.md), §3.

| | what the principal saw | what it left behind |
|---|---|---|
| judge 1 | the canonical demo | `cl-vp-today-raspberries` `NOT_RECEIVED`, `cl-vp-today-strawberries` `RECEIVED` |
| judge 2 | **an identical screen** | `cl-vp-tomorrow-raspberries` `NOT_RECEIVED` |
| judge 3 | nothing — `NEEDS_HUMAN_INTERPRETATION`, no question asked | — |

Judge 2 did not get a degraded copy of judge 1's demo. **Judge 2 attested that a delivery which
has not happened yet failed.** Today's raspberry line was already settled, so the only open
raspberry commitment left was tomorrow's; the interpreter resolved the same sentence against it
entirely correctly, and judge 2's answer settled it `NOT_RECEIVED`. The classification judge 2 saw
was identical to judge 1's — `pr-a` `AUTO_RECOVERABLE`, `pr-b` `APPROVAL_REQUIRED`, `pr-c`/`pr-d`
`BLOCKED`, `pr-e`/`pr-f` `UNAFFECTED` — which is precisely what makes it unsafe. **Nothing on the
screen distinguishes the real demo from a visitor having condemned tomorrow's delivery.**

Judge 3 dead-ends. With no open raspberry commitment left the sentence resolves to nothing, the
case stops at `NEEDS_HUMAN_INTERPRETATION`, and `answer_clarification` refuses with
`NotAwaitingClarificationError` because there is no question to answer.

Repeated with report and clarify only — no confirmation and therefore **zero operational
effects** — the outcome was the same. And it is not erasable: `audit_events` and `domain_events`
are outside the reset set and are refused truncation by trigger, so a visitor's false claim about
tomorrow's delivery is in the ledger of record permanently, attributed to a worker identity, and
reversible only by a correcting attestation reachable from the CLI alone.

**The shared fixture tolerates exactly two journeys, and two is an accident of this dataset rather
than a bound.**

### 3. A per-visitor universe is tenancy, and tenancy is on the frozen do-not-build list

The only design that survives §1 and §2 isolates the *physical* data rather than the case. The
projection is id-driven and could emit prefixed rows. **Every read above it is whole-table and
unscoped**, and that is the wall:

- `graph/loader.py` builds the snapshot with `select(table)` per table, with no filter;
- the interpreter's own commitment read is `select(CommitmentLine).order_by(CommitmentLine.id)`
  ([`domain/physical.py`](../../apps/backend/src/promisepatch/domain/physical.py)), with no filter;
- `GET /api/cases` applies no permission filter at all — every authenticated caller sees every
  case, newest first.

A second universe in the same tables would be loaded into the same snapshot, two visitors'
identically-worded reports would cross, and every classification would run over a doubled graph.
Scoping those reads is **tenancy across the domain**, in a system frozen as one bakery with one
store, and tenancy is on the frozen do-not-build list. That is not a widening of a principal; it
is a change to the frozen architecture, which CLAUDE.md requires be amended in an ADR in a session
scoped to it.

The two cheaper-looking alternatives fail on the same measurement. A **reset on session issue**
destroys a concurrent visitor's live case, or degrades to a probabilistic guarantee if guarded on
"no live session". A **pool of pre-built cases** is built by attesting the same fact repeatedly,
which is the thing that broke at three.

## Consequences

- **A judge reads and says nothing, and this is now a reason rather than a default.** The refusal
  a judge meets is the domain's, and `may_speak` / `permitted_verbs` tell the screen so.
- **A judge must therefore land on a case somebody else opened.** Read-only is only tolerable if
  there is something to read, and there was not: `pp reset-demo-state` seeds orders, promises,
  resources and staff and **no case**, so the judge entry has landed on an empty list since it
  shipped. That is a provisioning defect rather than an authority one, and it is fixed separately
  by [the seeded demo case](../seeded-demo-case.md) — attested by `maya`, who is already permitted
  to attest, and never by a visitor.
- **Isolation today is total, because nothing can interfere.** Every visitor holds a distinct
  session row naming the same powerless principal, and there is no per-visitor state to leak. The
  tenth judge sees exactly what the first judge saw.
- **The conversation panel is a demonstration to a judge, not a control for one.** §5 of the UX
  contract describes the worker's interaction; a judge watches it and the screen says so.
- **This closes the question rather than deferring it.** A future decision to let a visitor speak
  is a decision to build tenancy, and it starts by amending this ADR.

## Alternatives rejected

| rejected | why |
|---|---|
| A fresh `guest` principal per demo session, confined to its own case | Confinement is real and is not the problem: a report settles shared commitment lines, so the second visitor condemns tomorrow's delivery and the third dead-ends. Measured, §2. |
| The same, with `confirm` withheld | Repeated with zero operational effects and the same outcome. Intake does the damage, not authorisation. |
| A namespaced universe per visitor | Every read above the projection is whole-table and unscoped. Scoping them is tenancy across the domain, against a frozen architecture. |
| A reset when a demo session is issued | Destroys a concurrent visitor's live case, or becomes probabilistic if guarded on "no live session". |
| A pool of pre-built cases | Each is built by attesting the same fact again, which is what failed at the third journey. |
