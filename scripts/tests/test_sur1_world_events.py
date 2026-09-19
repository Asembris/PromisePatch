"""The armed events and the realisation lifecycle, proved without driving an arm.

Every test here works from a *controlled observation*: a count of outbound messages per channel
address, handed to the arming directly. No arm is constructed, no model is reached, no database
is opened, no order system is posted to and no comparative number is produced. That is not a
convenience -- it is the property under test. If firing a scenario's stipulated events required
an arm, then the events would be part of what is being measured rather than part of the world,
and the three readings would not be comparable.

The claims that carry the weight:

* every one of the nine scenarios has a firing plan, and every declared event that must happen
  is in it exactly once, with exactly one trigger and exactly one action;
* what a trigger may read is a count of asks and a set of completed events, and nothing else, so
  no trigger can consult an arm, an expected disposition, a scorer's reading or a clock;
* the same observable sequence produces the same mutations and the same log digest, whoever
  produced the sequence;
* an event fires once, a failure fails the whole arming closed, and nothing survives a reset;
* a realisation is ``READY`` only after the world is installed and the events are armed, and a
  refusal at any stage never reports ``READY``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from scripts.sur1.bindings.events import (
    ARMED,
    FAILED,
    REPLY_DELIVERY,
    STOCK_MOVEMENT,
    Arming,
    AskReachesChannel,
    DeliverReply,
    EventCompleted,
    EventFiringError,
    EventPlanError,
    MoveStock,
    Observation,
    declared_without_firing,
    observe,
    plan,
    plan_digest,
)
from scripts.sur1.bindings.programs import (
    ArmedEvent,
    ExternalRepin,
    Scarcity,
    ScenarioProgram,
    ScriptedReply,
    WorldMoves,
    programs,
)
from scripts.sur1.bindings.realisation import READY, Realisation, realise
from scripts.sur1.bindings.setup import PreparationError
from scripts.sur1.frozen import ARMS
from scripts.sur1.preflight import (
    ARM_FIELD_NAMES,
    FORBIDDEN_SCENARIO_FIELDS,
    _names_in,
    event_blinding,
)

NINE = ("C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09")
CHANNEL = "tg:1002"
EVENTFUL = ("C01", "C02", "C03", "C05", "C06", "C07", "C08", "C09")
"""Every scenario that owes the world something. ``C04`` is frozen eventless and stays so."""


@pytest.fixture(scope="module")
def built() -> dict[str, ScenarioProgram]:
    return programs()


# ----------------------------------------------------------------- controlled world events


@dataclass(frozen=True, slots=True)
class Message:
    """A channel record entry, reduced to the two fields a trigger may see."""

    channel_address: str
    direction: str


@dataclass(slots=True)
class RecordingSink:
    """A world that records what it was asked to do and refuses when told to.

    Stands in for the live sink so the ordering, the one-shot guarantee and the fail-closed
    behaviour are provable with no channel, no ledger and no stack.
    """

    calls: list[tuple[Any, ...]] = field(default_factory=list)
    refuse: str = ""

    def deliver_reply(
        self,
        *,
        message_id: str,
        channel: str,
        order: str,
        text: str,
        delivery: int,
        deliveries: int,
    ) -> str:
        if self.refuse == REPLY_DELIVERY:
            raise RuntimeError("the channel refused the message")
        self.calls.append(("reply", message_id, channel, order, text, delivery, deliveries))
        return f"reply:{message_id}:{delivery}/{deliveries}"

    def move_stock(self, *, resource: str, delta: Decimal, source_id: str, order: str) -> str:
        if self.refuse == STOCK_MOVEMENT:
            raise RuntimeError("the ledger refused the posting")
        self.calls.append(("stock", resource, str(delta), source_id, order))
        return f"ledger:sur1:{source_id}"


def after(asks: int, *, channel: str = CHANNEL) -> Observation:
    """The observation after ``asks`` outbound messages have reached one channel address."""
    return observe([Message(channel, "OUTBOUND")] * asks)


# ------------------------------------------------------------------ every scenario plans


def test_every_scenario_has_a_firing_plan_that_covers_what_it_declares(
    built: dict[str, ScenarioProgram],
) -> None:
    """All nine realise as far as planning goes, which is the check that used to refuse."""
    for scenario_id in NINE:
        program = built[scenario_id]
        planned = plan(program)
        unfired = declared_without_firing(program)
        must_fire = [event for event in program.armed if type(event).must_fire]

        assert len(planned) == len(must_fire), scenario_id
        assert {event.declared for event in planned} == {event.name for event in must_fire}
        assert set(unfired) == set(program.armed) - set(must_fire)


def test_c04_is_eventless_and_stays_that_way(built: dict[str, ScenarioProgram]) -> None:
    """Frozen with nothing to happen during an attempt. Inventing one would be a new scenario."""
    assert built["C04"].armed == ()
    assert plan(built["C04"]) == ()


def test_every_eventful_scenario_owes_at_least_one_event(
    built: dict[str, ScenarioProgram],
) -> None:
    for scenario_id in EVENTFUL:
        assert plan(built[scenario_id]), scenario_id


def test_every_planned_event_has_exactly_one_identity_one_trigger_and_one_action(
    built: dict[str, ScenarioProgram],
) -> None:
    """An event with two triggers is two events, and an event with none never happens."""
    seen: set[str] = set()
    for scenario_id in NINE:
        planned = plan(built[scenario_id])
        for event in planned:
            assert event.event_id not in seen, event.event_id
            seen.add(event.event_id)
            assert event.event_id.startswith(f"{scenario_id}:")
            assert event.kind in (REPLY_DELIVERY, STOCK_MOVEMENT)
            assert len(event.trigger.describes()) >= 1
            assert len(event.action.describes()) >= 1
            assert isinstance(event.trigger, AskReachesChannel | EventCompleted)
            assert isinstance(event.action, DeliverReply | MoveStock)
        sequences = [event.sequence for event in planned]
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences)


def test_a_declared_event_no_trigger_can_observe_refuses_rather_than_being_approximated() -> None:
    """The honest refusal: an event nothing can fire keeps its scenario out of a scored run."""

    @dataclass(frozen=True, slots=True)
    class WeatherTurns(ArmedEvent):
        pass

    program = ScenarioProgram(
        scenario_id="CXX",
        slug="invented",
        dimension="invented",
        steps=(),
        armed=(WeatherTurns(name="it rains", trigger="unobservable", effect="nothing here"),),
    )

    with pytest.raises(EventPlanError) as refusal:
        plan(program)

    assert "it rains" in str(refusal.value)
    assert "honestly observe" in str(refusal.value)


def test_a_movement_with_no_decision_to_follow_refuses(built: dict[str, ScenarioProgram]) -> None:
    """A world that moves *after* a decision needs a decision it can be armed on."""
    movement = next(event for event in built["C06"].armed if isinstance(event, WorldMoves))
    orphan = replace(built["C06"], armed=(movement,))

    with pytest.raises(EventPlanError) as refusal:
        plan(orphan)

    assert "no observable moment" in str(refusal.value)


# ----------------------------------------------------------------- a trigger is blinded


def test_a_trigger_may_read_a_count_of_asks_and_a_set_of_completed_events_and_nothing_else() -> (
    None
):
    """The whole of the blinding argument, as a property of the type a trigger is given."""
    assert set(Observation.__dataclass_fields__) == {"asks", "completed"}
    assert not set(Observation.__dataclass_fields__) & ARM_FIELD_NAMES
    assert not set(Observation.__dataclass_fields__) & FORBIDDEN_SCENARIO_FIELDS


def test_no_module_on_the_firing_path_names_an_arm_an_answer_or_a_reading() -> None:
    check = event_blinding()

    assert check.passed, check.detail


def test_the_firing_blindness_guard_bites(tmp_path: Path) -> None:
    """Proving the guard looks, rather than trusting that a pass means it did."""
    forbidden = FORBIDDEN_SCENARIO_FIELDS | ARM_FIELD_NAMES | frozenset(ARMS)
    for offence, source in (
        ("ground_truth", "def fire(scenario):\n    return scenario['ground_truth']\n"),
        ("the_point", "def fire(scenario):\n    return scenario.the_point\n"),
        ("PROMISEPATCH", "def fire(who):\n    return who == 'PROMISEPATCH'\n"),
        ("arm", "def fire(arm):\n    return arm\n"),
    ):
        offending = tmp_path / f"offending_{offence}.py"
        offending.write_text(source, encoding="utf-8")

        assert offence in _names_in(offending, forbidden), offence


def test_a_plan_is_derived_from_the_program_alone(built: dict[str, ScenarioProgram]) -> None:
    """There is no parameter by which two arms could be handed two plans."""
    import inspect

    assert list(inspect.signature(plan).parameters) == ["program"]
    for scenario_id in NINE:
        assert plan_digest(built[scenario_id]) == plan_digest(built[scenario_id])
    assert plan_digest(programs()["C06"]) == plan_digest(built["C06"])


# ------------------------------------------------------- the same sequence, the same world


def drive(program: ScenarioProgram, sequence: list[int]) -> tuple[Arming, RecordingSink]:
    """Pump one arming through a sequence of ask counts, and hand back what the world did."""
    arming = Arming.arm(program)
    sink = RecordingSink()
    for asks in sequence:
        arming.pump(after(asks), sink)
    return arming, sink


def test_identical_observable_sequences_produce_identical_mutations_and_logs(
    built: dict[str, ScenarioProgram],
) -> None:
    """The property that makes three arms' readings comparable at all."""
    for scenario_id in EVENTFUL:
        first_arming, first_sink = drive(built[scenario_id], [0, 1, 1, 2, 2])
        second_arming, second_sink = drive(built[scenario_id], [0, 1, 1, 2, 2])

        assert first_sink.calls == second_sink.calls, scenario_id
        assert first_arming.log_digest() == second_arming.log_digest(), scenario_id
        assert [event.event_id for event in first_arming.log] == [
            event.event_id for event in second_arming.log
        ]


def test_a_reply_is_not_delivered_before_an_ask_reaches_its_channel(
    built: dict[str, ScenarioProgram],
) -> None:
    for scenario_id in EVENTFUL:
        arming, sink = drive(built[scenario_id], [0, 0, 0])

        assert sink.calls == [], scenario_id
        assert arming.log == ()
        assert len(arming.pending) == len(arming.planned)


def test_a_reply_the_world_delivered_is_never_counted_as_an_ask() -> None:
    """Inbound is not an ask. A world that miscounted would answer its own first reply."""
    observation = observe(
        [
            Message(CHANNEL, "OUTBOUND"),
            Message(CHANNEL, "INBOUND"),
            Message(CHANNEL, "INBOUND"),
        ]
    )

    assert observation.asks_on(CHANNEL) == 1


# ------------------------------------------------------------------------- C02's ordering


def test_c02_keeps_its_two_replies_in_the_frozen_order(built: dict[str, ScenarioProgram]) -> None:
    """The non-literal one first, the literal ``YES`` only after a second ask."""
    frozen = [event.text for event in built["C02"].armed if isinstance(event, ScriptedReply)]
    arming = Arming.arm(built["C02"])
    sink = RecordingSink()

    assert arming.pump(after(1), sink) and len(sink.calls) == 1
    assert sink.calls[0][4] == frozen[0] == "Strawberries work."

    assert arming.pump(after(1), sink) == ()
    assert len(sink.calls) == 1

    assert arming.pump(after(2), sink) and len(sink.calls) == 2
    assert sink.calls[1][4] == frozen[1] == "YES"
    assert [event.event_id for event in arming.log] == ["C02:reply:1", "C02:reply:2"]


def test_c02_cannot_deliver_its_literal_reply_first(built: dict[str, ScenarioProgram]) -> None:
    """Two asks at once still deliver the first reply first: order is the frozen document's."""
    arming, sink = drive(built["C02"], [2])

    assert [call[1] for call in sink.calls] == ["sur1-reply-C02-1", "sur1-reply-C02-2"]
    assert [event.event_id for event in arming.log] == ["C02:reply:1", "C02:reply:2"]


# ------------------------------------------------------------------------ C06's movement


def test_c06_cannot_move_stock_before_its_decision_and_moves_it_once_after(
    built: dict[str, ScenarioProgram],
) -> None:
    """The world moves *after* the decision, and the decision is the reply being delivered."""
    arming = Arming.arm(built["C06"])
    sink = RecordingSink()

    assert arming.pump(after(0), sink) == ()
    assert sink.calls == []

    fired = arming.pump(after(1), sink)

    assert [event.event_id for event in fired] == ["C06:reply:1", "C06:stock:1"]
    assert [call[0] for call in sink.calls] == ["reply", "stock"]
    assert sink.calls[1] == ("stock", "res-strawberries", "-5.6", "counter-sales:ord-b", "ord-b")

    for asks in (1, 2, 5):
        assert arming.pump(after(asks), sink) == ()
    assert len([call for call in sink.calls if call[0] == "stock"]) == 1


def test_c06_arms_its_movement_on_the_reply_that_carries_the_decision(
    built: dict[str, ScenarioProgram],
) -> None:
    movement = next(event for event in plan(built["C06"]) if event.kind == STOCK_MOVEMENT)
    reply = next(event for event in plan(built["C06"]) if event.kind == REPLY_DELIVERY)

    assert isinstance(movement.trigger, EventCompleted)
    assert movement.trigger.event_id == reply.event_id
    assert movement.sequence > reply.sequence


def test_c06_declares_the_quantity_the_frozen_document_states(
    built: dict[str, ScenarioProgram],
) -> None:
    declared = next(event for event in built["C06"].armed if isinstance(event, WorldMoves))
    movement = next(event for event in plan(built["C06"]) if event.kind == STOCK_MOVEMENT)

    assert isinstance(movement.action, MoveStock)
    assert movement.action.delta == declared.delta == Decimal("-5.6")
    assert movement.action.resource == declared.resource_id


# ----------------------------------------------------------------------- C07's duplicate


def test_c07_delivers_one_provider_identity_twice_and_not_two_replies(
    built: dict[str, ScenarioProgram],
) -> None:
    """One decision seen twice. Two identities would be two decisions, which is another world."""
    planned = plan(built["C07"])
    arming, sink = drive(built["C07"], [1])

    assert len(planned) == 1
    assert isinstance(planned[0].action, DeliverReply)
    assert planned[0].action.deliveries == 2

    assert len(sink.calls) == 2
    assert {call[1] for call in sink.calls} == {"sur1-reply-C07-1"}
    assert [call[5] for call in sink.calls] == [1, 2]
    assert {call[4] for call in sink.calls} == {"YES"}
    assert len(arming.log) == 1
    assert len(arming.log[0].receipts) == 2


def test_every_other_scenario_delivers_its_one_reply_exactly_once(
    built: dict[str, ScenarioProgram],
) -> None:
    """``C07`` is the only scenario the frozen document gives a second delivery to."""
    for scenario_id in sorted(set(EVENTFUL) - {"C02", "C07"}):
        _, sink = drive(built[scenario_id], [1, 1, 1])

        assert [call[0] for call in sink.calls if call[0] == "reply"] == ["reply"], scenario_id


def test_c02_delivers_each_of_its_two_replies_exactly_once(
    built: dict[str, ScenarioProgram],
) -> None:
    _, sink = drive(built["C02"], [1, 1, 2, 2, 3])
    replies = [call for call in sink.calls if call[0] == "reply"]

    assert [call[1] for call in replies] == ["sur1-reply-C02-1", "sur1-reply-C02-2"]
    assert all(call[6] == 1 for call in replies)


# ------------------------------------------------------------------------ C09's scarcity


def test_c09_declares_its_scarcity_and_fires_nothing_for_it(
    built: dict[str, ScenarioProgram],
) -> None:
    """The shortage is a quantity in the starting ledger, not a rule the world applies."""
    scarcity = [event for event in built["C09"].armed if isinstance(event, Scarcity)]
    planned = plan(built["C09"])

    assert len(scarcity) == 1
    assert scarcity[0].group == "g-strawberries"
    assert scarcity[0].members == ("ord-a", "ord-b")
    assert scarcity[0].max_recovered == 1
    assert scarcity[0].min_recovered_for_complete == 1

    assert declared_without_firing(built["C09"]) == tuple(scarcity)
    assert [event.kind for event in planned] == [REPLY_DELIVERY]

    _, sink = drive(built["C09"], [1, 2, 3])

    assert [call[0] for call in sink.calls] == ["reply"]


def test_only_c09_declares_something_that_fires_nothing(
    built: dict[str, ScenarioProgram],
) -> None:
    for scenario_id in NINE:
        expected = ("scarcity g-strawberries",) if scenario_id == "C09" else ()
        assert (
            tuple(event.name for event in declared_without_firing(built[scenario_id])) == expected
        ), scenario_id


# ------------------------------------------------------------- once, closed, and forgotten


def test_an_event_fires_once_however_often_the_world_is_pumped(
    built: dict[str, ScenarioProgram],
) -> None:
    for scenario_id in EVENTFUL:
        arming, _ = drive(built[scenario_id], [5] * 6)
        identities = [event.event_id for event in arming.log]

        assert len(identities) == len(set(identities)) == len(arming.planned), scenario_id
        assert arming.pending == ()


def test_an_event_the_world_could_not_perform_fails_the_whole_arming_closed(
    built: dict[str, ScenarioProgram],
) -> None:
    """A half-fired world is not one an attempt was set up in, so it refuses every later pump."""
    arming = Arming.arm(built["C06"])
    sink = RecordingSink(refuse=STOCK_MOVEMENT)

    with pytest.raises(EventFiringError) as refusal:
        arming.pump(after(1), sink)

    assert "C06:stock:1" in str(refusal.value)
    assert arming.state == FAILED

    with pytest.raises(EventFiringError) as later:
        arming.pump(after(1), RecordingSink())

    assert "half" in str(later.value)


def test_a_failed_arming_keeps_what_did_happen_and_claims_nothing_more(
    built: dict[str, ScenarioProgram],
) -> None:
    """The reply really was delivered. A failure that unsaid it would be an undo."""
    arming = Arming.arm(built["C06"])

    with pytest.raises(EventFiringError):
        arming.pump(after(1), RecordingSink(refuse=STOCK_MOVEMENT))

    assert [event.event_id for event in arming.log] == ["C06:reply:1"]
    assert [event.event_id for event in arming.pending] == ["C06:stock:1"]


def test_a_reset_arming_starts_from_nothing_that_happened(
    built: dict[str, ScenarioProgram],
) -> None:
    arming, sink = drive(built["C06"], [1])

    assert arming.log and arming.pending == ()

    arming.reset()

    assert arming.log == ()
    assert arming.completed == frozenset()
    assert arming.pending == arming.planned
    assert arming.state == ARMED

    again = RecordingSink()
    arming.pump(after(1), again)

    assert [call[0] for call in again.calls] == ["reply", "stock"]
    assert again.calls == sink.calls


def test_a_reset_clears_a_failed_arming_as_well(built: dict[str, ScenarioProgram]) -> None:
    arming = Arming.arm(built["C06"])
    with pytest.raises(EventFiringError):
        arming.pump(after(1), RecordingSink(refuse=REPLY_DELIVERY))

    arming.reset()

    assert arming.state == ARMED
    assert arming.pending == arming.planned


def test_no_armed_event_leaks_between_two_scenarios(built: dict[str, ScenarioProgram]) -> None:
    """Every event id carries its own scenario, and two armings share no object."""
    first = Arming.arm(built["C02"])
    second = Arming.arm(built["C06"])
    first.pump(after(2), RecordingSink())

    assert second.log == ()
    assert second.completed == frozenset()
    assert all(event.event_id.startswith("C02:") for event in first.planned)
    assert all(event.event_id.startswith("C06:") for event in second.planned)
    assert first.fired is not second.fired


# ------------------------------------------------------------------- the realisation


@dataclass(slots=True)
class FakeInstaller:
    """Records what a realisation asked it to write, and refuses when told to."""

    loaded: list[str] = field(default_factory=list)
    crossed: list[str] = field(default_factory=list)
    refuse: str = ""

    def load(self, program: ScenarioProgram) -> str:
        if self.refuse == "load":
            raise PreparationError(f"{program.scenario_id}'s world could not be installed")
        self.loaded.append(program.scenario_id)
        return f"load:hollow-oak+sur1-{program.scenario_id}"

    def cross(self, step: Any, handles: Any) -> str:
        if self.refuse == "cross":
            raise PreparationError(f"the order system did not accept {step.order_id}")
        self.crossed.append(step.order_id)
        return f"external-change:{step.order_id}->{step.to_version_id}"


def realised(program: ScenarioProgram, installer: FakeInstaller) -> Realisation:
    return realise(program, handles=None, sink=RecordingSink(), installer=installer)  # type: ignore[arg-type]


def test_every_scenario_realises_ready_with_its_world_installed_and_its_events_armed(
    built: dict[str, ScenarioProgram],
) -> None:
    """All nine, which is the thing that used to be refused for eight of them."""
    for scenario_id in NINE:
        installer = FakeInstaller()
        realisation = realised(built[scenario_id], installer)

        assert realisation.state == READY and realisation.ready, scenario_id
        assert installer.loaded == [scenario_id]
        assert realisation.applied[0] == f"load:hollow-oak+sur1-{scenario_id}"
        assert realisation.arming.state == ARMED
        assert realisation.arming.log == ()
        assert realisation.arming.pending == realisation.arming.planned
        assert realisation.digest


def test_a_realisation_installs_the_world_before_it_crosses_an_external_change(
    built: dict[str, ScenarioProgram],
) -> None:
    """A change posted before the load would be an event about a world about to be replaced."""
    for scenario_id, order in (("C05", "ord-d"), ("C08", "ord-e")):
        installer = FakeInstaller()
        realisation = realised(built[scenario_id], installer)

        assert installer.crossed == [order], scenario_id
        assert realisation.applied[0].startswith("load:")
        assert realisation.applied[1].startswith(f"external-change:{order}")


def test_only_the_two_scenarios_the_contract_stipulates_cross_the_order_system(
    built: dict[str, ScenarioProgram],
) -> None:
    for scenario_id in NINE:
        installer = FakeInstaller()
        realised(built[scenario_id], installer)
        repins = [step for step in built[scenario_id].steps if isinstance(step, ExternalRepin)]

        assert len(installer.crossed) == len(repins), scenario_id
        assert bool(installer.crossed) == (scenario_id in {"C05", "C08"})


def test_a_failed_install_never_reports_ready(built: dict[str, ScenarioProgram]) -> None:
    installer = FakeInstaller(refuse="load")

    with pytest.raises(PreparationError) as refusal:
        realised(built["C01"], installer)

    assert "could not be installed" in str(refusal.value)
    assert installer.loaded == []


def test_a_failed_external_change_never_reports_ready(
    built: dict[str, ScenarioProgram],
) -> None:
    installer = FakeInstaller(refuse="cross")

    with pytest.raises(PreparationError) as refusal:
        realised(built["C05"], installer)

    assert "did not accept ord-d" in str(refusal.value)
    assert installer.crossed == []


def test_a_world_whose_events_nothing_could_perform_is_refused_before_it_is_installed(
    built: dict[str, ScenarioProgram],
) -> None:
    installer = FakeInstaller()

    with pytest.raises(PreparationError) as refusal:
        realise(built["C01"], handles=None, sink=None, installer=installer)  # type: ignore[arg-type]

    assert "no sink was given" in str(refusal.value)
    assert installer.loaded == []


def test_an_unfireable_scenario_is_refused_before_anything_is_written() -> None:
    """Planning comes first on purpose: the world would install and then owe an impossible reply."""

    @dataclass(frozen=True, slots=True)
    class WeatherTurns(ArmedEvent):
        pass

    program = ScenarioProgram(
        scenario_id="CXX",
        slug="invented",
        dimension="invented",
        steps=(),
        armed=(WeatherTurns(name="it rains", trigger="unobservable", effect="nothing here"),),
    )
    installer = FakeInstaller()

    with pytest.raises(PreparationError) as refusal:
        realise(program, handles=None, sink=RecordingSink(), installer=installer)  # type: ignore[arg-type]

    assert "it rains" in str(refusal.value)
    assert installer.loaded == []


def test_a_starting_world_that_is_not_the_declared_one_refuses_before_it_is_installed(
    built: dict[str, ScenarioProgram],
) -> None:
    """The freeze is checked against the object about to be written, not after the fact."""
    drifted = replace(built["C01"], steps=built["C09"].steps)
    installer = FakeInstaller()

    with pytest.raises(PreparationError) as refusal:
        realised(drifted, installer)

    assert "is not the declared one" in str(refusal.value)
    assert installer.loaded == []


def test_a_scenario_the_declaration_does_not_carry_refuses(
    built: dict[str, ScenarioProgram],
) -> None:
    unknown = replace(built["C04"], scenario_id="CXX")

    with pytest.raises(PreparationError) as refusal:
        realised(unknown, FakeInstaller())

    assert "not in the frozen world-program declaration" in str(refusal.value)


def test_a_retry_begins_from_a_fresh_world_and_a_fresh_arming(
    built: dict[str, ScenarioProgram],
) -> None:
    """Nothing an attempt did survives into the next try at the same scenario."""
    first = realised(built["C06"], FakeInstaller())
    first.arming.pump(after(1), RecordingSink())

    assert first.arming.pending == ()

    second = realised(built["C06"], FakeInstaller())

    assert second.arming is not first.arming
    assert second.arming.log == ()
    assert second.arming.pending == second.arming.planned
    assert second.digest == first.digest


def test_two_scenarios_realised_in_turn_share_no_event_state(
    built: dict[str, ScenarioProgram],
) -> None:
    earlier = realised(built["C02"], FakeInstaller())
    earlier.arming.pump(after(2), RecordingSink())
    later = realised(built["C07"], FakeInstaller())

    assert later.arming.log == ()
    assert {event.event_id for event in later.arming.planned} == {"C07:reply:1"}
    assert earlier.arming.completed == {"C02:reply:1", "C02:reply:2"}


def test_a_realisation_describes_itself_without_naming_an_arm(
    built: dict[str, ScenarioProgram],
) -> None:
    """What a capture would carry. A receipt naming an arm would be a receipt about one run."""
    payload = realised(built["C06"], FakeInstaller()).describes()

    assert payload["state"] == READY
    assert payload["scenario"] == "C06"
    assert [event["event_id"] for event in payload["armed"]["planned"]] == [
        "C06:reply:1",
        "C06:stock:1",
    ]
    assert payload["armed"]["fired"] == []
    rendered = repr(payload)
    assert not any(arm in rendered for arm in ARMS)
