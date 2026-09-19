"""What the world does during an attempt, and the observable signal that makes it do it.

:mod:`~scripts.sur1.bindings.programs` declares that a scenario owes the world something -- a
customer reply to an ask nobody has sent yet, that reply delivered a second time by the
provider, the strawberry stock moving after a decision about it. It declares them and stops
there, deliberately: a reply written into the starting state is a world in which somebody
answered a question nobody asked. This module is the other half. It says *when* each declared
event happens, *what* it does, *how many times* it may happen, and *in what order* -- and it
says all four from the frozen declaration alone.

**A trigger is an observable fact about the world, never a guess about the clock.** There is no
sleep here, no timeout, no polling interval and no "after the arm has had a moment". An event
becomes due when something the world's own records already show has happened: an outbound
message has reached a channel address, or an earlier declared event has completed. Those two
are the whole trigger vocabulary, and :class:`Observation` is the whole of what a trigger may
read -- a count of asks per channel and the set of events already fired. It is that small on
purpose. An arm's identity, an expected disposition, a scorer's reading and a wall clock are
not expressible in it, so a trigger cannot consult one even by mistake.

**The same observable sequence produces the same mutations for every arm.** The count of asks
is taken from the channel record, which holds the product's own outbox and the harness's own
transport alike; an arm that is PromisePatch and an arm that is not both reach a channel by
putting a message on it, and the world answers the message rather than the sender. That is what
makes "all three arms met the same world" a property of this file rather than a claim about
three setups.

**One reply is one message identity however many times it is delivered.** ``C07`` stipulates a
provider that delivers one customer message twice. It is modelled as one event performing two
deliveries under one ``message_id``, not as two events: two independent replies would be two
decisions, and the scenario is about one decision seen twice.

**Firing is one-shot and fails closed.** An event that has fired is never re-armed within an
attempt; an action that raises marks the whole arming ``FAILED`` and refuses every later pump,
because a half-fired world is a world an attempt was not set up in. The ledger's own uniqueness
on ``(source_kind, source_id)`` is the second, independent guard on the stock movement.

**Nothing here has been run against a driven arm.** This module is exercised entirely from
controlled observations; no arm has been constructed, no model reached and no capture written.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final, Protocol

from scripts.sur1.bindings.programs import (
    ArmedEvent,
    ScenarioProgram,
    ScriptedReply,
    WorldMoves,
    sha,
)

OUTBOUND: Final = "OUTBOUND"
"""The direction of an ask. Read off the channel record, never inferred from a text."""

REPLY_DELIVERY: Final = "REPLY_DELIVERY"
STOCK_MOVEMENT: Final = "STOCK_MOVEMENT"
"""The two kinds of thing the world does during an attempt. A third would be a new scenario."""

ARMED: Final = "ARMED"
FAILED: Final = "FAILED"
"""An arming is one or the other. There is no partly-armed state a run could proceed from."""

COUNTER_SALES: Final = "counter-sales"
"""The source identity a stock movement posts under, prefixed ``sur1:`` by the writer.

Unique per order, which makes the append-only ledger's own uniqueness constraint a second and
independent one-shot guarantee: a movement that somehow fired twice is a unique violation in
PostgreSQL rather than a quantity counted twice.
"""


class EventPlanError(RuntimeError):
    """A declared event could not be mapped honestly onto an observable trigger.

    Raised while the plan is built, before anything is installed. A scenario whose stipulated
    event nothing can fire must refuse to be realised: an attempt driven at it would be an
    attempt at a scenario whose facts never happen, and the number would look exactly like a
    number about the scenario.
    """


class EventFiringError(RuntimeError):
    """An armed event was due and the world could not perform it."""


# ------------------------------------------------------------------ what a trigger may read


class ObservedMessage(Protocol):
    """The two fields of a channel record a trigger is allowed to see."""

    channel_address: str
    direction: str


@dataclass(frozen=True, slots=True)
class Observation:
    """Everything a trigger may consult about the world, and nothing else.

    Two fields. How many asks have reached each channel address since the attempt began, and
    which declared events have already completed. There is no arm here, no model, no budget, no
    expected disposition and no clock, so a trigger written against this type cannot read one.
    """

    asks: Mapping[str, int] = field(default_factory=dict)
    completed: frozenset[str] = frozenset()

    def asks_on(self, channel: str) -> int:
        return int(self.asks.get(channel, 0))


def observe(messages: Iterable[ObservedMessage], *, completed: Iterable[str] = ()) -> Observation:
    """Reduce a channel record to the observation a trigger reads.

    Outbound only. A reply the world itself delivered is inbound and must never count as an ask,
    or a scenario owing two replies would answer its own first one.
    """
    asks: dict[str, int] = {}
    for message in messages:
        if message.direction != OUTBOUND:
            continue
        asks[message.channel_address] = asks.get(message.channel_address, 0) + 1
    return Observation(asks=dict(sorted(asks.items())), completed=frozenset(completed))


# ------------------------------------------------------------------------------- triggers


@dataclass(frozen=True, slots=True)
class Trigger:
    """The observable condition under which one declared event becomes due."""

    def due(self, observation: Observation) -> bool:
        raise NotImplementedError

    def describes(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class AskReachesChannel(Trigger):
    """The ``ordinal``-th outbound message has reached this channel address.

    Ordinal rather than a boolean because a scenario may owe more than one reply on one channel:
    ``C02``'s second reply is due when a second ask arrives, which is what keeps the two in the
    order the frozen document lists them without either event having to know about the other.
    """

    channel: str = ""
    ordinal: int = 1

    def due(self, observation: Observation) -> bool:
        return observation.asks_on(self.channel) >= self.ordinal

    def describes(self) -> dict[str, Any]:
        return {"trigger": "ask_reaches_channel", "channel": self.channel, "ordinal": self.ordinal}


@dataclass(frozen=True, slots=True)
class EventCompleted(Trigger):
    """An earlier declared event of this same scenario has finished.

    This is how *the world moves after the decision* is expressed without the world having to
    decide anything: the decision became observable when the reply carrying it was delivered,
    and the movement is armed on that delivery rather than on an opinion about what an arm did
    with it.
    """

    event_id: str = ""

    def due(self, observation: Observation) -> bool:
        return self.event_id in observation.completed

    def describes(self) -> dict[str, Any]:
        return {"trigger": "event_completed", "after": self.event_id}


# -------------------------------------------------------------------------------- actions


class WorldSink(Protocol):
    """The world's own two powers, which no arm holds and nothing in this module performs.

    Kept a protocol so the event model stays pure: the plan, the triggers and the ordering are
    checkable with no database, no order system and no channel, which is the only way they could
    be proved before a run is bought.
    """

    def deliver_reply(
        self,
        *,
        message_id: str,
        channel: str,
        order: str,
        text: str,
        delivery: int,
        deliveries: int,
    ) -> str: ...

    def move_stock(self, *, resource: str, delta: Decimal, source_id: str, order: str) -> str: ...


@dataclass(frozen=True, slots=True)
class Action:
    """What the world does once an event is due."""

    def perform(self, sink: WorldSink) -> tuple[str, ...]:
        raise NotImplementedError

    def describes(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class DeliverReply(Action):
    """Put one stipulated customer message on the channel, once per stipulated delivery.

    ``message_id`` is the provider's identity for the message and is the same string for every
    delivery of it. That is the whole of ``C07``: one decision, delivered twice, and an arm that
    produces two effects from it has done something the world did not.
    """

    message_id: str = ""
    channel: str = ""
    order: str = ""
    text: str = ""
    deliveries: int = 1

    def perform(self, sink: WorldSink) -> tuple[str, ...]:
        return tuple(
            sink.deliver_reply(
                message_id=self.message_id,
                channel=self.channel,
                order=self.order,
                text=self.text,
                delivery=delivery,
                deliveries=self.deliveries,
            )
            for delivery in range(1, self.deliveries + 1)
        )

    def describes(self) -> dict[str, Any]:
        return {
            "action": "deliver_reply",
            "message_id": self.message_id,
            "channel": self.channel,
            "order": self.order,
            "text": self.text,
            "deliveries": self.deliveries,
        }


@dataclass(frozen=True, slots=True)
class MoveStock(Action):
    """Post one signed physical movement to the append-only ledger, exactly once.

    A posting and never an edit of a total, for the same reason
    :class:`~scripts.sur1.bindings.programs.SpoilStock` is: the ledger is the record of what was
    attested and a total is a derivation nothing here owns.
    """

    resource: str = ""
    delta: Decimal = Decimal("0")
    order: str = ""

    @property
    def source_id(self) -> str:
        return f"{COUNTER_SALES}:{self.order}"

    def perform(self, sink: WorldSink) -> tuple[str, ...]:
        return (
            sink.move_stock(
                resource=self.resource,
                delta=self.delta,
                source_id=self.source_id,
                order=self.order,
            ),
        )

    def describes(self) -> dict[str, Any]:
        return {
            "action": "move_stock",
            "resource": self.resource,
            "delta": str(self.delta),
            "order": self.order,
            "source_id": self.source_id,
        }


# ------------------------------------------------------------------------------ the plan


@dataclass(frozen=True, slots=True)
class PlannedEvent:
    """One declared event, with its identity, its trigger, its action and its place in order."""

    event_id: str
    kind: str
    sequence: int
    declared: str
    trigger: Trigger
    action: Action

    def describes(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "sequence": self.sequence,
            "declared": self.declared,
            **self.trigger.describes(),
            **self.action.describes(),
        }


def reply_event_id(scenario_id: str, ordinal: int) -> str:
    return f"{scenario_id}:reply:{ordinal}"


def movement_event_id(scenario_id: str, ordinal: int) -> str:
    return f"{scenario_id}:stock:{ordinal}"


def plan(program: ScenarioProgram) -> tuple[PlannedEvent, ...]:
    """Derive one scenario's firing plan from what its program already declares.

    Nothing is invented and nothing is chosen: the replies are the frozen ``consent_facts`` in
    the order the document lists them, the delivery count is the frozen ``duplicate_deliveries``
    entry, and the movement is the frozen ``stale_after`` entry armed on the reply that carries
    the decision it comes after. A declared event this function cannot map raises, which is the
    refusal that keeps an unrealisable scenario out of a scored run.
    """
    planned: list[PlannedEvent] = []
    replies = 0
    movements = 0
    per_channel: dict[str, int] = {}
    decided: dict[str, str] = {}
    for sequence, declared in enumerate(program.armed):
        if isinstance(declared, ScriptedReply):
            replies += 1
            ordinal = per_channel.get(declared.channel, 0) + 1
            per_channel[declared.channel] = ordinal
            event_id = reply_event_id(program.scenario_id, replies)
            if declared.authorising:
                decided[declared.order] = event_id
            planned.append(
                PlannedEvent(
                    event_id=event_id,
                    kind=REPLY_DELIVERY,
                    sequence=sequence,
                    declared=declared.name,
                    trigger=AskReachesChannel(channel=declared.channel, ordinal=ordinal),
                    action=DeliverReply(
                        message_id=f"sur1-reply-{program.scenario_id}-{replies}",
                        channel=declared.channel,
                        order=declared.order,
                        text=declared.text,
                        deliveries=declared.deliveries,
                    ),
                )
            )
            continue
        if isinstance(declared, WorldMoves):
            after = decided.get(declared.order)
            if after is None:
                raise EventPlanError(
                    f"{program.scenario_id} stipulates the world moving after {declared.order} "
                    f"decides, and declares no authorising reply for {declared.order} that the "
                    "movement could be armed on; there is no observable moment to fire it at"
                )
            movements += 1
            planned.append(
                PlannedEvent(
                    event_id=movement_event_id(program.scenario_id, movements),
                    kind=STOCK_MOVEMENT,
                    sequence=sequence,
                    declared=declared.name,
                    trigger=EventCompleted(event_id=after),
                    action=MoveStock(
                        resource=declared.resource_id,
                        delta=declared.delta,
                        order=declared.order,
                    ),
                )
            )
            continue
        if not type(declared).must_fire:
            continue
        raise EventPlanError(
            f"{program.scenario_id} declares {declared.name!r}, a "
            f"{type(declared).__name__} that must happen during an attempt and that no trigger "
            "in this model can honestly observe"
        )
    return tuple(planned)


def declared_without_firing(program: ScenarioProgram) -> tuple[ArmedEvent, ...]:
    """The declared events already true of the starting world, which fire nothing.

    ``C09``'s contention is the whole of this list: the shortage is a quantity in the ledger and
    not a rule the world applies, so there is nothing for an attempt to wait for.
    """
    return tuple(event for event in program.armed if not type(event).must_fire)


# --------------------------------------------------------------------------- the arming


@dataclass(frozen=True, slots=True)
class FiredEvent:
    """One event that happened, and what the world recorded for it."""

    event_id: str
    kind: str
    receipts: tuple[str, ...]

    def describes(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "kind": self.kind, "receipts": list(self.receipts)}


@dataclass(slots=True)
class Arming:
    """One attempt's armed events: what is pending, what has fired, and nothing from before.

    Created fresh by :func:`~scripts.sur1.bindings.realisation.realise` for each attempt, so
    there is no object in which an event could survive between two scenarios or between two
    tries at one. :meth:`reset` exists for a caller that holds one across a retry, and is the
    same statement made explicitly.
    """

    scenario_id: str
    planned: tuple[PlannedEvent, ...]
    state: str = ARMED
    fired: dict[str, FiredEvent] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)

    @classmethod
    def arm(cls, program: ScenarioProgram) -> Arming:
        return cls(scenario_id=program.scenario_id, planned=plan(program))

    @property
    def pending(self) -> tuple[PlannedEvent, ...]:
        return tuple(event for event in self.planned if event.event_id not in self.fired)

    @property
    def completed(self) -> frozenset[str]:
        return frozenset(self.fired)

    @property
    def log(self) -> tuple[FiredEvent, ...]:
        return tuple(self.fired[event_id] for event_id in self.order)

    def reset(self) -> None:
        """Forget every fired event and re-arm. A retry begins from nothing that happened."""
        self.fired.clear()
        self.order.clear()
        self.state = ARMED

    def pump(self, observation: Observation, sink: WorldSink) -> tuple[FiredEvent, ...]:
        """Fire every event this observation makes due, in declared order, to a fixed point.

        The loop repeats because firing one event can make another due: a movement armed on a
        reply becomes due the moment that reply is delivered, in the same pump, without the
        caller having to know which event depends on which.
        """
        if self.state != ARMED:
            raise EventFiringError(
                f"{self.scenario_id}'s armed events are {self.state}; a world whose events half "
                "fired is not a world an attempt was set up in"
            )
        happened: list[FiredEvent] = []
        while True:
            due = self._next_due(observation, happened)
            if due is None:
                return tuple(happened)
            happened.append(self._fire(due, sink))

    def _next_due(
        self, observation: Observation, happened: Sequence[FiredEvent]
    ) -> PlannedEvent | None:
        """The lowest-sequence pending event this observation makes due, or nothing."""
        seen = self.completed | {event.event_id for event in happened}
        current = Observation(asks=observation.asks, completed=observation.completed | seen)
        for event in sorted(self.planned, key=lambda event: event.sequence):
            if event.event_id in seen:
                continue
            if event.trigger.due(current):
                return event
        return None

    def _fire(self, event: PlannedEvent, sink: WorldSink) -> FiredEvent:
        """Perform one event's action exactly once, or fail the whole arming closed."""
        try:
            receipts = event.action.perform(sink)
        except Exception as failure:
            self.state = FAILED
            raise EventFiringError(
                f"{self.scenario_id} could not perform {event.event_id}: "
                f"{type(failure).__name__}: {failure}"
            ) from failure
        happened = FiredEvent(event_id=event.event_id, kind=event.kind, receipts=receipts)
        self.fired[event.event_id] = happened
        self.order.append(event.event_id)
        return happened

    def describes(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario_id,
            "state": self.state,
            "planned": [event.describes() for event in self.planned],
            "fired": [event.describes() for event in self.log],
        }

    def log_digest(self) -> str:
        """The identity of what actually happened, so two runs of one sequence are comparable."""
        return sha({"scenario": self.scenario_id, "fired": [e.describes() for e in self.log]})


def plan_digest(program: ScenarioProgram) -> str:
    """The identity of one scenario's firing plan, independent of anything that ran."""
    return sha(
        {
            "scenario": program.scenario_id,
            "planned": [event.describes() for event in plan(program)],
            "declared_without_firing": [event.name for event in declared_without_firing(program)],
        }
    )


__all__ = [
    "ARMED",
    "COUNTER_SALES",
    "FAILED",
    "OUTBOUND",
    "REPLY_DELIVERY",
    "STOCK_MOVEMENT",
    "Action",
    "Arming",
    "AskReachesChannel",
    "DeliverReply",
    "EventCompleted",
    "EventFiringError",
    "EventPlanError",
    "FiredEvent",
    "MoveStock",
    "Observation",
    "ObservedMessage",
    "PlannedEvent",
    "Trigger",
    "WorldSink",
    "declared_without_firing",
    "movement_event_id",
    "observe",
    "plan",
    "plan_digest",
    "reply_event_id",
]
