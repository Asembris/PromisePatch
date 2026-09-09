# P5 — the product contract

**Locked before transport implementation, as G5 requires.** This page fixes what the
conversational surface is allowed to do, what the product is allowed to *say*, and what the
first case workspace must show. The MCP server, the voice path, the deployment and the frontend
expansion are not built here and are not described here as though they were.

Nothing on this page redesigns frozen architecture. Where it changes a decision, the decision
record is named.

## G5 item 1 — the superseding decision, in five parts

| part | where it is recorded |
|---|---|
| Remove the runtime apparent-intent classifier | [ADR-0008](adr/0008-remove-runtime-customer-intent-classifier.md) |
| Keep literal confirmation | [ADR-0008](adr/0008-remove-runtime-customer-intent-classifier.md), and the core invariant it restates |
| Keep deterministic explanations | §"Explanations", below — P4.8 stays closed |
| Distinguish planned from completed | §"The truthful state vocabulary", below |
| Define zero incident-caused operational effects | §"Zero incident-caused operational effects", below, and the [frozen manifest](effect-set-manifest.md) |

## The conversational authority contract

**The model understands; the deterministic protocol authorizes.** P4.9 established that nothing
a model says, fails to say, or fails to answer can reach a write, a consent decision or a
physical attestation. A conversational surface is exactly the thing that could undo that by
accident, so the boundary is stated as rules the transport must satisfy, not as intentions.

### What the server owns, and a tool argument can never carry

1. **Worker identity.** Established by the authenticated session, never read from a tool
   argument, never inferable from prose. A tool call that names an actor is naming a value the
   server ignores.
2. **The original turn text.** Stored first, verbatim, before any interpretation. The model may
   propose a reading of it; it may not replace, tidy or summarize the thing that was said.
3. **The physical attestation.** Only a permitted human's statement creates or corrects a
   physical fact. A model cannot synthesize one, and no plausible paraphrase becomes an
   attestation.
4. **Consent.** Only a literal normalized `YES` / `NO` from that order's own channel, inside the
   window, bound to that request and that plan. Customer prose is at most a non-authoritative
   apparent intent that can trigger one confirmation prompt — and after ADR-0008 no model reads
   it at all.
5. **Plan confirmation.** The worker confirms a *specific* case, plan and version under a
   command identity. A model cannot confirm a plan, cannot confirm on a worker's behalf, and
   cannot re-confirm one already confirmed.

### The tool surface

Finite and closed: **report, clarify, review-and-confirm, status, and a bounded withdrawal.**
No order, resource, recipe, reservation or consent CRUD tool is exposed — not disabled, not
present. An orchestrator may select an intent and propose a grounded interpretation; it has no
unconstrained editing surface to select from.

Tool availability by phase is defense in depth only. **Every domain check runs independently of
which tools were offered**, and rejects an invalid call whatever the model believed it was
allowed to do. A capability that is only prevented by not being advertised is not prevented.

### What the model may not do with words

- **Not paraphrase deterministic critical status into a guarantee.** Status, plan contents and
  recovery outcomes are rendered deterministically and delivered as rendered. A conversational
  layer may frame them; it may not restate them.
- **Not invent an entity, an authority, a version or a customer.** Recovery selects only
  pre-authored `RecipeVersion`s named by `SubstitutionPolicy`. Nothing at runtime creates,
  derives or synthesizes a version, and no tool argument can name one that does not exist.
- **Not answer for a system it did not reach.** A provider outage, a timeout or a malformed
  response is reported as an unavailable reading, never as a reading.

### The failure vocabulary

The semantic boundary's two-kind failure vocabulary from P4.9 holds across the new transport:
an input the vocabulary cannot carry is refused at the boundary rather than escaping as an
untyped exception past callers that catch only those two kinds. New transport inputs — tool
arguments, session identifiers, correlation identifiers, reconnect state — enter through that
same boundary and are bounded the same way.

## The truthful state vocabulary

The named risk is language outrunning reality: "approved", "sent", "recovered" said before they
are true. So the product's vocabulary is fixed here, each phrase bound to a durable source, and
**a phrase may not be spoken or displayed until its source exists.**

| product state | said to a human as | true only when |
|---|---|---|
| `UNTOUCHED` | "left alone" | the track is `UNAFFECTED`: unreachable from the exception, or its shortfall is covered |
| `PLANNED` | "planned — waiting for you" | analysis finished and the case is `PLANNED`. **Nothing has been done.** |
| `AUTHORIZED` | "your standing preference covers this" | the worker confirmed, and this track's classification was `AUTO_RECOVERABLE`. Permission to act; **not** an act |
| `REQUESTED` | "asked <customer>" | the outbound message was **acknowledged as delivered** by the provider. Not when it was queued, not when it was claimed |
| `CONSENTED` | "<customer> said yes" | a literal decision is recorded against that request, from that channel, inside the window |
| `DECLINED` | "<customer> said no" | as above, for a literal `NO` |
| `APPLYING` | "changing the order now" | the effect is durably queued under its idempotency key |
| `RECOVERED` | "changed" | the **external order system's own state** confirms it. An acknowledgement alone is not recovery |
| `ESCALATED` | "needs you" | the track is on the owner's desk, with an owner, a reason and a next action |
| `STALE` | "the plan no longer fits — re-planned" | revalidation refused and the track was re-planned against current truth |
| `EXPIRED` | "no answer by the deadline" | the request's timer fired with no decision |

### The four rules that vocabulary exists to enforce

1. **Planned is not completed.** An `AUTO_RECOVERABLE` classification is a permission to act
   later. Until the worker confirms and the effect is applied and observed, the honest sentence
   is "planned", and the count of recovered orders is zero.
2. **Asked means delivered.** "Asked Tomas" requires the provider to have acknowledged the
   message. A queued, claimed, retrying or terminally undeliverable message is not an ask, and a
   message whose window closed while queued is never delivered at all.
3. **Recovered means observed.** The external system is the record. Its echo completes the
   recovery; our acknowledgement does not. A pending delivery, a retry or an escalation may
   never be displayed as success.
4. **Worker confirmation is not customer consent.** They are different authorities, produced by
   different people, recorded separately, and never rendered in the same words. A worker
   confirming a bounded plan has authorized nothing on the consent-required track.

Long work gets honest progress, never premature success. Where the truthful answer is "still
waiting", that is the answer.

## Explanations

**User-facing explanations are rendered deterministically**, by
`promisepatch.domain.explanations.render` through `verbalisation.explain`, with
`PP_EXPLANATION_VERBALISATION` off by default. P5 wires that renderer to **real current case
state** and changes nothing about the selection.

P4.8 stays closed. The bounded Nova verbalisation path — prompt, schema, validators, `prepare`,
dataset, thresholds, judge and both DEVELOPMENT result files — remains preserved as
evaluated-but-not-selected capability. **The explanation holdout stays sealed permanently for
P4.8**, and the customer-intent semantic holdout stays sealed. Neither is opened by anything on
this page.

## Zero incident-caused operational effects

"Untouched" is a precise claim and is easy to overstate. An unaffected promise **does** receive
an `UNAFFECTED` case-track record; it is not true that no row anywhere mentions it, and the
product must not say so.

**The claim, exactly.** For an untouched order, this case produced no:

- recovery amendment to the external order,
- outbound customer message,
- reservation change,
- production-task hold,
- owner escalation.

**Attribution, exactly.** Counters are scoped to the case, and to effects attributed by case,
command and idempotency identity. The externally changed order in the demo has legitimate
history of its own; prior and independent external edits belong to the customer who made them
and are never incident-caused, whether they happened before or after the exception. Analysis
rows, case-track rows and audit rows record that a promise was *considered* — that is evidence
of selectivity, and it is never counted as an effect.

The published figure is **0/U**, where U is that scenario's predeclared case-baseline untouched
count — not the number of test scenarios. Every scenario in the [frozen
manifest](effect-set-manifest.md) declares its own U, and rule R5 there is this section in
machine-checkable form.

## The first case workspace — minimal information hierarchy

Locked now, before transport, because the evidence a worker needs decides what the tools must
return. One workspace, four bands in this order, plus one drawer. Not four screens.

| band | answers | contents |
|---|---|---|
| 1. What happened | "what did we learn?" | The physical fact in the worker's own words, who attested it, when, and its scope. An unresolved ambiguity appears here as a question, not as a result. |
| 2. What you must do now | "what is mine?" | Exactly one next action, with its owner. Where nothing is required of this worker, that is stated rather than left blank. |
| 3. What changes, under whose authority | "who decided?" | Threatened promises grouped by authority — covered by a standing preference / needs the customer / needs the owner — each with its customer, its deadline and the one-line reason it is in that group. |
| 4. What was left alone | "what did this not touch?" | The untouched promises, counted, with the reason each is untouched. Visible but quiet. |
| 5. Evidence drawer (collapsed) | "how do I know?" | Case and step identifiers, rule ids, reason details, snapshot fingerprints, the ten revalidation checks with the values they compared, parser enums, sender chain, provider references, audit rows. |

### Rules the workspace must satisfy

- **Real state only.** Every value is read from the durable case. No outcome, count or sentence
  is hardcoded in the frontend, including the closing summary.
- **Reload and reconnect preserve the case.** A refreshed browser, a dropped connection and a
  restarted worker all land on the same case in the same state. Work outlives a process, and the
  screen must not suggest otherwise.
- **Status is legible without color.** Every state carries text as well as color, and every
  blocked promise names an owner, a reason and a next action.
- **Engineering vocabulary lives in the drawer.** Sequence numbers, enum names and hashes are
  evidence, not the primary reading. Bands 1–4 are sentences a baker would say.
- **The untouched band is not decoration.** It carries the product's central claim and is
  present even when it is long.

## Explicitly not decided here

MCP transport and SDK pinning, the independent-client replay, voice, the deployed loop, the
withdrawal tool's exact bounds and the frontend build are **implementation**, and are governed by
G5 items 3–9 and G6. They are not described on this page as delivered, and nothing here should be
read as evidence that they exist.
