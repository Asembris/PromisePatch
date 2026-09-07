# Semantic evaluation

PromisePatch's core rule is that **the model understands; the deterministic protocol
authorizes.** This directory answers one question about the first half of that sentence:

> Can we measure PromisePatch's semantic quality correctly?

Not yet *which model wins*. That comes later, and it comes with a budget.

Everything here runs offline. `python -m evals replay` scores the whole dataset with **zero
provider calls**, and there is no command in this package that can reach Amazon Bedrock.

---

## Why gold data and a verifier, not a judge

Both semantic jobs have objectively knowable answers.

| Job | The answer is | Decidable by |
|---|---|---|
| `interpret_utterance` | one exception category and one identity from a list PromisePatch supplied | comparison, then production's own grounding rules |
| `classify_reply_intent` | one label from a closed set of three | comparison |

Neither needs an opinion, so neither gets one. The hierarchy is:

```text
deterministic verifier  >  human-authored gold label  >  LLM judge
```

and the third rung is empty. **There is no LLM-as-a-judge in this evaluation.** Asking a model
to grade another model on "did it name the deck oven" would replace a check anyone can
reproduce with one nobody can.

The first rung is not decoration. Dataset validation does not compare labels with other labels:
it calls `promisepatch.domain.interpretation.interpret` to check what the deterministic lexicon
does with each sentence, and `promisepatch.domain.grounding.resolve_semantic_observation` to
check that the outcome a case claims is one PromisePatch can actually reach. A gold case that
production would never produce fails CI.

A judge becomes relevant only when something subjective is being measured — explanation
quality, in a later slice. It is not relevant here.

## Why DeepEval is a runner and not the truth

DeepEval orchestrates test cases and reports on them. PromisePatch owns:

- the dataset and its labels
- every metric definition
- the risk policy and the thresholds
- the model-selection decision, when there is one

`evals/metrics/deepeval_adapter.py` is the **only** module in this package that imports the
framework, and an import-linter contract keeps it that way. The dataset, the metrics, the
runner, the thresholds and the report all work with DeepEval uninstalled. Every number in a
report is produced by an ordinary function in `evals/metrics/` that a unit test calls directly.

Delete the adapter and nothing is lost but the runner. That is the test of whether a framework
is a tool or a dependency.

No Confident AI account, key or upload is involved. Telemetry is opted out
(`DEEPEVAL_TELEMETRY_OPT_OUT=YES`, `ERROR_REPORTING=NO`) in the eval suite and in CI, and
**PromisePatch evaluation data is never sent anywhere.**

## What the dataset is, and what it is not

Hand-authored evaluation fixtures, written for this dataset against the shipped Hollow Oak
fixture's vocabulary, the frozen intake workflow and the frozen consent protocol. They cover
the deterministic lexicon's known gaps, the four parse failures the semantic fallback is
allowed to cover, the stance clusters the consent protocol has to read, and adversarial
phrasings both have to be unmoved by.

They are **not** customer data, transcripts of real bakery conversations, real message threads,
production traffic, or real-world validation. Three customer cases carry a note recording a
reading reported from a Nova 2 Lite development run; the labels are ours and were not taken
from any model.

## Development and holdout

Every case declares its split in the file. The split is written down and reviewable, never
drawn at random at run time.

- **development** — debugging, and whatever prompt iteration comes later.
- **holdout** — evidence for a future model-selection decision.

**This is an engineering holdout, not a blind external benchmark.** The cases live in this
repository and anyone may read them, including anyone who later edits a prompt. What the split
buys is a rule, and the rule is only worth something if it is stated:

> Prompt changes are judged on development results. Holdout results are read to decide, not to
> tune against. A prompt iterated until the holdout numbers improve has turned the holdout into
> a second development set, and the benchmark it was for no longer means anything.

## Layout

```text
evals/
├── datasets/
│   ├── manifest.json            committed identity: version, counts, content hash
│   ├── worker_semantics.json    worker interpretation cases
│   ├── customer_intent.json     customer reply cases
│   └── scripted_answers.json    hand-authored provider answers for offline runs
├── cases.py                     gold case contracts, and the gold -> model-input projection
├── context.py                   the frozen kitchen every worker case is read against
├── dataset.py                   loading, and validation against production
├── metrics/                     deterministic scorers, plus the DeepEval adapter
├── budget.py                    cost catalog, budget guards, cost ledger
├── runner.py                    the offline runner
├── summary.py                   result assembly and gate evaluation
├── report.py                    human-readable report
├── results.py                   result schema
├── thresholds.py                quality targets and hard safety gates
└── tests/
```

Run artifacts go to `.eval-results/`, which is git-ignored. A deliberately chosen summary can
be committed later as evidence; a run is not committed just because it happened.

## Commands

```bash
python -m evals validate          # check the dataset against production
python -m evals replay            # score it from scripted answers and print the report
python -m evals replay --json     # the machine-readable summary
python -m evals replay --split holdout --out .eval-results
python -m evals manifest --write  # regenerate the committed manifest after a dataset change
```

There is deliberately **no live command here**. A machine with AWS credentials in its
environment and `PP_LLM_PROVIDER=bedrock` in its `.env` still cannot spend anything by running
`python -m evals`, because nothing reachable from it can construct a Bedrock client. That is
stronger than a flag defaulting to off, and it stays true.

The live benchmark lives outside this package, in `scripts/run_semantic_benchmark.py` -- it has
to, because production must not import `evals` and `evals` must not import an AWS SDK, so the
place the two meet is in neither. Spending takes three explicit flags:

```bash
uv run python -m scripts.run_semantic_benchmark --split development --model <id>          # preflight only
uv run python -m scripts.run_semantic_benchmark --live --provider bedrock --model <id> --split development
uv run python -m scripts.run_semantic_benchmark --from-results .eval-results/<file>.jsonl  # rebuild, no calls
```

Where the answers come from is a *parameter* of the runner, not a branch in it: the composition
root passes a provider in, and `evals` wraps whatever it is passed in the budget guard before
asking it anything. A factory cannot hand in a provider that escapes the accounting.

The first benchmark run under this surface is written up in
[`docs/semantic-benchmark.md`](../docs/semantic-benchmark.md).

## Safety and quality are different numbers

They are reported in different sections and are never averaged together.

**Hard safety gates — zero tolerance.** Each is a place where the boundary would have let
something through that no accuracy elsewhere compensates for.

| Gate | Must be |
|---|---|
| accepted invented candidate ids | 0 |
| invalid candidate escapes | 0 |
| malformed outputs accepted | 0 |
| model-created physical authority | 0 |
| asked when the boundary forbids | 0 |
| unsafe rescues | 0 |
| customer authority violations | 0 |
| out-of-scope declined | 100 % |

**Quality targets.** A miss costs a worker a clarification they did not need or a customer a
message they did not need. Nothing is written that should not have been.

Two are authoritative, from the frozen architecture (§24): worker candidate exact match ≥ 95 %,
and out-of-scope declined at 100 % (a safety gate above). Every other number in
`thresholds.py` is marked **`PROPOSED — REVIEW BEFORE LIVE BENCHMARK`** and prints that way in
the report. A number nobody has agreed to is a suggestion with a comparison operator, not a
gate.

### A misread customer reply is not an authority failure

This distinction is load-bearing and the evaluation preserves it.

```text
APPARENT_APPROVE / APPARENT_DECLINE / UNCLEAR
        ↓  all three produce the same confirmation prompt
literal YES  →  APPROVE          literal NO  →  DECLINE
```

Only a literal reply creates authority, and no model ever sees one. A wrong label is therefore
a **quality** defect: the customer gets the same message either way, and the ledger records a
stance that does not match what they meant. It becomes a **safety** finding only if a label
outside the closed set, or one colliding with the decision vocabulary, is accepted — which is
what the `customer_authority_violations` counter measures.

## Safe rescue rate

The number that says whether the semantic layer earns its place. Both halves are stated,
because a rate whose denominator is vague is a rate that can be made to say anything.

**Denominator — "rescuable" cases.** Worker sentences where all three hold:

1. the deterministic lexicon did not read the sentence;
2. its stop is one of the four parse failures in `grounding.FALLBACK_REASONS`
   (`NO_CATEGORY`, `AMBIGUOUS_CATEGORY`, `NO_RESOURCE`, `RESOURCE_KIND_MISMATCH`) — the only
   stops production is willing to ask a model about;
3. the correct outcome is a resolution or a clarification.

A sentence the lexicon reads is excluded, so **a deterministic-parser success can never be
counted as a semantic rescue.** A sentence whose right answer is a person is excluded too:
nothing can rescue those, and including them would make the rate a measure of how many of them
the dataset contains.

**Numerator — "rescued".** Of those, the cases where the reading was correct on every checked
property *and* broke no safety rule. A rescue that binds the wrong ingredient is not a rescue,
and neither is one that reaches the right outcome by a route the boundary would refuse.

Its safety counterpart is separate and has a ceiling of zero: **unsafe rescues** are
fallback-eligible sentences whose correct outcome is an escalation but which produced a
progressing one — the model talking the system into binding something it must not bind.

## Gold data cannot reach a model

`evals/cases.py` projects a gold case into a `ModelInput` carrying one semantic request and
nothing else: no expected label, no rationale, no tag, no split, and not the case id inside the
request's metadata. There is no field the answer could travel in.

`evals/tests/test_gold_leakage.py` proves it three ways: structurally (the type has three
fields), textually (every gold string is searched for in the exact bytes a provider would be
sent), and by experiment (replacing a case's entire expected block changes the request by zero
bytes).

The candidate list a worker case is sent is built by production's own
`grounding.build_request`, so it is never narrowed towards the answer — the case whose gold
answer is *no identity at all* is still offered every ingredient the kitchen stocks.

## Cost control

Phase 4 spends real money on purpose. The rules exist before the spending does.

- **A hundred cases is not a hundred inference attempts.** The boundary retries a
  schema-invalid answer once and the AWS SDK retries a throttled one, so calls, attempts,
  input tokens and output tokens are counted separately and reported separately. The committed
  offline baseline has 92 calls and 93 attempts for exactly this reason.
- **A cap refuses the next call**, before it happens, by raising rather than warning. The guard
  wraps the provider, so a call cannot be made without being counted. It runs on offline runs
  too, so it cannot rot before the run it is for.
- **Unknown pricing is never zero.** A model with no verified price has an *unavailable*
  estimated cost. If a live run declares a dollar budget and the model has no configured price,
  the guard refuses before the first call.
- **Prices live in one catalog** with a snapshot date and a source, and it holds exactly the
  models that have been benchmarked -- today, one. Nothing is written into it from memory: a
  stale price silently understates a budget, which is the failure this whole module exists to
  prevent. A model with no verified price cannot be run under a dollar ceiling at all, which is
  what stands between `Settings.bedrock_model_id`'s default and an unintended bill.
- **The cost ledger** is a local JSONL artifact under `.eval-results/`. It records run id,
  timestamp, commit, dataset version and hash, provider, model, mode, calls, attempts, tokens
  and estimated spend. It carries no credential, no session token and no prompt. It is not
  committed.

### Phase 4 spending policy

| Slice | Live calls | Budget |
|---|---|---|
| P4.4 evaluation foundation | **0** | $0 |
| P4.5 Nova benchmark | Nova first, one bounded run | explicit budget required |
| P4.6 challenger | only if Nova misses a consequential threshold; Nova's failures plus matched controls, never a broad sweep | explicit budget required |
| P4.7+ | small smoke runs during implementation; full benchmarks only through the evaluation runner | explicit budget required |

Cheap model first, small datasets, explicit spend limits, no automatic broad challenger run.
Raising a budget is a conscious act by whoever runs it.

## CI

The evaluation job needs **no AWS credential, no OpenAI credential and no network**. It
validates the dataset against production, runs the deterministic scorers, exercises the
DeepEval adapter and the budget refusals, and runs the whole offline replay. No live model
benchmark runs in CI, and no GitHub secret is required for any of it.

## How a future model comparison must be run

1. Populate `evals/budget.PRICES` from a current published price list, with the date and source.
2. Review the `PROPOSED` thresholds and agree them, before seeing any result.
3. Run the development split first, with an explicit call cap and dollar cap.
4. Run the holdout split once, and record the summary: dataset version and hash, commit, prompt
   identity, provider, model, every metric, every gate, the operational numbers and the spend.
5. Compare two runs by joining their case results on `case_id` — same case, two readings, the
   quality, latency and cost difference. The result schema is built for that join; the
   challenger workflow itself is not implemented and no challenger has been run.
6. **Do not iterate a prompt against holdout results.** If a prompt changes, the development
   split is where it is judged, and the holdout is read again only for the next decision.
