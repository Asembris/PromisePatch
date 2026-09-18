# The `SUR-1` execution harness

**Built. Not run. No arm has been driven, no model has been reached, and no comparative number
exists.**

[`safe-useful-recovery-benchmark.md`](safe-useful-recovery-benchmark.md) closes with a list of
what the specification session deliberately left undone, and the first item on it is this:

> **The driver was not built.** Arm construction, evidence collection from the four receivers,
> the ablation wrapper's wiring, the capture writer and the token map belong to the execution
> session, which needs them and which is not this one.

This document records that machinery. It is still not the execution session: the harness has been
proved against stub arms, scripted models and evidence written by hand, and it has never been
pointed at a `SUR-1` scenario.

| | |
|---|---|
| Package | `scripts/sur1/` |
| Driver version | `1.0.0` (`scripts.sur1.DRIVER_VERSION`) |
| Benchmark | `SUR-1` v1.0.0, manifest SHA `5718340f…e70e84c` |
| Baseline prompt SHA | `772ba460…9ce47cb1` |
| Scorer | `scripts/score_safe_useful_recovery.py` v1.0.0, unchanged |
| Runs taken | **none** |

## Why it lives in `scripts/`

Beside the frozen scorer and verifier, and outside every application.

`scripts` is not one of import-linter's `root_packages` and is not synced into the runtime image,
so no deployed process can reach the ablation wrapper. That is the structural half of the
contract's promise that arm C changes no production file: the wrapper cannot be imported by
anything that runs in production, rather than merely not being imported by it today.

It could not live under `evals/`. That package is forbidden `boto3`, `httpx2`, `sqlalchemy`,
`socket`, `promisepatch.api`, `promisepatch.db` and `promisepatch.integrations`, which is exactly
right for an offline measurement harness and exactly wrong for a driver that has to reach a model,
an order system and a case workspace.

## Architecture

Ten modules. Each one owns one thing, and the boundaries between them are the contract's own.

| Module | What it owns |
|---|---|
| `frozen.py` | The three pinned identities and a typed read of the contract. Refuses a run. |
| `manifest.py` | `RunManifest`, `AttemptIdentity`, `AttemptManifest`, `Spend`. |
| `budget.py` | One ledger. Every ceiling, refused before the call that would cross it. |
| `arms.py` | The one `ArmAdapter` interface, the world and model ports, the terminal signals. |
| `evidence.py` | The four receivers' raw rows, and the blind projection to the scorer's bundle. |
| `replay.py` | Reading a capture back, so a verdict can be recomputed without re-driving. |
| `capture.py` | The artefact layout, write-once, the resume index, the token map. |
| `ablation.py` | Arm C: revalidation check 5 dropped from the outcome derivation. |
| `adapters.py` | The three arms. |
| `doubles.py` | Stand-ins, so the harness is provable without buying an attempt. |
| `driver.py` | The loop: budgets, retries, void, capture order, resume, the blinded join. |

## The adapter contract

One method, and deliberately no others.

```python
class ArmAdapter(Protocol):
    label: str
    def run(self, request: AttemptRequest) -> ArmAttempt: ...
```

An arm is handed an `AttemptRequest` — its identity, the scenario **without its ground truth or
its point**, the frozen contract, a budget and a world — and returns an `ArmAttempt`: receiver
evidence plus arm-specific diagnostics. It cannot write its own capture, decide its own outcome,
read the answer it is scored against, or widen its own budget, because none of those is reachable
from what it is given.

`label` exists so the driver can mint a token for it. It never travels with a result.

| Arm | Label | How it differs |
|---|---|---|
| A | `BASELINE` | A tool-using agent over a `ModelClient` port, given the frozen prompt. |
| B | `PROMISEPATCH` | Driven over a `WorkerSurface` port: report, clarify, confirm, read status. |
| C | `ABLATION` | Arm B's own object, inside the `ablation()` context manager. One line. |

Arm C **composes** arm B rather than subclassing it, so "drive PromisePatch" has exactly one
implementation and the ablated arm cannot drift into being a second one.
`test_the_ablated_arm_does_exactly_what_the_full_arm_does_plus_a_log` drives both against the same
script and asserts the conversations and the reads are identical.

### The frozen prompt, exactly

`BaselineArm` hands the model `docs/benchmarks/baseline-agent-prompt.v1.md` as the bytes on disk,
after `Contract.load()` has asserted the published hash. Not summarised, not excerpted, not
supplemented.

The file was **not** cut down to its "System instruction (verbatim)" section. Choosing where to
cut is choosing what the baseline is, and a benchmark whose baseline is shaped by the winner's
authors is worth exactly as much as that shaping.

One thing is structurally required and is therefore declared rather than hidden: `KICKOFF` is the
first user turn, because the Converse API needs one. It is the string `"Begin."`, identical for all
nine scenarios, and it carries no fact about any of them — the agent learns what happened by
calling `get_incident`, which is the same read arm B works from.

Arm A's **tool argument schemas** are the harness's, not the contract's, because arms B and C
never see one. The names and the descriptions come straight out of the contract's `tool_surface`
block.

## The ablation, and one disclosed discrepancy

The contract fixes arm C to `promise_graph.revalidation._substitute_check`, check 5, "substitute
still available". The wrapper calls the real evaluator unchanged, drops check 5 from the list the
outcome is derived from, and re-derives from the lowest-numbered remaining failing check **using
the evaluator's own `_OUTCOME_BY_CHECK` mapping, imported rather than copied**. A second copy of
that mapping would eventually measure a transcription error.

`RevalidationResult` carries one `checks` tuple that the domain uses for two jobs: deriving the
outcome, and writing the checks to the durable ledger. The contract wants check 5 gone from the
first and present in the second. So the wrapper replaces check 5 in place with a non-decisive
marker that keeps its real reading: the name becomes
`substitute still available [ABLATED: dropped from the outcome by SUR-1 arm C]` and the `actual`
becomes `FAILED(dropped): <what it really read>` or `PASSED(dropped): <…>`. An audit sees that it
was dropped *and* what it would have said, and `result.failed[0]` — which the durable refusal path
names as the deciding check — is never check 5.

`assert_only_check_five_moved` runs on **every** call, not once in a review: same length, same
order, checks 1–4 and 6–10 identical values, check 5 present and marked and absent from `failed`.
`test_only_check_five_stops_deciding_the_outcome` is parametrised over all ten positions.

**The discrepancy.** The frozen contract's `how_it_is_removed` says the arm wraps
`promise_graph.revalidation.evaluate`. There is no `evaluate`; the function is
`promise_graph.revalidation.revalidate`, and `_substitute_check` — which the contract names
precisely and which is what actually pins the arm — belongs to it. The harness wraps `revalidate`.
**The manifest was not edited**, because editing a frozen document to fix a name would move a
published hash, and the contract's own freeze block forbids a change that is not separately
versioned. It is recorded here instead.

The wrapper is installed over `promisepatch.domain.revalidation.revalidate` — the binding the
durable step resolves — for the length of one attempt, and restored in a `finally`. Rebinding the
engine's definition would change what every other importer sees.

## Evidence and artefact layout

```
docs/benchmarks/runs/<run_id>/
    run.json                  the run manifest and its identity fields
    arm_map.json              token -> arm. The scoring path never opens this.
    attempts/<key>.json       RAW: the receivers' rows, diagnostics, spend, latency
    verdicts/<key>.json       SCORED: outcome, primary, safety, findings. Token, never arm.
    result.json               the join, written by a separate later invocation
```

`<key>` is `<arm_token>-<scenario_id>-a<attempt>`, which is `AttemptIdentity.key` and is the
resume key.

**Raw evidence is a different artefact from the verdict that judged it.** That is what stops a
re-score from rewriting what a receiver saw, and it is what makes "re-score without re-running"
possible at all: the expensive half is on disk and the cheap half is a pure function of it.

Every write is a **write-once**. `write_once` refuses a path that already exists.

### What reaches the scorer, and what does not

| Collected | Reaches the bundle |
|---|---|
| E1 order events, E2 messages both directions, E3 task samples, E4 report | yes, projected |
| `promises[].reason` free text | **no** — the scorer's own type has no field for it |
| latency, model calls, tokens, dollars | **no** — they stay on the attempt manifest |
| the arm's label | **no** — an opaque token, and the map is a separate file |
| arm C's ablation log | **no** — it is a diagnostic, captured and never scored |

The `sequence` the scorer reads is derived here: one total order across E1's `occurred_at` and
E2's `accepted_at`, ties broken by receiver then by row identity. **E1 wins a tie**, which is the
fail-closed direction — an amendment and a literal `YES` recorded at the same instant read as the
amendment coming first, which is a consent violation rather than a pass.

`literal_decision` is decided structurally, by exact match on the stripped text against `YES` or
`NO`, and deliberately **not** by PromisePatch's own consent parser. Using one arm's
implementation to shape the scorer's input would be an undeclared advantage over the other two.

### Malformed evidence fails closed

A receiver row the projection cannot place — an order outside the case universe, a channel that
names no order, a direction that is neither inbound nor outbound, an amendment to nothing, a task
with only one sampled state — raises `EvidenceMalformedError`, which the driver records as
`HARNESS_FAILURE`. Never a default, never a drop, never a zero on a safety ceiling.

A source that could not be *read* is a different fact and is carried through as
`unreadable_sources`, which the scorer turns into `VOID`.

## Budget, retry and resume semantics

**Budgets.** One `AttemptBudget` per attempt, built from the contract's own ceilings. An arm calls
`authorise_model_call()` before a provider and `authorise_tool_call()` before a receiver, and the
ledger raises rather than reporting afterwards. Tokens are charged when the provider reports them
and refuse the *next* call, because that is the only place the refusal can honestly land; an answer
already paid for is recorded rather than dropped. Unknown cost is `unavailable` and never `0`.

**Terminal statuses.** `BUDGET_EXHAUSTED` and `HARNESS_FAILURE` are facts the driver observed and
are written **without calling the scorer at all**. Neither is `VOID`. Turning a nonpass into a void
is precisely how a bad attempt would vanish from a denominator that is capped at two.

**Retry.** One per scenario per arm, only when attempt 1 ended `VOID`, the whole scenario from a
clean fixture. Both attempts keep their captures and the retry's verdict is the scored one, marked
`retried`. `INVALID`, `BUDGET_EXHAUSTED`, `DISQUALIFIED` and every other verdict are never
retried. There is no third attempt: `AttemptIdentity` refuses to be one.

**Resume.** The driver skips any attempt identity that already has a raw capture, and re-scores any
that has a capture but no verdict — scoring is free, driving is not. The token map is minted once
and read back, so an attempt keeps its identity across a restart. A resumed run whose pinned
identities differ from the ones the run started with is **refused**, for the reason
`evals.store` gives about its own header.

**Order of writes.** Raw capture → verdict → join. A process that dies between the first two
resumes by re-scoring a file. A process that dies before the join has every verdict already
written, which is the blinding rule's own requirement: *verdicts are written before the map is
joined.*

## Frozen-hash enforcement

`assert_frozen()` runs before an arm is constructed, before a scenario is read and before a
transport is opened. It recomputes and compares:

1. the manifest's canonical SHA-256, against the published `5718340f…`;
2. the baseline prompt's newline-normalised SHA-256, against the published `772ba460…`;
3. the scorer's own `SCORER_VERSION` against `1.0.0`, and the scorer's `PUBLISHED_MANIFEST_SHA`
   against the driver's. A scorer pinned to a different contract is two experiments.

Any mismatch raises `FrozenIdentityError` and the run does not start.
`test_an_edited_ground_truth_entry_refuses_the_run` softens one bound in a copy of the manifest and
asserts the refusal.

## The one determination the harness refuses to make

The contract hands the driver `MessageRow.asserts_change` — whether an outbound message asserts
that a change was made — and requires that

> the rule by which the driver sets it must be declared in the execution session's
> predeclaration, before the first scored run.

This session is not that session. So the harness ships `UNDETERMINED`, which returns `None` for
every message, and `drive()` **refuses `kind="scored"`** unless it has been handed a classifier
that is not that default. A development run may proceed without one; its outbound messages are
undetermined and the ambiguity rule voids those scenarios, which is the honest reading of a rule
nobody has declared.

Inventing the rule here would be making a scoring determination while it is still possible to see
what the rule would do to an outcome.

## How it was validated without consuming `SUR-1`

Six test modules, 122 tests, under `scripts/tests/`. Every one of them runs beneath that
directory's existing `conftest.py`, which intercepts every outbound connection and **raises on
anything that is not loopback** — so "no model was called" is a property of the process rather than
a statement of intent.

| Proof | Where |
|---|---|
| Three adapters obey one interface | `test_sur1_adapters.py::test_all_three_arms_satisfy_one_adapter_protocol` |
| The baseline gets the frozen prompt, hash checked | `…::test_the_baseline_is_handed_the_frozen_prompt_as_the_bytes_on_disk` |
| The prompt is never supplemented per scenario | `…::test_the_baseline_prompt_is_never_supplemented_with_a_scenario_fact` |
| Budget exhaustion terminates the attempt | `test_sur1_budget.py`, `test_sur1_driver.py::test_budget_exhaustion_ends_the_attempt_and_is_never_a_void` |
| `BUDGET_EXHAUSTED` never becomes `VOID` | same test |
| A `VOID` retry happens at most once | `test_sur1_driver.py::test_a_void_is_retried_exactly_once` |
| `INVALID` is not retried as a `VOID` | `…::test_an_invalid_report_is_not_retried_and_is_not_a_void` |
| Both attempts captured, neither dropped | `…::test_both_attempts_are_captured_and_neither_is_dropped` |
| Resume skips completed attempt identities | `…::test_resume_skips_completed_attempt_identities` |
| A died-before-scoring run is not re-driven | `…::test_a_run_that_died_before_scoring_is_scored_without_being_re_driven` |
| The bundle leaks no arm label | `test_sur1_evidence.py::test_the_bundle_carries_a_token_and_no_arm_anywhere_in_it` |
| E4 free text is stripped | `…::test_every_free_text_field_of_the_worker_report_is_stripped` |
| Latency and cost are recorded, excluded, joined after | `test_sur1_driver.py::test_latency_and_cost_are_captured_and_joined_only_after_every_verdict` |
| The ablation removes exactly check 5 | `test_sur1_ablation.py::test_only_check_five_stops_deciding_the_outcome`, parametrised 1–10 |
| Malformed and partial evidence fail closed | `test_sur1_evidence.py`, `test_sur1_driver.py::test_malformed_evidence_fails_closed_to_a_harness_failure` |
| A moved manifest refuses before an arm is built | `test_sur1_driver.py::test_a_moved_manifest_refuses_before_any_arm_is_constructed` |
| A scored run refuses an undeclared rule | `…::test_a_scored_run_refuses_an_undeclared_outbound_rule` |
| An arm never sees its ground truth | `…::test_an_arm_is_never_shown_the_answer_it_is_scored_against` |

The driver tests use stub arms labelled `HARNESS-A`, `HARNESS-B` and `HARNESS-C` so no artefact
they write could be mistaken for a comparative attempt, and every run lands in `tmp_path` rather
than in the committed runs directory. Scenario `C01` appears in them only because the scorer loads
ground truth by identifier out of the frozen document and refuses an invented one — which is the
property that stops a caller scoring against a bound it would rather have.

## What was not done

- **No comparative run was taken.** No arm was driven against a `SUR-1` scenario, no
  `EvidenceBundle` was collected from a real attempt, and no number comparing any two arms exists.
- **No model was called.** No Bedrock, no OpenAI, no NVIDIA. No AWS resource was read or mutated
  and no spend authorisation was used. `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` remains unspent.
- **No frozen document was edited.** The manifest, the baseline prompt and the scorer are byte-for-
  byte what they were; both published hashes still verify.
- **No production file was changed.** Nothing under `packages/`, `apps/`, `evals/` or `deploy/`.
- **The live bindings were not written**, and this is the harness's largest declared gap. The ports
  `ModelClient`, `ScenarioWorld` and `WorkerSurface` are defined and exercised against doubles; the
  concrete bindings — a `bedrock-runtime` Converse client, a scenario world that applies stipulated
  facts to a clean Hollow Oak fixture and reads the four receivers back, and an MCP/workspace client
  for arms B and C — belong to the execution session. Writing them here would mean shipping a
  Bedrock client this session is forbidden to call and a world adapter it could not exercise.
- **The `asserts_change` rule was not declared.** See above. It is the execution session's
  predeclaration.
- **The effect sets are untouched.** `11/16` stands, the manifest hash is unchanged, `S12` stays
  committed failing.
- **Both evaluation holdouts stay sealed**, and neither was consulted.
- **This work sits outside the gate structure.** `G8` is the open gate and this is not one of its
  required artifacts. It should not be counted as one.
