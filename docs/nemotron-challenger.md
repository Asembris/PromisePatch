# The NVIDIA Nemotron challenger — integrated, not yet run

> **NVIDIA model calls: 0. OpenAI calls: 0. Nova calls: 0. Haiku calls: 0. Model spend: $0.**
> **Holdout model calls: 0. Worker calls: 0.**
> **Stage A has NOT been executed. Production routing unchanged.**

This page records what was built so that one more model can be asked the *same* question the
previous two were asked, and what was deliberately not built. Nothing here is evidence about
Nemotron: no request has been sent to NVIDIA, and every number below is either a configuration
somebody chose or a fact about an earlier model's run.

---

## Why a third challenger

The unresolved weakness is concentrated in terse assent, indirect assent and refusal, and
prompt-injection-shaped customer replies. Two models have now been measured against it on the
same twelve cases.

| model | correct / 12 | Nova failures repaired / 6 | control regressions | inversions | materiality |
|---|---|---|---|---|---|
| Nova 2 Lite (challenged) | 6 | — | — | — | — |
| Haiku 4.5 | 0 valid readings | — | — | — | **NOT MEASURED** — blocked by `INVALID_PAYMENT_INSTRUMENT` |
| GPT-4o-mini-2024-07-18 | 8 | 2 (0.333) | 0 | 0 | **FAIL** — floor is 0.50 |

GPT-4o-mini repaired both decline-side failures and none of the approve-side ones, which is a
real quality result under the frozen Stage-A criteria and is not reinterpreted here. The repair
rate fell below the floor, so Stage B was never opened. That leaves the approve-side cluster —
the one the product actually depends on — unaddressed, which is what justifies one stronger open
model. **This is the final additional Stage-A challenge** unless frozen evidence later gives a
very strong reason otherwise.

---

## What is frozen, and what changed

Everything that decides the number is unchanged:

| | |
|---|---|
| dataset | `promisepatch-semantic-gold` v1.0.0, hash `9cf1ab7820cac2be9a586328b8d500def0f34e40fe516cc8cd35e39e5a2144fd` |
| source run (challenged) | Nova `36c1f008de80`, read from disk and never re-run |
| selection | the same six failures and six matched controls, derived from Nova's stored answers |
| semantic contract | `classify_reply_intent`, system prompt `feff9a1629203692`, tool schema `7a1c05fec15963b0`, tool `record_apparent_intent` |
| scorer | unchanged |
| materiality gate | repair rate ≥ 0.50, ≥ 2 repairs, 0 inversions, ≤ 1 control regression, 0 safety violations |
| labels | `APPARENT_APPROVE` / `APPARENT_DECLINE` / `UNCLEAR` |

Exactly one thing changed: **which model answers, and where it is reached.**

```text
PRODUCTION ROUTING CHANGED:        NO
CUSTOMER AUTHORITY SEMANTICS:      NO
WORKER ROUTING CHANGED:            NO
PROMPT CHANGED:                    NO
SCHEMA CHANGED:                    NO
DATASET CHANGED:                   NO
THRESHOLDS CHANGED:                NO
MIGRATIONS:                        NONE
```

### The selected set, unchanged

Failures (Nova's, not GPT-4o-mini's):

```text
customer.approve.punctuation.001    customer.decline.indirect.005
customer.approve.terse.001          customer.decline.terse.003
customer.approve.terse.007          customer.unclear.injection.003
```

Matched controls:

```text
customer.approve.terse.003          customer.decline.indirect.001
customer.approve.terse.005          customer.decline.punctuation.001
customer.approve.explicit.001       customer.unclear.injection.001
```

Twelve unique cases, all customer-intent, all development split. Worker cases: 0. Holdout: 0.
The pairing stays Nova's so the two challengers remain comparable *with each other*; GPT-4o-mini
becomes a comparison column, never a second baseline and never a redefinition of "repaired".

The canonical case is untouched: `customer.approve.terse.001`, reply *"Strawberries work"*, gold
`APPARENT_APPROVE`, read as `UNCLEAR` by both Nova and GPT-4o-mini. It is not special-cased, not
named in any prompt, and nothing is tuned around it.

---

## The target

| field | value |
|---|---|
| provider | `nvidia` |
| model | `nvidia/nemotron-3-super-120b-a12b` |
| endpoint | `https://integrate.api.nvidia.com/v1` — NVIDIA hosted NIM |
| protocol | OpenAI-compatible Chat Completions, forced function calling |
| temperature | 1.0 |
| top_p | 0.95 |
| reasoning | disabled — `reasoning_effort: "none"` |
| output ceiling | 64 tokens (the job spec's `max_tokens`, not the model's 16k default) |
| streaming | off |

### One reasoning mechanism, chosen deliberately

There are two ways to switch this family's hidden reasoning off through a compatible endpoint:
`reasoning_effort` and `chat_template_kwargs.enable_thinking`. **Only `reasoning_effort="none"`
is sent**, because it is a first-class typed parameter of the installed client (`ReasoningEffort`
includes `"none"`) and needs no `extra_body` escape hatch. Sending both would be two instructions
about one thing, and which of them the endpoint honoured would be a fact about that endpoint on
that day rather than about this experiment. A test asserts the request carries `reasoning_effort`
and carries no `chat_template_kwargs`, `extra_body`, `reasoning` or `thinking` key.

This is provider-native **decoding**, not a semantic change. It is recorded as part of the
experiment identity, because the same model with reasoning on and off is two experiments.

---

## How it was built: one transport, three configurations

`promisepatch/integrations/openai.py` was already a Chat Completions adapter that held no
prompt, no schema and no vocabulary of its own. Everything in it except two things — the host a
client opens against, and the vendor named in a failure message — is a property of the *protocol*
rather than of OpenAI. So it was generalised by two values rather than copied:

```text
                    StructuredSemanticProvider
                              │
                  OpenAI-compatible transport
                (request, tool schema, extraction,
                 usage, failure classification)
                         ┌────┴────┐
                         │         │
                      OpenAI    NVIDIA NIM
                 Decoding(0.0)  Decoding(1.0, 0.95, none)
                 OPENAI_ERRORS  NVIDIA_ERRORS
                 base_url None  hosted NIM URL
```

* `Decoding` — the sampling configuration. A field left `None` is a key the request does not
  carry at all, so an OpenAI call is byte-identical to what it was before this gate.
* `TransportErrors` — the five exception types a fault becomes, plus the label used in its
  message. A stored result keeps only the exception's class name, so reusing OpenAI's types
  would file an NVIDIA outage under `OpenAiUnavailableError` and the evaluator's taxonomy would
  read one provider's history under another's vocabulary. NVIDIA gets its own five subclasses
  and hands them to the *same* classification function.

`promisepatch/integrations/nvidia.py` is the rest: a provider name, a pinned model, the decoding
above, the five error types, and the endpoint refusal. `NvidiaSemanticProvider` subclasses the
compatible provider and overrides nothing that shapes a question.

**No second semantic implementation exists.** `test_nvidia_semantic.py` pulls both requests apart
and asserts the system instruction, user content, tool name, tool description, JSON Schema,
forced tool choice and `max_completion_tokens` are equal, for both jobs — while asserting the
envelopes are *not* byte-identical and are not pretended to be.

### Structured output is preserved

NVIDIA NIM supports OpenAI-compatible `tools` and named `tool_choice`, so the forced-function
contract is used unchanged: one function, which is the job's output schema, forced by name.
Nothing appends "respond with JSON" and nothing restates the schema in prose — a test asserts
those strings are absent from the request. A response with no call to that one function is a
failure, not something to run a regular expression over.

The "tool" is an output shape. No NVIDIA tool call is ever executed against anything.

---

## Trust model: unchanged, and none

```text
Nemotron authority = NONE
```

It can produce one of `APPARENT_APPROVE` / `APPARENT_DECLINE` / `UNCLEAR` and nothing else. It
cannot create an `ApprovalDecision`, customer authority, a workflow authorisation, a physical
fact or any external effect. The model understands; the deterministic protocol authorizes.

Reasoning is off, so no hidden trace is requested. If the endpoint volunteers one anyway it
decides nothing and is not persisted: the reading is the structured function arguments.

---

## Billing: represented honestly

NVIDIA offers this model on a **free hosted endpoint** for prototype and API use, and publishes
no per-token price for it.

```text
NVIDIA HOSTED ENDPOINT STATUS:  free prototype endpoint according to NVIDIA Build
TOKEN PRICE:                    not modelled as a commercial per-token price
USD SPEND BUDGET:               not applicable to this hosted trial integration
RESOURCE GUARDS:                call and token ceilings, enforced
```

The budget architecture wanted a `ModelPrice` and a dollar ceiling. Writing `$0.00` would have
been two lies at once — asserting a published commercial rate that does not exist, and making
every dollar ceiling for this model trivially satisfiable — so a small refactor separated *how* a
model is charged for from *how much*:

* `BillingMode` — `METERED` or `FREE_HOSTED_TRIAL`.
* `Billing` — the terms, with the price present for a metered model and absent for a free one.
  The invariant is checked at construction: a metered entry with no price and a free entry with
  one are both refused.
* `BILLING` is derived from `PRICES` plus the free entries, so a price recorded once is the price
  in both catalogs and the two cannot disagree.

Unknown terms are still a refusal, not a default: a model absent from `BILLING` stops the run
before anything is constructed. **Nothing here says this endpoint is permanently free, or that
production use would be.**

Every existing paid guard is untouched — Nova, Haiku and GPT-4o-mini keep their prices, their
dollar ceilings and their provider-and-model-scoped ledger accounting, and a test proves NVIDIA
usage does not debit GPT-4o-mini's allowance or the reverse.

### Ceilings

| | NVIDIA global | NVIDIA Stage A |
|---|---|---|
| logical calls | 30 | 12 |
| input tokens | 100,000 | inherited |
| output tokens | 10,000 | inherited |
| dollar cap | none — no per-token billing | none |

Twelve is the selection's own size. Both ceilings remain in force and whichever is strictest
refuses first. The model's documented 16k completion ceiling and 16k reasoning budget reach
nothing: output is bounded per call by the job spec's 64 tokens, and reasoning is off.

---

## Endpoint identity, and why it fails closed

An OpenAI-compatible protocol is spoken by hosted services, self-hosted NIM containers, Ollama
and proxies alike. All of them could answer to `nvidia/nemotron-3-super-120b-a12b`, and a result
file recorded against any of them would look entirely normal afterwards. So:

* `NVIDIA_API_BASE_URL` **unset** → the documented hosted endpoint. Not an error: the default is
  the only endpoint the run would be permitted to use anyway.
* `NVIDIA_API_BASE_URL` **set to anything else** → refused, before a client exists. No fallback,
  no correction. Whitespace and a trailing slash are forgiven because they are typing; everything
  else is a different endpoint.

The check lives in the adapter and is called twice — once by the composition root before
authorisation-ordered construction, once by the adapter as the last line before a client — from
**one** constant, so the two cannot drift.

The endpoint is also in the run header's identity fields, alongside provider, model, commit,
dataset hash and prompt hashes. A NVIDIA Stage A therefore cannot resume a GPT-4o-mini, Haiku or
Nova result, nor a NVIDIA result taken against another endpoint. Runs that predate the field
record `None`, which matches `None`, so they stay continuable exactly as they were.

---

## Spending and quota safety

"Free" is not "harmless": the resource a stray call spends is somebody's prototype quota, and a
benchmark run from inside a test would be a measurement nobody asked for recorded under an
experiment's name. So every existing interlock extends to NVIDIA unchanged.

**`--live` is not permission.** Buying inference additionally takes a scope-bound phrase typed at
the invocation — `AUTHORISE-PAID-INFERENCE-STAGE-A` — never read from the environment, never from
`.env`, never defaulted, and never carried from one stage to the next. A Stage-A authorisation
cannot open Stage B, for any provider.

**A pytest process cannot construct a provider at all**, whatever flags, phrases or credentials
it inherits. Tests pass a provider builder in; the real one is unreachable from them.

Ordering, enforced by construction:

```text
parse provider/model/stage → authorisation → dataset identity → selection eligibility
→ worker/holdout exclusion → billing terms → budget ceiling → NVIDIA_API_KEY present
→ NVIDIA_API_BASE_URL validated → provider construction → network request
```

CI proves this rather than asserting it: a job sets a syntactically valid `NVIDIA_API_KEY` and
the real base URL, runs the suite, and the suite's socket guard raises on any connection leaving
the machine and asserts the count of them is zero. **No `NVIDIA_API_KEY` was added to GitHub
Secrets and none is needed** — a plausible credential is not what decides whether inference can
be bought.

### Secrets

Neither `NVIDIA_API_KEY` nor `OPENAI_API_KEY` is ever printed, logged, persisted or returned to
anything that formats. Everything a preflight, a plan, a report, a result file, a ledger line or
an error message sees is a boolean. A test runs the plan and the refusal paths with a
real-shaped key present and asserts the literal value appears in no stdout, stderr or written
artifact. `.env` is gitignored and untracked; `.env.example` documents both variables with an
empty key placeholder and the non-secret base URL.

---

## Failure taxonomy

The five NVIDIA transport types normalise to the existing categories, and none of them can
become a reading:

```text
NvidiaAuthenticationError  → AUTHENTICATION
NvidiaPermissionError      → PERMISSION
NvidiaRateLimitError       → RATE_LIMITED
NvidiaInvalidRequestError  → INVALID_REQUEST
NvidiaUnavailableError     → PROVIDER_UNAVAILABLE
NvidiaEndpointError        → INVALID_REQUEST
SemanticTimeoutError       → TIMEOUT
anything else              → UNKNOWN_PROVIDER_FAILURE
```

A transport failure is never `UNCLEAR`, never an `UNCHANGED_FAILURE` and never a
`CONTROL_REGRESSION`. Failed attempts go to their own log rather than the readings file, so a
resumed run does not read an outage back as an answer. Three provider failures stop the stage,
and a stopped stage reports **NOT MEASURED** rather than a materiality verdict. No provider
message, header or credential is persisted — the exception's class name is as far as it goes.

---

## The comparison report

The paired taxonomy is unchanged: `REPAIRED`, `UNCHANGED_FAILURE`, `DIRECTIONAL_INVERSION`,
`CONTROL_PRESERVED`, `CONTROL_REGRESSION`, `PROVIDER_FAILURE`, all computed against Nova.

`--compare-with PATH` adds an earlier challenger's stored run as a **column**: the same twelve
cases, each model's reading, and aggregates for correct / repairs / control regressions plus an
approve-side and decline-side split. It reads files and calls nothing, and it defines nothing — a
prior column contributes no outcome, no threshold and no input to the materiality gate. The
column is refused unless it was measured against the dataset on disk.

Tested offline with **invented** Nemotron readings, which exist only inside the test and are
never written to `.eval-results`. They exercise the report's arithmetic and are not evidence
about any model.

---

## How to run it, when it is run

```bash
uv run python -m scripts.run_intent_challenger --stage a --provider nvidia --model nvidia/nemotron-3-super-120b-a12b
```

That prints the preflight, the stage budget, the challenger set and the zero-call plan, and
stops. It constructs no client and calls nothing. Buying Stage A additionally takes `--live` and
`--authorise-paid-inference AUTHORISE-PAID-INFERENCE-STAGE-A`.

---

## What was not built

* NVIDIA is **not** in `LlmProvider` and no deployment can be routed to it.
* Nemotron is **not** an LLM judge, an explanation evaluator or a red-team model. Those are
  later decisions and none of that work is here.
* No Ollama, no generic provider marketplace, no model catalog sweep.
* Stage B is not authorised and is not opened. Stage A has not been executed.
