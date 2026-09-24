# ADR-0023 — A re-plan returns the case to PLANNED for that track only

Status: accepted — amended by [ADR-0025](0025-an-answer-is-revalidated-when-it-arrives.md) on
which states read a reply and where `RECONCILING` goes next
Date: 2026-09-23
Phase: 6

§14.2 says what one revalidation round does, **per track**: "valid + APPROVE → RECONCILING; …
fingerprint mismatch → STALE → re-plan (case returns to PLANNED for that track only …)". The
build keeps one state per case, and it read "returns to PLANNED" as a statement about the whole
case. With one asked track the two readings agree. With two, they do not, and the build strands a
promise either way.
[ADR-0022](0022-an-approval-episode-is-opened-by-the-confirmation-that-asks.md) made a re-planned
promise askable again and said explicitly that it did not decide this shape. This ADR decides it.

It changes no consent rule, no parser, no link, no approval identity, no table and no column.

## The evidence

Reproduced on 2026-09-23 through the product's own paths against the local PostgreSQL: the Proof C
world (the fixture's own `with_charlotte_variant`, and C's constraint set to ask), so the
canonical report asks two customers — B (EXT-B) and C (EXT-C). Both said a literal `YES` on their
own request; C's order then moved one version; the worker drained. `REQUEST_APPROVAL`,
`MARK_APPROVAL_SENT` and the decisions are the product's; nothing was inserted. The two
revalidations are created by one transaction, so which runs first falls to their random ids. Both
orders were forced and both fail:

| order | what happened | end state, fully drained |
|---|---|---|
| C's revalidation first | C `STALE`, `replan:C` enqueued. B's revalidation `PROCEED`; it counted only outstanding *revalidations*, saw none, and moved the case to `RECONCILING`. `replan:C` then skipped: it runs only in `REVALIDATING`. Reconcile skipped: C is not terminal. | case `RECONCILING`, C `STALE` for ever — never re-planned, re-asked or escalated, nothing armed |
| B's revalidation first | B `PROCEED`, C still outstanding, no move; `apply:B` enqueued. C `STALE`, `replan:C`. `apply:B` ran and **the amendment was delivered to the order system**. `replan:C` moved the whole case to `PLANNED`. `finalize:B` then skipped: recovery steps do not run in `PLANNED`. | case `PLANNED`, B `APPLYING` for ever with its order already changed; after the worker re-confirmed C and C was asked again, the case sat at `EXECUTING`, because an `APPLYING` track counts as runnable and it can never wait |

The second is the worse of the two: the order system holds a change the promise ledger never
settles, and the screen says the change is still being made.

## Root cause

Two case-level exits from one round, each blind to the other:

1. **The round ended before it finished.** A revalidation moved the case on when no other
   *revalidation* was outstanding, but a re-plan is part of the same round — §14.2 lists it among
   the round's per-track outcomes — and was not counted.
2. **The re-plan moved every track's case.** `PLANNED` means "awaiting a worker's yes"; for a
   re-plan that yes is about the re-planned track only. A sibling whose own yes had already passed
   revalidation was made to wait for it, by guards that assumed a planned case had nothing in
   flight — true until a sibling's `PROCEED` could precede a re-plan.

## Decision

### 1. A revalidation round ends once, when its last revalidation or re-plan finishes

A revalidation or a re-plan moves the case only when no other revalidation or re-plan of the case
is still outstanding. Whichever finishes last moves it, and the destination is read from rows:

- **`PLANNED`** if a track is `PENDING` — which in a revalidating case means a re-plan produced a
  plan that needs a worker's yes. A confirmed case reaches `REVALIDATING` only when nothing is
  runnable, so no other `PENDING` track can be there.
- **`RECONCILING`** otherwise.

The move to `PLANNED` arms §14.1's ten-minute timer, as it always has when a re-plan made it.

### 2. A track whose own yes passed revalidation finishes its recovery at `PLANNED`

`APPLY_RECOVERY` and `FINALIZE_RECOVERY` run in `PLANNED` as well as in `EXECUTING`,
`REVALIDATING` and `RECONCILING`. Their authority is their own track's: the worker's confirmation
of the plan that asked, the customer's literal yes, and a `PROCEED` against a fresh snapshot. A
sibling's re-plan touches none of those, and the apply step recomputes its own fingerprint in the
transaction that emits the amendment, so a sibling whose world has since moved still goes to the
owner rather than to the order system. `PLANNED` waits on a worker's yes for the re-planned track,
and only that track.

Nothing else changes: a planned case still never moves itself on a sibling's finish
(`settled_case_state` has no `PLANNED` exit), a confirmation still acts only on `PENDING` tracks,
§14.1's escalation still escalates only `PENDING` tracks, and a revalidation still runs only in
`REVALIDATING`.

## Answers

1. **Can a sibling's yes authorise the re-planned track?** No. Every revalidation, apply,
   finalize and re-plan step is keyed by its track and, since ADR-0022, by its request; the
   amendment's authority check reads the revalidation of the request its own track carries.
2. **Can the re-plan supersede, re-ask or cancel the sibling?** No. The re-plan supersedes the
   request of the track it re-plans; the re-confirmation partitions `PENDING` tracks only, so an
   `APPLYING` or `RECOVERED` sibling is neither asked nor applied again, and its revalidation key
   is declined if the next round proposes it.
3. **Does the case ever rest with nothing to move it?** Not in this shape: every track either
   settles or is `PENDING` under an armed `PLANNED` timer, and the last step of the round is the
   one that moves the case.
4. **Why may an order change while the case says `PLANNED`?** Because the change was authorised
   before the re-plan, by a different customer about a different order, and checked again against
   the world as it is. Holding it until an unrelated worker confirmation arrived would leave a
   delivered amendment unrecorded — the failure reproduced above.

## Rejected

- **Run the re-plan in `RECONCILING` too.** Fixes the first order only; the second still strands
  the sibling at `PLANNED`.
- **Allow recovery steps in `PLANNED`, and nothing else.** Fixes the second order only; the first
  still moves the case to `RECONCILING` before the re-plan runs.
- **Defer the move to `PLANNED` until every sibling has settled.** A sibling's finalize waits on
  the order system's echo, so the re-planned promise would wait on another customer's order, and
  a new `RECONCILING → PLANNED` edge would be needed that §14.1 does not draw.
- **Escalate the stale track instead of re-planning it when it has a sibling.** Live, but
  contradicts §14.4 and §23 exactly as ADR-0022's rejection of the same idea says.
- **A per-track case state.** The state machine §14.1 draws is per case; this is the smallest
  reading of "for that track only" that the existing columns can carry.

## Consequences

- In a case with two asked promises, one stale and one approved, the approved change is applied
  and settled, and the stale one is re-planned, re-confirmed and asked again, in either order.
- The plan identity covers the case version and every track's state, so a sibling settling while
  the case is `PLANNED` makes a plan read before it stale. A worker who confirms that older plan is
  refused and re-reads; that is the existing stale-plan protection, not a new one.
- The `PLANNED` headline said "Nothing has been done yet" at every planned case, including a
  re-planned one whose other promises had already been changed, messaged or escalated. That was
  untrue before this ADR, and this ADR makes an order change *during* `PLANNED` reachable, so a
  planned case that has already acted says so instead. A first plan is recognisable from rows:
  every track is `PENDING`, `UNAFFECTED` or `LINKED`. Presentation only; the headline, the plan
  offered and the next action are unchanged.

## What this does not do

It adds no consent path, no approval identity and no state. It does not make any case state
per-track, does not change which tracks are asked, and does not touch withdrawal, whose own
stand-down settles every unclaimed step whatever the case state.
