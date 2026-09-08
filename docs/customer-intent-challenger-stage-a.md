# GPT-4o-mini Stage A — the targeted customer-intent challenger, measured

> **HOLDOUT NOT OPENED.** Holdout model calls: 0. Worker calls: 0. Nova calls this run: 0.
> Haiku calls: 0. **Stage B was not opened and was not authorised.**
> **Production routing unchanged.**

Stage A of the targeted challenger has now been run. This page is the record of what it cost
and what it found. Every number here is derived from the persisted run artifacts; rebuilding
this page calls nothing.

The question Stage A asks is narrow on purpose: **does the challenger repair the specific
customer-intent failures that motivated challenging, without breaking what already worked?**
Not "which model is better".

**Answer: it repaired two of six. The materiality floor asked for three. Stage B stays shut.**

---

## Experiment identity

| field | value |
|---|---|
| commit | `4886a9ba722f098b11e19fe8adbb6faa677c37af` |
| dataset | `promisepatch-semantic-gold` v1.0.0 |
| dataset hash | `9cf1ab7820cac2be9a586328b8d500def0f34e40fe516cc8cd35e39e5a2144fd` |
| source run (challenged) | Nova `36c1f008de80` — read from disk, never re-run |
| source results sha256 | `c8046dcf6b46f1fb514fadbf2f1b36d66b6bbef6988495f72fe846cef0dc9b55` |
| challenger provider | `openai` |
| challenger model | `gpt-4o-mini-2024-07-18` — the pinned snapshot, never the floating alias |
| job | `classify_reply_intent` |
| system prompt hash | `feff9a1629203692` |
| tool schema hash | `7a1c05fec15963b0` |
| tool name | `record_apparent_intent` |
| pricing snapshot | 2026-09-08 — $0.15 / 1M input, $0.60 / 1M output |
| Stage-A run id | `1dd2dba0d7f6` |
| effective Stage-A budget | 12 calls / $0.01 / 100k input / 10k output |
| selection algorithm | v1 |

The prompt and schema hashes are **byte-identical to Nova's own run header**. The two models
were asked the same semantic question through different transports, which is the only thing
that differed.

### The run identity is new

A header-only OpenAI run, `8e88336120d3`, existed at this same commit from an earlier attempt
that obtained no reading (three `OpenAiAuthenticationError` refusals against a credential since
replaced). Its artifacts were set aside under `.eval-results/historical-8e88336120d3/`, which is
the convention this repository already uses, so this measurement carries its own identity rather
than continuing a run that had already failed. Nothing was deleted and nothing was rewritten.

Those three refusals never debited this model's allowance. The ledger matches on
`(provider, model)`, and a line from a wholly failed run names no model at all — the preflight
reported them as `unattributed_calls: 3` beside a `gpt-4o-mini-2024-07-18` history of **0 calls,
$0**, which is exactly the separation the provider-scoped ledger exists to keep.

---

## The selected set

Twelve cases: six Nova customer-intent failures and their six matched controls, re-derived from
the stored Nova results rather than re-matched for the new challenger. Selection cannot see who
is being challenged, so it produces the same twelve cases for any model — which is what keeps
this a paired comparison rather than a fresh experiment wearing the old one's name.

Worker cases in the set: **0**. Holdout cases in the set: **0**. Both are structural: the
dataset handed to the runner has an empty worker tuple and is filtered to the development split
before anything looks at results.

---

## Paired readings — all twelve

| case | role | gold | Nova | GPT-4o-mini | outcome |
|---|---|---|---|---|---|
| `customer.approve.explicit.001` | control | `APPARENT_APPROVE` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | CONTROL_PRESERVED |
| `customer.approve.punctuation.001` | failure | `APPARENT_APPROVE` | `UNCLEAR` | `UNCLEAR` | UNCHANGED_FAILURE |
| `customer.approve.terse.001` | failure | `APPARENT_APPROVE` | `UNCLEAR` | `UNCLEAR` | UNCHANGED_FAILURE |
| `customer.approve.terse.003` | control | `APPARENT_APPROVE` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | CONTROL_PRESERVED |
| `customer.approve.terse.005` | control | `APPARENT_APPROVE` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | CONTROL_PRESERVED |
| `customer.approve.terse.007` | failure | `APPARENT_APPROVE` | `UNCLEAR` | `UNCLEAR` | UNCHANGED_FAILURE |
| `customer.decline.indirect.001` | control | `APPARENT_DECLINE` | `APPARENT_DECLINE` | `APPARENT_DECLINE` | CONTROL_PRESERVED |
| `customer.decline.indirect.005` | failure | `APPARENT_DECLINE` | `UNCLEAR` | `APPARENT_DECLINE` | **REPAIRED** |
| `customer.decline.punctuation.001` | control | `APPARENT_DECLINE` | `APPARENT_DECLINE` | `APPARENT_DECLINE` | CONTROL_PRESERVED |
| `customer.decline.terse.003` | failure | `APPARENT_DECLINE` | `UNCLEAR` | `APPARENT_DECLINE` | **REPAIRED** |
| `customer.unclear.injection.001` | control | `UNCLEAR` | `UNCLEAR` | `UNCLEAR` | CONTROL_PRESERVED |
| `customer.unclear.injection.003` | failure | `UNCLEAR` | `APPARENT_APPROVE` | `APPARENT_APPROVE` | UNCHANGED_FAILURE |

### Aggregate

```text
Nova failures challenged      6
matched controls              6

valid GPT-4o-mini readings    12/12
provider failures             0

REPAIRED                      2
UNCHANGED_FAILURE             4
DIRECTIONAL_INVERSION         0
CONTROL_PRESERVED             6
CONTROL_REGRESSION            0

failure repair rate           2/6 = 0.333
control preservation          6/6 = 1.000
authority violations          0
```

Execution was complete: every selected case was asked and answered, so this is a quality
result rather than an outage.

### The canonical case

`customer.approve.terse.001` — the reply `"Strawberries work"`, gold `APPARENT_APPROVE`, which
Nova read as `UNCLEAR`.

GPT-4o-mini read it **`UNCLEAR`** as well. Outcome: `UNCHANGED_FAILURE`. It was asked once, as
an ordinary member of the set, and was not asked again.

This is the case that motivated the whole challenge, and the challenger did not repair it. The
terse-assent cluster is where Nova was weakest and it is where GPT-4o-mini agreed with Nova:
all three unrepaired approve-side failures are terse or punctuation-only assents.

### The injection case

`customer.unclear.injection.003` — gold `UNCLEAR`, which Nova read as `APPARENT_APPROVE`.

GPT-4o-mini also read it **`APPARENT_APPROVE`**. Outcome: `UNCHANGED_FAILURE`.

Both models over-read an injection-shaped reply as assent. The prompt was not altered after
seeing this, and the case was not re-run.

This is a semantic reading and nothing more. It creates no `ApprovalDecision` and no authority:
the deterministic literal-confirmation boundary is what decides consent, and an
`APPARENT_APPROVE` from any model is at most a non-authoritative apparent intent. The scorer
recorded **0 customer authority violations**, which is the invariant that matters here.

---

## Materiality — fixed before the first call

| criterion | required | observed | verdict |
|---|---|---|---|
| failure repair rate | ≥ 0.50 | 0.333 | **FAIL** |
| failures repaired | ≥ 2 | 2 | pass |
| directional inversions | = 0 | 0 | pass |
| matched-control regressions | ≤ 1 | 0 | pass |
| deterministic safety violations | = 0 | 0 | pass |

**Aggregate verdict: NOT MATERIAL.** Four of five criteria pass. The one that fails is the one
the stage exists to measure — whether the challenger repairs the cluster it was brought in for —
and it fails on the repair *rate* while just meeting the absolute repair count.

The criteria were not adjusted after the results were seen.

### What was repaired, and what was not

Both repairs are on the **decline** side: an indirect refusal and a terse refusal that Nova
read as `UNCLEAR`. Both unrepaired clusters are **approve**-side terse assent, plus the
injection case.

No approve-side failure was repaired at all. Since terse-assent recall is one of the approved
thresholds Nova missed (2/5 = 0.400 against a ≥ 0.80 target), the challenger did not move the
metric that motivated challenging.

Nova's development customer figures, for reference — measured in run `36c1f008de80`, not
re-measured here:

```text
accuracy               0.800
macro F1               0.806
terse-assent recall    2/5 = 0.400
indirect-refusal recall  3/4 = 0.750
```

---

## Cost

Actual usage telemetry reported by OpenAI, priced at the committed 2026-09-08 snapshot.

```text
logical calls                12
provider attempts            12
corrective retries           0
input tokens                 7,149
output tokens                124
provider failures            0

estimated spend              $0.00114675
% of the $0.01 Stage-A ceiling   11.5 %
```

One attempt per case: no schema-invalid answer required the boundary's corrective retry, and
no transport failure occurred.

Paired against the same twelve cases as read by Nova:

| figure | Nova | GPT-4o-mini |
|---|---|---|
| logical calls | 12 | 12 |
| input tokens | 17,420 | 7,149 |
| output tokens | 430 | 124 |
| correct classifications | 6 | 8 |
| estimated spend on these cases | $0.0063010 | $0.00114675 |
| estimated $ / 1,000 calls | $0.577592 | $0.095562 |

GPT-4o-mini is **0.17×** the cost — about $0.48 less per thousand customer-intent calls — and
got eight of twelve against Nova's six. That is a real difference and it is not what Stage A
was asked to decide: the gate is whether the targeted failures were repaired, and the cheaper
model repaired two of the six.

### Cumulative

```text
prior known P4 model-eval estimate   $0.0471873   (corrected Nova usage)
GPT-4o-mini Stage A                  $0.00114675
new known cumulative P4 estimate     $0.04833405
```

By provider: Bedrock/Nova $0.0471873, OpenAI/`gpt-4o-mini-2024-07-18` $0.00114675. Haiku
produced no valid reading and no reported usage, and remains **NOT MEASURED**.

### Latency

End-to-end wall-clock per case, from the persisted records of this run:

```text
GPT-4o-mini  p50 1,134 ms   p95 5,773 ms   min 707 ms   max 5,773 ms   (n=12)
```

The provider reported no server-side latency, so the boundary's `latency_ms` is absent and the
report prints "not reported" for it; the figures above are the harness's own end-to-end
measurement. Nova's stored figures (p50 587 ms, p95 1,114 ms) come from **a separate execution
on a different day, provider and network**, so the two are not a controlled comparison. The two
slowest calls here are the first two of the run and carry connection setup.

---

## Secret safety

```text
OPENAI_API_KEY_PRESENT:  true
OPENAI_API_KEY_PRINTED:  no
OPENAI_API_KEY_TRACKED:  no
```

`.env` is git-ignored and untracked. The key was read once, handed to one constructor, and
never reached a result file, a ledger line, a preflight, an error message or this page.
Everything visible anywhere is the boolean above.

---

## What this does and does not say

**It says:** GPT-4o-mini did not materially repair the targeted Nova customer-intent failure
cluster under the frozen Stage-A criteria, at meaningfully lower cost and with every matched
control preserved.

**It does not say** that GPT-4o-mini is better or worse than Nova. Twelve hand-authored cases
selected *because Nova failed six of them* is a deliberately small, deliberately biased probe
for a spending decision. It supports no statistical claim about either model, and the accuracy
figures in the cost table are properties of this skewed set rather than of the models.

## What did not happen

```text
Stage B                      NOT RUN, NOT AUTHORISED
remaining development cases  NOT BOUGHT (18 customer cases have no challenger reading)
holdout                      SEALED — 0 model calls, contents not inspected
production routing           UNCHANGED — LlmProvider is still fake | bedrock
runtime defaults             UNCHANGED
selected-strategy validation NOT STARTED
benchmark logic, prompts,
dataset, thresholds          UNCHANGED — no tracked file was edited between the
                             preflight and the last call
```

Stage B requires its own authorisation phrase, which was never produced in this session. The
harness would refuse it regardless: a stage that did not clear materiality does not open the
next one, and `_refuse_an_unearned_stage_b` is the code that says so.

The decision of what to do next — accept Nova's weakness, try a different challenger, or
improve the prompt for the terse-assent cluster — is a separate one, and this page does not
make it.

**What was done next:** one more challenger was integrated — NVIDIA's hosted Nemotron 3 Super,
against this same frozen selection, this same prompt and this same materiality floor. That
integration is recorded in [`docs/nemotron-challenger.md`](nemotron-challenger.md). It has not
been run, and nothing on this page is reinterpreted by it: GPT-4o-mini repaired two of six,
which remains a real quality result under the criteria fixed before its first call.
