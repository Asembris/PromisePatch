# The customer approval link

The consent protocol has had no transport since it was built. A customer's reply could reach it
only as a row somebody wrote into `inbox_events` by hand — in a test fixture, or from the CLI.
This slice gives it one: a signed link, a page a person can read on a phone, and two buttons.

**It is a transport and nothing else.** No check moved, no table changed, and no new thing can
authorise anything. Everything below is either the existing protocol, unmodified, or a statement
about what the new surface deliberately cannot do.

## What was already there

Found before anything was written, and reused unchanged:

| Piece | Where |
|---|---|
| The literal parser — the only thing that can read a yes | [`domain/consent.py`](../apps/backend/src/promisepatch/domain/consent.py) |
| Request, deadline timer, expiry, reply, decision | [`domain/approvals.py`](../apps/backend/src/promisepatch/domain/approvals.py) |
| Store-first inbound records, deduplicated by the database | [`domain/inbox.py`](../apps/backend/src/promisepatch/domain/inbox.py) |
| The reply normaliser and `customer-reply` source | [`domain/handlers.py`](../apps/backend/src/promisepatch/domain/handlers.py) |
| The worker's vocabulary for a promise | [`domain/status_view.py`](../apps/backend/src/promisepatch/domain/status_view.py) |

The path a reply takes was already complete:

```
inbox_events(source="customer-reply")
  -> handlers.normalize_inbound      reads the stored row, reaches nothing outside it
  -> approvals.bind_customer_reply   resolves which case, authorises nothing
  -> RECEIVE_CUSTOMER_REPLY          under the case lock:
       sender vs the channel the request was sent to   (§14.3 check 8)
       request still open
       deadline vs the *database's* clock
       consent.read_literal
  -> approval_decisions              append-only, one per request, parser='LITERAL' only
  -> REVALIDATING -> recovery, or the track escalates
```

The gap was the first line. This slice fills exactly that line.

## The link

[`domain/customer_link.py`](../apps/backend/src/promisepatch/domain/customer_link.py) is pure —
standard library and nothing else, no database, no clock, no parser — and is held to that by an
import-linter contract, *a possession link names a request and decides nothing*, which bans
`domain.consent` by name.

A token is `v1.<payload>.<hmac>` over the version, the request id and the channel.

- **It proves possession, never identity.** There is no account behind a bakery customer, no
  password, and nobody to check. A forwarded link is held by whoever it was forwarded to and
  this module cannot tell. The result type is called `Possession` and carries two fields, which
  a test asserts, so nothing downstream can start reading it as proof that a named person acted.
- **The channel is inside the signature, and is checked afterwards against the request.** It
  would be simpler to read the channel off the request row once the id is known, and it would
  turn §14.3 check 8 into a tautology. The link carries the channel it was minted for, the
  transport reports it as observed, and the existing check stays a real one.
- **There is no expiry in the token.** The request's deadline is in the database and is compared
  under the request's own lock. A second, weaker deadline held in a customer's browser is
  exactly the ambiguity the consent protocol exists not to have.
- **Minting is deterministic**, so a resent message carries the same link rather than a second
  door to the same question.

`PP_CUSTOMER_LINK_SECRET` and `PP_CUSTOMER_LINK_BASE_URL` are both required. Unset closes the
surface — a link nobody signed is a link anybody could write.

## How a customer gets one

The link goes in the payload of the outbound message queued for the customer's own channel,
beside the text rather than inside it: §13.6's wording is frozen and a transport may not edit
it. A channel that can render a link renders this one; a channel that cannot sends the words
unchanged and loses nothing, because the two literal words remain the whole protocol.

**Nothing stores the link and no surface hands one out.** It is not on the worker's workspace,
not in the case API and not in the MCP tools. That is deliberate: a link a worker could read is
a link a worker could open, and possession would stop meaning anything. The only reader is
whoever received the message.

## The surface

Two endpoints, [`api/routers/customer.py`](../apps/backend/src/promisepatch/api/routers/customer.py),
unauthenticated because their caller cannot be authenticated:

- `GET /api/customer/approval/{token}` — the reading, from rows.
- `POST /api/customer/approval/{token}` — one answer.

It is **not** `/api/conversation/approve`. That is a worker agreeing to a PromisePatch plan,
behind a session, a role and a CSRF token, spending a durable approval recorded where a person
was authenticated (ADR-0018). This is a customer answering about their own order. Nothing in
this module reaches the plan side.

What the POST body may carry is one field with two permitted values, `APPROVE` or `DECLINE`,
refused by the schema before a handler runs. There is no sender field, no channel field, no
timestamp and no free text — the channel comes from the signature and the clock from the
database. The two words that reach the parser are composed on the server from
`consent.APPROVE_TOKEN` and `consent.DECLINE_TOKEN`, so a page cannot put a sentence in front of
a parser whose whole value is that it is never asked to interpret one.

**One answer per link, enforced by an index.** The stored record's id is
`approvals.link_message_id(request_id, channel)` — derived from the request and the channel and
*not* from the answer — so a second press of either button proposes a key `inbox_events` already
holds and writes nothing. A decline cannot be pressed into an approval, and that is a unique
constraint rather than a branch somebody has to remember.

**A link for another channel is let through, not refused.** The read shows nothing, but the
answer is written, so it reaches the one check in PromisePatch that can refuse a reply because
of who sent it. An impersonation becomes an audited `UNAUTHORIZED_APPROVAL` row and the owner's
attention, where a quiet 404 would have made it nothing anybody could later see.

## What the customer sees

[`CustomerApproval.tsx`](../apps/frontend/src/features/customer/CustomerApproval.tsx), reached at
`?approve=<token>`. The shell dispatches on that parameter before either product mounts, so the
page opens no session and never shows a sign-in form for an account that does not exist.

Phases, which are the customer's vocabulary and not the worker's: `OPEN`, `RECEIVED`,
`APPROVED`, `DECLINED`, `EXPIRED`, `SUPERSEDED`, `CLOSED`.

`RECEIVED` is the important one. Between the press and the protocol reading it there is a real
interval, and the page says "we have your answer" rather than "approved". A transport that
reported a decision it had not seen would be inventing the one thing this system may never
invent.

Three things the page does not do:

- **No price.** PromisePatch models no amount on an order, an order line, a recipe version or a
  recovery option. There is no price difference to state, so there is no field, and a test
  asserts the response carries none.
- **No safety claim.** §16.1 gives this product no allergen knowledge. The change is named and
  the page stops.
- **No arithmetic on the deadline.** `answerable` is the server's answer. The page holds no date
  comparison at all.

The choice is drawn in the `ask` channel, never in `brand`: the visual system keeps customer
consent and worker confirmation off one another's colour, and `brand` is what a worker presses.

## One thing was wrong on the worker's side

`PromiseState.DECLINED` and `PromiseState.EXPIRED` were unreachable. A decline and an expiry
each escalate the track **in the same transaction** that settles them, so `_promise_state`
matched `ESCALATED` first and a worker was told "needs you" — the same words as a promise that
was never asked about at all. The two states had phrases and next-actions written for them and
nothing could reach either.

`_escalated_state` now reads the track's own approval request and tells them apart: a decline is
"said no", an expiry is "no answer by the deadline", and everything else stays the plain
escalation. An escalation after an *approval* stays plain too — the approval is not why it
escalated, and "said yes" would describe the consent while hiding the outcome.

## The answer outlives the state it produced

The paragraph above closes one gap and leaves the other half of it open. `_escalated_state`
refuses to say "said yes" about a promise whose approved change then failed, and it is right to:
the outcome is the owner's and the phrase has to say so. But the worker picking that promise up
was then told nothing at all about the customer — the same "needs you" as a promise nobody was
ever asked about. The same is true in the happy direction: `RECOVERED` / "changed" is the truth
about the order and is silent about who permitted it, so the one promise on the case that needed
a human being's permission read exactly like the one covered by a standing preference.

`PromiseView.consent` is that missing half, and it is deliberately **not** derived from the
promise state beside it. `status_view._consent` reads the track's own approval record, so the
answer a person gave stays on the row after the promise has moved on — past `RECOVERED`, and past
an escalation that happened *after* the yes. A row now carries two independent readings: what
happened to the order, and what the customer said. Neither can hide the other.

It invents no word. A decision is stated with the two phrases `_PROMISE_PHRASE` already owns
("said yes", "said no"), borrowed rather than re-typed; every other posture is the sentence
`explanations.CLOSED_VOCABULARIES[FactId.APPROVAL_STATE]` already publishes for that request
state, which is what makes "asked", "the window closed with no answer" and "the request was
withdrawn because the order changed" arrive rather than being composed.

Two gates, each borrowed from a refusal this module already makes:

- **A recorded decision is read first**, for `_escalated_state`'s reason — a customer who
  answered answered, whatever a later timer wrote on the request afterwards.
- **An undelivered message says nothing.** Without `provider_ref` nobody has been asked, so the
  field is `None` rather than "the customer has been asked" — the same gate that stops the word
  "asked" being said about a message still in the outbox.

### What it deliberately is not

- **Not an authority.** It is a projection of a durable record. Nothing reads it to decide
  anything, and a screen showing it cannot cause a consent to exist.
- **Not the customer's words.** `ApprovalStatus` carries no reply text and no channel address by
  design, and this adds neither.
- **Not in the spoken status.** `render` is a measured surface with a word budget; the consent
  line is structured-view only and `speech` is byte-for-byte what it was.

## What is proved

| Property | Where |
|---|---|
| The token binds one request and one channel; every edit fails | [`test_customer_link.py`](../apps/backend/tests/test_customer_link.py) |
| The loop, against a real database, worker and HTTP hop | [`test_customer_approval_link.py`](../apps/backend/tests/test_customer_approval_link.py) |
| The page says only what the backend read | [`customerApproval.test.tsx`](../apps/frontend/tests/customerApproval.test.tsx) |
| The whole journey in a browser, against the real stack | [`customer-approval.spec.ts`](../apps/frontend/e2e/customer-approval.spec.ts) |
| A yes survives onto the worker's row past `RECOVERED` and past a later escalation | [`test_status_view.py`](../apps/backend/tests/test_status_view.py), [`test_customer_approval_link.py`](../apps/backend/tests/test_customer_approval_link.py) |
| Only the promise a customer was asked about claims an answer | [`test_case_workspace.py`](../apps/backend/tests/test_case_workspace.py) |
| The row renders the sentence unchanged, and none at all where there is none | [`propagation.test.tsx`](../apps/frontend/tests/propagation.test.tsx) |

The backend file covers approve, decline, replay, a decline that cannot be pressed into an
approval, a closed window, a superseded request, an approval that fails revalidation and changes
no order, a link minted for another channel, a worker holding the endpoint's address and every
credential except the signature, and the worker's screen afterwards for each ending.

## What is not built

- **No notification transport was built with this slice.** One exists now, for one channel:
  [`customer-message-transport.md`](customer-message-transport.md) added outbound Telegram
  delivery behind the existing provider boundary, and it changes who hands the link over and
  nothing about what happens next. It has never made a live Bot API call. Email and SMS remain
  unbuilt and unplanned.
- **No rate limit on the surface.** The token is an HMAC-SHA256 and is not guessable, and an
  oversized one is refused before it is decoded, but a valid token can be polled.
- **No option codes.** §13.6 also permits an exact option code; the parser still implements only
  `YES` and `NO`, and the page offers exactly those two.
