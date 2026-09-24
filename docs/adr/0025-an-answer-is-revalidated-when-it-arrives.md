# ADR-0025 — An answer is revalidated when it arrives, not when the last sibling's does

Status: accepted — amends [ADR-0023](0023-a-re-plan-returns-the-case-to-planned-for-that-track-only.md)
on which states read a reply and where `RECONCILING` goes next
Date: 2026-09-24
Phase: 7

§14.2 lists **"a literal ApprovalDecision received"** as its own exit from `WAITING`, and draws the
return: "RECONCILING → WAITING if other tracks are still waiting". The frozen architecture plan draws
the same arrow ("ApprovalDecision(parser=LITERAL) → case WAITING → REVALIDATING"). The build moved
`WAITING → REVALIDATING` only once **no** request on the case was still open, so one case state
gated every track's revalidation on the slowest customer. No ADR chose that; the rule dates from
`63141e9`.

It changes no consent rule, parser, link, approval identity, request isolation, table or column,
and it adds no case state and no step kind.

## The evidence

Reproduced on 2026-09-24 at `fe0cf80` through the product's own paths: Proof C's world
(`with_charlotte_variant` authored, C's constraint set to ask), so the canonical report asks Tomas
about B and the Okafor-Reyes wedding about C. The fixture's own schedule gives unequal windows —
B's deadline, and B's production start an hour after it, both fall hours before C's deadline.
Tomas answered a literal `YES`; C's customer said nothing. No workflow row was written by hand;
only the step runner's clock moved, and only after the first observation.

| moment | case | B | `revalidate:B` |
|---|---|---|---|
| B's yes drained | `WAITING` | `WAITING_FOR_CUSTOMER`, request `ANSWERED` | none, and nothing outstanding |
| clock past C's deadline | — | **`PENDING`**: refused `STALE` (start passed) and re-planned | ran only now |

Tomas answered in time, and his yes was never looked at until C's window closed. The regression
`test_silent_sibling.py` fails six of its eleven tests at that SHA, each on this.

## Why relaxing the gate alone is wrong

The gate was load-bearing. Dropping it from `WAITING` alone strands the *other* track instead:

1. a decision arriving in `REVALIDATING` asked `settled_case_state`, which had no `REVALIDATING`
   exit, and enqueued nothing — a second answer would never be checked;
2. a decision arriving in `RECONCILING` reached a rule that returned to `WAITING` only while a
   request was *open*, and resolved only when every track was terminal — with an answered,
   unchecked track it did neither;
3. a round that ends at `PLANNED` (ADR-0023) with a sibling's request still open would skip that
   sibling's reply, because a reply was not read in `PLANNED` at all, and the customer's second
   press of a signed link proposes the same reply id and writes nothing: a lost answer;
4. `RECONCILING` could be entered only once, because its step key was one per case.

## Decision

One definition, read from rows: an **unchecked approval** is a track `WAITING_FOR_CUSTOMER` whose
carried request is `ANSWERED` and decided, and for which no revalidation step with that request's
key exists. A decline or an expiry is not one — both escalate the track where they happen and
leave nothing to check. An `UNAUTHORIZED` refusal is not one either: its revalidation exists.

### 1. An unchecked approval opens a revalidation from wherever the case can take it

- **`WAITING`**: an unchecked approval moves the case to `REVALIDATING`, whether or not another
  request is still open. This is §14.2's per-decision exit. With none, the rule is unchanged.
- **`EXECUTING`**: once nothing is runnable, an unchecked approval goes to `REVALIDATING` before
  the case would otherwise wait on an open sibling — the build already skipped `WAITING` for an
  answer already in the database; it now does so per answer.
- **`REVALIDATING`**: an approval that arrives during a round **joins it**. The decision's own
  transition re-enters `REVALIDATING`, and `work_for_case` proposes one revalidation per settled
  request; the ones that exist are declined by the unique index, and the new one becomes part of
  the round. ADR-0023's rule is untouched: the round ends once, when its last revalidation or
  re-plan finishes, whichever claim order the worker took.
- **`RECONCILING`**: see 2.
- **`PLANNED`**: a reply **is read** and a literal decision is recorded; the case does not move.
  ADR-0023's `PLANNED` waits on a worker's yes for the re-planned track, and still never moves
  itself on a sibling. The answer is checked by whichever transition leaves `PLANNED`: the
  confirmation (through `EXECUTING`, above) or §14.1's ten-minute escalation (through
  `RECONCILING`, below). The wait is bounded at ten minutes by a timer that is already armed.

### 2. `RECONCILING` finishes what it is applying, and then goes where the rows say

`RECONCILING` is where approved changes are applied (§14.1). It now leaves only when no recovery
is in flight — no track `APPLYING` and no unsettled `APPLY_RECOVERY`, `FINALIZE_RECOVERY` or
`ABANDON_RECOVERY` step other than the one asking — and then, in this order:

1. to **`REVALIDATING`** if an unchecked approval exists (a new edge; the answer that arrived
   while the sibling's change was being made is checked now, against a world in which that change
   has settled — so check 5 counts the sibling among the tracks "already RECOVERED");
2. to **`WAITING`** if a track still waits on an open request (§14.2's drawn edge, now taken only
   after the change in flight has settled, so `WAITING` keeps §14.1's "nothing consequential runs");
3. to **`RESOLVED`** if every track is terminal and nothing is outstanding (unchanged).

The recovery step that settles last asks the question, as it always has, so no case waits on a
reconciliation step that already ran.

### 3. `RECONCILING` may be entered more than once

A case can now go `REVALIDATING → RECONCILING → WAITING → REVALIDATING → RECONCILING`. Each entry
creates its own `RECONCILE_CASE` step: `reconcile:<case>` for the first, `reconcile:<case>:<n>` for
the *n*-th after *n* have settled. The index is read from the step ledger, so two transitions
reaching one boundary while its step is outstanding propose the same key and the database declines
the second, exactly as before.

## Answers

1. **Can one customer's answer authorise another's promise?** No. Nothing here touches a
   revalidation's inputs: each is keyed by its track and request (ADR-0022), check 8 compares the
   decision's sender with that request's own channel, and the amendment's authority check reads the
   revalidation of the request its own track carries.
2. **Can a later answer, a timeout or a decline undo or replay the first change?** No. The first
   track is `RECOVERED`; a later round's `work_for_case` proposes its revalidation key again and
   the index declines it; its apply and finalize keys already exist. A decline or expiry escalates
   only the track it is about.
3. **Is an answer ever checked twice?** No. One revalidation per request, by key.
4. **Does the case ever rest with nothing to move it?** Every new rest point has a mover: an
   unchecked approval in `WAITING`/`RECONCILING` is moved by the transition that produced or
   finished it; in `PLANNED`, by the confirmation or the armed ten-minute timer.
5. **Does `WAITING` still mean nothing consequential runs?** Yes. `WAITING` is entered from
   `EXECUTING` only with nothing runnable, and from `RECONCILING` only with no recovery in flight.

## Rejected

- **Relax the `WAITING` gate only.** Strands the other track (the four failures above).
- **`REVALIDATING → WAITING` directly when a request is still open.** Shorter, but the approved
  change would then be applied while the case says `WAITING`, which §14.1 defines as the state in
  which nothing consequential runs.
- **Check an answer that arrives during `RECONCILING` at once, beside the change in flight.**
  Its check 5 would not count the sibling whose substitute is being committed (§14.3 counts
  tracks "already RECOVERED"), and it would need a second concurrent round.
- **Leave replies unread in `PLANNED`.** A literal yes would be skipped and, because a second
  press of the same link proposes the same reply id, lost for good.
- **Per-track case state.** The state machine §14.1 draws is per case.

## Consequences

- Tomas's yes is revalidated and applied inside his own window; the case then waits on C, and says
  so, with nothing running.
- C answering later is revalidated once, in its own round; C timing out or declining escalates C
  only. B's rows are never revisited.
- ADR-0023's two-asked round, in both claim orders, is unchanged when both answers are read before
  either checklist runs — the second now joins the first's round instead of opening it.
- A case may pass through `RECONCILING` more than once; each pass has its own reconciliation step.

## What this does not do

It adds no consent path, no approval identity, no state and no step kind, changes no parser or
link, and touches no promise the exception does not reach. It does not change what an escalation,
a withdrawal or a re-plan does to a track.
