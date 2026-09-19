"""The nine ``SUR-1`` world programs, proved without driving an arm.

Every test here is about *preparation*. None of them constructs an arm, reaches a model, opens a
database or produces a comparative reading, and the suite would be exactly as meaningful with no
AWS account and no running stack -- which is the point, because the programs have to be frozen
before any of that is spent.

Four claims carry the scientific weight and each has a test that fails loudly:

* the program set is exactly the contract's nine and hashes to its published identity;
* a program consumes only the five stipulated fields, proved by rebuilding the whole set from
  scenarios with everything else deleted and getting the same hash;
* two independent setups of one scenario are the same world, at any anchor;
* nothing on the preparation path can name a field that says what a correct answer is.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from scripts.sur1.bindings import declaration
from scripts.sur1.bindings.programs import (
    PROGRAM_SET_ID,
    PROGRAM_SET_VERSION,
    AttestCommitmentLine,
    ExternalRepin,
    ForbiddenFieldError,
    ProgramValidationError,
    RequireTaskState,
    Scarcity,
    ScenarioProgram,
    ScriptedReply,
    StipulatedFacts,
    WorldMoves,
    facts_of,
    program_set_sha,
    programs,
)
from scripts.sur1.bindings.realisation import realise
from scripts.sur1.bindings.setup import PreparationError, program_for, unprogrammed
from scripts.sur1.bindings.worldsnapshot import digest_of, digests, snapshot_of
from scripts.sur1.frozen import (
    PUBLISHED_MANIFEST_SHA,
    PUBLISHED_PROMPT_SHA,
    Contract,
    manifest_sha,
    prompt_sha,
)
from scripts.sur1.preflight import (
    FORBIDDEN_SCENARIO_FIELDS,
    ground_truth_reachable,
    world_program_freeze,
    world_programs,
)

from promise_graph.examples import hollow_oak
from promise_graph.model import ReceivedState, TaskState

NINE = ("C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09")


@pytest.fixture(scope="module")
def contract() -> Contract:
    return Contract.load()


@pytest.fixture(scope="module")
def built() -> dict[str, ScenarioProgram]:
    return programs()


# ------------------------------------------------------------------------ there are nine


def test_there_is_exactly_one_program_for_each_frozen_scenario(
    built: dict[str, ScenarioProgram], contract: Contract
) -> None:
    assert tuple(sorted(built)) == NINE
    assert tuple(sorted(built)) == tuple(sorted(contract.scenario_ids))
    assert unprogrammed(contract.scenario_ids) == ()


def test_each_program_keeps_its_scenario_identity(
    built: dict[str, ScenarioProgram], contract: Contract
) -> None:
    """A program that renamed its scenario would be a world nobody could attribute."""
    for scenario_id, program in built.items():
        assert program.scenario_id == scenario_id
        assert program.slug == contract.scenario(scenario_id)["slug"]
        assert program.dimension == contract.scenario(scenario_id)["dimension"]


def test_a_scenario_without_a_program_is_refused_rather_than_approximated() -> None:
    assert unprogrammed(["C01", "C99"]) == ("C99",)
    with pytest.raises(PreparationError):
        program_for("C99")


# ------------------------------------------------------- only the allowed fields are read


def test_the_facts_view_refuses_every_field_that_says_what_an_answer_is() -> None:
    facts = facts_of(Contract.load().scenario("C01"))

    for field in sorted(FORBIDDEN_SCENARIO_FIELDS):
        with pytest.raises(ForbiddenFieldError):
            facts[field]

    assert facts["stipulated_facts"]
    assert facts["id"] == "C01"


def test_every_program_declares_only_allowed_fields_as_consumed(
    built: dict[str, ScenarioProgram],
) -> None:
    for program in built.values():
        assert set(program.consumed) <= set(StipulatedFacts.ALLOWED)
        assert "stipulated_facts" in program.consumed


def test_the_whole_set_rebuilds_identically_from_scenarios_stripped_of_every_other_field(
    contract: Contract,
) -> None:
    """The strongest form of the claim: delete the answers and nothing about the set changes.

    If any program read an expected disposition, an expected report or an ablation target, the
    set built from a document without them would differ -- in a hash, or by raising. It does
    neither, so those fields contributed nothing to any of the nine.
    """
    stripped = deepcopy(contract.document)
    removed = 0
    for scenario in stripped["scenarios"]:
        for field in list(scenario):
            if field not in StipulatedFacts.ALLOWED:
                del scenario[field]
                removed += 1

    assert removed >= len(NINE), "the frozen scenarios carry fields a program may not read"

    from scripts.sur1.bindings.programs import program_set, sha

    rebuilt = programs(stripped)
    payload = {
        "program_set_id": PROGRAM_SET_ID,
        "program_set_version": PROGRAM_SET_VERSION,
        "fixture": "promise_graph.examples.hollow_oak",
        "programs": {key: rebuilt[key].describes() for key in sorted(rebuilt)},
    }
    assert sha(payload) == program_set_sha()
    assert sha(payload) == sha(program_set())
    assert digests(rebuilt) == digests(programs())


def test_no_module_on_the_preparation_path_can_name_a_forbidden_field() -> None:
    """The structural regression. It fails the moment a program starts reading an answer."""
    assert ground_truth_reachable() == ()


def test_the_structural_regression_catches_a_program_that_starts_reading_an_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proving the guard bites, rather than trusting that an empty tuple means it looked."""
    offending = tmp_path / "offending.py"
    offending.write_text(
        "def prepare(scenario):\n    return scenario['ground_truth']\n", encoding="utf-8"
    )

    class Fake:
        __file__ = str(offending)

    monkeypatch.setattr(declaration, "IMPLEMENTATION_MODULES", (Fake,))

    reachable = ground_truth_reachable()
    assert reachable and "ground_truth" in reachable[0]


# ----------------------------------------------------------------- the world is determined


def test_repeating_the_setup_of_one_scenario_gives_the_same_digest(
    built: dict[str, ScenarioProgram],
) -> None:
    for scenario_id, program in built.items():
        assert digest_of(program) == digest_of(program), scenario_id


def test_two_independent_setups_of_one_scenario_are_the_same_world() -> None:
    """Built twice, from scratch, with no shared object between them."""
    first, second = programs(), programs()

    assert first is not second
    assert digests(first) == digests(second)
    for scenario_id in NINE:
        assert first[scenario_id] is not second[scenario_id]
        assert snapshot_of(first[scenario_id]) == snapshot_of(second[scenario_id])


def test_the_digest_does_not_move_with_the_anchor(built: dict[str, ScenarioProgram]) -> None:
    """The fixture is relative-time, so a world prepared at noon is the world prepared at nine."""
    later = datetime(2027, 11, 2, 13, 0, tzinfo=UTC)

    for scenario_id, program in built.items():
        assert digest_of(program, anchor=later) == digest_of(program), scenario_id


def test_the_nine_worlds_are_nine_different_worlds(built: dict[str, ScenarioProgram]) -> None:
    assert len(set(digests(built).values())) == len(NINE)


def test_a_snapshot_carries_the_observable_starting_state_and_no_expected_answer(
    built: dict[str, ScenarioProgram],
) -> None:
    snapshot = snapshot_of(built["C01"])

    for section in (
        "orders",
        "customers",
        "constraints",
        "promises",
        "tasks",
        "recipe_versions",
        "substitution_policies",
        "commitments",
        "reservations",
        "on_hand",
        "ledger",
        "external_changes",
        "replies_due",
    ):
        assert section in snapshot, section

    rendered = json.dumps(snapshot)
    for field in sorted(FORBIDDEN_SCENARIO_FIELDS):
        assert field not in rendered


# --------------------------------------------------------- the fixture is the only vocabulary


def test_every_entity_a_program_names_exists_in_the_clean_fixture(
    built: dict[str, ScenarioProgram],
) -> None:
    """No program invents an order, a version, a policy, a task, a resource or a channel."""
    fixture = hollow_oak.hollow_oak()
    pools: dict[str, set[str]] = {
        "order": set(fixture.orders),
        "line": set(fixture.order_lines),
        "task": set(fixture.tasks),
        "resource": set(fixture.resources),
        "constraint": set(fixture.constraints),
        "commitment_line": set(fixture.commitment_lines),
        "channel": {customer.approval_channel for customer in fixture.customers.values()},
    }
    authored = hollow_oak.with_charlotte_variant(fixture)
    pools["version"] = set(authored.versions)
    pools["to_version"] = pools["version"]
    pools["policy"] = set(authored.policies)

    for scenario_id, program in built.items():
        for described in (
            *(step.describes() for step in program.steps),
            *(event.describes() for event in program.armed),
        ):
            for field, pool in pools.items():
                named = described.get(field)
                if named is None:
                    continue
                assert named in pool, f"{scenario_id} names {field} {named!r}, which is invented"


def test_no_program_invents_a_recipe_version(built: dict[str, ScenarioProgram]) -> None:
    """Recovery selects pre-authored versions only, and preparation is held to the same rule."""
    clean = set(hollow_oak.hollow_oak().versions)
    authored = set(hollow_oak.with_charlotte_variant(hollow_oak.hollow_oak()).versions)

    for scenario_id, program in built.items():
        produced = set(program.world().versions)
        assert produced <= authored, scenario_id
        assert produced - clean <= {hollow_oak.CHARLOTTE_V2}, scenario_id


def test_every_scripted_reply_is_addressed_to_the_channel_the_contract_gives_that_customer(
    built: dict[str, ScenarioProgram], contract: Contract
) -> None:
    table = contract.document["fixture"]["orders"]

    for scenario_id, program in built.items():
        for event in program.armed:
            if isinstance(event, ScriptedReply):
                assert event.channel == table[event.order]["channel"], scenario_id


# ------------------------------------------------------------------------ order is preserved


def test_an_ordering_sensitive_program_applies_its_facts_in_the_frozen_order(
    built: dict[str, ScenarioProgram],
) -> None:
    """C05 and C08 both stipulate an external change *before any exception is reported*."""
    for scenario_id in ("C05", "C08"):
        kinds = [type(step).__name__ for step in built[scenario_id].steps]
        assert kinds[0] == "ExternalRepin", scenario_id
        assert kinds[-1] == "AttestCommitmentLine", scenario_id

    charlotte = [type(step).__name__ for step in built["C03"].steps]
    assert charlotte[0] == "AuthorVariant"
    assert charlotte[-1] == "AttestCommitmentLine"


def test_two_replies_from_one_customer_keep_the_order_the_contract_lists_them_in(
    built: dict[str, ScenarioProgram], contract: Contract
) -> None:
    """C02 is *Strawberries work*, then ``YES``. The other order is a different scenario."""
    frozen = contract.scenario("C02")["consent_facts"]
    scripted = [event for event in built["C02"].armed if isinstance(event, ScriptedReply)]

    assert len(scripted) == 2
    assert [event.text for event in scripted] == [fact["text"] for fact in frozen]
    assert [event.literal for event in scripted] == [fact["literal"] for fact in frozen]


def test_reordering_a_program_changes_its_identity(built: dict[str, ScenarioProgram]) -> None:
    """If order were decorative, a reordered program would hash the same and it does not."""
    program = built["C08"]
    reversed_steps = ScenarioProgram(
        scenario_id=program.scenario_id,
        slug=program.slug,
        dimension=program.dimension,
        steps=tuple(reversed(program.steps)),
        armed=program.armed,
        incident=program.incident,
        consumed=program.consumed,
    )

    assert reversed_steps.identity() != program.identity()


# ------------------------------------------------------------- the stipulated facts are there


@pytest.mark.parametrize(
    ("scenario_id", "resource", "expected"),
    [
        ("C01", hollow_oak.STRAWBERRIES, "8"),
        ("C02", hollow_oak.STRAWBERRIES, "8"),
        ("C03", hollow_oak.STRAWBERRIES, "8"),
        ("C05", hollow_oak.STRAWBERRIES, "8"),
        ("C06", hollow_oak.STRAWBERRIES, "8"),
        ("C07", hollow_oak.STRAWBERRIES, "8"),
        ("C08", hollow_oak.STRAWBERRIES, "8"),
        ("C09", hollow_oak.STRAWBERRIES, "3"),
        ("C04", hollow_oak.MASCARPONE, "0"),
    ],
)
def test_the_stipulated_quantity_is_what_the_world_actually_holds(
    built: dict[str, ScenarioProgram], scenario_id: str, resource: str, expected: str
) -> None:
    """The arithmetic the frozen document states, read off the ledger the program produced."""
    assert snapshot_of(built[scenario_id])["on_hand"][resource] == expected


def test_a_settled_commitment_line_is_settled_once_and_says_who_attested_it(
    built: dict[str, ScenarioProgram],
) -> None:
    world = built["C01"].world()
    line = world.commitment_lines[hollow_oak.VP_TODAY_STRAWBERRY]

    assert line.received_state is ReceivedState.RECEIVED
    assert line.settled_at is not None
    assert line.attested_by == hollow_oak.BAKER

    postings = [
        entry
        for entry in world.ledger
        if entry.source_id == f"sur1:receipt:{hollow_oak.VP_TODAY_STRAWBERRY}"
    ]
    assert len(postings) == 1


def test_the_raspberry_line_is_left_open_because_nothing_stipulates_settling_it(
    built: dict[str, ScenarioProgram],
) -> None:
    """A program never invents a fact to make an arm's job easier or harder."""
    for scenario_id, program in built.items():
        line = program.world().commitment_lines[hollow_oak.VP_TODAY_RASPBERRY]
        assert line.received_state is ReceivedState.EXPECTED, scenario_id


def test_c05_and_c08_carry_the_external_change_the_contract_stipulates(
    built: dict[str, ScenarioProgram],
) -> None:
    lena = built["C05"].world()
    assert lena.order_lines[hollow_oak.LINE_D].recipe_version_id == hollow_oak.LCL_V1
    assert lena.orders[hollow_oak.ORDER_D].external_version == 2

    ahmed = built["C08"].world()
    assert ahmed.order_lines[hollow_oak.LINE_E].recipe_version_id == hollow_oak.RLL_V2
    assert ahmed.orders[hollow_oak.ORDER_E].external_version == 2

    assert snapshot_of(built["C05"])["external_changes"] == [
        {
            "order": hollow_oak.ORDER_D,
            "line": hollow_oak.LINE_D,
            "to_version": hollow_oak.LCL_V1,
            "committed_by": "the external order system",
        }
    ]


def test_c05_repins_exactly_the_way_the_fixture_own_lena_mutation_does() -> None:
    """The external change is the fixture's own shape, not a second one that looks like it."""
    expected = hollow_oak.with_lena_mutation(hollow_oak.hollow_oak())
    produced = ExternalRepin(
        name="lena",
        order_id=hollow_oak.ORDER_D,
        line_id=hollow_oak.LINE_D,
        to_version_id=hollow_oak.LCL_V1,
    ).project(hollow_oak.hollow_oak(), anchor=hollow_oak.ANCHOR)

    assert produced.orders == expected.orders
    assert produced.order_lines == expected.order_lines
    assert produced.reservations == expected.reservations


def test_c03_authors_the_variant_and_keeps_the_wedding_refusal(
    built: dict[str, ScenarioProgram],
) -> None:
    world = built["C03"].world()

    assert hollow_oak.CHARLOTTE_V2 in world.versions
    assert hollow_oak.POLICY_CHARLOTTE in world.policies
    assert hollow_oak.CONSTRAINT_C_NOSUB in world.constraints


def test_c06_represents_the_world_moving_after_the_decision_and_not_before(
    built: dict[str, ScenarioProgram], contract: Contract
) -> None:
    """The consumption is armed. Applied at setup it would be a shortage seen before the yes."""
    frozen = contract.scenario("C06")["stale_after"]
    moves = [event for event in built["C06"].armed if isinstance(event, WorldMoves)]

    assert len(moves) == len(frozen) == 1
    assert moves[0].order == frozen[0]["order"]
    assert moves[0].resource_id == hollow_oak.STRAWBERRIES
    assert moves[0].delta == Decimal("-5.6")
    assert moves[0].effect == frozen[0]["after_which"]

    assert snapshot_of(built["C06"])["on_hand"][hollow_oak.STRAWBERRIES] == "8"
    assert "stale_after" in built["C06"].consumed


def test_c07_carries_one_decision_delivered_twice_and_not_two_decisions(
    built: dict[str, ScenarioProgram],
) -> None:
    scripted = [event for event in built["C07"].armed if isinstance(event, ScriptedReply)]

    assert len(scripted) == 1
    assert scripted[0].deliveries == 2
    assert snapshot_of(built["C07"])["replies_due"] == [
        {
            "order": "ord-b",
            "channel": "tg:1002",
            "text": "YES",
            "deliveries": 2,
            "delivered": False,
        }
    ]


def test_c09_represents_the_contention_the_contract_declares(
    built: dict[str, ScenarioProgram], contract: Contract
) -> None:
    frozen = contract.scenario("C09")["contention_groups"]
    groups = [event for event in built["C09"].armed if isinstance(event, Scarcity)]

    assert len(groups) == len(frozen) == 1
    assert groups[0].group == frozen[0]["id"]
    assert list(groups[0].members) == list(frozen[0]["members"])
    assert groups[0].max_recovered == frozen[0]["max_recovered"]

    line = built["C09"].world().commitment_lines[hollow_oak.VP_TODAY_STRAWBERRY]
    assert line.received_state is ReceivedState.SHORT
    assert line.received_qty == Decimal("1.0")


def test_no_reply_is_present_in_a_starting_world(built: dict[str, ScenarioProgram]) -> None:
    """A reply in the starting state would be a customer answering an unasked question."""
    for scenario_id, program in built.items():
        for entry in snapshot_of(program)["replies_due"]:
            assert entry["delivered"] is False, scenario_id


# ------------------------------------------------------------------- started work is not written


def test_c08_asserts_the_started_task_and_never_writes_one(
    built: dict[str, ScenarioProgram],
) -> None:
    """Starting work is a physical fact. Setup checks it and has no statement that writes it."""
    requirement = [step for step in built["C08"].steps if isinstance(step, RequireTaskState)]

    assert len(requirement) == 1
    assert requirement[0].task_id == f"task-{hollow_oak.LINE_E}"
    assert requirement[0].state is TaskState.STARTED

    world = built["C08"].world()
    assert world.tasks[f"task-{hollow_oak.LINE_E}"].state is TaskState.STARTED
    assert hollow_oak.hollow_oak().tasks[f"task-{hollow_oak.LINE_E}"].state is TaskState.STARTED


def test_no_program_moves_any_task_out_of_the_state_the_fixture_gave_it(
    built: dict[str, ScenarioProgram],
) -> None:
    clean = {task_id: task.state for task_id, task in hollow_oak.hollow_oak().tasks.items()}

    for scenario_id, program in built.items():
        produced = {task_id: task.state for task_id, task in program.world().tasks.items()}
        assert produced == clean, scenario_id


def test_a_started_work_requirement_the_fixture_contradicts_refuses_the_preparation() -> None:
    """Fail closed: the fixture is the authority and setup never makes the stipulation true."""
    step = RequireTaskState(
        name="a task the fixture has scheduled",
        task_id=f"task-{hollow_oak.LINE_A}",
        state=TaskState.STARTED,
    )

    with pytest.raises(ProgramValidationError) as refusal:
        step.project(hollow_oak.hollow_oak(), anchor=hollow_oak.ANCHOR)

    assert "STARTED" in str(refusal.value)


# ------------------------------------------------------------------ a failed setup is not ready


def test_a_program_naming_an_entity_the_fixture_lacks_refuses_rather_than_skipping() -> None:
    missing = AttestCommitmentLine(
        name="a line nobody committed",
        line_id="cl-nowhere",
        state=ReceivedState.RECEIVED,
        arrived=Decimal("1.0"),
    )

    with pytest.raises(ProgramValidationError):
        missing.project(hollow_oak.hollow_oak(), anchor=hollow_oak.ANCHOR)


def test_a_commitment_line_settles_exactly_once() -> None:
    """A second settlement would post received supply twice and count it as expected as well."""
    once = AttestCommitmentLine(
        name="receipt",
        line_id=hollow_oak.VP_TODAY_STRAWBERRY,
        state=ReceivedState.RECEIVED,
        arrived=Decimal("6.0"),
    )
    world = once.project(hollow_oak.hollow_oak(), anchor=hollow_oak.ANCHOR)

    with pytest.raises(ProgramValidationError):
        once.project(world, anchor=hollow_oak.ANCHOR)


def test_a_program_that_cannot_build_its_world_fails_the_preflight_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A world that refused to be prepared must never be reported as a prepared world."""
    broken = ScenarioProgram(
        scenario_id="C01",
        slug="broken",
        dimension="auto_recovery",
        steps=(
            AttestCommitmentLine(
                name="a line nobody committed",
                line_id="cl-nowhere",
                state=ReceivedState.RECEIVED,
                arrived=Decimal("1.0"),
            ),
        ),
    )
    monkeypatch.setattr(
        "scripts.sur1.bindings.setup.registry", lambda: {"C01": broken}, raising=True
    )

    refused = world_programs(["C01"])
    assert not refused.passed
    assert "cl-nowhere" in refused.detail


def test_a_world_carrying_unfired_armed_events_refuses_to_be_realised(
    built: dict[str, ScenarioProgram],
) -> None:
    """The remaining blocker, asserted rather than described: the firing path is not wired."""
    with pytest.raises(PreparationError) as refusal:
        realise(built["C01"], handles=None)  # type: ignore[arg-type]

    assert "armed" in str(refusal.value)
    assert "reply 1 on tg:1002" in str(refusal.value)


def test_a_declared_scarcity_is_not_something_the_world_has_to_fire(
    built: dict[str, ScenarioProgram],
) -> None:
    """C09 is short of strawberries in its starting stock; nothing has to happen for that."""
    scarcity = [event for event in built["C09"].armed if isinstance(event, Scarcity)]

    assert scarcity and all(type(event).must_fire is False for event in scarcity)
    assert all(type(event).must_fire for event in built["C09"].armed if event not in scarcity)

    with pytest.raises(PreparationError) as refusal:
        realise(built["C09"], handles=None)  # type: ignore[arg-type]

    assert "g-strawberries" not in str(refusal.value)


# ------------------------------------------------------------------------------ the freeze


def test_the_frozen_sur1_identities_have_not_moved(contract: Contract) -> None:
    """The world programs are new; the contract they are a reading of is not allowed to be."""
    assert manifest_sha(contract.document) == PUBLISHED_MANIFEST_SHA
    assert prompt_sha(contract.baseline_prompt()) == PUBLISHED_PROMPT_SHA
    assert contract.identity.manifest_version == "1.0.0"


def test_the_published_declaration_matches_the_code() -> None:
    assert declaration.differences() == ()


def test_the_declaration_names_every_scenario_with_both_of_its_identities(
    built: dict[str, ScenarioProgram],
) -> None:
    published: dict[str, Any] = declaration.published()

    assert tuple(sorted(published["programs"])) == NINE
    assert published["program_set_sha"] == program_set_sha()
    assert published["snapshot_schema_version"] == "1"
    for scenario_id, program in built.items():
        entry = published["programs"][scenario_id]
        assert entry["program_sha"] == program.identity()
        assert entry["world_digest"] == digest_of(program)


def test_the_declaration_states_that_no_arm_was_executed() -> None:
    published = declaration.published()

    assert published["no_arm_executed"] == declaration.NO_ARM_EXECUTED
    assert "No arm was executed" in published["no_arm_executed"]


def test_the_declaration_also_records_what_was_actually_run() -> None:
    """A freeze that only said what had not happened would be a freeze nobody should trust."""
    published = declaration.published()

    assert published["realisation_exercised"] == declaration.REALISATION_EXERCISED
    assert "C04" in published["realisation_exercised"]


def test_the_freeze_check_passes_and_refuses_a_set_that_is_not_the_nine(
    contract: Contract, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert world_program_freeze(contract).passed

    only_one = {"C01": program_for("C01")}
    monkeypatch.setattr(
        "scripts.sur1.bindings.programs.programs",
        lambda document=None: dict(only_one),
        raising=True,
    )
    refused = world_program_freeze(contract)

    assert not refused.passed
    assert "C02" in refused.detail
