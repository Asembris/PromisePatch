# ADR-0021 — A customer answers on the web, and their address stays in the database

Status: accepted
Date: 2026-09-22
Phase: 5

Two things a customer's message did that it should not have. It told them to reply on a channel
that cannot hear, and it put their Telegram chat id on three surfaces that can be read by people
the message was never for. Both were measured on the deployed system before they were changed,
and both are closed here.

Neither changes what authorises anything. The literal parser is untouched, the signed link is
untouched, the ten revalidation checks are untouched, and
[ADR-0018](0018-a-plan-confirmation-spends-a-human-approval.md)'s separation of worker approval
from customer consent is untouched. What moves is one sentence and one set of render boundaries.

## The question this decides

§13.6 fixes the customer-facing reply instruction as a literal:

> **must** contain the literal reply instruction "Reply YES to approve this change or NO to
> decline it. If you decline, the bakery will follow up."

That sentence presupposes an inbound channel. §16's contract says so outright — *"the approval
**must** enter PromisePatch through the provider's inbound webhook"* — and this build
deliberately has none. The question is whether a frozen literal that names a door the product
does not have stays frozen.

## The evidence, which is a measurement and not an argument

On 2026-09-22 a real approval message was delivered to a real phone, and the person holding it
typed a literal `YES` into the bot's own chat, because the message told them to.

| what was checked | value |
|---|---|
| `inbound_replies` created by that `YES` | **0** |
| `approval_decisions` created by it | **0** |
| request state after it | still `SENT` |
| `getUpdates` calls in the deployment's whole history | **0** |

[`deployed-customer-channel.md`](../deployed-customer-channel.md) section 10.7 records it. The
instruction did not merely describe a path that was unlikely to work; it described one that does
not exist, and a real person followed it into nothing. The same document's section 11 records
what *did* work: the signed possession link in the same message, opened on the phone, one
`APPROVE` press, one `approval_decisions` row through the `LITERAL` parser.

## Decision

### 1. The instruction names the link, because the link is the only door

`CONSENT_INSTRUCTION` becomes:

> Open the secure link below to approve or decline this change. If you decline, the bakery will
> follow up.

The second clause is §13.6's own, reproduced exactly. Only the first moves.
`CONFIRMATION_INSTRUCTION` moves with it and points *backwards* — *"use the secure link in our
earlier message"* — because the confirmation prompt's effect payload carries no `approval_url`
and a prompt saying "below" would name a line the transport was given nothing to write.

**This is not a new consent path.** The link already existed, already carried the answer that
already worked, and already fed the one literal parser. What changes is that the words now point
at it. A message that named two words readable from nowhere was not a stricter protocol than one
that names the link; it was the same protocol described wrongly.

### 2. Telegram inbound stays unbuilt, and this decision does not weaken that

A second route for the word `YES` would be a second consent parser, and there is exactly one.
Nothing here adds a webhook, a `getUpdates` call, an update handler or a second parser. The
correct response to "the customer replied on Telegram and nothing happened" is to stop telling
them to, which is what this does — not to start listening.

### 3. A deployment that mints no link asks for nothing at all

Where `PP_CUSTOMER_LINK_SECRET` is unset there is no surface on which the customer can answer, so
the message stops being a question:

> This message cannot take your answer, so nothing about your order changes because of it. The
> bakery will follow up.

Both claims hold by construction. No consent means no amendment; an unanswered request reaches
its deadline and escalates the promise to its owner. The alternative considered was refusing to
send a request at all in that configuration — which §13.6's own principle would support, since
*"a request is never sent into a window in which no valid answer could arrive"*. It is **not**
taken here: it is a behaviour change to the state machine, not a wording change, and it belongs
to whoever decides that deployments without links should not ask. Recorded rather than done.

The wording and the link are chosen from **one** reading of one setting, and the pre-send guard
is told which sentence was owed. A message promising a link nobody attached fails the guard.

### 4. A customer's channel address stops at the database

The address is load-bearing inside the system and disclosing outside it. It stays in the outbox
row, the approval request, the decision row and the audit ledger — where addressing a message,
comparing a reply's sender to the channel a request was sent to (§14.3 check 8) and saying
afterwards what those two values were all need it. It is masked to its channel kind at every
boundary where it is read out:

| boundary | carried it as | now |
|---|---|---|
| `worker.telegram.sent` → CloudWatch | `chat_id` field **and** inside `provider_ref` | channel kind and idempotency key only |
| `pp case-status` | `approval.provider_ref`, `effect.provider_ref` | `telegram:***` |
| `pp case-status` | revalidation check 8's `expected` / `actual` | `tg:***`, and whether they matched |
| `GET /api/cases/{id}` | the same three fields, over the public internet | the same masking |
| the deployed SPA's evidence drawer | rendered `provider_ref` verbatim | the same masking |
| `pp channel check` | echoed the chat id back | the chat *type* only |

The last three were not previously recorded anywhere. Sections 10.8 and 11.7 of
[`deployed-customer-channel.md`](../deployed-customer-channel.md) named the log line and
`pp case-status`; the public API and the deployed SPA render the same projection and were
disclosing the same identifier to anyone holding a case id.

**Masking, not hashing.** A Telegram chat id is about ten decimal digits, so the space is roughly
ten billion and a truncated digest of one is a digest a commodity GPU walks through in seconds.
Publishing `sha256(chat_id)` would publish the chat id to anybody who cared while looking
careful. A keyed digest was rejected for a different reason: a key reaching every rendering
boundary is a second secret to hold, rotate and leak, bought for an operator convenience that the
idempotency key already provides.

**One place, not six.** The reduction is applied in `promisepatch.domain.analysis`, which is the
single projection the CLI, the HTTP response and the SPA are all built from, plus the one log
call in the adapter. A rule applied at each of six render sites is a rule that is eventually
applied at five.

## Consequences

- §13.6's literal is amended. The pre-send guard still exists and still refuses a message missing
  its instruction — it is now told which instruction was owed, so it cannot pass a message
  composed for the other configuration.
- `carries_required_literals` and `carries_confirmation_literals` take `link_available` with no
  default. A default would decide silently on behalf of a caller that forgot to, which is the
  mistake a pre-send check exists to catch.
- An operator reading a case can no longer tell *which* chat was reached. That is the point. The
  audit ledger and the rows answer it for a reader entitled to ask.
- A failing check 8 reports that the addresses differed rather than printing two identical masks,
  so an `UNAUTHORIZED` refusal stays readable without being disclosing.
- The Telegram message id is lost at the boundary along with the address, because an address may
  itself contain a separator and a rule that kept the final segment would leak the tail of a long
  one. It identifies nothing actionable without access to the chat, which is what this prevents.
- **Nothing about idempotency, retry or consent changes.** The outbox key is unmoved, the link is
  unmoved, the parser is unmoved, and `sendMessage` still has no idempotency key.

## What this does not do

- It does not build Telegram inbound, and ADR-0006's channel decision is unchanged.
- It does not refuse to send a request where no link exists. See decision 3.
- It does not edit any frozen or historical evidence. Sections 3 and 6 through 11 of
  [`deployed-customer-channel.md`](../deployed-customer-channel.md) stand as written, and the
  later truth is recorded beside them.
- It does not change what a durable row stores, and it rewrites no stored row. A case recorded
  before this decision keeps the address it recorded; only the reading of it is reduced.
- It does not touch `SUR-1`, its harness, its manifest or any published run.

## Revisit if

- An inbound transport is ever built. It would need its own decision, because it is a second door
  to the one parser, and this ADR is the record of why there is currently one.
- A deployment needs an operator to correlate two cases by customer at a render boundary. The
  answer then is a keyed fingerprint with a named key owner, not the address and not a bare hash.
- §13.6 is ever unfrozen wholesale, in which case this amendment folds into that.
