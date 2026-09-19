# The `SUR-1` live bindings, and the gate in front of them

**Written. Not run. No arm has been driven, no model has been reached, no AWS resource read, and
no comparative number exists.**

[`sur1-execution-harness.md`](sur1-execution-harness.md) closes with its own largest declared gap:

> **The live bindings were not written**, and this is the harness's largest declared gap. The
> ports `ModelClient`, `ScenarioWorld` and `WorkerSurface` are defined and exercised against
> doubles; the concrete bindings — a `bedrock-runtime` Converse client, a scenario world that
> applies stipulated facts to a clean Hollow Oak fixture and reads the four receivers back, and an
> MCP/workspace client for arms B and C — belong to the execution session.

This document records those bindings, the scored-run preflight in front of them, and the one gap
that remains after them.

| | |
|---|---|
| Package | `scripts/sur1/bindings/`, plus `scripts/sur1/preflight.py` and `scripts/sur1/run.py` |
| Predeclaration | [`benchmarks/sur1-execution-predeclaration.v1.md`](benchmarks/sur1-execution-predeclaration.v1.md), rules SHA `c53d267a…1d1e1927` |
| Benchmark | `SUR-1` v1.0.0, manifest SHA `5718340f…e70e84c`, **unchanged** |
| Scorer | `scripts/score_safe_useful_recovery.py` v1.0.0, **unchanged** |
| Runs taken | **none** |

## The three bindings

| Port | Binding | Reaches |
|---|---|---|
| `ModelClient` | `bindings/bedrock.py::BedrockConverseClient` | `bedrock-runtime` Converse, at the frozen model id and temperature |
| `WorkerSurface` | `bindings/promisepatch.py::LiveWorkerSurface` | the MCP endpoint and the workspace a worker signs in to |
| `ScenarioWorld` | `bindings/world.py::LiveScenarioWorld` | the order system, the customer channel and the kitchen |

Each declares `binding_kind = "real"`. `scripts/sur1/doubles.py` declares nothing, which is how
the preflight refuses a scored run driven by a stand-in rather than trusting a caller to have
passed the right object — checked by value and not by protocol, because a runtime-checkable
protocol only asks whether the members exist.

### Arm A — the model

The provider, the model id, the API and the temperature are read out of the frozen manifest after
its hash is asserted; the output ceiling is read out of the same document's budget block. There is
no literal in the request builder that a contract change would fail to move.

`build_converse_request` is **pure**, which is what makes "the binding sends what the contract
says" evidence rather than intent: the exact payload — `modelId`, the system block, the turns, the
tool config, `temperature` and `maxTokens` — is asserted in a test with no AWS account, no
credential and no socket. The client opens its boto3 transport on first use and never at
construction, so importing this module on a machine with no AWS configuration succeeds.

The eleven frozen actions are published as Converse tool specifications with every argument
required and **no `toolChoice`**: the baseline is an agent deciding what to do, and forcing a tool
would be the harness deciding for it.

### Arms B and C — ordinary product surfaces, and nothing else

Two surfaces. The **MCP endpoint** over Streamable HTTP through the official client SDK, carrying
a bearer credential — the five frozen tools and no sixth. The **workspace**, where a worker signs
in with their own credential and approves a plan.

The workspace half is there because of [ADR-0018](adr/0018-a-plan-confirmation-spends-a-human-approval.md)
and it is not a convenience. A confirmation *spends* a durable human approval it cannot write, so
an arm holding only a service credential could never get past a plan — not because the harness is
missing a shortcut, but because the product refuses one. The arm therefore does what a worker
does: `POST /api/conversation/approve` on the surface this system authenticated them on, then MCP
`confirm` to carry it out. `test_a_confirmation_is_preceded_by_the_worker_s_own_approval` asserts
the order.

`test_the_promisepatch_arm_touches_only_the_five_mcp_tools_and_the_workspace_approval` records
every call the surface made and asserts the set, rather than asserting it by reading the code.

**Waiting is not an action.** PromisePatch works in a durable worker, so the binding polls
`status` until the case asks for something or three consecutive readings are identical. Those
polls are the transport waiting for the product; they are **not** frozen actions and are not
charged against the tool-call ceiling, which counts the eleven the contract froze. The attempt's
wall-clock ceiling bounds them.

**Arm C is arm B's own object inside one context manager.** `three_arms()` builds one
`PromisePatchArm` and hands it to `AblationArm`, so "drive PromisePatch" has exactly one
implementation. `test_the_ablated_arm_drives_the_same_binding_and_adds_only_its_log` drives both
against one script and asserts the MCP calls and the world reads are identical and that the only
difference is arm C's ablation diagnostics.

### The world, and the four receivers

`LiveScenarioWorld` is one object for every arm in a run, which is what makes *the same world* a
fact about the harness rather than a claim about three setups. It performs the eleven frozen
actions and reads E1 through E4 back.

`get_promise_graph`, `get_stock` and `get_tasks` read the fixture's own rows for whoever asks. The
contract is explicit that the baseline is denied PromisePatch's deterministic machinery and **not**
the domain — *an agent that did not know the wedding customer had refused substitution would be
measuring ignorance rather than architecture.*

E4 has the two sources the contract names: an arm with a `report_outcome` call is reported by that
call, and arms B and C are *projected from `status_view`* under the rule declared in the
predeclaration.

Two disclosed discrepancies are recorded in
[the predeclaration](benchmarks/sur1-execution-predeclaration.v1.md#3--two-discrepancies-between-the-frozen-contract-and-the-systems-it-names)
rather than repaired in the frozen document: E1 is read from the order system's own committed
event log because `GET /admin/events` publishes none of the three fields rule `B2` depends on, and
the harness's channel ledger is a second *transport* for arm A's outbound messages and never a
second protocol. **The order simulator was not modified**; adding a read endpoint for this
measurement would break the contract's own promise that no production file changes for it.

## The scored-run preflight

Eleven checks, asked before an arm is constructed, a world is prepared or a transport is opened.
Nine were asked when this record was written; `world_program_freeze` and `event_blinding` arrived
with the world programs and the armed events.

| # | check | refuses when |
|---:|---|---|
| 1 | `frozen_identities` | the manifest, the prompt or the scorer has moved |
| 2 | `real_bindings` | any binding is a stand-in |
| 3 | `model_identity` | the model is not the contract's, or names no region |
| 4 | `configuration` | a required credential or address is unset |
| 5 | `receivers` | a receiver does not answer |
| 6 | `classifier_identity` | the rule is undeclared, is not the declared one, or has moved |
| 7 | `world_programs` | a selected scenario cannot be prepared |
| 8 | `world_program_freeze` | the programs are not the frozen nine at their published digests |
| 9 | `output_directory` | the directory is neither new nor a resumable run of this experiment |
| 10 | `blinding` | an arm name is reachable from a bundle or from the scorer |
| 11 | `event_blinding` | a world event's firing path can name an arm, an answer or a reading |

The names are pinned as `preflight.REQUIRED_CHECKS`, which is what a scored authorisation refuses
to be minted without.

**It reads and never writes.** It opens clients and recomputes hashes; it creates no run
directory, mints no token, prepares no world and calls no model. Invoking the model to find out
whether the model can be invoked would spend exactly the thing it exists to protect.

**It does not short-circuit.** A caller fixing a run wants every reason it was refused, not the
first one.

`scripts/sur1/run.py` is the one place a run is composed, and it exists so the preflight cannot be
the optional step: `execute()` refuses a failed scored run **before** `drive()` is called, which
`test_a_scored_run_never_reaches_the_driver_when_a_precondition_is_false` asserts by making the
driver an alarm. A development run is reported and permitted — refusing one would make the harness
unusable during the work that prepares a scored run.

```bash
uv run python -m scripts.sur1.run --run-id <id> --preflight
```

**The boundary this leaves, named rather than implied.** `driver.drive()` is still callable
directly, and called that way it enforces only what it always did — the frozen identities, and its
refusal of a scored run under an undeclared rule. It is not given the bindings and cannot ask the
other seven questions. Tightening it to demand a passing preflight would mean either coupling the
driver to the bindings package or duplicating the check somewhere it could only be approximate, so
the gate lives in one place and `run.py` is the way a run is taken. A caller who imports the
driver and bypasses `run.py` has bypassed the preflight, and that is a fact about the entry point
rather than a property of the gate.

> **Since closed, and by neither of those two means.** A passing scored preflight now returns a
> capability bound to the inputs it checked, and `drive()` and `open_run()` ask for the object.
> The driver did not gain a dependency on the bindings package and the checks were not duplicated:
> it re-observes a fingerprint from the objects it was handed and claims the capability against it,
> once. `driver.drive()` stays callable for development and for the tests that prove its rules;
> what it stopped being able to do is produce a scored artefact around the preflight. See
> [`sur1-scored-authorisation.md`](sur1-scored-authorisation.md).

## How this was validated without consuming `SUR-1`

Four new modules under `scripts/tests/`, 101 tests, beneath the directory's existing `conftest.py`,
which intercepts every outbound connection and **raises on anything that is not loopback**.

| Proof | Where |
|---|---|
| The Converse request is the frozen configuration, built without a network | `test_sur1_bedrock_binding.py::test_the_request_carries_the_frozen_model_temperature_and_output_ceiling` |
| The eleven actions are published and none is forced | `…::test_the_tool_config_publishes_the_eleven_frozen_actions_and_forces_none_of_them` |
| A tool result is paired to the call it answers | `…::test_a_tool_result_is_paired_to_the_call_it_answers` |
| A malformed envelope reads as an empty answer | `…::test_a_malformed_envelope_reads_as_an_empty_answer_rather_than_raising` |
| Arms B and C touch only ordinary surfaces | `test_sur1_live_bindings.py::test_the_promisepatch_arm_touches_only_the_five_mcp_tools_and_the_workspace_approval` |
| The approval precedes the confirmation | `…::test_a_confirmation_is_preceded_by_the_worker_s_own_approval` |
| B and C differ only by the ablation | `…::test_the_ablated_arm_drives_the_same_binding_and_adds_only_its_log` |
| E1 carries the command key the HTTP projection does not | `…::test_the_order_receiver_reads_the_command_key_the_http_projection_does_not_publish` |
| A pre-incident external change is not an arm's effect | `…::test_an_event_before_the_attempt_started_is_not_read_as_this_attempt_s_effect` |
| A partial task sample is not a reading | `…::test_a_task_sampled_once_is_left_out_rather_than_given_a_state` |
| Receiver evidence projects to a blind bundle | `…::test_receiver_evidence_projects_to_a_bundle_that_carries_a_token_and_no_arm` |
| `asserts_change` is deterministic, arm-blind and fails closed | `test_sur1_predeclaration.py`, six tests |
| A moved rule refuses the run | `test_sur1_preflight.py::test_a_moved_rule_refuses_the_run_even_though_the_function_is_the_declared_one` |
| Each missing credential refuses the run | `…::test_a_missing_credential_or_address_refuses_the_run`, parametrised over all six |
| A scored run refuses a stand-in | `…::test_a_stand_in_cannot_drive_a_scored_run` |
| A preflight opens no run directory | `…::test_the_preflight_opens_no_run_directory` |
| A refused scored run never reaches the driver | `test_sur1_run.py::test_a_scored_run_never_reaches_the_driver_when_a_precondition_is_false` |
| A refused scored run writes nothing | `…::test_a_refused_scored_run_writes_nothing_at_all` |
| Write-once still refuses to edit a capture | `…::test_write_once_still_refuses_to_edit_a_capture` |

The receiver tests read a temporary SQLite file shaped exactly like the simulator's own
`order_events` table. No `docker compose` service was started for any of them, no PostgreSQL was
reached, and no run landed anywhere but `tmp_path`.

## What remains before a real `SUR-1` run

1. **The nine world programs.** Each scenario's stipulated facts are English sentences in the
   frozen contract and there is no machine-readable form of them.
   `bindings/setup.py::PROGRAMS` is empty, `program_for` refuses, and preflight check 7 refuses a
   scored run for any scenario in that state. **This is deliberately not done here**: a program
   written in the session that also built the scoring path, with the scenario's ground truth
   visible, is not distinguishable from one written towards it.
2. **A prepared environment.** The local stack up on its published ports, a worker credential, an
   MCP bearer token, a readable order-system event log and a region. Preflight checks 4 and 5 are
   what say whether it is there.
3. **A model this account can invoke**, and the spend authorisation
   `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE`, which is unspent.
4. **A different session.** The contract's freeze block is explicit that the building session is
   not the scoring session. This session built bindings and a gate. It did not score.

## What was not done

- **No comparative run was taken.** No arm was driven at a `SUR-1` scenario, no `EvidenceBundle`
  collected from a real attempt, and no number comparing any two arms exists.
- **No model was called.** No Bedrock, no OpenAI, no NVIDIA. No AWS resource was read or mutated.
  `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` remains unspent.
- **No frozen document was edited.** The manifest, the baseline prompt and the scorer are
  byte-for-byte what they were, and `verify_safe_useful_recovery.py` still recomputes both hashes.
- **No production file was changed.** Nothing under `packages/`, `apps/`, `evals/` or `deploy/`.
  The order simulator gained no endpoint for this measurement.
- **No scenario was tuned, prepared or authored.** The nine world programs do not exist.
- **The effect sets are untouched.** `11/16` stands, the manifest hash is unchanged, `S12` stays
  committed failing.
- **Both evaluation holdouts stay sealed**, and neither was consulted.
- **No service was started and nothing was deployed.** No `docker compose` service was brought up
  for this work.
- **This work sits outside the gate structure.** `G8` is the open gate and this is not one of its
  required artifacts. It should not be counted as one.
