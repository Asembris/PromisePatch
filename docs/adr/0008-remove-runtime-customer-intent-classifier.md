# ADR-0008 — Remove the runtime customer-intent classifier

Status: accepted, and **implemented on 2026-09-14** — supersedes the RETAIN decision in
[`customer-intent-architecture-closeout.md`](../customer-intent-architecture-closeout.md)
Date: 2026-09-09
Phase: 5
Implementation: [`customer-intent-classifier-removal.md`](../customer-intent-classifier-removal.md)

## Decision

**The synchronous apparent-intent classification of a customer's reply leaves the production
consent path.** The `INTERPRET_CUSTOMER_REPLY` step and its `classify_reply_intent` provider
call are removed from the runtime; the confirmation prompt a non-literal reply earns is
produced deterministically, from the request the reply is bound to.

Everything the consent protocol actually decides with is unchanged:

| | before | after |
|---|---|---|
| What can approve | literal normalized `YES` / `NO` only | unchanged |
| Sender, deadline and plan binding | enforced before any reading | unchanged |
| A non-literal reply | stored verbatim, decides nothing, earns one confirmation prompt | unchanged |
| Request state after a non-literal reply | `CONFIRMATION_PENDING`, track where it was | unchanged |
| The prompt's wording | frozen literal instruction | unchanged |
| Who produces that prompt | a Bedrock call, then the deterministic protocol | the deterministic protocol |
| Worker semantics (`interpret_utterance`) | Bedrock, per ADR-0007 | **unchanged; not in scope** |

The evaluation surface is untouched. `evals` keeps the 56 customer-intent cases, both splits,
the prompt, the schema, the scorers, the challenger records and every measurement already taken.
The customer-intent semantic **holdout remains sealed** and is not opened by this decision.

## Context

The retained decision said so itself, in its own words: the classifier is kept "because the
frozen product contract locks the non-authoritative apparent intent into the consent protocol
and into mandatory Proof E, not because the measurements justified the call on product value."

That is a contract argument, and P5 is the phase that supersedes that contract. What is left
once it is withdrawn is the module's own documented property:

> The label changes what the ledger records. It changes nothing about what happens.

`APPARENT_APPROVE`, `APPARENT_DECLINE`, `UNCLEAR`, malformed JSON and an unreachable provider
all produce the identical message and the identical state. There is no branch for the label to
influence. The measured quality was 24/30 with terse-assent recall 2/5 and indirect-refusal 3/4
below their thresholds, and three challenger configurations cleared no materiality floor — but
the quality number was never the reason to keep or drop it, because no value of it changes a
customer outcome.

What the call does change is the shape of the consent path. It is a synchronous provider call,
with a corrective retry, sitting between a customer's reply and the prompt that tells them how
to answer — on the one path where a person is waiting, and the one path where a provider outage
would delay a message whose content was never in doubt.

## Alternatives rejected

- **Keep it as it is.** Its only remaining justification was a contract this phase replaces. A
  synchronous model call on the consent path whose every outcome is identical is latency,
  a failure mode and an ongoing cost with no user-visible return.
- **Keep it, moved off the critical path as advisory telemetry.** This preserves the ledger
  detail and removes the latency, and it was the closest call here. Rejected for P5 because it
  keeps a paid provider dependency, a step kind, a prompt, a schema and a failure surface alive
  to enrich an audit row nobody has asked to read — and because it invites exactly the claim
  this decision refuses to let the submission make. It remains the cheapest way back if a later
  phase finds a real consumer for the label.
- **Replace the provider for this job.** No measured challenger cleared the frozen materiality
  floor. Replacing a component whose output changes nothing would be spending on a decision
  that does not exist.
- **Let a model produce or influence the decision.** Never on the table. The literal parser is
  the only thing that can approve, and that is a core invariant, not a configuration.

## Consequences

- One provider dependency, one step kind, one prompt and one schema leave the production consent
  path. A Bedrock outage can no longer delay the confirmation prompt.
- The audit ledger stops recording an apparent-intent label for replies. What it records instead
  is what it always decided on: the verbatim reply, the binding, and the refusal to treat it as
  an answer.
- **A claim that must not be made anywhere.** The submission may not say, or imply, that the
  model recognized "Strawberries work" as agreement. It did not, in production, before or after
  this decision — and after it, no model reads the reply at all. What the product demonstrates
  there is that an agreeable sentence is not authorization. Scenario S09 of the frozen
  effect-set manifest encodes precisely that, and its declared outcome is independent of any
  apparent-intent reading.
- Historical evidence stays exactly where it is, unedited. The measurements were taken, the
  closeout reasoning was sound at the time, and the fact that a component was evaluated and then
  not selected is a result worth keeping — the same shape as the P4.8 explanation decision.
- The removal itself is an implementation slice, not this document. If it is not completed
  before the roadmap's September 18 P5 cutoff, it is carried as a named MUST item under G7 and
  never silently dropped.

## Implementation note (2026-09-14)

Added after the fact, and changing no reasoning above. The removal landed as described, with one
deliberate difference from the wording of the Decision, recorded here rather than quietly.

*The `classify_reply_intent` provider call is gone from the runtime, entirely.* No production
path reaches it, and an import-linter contract forbids `promisepatch.domain.customer_intent`
from importing `promisepatch.semantic` at all.

*The step kind `INTERPRET_CUSTOMER_REPLY` is retained, carrying only deterministic work.* The
Decision says the step is removed; it is not, and this is why. The kind is a durable identity —
it is on step rows, on audit rows and in the ledger of every case ever run — so renaming it
would orphan any step in flight and would rewrite history to describe today. The second
transaction it names is also worth keeping on its own merits: it re-reads the request under the
system's lock order, which is where a literal `YES` racing the prompt wins absolutely. What it
no longer does is ask anybody anything. The same applies to the step-key prefix
`interpret-reply:` and to the two `approval.semantic_interpretation_*` event types.

Also retained, for the reasons this ADR already gives: the whole `classify_reply_intent` job
(contract, prompt, schema, validators, scorers, the `ApparentIntent` vocabulary) because the
evaluation surface is untouched, and `inbound_replies.apparent_intent`, which holds the labels
taken while the classifier ran and is now written by nothing.

Full record: [`customer-intent-classifier-removal.md`](../customer-intent-classifier-removal.md).

## Revisit trigger

A consumer that would actually change a customer outcome from an apparent-intent label — not an
audit field, not a dashboard. Short of that: amend this ADR before putting a model back on the
consent path.
