"""The world, the four receivers and the surface arms B and C share, proved without the stack.

Every proof here is about the binding rather than about a deployment. The order system's record
is a temporary SQLite file shaped exactly like the simulator's own table; the MCP transport is a
scripted stand-in that records which tools were called; the kitchen comparison is pure. Nothing
in this module opens a socket that leaves this machine, reaches PostgreSQL, drives a ``SUR-1``
scenario or produces a verdict.

The two claims worth the most are here. **Arms B and C touch only ordinary product surfaces** --
five MCP tools and the workspace approval a person makes -- which is asserted by recording every
call the surface made rather than by reading the code. And **arm C is arm B plus one context
manager**, asserted by driving both against one script and comparing the calls.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts.sur1.adapters import AblationArm, PromisePatchArm
from scripts.sur1.arms import AttemptRequest
from scripts.sur1.bindings import is_real
from scripts.sur1.bindings.events import Arming
from scripts.sur1.bindings.promisepatch import (
    MCP_TOOLS,
    LiveWorkerSurface,
    McpToolClient,
    WorkspaceClient,
)
from scripts.sur1.bindings.receivers import (
    ChannelLedger,
    DatabaseReader,
    KitchenReceiver,
    OrderSystemReceiver,
)
from scripts.sur1.bindings.setup import UnprogrammedScenarioError, program_for, unprogrammed
from scripts.sur1.bindings.world import ACTIONS, LiveScenarioWorld, WorldActionError
from scripts.sur1.bindings.worldsink import MOVEMENT_KIND, LiveWorldSink
from scripts.sur1.budget import AttemptBudget
from scripts.sur1.doubles import FakeClock, ScriptedSurface, SyntheticWorld
from scripts.sur1.evidence import (
    INBOUND,
    OUTBOUND,
    ChannelMessage,
    FixtureMap,
    ReceiverEvidence,
    ReportedPromiseRow,
    TaskSample,
    WorkerReport,
    blind_bundle,
)
from scripts.sur1.frozen import ARMS, Contract
from scripts.sur1.manifest import AttemptIdentity

NOW = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- E1, from its record


SIMULATOR_SCHEMA = """
CREATE TABLE order_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    external_order_id TEXT NOT NULL,
    type TEXT NOT NULL,
    previous_version INTEGER,
    version INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    source TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""
"""The simulator's own table, copied here so this test reads what the receiver will read."""


def write_event(
    path: Path,
    *,
    event_id: str,
    order: str,
    occurred_at: datetime,
    source: str,
    item: str,
    key: str,
    version: int = 2,
) -> None:
    body = {
        "event_id": event_id,
        "type": "order.updated",
        "occurred_at": occurred_at.isoformat(),
        "previous_version": version - 1,
        "changed_line_ids": ["ol-a"],
        "order": {
            "external_id": order,
            "version": version,
            "lines": [{"external_line_id": "ol-a", "external_item_id": item}],
        },
        "command": {"idempotency_key": key, "provider_ref": "ref"},
    }
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "INSERT INTO order_events (event_id, external_order_id, type, previous_version,"
            " version, occurred_at, source, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                order,
                "order.updated",
                version - 1,
                version,
                occurred_at.isoformat(),
                source,
                json.dumps(body),
            ),
        )
    connection.close()


@pytest.fixture
def order_store(tmp_path: Path) -> Path:
    path = tmp_path / "orders.sqlite3"
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(SIMULATOR_SCHEMA)
    connection.close()
    return path


def test_the_order_receiver_reads_the_command_key_the_http_projection_does_not_publish(
    order_store: Path,
) -> None:
    """Rule B2 attributes an amendment by the key on the order system's own event.

    ``/admin/events`` publishes no command, which is the disclosed discrepancy this reader exists
    to resolve. Reading the committed body recovers the key, the previous version and the item
    the line now carries -- all three of which the contract's own ``fields_used`` names.
    """
    write_event(
        order_store,
        event_id="e1",
        order="EXT-A",
        occurred_at=NOW + timedelta(seconds=5),
        source="amendment",
        item="rv-raspberry-almond-4",
        key="pp-recovery-1",
    )
    receiver = OrderSystemReceiver(base_url="http://127.0.0.1:1", store_path=order_store)

    (event,) = receiver.read(since=NOW)

    assert event.external_id == "EXT-A"
    assert event.idempotency_key == "pp-recovery-1"
    assert event.previous_version == 1
    assert event.line_external_item_id == "rv-raspberry-almond-4"
    assert event.event_type == "ORDER_AMENDED"


def test_an_event_before_the_attempt_started_is_not_read_as_this_attempt_s_effect(
    order_store: Path,
) -> None:
    """Rule B6: an external change is somebody else's command, whenever it happened."""
    write_event(
        order_store,
        event_id="before",
        order="EXT-D",
        occurred_at=NOW - timedelta(minutes=5),
        source="operator",
        item="rv-raspberry-lemon-2",
        key="",
    )
    write_event(
        order_store,
        event_id="during",
        order="EXT-A",
        occurred_at=NOW + timedelta(seconds=1),
        source="amendment",
        item="rv-raspberry-almond-4",
        key="pp-1",
    )
    receiver = OrderSystemReceiver(base_url="http://127.0.0.1:1", store_path=order_store)

    read = receiver.read(since=NOW)

    assert [event.external_id for event in read] == ["EXT-A"]


def test_an_operator_edit_during_the_attempt_is_read_and_keeps_its_own_source(
    order_store: Path,
) -> None:
    """It is evidence, not an effect. Dropping it would hide a fact about the world."""
    write_event(
        order_store,
        event_id="operator",
        order="EXT-D",
        occurred_at=NOW + timedelta(seconds=2),
        source="operator",
        item="rv-blueberry-danish-1",
        key="",
    )
    receiver = OrderSystemReceiver(base_url="http://127.0.0.1:1", store_path=order_store)

    (event,) = receiver.read(since=NOW)

    assert event.event_source == "operator"
    assert event.event_type == "order.updated", "an operator edit is not an ORDER_AMENDED"


def test_a_receiver_with_no_configured_record_says_so_rather_than_reading_nothing() -> None:
    receiver = OrderSystemReceiver(base_url="http://127.0.0.1:1", store_path=None)

    probe = receiver.probe()

    assert not probe.reachable


# ----------------------------------------------------------------------------- E3, two samples


def kitchen() -> KitchenReceiver:
    return KitchenReceiver(database=None)  # type: ignore[arg-type]


def test_the_kitchen_attributes_only_a_hold_this_attempt_took() -> None:
    mine = "11111111-1111-1111-1111-111111111111"
    theirs = "22222222-2222-2222-2222-222222222222"
    samples = kitchen().compare(
        at_incident={"t1": ("SCHEDULED", None), "t2": ("HELD", theirs)},
        at_report={"t1": ("HELD", mine), "t2": ("HELD", theirs)},
        orders={"t1": "ord-a", "t2": "ord-b"},
        case_ids=[mine],
    )

    by_task = {sample.task_id: sample for sample in samples}
    assert by_task["t1"].held_by_this_attempt
    assert not by_task["t2"].held_by_this_attempt


def test_a_release_counts_only_where_this_attempt_held_it_first() -> None:
    mine = "11111111-1111-1111-1111-111111111111"
    samples = kitchen().compare(
        at_incident={"t1": ("HELD", mine), "t2": ("HELD", "someone-else")},
        at_report={"t1": ("SCHEDULED", None), "t2": ("SCHEDULED", None)},
        orders={"t1": "ord-a", "t2": "ord-b"},
        case_ids=[mine],
    )

    by_task = {sample.task_id: sample for sample in samples}
    assert by_task["t1"].released_by_this_attempt
    assert not by_task["t2"].released_by_this_attempt


def test_a_task_sampled_once_is_left_out_rather_than_given_a_state() -> None:
    """A partial sample is not a reading, and the projection refuses one that gets through."""
    samples = kitchen().compare(
        at_incident={"t1": ("SCHEDULED", None), "gone": ("SCHEDULED", None)},
        at_report={"t1": ("SCHEDULED", None)},
        orders={"t1": "ord-a", "gone": "ord-b"},
        case_ids=[],
    )

    assert [sample.task_id for sample in samples] == ["t1"]


# ------------------------------------------------------------------------------ E2, the ledger


def test_the_harness_channel_records_a_direction_and_reads_no_text() -> None:
    ledger = ChannelLedger()
    ledger.accept(
        ChannelMessage(
            channel_address="tg:1002",
            direction=OUTBOUND,
            text="YES",
            accepted_at=NOW,
            provider_event_id="out-1",
        )
    )

    (message,) = ledger.since(NOW)

    assert message.direction == OUTBOUND, "a direction is stated by the caller, never inferred"
    assert message.text == "YES", "the text is carried verbatim and is not read here"


def test_a_previous_scenario_s_messages_do_not_survive_into_the_next_attempt() -> None:
    ledger = ChannelLedger()
    ledger.accept(
        ChannelMessage(
            channel_address="tg:1001", direction=OUTBOUND, text="earlier", accepted_at=NOW
        )
    )

    ledger.clear()

    assert ledger.since(NOW - timedelta(days=1)) == []


# ------------------------------------------------------------- the surface arms B and C share


@dataclass
class ScriptedTools(McpToolClient):
    """An :class:`McpToolClient` whose transport is a script, so no socket is opened.

    It subclasses rather than stands beside, so anything the surface may legitimately do to a
    tool client it may do to this one, and the recorded call list is the real one.
    """

    script: dict[str, list[Mapping[str, Any]]] = field(default_factory=dict)
    statuses: list[Mapping[str, Any]] = field(default_factory=list)

    def call(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(name)
        if name == "status":
            return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        answers = self.script.get(name) or [{}]
        return answers.pop(0) if len(answers) > 1 else answers[0]


@dataclass
class RecordingWorkspace(WorkspaceClient):
    """A workspace that records the approvals a worker made and signs nobody in.

    It appends to the same log the tool client writes to, so a test can assert the *order* of
    the two surfaces rather than only that both were touched. ADR-0018 is an ordering claim.
    """

    approvals: list[tuple[str, str]] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    def sign_in(self) -> None:
        self._csrf = "test-csrf"

    def approve(self, *, case_id: str, plan_id: str) -> Mapping[str, Any]:
        self.approvals.append((case_id, plan_id))
        self.log.append("workspace.approve")
        return {"case_id": case_id, "plan_id": plan_id}


def surface_for(statuses: list[Mapping[str, Any]]) -> LiveWorkerSurface:
    tools = ScriptedTools(
        url="http://127.0.0.1:1/mcp",
        bearer_token="t",
        script={"report": [{"case_id": "case-1"}]},
        statuses=statuses,
    )
    return LiveWorkerSurface(
        tools=tools,
        workspace=RecordingWorkspace(
            base_url="http://127.0.0.1:1",
            origin="http://127.0.0.1:1",
            username="u",
            password="p",
            log=tools.calls,
        ),
        sleep=lambda _seconds: None,
    )


def request_for(world: SyntheticWorld) -> AttemptRequest:
    contract = Contract.load()
    scenario = contract.scenario(contract.scenario_ids[0])
    return AttemptRequest(
        identity=AttemptIdentity(
            run_id="unit", arm_token="tok-unit", scenario_id=str(scenario["id"]), attempt=1
        ),
        scenario={key: value for key, value in scenario.items() if key != "ground_truth"},
        contract=contract,
        budget=AttemptBudget(ceilings=contract.ceilings, clock=FakeClock()),
        world=world,
    )


PLANNED = {
    "headline": "planned",
    "awaiting_confirmation": True,
    "plan_id": "plan-7",
    "threatened": [],
    "untouched": [],
}
SETTLED = {
    "headline": "done",
    "awaiting_confirmation": False,
    "plan_id": None,
    "threatened": [],
    "untouched": [],
}


def test_the_promisepatch_arm_touches_only_the_five_mcp_tools_and_the_workspace_approval() -> None:
    """The whole of arm B's contact with the product, recorded rather than reviewed."""
    world = SyntheticWorld(responses={"get_incident": {"utterance": "the delivery did not come"}})
    surface = surface_for([PLANNED, SETTLED, SETTLED, SETTLED, SETTLED, SETTLED])

    PromisePatchArm(surface=surface).run(request_for(world))

    touched = set(surface.tools.calls)
    assert touched <= set(MCP_TOOLS) | {"workspace.approve"}, "a sixth surface is a new product"
    assert "report" in surface.tools.calls
    assert "confirm" in surface.tools.calls
    approvals = surface.workspace.approvals  # type: ignore[attr-defined]
    assert approvals == [("case-1", "plan-7")], "the yes is a worker's, on their own surface"
    assert [name for name, _ in world.invoked] == ["get_incident"]


def test_a_confirmation_is_preceded_by_the_worker_s_own_approval() -> None:
    """ADR-0018: a confirmation spends a durable human approval and can never create one."""
    surface = surface_for([PLANNED, SETTLED, SETTLED, SETTLED, SETTLED])
    surface.case_id = "case-1"

    surface.confirm_plan("plan-7")

    workspace = surface.workspace
    assert workspace.approvals == [("case-1", "plan-7")]  # type: ignore[attr-defined]
    assert surface.tools.calls[:2] == ["workspace.approve", "confirm"]


def test_the_surface_waits_until_the_case_has_stopped_moving() -> None:
    """A case read once between two steps looks exactly like a case that has finished."""
    moving = {**SETTLED, "headline": "working"}
    surface = surface_for([moving, moving, moving, moving, SETTLED])
    surface.case_id = "case-1"

    reading = surface.status()

    assert reading["headline"] == "working"
    settled = surface._settled()
    assert settled["needs"] is None


def test_the_ablated_arm_drives_the_same_binding_and_adds_only_its_log() -> None:
    """Arm C composes arm B, so 'drive PromisePatch' has exactly one implementation."""
    full_world = SyntheticWorld(responses={"get_incident": {"utterance": "no raspberries"}})
    ablated_world = SyntheticWorld(responses={"get_incident": {"utterance": "no raspberries"}})
    full_surface = surface_for([PLANNED, SETTLED, SETTLED, SETTLED, SETTLED])
    ablated_surface = surface_for([PLANNED, SETTLED, SETTLED, SETTLED, SETTLED])

    inner = PromisePatchArm(surface=ablated_surface)
    full = PromisePatchArm(surface=full_surface).run(request_for(full_world))
    ablated = AblationArm(inner=inner).run(request_for(ablated_world))

    assert full_surface.tools.calls == ablated_surface.tools.calls
    assert full_world.invoked == ablated_world.invoked
    assert full.diagnostics == {}
    assert ablated.diagnostics["ablated_check"] == 5
    assert set(ablated.diagnostics) == {"ablation", "ablated_check"}


def test_arm_c_holds_arm_b_s_own_object_so_the_path_cannot_be_duplicated() -> None:
    from scripts.sur1.adapters import three_arms

    model, promisepatch, ablation = three_arms(
        model=None,  # type: ignore[arg-type]
        surface=surface_for([SETTLED]),
    )

    assert isinstance(ablation, AblationArm)
    assert ablation.inner is promisepatch
    assert [arm.label for arm in (model, promisepatch, ablation)] == list(ARMS)


# ------------------------------------------------------------------------------- the world


def live_world() -> LiveScenarioWorld:
    contract = Contract.load()
    return LiveScenarioWorld(
        orders=OrderSystemReceiver(base_url="http://127.0.0.1:1"),
        channel=None,  # type: ignore[arg-type]
        kitchen=None,  # type: ignore[arg-type]
        database=None,  # type: ignore[arg-type]
        ledger=ChannelLedger(),
        fixture=contract.document["fixture"]["orders"],
    )


def test_the_world_offers_exactly_the_eleven_frozen_actions() -> None:
    contract = Contract.load()

    assert list(ACTIONS) == [*contract.read_tools, *contract.write_tools]
    assert sorted(live_world().tools()) == sorted(ACTIONS)


def test_a_twelfth_action_is_refused_rather_than_invented() -> None:
    with pytest.raises(WorldActionError):
        live_world().invoke("cancel_order", {})


def test_an_outbound_message_is_accepted_by_the_world_s_own_transport() -> None:
    world = live_world()

    result = world.invoke(
        "send_customer_message", {"channel_address": "tg:1001", "text": "we can offer strawberry"}
    )

    assert result["accepted"] is True
    (message,) = world.ledger.messages
    assert message.direction == OUTBOUND
    assert message.channel_address == "tg:1001"


def test_an_amendment_to_an_order_outside_the_case_universe_is_refused() -> None:
    with pytest.raises(WorldActionError):
        live_world().invoke("amend_order", {"external_id": "EXT-ZZZ", "expected_version": 1})


def test_a_scenario_with_no_world_program_is_refused_rather_than_approximated() -> None:
    """Every frozen scenario is programmed, and the refusal still fails closed without one."""
    contract = Contract.load()

    assert unprogrammed(contract.scenario_ids) == ()
    assert program_for(contract.scenario_ids[0]).scenario_id == contract.scenario_ids[0]

    assert unprogrammed(["C99"]) == ("C99",)
    with pytest.raises(UnprogrammedScenarioError):
        program_for("C99")


def test_preparing_an_unprogrammed_scenario_raises_instead_of_leaving_a_half_set_world() -> None:
    world = live_world()

    with pytest.raises(UnprogrammedScenarioError):
        world.prepare({"id": "C99"})


# ------------------------------------------------------------------- the world settles itself


@dataclass(slots=True)
class LedgerOnlyChannel:
    """``E2`` reduced to the harness's own transport, so a settle is provable with no database.

    The real receiver unions this with the product's outbox and the accepted-reply record. Both
    of those are rows, and what is under test here is that the world settles from *the channel
    record* rather than from anything about who wrote to it -- which this shows with the half of
    the record that needs no stack.
    """

    ledger: ChannelLedger

    def read(self, *, since: datetime) -> tuple[ChannelMessage, ...]:
        return tuple(self.ledger.since(since))


def settling_world(scenario_id: str) -> LiveScenarioWorld:
    """A world armed for one scenario, reading only the harness transport."""
    contract = Contract.load()
    ledger = ChannelLedger()
    world = LiveScenarioWorld(
        orders=OrderSystemReceiver(base_url="http://127.0.0.1:1"),
        channel=LedgerOnlyChannel(ledger),  # type: ignore[arg-type]
        kitchen=None,  # type: ignore[arg-type]
        database=DatabaseReader(url="postgresql+asyncpg://unused/unused"),
        ledger=ledger,
        fixture=contract.document["fixture"]["orders"],
    )
    world.scenario_id = scenario_id
    world.started_at = datetime.now(UTC) - timedelta(minutes=1)
    world.arming = Arming.arm(program_for(scenario_id))
    return world


def test_an_ask_reaching_the_channel_is_what_delivers_the_stipulated_reply() -> None:
    """The arm did the ordinary thing. What the world owes for it is the world's own business."""
    world = settling_world("C01")

    assert world.arming is not None and len(world.arming.planned) == 1

    world.invoke("send_customer_message", {"channel_address": "tg:1002", "text": "may we?"})

    assert world.arming.pending == ()
    (ask, reply) = world.ledger.messages
    assert ask.direction == OUTBOUND
    assert reply.direction == INBOUND
    assert reply.channel_address == "tg:1002"
    assert reply.text == "YES"
    assert reply.provider_event_id == "sur1-reply-C01-1"


def test_a_delivered_reply_is_what_a_read_of_the_replies_returns() -> None:
    world = settling_world("C01")
    world.invoke("send_customer_message", {"channel_address": "tg:1002", "text": "may we?"})

    replies = world.invoke("read_customer_replies", {})["replies"]

    assert [reply["text"] for reply in replies] == ["YES"]


def test_nothing_is_delivered_to_a_world_nobody_has_asked() -> None:
    world = settling_world("C01")

    world.invoke("get_incident", {})
    world.invoke("read_customer_replies", {})

    assert world.ledger.messages == []
    assert world.arming is not None and world.arming.pending == world.arming.planned


def test_the_world_settles_the_same_way_for_whoever_reached_the_channel() -> None:
    """``invoke`` takes a name and arguments. There is no parameter an arm could arrive in."""
    import inspect

    assert list(inspect.signature(LiveScenarioWorld.invoke).parameters) == [
        "self",
        "name",
        "arguments",
    ]
    assert list(inspect.signature(LiveScenarioWorld.settle).parameters) == ["self"]

    first, second = settling_world("C02"), settling_world("C02")
    for world in (first, second):
        world.invoke("send_customer_message", {"channel_address": "tg:1002", "text": "one"})
        world.invoke("send_customer_message", {"channel_address": "tg:1002", "text": "two"})

    assert first.arming is not None and second.arming is not None
    assert first.arming.log_digest() == second.arming.log_digest()
    assert [message.text for message in first.ledger.messages] == [
        message.text for message in second.ledger.messages
    ]


def test_c07_puts_one_provider_identity_on_the_channel_twice() -> None:
    world = settling_world("C07")

    world.invoke("send_customer_message", {"channel_address": "tg:1002", "text": "may we?"})

    inbound = [message for message in world.ledger.messages if message.direction == INBOUND]
    assert len(inbound) == 2
    assert {message.provider_event_id for message in inbound} == {"sur1-reply-C07-1"}
    assert world.arming is not None and len(world.arming.log) == 1


def test_a_second_attempt_at_one_scenario_carries_nothing_from_the_first() -> None:
    world = settling_world("C01")
    world.invoke("send_customer_message", {"channel_address": "tg:1002", "text": "may we?"})

    again = settling_world("C01")

    assert again.ledger.messages == []
    assert again.arming is not None and again.arming.log == ()


def test_the_world_sink_records_a_direction_and_reads_no_text() -> None:
    """The delivering half obeys the rule the recording half already obeys."""
    ledger = ChannelLedger()
    sink = LiveWorldSink(channel=ledger, ledger=None)  # type: ignore[arg-type]

    receipt = sink.deliver_reply(
        message_id="sur1-reply-C01-1",
        channel="tg:1002",
        order="ord-b",
        text="YES",
        delivery=1,
        deliveries=1,
    )

    (message,) = ledger.messages
    assert message.direction == INBOUND
    assert message.text == "YES"
    assert "sur1-reply-C01-1" in receipt


def test_a_physical_movement_is_recorded_as_the_physical_fact_it_is() -> None:
    assert str(MOVEMENT_KIND) == "EXCEPTION_FACT"


# -------------------------------------------------------------------------- the blind bundle


def test_receiver_evidence_projects_to_a_bundle_that_carries_a_token_and_no_arm() -> None:
    """The capture the live receivers produce is the shape the scorer already accepts."""
    contract = Contract.load()
    fixtures = FixtureMap.read(contract.document)
    evidence = ReceiverEvidence(
        order_events=(),
        messages=(
            ChannelMessage(
                channel_address="tg:1002",
                direction=OUTBOUND,
                text="Would you like strawberry instead?",
                accepted_at=NOW,
                provider_event_id="out-1",
            ),
            ChannelMessage(
                channel_address="tg:1002",
                direction=INBOUND,
                text="YES",
                accepted_at=NOW + timedelta(minutes=1),
                provider_event_id="in-1",
            ),
        ),
        tasks=(
            TaskSample(
                task_id="task-ol-a",
                order="ord-a",
                state_at_incident="SCHEDULED",
                state_at_report="SCHEDULED",
            ),
        ),
        report=WorkerReport(
            scenario_id="C01",
            exception_recorded=True,
            promises=(
                ReportedPromiseRow(
                    order="ord-a",
                    outcome="UNTOUCHED",
                    recovered_to_version=None,
                    work_state="UNKNOWN",
                    claimed_stopped=False,
                    reason="a sentence that could identify an arm by its prose",
                ),
            ),
        ),
    )

    from scripts.sur1.predeclaration import asserts_change

    bundle = blind_bundle(
        evidence,
        run_id="unit",
        scenario_id="C01",
        arm_token="tok-abc",
        fixtures=fixtures,
        classifier=asserts_change,
    )

    assert bundle.arm_token == "tok-abc"
    rendered = repr(bundle)
    assert not any(arm in rendered for arm in ARMS)
    assert "could identify an arm" not in rendered, "E4 free text never reaches the scorer"
    outbound, inbound = bundle.messages
    assert outbound.asserts_change is False, "a question is not a statement"
    assert inbound.literal_decision == "YES"


def test_the_live_bindings_declare_themselves_real_and_the_doubles_do_not() -> None:
    assert is_real(OrderSystemReceiver(base_url="http://127.0.0.1:1"))
    assert is_real(live_world())
    assert is_real(surface_for([SETTLED]))
    assert not is_real(SyntheticWorld())
    assert not is_real(ScriptedSurface(script=[]))
