# Runtime provider and storyboard closeout

> **Zero model calls.** Nova: 0. GPT-4o-mini: 0. Nemotron: 0. Haiku: 0. NVIDIA: 0. Ollama: 0.
> Holdout: 0. Spend: $0. No benchmark was run, recomputed or rewritten. Every number on this
> page is read from artifacts that already existed and from the code in this commit.

[`customer-intent-architecture-closeout.md`](customer-intent-architecture-closeout.md) recorded
two open items rather than closing them. This page closes both.

1. The configured runtime model named Claude Haiku 4.5, which this account cannot invoke.
2. The frozen storyboard named `APPARENT_APPROVE` as the reading of `"Strawberries work"`, which
   no measured provider returns.

Neither is an authority question. Nothing below changes who may authorise a recovery.

---

## 1. What the runtime actually configures

`Worker` holds one `SemanticProvider` field, built once by `build_semantic_provider(settings)`,
and routes both semantic step kinds through it — `semantic_intake.prepare` for the worker's
sentence and `customer_intent.prepare` for the customer's reply. `BedrockSemanticProvider`
carries one `model_id`, read from `PP_BEDROCK_MODEL_ID`.

So the two jobs do not have independent provider or model configuration, and giving them one
would mean building a second provider and adding a per-job setting — the multi-model routing
ADR-0004 rejected. **Selecting a model selects it for both jobs.**

| runtime semantic job | provider/model before | operational? | measured evidence |
|---|---|---|---|
| Worker — `interpret_utterance` | Bedrock, `us.anthropic.claude-haiku-4-5-20251001-v1:0` | **no** — Marketplace `INVALID_PAYMENT_INSTRUMENT` | none for Haiku. The worker split was measured on Nova 2 Lite |
| Customer — `classify_reply_intent` | the same setting, the same model | **no** — same blocker | none for Haiku. Three challengers were measured on Nova, GPT-4o-mini and Nemotron |

Haiku's **quality is not measured and is not in question**. What is established is only that it
cannot be called from this account.

## 2. Candidates

| candidate | operational | measured customer evidence | complexity | verdict |
|---|---|---|---|---|
| **Nova 2 Lite** (`us.amazon.nova-2-lite-v1:0`) | **yes** — already the benchmarked path | 12/12 valid, 6/12 correct on the targeted set; 0.800 accuracy / 0.806 macro F1 over 30 replies; terse-assent recall 0.40 and indirect-refusal recall 0.75 both **below** the 0.80 floor | lowest — one provider, one credential chain, one IAM path, already wired | **selected** |
| GPT-4o-mini-2024-07-18 | yes, with an OpenAI key | 12/12 valid, 2/6 repairs, repair rate 0.333, 0/3 approve-side, controls 6/6 — **materiality FAIL** (floor 0.50) | a second production provider, a second credential, a second failure surface on the consent path | rejected — non-material margin |
| NVIDIA Nemotron 3 Super | hosted prototype endpoint | 12/12 valid, 0/6 repairs, repair rate 0.000, controls 6/6 — **materiality FAIL** | as above, plus a prototype endpoint on a production path | rejected — no repair at all |
| Claude Haiku 4.5 | **no** — Marketplace `INVALID_PAYMENT_INSTRUMENT` | 0 readings — **quality not measured** | unchanged | rejected as the *default*; retained as a supported value |

## 3. Selection

```
WORKER SEMANTIC PROVIDER            Bedrock
CUSTOMER APPARENT-INTENT PROVIDER   Bedrock
MODEL                               us.amazon.nova-2-lite-v1:0
```

Recorded as [ADR-0007](adr/0007-runtime-semantic-model-nova-2-lite.md), which amends ADR-0004 on
the model identity only.

Measured customer quality did not select this, because no challenger cleared the frozen
materiality floor and a twelve-case development margin is not grounds to move a production
dependency. With quality unable to decide, what decides is operational: Nova 2 Lite is reachable
today, it is AWS-native, it is the model the worker benchmark was actually taken against, and it
keeps PromisePatch on one provider.

The honest statement of Nova's customer quality is that it **failed two approved recall
thresholds and those failures are unrepaired**. That is tolerable here for exactly one reason:
the label changes no authoritative behaviour, so a better or worse reading buys the same single
confirmation prompt. This is not a claim that Nova reads customers well.

The eval-only OpenAI and NVIDIA transports stay where they are, in
`scripts/run_intent_challenger.py`. Neither ever had production routing and neither gains one.

## 4. The storyboard label

| | `"Strawberries work"` |
|---|---|
| gold (`promisepatch-semantic-gold` v1.0.0, `customer.approve.terse.001`) | `APPARENT_APPROVE` |
| Nova 2 Lite | `UNCLEAR` |
| GPT-4o-mini-2024-07-18 | `UNCLEAR` |
| NVIDIA Nemotron 3 Super | `UNCLEAR` |

The gold label is **unchanged**. Gold is the human-authored intended reading; the runtime
readings are what the models actually returned. They disagree, and that disagreement is
evidence. Erasing it by editing gold would destroy the only record that three models missed the
same case.

What was not done, and will not be: no regex, no phrase special-case, no in-context example, no
prompt tuning for this sentence, no edited model results.

What was done is the reverse. The storyboard asserted a label the running system does not
produce, so the storyboard was corrected to match the system.

### Frozen-contract amendment

`PROMISEPATCH_PRODUCT_SPEC.md` and `ARCHITECTURE_PLAN.md` are local-only and remain untracked.
Three lines changed, plus an amendment note in each document's status block:

| document | location | change |
|---|---|---|
| spec | §8 step 9 | "classifies the apparent intent as approval" → "produces a non-authoritative apparent-intent reading; which of the three labels it lands on changes nothing" |
| spec | §21, the Proof E row | "LLM apparent intent: `APPARENT_APPROVE`" → "LLM apparent intent: whatever the configured model reads — `UNCLEAR` on every provider measured to date" |
| plan | Phase 4 acceptance | `"Strawberries work" → APPARENT_APPROVE non-authoritative` → `"Strawberries work" → a non-authoritative apparent intent that authorises nothing (measured: UNCLEAR)` |

Everything else stays frozen. §13.6 already routes all three labels to the same single prompt
and needed no change. §22's Proof E obligation was already provider-neutral — "free-text reply
produces a non-authoritative apparent intent and **no write**" — and is untouched. §28's Explicit
Locks are untouched: its Demo scenario row locks the §21 storyboard and never named a label
itself, and its Human approval and Trust model rows are unaffected.

### Why this is the stronger demo, not a weaker one

The amended sequence is a better demonstration of the product's central claim than the original.

```
Customer   "Strawberries work"

           MODEL INTERPRETATION   UNCLEAR
           AUTHORITY              NONE
           WRITE                  NONE
           REQUIRES               LITERAL CUSTOMER CONFIRMATION

System     "To confirm this change, reply YES. Reply NO to decline."

Customer   "YES"

           DECISION               APPROVE
           PARSER                 LITERAL
           REVALIDATION           10 / 10
```

The original storyboard asked a viewer to watch a model read the customer correctly and then
watch the protocol refuse to act on a correct reading. The amended one shows the protocol
holding when the model did **not** read the customer confidently — which is the case the trust
boundary exists for. "The model understands; the deterministic protocol authorizes" is easier to
believe when the demonstration does not depend on the model understanding.

## 5. What did not change

Authority, unchanged and re-asserted by test:

```
APPARENT_APPROVE  → no ApprovalDecision
APPARENT_DECLINE  → no ApprovalDecision
UNCLEAR           → no ApprovalDecision
literal YES       → the existing authoritative approve path
literal NO        → the existing authoritative decline path
```

The literal parser's vocabulary was not widened. The ten §14.3 revalidation checks were not
touched. Wrong-sender refusal, one-consumption semantics and external-write timing were not
touched. The worker's grounding, candidate construction, cross-kind conflict handling, physical-
fact authority and correction semantics were not touched.

Historical evidence, unchanged: the Nova benchmark, the GPT-4o-mini Stage A record, the Nemotron
Stage A record and the Haiku access record are bound to the provider, model, commit, dataset and
prompt hashes they were produced under. No result was recomputed, no threshold was moved, no
dataset row was edited, and the holdout was not opened.

## 6. Revisit trigger

Marketplace access completing does not on its own reopen the model choice — Haiku would have to
be measured first. A challenger clearing the frozen materiality floor reopens the customer job.
A worker-semantics regression below ADR-0004's grounding or JSON-validity triggers reopens both.
