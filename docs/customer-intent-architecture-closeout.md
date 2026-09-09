# Customer-intent architecture closeout

> **SUPERSEDED on 2026-09-09 by [ADR-0008](adr/0008-remove-runtime-customer-intent-classifier.md).**
> The RETAIN decision below no longer describes the intended production path: P5 withdraws the
> frozen contract that was this page's stated reason for keeping the classifier, and the runtime
> apparent-intent call leaves the consent path. **Nothing on this page has been edited or
> rescored.** Every measurement, challenger result and argument is preserved exactly as it was
> recorded, including the reasoning that was correct at the time, because a component that was
> evaluated and then not selected is a result worth keeping.

> **Zero model calls.** Nova: 0. GPT-4o-mini: 0. Nemotron: 0. Haiku: 0. Ollama: 0. Holdout: 0.
> Spend: $0. Every number on this page is read from persisted run artifacts and from the code
> in this commit. **Production routing is unchanged by this page.**

Three targeted challengers were measured against the customer-intent job and none of them
repaired the failure cluster that motivated challenging. That result raised a fair architectural
question, and this page is where it is asked and answered:

> Does `classify_reply_intent` provide enough decision-relevant product value to justify a
> runtime model call, or should nonliteral customer replies deterministically enter the
> literal-confirmation protocol instead?

**Answer: the classifier stays in the synchronous customer path, because the frozen product
contract locks it there — not because the measured evidence argues for it.** Those are different
reasons and the distinction is the whole of this page.

---

## What the classifier contributes to behaviour: nothing

`promisepatch.domain.customer_intent` fetches one label and then ignores it. Traced through
`execute` and `_request_confirmation`, every consequence is reached identically for all three
labels, for a rejected reading, and for a provider that could not be reached at all.

| Consequence | `APPARENT_APPROVE` | `APPARENT_DECLINE` | `UNCLEAR` | materially different? |
|---|---|---|---|---|
| Workflow state | request → `CONFIRMATION_PENDING`, track `WAITING_FOR_CUSTOMER`, case `WAITING` | identical | identical | **no** |
| Allowed transition | the same single `SENT` → `CONFIRMATION_PENDING` update | identical | identical | **no** |
| Confirmation wording | `build_confirmation_prompt(customer_name, order_reference, option_code)` | identical | identical | **no** — the builder is never given the label |
| Recipient | `binding.customer_channel` | identical | identical | **no** |
| Timeout / deadline | untouched; `now > binding.deadline` is re-checked under lock either way | identical | identical | **no** |
| Revalidation | check 9 of §14.3 rejects any non-literal reading regardless of label | identical | identical | **no** |
| Customer authority | none created; `ApparentIntent` is not `ApprovalDecisionKind` | identical | identical | **no** |
| Recovery option selection | untouched | identical | identical | **no** |
| External mutation | none | identical | identical | **no** |
| Audit semantics | `SYSTEM` actor, `authority="NONE"`, `parser: null` | identical | identical | **no** |
| Message count | exactly one prompt, keyed `pp:confirm:{request}:{reply}` | identical | identical | **no** |
| Escalation | a second non-literal reply escalates on **request state**, not on any label | identical | identical | **no** |
| User-visible behaviour | one prompt asking for `YES` or `NO` | identical | identical | **no** |

Everywhere the label does reach is evidence: the `inbound_replies.apparent_intent` column, the
audit `after` block, the audit provenance `semantic` block, the
`APPROVAL_INTERPRETATION_RESOLVED` event payload, the step result, and the two structured log
lines. There is no branch on it anywhere in the runtime.

`test_every_apparent_intent_asks_and_decides_nothing` asserts this across all three labels;
`test_the_prompt_does_not_repeat_what_the_model_thought` asserts the label never reaches the
customer. The §9 redundancy finding from the P4.3 audit therefore still holds, unchanged.

## What it contributes to authority: nothing, structurally

Removing the classifier could not create an `ApprovalDecision` that cannot happen today, admit a
reply from the wrong sender, bypass request/decision binding or one-consumption semantics, weaken
any of the ten §14.3 checks, mutate an order earlier, authorize a recovery option, or weaken
fail-closed behaviour. Every one of those is enforced by the deterministic protocol before or
after the classifier, and the classifier module holds no database write, imports no
`ApprovalDecision`, and cannot name a decision value.

The corollary matters for honesty: **the classifier is not a safety control, so it cannot be
defended as one.** A prompt-injected reply that talks a model all the way to `APPARENT_APPROVE`
buys exactly one confirmation prompt, which is what an unreadable reply buys anyway.

## Measured quality evidence

On the frozen targeted set of twelve development cases, `promisepatch-semantic-gold` v1.0.0,
byte-identical prompt and tool-schema hashes across all three runs:

| configuration | valid readings | correct | repairs vs Nova | repair rate | approve-side repairs | controls preserved | materiality |
|---|---|---|---|---|---|---|---|
| Nova (source run) | 12/12 | 6/12 | — | — | — | — | — |
| GPT-4o-mini-2024-07-18 | 12/12 | 8/12 | 2/6 | 0.333 | 0/3 | 6/6 | **FAIL** (floor 0.50) |
| NVIDIA Nemotron 3 Super | 12/12 | 6/12 | 0/6 | 0.000 | 0/3 | 6/6 | **FAIL** (floor 0.50) |
| Claude Haiku 4.5 | 0 | — | — | — | — | — | no quality conclusion — AWS Marketplace billing |

The canonical utterance `"Strawberries work"` reads `UNCLEAR` under all three measured
configurations, against a gold label of `APPARENT_APPROVE`. The injection-shaped case
`customer.unclear.injection.003` reads `APPARENT_APPROVE` under all three, against a gold label
of `UNCLEAR`.

These are readings of one closed-label job on twelve cases. They are not a ranking of the models
and nothing here concludes that the job is unsolvable — only that no measured configuration
repaired the cluster it was brought in to repair.

Details, selection algorithm and per-case tables:
[`semantic-benchmark.md`](semantic-benchmark.md),
[`semantic-benchmark-scorer-audit.md`](semantic-benchmark-scorer-audit.md),
[`customer-intent-challenger-stage-a.md`](customer-intent-challenger-stage-a.md),
[`nemotron-challenger-stage-a.md`](nemotron-challenger-stage-a.md).

## What the call costs

A synchronous provider call on the customer path adds latency, a provider dependency and its
failure modes, a retry ladder, and quota and telemetry surface. Observed latencies from the three
separate runs — `p50 ≈ 587 / 1134 / 1317 ms` and `p95 ≈ 1114 / 5773 / 5611 ms` for Nova,
GPT-4o-mini and Nemotron respectively — were produced by different executions under different
conditions and are not a controlled comparison; they are recorded as orders of magnitude only.

The cost is real and it is paid for evidence rather than for behaviour. The mitigations already
in the code are what keep it bounded: the reply step refuses to create the work at all for an
unauthorised sender, a closed window, a settled request, a duplicate delivery or a literal `YES`,
so none of those costs a call; the call is made between transactions holding no lock and no
connection; and a provider outage falls back to `UNCLEAR`, which sends the same message.

## The three candidates

**A — RETAIN.** Nonliteral reply → `classify_reply_intent` → deterministic confirmation.
**Verdict: selected, by frozen contract.**

**B — DEMOTE** (out of the synchronous path, label kept as offline telemetry).
**Verdict: rejected — violates the frozen contract.**

**C — REMOVE from the customer runtime** (nonliteral reply → confirmation, full stop).
**Verdict: rejected — violates the frozen contract.**

On the engineering merits alone, B and C are attractive: they delete a runtime provider
dependency that changes no authoritative behaviour, and they remove one model failure surface
from the consent path. That is not the deciding question, because the classifier is not an
unlocked implementation detail.

`PROMISEPATCH_PRODUCT_SPEC.md` §28 Explicit Locks fixes it in two separate rows:

- **Human approval** — "free text yields a non-authoritative apparent intent and at most one
  confirmation prompt".
- **Trust model** — locks the §15 table, whose customer-consent row assigns the model exactly one
  job: "Reads non-literal text into a *non-authoritative* apparent intent that can trigger one
  confirmation prompt; can never produce a decision."

§28 further locks **Proof obligations — §22 A–H, all mandatory**. Proof E's observable evidence is
"free-text reply produces a non-authoritative apparent intent and **no write**", with all three
steps visible in the ledger; and §28's **Demo scenario** row locks the §21 storyboard verbatim,
whose split-screen shows the apparent intent marked non-authoritative beside the absent write.
`ARCHITECTURE_PLAN.md` carries the same shape: `classify_reply_intent` is one of the frozen
semantic jobs, and the frozen step chain sequences it before the confirmation prompt.

So the apparent intent is not incidental telemetry that happens to be logged. It is a locked,
demonstrable artifact of the product's central claim — the system read the customer, and refused
to act on the reading. Removing it would delete the visible half of "the model understands; the
deterministic protocol authorizes" from the one place a viewer can watch the protocol decline to
be persuaded. Per `CLAUDE.md`, frozen architecture is not redesigned in place; a decision like
that is amended first, deliberately, and this gate is not that amendment.

## Decision

*Superseded 2026-09-09 by [ADR-0008](adr/0008-remove-runtime-customer-intent-classifier.md); preserved unedited.*

**RETAIN the runtime classifier.** No production routing changes. No provider is selected on the
strength of the targeted set: no measured challenger cleared materiality, and a 12-case
development margin is not grounds to move a production dependency. Configuration stays as
ADR-0004 fixed it.

The honest statement of the position is narrow. Three measured customer-intent configurations
failed the frozen targeted materiality criterion, and the apparent-intent labels do not alter
authorization or any user-visible behaviour; the classifier is retained because the frozen
product contract locks the non-authoritative apparent intent into the consent protocol and into
mandatory Proof E, not because the measurements justified the call on product value.

## Runtime and eval provider boundary

| surface | provider | status |
|---|---|---|
| Worker semantics — `interpret_utterance` | Bedrock, per ADR-0004 | production; not in this gate's scope and not modified (model identity later selected by ADR-0007) |
| Customer intent — `classify_reply_intent` | Bedrock, per ADR-0004 | production; retained, unchanged (model identity later selected by ADR-0007) |
| Local development and CI | `FakeSemanticProvider` | the default everywhere, including the worker |
| OpenAI transport | `scripts/run_intent_challenger.py` | **eval-only** — never had production routing |
| NVIDIA transport | `scripts/run_intent_challenger.py` | **eval-only** — never had production routing |

`LlmProvider` is a closed enum of `fake` and `bedrock`, so there is no dead production routing to
remove: the OpenAI and NVIDIA transports were only ever reachable from the challenger script and
remain there as eval infrastructure.

## Open items, since closed

Both were closed by [`runtime-provider-and-storyboard-closeout.md`](runtime-provider-and-storyboard-closeout.md),
with zero model calls and no change to any measurement on this page.

- **The storyboard's specific label was not reproducible.** §21 and `ARCHITECTURE_PLAN.md`'s
  acceptance line both named `"Strawberries work" → APPARENT_APPROVE`, and all three measured
  configurations read it `UNCLEAR`. Proof E's substance was never affected — `UNCLEAR` is a
  non-authoritative apparent intent, produces no write and sends the same prompt. The frozen
  documents were amended to state the reading provider-neutrally rather than to name a label the
  running system does not produce. The gold label is unchanged.
- **ADR-0004 named `claude-haiku-4-5` and the configured default did too.** The selected runtime
  semantic model is now `us.amazon.nova-2-lite-v1:0` for both semantic jobs, recorded as
  [ADR-0007](adr/0007-runtime-semantic-model-nova-2-lite.md). Haiku's quality remains unmeasured;
  it was rejected as the default because the account's Marketplace subscription cannot complete,
  and it remains a supported value of `PP_BEDROCK_MODEL_ID`.

## Revisit trigger

Amend the frozen documents first, not the code, if the apparent intent is to leave the consent
protocol. Short of that: a challenger that clears the frozen materiality floor on the targeted set
would justify a provider change, and would not require any of the analysis above to be redone —
the behavioural matrix holds whatever label the provider returns.
