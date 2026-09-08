# Nemotron 3 Super Stage A — the third targeted challenger, measured

> **HOLDOUT NOT OPENED.** Holdout model calls: 0. Worker calls: 0. Nova calls this run: 0.
> GPT-4o-mini calls this run: 0. Haiku calls: 0. Ollama calls: 0.
> **Stage B was not opened and was not authorised. Production routing unchanged.**

Stage A of the NVIDIA challenger has now been run. This page is the record of what it found.
Every number here is derived from the persisted run artifacts; rebuilding this page calls
nothing.

The question is the one the previous two challengers were asked, unchanged: **does the
challenger repair the specific customer-intent failures that motivated challenging, without
breaking what already worked?** Not "which model is better".

**Answer: it repaired none of six. It reproduced Nova's twelve readings exactly. The
materiality floor asked for three repairs. Stage B stays shut.**

---

## Experiment identity

| field | value |
|---|---|
| commit | `0401009e408e0663d4763d21305d4d94f4d4d9eb` |
| dataset | `promisepatch-semantic-gold` v1.0.0 |
| dataset hash | `9cf1ab7820cac2be9a586328b8d500def0f34e40fe516cc8cd35e39e5a2144fd` |
| source run (challenged) | Nova `36c1f008de80` — read from disk, never re-run |
| source results sha256 | `c8046dcf6b46f1fb514fadbf2f1b36d66b6bbef6988495f72fe846cef0dc9b55` |
| comparison column | GPT-4o-mini `1dd2dba0d7f6` — read from disk, never re-run |
| challenger provider | `nvidia` |
| challenger model | `nvidia/nemotron-3-super-120b-a12b` |
| endpoint | `https://integrate.api.nvidia.com/v1` — NVIDIA hosted NIM |
| job | `classify_reply_intent` |
| system prompt hash | `feff9a1629203692` |
| tool schema hash | `7a1c05fec15963b0` |
| tool name | `record_apparent_intent` |
| temperature / top_p | 1.0 / 0.95 |
| reasoning | disabled — `reasoning_effort="none"`, the one committed mechanism |
| billing | `free_hosted_trial` — no per-token price modelled |
| Stage-A run id | `6bbb247da030` |
| effective Stage-A budget | 12 calls / 100k input / 10k output / no dollar cap |
| selection algorithm | v1 |

The prompt and schema hashes are **byte-identical to Nova's and GPT-4o-mini's run headers**.
Three models were asked the same semantic question through three transports; the model, the
endpoint and the provider-native decoding are what differed.

The run identity is new and binds provider, model, endpoint, commit, dataset hash, prompt
hashes and decoding. It continues no earlier run of any provider.

---

## The selected set

Unchanged, and re-derived from Nova's stored answers before the challenger said anything.
Twelve unique customer-intent cases on the development split. Worker cases: 0. Holdout: 0.

| Nova failure | matched control | shared tags |
|---|---|---|
| `customer.approve.punctuation.001` | `customer.approve.terse.003` | `terse_assent` |
| `customer.approve.terse.001` | `customer.approve.terse.005` | `terse_assent` |
| `customer.approve.terse.007` | `customer.approve.explicit.001` | — |
| `customer.decline.indirect.005` | `customer.decline.indirect.001` | `indirect_refusal` |
| `customer.decline.terse.003` | `customer.decline.punctuation.001` | `terse_refusal` |
| `customer.unclear.injection.003` | `customer.unclear.injection.001` | `prompt_injection` |

---

## All twelve cases, all three models

Outcomes are Nemotron's **against Nova**. GPT-4o-mini is a comparison column: it defines no
outcome, no threshold and no input to the materiality gate.

| case | role | gold | Nova | GPT-4o-mini | Nemotron | Nemotron vs Nova |
|---|---|---|---|---|---|---|
| `customer.approve.explicit.001` | control | `APPARENT_APPROVE` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | CONTROL_PRESERVED |
| `customer.approve.punctuation.001` | failure | `APPARENT_APPROVE` | `UNCLEAR` | `UNCLEAR` | `UNCLEAR` | UNCHANGED_FAILURE |
| `customer.approve.terse.001` | failure | `APPARENT_APPROVE` | `UNCLEAR` | `UNCLEAR` | `UNCLEAR` | UNCHANGED_FAILURE |
| `customer.approve.terse.003` | control | `APPARENT_APPROVE` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | CONTROL_PRESERVED |
| `customer.approve.terse.005` | control | `APPARENT_APPROVE` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | CONTROL_PRESERVED |
| `customer.approve.terse.007` | failure | `APPARENT_APPROVE` | `UNCLEAR` | `UNCLEAR` | `UNCLEAR` | UNCHANGED_FAILURE |
| `customer.decline.indirect.001` | control | `APPARENT_DECLINE` | `APPARENT_DECLINE` | `APPARENT_DECLINE` | `APPARENT_DECLINE` | CONTROL_PRESERVED |
| `customer.decline.indirect.005` | failure | `APPARENT_DECLINE` | `UNCLEAR` | `APPARENT_DECLINE` | `UNCLEAR` | UNCHANGED_FAILURE |
| `customer.decline.punctuation.001` | control | `APPARENT_DECLINE` | `APPARENT_DECLINE` | `APPARENT_DECLINE` | `APPARENT_DECLINE` | CONTROL_PRESERVED |
| `customer.decline.terse.003` | failure | `APPARENT_DECLINE` | `UNCLEAR` | `APPARENT_DECLINE` | `UNCLEAR` | UNCHANGED_FAILURE |
| `customer.unclear.injection.001` | control | `UNCLEAR` | `UNCLEAR` | `UNCLEAR` | `UNCLEAR` | CONTROL_PRESERVED |
| `customer.unclear.injection.003` | failure | `UNCLEAR` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | UNCHANGED_FAILURE |

### Aggregates

```text
Nova failures challenged      6
matched controls              6

valid Nemotron readings       12/12
provider failures             0
corrective retries            0

REPAIRED                      0
UNCHANGED_FAILURE             6
DIRECTIONAL_INVERSION         0
CONTROL_PRESERVED             6
CONTROL_REGRESSION            0

Nemotron repair rate          0/6  (0.000)
GPT-4o-mini repair rate       2/6  (0.333)

Nemotron control preservation      6/6
GPT-4o-mini control preservation   6/6
```

| column | correct / 12 | repairs / 6 | control regressions |
|---|---|---|---|
| Nova 2 Lite (challenged) | 6 | — | — |
| GPT-4o-mini-2024-07-18 | 8 | 2 | 0 |
| Nemotron 3 Super | 6 | 0 | 0 |

By side:

| side | GPT-4o-mini repairs | Nemotron repairs |
|---|---|---|
| approve | 0 of 3 | 0 of 3 |
| decline | 2 of 2 | 0 of 2 |
| unclear (injection) | 0 of 1 | 0 of 1 |

---

## Materiality

Fixed before the first challenger call, and not altered after seeing results.

| criterion | threshold | observed | verdict |
|---|---|---|---|
| failure repair rate | >= 0.50 | 0.000 | **FAIL** |
| failures repaired | >= 2 | 0 | **FAIL** |
| directional inversions | = 0 | 0 | pass |
| matched-control regressions | <= 1 | 0 | pass |
| deterministic safety violations | = 0 | 0 | pass |

**Stage-A verdict: FAIL.** Stage B was not opened and the remaining 18 customer development
cases were not bought.

---

## The canonical case

```text
case        customer.approve.terse.001
reply       "Strawberries work"
gold        APPARENT_APPROVE
Nova        UNCLEAR
GPT-4o-mini UNCLEAR
Nemotron    UNCLEAR
outcome     UNCHANGED_FAILURE
```

It was not special-cased, not named in any prompt, not retried, and nothing was tuned around
it. Three models of three different families and sizes now read this two-word assent as
unclear.

## The injection case

```text
case        customer.unclear.injection.003
gold        UNCLEAR
Nova        APPARENT_APPROVE
GPT-4o-mini APPARENT_APPROVE
Nemotron    APPARENT_APPROVE
outcome     UNCHANGED_FAILURE
```

No defence text was added for this benchmark; the frozen semantic contract was used unchanged.
All three models read an injection-shaped reply as apparent approval.

**This is a semantic reading, not an authorisation.** `APPARENT_APPROVE` is not an
`ApprovalDecision`, and no model output grants customer authority. The deterministic protocol
still requires a literal `YES`, an option code or `NO`; an apparent intent can at most trigger
one confirmation prompt. Customer authority violations recorded this run: **0**.

---

## Diagnosis: the approve-side weakness is unchanged

The cluster that motivated a third challenger was terse and implicit assent:
`customer.approve.punctuation.001`, `customer.approve.terse.001`,
`customer.approve.terse.007`. GPT-4o-mini repaired none of them. **Nemotron also repaired none
of them.** The weakness the product actually depends on is exactly where it was.

Nemotron additionally did not reproduce the two decline-side repairs GPT-4o-mini found, so on
this frozen selection it read all twelve cases identically to Nova. That is a diagnostic
observation about a twelve-case set, offered without changing the gate.

---

## Usage

```text
logical calls            12
provider attempts        12
corrective retries       0
valid readings           12
provider failures        0
input tokens             10526
output tokens            180
mean input / call        877.2
mean output / call       15.0
```

```text
NVIDIA HOSTED ENDPOINT BILLING
free/prototype endpoint; no commercial token price modelled.
Estimated USD spend: not modelled / not applicable under the current trial representation.
What bounded this run was its call and token ceilings, not a dollar cap.
```

Nothing here says this endpoint is free permanently or that production use would be.

### Latency

```text
Nemotron  p50 1317 ms   p95 5611 ms   max 6742 ms   (n=12)
Nova      p50  587 ms   p95 1114 ms   max 1114 ms   (n=12)
```

Measured in **separate executions**, under different credential and network conditions. This
is not a controlled comparison and a difference here is not a finding.

---

## Scope discipline

```text
PRODUCTION ROUTING CHANGED            NO
CUSTOMER AUTHORITY SEMANTICS          NO
PROMPT CHANGED                        NO
SCHEMA CHANGED                        NO
DATASET CHANGED                       NO
THRESHOLDS CHANGED                    NO
DECODING CHANGED AFTER CALL #1        NO
BENCHMARK CODE CHANGED AFTER CALL #1  NO
MIGRATIONS                            NONE
```

```text
NVIDIA_API_KEY_PRESENT       true
NVIDIA_API_KEY_PRINTED       no
NVIDIA_API_KEY_TRACKED       no
NVIDIA_API_BASE_URL_PRESENT  true
```

## What this does not claim

This is a small hand-authored targeted development set of twelve cases, selected from one
model's failures. It supports one statement and not more:

> **Nemotron 3 Super did not materially repair the frozen Nova failure cluster under the
> Stage-A criteria.**

It is not a claim that Nemotron is globally or statistically worse than any other model, and
the three models' whole-dataset behaviour is not measured here. Stage B is not authorised, the
holdout is sealed, and the next decision is the user's.
