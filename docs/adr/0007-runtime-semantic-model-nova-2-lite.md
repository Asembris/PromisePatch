# ADR-0007 — Runtime semantic model: Nova 2 Lite

Status: accepted — amends ADR-0004 on the model identity only
Date: 2026-09-08
Phase: 4

## Decision

The one model both runtime semantic jobs are called through is `us.amazon.nova-2-lite-v1:0`,
via a cross-Region inference profile on Amazon Bedrock. Everything else ADR-0004 fixed is
unchanged: one model for every job, the boto3 `bedrock-runtime` Converse API, forced tool use
for structured output, Pydantic validation with one corrective retry and a deterministic
fallback.

| runtime semantic job | provider | model | authority |
|---|---|---|---|
| Worker — `interpret_utterance` | Bedrock | `us.amazon.nova-2-lite-v1:0` | candidate bindings only, validated against the graph |
| Customer — `classify_reply_intent` | Bedrock | `us.amazon.nova-2-lite-v1:0` | **non-authoritative** apparent intent; never an `ApprovalDecision` |

The two jobs share one provider by construction: `Worker` holds a single `SemanticProvider`
built once from settings, and routes both step kinds through it. Selecting a model selects it
for both.

## Context

ADR-0004 named `claude-haiku-4-5`, and the configured default named it with it. The P4.6 record
has Haiku returning **no valid readings**: the AWS Marketplace subscription this account needs
cannot complete because of `INVALID_PAYMENT_INSTRUMENT`. That is an access fact and not a
quality one — **Haiku's reading quality was never measured** and nothing here concludes anything
about it.

Meanwhile Nova 2 Lite is the model every measurement PromisePatch actually holds was taken
against, and it is reachable from this account today.

## Alternatives rejected

- **Claude Haiku 4.5 (ADR-0004's model)** — quality unmeasured; cannot be invoked in the target
  account. A default that names a model the deployment cannot call fails on the first spoken
  turn rather than at configuration time.
- **GPT-4o-mini-2024-07-18 for the customer job only** — measured 2/6 repairs on the frozen
  targeted set, repair rate 0.333 against a materiality floor of 0.50: **not material**, and
  0/3 of the repairs were on the approve side. Buying a second production provider, a second
  credential and a second failure surface on the consent path for a non-material margin on a
  twelve-case development set is not a trade this evidence supports.
- **NVIDIA Nemotron 3 Super for the customer job only** — measured 0/6 repairs, repair rate
  0.000: **not material**. It is additionally a hosted prototype endpoint, and "free and larger"
  is not a production argument.
- **Per-job model routing** — ADR-0004 rejected multi-model routing as unjustified complexity
  for closed-label jobs, and no measured evidence reopens that: no challenger cleared
  materiality, so there is no better customer model to route *to*.

## Why

No challenger met the frozen materiality criterion, so measured customer quality does not
select a provider. What is left to decide on is operational: Nova 2 Lite is already reachable,
already AWS-native, already the model the worker semantic benchmark was taken against
(candidate exact match 20/20, interpretation outcome 20/20, structured-output validity 20/20 on
the development split), and it keeps PromisePatch on one provider, one credential chain, one
IAM path and one observability surface.

The customer job's own quality is stated plainly rather than talked up. Nova read the full
30-reply development customer set at accuracy 0.800 and macro F1 0.806, and **failed** two
approved per-tag recall thresholds — terse assent 0.40 and indirect refusal 0.75, both against
a floor of 0.80. Those failures are unrepaired. They are tolerable here for one reason: the
label this job produces changes no authoritative behaviour, so a worse or better reading buys
the same single confirmation prompt.

## Consequences

`PP_BEDROCK_MODEL_ID` defaults to `us.amazon.nova-2-lite-v1:0`. Haiku remains a supported value
of that variable and its Bedrock transport, price entry and tests are untouched — it is a tested
integration that is not the selected runtime.

The customer apparent intent stays exactly what it was: non-authoritative, stored as
`apparent_intent`, visible in the ledger, incapable of naming a decision. Only the literal
parser produces an `ApprovalDecision`, and the ten §14.3 revalidation checks are unchanged.

Historical benchmark artifacts are bound to the provider, model, commit, dataset and prompt
hashes they were produced under, and none of them is rewritten by this decision. The eval-only
OpenAI and NVIDIA transports keep their place in `scripts/run_intent_challenger.py`; neither
ever had production routing and neither gains one here.

## Revisit trigger

Marketplace access completing does not by itself reopen this — Haiku would first have to be
measured. A challenger that clears the frozen materiality floor on the targeted set reopens the
customer job; a worker-semantics regression below ADR-0004's grounding or JSON-validity triggers
reopens both.
