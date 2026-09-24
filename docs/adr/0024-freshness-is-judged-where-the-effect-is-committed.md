# ADR-0024 — Freshness is judged where the effect is committed

Status: accepted
Date: 2026-09-24
Phase: 7

§14.3's ten checks are, in the product spec's own words, what must hold "before any write", and
§24's row *Recovery invalid before execution* adds that "validation is re-run at APPLYING, not only
at PLANNED". The build re-runs the checks' *row* half at `APPLYING`: `APPLY_RECOVERY` recomputes
the track's fingerprint inside the transaction that commits the amendment. It does not re-run the
one condition the rows cannot express. Check 6 asks that the production task be `SCHEDULED` or
held by this case **and that now < its scheduled start**; the fingerprint covers the task's state,
start and holder, but "now" is not a row.

This ADR decides which time conditions govern what, and where each is judged. It changes no
consent rule, parser, link, approval identity, request isolation, table or column.

## The evidence

Reproduced on 2026-09-24 against the local PostgreSQL through the product's own paths: the
canonical case, Tomas's literal `YES` on B's request, the worker run only until B's revalidation
recorded `PROCEED` and `apply:B` was enqueued. Then **only the clock moved** — the step runner's
`now` was advanced past B's task start (12:47) and B's approval deadline (11:47); no row was
written. The worker drained.

| read | value |
|---|---|
| revalidation of B | `PROCEED`, at 08:47 |
| B's fingerprint, before and after the clock moved | identical, and equal to the planned one |
| `apply:B` | ran at 12:48 and committed `APPLYING` and the amendment |
| the amendment | `DELIVERED` at one attempt |
| B / the case | `RECOVERED` / `RESOLVED` |
| B's production task | `SCHEDULED`, start 12:47 — already in the past when the order was changed |

The order was changed for a cake whose production start had passed, on authority that every check
in the system had last looked at four hours earlier. The same code path serves an automatic
track, whose `APPLY_RECOVERY` is enqueued by the worker's confirmation.

## Decision

### 1. The approval deadline governs the answer, not the execution

The deadline (`min(now + 24 h, start − 60 min)`, §12) is the window in which a customer's answer
may be **accepted and consumed**. It is judged where it always has been: by the parser when a
reply arrives, by the deadline sweep, and by check 7 inside the revalidation that consumes the
decision. That revalidation records `PROCEED` and enqueues the one `APPLY_RECOVERY` in a single
transaction, which is the record that the consent was spent in time.

It is not re-judged afterwards. A yes that was valid when it was consumed stays the authority for
the change it named; what may stop the change after that is the world, not the calendar of the
question. The deadline sits at least an hour before the start, so the start — decision 2 — is the
stricter physical limit and the one that protects the kitchen.

### 2. Execution freshness is judged in the transaction that commits the effect

`APPLY_RECOVERY` commits the track at `APPLYING` and the outbox row in one transaction. Before that
commit nothing exists that could be sent; after it, the effect is decided. That transaction is the
**durable commit boundary**, and everything that must still be true for an order to be changed is
judged inside it, for automatic and customer-approved tracks alike:

- the authority, re-read from rows (unchanged);
- the fingerprint, recomputed (unchanged) — the order, pinned version, constraints, reservations,
  watched resources, and the task's state, start and holder;
- **now < the scheduled start of the line's production task** — check 6's time half, the one
  condition the fingerprint cannot see. A task or start that cannot be read fails closed.

A failure takes the existing apply-time refusal: the track goes to the owner as `PLAN_STALE` with
its scheduled work held, nothing is emitted, and nothing is re-planned — the checklist had already
passed, and a fresh plan would spend the customer's yes on something they were never asked about.

### 3. After the commit, the outbox delivers what was decided

The dispatcher is given **no** time gate for an amendment. Its first attempt follows a committed
claim; any later attempt may follow one the order system accepted and never acknowledged, and a
refusal at that point would record "not changed" for an order that may have been changed. The
effect is re-sent under its stable idempotency key, which the order system collapses. "Nothing
sent" is provable only while no attempt has been claimed; "the provider may have accepted" is the
state from the first claim onwards, and the ledger never treats the second as the first.

## Answers

1. **Does the approval deadline govern execution?** No. It governs acceptance and consumption of
   the answer; execution is governed by the task's start and the fingerprint.
2. **What must stay true until the first external mutation?** The authority chain, every watched
   row (the fingerprint), and now < the task's scheduled start — judged at the commit of the
   effect, which is the last instant at which "nothing has been sent" is certain.
3. **What is the durable commit boundary?** `APPLY_RECOVERY`'s transaction: track `APPLYING` and
   the outbox row, together.
4. **Why not check at dispatch?** Because from the first claim onwards the dispatcher cannot tell
   "nothing sent" from "sent, acknowledgement lost", and the only refusal it can record would also
   route to `DOWNSTREAM_UNAVAILABLE`, which would say the order system failed when it did not.

## Rejected

- **Re-check the approval deadline at apply.** Turns worker latency into customer expiry: a yes
  consumed in time would expire because a queue was slow, and the order would be refused for a
  reason that is not about the order.
- **Re-run the whole checklist at apply.** Check 1 cannot hold there (the case has left
  `REVALIDATING`), and checks 2–5 are already the fingerprint.
- **A time gate in the dispatcher, or on retry.** See answer 4. It could cancel, and misreport, an
  effect the order system may already hold.
- **Refuse only the first dispatch attempt (`attempts == 1`).** Provable, but it needs a second
  abandon semantics beside `DOWNSTREAM_UNAVAILABLE` for a window that is normally the same worker
  cycle as the apply. Recorded as a limitation instead.

## Consequences

- An amendment is never committed after its production start has passed, whether the delay was a
  paused worker, a backlog or a crash-and-restart before `APPLY_RECOVERY` ran.
- **Residual window, disclosed:** between `APPLY_RECOVERY`'s commit and the dispatcher's first
  claim. The worker runs the step and then dispatches in the same cycle, so the window is normally
  milliseconds; a crash inside it followed by an outage past the start still dispatches late.
- **Residual time sensitivity, disclosed:** substitute allocation reads `now` too — an expected
  supply line that becomes overdue without a row changing can alter availability. Automatic tracks
  do not re-run the allocation at apply; approved tracks ran it in check 5 at revalidation.

## What this does not do

It changes no consent rule, no approval deadline, no parser or link, no approval identity
(ADR-0022), no round semantics (ADR-0023), no observer permission, and nothing about promises the
exception does not reach. It adds no state, step kind, table or column.
