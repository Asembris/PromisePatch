# ADR-0022 — An approval episode is opened by the confirmation that asks

Status: accepted
Date: 2026-09-23
Phase: 6

§14.4 says that when a customer's yes goes stale, the old request is `SUPERSEDED`, the promise is
re-planned, and "a new request (if any) follows". §23 says the same: "new request if still
needed". The build could not send one. Every approval identity was derived from the track alone,
so the first ask used the only identity a track would ever have, and a re-planned promise that
still needed its customer was confirmed, reported as `awaiting_approval`, and then never asked.
Its case stopped at `EXECUTING` with nothing outstanding and nothing armed to wake it.

This ADR decides what identifies one approval episode, so that a re-ask is a new episode and a
retry of the same one is not. It changes no consent rule, no parser, no link format, no
idempotency-key shape, no table and no column.

## The evidence

Reproduced on 2026-09-23 through the product's own paths against the local PostgreSQL: the
canonical case, the customer's literal `YES` on request A, the order moved one version, the
worker drained. Revalidation refused at check 2, `REPLAN_TRACK` superseded A and unbound the
track, and the case returned to `PLANNED`. A worker then approved and confirmed the new plan, and
the confirmation listed the track under `awaiting_approval`. After a full drain:

| read | value |
|---|---|
| case | `EXECUTING` |
| the asked track | `PENDING`, `approval_request_id` null |
| approval requests | one: A, `SUPERSEDED` |
| outstanding steps | none |
| `approval:<track>` | `DONE`, from A |
| timers | A's deadline only, a no-op on a superseded request |

The re-plan also chose **the same option id** A was asked about, because an option's id is
derived from the track and the engine's option. So the defect is two collisions, not one:

1. **The request step.** `approval:<track>` was already `DONE`, so the confirmation's enqueue was
   declined by `uq_case_steps_case_step_key` and no step ran.
2. **The request itself.** `request_id_for(track, option)` would have reproduced A's primary key.
   Had the step run, the insert would have written nothing, and the track would have been
   re-bound to A — superseded, decided, and carrying the customer's old yes.

Every step after the request inherits the same fault: `approval-sent:<track>`,
`approval-abandoned:<track>`, `revalidate:<track>` and `replan:<track>` were all `DONE` from
episode A. And the authority check that lets an approved amendment reach an order,
`recovery._approved_and_revalidated`, looked for a `PROCEED` under `revalidate:<track>`, which
is to say under a key that did not say *which* request had been revalidated.

## Decision

### 1. One approval episode is one track asked under one confirmed plan

A customer is asked because a worker confirmed a plan that needed their answer
([ADR-0018](0018-a-plan-confirmation-spends-a-human-approval.md)). The plan confirmation is
already bound to a `plan_id`, and `plan_approvals` is already unique on `(case_id, plan_id)`. A
plan identity covers the case version, so no two confirmations of one case can ever quote the
same one. That is the episode's identity: **the track, and the plan whose confirmation asked**.

- The request step's key is `approval:<track>:<plan_id>`.
- The request's id is `uuid5("approval:<track>:<option>:<plan_id>")`.

Everything downstream of a request is about that request, and names it:
`approval-sent:<track>:<request>`, `approval-abandoned:<track>:<request>`,
`revalidate:<track>:<request>` and `replan:<track>:<request>`.

### 2. The first ask on a track keeps the identity it has always had

A track's first ask is unique by construction: analysis runs only before a confirmation, and the
only way a confirmed case returns to `PLANNED` is a `REPLAN_TRACK` that supersedes the request it
replaces. So "first ask" is exactly "this track has no approval request yet", read under the track
locks the confirmation already holds. It keeps `approval:<track>`, `uuid5("approval:<track>:<option>")`
and every per-track downstream key, byte for byte.

A request knows which of the two it is without being told: a first ask's id is the per-track
derivation of its own track and option, and a later ask's id cannot be, because its derivation
includes a plan identity. `approvals.ask_scope(request)` is `None` for the first and the request's
own id for every later one, and every downstream key is built from it.

### 3. A step about one request acts only on that request

A sent, abandoned, revalidation or re-plan step acts only if the track still carries **the
request its key names**; otherwise it is skipped and changes nothing. A request step does not ask
about a track that already carries a request. The amendment's authority check reads the
revalidation of the request the track carries, and the amendment's provenance names that
request's decision — never an earlier one.

## Answers

1. **What identifies one approval episode?** The track and the `plan_id` whose human-approved
   confirmation asked. For a track's first ask the plan is implicit, because there is exactly one.
2. **What makes a re-ask new rather than a retry?** A new confirmation of a new plan, after a
   re-plan superseded the previous request. A retry replays the same step key, proposes the same
   request id and the same `pp:approval:<request>` key, and every unique index declines it.
3. **Can the same option be asked again after the world changes?** Yes, as a new request. §14.4
   requires it, and the option row the customer was first asked about already survives its own
   supersession.
4. **How does the old link and decision stay bound to A?** The link is minted from A's id and the
   channel, and its reply id from A's id; nothing about B is derivable from it. A reply on A's
   link reaches A, which is `SUPERSEDED`, and is recorded as `ALREADY_SETTLED`. A's decision is
   unique on A's id and is never read for B: revalidation reads the decision of the request the
   track carries.
5. **How do retries and crashes avoid duplicates?** All identities are derived, never minted.
   A crash before the request commit leaves nothing; the retried step proposes the same request id
   and the same message key. A confirmation replayed by command id returns before it enqueues, and
   a second command for the same plan is refused because the case is no longer `PLANNED`.

## Rejected

- **A minted key (`uuid4`, a clock, an attempt number).** Not replay-safe: a replayed enqueue or
  a crash between two transactions would mint request C.
- **Resetting or deleting the `DONE` step.** The step ledger is history, and the unique index is
  the idempotency guarantee. Rewriting either to make room would make both lie.
- **Keying by fingerprint.** A world that moves and moves back reproduces the same fingerprint,
  and with it A's identity.
- **A per-track ordinal (count of earlier requests).** Deterministic, but it names nothing that
  authorised the ask. `plan_id` is the authority's own identity.
- **Chaining from the predecessor request.** Needs "the latest request" by timestamp, and a
  replayed enqueue after B exists would derive C from B.
- **Escalating on re-plan instead of asking again.** Live, but it contradicts §14.4 and §23,
  which require the new request when one is still needed.
- **Making every ask plan-scoped, first asks included.** Changes the identity of every first ask,
  every in-flight row's derivation and the meaning of recorded evidence, for no liveness gain:
  a first ask was never the problem.

## Consequences

- A promise re-planned after a stale yes that still needs its customer is asked again, with a
  fresh request, deadline, message and link. A promise that goes stale a second time is re-planned
  a second time.
- A customer can receive a second approval message on one order, after the §14.4 notice that
  their order changed. That is the sequence the spec describes, not a new one.
- No migration. `step_key` is `VARCHAR(128)`, and the longest new key is 110 characters.
- Rows written before this change keep executing: a per-track key still resolves to the track's
  first ask.

## What this does not do

It adds no consent path, reads no Telegram inbound, lets no model or service credential create an
approval, and changes nothing about which tracks are asked. It does not change what happens to a
case with two approval tracks when only one of them is re-planned.
