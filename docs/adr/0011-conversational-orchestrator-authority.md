# ADR-0011 — What a model may decide in a conversation, and what it may not

Status: accepted
Date: 2026-09-10
Phase: 5

Records the decisions P5.3 had to make to put a model in the conversational loop over the
four-tool surface [ADR-0009](0009-mcp-transport-spine.md) and
[ADR-0010](0010-plan-bound-worker-confirmation.md) built. It reopens neither. The rules it has
to satisfy are in the [P5 product contract](../p5-product-contract.md), whose conversational
authority section says what the server owns and what a tool argument may never carry.

The core rule is unchanged and is the whole point of the shape below: **the model understands;
the deterministic protocol authorizes.**

## Decision

**1. The model's only output is a verb. It supplies no arguments, ever.**

One bounded semantic job, `select_tool`, whose result type — `ToolSelection` — has exactly two
fields: a member of a closed `ConversationTool` enum, and an optional sentence of glue. There
is no `case_id` on it, no `plan_id`, no `text`, no `answer`, no worker and no customer.

This is deliberately structural rather than validated. A field the model can fill in with an
identifier is a field somebody will eventually be tempted to trust after "the schema checks
it", and the check that would have to catch a fabricated plan identity is a check against a
value the server also holds — at which point the field was never needed. So there is no field,
a fabricated identity is refused by `extra="forbid"`, and every argument that reaches a tool is
one of exactly two things: the worker's own turn forwarded byte for byte, or an opaque
identifier a trusted tool returned.

**2. Tool availability is computed from the durable case, and is defence in depth only.**

A phase is derived from a `status` reading the server rendered — never from what the model
said, never from what the loop hoped — and each phase offers a fixed set of verbs. `CONFIRM` is
offered only by a case that is `PLANNED` *and* handed over a plan identity; `CLARIFY` only by a
case with an open question; `REPORT` only when no case is open; every phase offers `STATUS`.

The offer is checked twice — once by the semantic boundary against the request, once by the
policy before a call is built — and neither is the real control. The domain checks every one of
these again and refuses a call the case cannot accept whatever this table believed. What the
table buys is that a model is never *offered* something the case cannot do, which is the
difference between a refusal a worker hears and a refusal they never had to.

**3. A plan is confirmed by the worker, in the worker's own words, or not at all.**

`CONFIRM` requires three independent things: the phase permits it, the conversation holds a
plan identity it read from `status`, and the worker's turn opens with one of a closed set of
affirmations and contains none of the words that qualify one. A model selecting `CONFIRM` on
"that plan looks right to me" reaches no tool.

This is stricter than the domain, which treats the call itself as the yes — correct there,
because the caller was a client a person was driving. A conversational layer is the one caller
that can be *agreeable*, so the extra lock is on the one door that opens onto somebody's order.

It is **not** the customer consent parser and shares nothing with it. Worker plan confirmation
and customer consent are different authorities, produced by different people, recorded
separately; `promisepatch.orchestrator` cannot import `promisepatch.domain.consent` and does
not resemble it.

**4. Everything a worker is told is rendered deterministically. Model language is glue.**

The reply is the tool's own `speech`, written by `promisepatch.domain.status_view` on the far
side of two hops and delivered unchanged. The model's optional preface stands in front of it
and never in place of it, is capped at 25 words, may contain no digit, and may contain none of
a closed list of words that report an outcome — `changed`, `sent`, `asked`, `confirmed`,
`done`, `sorted`, `recovered` and the rest.

A preface that fails is not trimmed. It fails the whole answer, because a repaired sentence is
one nobody wrote and the caller already holds a rendering it can use instead. And glue is
delivered **only when the turn did what was chosen**: a blocked or refused turn drops it,
since a sentence written to introduce an action is not necessarily safe introducing that action
not happening.

The gate is a floor and is described as one. It compares words against a list and understands
nothing; a model determined to imply completion without any of those words can. What it
establishes is that the sentence a worker acts on never comes from the glue at all.

**5. Two tool calls per turn, of which at most one may affect state.**

A hard count. The second call is always `status`, so a turn can end on the truth rather than on
what the first call hoped, and it is what refreshes the phase for the next turn. Nothing is
ever retried: a refusal is an answer, and the loop says the deterministic sentence for its code
and gives the worker their turn back.

The one corrective retry in the system stays where it already was — inside the semantic
gateway, spent on a schema, bounded at one. There is no retry loop anywhere in the
orchestrator, which is what stops a conversational layer from quietly becoming an agent looking
for a way around a rule.

**6. The orchestrator is a client, structurally.**

It cannot import the domain, the database, the API package, the engine, SQLAlchemy, an AWS SDK
or the MCP server's own internals; an import-linter contract enforces it. Everything it can
cause is something an unrelated MCP client could already cause with a bearer token. That is the
whole authority argument for putting a model in the loop: the boundary a model now sits behind
is one that was already load-bearing before it arrived.

## Consequences

- **A turn can fail closed and cost the worker a turn.** Glue that claims an outcome fails the
  whole answer, so a model that phrases badly twice loses that turn's action and the worker
  repeats themselves. Accepted: the alternative is a repaired sentence or a partial answer, and
  both are worse in the direction that matters.
- **One case per conversation.** The phase table offers `REPORT` only from `NO_CASE`, so a
  worker reporting a second exception starts a second conversation. Correct for this slice and
  a thing to revisit when the case workspace can hold more than one.
- **The affirmation list is a list.** A worker who says yes in a way nobody wrote down is asked
  again. It fails towards asking, which costs a turn, rather than towards confirming, which
  costs an order.
- **A refusal code travels in prose.** The SDK reports a tool failure as text, so the frozen
  code is searched for in it rather than parsed from a field. An unrecognised refusal is read as
  unavailability, never as the nearest familiar code.
- **Staleness and "not planned" remain one code to the conversation**, as ADR-0010 §5 decided.
  The loop's sentence for it says the case moved on and re-reads it, which is the remedy for
  both.

## Revisit if

- A phase needs to offer a verb conditionally on something other than the case's own rendering.
  That would be the first argument the model could influence, and it belongs in an amended ADR
  rather than in a policy table.
- The glue gate starts refusing sentences a person would call harmless often enough to be
  noticed. The fix is a narrower list, not a cleverer reader.
- The withdrawal tool arrives. It is an effecting verb and needs its own phase rule and its own
  gate; nothing here anticipates one, and `ConversationTool` has no member for it.
