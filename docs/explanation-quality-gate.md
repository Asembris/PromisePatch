# The bounded explanation quality gate (P4.8 foundation)

**These are hand-authored software-evaluation fixtures. Nothing in this document, and nothing the
harness it describes produces, is evidence of business impact.** They measure software and model
behaviour on thirty-five cases somebody wrote on purpose.

This slice builds and freezes the evaluation protocol around the bounded-explanation architecture
P4.7 shipped. **No model was called to build it.** Nova wrote nothing, Nemotron judged nothing,
and the model spend for the whole gate is $0.

---

## What P4.8 evaluates

Exactly one thing:

```text
ExplanationFacts  ->  SemanticJob.VERBALISE  ->  speech + fact_refs
```

When Nova 2 Lite is asked to say already-decided facts out loud, is the passage safe, faithful,
causally sufficient, concise, clear and suitable for speech?

## What it does not evaluate

Whether the impact was right, whether the recovery was right, whether approval was required,
whether the graph reachability was right, whether revalidation concluded correctly. Those are
deterministic outcomes the engine has already settled, and they arrive at this boundary as
*inputs*. A gate that re-litigated them would be measuring the engine through a paraphrase.

It also does not evaluate the deterministic fallback's prose. The fallback is checked
**structurally** across all thirty-five fixtures -- it renders, it fits its surface's word cap, it
carries the fact the outcome turns on -- and the LLM judge is never the authority over it.

---

## The dataset

```text
promisepatch-explanation-gold  v1.0.0
ebb9b6791e1eb453762b94a5c1d68c14b708a69d8f59a83bff059ee5cf7f1c57

35 cases   7 families x 5   ( 3 development + 2 holdout each )
21 development   14 holdout
```

Seven families over the four production surfaces. `TRACK_OUTCOME` is split four ways because its
four outcomes fail in different directions and an average over them would hide whichever one is
weak.

| Family | Surface | Cap |
|---|---|---|
| `PLAN_SUMMARY` | `PLAN_SUMMARY` | 70 words |
| `TRACK_AUTO_RECOVERABLE` | `TRACK_OUTCOME` | 40 |
| `TRACK_APPROVAL_REQUIRED` | `TRACK_OUTCOME` | 40 |
| `TRACK_BLOCKED` | `TRACK_OUTCOME` | 40 |
| `TRACK_UNAFFECTED` | `TRACK_OUTCOME` | 40 |
| `CUSTOMER_WAIT` | `CUSTOMER_WAIT` | 40 |
| `REVALIDATION` | `REVALIDATION` | 40 |

### Provenance

Hand-authored deterministic software-evaluation fixtures, written against the frozen projection in
`promisepatch.domain.explanations` and the Hollow Oak vocabulary. **Not** customer data, not
production traffic, not real message threads, not real-world validation.

### Validation is against production, not against itself

`python -m evals explanation-validate` runs the application over every case:

- every value drawn from a closed set must be one `CLOSED_VOCABULARIES` says the engine emits, so
  a plausible hand-written reason cannot enter the dataset;
- the facts, in order, must be a subsequence of what the surface's projection appends, and must
  contain the ones it always appends -- order matters because the facts fingerprint is over the
  sequence;
- the `required` set must be exactly the one the projection would compute from those facts;
- every classification/reason pair must be one the classifier can produce, every constraint
  citation must be the one its sub-cause cites, and no blocked or unaffected promise may carry a
  recovery fact;
- every revalidation case must name one of the engine's ten checks with the outcome that check's
  failure produces -- the check table is a restatement, and the dataset suite runs the engine's own
  `revalidate` to pin it;
- the whole fixture must build a real `VerbaliseRequest`, and the deterministic renderer must be
  able to phrase it inside the surface's cap while carrying the decisive fact.

### Coverage

Canonical Hollow Oak anchors in development: **A** Priya (automatic, pre-approved strawberry
variant), **B** Tomas (approval required, ask-before-visible-change), **C** Okafor-Reyes (blocked,
no-substitution), **D** Lena (unaffected, `NO_PATH`, Lemon Curd Layer v1), plus a canonical wait, a
canonical revalidation and the canonical plan summary.

Also covered: quantified and non-quantified shortfalls; multiple quantities; counts small enough to
be written as words; all three automatic sub-causes and both approval sub-causes; five blocked
sub-causes; both unaffected readings kept apart; four approval-request states; five of the ten
revalidation checks; a consent-shaped order reference (`YES-2291`); an instruction-shaped trade
name; long punctuated entity names; a plan where nothing is affected at all.

**A known gap in v1.0.0.** The frozen five-per-family distribution leaves room for five of the six
revalidation causes; *production task not started* is not covered. Recipe version, order version,
constraint snapshot, substitute stock and deadline are. Closing it takes a new dataset version.

---

## Hard gates and soft targets are never mixed

A high subjective score can never compensate for a hard safety failure. They are computed
separately, reported in separate sections, and gated separately.

### Structural -- production's own validator, ceiling zero

Every accepted passage is put back through `promisepatch.semantic.jobs.validate` against the
request that produced it. A finding here means the gate leaked.

| Metric | Must be |
|---|---|
| `schema_invalid_accepted` | 0 |
| `unknown_fact_refs_accepted` | 0 |
| `missing_required_fact_refs_accepted` | 0 |
| `word_cap_violations_accepted` | 0 |
| `unsupported_digit_claims_accepted` | 0 |
| `fallback_failures` (over all 35 fixtures) | 0 |

### Semantic -- one judge verdict per passage, ceiling zero

These need content-level judgement because P4.7 deliberately does not claim arbitrary prose is
checkable structurally.

| Metric | Must be |
|---|---|
| `outcome_contradictions` | 0 |
| `authority_contradictions` | 0 |
| `unsupported_entity_or_option_claims` | 0 |
| `unsupported_guarantees` | 0 |
| `unsupported_quantity_in_words` | 0 |

`unsupported_quantity_in_words` exists because the digit guard compares digit runs and understands
nothing: a passage saying "ten kilos short" where the facts say 9 passes it. **That limitation has
not gone away and is measured rather than assumed away.**

Two families carry their own gate: `CUSTOMER_WAIT` authority contradictions at zero, and
`TRACK_BLOCKED` invented alternatives at zero. Every family carries zero semantic failures and a
faithfulness floor of 4.0, so an average over seven cannot hide one weak surface.

### Quality -- accepted model prose only

Fixed before any Nova output existed.

| Dimension | Development target |
|---|---|
| faithfulness | >= 4.5 |
| causal completeness | >= 4.2 |
| clarity | >= 4.3 |
| brevity | >= 4.2 |
| speech naturalness | >= 4.2 |
| accepted passages with faithfulness < 3 | 0 |
| per-family mean faithfulness | >= 4.0 |

The acceptance rates -- accepted model verbalisation, validator rejection, provider failure,
fallback -- are printed above the quality means, because a model excellent on the third of cases it
did not get refused on is not a model with excellent prose.

---

## The judge

```text
provider   nvidia
model      nvidia/nemotron-3-super-120b-a12b
role       offline evaluation only
authority  NONE
```

Independent of the system under test on purpose: Bedrock runs the model being graded, and a judge
from the same vendor scoring its own vendor's output would be one opinion wearing two hats.

### Exactly one structured call per accepted passage

```text
one accepted passage  ->  ONE judge request  ->  ONE JudgeVerdict
                          (5 safety flags + 5 scores + one rationale)
```

Not one call per dimension. Not one metric per dimension each opening its own connection. Twenty-one
accepted development passages cost **at most twenty-one ordinary judge calls**, and
`evals/tests/test_explanation_judge.py` proves it with instrumentation rather than asserting it in a
comment. A bounded corrective retry is counted as a *provider attempt* and never as a second logical
call.

### The verdict contract refuses a broken answer

`JudgeVerdict` is Pydantic v2 with `extra="forbid"` and `strict=True`. A 0, a 6, a float where an
integer belongs, a string where a boolean belongs, a missing score, a missing flag, an unknown key
and an over-long rationale are each refused. Nothing is clamped, defaulted or partially believed: an
answer that does not validate produces `JUDGE_RESULT_INVALID` and an **unscored** case.

### The judge decides nothing

It cannot promote a passage production refused -- a rejected passage is a fallback whatever the
judge thinks of the prose. It cannot lower a structural finding. And its outage is its own: three
unexpected transport failures stop judging, the generation results stand untouched, and the
subjective verdict is reported **INCOMPLETE** rather than as a model that did badly. There is no
automatic switch to another judge.

### DeepEval is a runner, and the fan-out prohibition is structural

DeepEval organises and reports. It may not hold, construct or reach a model. No `GEval`, no
`FaithfulnessMetric`, no `AnswerRelevancyMetric`, no default OpenAI judge. `ExplanationQualityMetric`
is a shell over a verdict that already exists, and the regression test runs it over every case and
asserts zero provider calls. If a framework metric ever starts opening its own connection, that test
is where it appears.

### Contingency, documented only

If NVIDIA's hosted endpoint becomes operationally unusable, a separately authorised future decision
*may* select `gpt-4o-mini-2024-07-18` ($0.15 / $0.60 per 1M, already in the pricing catalog). That
would be **one judge replacing this one** -- still exactly one structured call per passage. No
ensemble, no second simultaneous pipeline. Nothing in this gate selects it, prices a run against it
or calls it.

---

## Cost accounting

Generation and judging never share a counter.

| | Nova generation | Nemotron judging |
|---|---|---|
| billing | metered | `free_hosted_trial` |
| price | $0.33 in / $2.75 out per 1M (Regional, verified 2026-09-08) | none published |
| known USD | computed with `Decimal` | **not modelled** |

`$0.00` is never written for the judge. That would assert a commercial rate nobody published and
would switch off the dollar guard for the model that has one. What bounds a free endpoint is calls
and tokens -- the resource actually at risk is quota.

The judge's billing mode has exactly one repository value, `BillingMode.FREE_HOSTED_TRIAL` in
`evals.budget`, and every plan, report and judging summary renders that enum rather than a
string of its own. It is a mode, never a price.

### Derived development ceilings

Computed by serialising every development case's production request and measuring it. No inference,
no provider, no number copied from another run.

```text
NOVA        logical calls 21   provider attempts 42
            input tokens  83,677   output tokens 13,440
            derived from 75,211 measured prompt characters
            projected $0.052   hard ceiling $0.07

JUDGE       logical calls 21   provider attempts 42
            input tokens  92,072   output tokens 21,504
            derived from 85,287 measured prompt characters
            billing mode free_hosted_trial   known USD not modelled
```

Characters are converted at three per token where English is nearer four, every case is assumed to
take both permitted attempts, and the dollar ceiling carries a further 25%. The point is not a
forecast. The point is that a runaway is refused **before** the provider call that would cause it.
The Nova figures above are the ones `python -m evals explanation-plan --split development` derives
from the repaired verbalise instruction (see *One repair* below); the first development run was
bounded by the pre-repair figures, 73,807 input tokens from 63,367 characters, under the same $0.07
ceiling.

### The ceiling is per run, and a split buys at most two runs

The derived ceiling bounds **one run identity**: a canary and the resume that finishes it are one
run, one file and one allowance, and a resumed pass is charged for every call the identity already
made. It does not bound the gate's lifetime, because the protocol below authorises exactly one
repaired rerun after the one repair, and a rerun that inherited what the first run left would have
been refused after one call -- which is what the first accounting did, and why it was fixed.

```text
per run      21 logical calls, the derived token ceilings, $0.07
per split    that ceiling times the runs the split may ever buy, minus everything every run spent
             DEVELOPMENT  2 runs   one original + one repaired rerun   42 calls, $0.14
             HOLDOUT      1 run                                        14 calls, its own ceiling
a third development run identity is refused before its first call
```

A run is an identity that bought at least one call; an identity refused before its first call is
not a run and does not use the allowance. A typed `--max-calls` or `--max-estimated-usd` still only
narrows. Nothing resets: the split's cumulative spend is recognised across both runs and printed
run by run, with the cumulative total, by `plan --split development` and after every generation
pass.

**What a run spent is recognised from every record of it.** The ledger says what a pass charged on
its way out; the run file says what was written down as each call returned. Where they disagree,
the larger is recognised field by field, and the disagreement is printed rather than either record
being edited. That is how the first run is accounted for: `p48dev`'s canary was written to its run
file before the ledger-on-the-way-out fix existed, so its ledger line says 20 calls while its run
file holds 21 generation records. The line is not rewritten. The run is recognised as 21 logical
calls, 25 provider attempts, 35,214 input and 1,575 output tokens, $0.01595 -- one call, one
attempt, 1,630 input and 74 output tokens, $0.00074 more than the ledger alone says -- and the plan
prints both figures. New ledger lines name their split; a line that names none is attributed
through the run file with its identity, and one with neither is charged against **every** split,
because an unattributable spend that debited nothing would be an allowance nobody granted.

---

## Authorisations

Three scopes, and none implies another:

```text
AUTHORISE-PAID-INFERENCE-P4-8-NOVA-DEVELOPMENT-GENERATION
AUTHORISE-PAID-INFERENCE-P4-8-NEMOTRON-DEVELOPMENT-JUDGING
AUTHORISE-PAID-INFERENCE-P4-8-EXPLANATION-HOLDOUT
```

Letting the model under test speak is not letting somebody else's model grade it, and neither is
permission to open the holdout. There is no `ALLOW_ALL_LIVE_EVALS`. Command line only, run-scoped,
never defaulted -- and a process running under pytest may not construct a paid provider whatever
phrase was typed and whatever credentials it inherited.

---

## Result identity and replay

Two records, kept apart:

- **`NovaExplanationResult`** binds to provider, model, commit, dataset name/version/hash, case,
  family, the facts fingerprint, the prompt hash, the schema hash and the word limit. Change any of
  them and the fingerprint moves, so a stored passage cannot be presented as an answer to a question
  that has changed.
- **`ExplanationJudgeResult`** binds to judge provider, judge model, rubric version, judge prompt
  hash, verdict schema hash **and the generation fingerprint it judged**.

Every record's `dataset_hash` is the frozen dataset's hash -- the one the manifest, the run header
and the authorisation name. A split, and the narrowed selection a resumed run generates from, are
views of that dataset and inherit its identity; they never hash the handful of cases they hold.

**Compatibility.** Generation and judge records written before this was pinned (the first
development run, `p48dev`) carry the hash of the selection they were generated from -- one value
for the single-case canary, another for the twenty cases the resume covered -- while their run
header carries the authoritative hash. Those files are not rewritten: `report` and `review` read
them as they are, the header is what gates a resume and a judge pass, and the records are refused
for rejudging anyway because the verbalise prompt has moved since they were written.

That separation buys the three replay properties:

| Operation | Nova calls | Judge calls |
|---|---|---|
| rescore stored results | **0** | **0** |
| rejudge stored results | **0** | one per accepted passage |
| rebuild a report | **0** | **0** |

Each is a test, not a claim.

---

## Leakage

Proved structurally, textually and by experiment.

**Towards Nova.** `ExplanationModelInput` has three fields and one is the production request. No
reference passage, split, tag, note, calibration focus, threshold, rubric or expected verdict
appears in the bytes a provider would be sent -- including the corrective retry. Replacing a case's
entire expected block, or moving it between splits, changes the request by **zero bytes**. The
committed scripted payload files share no wording with any reference passage either, so a scripted
run cannot smuggle one in.

**Towards the judge.** A judge request carries the authoritative facts, the required refs, the
surface, the word limit and one passage. It does not carry the split, the tags, the reference, the
expected constraints, any threshold, any previous verdict, or any marker saying a case is
adversarial. The human reference is deliberately **not** sent: the judge compares the passage with
the facts, which is the comparison the product cares about, and comparing it with somebody's
preferred wording would score similarity to a style rather than fidelity to a fact.

---

## Protocol

### Development

```text
21 development ExplanationFacts
      -> Nova generation
      -> production validation (the workflow's own acceptance path)
      -> accepted verbalisation or deterministic fallback
      -> deterministic hard scoring
      -> accepted model prose only
      -> ONE Nemotron JudgeVerdict each
      -> manual review of ALL 21
      -> DEVELOPMENT verdict
```

Manual review of every one of the twenty-one is required on the first live run -- plus every hard
failure, every dimension scored 3 or below, and every judge/validator disagreement, on every run
after. The dataset is deliberately small enough to read end to end. An LLM judge is not the
authority here.

### One repair

**At most one bounded production prompt or contract repair before the holdout.** If development
fails, diagnose manually first, into these buckets:

```text
ARCHITECTURE_OR_CONTRACT_DEFECT   PROMPT_DEFECT   MODEL_QUALITY
JUDGE_DEFECT                      FIXTURE_DEFECT  EXPECTED_FALLBACK
```

Only a genuine architecture/contract or prompt defect may spend it. No case-specific hacks, and no
weakening a gate to make a run pass.

**The repair has been spent.** The first development run (`p48dev`, 2026-09-09) passed six of the
seven families and failed `PLAN_SUMMARY` with two outcome contradictions: the count of promises
*affected* was said as promises *blocked*, once against a `case.blocked` of `0`. Manual diagnosis
classified it `PROMPT_DEFECT`: the payload carries all five counts with their labels, the engine
keeps the four postures apart, and the verbalise instruction explained none of that while its only
outcome vocabulary was the word *blocked*. The four causal-completeness misses in the same run
(`auto.002`, `blocked.002`, `wait.003`, `revalidation.001`) shared one cause -- a required fact cited
in `fact_refs` and left out of the words, which the instruction framed as an id-list requirement.
One revision of the verbalise system instruction, two generic rules, no fixture text, no case id,
no phrase list: counts of promises are a whole and its parts, and a required fact must be said,
not only cited. The prompt hash moved with it, so `p48dev`'s passages cannot be rejudged as answers
to the current question and DEVELOPMENT must be generated again. No second repair remains before
the holdout.

### Model selection is not reopened automatically

If Nova's quality is weak, the next step is **not** benchmarking GPT-4o-mini, Nemotron-as-generator,
Haiku or anything else. A legitimate conclusion is that the deterministic fallback is better than a
model for one or more explanation surfaces.

### Holdout

Fourteen sealed cases. Sealed during prompt development, judge calibration, threshold changes,
development execution, development repair and development analysis. Requires its own explicit
authorisation after the development evidence has been reviewed. There is no automatic continuation.

The existing customer-intent semantic holdout is unrelated and was **not opened**.

---

## Judge calibration

Five development-only examples with hand-authored candidate passages and expected verdicts as
*ranges*:

| Example | Shape |
|---|---|
| `calibrate.excellent` | grounded, complete, short |
| `calibrate.incomplete` | safe, no invention, and never says why |
| `calibrate.wordy` | true, inside the cap, painful aloud |
| `calibrate.authority` | claims an approval that does not exist |
| `calibrate.invented` | a substitute, a delivery and a promise none of the facts contain |

The authority example deliberately keeps clarity and brevity high: a subjective score must never
offset a hard flag, and this is where that is checked. Calibration makes **no calls in this gate**,
and running it later requires its own authorisation.

---

## Commands

```bash
python -m evals explanation-validate            # dataset against production
python -m evals explanation-plan                # the zero-call preflight
python -m evals explanation-plan --split development
python -m evals explanation-replay              # offline run, gates and all
python -m evals explanation-replay --json --out .eval-results
python -m evals explanation-manifest --write    # after a deliberate dataset change
```

There is no live command here, and nothing reachable from `python -m evals` can construct a Bedrock
or NVIDIA client. The plan prints counts and ceilings and no sealed passage.

### The live surface

Reaching a model is a **composition root outside both cores**, `scripts/run_explanation_eval.py`,
for the reason the import contract exists: `evals` may not import a vendor SDK, so the package that
scores cannot be the package that spends.

```bash
python -m scripts.run_explanation_eval plan --split development

python -m scripts.run_explanation_eval generate --live --split development \
    --authorise-paid-inference AUTHORISE-PAID-INFERENCE-P4-8-NOVA-DEVELOPMENT-GENERATION

python -m scripts.run_explanation_eval judge --live --split development \
    --results .eval-results/explanation-<run>.jsonl \
    --authorise-paid-inference AUTHORISE-PAID-INFERENCE-P4-8-NEMOTRON-DEVELOPMENT-JUDGING

python -m scripts.run_explanation_eval report --results .eval-results/explanation-<run>.jsonl
python -m scripts.run_explanation_eval review --results .eval-results/explanation-<run>.jsonl
```

Four properties, each a test rather than a claim:

- **Two passes, two authorisations, neither implying the other.** `--live` names a code path; the
  scope-bound phrase is typed at the invocation, read from nowhere else and never defaulted. A
  generation phrase cannot buy judging, and neither can open the holdout -- `--split holdout` maps
  to `AUTHORISE-PAID-INFERENCE-P4-8-EXPLANATION-HOLDOUT` in both passes. A process running under
  pytest constructs no paid provider whatever it was handed.
- **Every passage and verdict is on disk the moment it exists**, in one JSONL run file whose header
  gates the resume on commit, dataset name/version/hash, provider, model, mode, split, prompt hash
  and schema hash. An interrupted run continues; a file from another experiment is refused. The
  judge reads passages from that file and never reaches Nova, and a passage written under a prompt
  or schema that has since moved is refused rather than rejudged.
- **A call that happened is in the ledger, exactly once.** The generation pass writes its ledger
  line on the way out, whichever way it ends -- a `--max-calls` ceiling refusing the next call, a
  provider fault, an interrupt -- so a canary of one paid call cannot be recorded in the run file
  and missing from the ledger. One line per pass, so a resumed run charges its own calls and never
  the canary's again; a pass that bought nothing writes nothing. The ceiling is per run identity
  and a split buys at most the runs the protocol authorises (see *The ceiling is per run* above), so
  a repaired rerun starts with the whole derived allowance and a third identity is refused before
  any call.
- **`report` and `review` call nothing.** Both are rebuilt from the run file, which is what makes a
  lost terminal cheap and the manual review of all twenty-one free.
- **The two providers never share a counter or a ledger.** Nova's ceiling is the one this dataset
  derives and its spend lands in `.eval-results/explanation-cost-ledger.jsonl`, separate from the
  customer-intent gate's: a ceiling for this evaluation is not a ceiling on everything the account
  has ever spent. NVIDIA's usage is recorded in calls and tokens with its dollars absent.

---

## What this gate spent

```text
NOVA MODEL CALLS            0
NVIDIA JUDGE CALLS          0
GPT-4O-MINI JUDGE CALLS     0
OPENAI OTHER MODEL CALLS    0
HAIKU MODEL CALLS           0
OLLAMA MODEL CALLS          0
OTHER MODEL CALLS           0

MODEL SPEND                 $0

EXPLANATION HOLDOUT MODEL CALLS   0
SEMANTIC HOLDOUT MODEL CALLS      0
```

The live surface described above was built and exercised **offline**, against the scripted factory
and a scripted judge passed in as parameters. Building the path that can spend is not spending, and
this count stays at zero until a development run is separately authorised.
