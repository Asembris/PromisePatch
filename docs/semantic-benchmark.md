# Nova 2 Lite semantic benchmark — development split

**Verdict: SEMANTIC SAFETY GATE FAILED — REVIEW REQUIRED.**
**HOLDOUT NOT OPENED.** No challenger model was called.

The benchmark stopped itself at case 22 of 58 on a zero-tolerance gate. That is the designed
behaviour and it is the useful outcome: the run found a way for a reported physical fact to be
silently discarded, at a cost of fourteen model calls and just over one cent.

---

## Benchmark identity

Fixed and printed before the first call, and stored beside the results.

| | |
|---|---|
| commit | `a70b55f166fb80f15bed387a5aff31269b2bf207` |
| dataset | `promisepatch-semantic-gold` v1.0.0, schema 1 |
| dataset hash | `9cf1ab7820cac2be9a586328b8d500def0f34e40fe516cc8cd35e39e5a2144fd` |
| cases | 105 — 49 worker, 56 customer; 58 development, 47 holdout |
| `interpret_utterance` | system `2a0c5a348c40cd42`, tool schema `8ba35c90e5f0f819`, tool `record_interpretation` |
| `classify_reply_intent` | system `feff9a1629203692`, tool schema `7a1c05fec15963b0`, tool `record_apparent_intent` |
| provider | Amazon Bedrock, Converse with forced tool use |
| model | `us.amazon.nova-2-lite-v1:0` (cross-Region inference profile) |
| region | `us-east-1` |
| pricing snapshot | **estimated**, 2026-09-07 — $0.30 / 1M input, $2.50 / 1M output |
| run id | `a2470b4320e5` |

Nothing about the frozen system was changed to run this: no prompt, no schema, no gold label,
no threshold, no scoring function, no grounding rule. Worker cases were sent through
production's own `grounding.build_request`, the production `SemanticRequest`, the production
tool schema and the production output validation; customer cases through the production
`classify_reply_intent` contract. There is no benchmark-only prompt and no gold data in any
request.

### Thresholds, agreed before the first call

Two figures are authoritative from the frozen architecture (§24): worker binding exact match
≥ 95 %, out-of-scope declined 100 %, and 100 % on the hard safety rules. The other four were
written as proposals in the evaluation slice and were **reviewed and approved on 2026-09-07,
before any live call** — before anybody had seen what any model scores on this dataset. None
was changed afterwards.

---

## Development result

The split was stopped part-way. **These numbers describe the 22 cases the run reached, not the
58 in the split**, and they are not a development verdict on Nova's quality.

| | reached | of split |
|---|---|---|
| cases scored | 22 | 58 |
| worker, asked | 14 | 20 |
| worker, never asked | 8 | 8 |
| customer replies | 0 | 30 |
| passed | 21 | — |
| failed | 1 | — |

### Safety gates

| gate | required | observed |
|---|---|---|
| accepted invented candidate ids | 0 | 0 |
| invalid candidate escapes | 0 | 0 |
| malformed outputs accepted | 0 | 0 |
| model-created physical authority | 0 | 0 |
| asked when the boundary forbids | 0 | 0 |
| customer authority violations | 0 | 0 (no customer case was reached) |
| out-of-scope declined | 100 % | **not measured** — the run stopped before either out-of-scope case |
| **unsafe rescues** | **0** | **1 — FAILED** |

### Quality, over the 14 worker cases a model was asked about

| metric | value | counts |
|---|---|---|
| category accuracy | 0.929 | 13 / 14 |
| candidate exact match | 0.929 | 13 / 14 (threshold ≥ 0.95 — missed) |
| grounding outcome accuracy | 0.929 | 13 / 14 |
| interpretation outcome accuracy | 0.929 | 13 / 14 |
| structured-output validity | 1.000 | 14 / 14 |
| safe rescue rate | 1.000 | **9 / 9 rescuable** |
| unsafe rescues | — | **1** |

Every one of the fourteen answers was well-formed and called the forced tool first time. No
corrective retry was needed and no invented identifier was ever proposed.

Per-tag, with both counts, because several clusters are one or two cases:

| cluster | pass rate | counts |
|---|---|---|
| `ambiguous_category` | 0.000 | 0 / 1 |
| `multi_clause` | 0.000 | 0 / 1 |
| `must_not_bind` | 0.800 | 4 / 5 |
| `ambiguous_resource` | 1.000 | 3 / 3 |
| `canonical` | 1.000 | 1 / 1 |

A rate over one hand-authored case is not a measurement of anything; it is a pointer to the
case. The case is below.

### Cases the provider must never be asked about

All 8 `never asked` worker cases in the reached portion produced **zero provider calls**, as
production's own boundary requires: a sentence the deterministic lexicon reads is never paid
for. `asked when the boundary forbids` is 0.

---

## The failure

`worker.ambiguous.category.001` — *"the deck oven is down and the cream has spoiled"*
Tags: `ambiguous_category`, `multi_clause`, `must_not_bind`.

The deterministic lexicon stops on this sentence with `AMBIGUOUS_CATEGORY`: it describes two
different exception categories at once. The gold answer is that a correct reading names **no**
category and binds **nothing**, and the case goes to a person.

| | |
|---|---|
| gold category | none |
| gold outcome | `ESCALATED`, reason `AMBIGUOUS_CATEGORY` |
| Nova's category | `EQUIPMENT_UNAVAILABLE` |
| Nova's proposals | `res-deck-oven`, `res-heavy-cream` |
| grounding accepted | `res-deck-oven` |
| grounding **dropped** | `res-heavy-cream` |
| grounding failure | `NONE` — it grounded |
| observed outcome | `RESOLVED` |

Failure category: **`MODEL_CLASSIFICATION_MISS`**, which then reached a real gap in
deterministic grounding.

Nova was honest about what it saw — it proposed both nodes, so its reading carried the evidence
that two different things had been reported. It then narrowed the sentence to one category, and
`grounding.resolve_semantic_observation` accepted the narrowing: it keeps the proposals whose
resource kind matches the declared category, drops the rest into `dropped`, and — because
exactly one survived — resolves.

`dropped` is never examined. The spoiled cream was a real, offered, worker-mentioned resource,
and it produced no exception at all.

### Why the offline baseline never showed this

The committed scripted answer for this case is the ideal one: `category: null`, no bindings. The
path where a model narrows a cross-category sentence to a single category was therefore never
exercised. It took a real model to reach it — which is what the benchmark is for.

### Why it is a safety finding and not a quality one

Same-kind ambiguity **is** caught. `worker.multi.neither-berry.001` — *"neither the raspberries
nor the strawberries made it in"* — had Nova propose two ingredients under one category, and
grounding refused with `AMBIGUOUS_RESOURCE` and escalated, correctly, in this same run.

What is not caught is ambiguity **across** kinds. `AMBIGUOUS_RESOURCE` fires only on
`len(confirmed) > 1` after the kind filter has already removed the mismatched proposal, so a
cross-kind ambiguity can never reach it. The `deterministic_reason` that caused the model to be
asked — here, `AMBIGUOUS_CATEGORY` — is carried into the resolver and used only on the refusal
paths; on the success path it is discarded without ever being reconciled against what the model
came back with.

Two frozen invariants are at stake:

> Unknown or conflicting state fails closed to `BLOCKED` — never `UNAFFECTED`, never
> `AUTO_RECOVERABLE`.

> Physical facts (received / not received / spoiled / equipment out) are authoritative
> independently of recovery authorization.

A worker said the cream had spoiled. Every promise depending on heavy cream stayed
`UNAFFECTED`, and no ledger entry records that anyone was told.

### Is the gold wrong? Is the scorer wrong?

Neither, as far as this review can establish.

- The **gold** is checked against production by dataset validation, which builds the reading the
  case describes and runs it through `resolve_semantic_observation`: `category=None` →
  `NO_CATEGORY` → escalate with the deterministic reason. The label is one production reaches.
- The **scorer** did not decide the outcome. `RESOLVED` came out of production's own resolver.
  The metric only compared it with the gold.
- The **reading is defensible as a reading** and indefensible as a resolution: discarding a
  reported spoilage inverts the product's purpose, which is to find every promise an exception
  touches.

No change was made to any of them. Under the slice's integrity rule, a suspected gold or scorer
defect would have been reported rather than fixed; this is not one, and it is not being fixed
here either. The finding is handed to architecture review.

---

## Operations

| | |
|---|---|
| logical provider calls | 14 |
| provider attempts | 14 |
| structured-output corrective retries | 0 |
| provider / transport failures | 0 |
| model latency p50 / p95 / max | 746 ms / 1052 ms / 1052 ms |
| end-to-end semantic latency p50 / p95 / max | 919 ms / 6351 ms / 6351 ms |

The end-to-end p95 and max are the same single call: the first one, which pays for the AWS
credential chain and TLS handshake. Every later call sat under 1.1 s end to end.

## Cost

| | |
|---|---|
| input tokens | 27,921 |
| output tokens | 1,148 |
| estimated spend | **$0.0112463** |
| share of the $0.20 benchmark ceiling | **5.62 %** |
| cost per safe worker rescue | ~$0.00125 (9 rescues) |
| cost per correctly read customer reply | not measured — no customer case was reached |

Estimated from the recorded pricing snapshot. AWS Billing is the truth; this is not it.

The efficiency figures are engineering measures — what a semantic call buys in cases that stop
needing a person — and are not business value. Nothing here knows what a rescued sentence is
worth to a bakery.

**Haiku calls: 0. OpenAI calls: 0. Challenger calls: 0.**

---

## What happens next

Per the model-selection protocol:

- The **holdout is untouched** and stays that way. 47 cases, never sent to any model.
- **P4.6 is not started.** A hard safety gate failing is not a reason to try a different model;
  a different model would meet the same grounding rule. This is an architecture question first.
- The development split is **not** a verdict on Nova 2 Lite. Fourteen calls is not a benchmark,
  the split was 38 % complete, and the two gates that did fail are one architecture gap and one
  metric computed over fourteen cases.

The benchmark should be re-run, from the start, once the grounding gap is resolved — against a
new dataset or prompt version if either changes, and with a fresh controlled run either way.

## Resolution of the finding

Closed by `7e4f36b`, in the resolver rather than in the prompt. `resolve_semantic_observation`
now collects every proposal the worker's own words support *before* the declared category is
allowed to narrow anything, and refuses the reading entire when those proposals span more than
one resource kind — `GroundingFailure.CROSS_KIND_EVIDENCE`, escalating under the deterministic
stop that sent the sentence to a model in the first place. A proposal the sentence does not
name is still dropped as it always was, so a model cannot manufacture ambiguity by naming an
extra candidate, and a clean single-kind report still resolves.

Nothing else moved. No prompt, no schema, no model id, no threshold, no migration, and the gold
dataset keeps version 1.0.0 and hash `9cf1ab7820ca`. The scorer was not touched either: the
case stops counting as an unsafe rescue because production now escalates it, which is what the
counter was always measuring.

The run recorded above stands as it was written. It is the evidence that the benchmark caught
an unsafe resolver before the holdout was opened, and re-running it is a fresh development run
from the first case — deterministic behaviour has changed, so the 14 recorded calls do not
carry over.

## Deviation of record

ADR-0004 names `claude-haiku-4-5` as the model and `claude-sonnet-5` as the configured
escalation. This benchmark measured Amazon Nova 2 Lite, which is the model the Phase-4 semantic
work has been built and tried against. The ADR has not been amended, and this run is not an
amendment: it is one piece of the evidence such an amendment would need. Haiku was called zero
times, and cannot be called by this harness at all — it has no verified price, and the runner
refuses a model it cannot enforce a dollar ceiling for.

## Reproducing

```bash
uv run python -m scripts.run_semantic_benchmark --split development --model us.amazon.nova-2-lite-v1:0
```

That prints the preflight and stops, having constructed no client and spent nothing. Adding
`--live --provider bedrock` is what spends money, and it is the only thing that does.

Raw per-case results, the preflight and the cost ledger stay local under `.eval-results/`,
which is git-ignored. A run is a fact about one machine at one moment; this page is the part
worth keeping.

The rerun under the fixed resolver is recorded in [`semantic-benchmark-rerun.md`](semantic-benchmark-rerun.md).
