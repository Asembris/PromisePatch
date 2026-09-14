# Removing the runtime customer-intent classifier

Implements [ADR-0008](adr/0008-remove-runtime-customer-intent-classifier.md).
Supersedes nothing; edits no historical measurement.
Date: 2026-09-14

## What was actually there

The old audit finding was re-verified against the repository rather than assumed, and it was
still true. The classifier was reachable from production, on the one path where a person is
waiting:

```text
RECEIVE_CUSTOMER_REPLY                      approvals.execute
  sender, settled, deadline checked
  consent.read_literal(reply.text)
  → None ⇒ store the reply, enqueue INTERPRET_CUSTOMER_REPLY
worker._execute_one_step                    worker.py:143-146
  claim.kind == STEP_INTERPRET_CUSTOMER_REPLY
  → customer_intent.prepare(database, semantic, claim=claim)
      → provider.run(ClassifyReplyIntentRequest(...))     ← a Bedrock call
      → store the label on the claimed step row
INTERPRET_CUSTOMER_REPLY                    customer_intent.execute
  re-read under lock, re-check, send one confirmation prompt
```

- **Input**: the reply text and nothing else, plus the case id as metadata.
- **Output**: one of `APPARENT_APPROVE` / `APPARENT_DECLINE` / `UNCLEAR`, stored on
  `inbound_replies.apparent_intent` and in the confirmation audit row's `semantic` provenance.
- **Authoritative decisions depending on it**: none. Every label, a malformed answer and an
  unreachable provider reached the identical branch — `_request_confirmation` — and produced
  the identical message and the identical state.
- **Cost, latency and failure**: real, and all three. A synchronous provider call with a
  corrective retry sat between a customer's reply and the prompt telling them how to answer;
  `execute` could return `RETRYING` on `STATUS_UNAVAILABLE`, so a provider outage delayed a
  message whose content was never in doubt.

## What changed

The call is gone and the transaction that used to consume its answer is unchanged in every
respect that touches a person. `customer_intent` no longer imports `promisepatch.semantic` at
all; `prepare`, `_store`, `PreparedIntent`, `_label_of`, `_blocking_reason`,
`binding_fingerprint`, the `STALE` outcome and the unavailable-provider retry are deleted, and
the worker's step path makes one provider call rather than two.

Everything the consent protocol decides with is untouched: the literal parser runs first and
alone, the sender, deadline and plan binding are enforced before it, a non-literal reply is
stored verbatim and earns exactly one confirmation prompt, the request goes to
`CONFIRMATION_PENDING` with the track where it was, and the prompt's wording is the same frozen
sentence — now built, as ADR-0008 directs, from the request the reply is bound to.

Two ledger fields change meaning rather than shape. The confirmation audit row's `semantic`
provenance is now present and `null`, beside the `parser: null` that was always there, so a
later reader can tell "no model read this" from "this field was not written". And
`approval.semantic_interpretation_resolved` carries the outcome instead of a label.

## What was deliberately kept

- **The step kind `INTERPRET_CUSTOMER_REPLY`, the step-key prefix `interpret-reply:`, and the
  two `approval.semantic_interpretation_*` event types.** These are durable identities, on rows
  in every case ever run. Renaming them would orphan in-flight steps and rewrite history to
  describe today. Their docstrings now say what the work is and why the name is older than it.
- **The module name `promisepatch.domain.customer_intent`**, for the same reason: it is the
  module the ledger's vocabulary points at, and an import-linter contract names it.
- **`inbound_replies.apparent_intent`.** Retained, holding the labels taken while the classifier
  ran. Nothing writes it now, and rows created since carry `null`. `domain.analysis` and
  `domain.explanations` still read it, so a historical case still explains itself truthfully.
- **The whole `classify_reply_intent` job** — contract, prompt, schema, validators, scorers and
  the `ApparentIntent` vocabulary. ADR-0008 leaves the evaluation surface untouched: `evals`
  keeps the 56 gold cases, both splits, the challenger records and every measurement taken. The
  job is also what `pp semantic-smoke` asks, which is the diagnostic that proves a machine can
  reach a model without staging a demo to find out.

Bedrock usage elsewhere is unaffected. `interpret_utterance` (ADR-0007), `verbalise` and
`select_tool` are untouched, and the worker still carries one provider object for the one job on
its step path.

## How it is kept out

Three guards, at three different levels, none of which is a review:

1. **An import-linter contract** — `the customer reply path holds neither the parser nor a
   provider` — forbids `promisepatch.domain.customer_intent` from importing
   `promisepatch.domain.consent` *or* `promisepatch.semantic`.
2. **A source assertion** over the module's syntax tree, docstrings excluded, refusing
   `SemanticProvider`, `ClassifyReplyIntentRequest`, `ReplyIntentReading`, `ApparentIntent` and
   `promisepatch.semantic` alongside the decision names it already refused.
3. **A provider that raises** rather than a call count. Every scenario in `test_customer_intent`
   drives a worker whose provider treats a `CLASSIFY_REPLY_INTENT` question as a test failure,
   so a classifier put back on this path fails at the call site, naming the job.

`test_semantic_provider` adds the worker-level half: the two step kinds are claimed and
executed, and only the worker's own sentence is handed to the provider.

## What the tests say now

`test_consent_authority` is new and deliberately provider-agnostic: literal `YES` approves and
literal `NO` declines through `ParserKind.LITERAL`, punctuation and case normalise, an agreeable
sentence gains no authority and is kept word for word, a reply from another address on the same
transport is refused on identity, a `YES` after the window closed does not reopen it, a
redelivered reply decides once, a contradicting word after a decision changes nothing, and a
worker confirming a plan writes no customer decision at all. It passed unchanged before the
removal and after it, which is what makes it the guard rather than a description.

`test_customer_intent` keeps every scenario that still means something and loses the ones that
tested deleted behaviour: the label parametrisations, the refused-vocabulary and malformed-output
cases, the provider-outage case, and the `_blocking_reason` over-long-reply gate, whose subject
no longer exists — a reply of any length now reaches no model. Its two race tests are rewritten
against the window that remains, by claiming the confirmation step and holding it unexecuted
while a literal `YES` commits, which is a real interleaving rather than a hook inside a call
that is no longer made.

## What this does not close

The G7 obligation this discharges is the removal itself. The bounded withdrawal and the
finishing of the case workspace remain open, and `docs/p7.3-visual-acceptance.md` is left
unedited: it recorded truthfully, at the time, that this had not been done.
