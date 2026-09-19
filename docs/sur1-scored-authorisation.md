# A scored `SUR-1` run is driven under a capability

`SUR-1` is a one-shot comparative benchmark. It may be taken once, its retry policy permits no
second opinion, and whatever number comes out is the headline. So the question this slice answers
is not *did somebody run the preflight* but *can a scored run exist without one*.

Until this change, it could.

## The weakness, stated as it was

[`sur1-execution-bindings.md`](sur1-execution-bindings.md) named it in its own words:

> `driver.drive()` is still callable directly, and called that way it enforces only what it always
> did … A caller who imports the driver and bypasses `run.py` has bypassed the preflight, and that
> is a fact about the entry point rather than a property of the gate.

That was accurate, and it was the whole hole. `kind="scored"` was a string. Anything that could
import `scripts.sur1.driver` could pass it, and what came out was a directory of scored artefacts —
`run.json` saying `"kind": "scored"`, an arm-token map, attempt captures, verdicts, a joinable
`result.json` — indistinguishable from an authorised run's, having asked none of the eleven
preconditions.

It was not a hypothetical. `test_a_declared_rule_lets_a_scored_run_start` did exactly this: stub
arms, a world made of values, a rule declared inline in a test file, and a scored run directory
on disk. That test now asserts the refusal.

### Every path that could produce a scored artefact

| Path | Before | Now |
|---|---|---|
| `run.execute(kind="scored")` | preflight, then drive | unchanged, and it is where the capability is minted |
| `driver.drive(kind="scored")` called directly | wrote the full scored layout | refused without a capability |
| `capture.open_run(manifest)` with a scored manifest | created `run.json` and the token map | refused without a capability |
| `RunManifest(kind="scored")` | constructible anywhere | constructible, and reaches no artefact without the two gates above |
| `write_attempt` / `write_verdict` / `write_driver_verdict` | write into a `RunDirectory` | unchanged; a scored directory cannot be opened to write into |
| `driver.join(directory)` | publishes `result.json` | unchanged; it joins a directory only `open_run` can have created |

The last three need no gate of their own, and giving them one would have been theatre: they cannot
reach a scored layout that `open_run` refused to create. What they *do* need is the guarantee that
no fourth module quietly grows its own copy of one, which is
`test_one_module_calls_each_scored_artefact_path` — an AST scan asserting each of those names is
called from exactly one module in `scripts/sur1/`.

## The design

A passing scored preflight now returns a **capability**, and the scored path asks for the object
rather than for the assurance that one exists.

```
preflight()  ->  PreflightReport  --authorise()-->  ScoredAuthorisation
                                                          |
                                        drive(kind="scored", authorisation=…)
                                                          |
                                        open_run(manifest, authorisation=…)
```

`scripts/sur1/authorisation.py` is a **leaf module**: it imports nothing from `scripts.sur1` at
module scope, so the capture layer, the driver and the preflight can all depend on it without a
cycle. What it needs from the frozen contract it imports inside the function that needs it.

### It cannot be constructed

`ScoredAuthorisation.__init__` refuses every caller that does not hold the module's own sentinel,
so `ScoredAuthorisation(fingerprint)` raises. The one function holding the sentinel is
module-private `_grant`, and `preflight.authorise` is the only thing in the repository that calls
it. `authorise` refuses in turn:

- a `report` that is not a `PreflightReport` — by type, not by duck-typing;
- a report or a fingerprint that is not `kind="scored"`;
- a report that does not name **every** check in `preflight.REQUIRED_CHECKS`, so a hand-built
  report holding one cheerful check cannot mint;
- a report on which any check failed.

`REQUIRED_CHECKS` is a named list rather than a count, because a report naming eleven checks — one
of them new, two of them missing — would satisfy a count.
`test_the_required_checks_are_the_questions_the_preflight_actually_asks` pins the list against what
`preflight()` actually produces, so a twelfth check cannot be added and silently left out of the
gate.

### It binds what was checked, not that checking happened

A `RunFingerprint` is **observed from the live objects** — not accepted as a description of them:

| Bound | Read from |
|---|---|
| `benchmark_id`, `manifest_sha`, `baseline_prompt_sha`, `scorer_version` | `Contract.load()`, recomputed from disk at both ends |
| `model_configuration` | the contract's own frozen configuration |
| `predeclaration_sha`, `classifier_rule` | `predeclaration.identity_sha()` and the classifier function's own module and qualname |
| `world_program_sha` | `bindings.declaration.implementation_sha()` |
| `world` | the world object's declared `binding_kind` and its `identity()` |
| `arms` | each arm's label, its concrete type, and the `model` / `surface` / `inner` bindings reachable through it |
| `run_id`, `root`, `scenarios`, `kind` | the run inputs, with `root` resolved |

The capability carries that fingerprint's digest. `drive()` observes the fingerprint **again**,
from the objects it was actually handed, and claims the capability against it. One differing field
refuses the run and the refusal names the field.

That second observation is what makes it a binding rather than a receipt. A capability minted
against the real bindings cannot drive stubs, because a stand-in declares no `binding_kind` and
fingerprints as `kind=none`. A `BaselineArm` holding a `ScriptedModel` has the same label and the
same class as one holding a Bedrock client, and still fingerprints differently, because the
fingerprint reaches through the arm to the binding under it. A manifest edited between the
preflight and the drive changes `manifest_sha`. A run redirected to another `run_id` or another
output root changes those.

### It is single-use

`claim()` refuses a second claim. One preflight authorises one scored run; a capability that could
authorise two would let a session that disliked the first buy a second under the first one's
preflight. A refused claim does **not** spend it, so a run rejected for the wrong run id has not
consumed the preflight that authorised it.

Resume is unaffected, and this is the point worth being careful about: a resume is a fresh
invocation of `run.execute`, which runs a fresh preflight — including `output_directory`, which is
already the check that a resumable directory is the same experiment — and mints a fresh capability
for the same run id. Attempts already captured are still skipped, verdicts already written are
still not re-driven, and the retry-once-for-a-void policy is untouched.

### A development run takes no capability, and is refused one

The harness stays usable during the work that prepares a scored run: `drive(kind="development")`
needs nothing and behaves exactly as before. Handing it a scored capability is an error rather
than a no-op, because that is the one way a scored capability could be spent on something that is
not a scored run.

### Nothing about the capability is persisted

The capability is authority, not evidence. Its digests reach no capture, and its fingerprint is
made of addresses, model ids, regions and hashes — the same material
`BindingConfig.as_payload()` is allowed to write — so no credential could reach one even if one
were written. `test_a_scored_capture_carries_no_capability_and_no_digest` asserts that no file a
scored run writes contains either digest.

## What was proved, without running `SUR-1`

75 tests across `scripts/tests/test_sur1_authorisation.py` (42) and the scored-boundary additions
to `test_sur1_driver.py`, all beneath the directory's existing `conftest.py`, which raises on any
connection that is not loopback.

| Proof | Where |
|---|---|
| A capability cannot be constructed | `test_sur1_authorisation.py::test_a_capability_cannot_be_constructed` |
| An object shaped like a report cannot mint | `…::test_only_a_preflight_report_mints` |
| A failed preflight cannot mint | `…::test_a_failed_preflight_cannot_mint` |
| One failed check among eleven cannot mint | `…::test_one_failed_check_among_many_cannot_mint` |
| A partial report cannot mint | `…::test_a_partial_report_cannot_mint` |
| A development preflight cannot mint | `…::test_a_development_preflight_cannot_mint` |
| `REQUIRED_CHECKS` is what the preflight actually asks | `…::test_the_required_checks_are_the_questions_the_preflight_actually_asks` |
| The fingerprint binds every frozen identity | `…::test_the_fingerprint_binds_every_frozen_identity` |
| The fingerprint binds the world-program freeze | `…::test_the_fingerprint_binds_the_world_program_freeze` |
| Any one moved input invalidates the capability | `…::test_one_moved_input_invalidates_the_capability`, parametrised over thirteen |
| A matching fingerprint is claimed exactly once | `…::test_a_matching_fingerprint_is_claimed_exactly_once` |
| A refused claim does not spend the capability | `…::test_a_refused_claim_does_not_spend_the_capability` |
| A capability minted against a real world cannot drive a double | `…::test_a_capability_minted_against_a_real_world_cannot_drive_a_double` |
| The same arm holding a scripted model fingerprints differently | `…::test_the_same_arm_holding_a_scripted_model_fingerprints_differently` |
| A scored directory is not opened without a capability | `…::test_a_scored_directory_is_not_opened_without_a_capability` |
| A capability about another run or root is refused | `…::test_a_scored_directory_refuses_a_capability_about_another_run`, `…another_root` |
| A development directory still opens with none | `…::test_a_development_directory_still_opens_with_no_capability` |
| Each scored-artefact path has exactly one caller | `…::test_one_module_calls_each_scored_artefact_path`, parametrised over seven names |
| The sentinel and the report check are in different modules | `…::test_nothing_in_the_package_can_mint_without_the_report_check` |
| The boundary moved no frozen identity | `…::test_the_boundary_moved_no_frozen_identity` |
| `drive(kind="scored")` refuses and writes nothing | `test_sur1_driver.py::test_a_scored_run_refuses_to_start_without_an_authorisation` |
| An authorised scored run starts | `…::test_a_declared_rule_and_an_authorisation_let_a_scored_run_start` |
| An authorised scored run retries a void exactly once | `…::test_an_authorised_scored_run_retries_a_void_exactly_once` |
| An authorised scored run resumes under a second capability | `…::test_an_authorised_scored_run_resumes_under_a_second_capability` |
| A scored capture carries no capability and no digest | `…::test_a_scored_capture_carries_no_capability_and_no_digest` |
| A development run is refused a scored capability | `…::test_a_development_run_is_refused_a_scored_authorisation` |

The two synthetic minting helpers — one in each test module — build a passing report by hand and
still have to go through `authorise` to turn it into authority. That forgery is deliberate and is
itself part of the proof: **nothing in the shipped package can do what those helpers do.**

## What this does not claim

- **It is not a defence against a determined author.** Python has no private members. A session
  that imported `authorisation._grant` and forged a fingerprint would mint a capability. What the
  boundary removes is the *accident*: reaching a scored artefact by calling a public function with
  a string, which is how this would actually have happened.
- **It does not verify that the preflight's answers were true**, only that a report which asked
  every question and passed every one is what minted the capability, and that the inputs it was
  about are the inputs being driven.
- **It asks no new question.** The eleven checks are the eleven that were already there. This
  slice changed who has to have asked them, not what they are.

## What was not done

- **No `SUR-1` run was taken.** No arm was driven at a scenario, no world was prepared, no
  comparative number exists. `BASELINE`, `PROMISEPATCH` and `ABLATION` were not run.
- **No model was called.** No Bedrock, no OpenAI, no NVIDIA. No AWS resource was read or mutated.
  `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` remains unspent.
- **No capability has been minted against real bindings.** Every one that exists was minted inside
  a test, from a report that test wrote, against values that reach nothing.
- **No frozen document was edited.** The manifest, the baseline prompt, the scorer, the
  predeclaration and the nine world programs are byte-for-byte what they were, and their published
  hashes still verify — asserted by `test_the_boundary_moved_no_frozen_identity`.
- **No production file was changed.** Nothing under `packages/`, `apps/`, `evals/` or `deploy/`.
- **No Docker service was started** and no database was reached.
- **The effect sets are untouched.** `11/16` stands and `S12` stays committed failing.
- **This sits outside the gate structure.** `G8` is the open gate; this is not one of its required
  artifacts and should not be counted as one.

## What still stands between here and a dress rehearsal

Unchanged by this slice, and restated so the boundary is not mistaken for readiness:

1. **A prepared environment.** The local stack on its published ports, a worker credential, an MCP
   bearer token, a readable order-system event log and a region. Preflight checks `configuration`
   and `receivers` are what say whether it is there.
2. **A model this account can invoke**, and the spend authorisation, which is unspent.
3. **A rehearsal that is not a scored run.** Nothing has yet driven an arm at a prepared world,
   under any `kind`. The capability gates the scored path; it does not shorten the development
   path that has to come first.
4. **A different session.** The contract's freeze block is explicit that the building session is
   not the scoring session.
