# The scored `SUR-1` consent ingress: how a stipulated reply reaches the deciding system

**No arm was driven, no model called, no scorer run, no AWS resource touched and no `SUR-1` result
directory opened.** `SUR-1` is still unrun, `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` is
unspent, and both evaluation holdouts stay sealed. This work changed how a declared customer reply
is *delivered* during an attempt, and nothing about what any attempt is scored on.

This closes the one material blocker [`sur1-pre-run-audit.md`](sur1-pre-run-audit.md) recorded.
That audit is history and is not edited: this document is the later truth recorded beside it.

## What was wrong

On the scored path a stipulated customer reply reached an in-memory Python list and nothing else.
`LiveWorldSink.deliver_reply` appended to the harness's own `ChannelLedger` and stopped there, so
PromisePatch never received it: no `approval_request` was bound, no sender was compared against the
channel the request was sent to, no deadline was checked against the database's clock,
`consent.read_literal` never ran and no consent decision was written.

The damage was **arm-correlated**, which is what made it a confound rather than a limitation. The
baseline is not PromisePatch and has no consent protocol: it needs the reply only to *exist* as
`E2` evidence, and it did. So the same missing door left the baseline whole and stopped the two
arms that have a consent protocol recovering anything that needs a literal yes — across the seven
scenarios holding a `CONSENT_REQUIRED` order, in the direction that favours the baseline, on the
benchmark's primary metric.

## The ingress architecture

One new module, [`scripts/sur1/bindings/consentdoor.py`](../scripts/sur1/bindings/consentdoor.py),
holding `SignedLinkDoor`: a transport that reads the signed possession link **out of the outbound
message PromisePatch itself queued**, and posts one answer to
`POST /api/customer/approval/{token}`.

```text
declared reply event
        |
        v
LiveWorldSink.deliver_reply
        |
        +--> ChannelLedger.accept(...)        always, unconditionally   -> E2
        |
        +--> ConsentDoor.offer(...)           only where a link exists  -> the consent protocol
```

The door is **optional on the sink and required by the preflight**, which are two different
statements enforced where each belongs: the event model stays provable with no database, no API and
no door, while a scored run is refused unless it carries a real one.

**It is one door for the whole run, never chosen per arm.** `LiveScenarioWorld` is a single object
serving all three arms — that is what makes *the same world* a fact about the harness rather than a
claim about it — so a door bound per arm would have made the later numbers a comparison between two
worlds. Binding it per arm was the one thing in the original brief this implementation did not do,
and the reason is that it is unnecessary: the door is **blind by construction**. It presses the link
the *driven system's own outbox* holds, so an arm that opened no approval request has no link, and
the door stays shut without ever being told who was driving.

## Baseline versus `PROMISEPATCH` / `ABLATION`

| | baseline | the two arms with a consent protocol |
|---|---|---|
| channel record (`E2`) | the reply | the same reply, byte for byte |
| approval request | none was ever opened | the one that arm actually created |
| signed link | none exists to press | read from that arm's own outbox row |
| the endpoint | never called | called once per delivery |
| consent decision | none — it has no protocol | written by the protocol, under its own lock |

The *observable customer event* is identical: one inbound message, same channel address, same
words, same provider identity, same point in the sequence. What differs is whether a running system
was also told, which is a fact about what that system did. This is the asymmetry `DR01` already
named — *delivery, not authority* — and the receipts from that rehearsal show both halves happening
live: one `harness-channel-record` with reason *no approval request was opened for this channel*,
and two `customer-approval-link` presses answered `202`.

## The authority path, and which half is proved where

The door holds no authority and decides nothing. Everything that makes a reply *authorising* is the
protocol that already existed, reached through one URL.

Proved against the real router, the real domain and the real database in
[`apps/backend/tests/test_customer_approval_link.py`](../apps/backend/tests/test_customer_approval_link.py),
which this work did not touch: the sender read out of the link's signature and compared against the
channel the request was sent to; a link minted for another channel recorded as unauthorised rather
than as consent; the deadline against the database's clock; a superseded request refused; a forged
link opening nothing; the literal parser producing one `YES` or one `NO`; one reply row bound to the
request it named; a second press absorbed; a decline never pressed into an approval.

Proved by [`scripts/tests/test_sur1_consent_ingress.py`](../scripts/tests/test_sur1_consent_ingress.py),
on synthetic non-`SUR-1` fixtures, is the **join** that was missing — that a benchmark reply reaches
that endpoint at all:

- the reply goes through the signed link the product actually sent, at
  `{base}/api/customer/approval/{token}` and no other address;
- the body is exactly `{"answer": ...}` — no sender, no channel, no clock, no free text, because the
  endpoint has no field for any of them and the channel comes out of the signature;
- a channel nobody asked, a message carrying no link, and an unreadable outbox each leave the door
  shut, with no call made and no link fabricated;
- a refused or unreachable surface fails the arming **closed** rather than recording a reply the
  product never got.

The two compose because the door's only reach into PromisePatch is that one URL, and that is read
out of the syntax rather than taken on trust: the module makes exactly one `httpx2.post`, one
`httpx2.get`, one `SELECT` — against `outbox_messages` — and names no `INSERT`, `UPDATE`, `DELETE`,
`approval_decisions` or `inbound_replies`. **No approval decision is inserted anywhere by this
harness.**

## Replay and stale safety

The door does not remember and does not branch. Both deliveries of a redelivered message are
pressed, both name the same server-derived record id, and the endpoint answers `202` to the one it
stored and `200` to the one it already held — so exactly-once is the database's unique index, not
this object's memory. That is `C07`'s shape: one decision seen twice, never two decisions.

Nothing stale can be pressed. The door reads links from `outbox_messages` and requests from
`approval_requests`, and both are emptied by the governed fixture load that every `prepare` runs, so
each attempt begins with no link, no request and no session from the last one. A test asserts those
tables are in `resettable_tables()`, which is the structural form of that claim. The door therefore
carries **no time filter deliberately**: a filter would add a clock-skew dependency between this
process and PostgreSQL that could silently drop a real link, which is the failure this whole
document exists to stop.

## `E2` equivalence

The channel record is written **first and unconditionally**, before the door is offered, so `E2`
holds the same observable reply whether a door opened, stayed shut, or refused. A test drives a sink
with a door and a sink without one and asserts the two ledgers are equal on channel address,
direction, text and provider identity.

Where an arm's own reply also lands in `inbound_replies` after its protocol binds it, that row is
that system's own record of having been told — the same class of fact as its outbox rows, which the
baseline equally does not have. It is metric-neutral: the scorer counts only `OUTBOUND` messages
against `max_customer_messages`, and reads an authorising reply with `any(...)`, so a second inbound
`YES` changes no reading.

## What this does not close

**`C02`'s free-text reply still does not reach PromisePatch.** The scenario stipulates
*"Strawberries work."* before the literal `YES`. The customer approval page offers two buttons and
no text field, so there is no honest way to put a sentence through that ingress — and inventing one
would mean this harness deciding that a sentence was a decision, which is precisely what the
product's literal parser exists to prevent. The reply is delivered to the channel record,
uninterpreted, and the door records `reason: the customer approval page offers two buttons and this
reply is neither`. The free-text apparent-intent path belongs to the Telegram channel, which is
unbuilt. This is a disclosed limitation of the transport, not of the consent protocol, and it is
**not** arm-correlated in the way the original blocker was: the reply is equally unread by every
arm.

## The preflight

`consent_ingress` is a fourteenth `REQUIRED_CHECK`, so a scored run cannot be authorised without it.
It refuses a world carrying no door, refuses a stand-in door, and otherwise asks the door to probe:
one unauthenticated `GET` at a token that cannot verify. A process holding no link secret signs
nothing, mints no link into any message and answers `503`; a process that verifies answers `404`,
and only `404` is accepted. The probe reads and writes nothing — there is no request behind that
token to answer.

Run against the local stack during this work, it passed: *`http://127.0.0.1:48000` verifies customer
approval links*.

## Frozen identities

| | |
|---|---|
| Manifest `safe-useful-recovery.v1.json` | `5718340f…e70e84c`, **unchanged** |
| Baseline prompt | `772ba460…9ce47cb1`, **unchanged** |
| Scorer `score_safe_useful_recovery.py` | v1.0.0, **unchanged** |
| Predeclaration rules | `c53d267a…1d1e1927`, **unchanged** |
| `program_set_sha` | `88db566c…ab1de649`, **unchanged** |
| All nine per-scenario world digests | **unchanged** |
| `implementation_sha` | `76eda88e…5300e883` → `34b2daae…387b79c7a9315a8c`, **re-frozen** |

One hash moved, and it is the one whose whole job is to move. `implementation_sha` is taken over the
bytes of the modules that decide what a program is and what its world does; `worldsink` gained the
door hook and `consentdoor` was added to that list, precisely so that a later change to *what a
reply reaches* cannot happen while every world digest holds still. The declared worlds themselves
are byte-identical: `declaration.differences()` is empty. No `SUR-1` fact, prompt, scorer, ground
truth, budget or label was altered.

## What this work did not do

- **It drove nothing.** No arm, no `C01`–`C09` attempt, no scorer invocation, no Bedrock, OpenAI or
  NVIDIA call, no AWS API, no deployment.
- **It changed no product behaviour and no UI.** The customer endpoint, the consent protocol, the
  parser and the workspace are untouched; the door is a caller of an endpoint that already existed.
- **It opened no holdout** and wrote no `SUR-1` capture, verdict or run directory.
- **It did not make the scored run ready.** The remaining preconditions are unchanged and are listed
  below.

## What is still open before a scored run

1. **A model this account can invoke**, and the spend authorisation, which is unspent.
2. **A different session.** The contract's freeze block is explicit that the building session is not
   the scoring session — and this session is now also a building session for the ingress.
3. **The scored preflight has still never been run against real bindings with a region set.**
   `model_identity` and the AWS half of `configuration` need an account this work did not touch.
   `consent_ingress`, `receivers` and `workspace_origin` have now each passed against the local
   stack, but never all thirteen others in one report.
4. **`C02`'s free-text delivery**, recorded above as a disclosed limitation rather than a blocker.
