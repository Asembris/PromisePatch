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

import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from scripts.sur1.adapters import AblationArm, PromisePatchArm
from scripts.sur1.arms import AttemptRequest
from scripts.sur1.bindings import is_real
from scripts.sur1.bindings.events import Arming
from scripts.sur1.bindings.promisepatch import (
    MCP_TOOLS,
    QUIET_READINGS,
    LiveWorkerSurface,
    McpToolClient,
    WorkspaceClient,
)
from scripts.sur1.bindings.receivers import (
    ChannelLedger,
    DatabaseReader,
    KitchenReceiver,
    OrderSystemReceiver,
    ReceiverUnreadableError,
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
    EvidenceMalformedError,
    FixtureMap,
    ReceiverEvidence,
    ReportedPromiseRow,
    TaskSample,
    WorkerReport,
    blind_bundle,
)
from scripts.sur1.frozen import ARMS, Contract
from scripts.sur1.manifest import AttemptIdentity
from scripts.sur1.predeclaration import asserts_change

NOW = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- E1, from its record

# The order system is the real application, served on a loopback port, and E1 is read through
# the endpoint the frozen contract names. Nothing here is shaped to look like the simulator's
# record: what the receiver parses is what ``apps/order-simulator`` actually publishes, which is
# the only way "the supported read path carries every field rule B2 needs" is evidence rather
# than a restatement of the reader.


@dataclass(slots=True)
class OrderSystem:
    """One real simulator, on a loopback port, with a store of its own."""

    base_url: str
    timeout_seconds: float = 60.0
    """Generous, because this is a setup step and not the thing under test.

    The server is on loopback and answers in milliseconds when the machine is idle; a developer
    box whose virus scanner has just noticed a new SQLite file has taken fifteen seconds. A
    tight timeout here turns that into a failing assertion about the receiver, which is the one
    thing this file must not report falsely.
    """

    def amend(self, *, order: str, line: str, was: str, now: str, key: str, version: int) -> None:
        import httpx2

        from order_contract.amendments import AmendmentCorrelation, AmendmentRequest

        request = AmendmentRequest(
            external_order_id=order,
            expected_version=version,
            external_line_id=line,
            from_item_id=was,
            to_item_id=now,
            correlation=AmendmentCorrelation(case_id=uuid4(), track_id=uuid4(), option_id=uuid4()),
        )
        answer = httpx2.post(
            f"{self.base_url}/orders/{order}/amendments",
            content=request.model_dump_json(),
            headers={"Content-Type": "application/json", "Idempotency-Key": key},
            timeout=self.timeout_seconds,
        )
        assert answer.status_code == 200, answer.text

    def operator_change(self, *, order: str, line: str, to_item: str) -> None:
        import httpx2

        answer = httpx2.post(
            f"{self.base_url}/ui/orders/{order}/lines/{line}",
            data={"to_item_id": to_item},
            follow_redirects=False,
            timeout=self.timeout_seconds,
        )
        assert answer.status_code in (200, 303), answer.text


@pytest.fixture
def order_system(tmp_path: Path) -> Iterator[OrderSystem]:
    """The real order simulator, served on loopback for the length of one test."""
    import socket
    import threading

    import uvicorn

    from order_simulator.app import create_app
    from order_simulator.config import Settings

    settings = Settings(database_path=tmp_path / "order-simulator.sqlite3")
    app = create_app(settings, deliver=False)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "the order simulator did not start"
    try:
        yield OrderSystem(base_url=f"http://127.0.0.1:{port}")
    finally:
        server.should_exit = True
        thread.join(timeout=30.0)


def test_the_order_receiver_reads_every_field_rule_b2_needs_from_the_named_endpoint(
    order_system: OrderSystem,
) -> None:
    """Rule B2 attributes an amendment by the key on the order system's own event.

    The command key, the previous version and the item the line now carries are all three named
    in the contract's own ``fields_used``, and all three now arrive from ``GET /admin/events``.
    This closes the disclosed discrepancy: the reader no longer opens the simulator's SQLite
    file, so a scored run needs no path into its container.
    """
    since = datetime.now(UTC) - timedelta(seconds=1)
    order_system.amend(
        order="EXT-D",
        line="ol-d",
        was="rv-raspberry-lemon-2",
        now="rv-lemon-curd-1",
        key="pp-recovery-1",
        version=1,
    )
    receiver = OrderSystemReceiver(base_url=order_system.base_url)

    (event,) = receiver.read(since=since)

    assert event.external_id == "EXT-D"
    assert event.idempotency_key == "pp-recovery-1"
    assert event.previous_version == 1
    assert event.version == 2
    assert event.line_external_item_id == "rv-lemon-curd-1"
    assert event.event_type == "ORDER_AMENDED"
    assert event.event_source == "amendment"


def test_an_event_before_the_attempt_started_is_not_read_as_this_attempt_s_effect(
    order_system: OrderSystem,
) -> None:
    """Rule B6: an external change is somebody else's command, whenever it happened."""
    order_system.operator_change(order="EXT-D", line="ol-d", to_item="rv-lemon-curd-1")
    # Wider than the system clock's own granularity, which is about 16ms on Windows: two
    # ``now()`` calls either side of a shorter pause can return the same instant, and the
    # earlier event would then sit exactly on the boundary rather than before it.
    time.sleep(0.1)
    since = datetime.now(UTC)
    time.sleep(0.1)
    order_system.amend(
        order="EXT-D",
        line="ol-d",
        was="rv-lemon-curd-1",
        now="rv-raspberry-lemon-2",
        key="pp-1",
        version=2,
    )
    receiver = OrderSystemReceiver(base_url=order_system.base_url)

    read = receiver.read(since=since)

    assert [event.idempotency_key for event in read] == ["pp-1"]


def test_an_operator_edit_during_the_attempt_is_read_and_keeps_its_own_source(
    order_system: OrderSystem,
) -> None:
    """It is evidence, not an effect. Dropping it would hide a fact about the world.

    An operator change carries no command, and the reader says so rather than inventing one:
    an empty key is what rule B6 turns on.
    """
    since = datetime.now(UTC) - timedelta(seconds=1)
    order_system.operator_change(order="EXT-D", line="ol-d", to_item="rv-lemon-curd-1")
    receiver = OrderSystemReceiver(base_url=order_system.base_url)

    (event,) = receiver.read(since=since)

    assert event.event_source == "operator"
    assert event.event_type == "order.updated", "an operator edit is not an ORDER_AMENDED"
    assert event.idempotency_key == ""


def test_the_order_receiver_probes_the_endpoint_rather_than_a_file(
    order_system: OrderSystem,
) -> None:
    """The probe is reachability plus a readable log, and it needs no store path at all."""
    assert OrderSystemReceiver(base_url=order_system.base_url).probe().reachable


def test_an_order_system_that_does_not_answer_is_unreachable_rather_than_empty() -> None:
    probe = OrderSystemReceiver(base_url="http://127.0.0.1:1").probe()

    assert not probe.reachable


def test_a_log_the_order_system_cut_short_is_unreadable_rather_than_shorter(
    order_system: OrderSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial reading of a receiver is not a reading.

    A truncated log that read as a complete one would let an attribution conclude an amendment
    never happened when it simply was not fetched, which is a silent zero on a safety ceiling.
    """
    order_system.operator_change(order="EXT-D", line="ol-d", to_item="rv-lemon-curd-1")
    order_system.operator_change(order="EXT-D", line="ol-d", to_item="rv-raspberry-lemon-2")
    monkeypatch.setattr("scripts.sur1.bindings.receivers.EVENT_WINDOW", 1)
    receiver = OrderSystemReceiver(base_url=order_system.base_url)

    with pytest.raises(ReceiverUnreadableError) as refused:
        receiver.read(since=datetime.now(UTC) - timedelta(seconds=5))

    assert "cut its event log short" in refused.value.detail


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


@dataclass
class CorrelatedTools(McpToolClient):
    """The MCP server's own behaviour: one case, and a fresh correlation id on every answer.

    ``mcp/server.py`` mints a ``uuid4`` per request and returns it on the result, so two
    readings of a case that has not moved are identical except in that one field. This double
    exists because the earlier scripted one did not carry the field at all, which is precisely
    why a settling rule that compared whole answers passed every test and then ran to its
    deadline on every real attempt.
    """

    reading: Mapping[str, Any] = field(default_factory=dict)
    status_calls: int = 0

    def call(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(name)
        if name != "status":
            return {"case_id": "case-1"}
        self.status_calls += 1
        return {**self.reading, "correlation_id": str(uuid4())}


def correlated_surface(reading: Mapping[str, Any]) -> LiveWorkerSurface:
    tools = CorrelatedTools(url="http://127.0.0.1:1/mcp", bearer_token="t", reading=reading)
    return LiveWorkerSurface(
        tools=tools,
        workspace=RecordingWorkspace(
            base_url="http://127.0.0.1:1",
            origin="http://localhost:55173",
            username="u",
            password="p",
            log=tools.calls,
        ),
        sleep=lambda _seconds: None,
    )


def test_a_settled_case_is_detected_although_every_answer_carries_a_new_correlation_id() -> None:
    """The defect that made every arm-B and arm-C attempt wait out its whole deadline.

    The case below never moves. Its answers differ only in the correlation id the transport
    mints per call, so a fingerprint over the whole answer never repeated, three quiet readings
    never happened and the wait ended only when the clock did -- 243.5s and 244.7s in the dress
    rehearsal, for work that had finished in about three seconds. The reading settles after the
    readings the rule asks for and not one more.
    """
    surface = correlated_surface({"case_id": "case-1", "headline": "Nothing is yours right now."})

    answer = surface.report_exception("the raspberries did not arrive")

    tools = surface.tools
    assert isinstance(tools, CorrelatedTools)
    assert answer["needs"] is None
    assert tools.status_calls == QUIET_READINGS + 1


def test_the_whole_attempt_shares_one_waiting_deadline_rather_than_one_per_wait() -> None:
    """Three waits of the binding's deadline is 720s against a frozen 300s ceiling.

    A deadline applied per wait bounded no attempt at all: each one started a fresh clock, so an
    attempt could cross the wall-clock ceiling while every individual wait stayed inside a bound
    that was supposed to sit under it.
    """
    surface = correlated_surface({"case_id": "case-1", "headline": "settled"})

    surface.report_exception("the raspberries did not arrive")
    opened = surface.waiting_until
    surface.answer_clarification("about four kilos")

    assert opened is not None
    assert surface.waiting_until == opened, "a later wait did not start a second clock"


def test_forgetting_a_scenario_forgets_its_waiting_budget_too() -> None:
    """The next attempt opens its own case, and its waiting starts when that case does."""
    surface = correlated_surface({"case_id": "case-1", "headline": "settled"})
    surface.report_exception("the raspberries did not arrive")

    surface.forget()

    assert surface.waiting_until is None


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
    world = SyntheticWorld(responses={"get_incident": {"reported": "the delivery did not come"}})
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
    full_world = SyntheticWorld(responses={"get_incident": {"reported": "no raspberries"}})
    ablated_world = SyntheticWorld(responses={"get_incident": {"reported": "no raspberries"}})
    full_surface = surface_for([PLANNED, SETTLED, SETTLED, SETTLED, SETTLED])
    ablated_surface = surface_for([PLANNED, SETTLED, SETTLED, SETTLED, SETTLED])

    inner = PromisePatchArm(surface=ablated_surface)
    full = PromisePatchArm(surface=full_surface).run(request_for(full_world))
    ablated = AblationArm(inner=inner).run(request_for(ablated_world))

    assert full_surface.tools.calls == ablated_surface.tools.calls
    assert full_world.invoked == ablated_world.invoked
    assert ablated.diagnostics["ablated_check"] == 5
    assert set(ablated.diagnostics) == {"ablation", "ablated_check", "settled"}
    # Arm C adds its log and nothing else. Everything the two arms do to the world and to the
    # surface is identical, and so is the one diagnostic they both carry: both waited for the
    # durable work in the same call, which is what keeps arm C's wrapper installed over the
    # whole attempt without making the wait a difference between the arms. See ADR-0020.
    assert set(full.diagnostics) == {"settled"}
    assert full.diagnostics["settled"] == ablated.diagnostics["settled"]
    assert full_world.settled == ablated_world.settled == 1


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


def test_an_amendment_read_from_the_endpoint_reaches_the_scorer_s_bundle_with_its_key(
    order_system: OrderSystem,
) -> None:
    """The whole E1 path, end to end: a real order system to the blind bundle the scorer reads.

    Rule ``B2`` attributes an amendment to an arm by the idempotency key on the order system's
    own event, and rule ``B6`` says an external change is somebody else's command. Both live at
    the far end of this chain, so proving the receiver parses a key is not by itself proving the
    scorer can see one. This drives the real simulator, reads it through the receiver, projects
    the reading, and asserts the key and the version arrived -- with no arm name anywhere in the
    result.
    """
    since = datetime.now(UTC) - timedelta(seconds=5)
    order_system.amend(
        order="EXT-D",
        line="ol-d",
        was="rv-raspberry-lemon-2",
        now="rv-lemon-curd-1",
        key="pp-recovery-1",
        version=1,
    )
    events = OrderSystemReceiver(base_url=order_system.base_url).read(since=since)

    bundle = blind_bundle(
        ReceiverEvidence(order_events=events, messages=(), tasks=(), report=None),
        run_id="unit",
        scenario_id="C01",
        arm_token="tok-abc",
        fixtures=FixtureMap.read(Contract.load().document),
        classifier=asserts_change,
    )

    (amendment,) = bundle.amendments
    assert amendment.idempotency_key == "pp-recovery-1"
    assert amendment.to_version == "rv-lemon-curd-1", "the item the changed line now holds"
    assert amendment.order == "ord-d"
    assert not any(arm in repr(bundle) for arm in ARMS)


def test_the_live_bindings_declare_themselves_real_and_the_doubles_do_not() -> None:
    assert is_real(OrderSystemReceiver(base_url="http://127.0.0.1:1"))
    assert is_real(live_world())
    assert is_real(surface_for([SETTLED]))
    assert not is_real(SyntheticWorld())
    assert not is_real(ScriptedSurface(script=[]))


def test_an_outbound_row_names_the_channel_the_fixture_maps_and_the_arming_waits_on() -> None:
    """The stored kind and address rejoin into the identity everything else speaks.

    An outbound message's payload carries ``channel_kind='telegram'`` and
    ``channel_address='1002'``, because that is how the database stores an approval channel. The
    frozen fixture maps ``tg:1002`` to an order and knows nothing called ``1002``, and an arming
    counts asks on ``tg:1002``. Reading the address alone therefore produced a row the projection
    refuses **and** an event that never became due -- one root cause, two consequences, neither
    visible until a real outbound message existed.
    """
    from scripts.sur1.bindings.receivers import CHANNEL_PREFIX_BY_KIND, channel_identity

    from promisepatch.graph.channel import PREFIX_BY_KIND, split_channel

    assert CHANNEL_PREFIX_BY_KIND == PREFIX_BY_KIND, "the restated codec has drifted"

    fixtures = FixtureMap.read(Contract.load().document)
    for channel, order in sorted(fixtures.by_channel.items()):
        kind, address = split_channel(channel)
        payload = {"channel_kind": kind, "channel_address": address, "text": "x"}
        assert channel_identity(payload) == channel
        assert fixtures.order_for_channel(channel_identity(payload)) == order


def test_an_outbound_row_whose_kind_this_build_does_not_know_is_refused_not_guessed() -> None:
    from scripts.sur1.bindings.receivers import channel_identity

    fixtures = FixtureMap.read(Contract.load().document)
    identity = channel_identity({"channel_kind": "carrier-pigeon", "channel_address": "1002"})

    assert identity == "1002"
    with pytest.raises(EvidenceMalformedError, match="names no order"):
        fixtures.order_for_channel(identity)


# ------------------------------------------------- the transport resolves one channel identity


def test_the_bare_address_the_order_system_shows_is_recorded_as_the_joined_identity() -> None:
    """``1002`` is ``tg:1002``. The defect that lost the baseline on two scored runs.

    ``get_orders`` is the order system's own snapshot and shows ``{"kind": "telegram",
    "address": "1002"}``; ``get_promise_graph`` shows ``tg:1002``. Both spellings name one
    customer, the arming watches the joined one, and the transport used to record whichever
    string it was handed. See ``docs/sur1-v3-forensic-audit.md`` §1.
    """
    world = live_world()

    world.invoke("send_customer_message", {"channel_address": "1002", "text": "may we?"})

    (message,) = world.ledger.messages
    assert message.channel_address == "tg:1002"


@pytest.mark.parametrize("spelling", ["tg:1002", "1002", "telegram:1002", " 1002 "])
def test_every_spelling_this_world_shows_resolves_to_the_one_identity(spelling: str) -> None:
    world = live_world()

    world.invoke("send_customer_message", {"channel_address": spelling, "text": "may we?"})

    (message,) = world.ledger.messages
    assert message.channel_address == "tg:1002"


@pytest.mark.parametrize("address", ["9999", "tg:9999", "wa:1002", "console:1002", ""])
def test_an_address_naming_no_channel_in_this_world_is_refused_at_the_transport(
    address: str,
) -> None:
    """Fails closed, where the arm can still see it, rather than at placement minutes later.

    Guessing which customer was meant would be the harness answering the one question only the
    arm can answer, and a wrong guess would be scored as that arm's own message to somebody else.
    """
    world = live_world()

    with pytest.raises(WorldActionError):
        world.invoke("send_customer_message", {"channel_address": address, "text": "may we?"})

    assert world.ledger.messages == []


def test_an_ask_sent_with_the_bare_address_fires_the_stipulated_reply() -> None:
    """The arming counts asks under the joined name, so the resolution is what makes it due."""
    world = settling_world("C01")

    world.invoke("send_customer_message", {"channel_address": "1002", "text": "may we?"})

    assert world.arming is not None and world.arming.pending == ()
    (ask, reply) = world.ledger.messages
    assert ask.channel_address == "tg:1002"
    assert reply.direction == INBOUND
    assert reply.channel_address == "tg:1002"
    assert reply.text == "YES"


def test_a_reply_to_a_bare_addressed_ask_reads_back_on_the_same_identity() -> None:
    """The prompt tells arm A a reply from any other address is not that customer's answer."""
    world = settling_world("C01")
    world.invoke("send_customer_message", {"channel_address": "1002", "text": "may we?"})

    replies = world.invoke("read_customer_replies", {})["replies"]

    assert [reply["text"] for reply in replies] == ["YES"]
    assert {reply["channel_address"] for reply in replies} == {"tg:1002"}


def test_a_message_sent_with_the_bare_address_is_placeable_against_the_fixture() -> None:
    """The second consequence: an ``E2`` row the projection can put on an order."""
    world = settling_world("C01")
    world.invoke("send_customer_message", {"channel_address": "1002", "text": "may we?"})

    fixtures = FixtureMap.read(Contract.load().document)
    placed = {
        fixtures.order_for_channel(message.channel_address) for message in world.ledger.messages
    }

    assert placed == {"ord-b"}


def test_the_channel_universe_is_the_frozen_fixture_s_own_channel_set() -> None:
    contract = Contract.load()

    assert live_world().channel_universe() == tuple(
        sorted(str(entry["channel"]) for entry in contract.document["fixture"]["orders"].values())
    )


def test_resolution_reads_the_address_and_the_world_and_never_who_is_driving() -> None:
    import inspect

    from scripts.sur1.bindings.receivers import resolve_channel_address

    assert list(inspect.signature(resolve_channel_address).parameters) == ["address", "known"]


def test_one_bare_address_carried_by_two_kinds_is_refused_rather_than_picked() -> None:
    from scripts.sur1.bindings.receivers import (
        UnresolvableChannelError,
        resolve_channel_address,
    )

    with pytest.raises(UnresolvableChannelError, match="more than one channel"):
        resolve_channel_address("1002", known=("tg:1002", "wa:1002"))
