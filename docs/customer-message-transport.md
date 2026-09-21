# The customer message transport

The consent protocol has had a signed door since [`customer-approval-link.md`](customer-approval-link.md),
and no way to hand anybody the key. The message was composed, the link was minted, the row was
queued — and the only provider in the repository was a fake one that accepted the call and
forgot about it. This slice closes that gap for one channel.

**It is a transport and nothing else.** No check moved, no table changed, no migration ran, and
nothing new can authorise anything. What is different is that an approval request PromisePatch
decided to send can now arrive on a phone.

## What was added

| Piece | Where |
|---|---|
| The Bot API adapter | [`integrations/telegram.py`](../apps/backend/src/promisepatch/integrations/telegram.py) |
| Which channel this deployment has | `PP_CUSTOMER_CHANNEL_PROVIDER`, read in exactly one function |
| The credential | `PP_TELEGRAM_BOT_TOKEN`, required only when the provider is `telegram` |
| The ceiling on one call | `PP_TELEGRAM_TIMEOUT_SECONDS`, default 10s |
| The routing decision | [`worker.built`](../apps/backend/src/promisepatch/worker.py), beside the order-system route |
| The proof | [`test_telegram_channel.py`](../apps/backend/tests/test_telegram_channel.py) |

Nothing else changed. The domain is untouched, the engine is untouched, the API is untouched,
the frontend is untouched, and there is no new table, column or index.

## The path, end to end

```text
a plan needs a customer's permission
  -> approvals.request  writes approval_requests and enqueues one outbox row,
                        in one transaction, under a derived idempotency key
  -> the row carries    channel_kind, channel_address, the frozen §13.6 text,
                        the signed approval_url, and its two continuations
  -> outbox.claim       commits that an attempt is about to happen
  -> RoutedEffectAdapter picks the provider for MESSAGE_SEND
  -> TelegramAdapter    one sendMessage, no transaction held
  -> outbox.record      provider_ref = telegram:<chat>:<message_id>, DELIVERED
  -> the continuation   STEP_MARK_APPROVAL_SENT, which re-reads the row and only
                        then lets the track say it is waiting
  -> the customer       opens the signed link, on the surface that already existed
```

Every arrow but one already existed. The adapter is the one that did not.

## Telegram against the guarantees: the verdict

The Bot API was checked against each property the outbox already provides before any of it was
written. It preserves all of them except idempotency, which it cannot provide and which the
outbox never claimed.

| Situation | Telegram | Verdict |
|---|---|---|
| Duplicate dispatch under one key | No idempotency key exists. Two calls, two messages. | **At-least-once, duplicate real.** See below. |
| Timeout before Telegram acted | Indistinguishable from the next row. `RETRYABLE`. | Preserved |
| Timeout after Telegram may have acted | Indistinguishable from the row above. `RETRYABLE`. | Preserved, and the duplicate is possible here |
| Crash after acceptance, before the local commit | The claim committed first; the lease expires; the row is retried under the same key. | Preserved unchanged — the outbox already owns this |
| Retry under one durable effect identity | The key is the row's, never the adapter's. The composed call is byte-identical. | Preserved |
| Deterministic refusal | `400` / `401` / `403` / `404` with a description. | Terminal in one attempt |
| Throttling and server faults | `429` / `5xx`. | Retryable on the row's own ladder |

### The one thing it cannot do, stated plainly

**`sendMessage` has no idempotency key.** There is no header, no parameter and no
after-the-fact query that would let a second call be recognised as the first. A retry in the
uncertain window therefore puts a second copy of the message on the customer's phone, and
nothing on this side can prevent it.

This is not a weakened invariant. It is the case [`outbox.py`](../apps/backend/src/promisepatch/domain/outbox.py)
names in its own first paragraph — *"where a provider does not, the duplicate is real, and the
attempt count on the row says so"* — and `TelegramAdapter` is the first provider in this
repository that is actually that case. What bounds the damage is that the duplicate is a
duplicate **message**, never a duplicate **effect**:

- **one outbox row**, because the key is derived from persisted identity and is unique;
- **one approval request**, because `_insert_request` is `ON CONFLICT DO NOTHING` on a derived
  primary key;
- **one link**, because `customer_link.mint` is deterministic in the request and the channel —
  both copies open the same question, not two;
- **one answer**, because consent is spent once against a `plan_id` and a second `YES`
  authorises nothing a second time;
- **one order amendment**, because the message is not the amendment.

So a customer may read the same proposal twice. They cannot be asked twice, cannot answer
twice, and cannot have their order changed twice.
`test_two_attempts_under_one_key_send_one_proposal_twice` asserts the two outbound bodies are
identical, which is the whole of what makes the duplicate survivable.

## What the adapter refuses, and why each refusal is terminal

Every refusal below is deterministic, so retrying it would spend five attempts and ten minutes
of the approval window on an answer that cannot change. Each one is recorded as a terminal
failure, which runs the outbox row's `FAILED` continuation: the approval is abandoned, the
kitchen work is held, and the promise goes to its owner.

- **not a `MESSAGE_SEND` effect** — an adapter that guessed would report a success nobody
  performed;
- **not a `telegram` channel** — the stored channel kind decides, so a deployment that switched
  its transport on cannot send one customer's message to a chat id that is really somebody
  else's WhatsApp number;
- **not a numeric chat id** — ADR-0006 makes the numeric id the approval identity.
  `@username` is refused *although the Bot API would accept it*: a username is reassignable, so
  a message addressed to one can reach whoever holds the name today rather than the customer
  the request was created for;
- **no words to send**;
- **longer than 4096 characters** — refused rather than truncated, because the first thing lost
  off the end of an approval request is the instruction telling the customer how to answer it;
- **a `200` this build cannot read** — the round trip completed and the answer is not one we
  understand. Terminal rather than retryable, deliberately: the same call would produce the
  same unreadable answer, and the honest ending is an owner reading it rather than a ladder
  that might put a third copy of the message on a phone.

## What the message looks like on the wire

```text
POST https://api.telegram.org/bot<token>/sendMessage
{"chat_id": "...", "text": "<the frozen §13.6 wording>\n\n<the signed link>",
 "link_preview_options": {"is_disabled": true}}
```

Three properties, and all three are the message contract rather than formatting.

- **No `parse_mode`, ever.** §13.6's wording is frozen and a transport may not edit it. Sent as
  Markdown, an underscore in a recipe name would be swallowed and the customer would read
  different words than the ones the transaction composed.
- **The link travels beside the words**, on its own line, exactly as the payload carries it. A
  deployment that mints no link sends the words unchanged and loses nothing: the two literal
  answers remain the whole protocol.
- **Previews off**, so Telegram's own crawler does not fetch a possession link. The page it
  would reach is a read that decides nothing, but a possession link is for the person it was
  sent to.

## The credential

The Bot API takes its token in the request **path**, which makes secret hygiene structural
rather than a matter of care in one file: an HTTP client logs the path it called, so an adapter
that was scrupulous everywhere in its own code would still publish the token through
`httpx2`'s ordinary request line. Writing the first version of this adapter and its tests
demonstrated exactly that — the leak was found by
`test_the_bot_token_reaches_the_request_line_and_nothing_else` before the slice was finished.

Four things follow, and each has a test:

- `API_ORIGIN` is a **constant, not a setting**. Every other address in this application is
  configurable because pointing it elsewhere is a legitimate deployment choice; pointing a bot
  credential elsewhere is how a credential is stolen.
- The token is **never in the client's `base_url`**, so it cannot reach a client `repr`, and
  `TelegramAdapter.__repr__` names the channel and the timeout and nothing else.
- **Transport failures are recorded by exception type**, never by message. An httpx error's own
  text can carry the URL that failed, and that URL is the token — and `outcome.error` is
  written to `outbox_messages.last_error`, which every evidence surface can read.
- `_TokenRedaction` is installed on the `httpx2` and `httpcore` loggers while an adapter is
  open and removed when it closes. It **redacts rather than silences**, so the order system's
  request lines still reach an operator reading a failed amendment.

Nothing logs the message text or the approval link. A log line carrying the link would hand an
approval to whoever reads the logs, which is precisely the party the signature exists to
exclude.

## What is deliberately absent

- **No inbound path.** No webhook, no `secret_token` header check, no `update_id`
  deduplication, no `getUpdates`, no polling, no parser. A customer answers through the signed
  link on the surface that already existed, into the consent protocol that already existed.
  Adding a second door through which the word `YES` could arrive would be adding a second
  consent parser, and there is exactly one.
- ~~**No `pp channel check`.** ADR-0006's rehearsed setup step is still unwritten.~~
  **Written on 2026-09-21**, after this slice and separately from it. See
  [the operator preflight](#the-operator-preflight) below. It changed nothing here: no adapter,
  no setting, no check and no row moved. It is also what made the first live Bot API calls from
  this repository, on 2026-09-21 — two reads that sent nobody anything. See
  [what is proven live](#what-is-proven-live).
- **No second provider.** WhatsApp and SMS are out of scope and no groundwork for either was
  laid; the enum has two members because two is what exists.
- **No retry_after honoured.** Telegram's `429` carries advice on how long to wait. The row's
  own ladder decides when the next attempt happens, so the advice is recorded in the error
  rather than silently discarded.
- **No rate limiting of our own**, and no batching. One effect, one call.

## What is proven live

**On 2026-09-21 the credential and one private destination were checked against the real Bot
API**, from a developer machine, with the deployment's provider still `fake`:

```text
pp channel check                  -> getMe   : ok, the expected bot, is_bot verified
pp channel check --chat-id <id>   -> getChat : ok, that same numeric id, type private
```

Two reads, and that is the whole of it. Telegram answered `200` with `ok: true` to each; `getMe`
returned the bot username this deployment expects; `getChat` returned the same numeric id it was
asked for, typed `private`. One refusal was observed on the way, against an id that is nobody's
destination: `Bad Request: chat not found`. That is exactly what an operator sees before the
customer has pressed Start, and it is the first real Bot API error description this repository
has read rather than inferred from documentation.

The numeric chat id belongs to a person and is deliberately recorded nowhere — not here, not in
a test, not in a fixture. The token stays in gitignored `docker/env/api.env` and was never
printed by any of this.

**This is reachability, not delivery.** Nothing was sent.

## What is not proven

**No message has ever been sent from this repository**, and every test in this slice still runs
against a scripted transport. What that buys is real — the mapping from a provider's answers to
the outbox's three words, every refusal, the byte-identical retry, and the credential's reach
— and what it does not buy is the thing a G8 rehearsal is for:

- `sendMessage` has never been called live, and no message has reached a second device;
- no deployed process has ever had `PP_CUSTOMER_CHANNEL_PROVIDER=telegram`; the two reads above
  ran from a developer machine against a stack whose provider is `fake`, which is why the
  preflight prints the configured provider beside its answer;
- the deployed `PP_CUSTOMER_LINK_BASE_URL` has not been checked against what a phone can open,
  and a loopback address is not one;
- Telegram's real error descriptions are observed for `chat not found` and nothing else; every
  other refusal in the table above is still a documented shape;
- nothing proves a real chat id reaches the adapter. The preflight is *told* a destination by an
  operator; no approval request has ever carried one.

Until a deployed rehearsal does all of that, "PromisePatch can contact a customer" is a claim
about code that has spoken to Telegram exactly twice, read-only, and has still delivered nothing.

## The operator preflight

`pp channel check` answers, without sending anything, the two questions an operator otherwise
answers by putting a real approval message on a real phone and watching it arrive:

```text
pp channel check                    -> getMe    : is this credential a bot the API recognises
pp channel check --chat-id 1002     -> getChat  : may the bot speak to exactly that destination
```

The second is ADR-0006's rehearsed setup step — the customer presses Start once, because bots
cannot open a conversation — and until now nothing verified it. `chat not found` is what an
operator sees when they have not.

What it cannot do is the design, and each line of it is a test in
[`test_channel_check.py`](../apps/backend/tests/test_channel_check.py):

- **it cannot send** — there is no `sendMessage` in the command and no text to put in one, so
  the first message a customer receives is still one the transaction composed, not one an
  operator typed;
- **it cannot read a reply** — no `getUpdates`, no webhook, no parser, for the reason the
  adapter gives: a second door for the word `YES` would be a second consent parser;
- **it opens no database and needs no AWS credential** — it reads settings, makes at most two
  HTTPS calls and prints what it found;
- **it prints no secret** — not the token, and not the URL it called, because the Bot API takes
  its credential in the path and that URL *is* the token. It reuses the adapter's
  `_TokenRedaction` and its by-exception-type transport errors, so a provider that echoed the
  credential back would still not get it onto a terminal.

It is deliberately **not gated on `PP_CUSTOMER_CHANNEL_PROVIDER`**: a preflight is what an
operator runs *before* selecting Telegram, and one that demanded the deployment already be
switched on could only confirm a decision already made. For the same reason the report names
the configured provider beside the answer — a working credential is not a switched-on
transport, and a green check must never be read as "this deployment is contacting customers".

## Turning it on

Two variables on the **worker** — it is the only process that dispatches an effect — and a
recreate, because an env file edited under a running container changes nothing:

```text
PP_CUSTOMER_CHANNEL_PROVIDER=telegram
PP_TELEGRAM_BOT_TOKEN=<from BotFather>
```

The token belongs in `docker/env/api.env`, which is generated and gitignored, and nowhere else.
A worker selected for Telegram with no token **refuses to start**, naming the variable, before
it builds a database handle — because the alternative is worse than a crash: a deployment that
believed it was contacting customers while delivering to an in-memory provider, with approval
requests marked sent, tracks waiting, deadlines running, and nobody ever asked.

The customer must press Start on the bot once first. Bots cannot initiate conversations, which
ADR-0006 already records as a rehearsed setup step.

## Where each claim is proved

| Claim | Test |
|---|---|
| The frozen wording and the signed link reach the chat the request named | `test_a_message_and_its_link_reach_the_chat_the_request_named` |
| No markup mode may reinterpret the wording | `test_the_frozen_wording_is_sent_as_text_and_not_as_markup` |
| A deployment with no link sends the words unchanged | `test_a_deployment_that_mints_no_link_sends_the_words_unchanged` |
| Another channel's address is never sent to Telegram | `test_a_message_for_another_channel_is_never_sent_to_telegram` |
| An address that is not a chat id costs no call | `test_an_address_that_is_not_a_chat_id_is_refused_before_the_call` |
| A message too long is refused, not shortened | `test_a_message_too_long_for_telegram_is_refused_rather_than_shortened` |
| A deterministic refusal stops at one attempt | `test_a_deterministic_refusal_stops_at_one_attempt` |
| Throttling and server faults are retryable | `test_an_answer_that_may_change_is_retryable` |
| A timeout is uncertain rather than failed | `test_a_transport_failure_is_uncertain_rather_than_failed` |
| An unreadable acceptance escalates instead of looping | `test_an_acceptance_this_build_cannot_read_is_terminal` |
| Telegram makes no authoritative statement to verify later | `test_a_delivered_message_reports_no_authoritative_result` |
| Two attempts under one key send one proposal twice | `test_two_attempts_under_one_key_send_one_proposal_twice` |
| The retry after an uncertain answer is the identical call | `test_a_retry_after_an_uncertain_answer_repeats_the_identical_call` |
| The token reaches the request line and nothing else | `test_the_bot_token_reaches_the_request_line_and_nothing_else` |
| Redaction survives a provider echoing the token back | `test_a_provider_that_echoed_the_token_back_would_not_get_it_into_a_row` |
| Neither the words nor the link are logged | `test_neither_the_words_nor_the_link_are_logged` |
| The redaction is removed when the adapter closes | `test_the_redaction_is_installed_while_the_adapter_is_open_and_not_after` |
| An unconfigured deployment reaches nobody | `test_the_fake_channel_is_what_an_unconfigured_deployment_gets` |
| Telegram selected with no token refuses to start, first, naming the variable | `test_a_worker_selected_for_telegram_without_a_token_fails_before_anything_else` |
| A configured worker routes only the customer message | `test_a_configured_worker_routes_customer_messages_to_telegram_and_nothing_else` |

The crash-window behaviour is **not** re-proved here. It belongs to the outbox and is already
proved there, against the row rather than against a provider:
`test_a_death_after_the_provider_accepted_sends_the_same_key_again` in
[`test_workflow_outbox.py`](../apps/backend/tests/test_workflow_outbox.py).
