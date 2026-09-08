# Challenger harness hardening — the accidental live path, and what it cost

> **Haiku quality: NOT MEASURED.** No semantic reading has ever been obtained from
> `us.anthropic.claude-haiku-4-5-20251001-v1:0` in this repository. Nothing on this page is
> evidence about that model, and no page in this repository is. **Holdout: not opened.**
> **For the work recorded on this page — Nova calls: 0. Haiku calls: 0. OpenAI calls: 0.**

This is the record of a harness defect, the evidence it produced, and the guards added because
of it. It is written down rather than tidied away because the sequence — a safe-looking test
became a live benchmark, and the thing that stopped it spending was AWS — is the most useful
piece of engineering evidence this slice has produced.

---

## What happened

Two live runs were attempted on 2026-09-07. Neither obtained a single semantic reading.

### Run `ceb14bb15b02` — the accidental one

At commit `03c3723`, 21:54:15Z. Not started by an operator: started by **pytest**.

A test asserted that a model with no verified price cannot be benchmarked, and it asserted it
by running the real command with the model id of the day:

```python
main(["--live", "--split", "development", "--provider", "bedrock", "--model", HAIKU])
```

While Haiku had no price, that line refused for the reason the test claimed. Haiku was then
priced on purpose, for the challenger. From that moment the same line was no longer an
assertion about pricing — it was a live benchmark of the development split, and the split
begins with worker cases.

It built the real Bedrock provider and put **three worker sentences** to it:

| case | job | outcome |
|---|---|---|
| `worker.equipment.deck-oven.001` | `interpret_utterance` | provider failure |
| `worker.equipment.deck-oven.002` | `interpret_utterance` | provider failure |
| `worker.equipment.convection-oven.002` | `interpret_utterance` | provider failure |

Three calls, three attempts, **zero readings**, zero token usage reported. The stop policy
fired at the third failure and ended the run.

The worker job is not what P4.6 is about, and no worker challenger was ever authorised. These
calls were outside the slice entirely.

### Run `8c78170b6bf4` — the intended Stage A

At commit `7ef11cb`, 22:03:21Z. Started deliberately, as the challenger's Stage A.

| case | role | outcome |
|---|---|---|
| `customer.approve.terse.001` | failure | provider failure |
| `customer.approve.terse.003` | control | provider failure |
| `customer.approve.terse.005` | control | provider failure |

Three calls, three attempts, **zero readings**, zero token usage reported. The stop policy
fired again.

### What the report then said, and why it was wrong

The paired report classified those three unanswered calls as:

```text
customer.approve.terse.001   UNCHANGED_FAILURE
customer.approve.terse.003   CONTROL_REGRESSION
customer.approve.terse.005   CONTROL_REGRESSION
```

Every one of those labels asserts that a model read a sentence and read it wrongly. **None of
the three sentences had been read.** The repair rate and the regression count computed from
them were arithmetic over absences, and the whole block looked like evidence about a model
while being evidence about an account.

---

## The two defects

**A — safety rested on things that change.** The harness's protection against paid inference
from a test was, in order: the model was unpriced, then the credentials were absent, then the
account had no access. Every one of those is something a person may fix on purpose one
afternoon without noticing what they removed. The first was removed deliberately. The last one
is what actually stopped the spend, which means the repository was being protected by AWS.

**B — an execution failure could wear a quality label.** `provider_error` was recorded on the
result, and then nothing downstream consulted it: the paired taxonomy asked only "is the
challenger's label the gold label", and a missing label is not the gold label.

---

## What was hardened

### Spend authorisation, scope-bound and command-line only

`--live` now names a code path and nothing else. Being charged additionally takes a phrase
typed at the invocation, naming the exact scope it pays for:

```bash
uv run python -m scripts.run_intent_challenger --live --provider bedrock --model <id> \
    --stage a --authorise-paid-inference AUTHORISE-PAID-INFERENCE-STAGE-A
```

It is never read from the environment, never from `.env`, never defaulted, and never carried
from one stage to the next — a Stage-A approval is refused for Stage B, which matters because
Stage A was the only thing that had been approved. The phrase is not a secret and is not
authentication; it is an intentionality gate, and publishing it costs nothing.

Authorisation does not replace the budget. Both are required: a deliberate decision to spend,
and a hard ceiling that refuses the call which would cross it.

### A test process cannot construct a paid provider

Beside the operator guard, and not consulting it, is an interlock: the real provider builder
refuses inside pytest, before the Bedrock import on the line below it. It does not care what
phrase was typed, whether the model is priced, whether credentials are present, or whether the
account has access — none of those was ever what kept CI safe.

The builder is also a parameter rather than a branch. A test that needs the orchestration
passes one that reaches nothing; the real one is a default nobody in a test can get past.

CI runs the whole interlock suite a second time with a complete, syntactically valid set of AWS
variables, so "CI has no credentials" is demonstrated to be irrelevant rather than relied on.

### Provider failures are a first-class state

`CaseResult.execution_status` derives one of `ANSWERED`, `PROVIDER_FAILURE`, `NOT_INVOKED` from
facts the result already carries — so every result file written before the type existed reads
back correctly, and no migration was needed.

- `PairedOutcome.PROVIDER_FAILURE` exists, and the four quality outcomes now require two
  readings.
- Provider failures are excluded from the repair-rate denominator, from wins/losses/ties, from
  per-cluster recall, and from the customer quality aggregates.
- A provider failure leaves the stage **incomplete**, and an incomplete stage cannot clear
  materiality — so Stage B stays closed on an execution failure however good the partial
  numbers look.
- The verdict says `STAGE A INVALID FOR A QUALITY DECISION — EXECUTION FAILURE`, never "not
  material". Reporting a model as unmaterial on the strength of an unreachable endpoint is the
  error this whole page is about.

Failure categories are deliberately coarse — `TIMEOUT`, `PROVIDER_UNREACHABLE`,
`UNKNOWN_PROVIDER_FAILURE` — derived from the boundary's exception class, which is the only
thing about a fault that reaches a stored result. Production was **not** widened to publish a
sanitised provider code, and no raw provider message is ever persisted.

### Failed attempts are kept, and kept somewhere they cannot be read back as answers

A refusal now goes to a separate attempt log rather than being discarded or written into the
readings file. A resumed run therefore asks the case again once the infrastructure is fixed,
the historical refusal survives beside the eventual answer, and no outage is ever frozen into
the record as a reading. The log holds identifiers, a coarse category and timings — no
credential, no session token, no request header, no prompt, no provider message. Token counts
and cost are **absent, not zero**: AWS reported no usage, and a zero would be a measurement
nobody made.

`--from-results` rebuilds the whole execution-and-quality picture from the readings file plus
the attempt log, with the provider builder raising if touched.

---

## Cost

**No measurable token-based spend.** Both runs reported zero token usage, so no token-based
estimate exists for either — which is a statement about what AWS reported, not a claim that
nothing was billed. **AWS Billing remains authoritative**; this repository's ledger is an
estimate and has never been anything else.

The two ledger lines record `estimated_usd: null`, `input_tokens: null`, `output_tokens: null`.
Nothing was invented to fill them.

---

## Pricing audit — no model calls, no AWS authentication

Both entries were re-checked against the public AWS Price List bulk API. No Bedrock call, no
AWS Billing, no Cost Explorer, no credentials.

### Nova 2 Lite — **corrected**

`us-east-1` publishes exactly two on-demand tiers for this model:

| usage type | SKU | input / 1M | output / 1M |
|---|---|---|---|
| `USE1-Nova2.0Lite-input-tokens` / `-output-tokens` | `FY8T82UUN7VZR55K`, `DY69Q8C3F88CHA2Q` | **$0.33** | **$2.75** |
| `USE1-Nova2.0Lite-input-tokens-cross-region-global` / `-output-tokens-cross-region-global` | `EPMQ24NAG4R6FPX8`, `PT8HC9XDED4UMEZX` | $0.30 | $2.50 |

Offer `AmazonBedrock`, version `20260901205051`, published 2026-09-01T20:50:51Z, read
2026-09-08.

The catalog held **$0.30 / $2.50** — the Global pair. The model this repository calls is
`us.amazon.nova-2-lite-v1:0`, a **US geo cross-Region inference profile**, and the
`-cross-region-global` usage type belongs to `global.amazon....`, which this repository does not
call. There is no third, `us`-specific usage type, and that absence is itself the evidence: a
geo profile bills at the source Region's own on-demand rate, which is the first pair.

This is the same distinction the Haiku entry was already recorded against. The Nova entry had
taken the cheaper of two published figures, and the cheaper one was the wrong one.

**Corrected to $0.33 / $2.75.** Arithmetic only: no model output, no reading and no quality
number anywhere changes.

Historical estimates, recomputed:

| run | input | output | estimate as recorded | corrected |
|---|---|---|---|---|
| `a2470b4320e5` | 27,921 | 1,148 | $0.0112463 | **$0.0123709** |
| `36c1f008de80` | 83,554 | 2,634 | $0.0316512 | **$0.0348163** |
| total | | | $0.0428975 | **$0.0471873** |

An understatement of $0.0043, about 10 %. The ledger lines are **not rewritten** — they record
what was estimated at the time, which is what an append-only ledger is for. The corrected
figures are here.

### Claude Haiku 4.5 — **retained, re-verified**

| usage type | SKU | per 1M |
|---|---|---|
| `USE1-MP:USE1_InputTokenCount-Units` | `JQDUC8Q4K8C6GSGH` | $1.10 |
| `USE1-MP:USE1_OutputTokenCount-Units` | `X629GDA2GXAP6R54` | $5.50 |
| `USE1-MP:USE1_InputTokenCount_Global-Units` | `DY4B4Q3TRTAY8V6G` | $1.00 |
| `USE1-MP:USE1_OutputTokenCount_Global-Units` | `XADKFYXVGBFBJSU7` | $5.00 |

Offer `AmazonBedrockFoundationModels`, version `20260901183649`. The catalog holds the Regional
pair, which is the one a `us.anthropic....` profile bills at. **Unchanged.**

---

## Preserved evidence

Nothing was deleted or rewritten. The artifacts are local and git-ignored, under
`.eval-results/`:

| file | what it is |
|---|---|
| `ceb14bb15b02.json`, `ceb14bb15b02-preflight.txt` | the accidental benchmark run |
| `development-us.anthropic.claude-haiku-4-5-20251001-v1_0.jsonl` | its result file: eight never-asked worker cases, no readings |
| `8c78170b6bf4-challenger.json`, `8c78170b6bf4-challenger-preflight.txt` | the Stage-A attempt, **including the three mislabelled classifications** |
| `challenger-us.anthropic.claude-haiku-4-5-20251001-v1_0.jsonl` | header only, because three failures produced no readings to write |
| `cost-ledger.jsonl` | both runs, with null tokens and null estimates |

The `8c78170b6bf4-challenger.json` report is left exactly as it was written. It is wrong, this
page says how it is wrong, and a corrected report of the same run is reproducible offline —
`--from-results` now reads the attempt log and reports the same three cases as
`PROVIDER_FAILURE`, with no calls.

The header-only challenger result file names commit `7ef11cb`. The harness has changed since,
so the result store refuses to continue it rather than appending readings bought under one
version of the code to a run identified as another. That refusal is a tested behaviour. A
future live attempt takes a **new run identity**; the old file is not edited.

---

## What this does not do

This gate obtained no reading, changed no production code, ran no migration, altered no
threshold, touched no gold data and opened no holdout. It did not request Bedrock model access,
accept Marketplace terms, modify IAM or authenticate to AWS. Whether to pursue Haiku access at
all is a separate decision, and it is still open.

---

## Stage A carries its own hard budget

The global `CHALLENGER_CEILING` — 30 calls and $0.15 — covers the whole challenger: Stage A,
Stage B and any resumed attempt. It is deliberately generous enough to hold both stages, which
means it is **not** a bound on Stage A. A Stage-A run approved at three cents was, in the code
as it stood, permitted fifteen.

That gap was found during a preflight, before any call. Stage A now carries its own ceiling:

```python
STAGE_A_CEILING = EvalBudget(
    max_calls=12,
    max_estimated_usd=Decimal("0.03"),
)
```

Twelve is the selection's own size — six failures and six matched controls — so the call cap
and the experiment are the same number rather than two numbers that have to be kept in step.

**Both ceilings remain in force.** `stage_ceiling()` composes them with
`evals.budget.tightest()`, which takes the smaller of each field, and `None` means *uncapped*
and always loses. So the stage bound narrows calls and dollars, while the global ceiling's
token caps carry through untouched — a field a stage bound is silent about keeps the wider
protection rather than losing it. Composition can only ever narrow: that is asserted, both
ways round, rather than assumed.

The effective allowance is still the composed ceiling *less what the local ledger says this
model already used*, so a resumed Stage A does not get a fresh three cents.

**Stage B is unchanged.** It has no entry in `STAGE_CEILINGS`, so it keeps the global 30-call
/ $0.15 protection exactly as before, and it remains separately authorised: a Stage-A phrase
is refused for Stage B at the parse, before a dataset is read or a price is looked up.

### Why not a flag

`--max-estimated-usd` would have been three lines. It was rejected on purpose. A ceiling typed
at the invocation is a ceiling that depends on whoever is at the keyboard getting it right at
the end of a long session — and the failure this whole page documents is precisely a safety
property that rested on somebody noticing. The bound belongs to the frozen experiment
protocol, so it lives in a commit somebody reviews. There is a test asserting no such flag
exists.

The preflight prints all three figures — global, stage, effective — so a stored preflight can
answer *which bound would have refused* without the operator present.

---

## Audit note — holdout inputs displayed during a preflight

During the preflight that found the gap above, a search for one canonical development case
(`customer.approve.terse.001`, "Strawberries work") printed the matching rows of the customer
dataset, and six of those rows were **holdout** cases. Their input strings were displayed in
the operator's terminal.

Recorded here rather than left out, because a page about a harness defect that quietly omitted
an exposure of its own would be worth less than no page.

What that did **not** do:

- **No holdout gold label was used for tuning.** No threshold, prompt, schema, selection rule
  or scorer was changed, and nothing was changed *because of* those inputs.
- **No holdout model call occurred.** The holdout is excluded structurally: selection filters
  to the development split before anything else reads a result, `narrow()` cannot return a
  holdout case, and there is no flag that opens it. All three are tested.
- **No dataset change.** The gold data is untouched and its hash is unchanged:
  `9cf1ab7820cac2be9a586328b8d500def0f34e40fe516cc8cd35e39e5a2144fd`.
- **No production semantic change.** No prompt, no tool schema, no boundary behaviour.
- **No model call of any kind** was made in that session — Haiku, Nova or otherwise.

The exposure is to the operator's terminal, not to a model and not to the harness. The holdout
remains unopened for evaluation purposes, and those inputs are not to be inspected again.

---

## The challenger is replaced: Haiku 4.5 → `gpt-4o-mini-2024-07-18`

Recorded on 2026-09-08. This is a change of challenger, not a finding about one.

### Why Haiku was dropped

```text
valid Haiku semantic readings:  0
Haiku quality conclusion:       NONE
reason for replacement:         AWS Marketplace INVALID_PAYMENT_INSTRUMENT
```

Every attempt against `us.anthropic.claude-haiku-4-5-20251001-v1:0` was refused by the AWS
data plane before the model was reached. CloudTrail records `AccessDenied` with
`INVALID_PAYMENT_INSTRUMENT`, and the Marketplace condition behind it:

> A valid payment instrument must be provided. Your AWS Marketplace subscription for this
> model cannot be completed.

That is an account-level billing constraint on a third-party model billed through AWS
Marketplace — the distinction already recorded against `CLAUDE_HAIKU_4_5` in the price
catalog, which is a first-party/third-party billing fact rather than a quality one.

**Nothing about Haiku's ability to read a customer's sentence was measured, and nothing on
this page or anywhere in this repository is evidence about it.** The historical artifacts —
the header-only result file, the provider-failure log, the preflights, the ledger lines — stay
on disk exactly as written. They are the record of what infrastructure did. They are not model
errors and must not be reinterpreted as any.

### What replaces it

```text
provider:  OpenAI
model:     gpt-4o-mini-2024-07-18
```

The pinned snapshot, never the floating `gpt-4o-mini` alias. An alias is a pointer the
provider may repoint, so a benchmark recorded against one would describe whichever model
answered that day; the command refuses the alias by name and tells the operator to type the
date. Price, result file, run header identity and ledger totals are all keyed on the pair
`(provider, model)`, so an alias run and a snapshot run can never merge.

**GPT-4o-mini was not chosen because it performed better. It has not been tested.** It is a
challenger that can be reached and paid for. Whether it repairs anything is what Stage A
exists to find out, and Stage A has not been run.

### What did not change

The experiment is the frozen one, and only the challenger's model differs:

| held fixed | value |
|---|---|
| dataset | `promisepatch-semantic-gold` v1.0.0, `9cf1ab7820ca…144fd` |
| source run | Nova `36c1f008de80`, read from disk and never re-run |
| Stage-A set | the same 6 failures and 6 matched controls, re-derived not re-matched |
| job | `classify_reply_intent` |
| prompt and schema | production's own, byte-identical across both adapters |
| scorer | unchanged, same denominators |
| Stage-A materiality | repair rate ≥ 0.50, ≥ 2 repairs, 0 inversions, ≤ 1 control regression, 0 safety violations |
| approved thresholds | macro F1 ≥ 0.80, terse-assent recall ≥ 0.80, indirect-refusal recall ≥ 0.80 |
| production routing | unchanged; `LlmProvider` is still `fake \| bedrock` |

The controls are deliberately **not** re-matched for the new challenger. Selection reads the
stored Nova results and cannot see who is being challenged, so re-running it produces the same
twelve cases — which is what keeps the comparison paired across models rather than a fresh
experiment wearing the old one's name.

### The OpenAI ceilings

Its own, because the two models are an order of magnitude apart in price and a cap sized for
the dearer one is not a cap on the cheaper one.

```text
gpt-4o-mini-2024-07-18   $0.15 / 1M input     $0.60 / 1M output   (verified 2026-09-08)

global OpenAI challenger ceiling   30 calls   100k in   10k out   $0.03
OpenAI Stage-A ceiling             12 calls                       $0.01
effective Stage-A allowance        12 calls   100k in   10k out   $0.01
```

At the recorded price the token ceilings come to $0.021, so the global dollar cap sits above
what the token bounds already permit — a backstop for arithmetic nobody re-checked, not the
bound expected to bite. Stage A's cent is stricter than all of it, and twelve is the
selection's own size rather than a number retyped at a keyboard.

The Bedrock ceilings are untouched. Adding a provider is not repricing the one already there,
and the ledger now matches on `(provider, model)` so neither challenger's history can debit
the other's allowance. Lines from a wholly failed run name no model at all — the id is read
off what came back — and those are reported beside the totals rather than charged to whichever
model asks next.

### Spend safety, unchanged and extended

`--live` still buys nothing. The scope-bound phrase is still typed at the invocation and read
from nowhere else, a Stage-A authorisation is still not a Stage-B authorisation, and a process
running under pytest still cannot construct a paid provider — now proved for the OpenAI
builder as well as the Bedrock one, with a syntactically valid key present throughout so that
what refuses is demonstrably the harness rather than the credential.

One gate is new, and it is the last one before a client can exist: a live OpenAI stage refuses
when `OPENAI_API_KEY` is absent, before the provider builder is called, with no fallback to
another provider or another model. The key is read from the environment or from the ignored
local `.env`, is handed to exactly one constructor, and is never printed, logged, persisted or
returned to anything that formats. Everything visible anywhere — the plan, the preflight, this
page — is a boolean.

### Accounting for the integration itself

```text
OpenAI model calls:  0
Nova calls:          0
Haiku calls:         0
model spend:         $0
holdout model calls: 0
migrations:          none
```

Stage A had not been run when this page was written. It has been run since, against
`gpt-4o-mini-2024-07-18`: twelve calls, twelve readings, no provider failure, $0.00114675. It
repaired two of Nova's six customer-intent failures against a floor of three, preserved all six
matched controls, and did **not** clear materiality, so Stage B was not opened. The record is
[`docs/customer-intent-challenger-stage-a.md`](customer-intent-challenger-stage-a.md).
