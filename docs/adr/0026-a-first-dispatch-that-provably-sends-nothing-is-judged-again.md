# ADR-0026 — A first dispatch that has provably sent nothing is judged again

Status: accepted — amends [ADR-0024](0024-freshness-is-judged-where-the-effect-is-committed.md)
on where "nothing has been sent" ends
Date: 2026-09-24
Phase: 7

ADR-0024 judged execution freshness in `APPLY_RECOVERY`'s transaction, called that commit "the
last instant at which 'nothing has been sent' is certain", and gave the dispatcher no time gate.
It considered refusing the first dispatch attempt only, called it provable, and rejected it
because it "needs a second abandon semantics beside `DOWNSTREAM_UNAVAILABLE`", recording the
window between the commit and the first claim as a disclosed residual.

The wording and the implementation disagree on one point, and the residual is larger than its
description. The commit is not the last instant at which nothing has been sent: **nothing can be
sent until a dispatch claim has committed**, so "nothing sent" stays provable until the first
claim. And the window is not "normally milliseconds" whenever it matters: a worker that dies
after the commit and stays down past the start dispatches the amendment late on restart.

It changes no consent rule, parser, link, approval identity, request isolation, table, column,
step kind or escalation reason.

## The evidence

Reproduced on 2026-09-24 at `fe0cf80` through the product's own paths: the canonical case,
Tomas's literal `YES`, the worker run until B's revalidation recorded `PROCEED`, then
`APPLY_RECOVERY` run while B's start was ahead, with the worker killed at the product's own
`AFTER_TRANSITION_COMMIT` crash point. The amendment row was `PENDING` at **zero attempts**; no
transport call had carried its key. Then only the clock moved, past B's production start, and a
fresh worker drained: its first dispatch **sent the amendment** and the order changed for a cake
whose start had passed. `test_a_committed_amendment_never_attempted_is_not_first_sent_after_its_start`
fails on that at `fe0cf80`.

## Decision

### 1. The effect is decided at the commit; it becomes irrevocable at the first claim

`APPLY_RECOVERY`'s transaction still decides the effect and still judges everything ADR-0024
lists — authority, fingerprint, and now < the line's scheduled production start. The outbox row
it commits is a decision to send, not a send.

Every dispatch claim commits `attempts + 1` in its own transaction **before** any provider call
(`claim_effect`). So:

- a claim that reads **`attempts == 1`** is provably the first: no earlier claim committed, and a
  provider call can only follow a committed claim, so **no earlier call exists**;
- a claim that reads **`attempts > 1`** follows a claim that may have reached the provider — the
  process may have died before the call, during it, or after it with the acknowledgement lost,
  and the rows are identical in all three.

### 2. The first claim of an order amendment re-judges check 6's time half

On a claim at `attempts == 1` of an `ORDER_AMEND` effect, before the adapter is called, the
dispatcher asks the one question ADR-0024 moved to the commit and the clock can still change:
**is now before the line's scheduled production start?** A start that cannot be read fails closed.

If not, the effect is refused **unsent**: it is recorded as a terminal failure at one attempt with
no provider reference, and its failure continuation runs. That continuation reads the refusal off
the row and ends the track exactly as a refusal at `APPLY_RECOVERY` would — `ESCALATED` with
`PLAN_STALE`, its scheduled work held, nothing re-planned — **not** `DOWNSTREAM_UNAVAILABLE`, which
would say the order system failed when it was never asked. That is the "second abandon semantics"
ADR-0024 declined to build; it reuses an existing reason and an existing ending.

### 3. From the second claim on, there is no time gate

Unchanged from ADR-0024: a retry after an uncertain attempt goes out under the same idempotency
key, even past the start, and the order system collapses it. Refusing there could record "not
changed" for an order that has changed.

### 4. The approval message's window says only what it knows

The same discriminant governs what the approval-message window gate may *say*. It already refuses
a message whose window has closed on every claim, which is right: a question nobody can answer is
not worth delivering. Its text claimed the window closed "before the message could be delivered"
— false when an earlier attempt may have reached the customer. At `attempts == 1` it now says the
message was not sent; after that, that an earlier attempt may have reached the customer.

## Answers

1. **Is the outbox commit the irrevocable boundary?** No. It is where the effect is *decided*.
   The first dispatch claim is where it becomes irrevocable, because it is the last point at which
   "nothing was sent" is provable from rows.
2. **Must a provably never-attempted amendment be judged again at its first dispatch?** Yes, on
   the production start, and only on that.
3. **How is never-attempted told from uncertain acceptance?** By the claim's own `attempts`:
   `1` is proof that no call exists; anything else is uncertainty, and is treated as possible
   acceptance.
4. **Is anything re-judged after an uncertain attempt?** No.

## Rejected

- **Keep the commit as the boundary and disclose the residual** (ADR-0024). The residual is the
  exact harm ADR-0024 exists to prevent, reachable by one crash and one outage, and it is provably
  closable.
- **Gate every claim.** Could cancel, and misreport, an amendment the order system already holds.
- **Gate the first claim on the fingerprint too.** The order system already refuses an amendment
  against a version it no longer holds; the start is the one condition only the clock can move.
- **Judge inside the claim transaction.** The refusal must lock the case before the outbox row,
  and the claim holds the outbox row; the refusal would invert the lock order every other
  transaction keeps.
- **A new escalation reason or step kind.** `PLAN_STALE` with the work held is already the answer
  for "valid when decided, no longer valid before it reached anyone".

## Consequences

- An amendment never reaches the order system for the first time after its production start,
  whatever delayed the first dispatch.
- **Residual, disclosed and irreducible:** a dispatcher that dies between committing the first
  claim and calling the provider leaves rows identical to one that died after the call. The next
  claim is uncertain and ungated, so a worker that dies inside that window *and* stays down past
  the start still delivers late — once, under the same key. The window is two statements of one
  dispatcher with no network call between them.
- Substitute allocation's own clock sensitivity on automatic tracks (ADR-0024) is unchanged.

## What this does not do

It changes no approval deadline, consent rule, parser or link, no approval identity (ADR-0022),
no round semantics (ADR-0023, ADR-0025), no observer permission, and nothing about promises the
exception does not reach. It adds no state, step kind, escalation reason, table or column.
