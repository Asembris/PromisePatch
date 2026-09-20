"""Three arms, one interface, and the one place each of them is allowed to differ.

The comparative claim rests on the three arms being given the same world, the same facts and the
same ceilings. That is a property of this harness, so it is asserted here: the adapters satisfy
one protocol, the baseline gets the frozen prompt as the bytes on disk, arms B and C go through
the worker surface and nothing privileged, and arm C differs from arm B by exactly one context
manager.

Every model here is a script in a list. Nothing calls Bedrock, nothing opens a socket -- the
directory's own guard refuses an off-machine connection -- and no ``SUR-1`` scenario is executed
against a real world.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from scripts.sur1.ablation import installed_evaluator
from scripts.sur1.adapters import (
    ARGUMENTS,
    KICKOFF,
    AblationArm,
    BaselineArm,
    PromisePatchArm,
    three_arms,
    tool_specifications,
)
from scripts.sur1.arms import ArmAdapter, AttemptRequest, HarnessFailureError, ModelReply
from scripts.sur1.budget import AttemptBudget, BudgetExhaustedError
from scripts.sur1.doubles import FakeClock, ScriptedModel, ScriptedSurface, SyntheticWorld
from scripts.sur1.evidence import ReceiverEvidence, TaskSample
from scripts.sur1.frozen import PROMPT_PATH, PUBLISHED_PROMPT_SHA, Contract, prompt_sha
from scripts.sur1.manifest import AttemptIdentity

CONTRACT = Contract.load()

EVIDENCE = ReceiverEvidence(tasks=(TaskSample("task-ol-a", "ord-a", "SCHEDULED", "SCHEDULED"),))


def request_for(world: SyntheticWorld, *, clock: FakeClock | None = None) -> AttemptRequest:
    return AttemptRequest(
        identity=AttemptIdentity("run-1", "tok-opaque", "C01", 1),
        scenario={"id": "C01", "stipulated_facts": ["a stipulated fact"]},
        contract=CONTRACT,
        budget=AttemptBudget(ceilings=CONTRACT.ceilings, clock=clock or FakeClock()),
        world=world,
    )


def calling(name: str, **arguments: object) -> ModelReply:
    return ModelReply(text="", tool_calls=({"name": name, "arguments": arguments},))


# --------------------------------------------------------------------------- one interface


def test_all_three_arms_satisfy_one_adapter_protocol() -> None:
    arms = three_arms(model=ScriptedModel([]), surface=ScriptedSurface([]))
    assert [arm.label for arm in arms] == ["BASELINE", "PROMISEPATCH", "ABLATION"]
    for arm in arms:
        assert isinstance(arm, ArmAdapter)
        assert callable(arm.run)


def test_the_two_promisepatch_arms_share_one_implementation() -> None:
    """Composition, so 'drive PromisePatch' cannot drift into being two things."""
    _, promisepatch, ablated = three_arms(model=ScriptedModel([]), surface=ScriptedSurface([]))
    assert isinstance(ablated, AblationArm)
    assert ablated.inner is promisepatch


# ------------------------------------------------------------------ the frozen prompt, exactly


def test_the_baseline_is_handed_the_frozen_prompt_as_the_bytes_on_disk() -> None:
    model = ScriptedModel([calling("report_outcome")])
    world = SyntheticWorld(evidence=EVIDENCE)
    BaselineArm(model=model).run(request_for(world))

    system = model.systems_seen[0]
    assert system == PROMPT_PATH.read_text(encoding="utf-8")
    assert prompt_sha(system) == PUBLISHED_PROMPT_SHA


def test_the_baseline_prompt_is_never_supplemented_with_a_scenario_fact() -> None:
    """A per-scenario addition would be an edit of the baseline by another name."""
    model = ScriptedModel([calling("report_outcome")])
    world = SyntheticWorld(evidence=EVIDENCE)
    request = request_for(world)
    BaselineArm(model=model).run(request)

    system = model.systems_seen[0]
    for fact in request.stipulated_facts:
        assert fact not in system
    first_turn = model.calls[0]["messages"][0]
    assert first_turn == {"role": "user", "content": KICKOFF}


def test_the_kickoff_is_identical_for_every_scenario_and_carries_no_fact() -> None:
    assert KICKOFF == "Begin."
    for scenario_id in CONTRACT.scenario_ids:
        assert scenario_id not in KICKOFF


def test_the_tool_descriptions_are_the_contract_s_own_words() -> None:
    world = SyntheticWorld()
    specifications = tool_specifications(request_for(world))
    assert [spec["name"] for spec in specifications] == [
        *CONTRACT.read_tools,
        *CONTRACT.write_tools,
    ]
    surface = CONTRACT.document["tool_surface"]
    assert specifications[0]["description"] == surface["reads"][0]["returns"]
    assert specifications[-1]["description"] == surface["writes"][-1]["contract"]
    assert set(ARGUMENTS) == {*CONTRACT.read_tools, *CONTRACT.write_tools}


# --------------------------------------------------------------------------- the agent loop


def test_the_baseline_acts_on_the_world_and_ends_at_its_report() -> None:
    model = ScriptedModel(
        [
            calling("get_incident"),
            calling("amend_order", external_id="EXT-A", expected_version=1),
            calling("report_outcome"),
        ]
    )
    world = SyntheticWorld(evidence=EVIDENCE, responses={"get_incident": {"reported": "hi"}})
    attempt = BaselineArm(model=model).run(request_for(world))

    assert [name for name, _ in world.invoked] == ["get_incident", "amend_order", "report_outcome"]
    assert attempt.evidence == EVIDENCE


def test_every_model_call_and_every_tool_call_is_charged_to_the_shared_ledger() -> None:
    model = ScriptedModel([calling("get_orders"), calling("report_outcome")])
    world = SyntheticWorld(evidence=EVIDENCE)
    request = request_for(world)
    BaselineArm(model=model).run(request)
    assert request.budget.spend.model_calls == 2
    assert request.budget.spend.tool_calls == 2


def test_the_baseline_cannot_outlast_the_model_call_ceiling() -> None:
    """A model that never reports is ended by the ledger, not by a number this arm holds."""
    chatter = [ModelReply(text="thinking") for _ in range(CONTRACT.ceilings.model_calls + 5)]
    request = request_for(SyntheticWorld(evidence=EVIDENCE))
    with pytest.raises(BudgetExhaustedError) as exhausted:
        BaselineArm(model=ScriptedModel(chatter)).run(request)
    assert exhausted.value.dimension == "model_calls"
    assert request.budget.spend.model_calls == CONTRACT.ceilings.model_calls


def test_reported_usage_is_charged_as_the_provider_reports_it() -> None:
    model = ScriptedModel(
        [
            ModelReply(
                text="",
                tool_calls=({"name": "report_outcome"},),
                input_tokens=900,
                output_tokens=40,
            )
        ]
    )
    request = request_for(SyntheticWorld(evidence=EVIDENCE))
    BaselineArm(model=model).run(request)
    assert request.budget.spend.input_tokens == 900
    assert request.budget.spend.output_tokens == 40


def test_the_baseline_records_every_tool_call_it_made_as_diagnostics() -> None:
    """Captured, never scored. Without it the empty-``E4`` mechanism could only be guessed at."""
    model = ScriptedModel(
        [
            calling("get_incident"),
            calling("send_customer_message", channel_address="1002", text="may we?"),
            calling("report_outcome"),
        ]
    )
    world = SyntheticWorld(evidence=EVIDENCE, responses={"get_incident": {"reported": "hi"}})

    attempt = BaselineArm(model=model).run(request_for(world))

    assert [call["name"] for call in attempt.diagnostics["tool_calls"]] == [
        "get_incident",
        "send_customer_message",
        "report_outcome",
    ]
    assert attempt.diagnostics["tool_calls"][1]["arguments"] == {
        "channel_address": "1002",
        "text": "may we?",
    }


def test_the_baseline_s_report_argument_is_kept_in_full_structure() -> None:
    """The one argument the audit could not read from the artefacts."""
    report = {"scenario_id": "C01", "exception_recorded": True, "promises": [{"order": "ord-a"}]}
    model = ScriptedModel([calling("report_outcome", report=report)])
    world = SyntheticWorld(evidence=EVIDENCE)

    attempt = BaselineArm(model=model).run(request_for(world))

    (call,) = attempt.diagnostics["tool_calls"]
    assert call["arguments"]["report"] == report


def test_a_diagnostic_is_bounded_so_a_capture_cannot_become_a_transcript_dump() -> None:
    from scripts.sur1.adapters import TEXT_CEILING, WIDTH_CEILING, sanitised

    long_text = "x" * (TEXT_CEILING + 50)
    assert sanitised(long_text).endswith("[... cut]")
    assert len(sanitised(long_text)) == TEXT_CEILING + len("[... cut]")

    wide = list(range(WIDTH_CEILING + 5))
    assert sanitised(wide)[-1] == "[5 more entries]"

    from scripts.sur1.adapters import DEPTH_CEILING

    deep: Any = "bottom"
    for _ in range(DEPTH_CEILING + 2):
        deep = {"down": deep}
    assert "depth ceiling" in str(sanitised(deep))


def test_diagnostics_are_written_into_the_capture_and_never_into_a_bundle() -> None:
    """The structural reason an arm-identifying record may exist at all."""
    import inspect

    from scripts.sur1.evidence import blind_bundle

    assert "diagnostics" not in inspect.signature(blind_bundle).parameters


# ------------------------------------------------------------------ the ordinary surfaces


def test_promisepatch_is_driven_through_the_worker_surface_and_nothing_else() -> None:
    surface = ScriptedSurface(
        script=[
            {"needs": "clarification", "question": "which line?"},
            {"needs": "confirmation", "plan_id": "plan-7"},
            {"needs": None},
        ],
        status_payload={"promises": []},
    )
    world = SyntheticWorld(
        evidence=EVIDENCE,
        responses={
            "get_incident": {
                "reported": "no raspberries",
                "clarification": {"question": "which line?", "answer": "just those"},
            }
        },
    )
    request = request_for(world)
    attempt = PromisePatchArm(surface=surface).run(request)

    assert [verb for verb, _ in surface.seen] == [
        "report_exception",
        "answer_clarification",
        "confirm_plan",
        "status",
    ]
    assert surface.seen[0][1] == "no raspberries"
    assert surface.seen[1][1] == "just those"
    assert surface.seen[2][1] == "plan-7"
    assert attempt.evidence == EVIDENCE


def test_promisepatch_reads_the_incident_from_the_same_tool_the_baseline_does() -> None:
    """Identical facts, from one read, so 'the same world' is structural."""
    surface = ScriptedSurface(script=[{"needs": None}])
    world = SyntheticWorld(evidence=EVIDENCE, responses={"get_incident": {"reported": "spoiled"}})
    PromisePatchArm(surface=surface).run(request_for(world))
    assert world.invoked[0][0] == "get_incident"


def test_an_incident_nobody_reported_is_a_harness_failure_and_not_a_verdict() -> None:
    world = SyntheticWorld(evidence=EVIDENCE, responses={"get_incident": {}})
    with pytest.raises(HarnessFailureError, match="no arm can be driven"):
        PromisePatchArm(surface=ScriptedSurface([])).run(request_for(world))


def test_the_worker_surface_conversation_is_charged_to_the_ledger() -> None:
    surface = ScriptedSurface(script=[{"needs": None}])
    world = SyntheticWorld(evidence=EVIDENCE, responses={"get_incident": {"reported": "x"}})
    request = request_for(world)
    PromisePatchArm(surface=surface).run(request)
    assert request.budget.spend.tool_calls == 3
    assert request.budget.spend.model_calls == 0


# ----------------------------------------------------------------------------- arm C is arm B


def test_the_ablated_arm_does_exactly_what_the_full_arm_does_plus_a_log() -> None:
    """Same conversation, same reads, same evidence. The difference is the dropped check."""

    def drive(build: str) -> tuple[list[tuple[str, str]], list[tuple[str, Mapping[str, Any]]]]:
        surface = ScriptedSurface(
            script=[{"needs": "confirmation", "plan_id": "p1"}, {"needs": None}]
        )
        world = SyntheticWorld(evidence=EVIDENCE, responses={"get_incident": {"reported": "x"}})
        inner = PromisePatchArm(surface=surface)
        arm = inner if build == "full" else AblationArm(inner=inner)
        attempt = arm.run(request_for(world))
        assert attempt.evidence == EVIDENCE
        return surface.seen, world.invoked

    full_seen, full_invoked = drive("full")
    ablated_seen, ablated_invoked = drive("ablated")
    assert full_seen == ablated_seen
    assert full_invoked == ablated_invoked


def test_the_ablated_arm_records_which_check_it_dropped() -> None:
    surface = ScriptedSurface(script=[{"needs": None}])
    world = SyntheticWorld(evidence=EVIDENCE, responses={"get_incident": {"reported": "x"}})
    attempt = AblationArm(inner=PromisePatchArm(surface=surface)).run(request_for(world))
    assert attempt.diagnostics["ablated_check"] == 5
    assert attempt.diagnostics["ablation"] == []


def test_the_full_arm_carries_no_ablation_diagnostics() -> None:
    surface = ScriptedSurface(script=[{"needs": None}])
    world = SyntheticWorld(evidence=EVIDENCE, responses={"get_incident": {"reported": "x"}})
    attempt = PromisePatchArm(surface=surface).run(request_for(world))
    assert attempt.diagnostics == {}


def test_the_ablation_is_installed_only_while_arm_c_is_running() -> None:
    original = installed_evaluator()
    seen: list[object] = []

    class Watching(ScriptedSurface):
        def status(self) -> dict[str, object]:
            seen.append(installed_evaluator())
            return {}

    surface = Watching(script=[{"needs": None}])
    world = SyntheticWorld(evidence=EVIDENCE, responses={"get_incident": {"reported": "x"}})
    AblationArm(inner=PromisePatchArm(surface=surface)).run(request_for(world))

    assert seen and seen[0] is not original
    assert installed_evaluator() is original


def test_the_incident_arms_b_and_c_read_is_the_one_a_world_program_writes() -> None:
    """The field names, pinned against a real program rather than against a hand-written payload.

    This assertion is the one that was missing. Every test above builds its own ``get_incident``
    payload, so the arms and the world programs could disagree about what an incident is called
    and no test would notice -- which is exactly what happened: the programs wrote ``reported``
    and the arm read ``utterance``, so arms B and C raised ``HarnessFailureError`` on every one
    of the nine scenarios. Reading the shape off a program is what stops that drifting again.
    """
    from scripts.sur1.adapters import CLARIFICATION, REPORTED, clarification_answer
    from scripts.sur1.bindings.programs import programs

    for scenario_id, program in sorted(programs().items()):
        incident = dict(program.incident)
        assert str(incident.get(REPORTED, "")).strip(), f"{scenario_id} reports nothing"
        assert set(incident) <= {REPORTED, CLARIFICATION}, f"{scenario_id} writes a third field"
        block = incident.get(CLARIFICATION)
        if block is None:
            assert clarification_answer(incident) == ""
        else:
            assert clarification_answer(incident) == block["answer"]
            assert clarification_answer(incident) != block["question"]
