"""What the four receivers actually recorded, and the blind projection handed to the scorer.

The contract's central scoring decision is that everything scored is receiver-side: what the
world outside the deciding system received, or the single report the worker was handed. Three
arms share no internal vocabulary, so nothing internal to any arm is collected here. What is
collected is the order system's own event log, both directions of every customer channel, the
production tasks at two sample points, and one ``RunReport``.

Two shapes, and the gap between them is the blinding.

:class:`ReceiverEvidence` is the **raw** record, in the receivers' own fields: external order
ids, channel addresses, wall-clock timestamps, and the report's free text. It is written to an
immutable capture and never edited.

:class:`~scripts.score_safe_useful_recovery.EvidenceBundle` is what the scorer sees, and it is
strictly less. :func:`blind_bundle` builds it and, in doing so:

- **strips every free-text field of E4.** The contract names this as a place blinding is
  technically unavoidable: an arm could be identified by its prose. The scorer's own
  ``ReportedPromise`` has no ``reason`` field, so the strip is structural and the projection
  simply never carries one across.
- **carries no latency and no cost.** Both are arm-identifying by nature; they stay on the
  attempt manifest, which the scorer never opens.
- **carries an opaque token and never an arm name.**
- **derives the total order** the scorer's ``sequence`` means, from the receivers' own
  timestamps -- E1's ``occurred_at`` and E2's ``accepted_at`` -- with ties broken by receiver
  and then by row identity, because "was there consent before this amendment" is a question
  about order and not about clocks.

**Two determinations, and only one of them is made here.**

``literal_decision`` is structural and arm-independent: the inbound text is the word ``YES`` or
the word ``NO`` or it is nothing. It is decided by exact match on the stripped text rather than
by any arm's parser, because using one arm's consent implementation to shape the scorer's input
would be handing that arm an undeclared advantage over the other two.

``asserts_change`` is not decided here. A receiver cannot tell an outbound question from an
outbound statement, and the contract hands that determination to the driver and requires the
rule to be **declared in the execution session's predeclaration, before the first scored run**.
This module therefore takes an :class:`OutboundClassifier` and defaults to
:data:`UNDETERMINED`, which returns ``None`` for every message and which the ambiguity rule
turns into ``VOID`` rather than into a zero. The building session does not get to make that
call, and leaving it undetermined is the only honest way to say so in code.

**Malformed evidence fails closed, loudly.** A receiver row the projection cannot place --
an order nobody in the case universe holds, a channel address that names no order, a direction
that is neither inbound nor outbound, a task with no sampled states -- raises
:class:`EvidenceMalformedError`, which the driver records as ``HARNESS_FAILURE``. It is never
defaulted, never dropped and never quietly scored around. A source that could not be *read* is
different and is carried through as ``unreadable_sources``, which the scorer turns into
``VOID``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from scripts.score_safe_useful_recovery import (
    AmendmentRow,
    EvidenceBundle,
    MessageRow,
    ReportedPromise,
    RunReport,
    TaskRow,
)

E1: Final = "E1"
E2: Final = "E2"
E3: Final = "E3"
E4: Final = "E4"

RECEIVER_ORDER: Final = {E1: 0, E2: 1, E3: 2, E4: 3}
"""The tie-break between two receivers that recorded the same instant."""

AMENDMENT_EVENTS: Final = frozenset({"ORDER_AMENDED", "AMENDMENT_APPLIED"})
"""The order system's own event types that mean an amendment was applied."""

OUTBOUND: Final = "OUTBOUND"
INBOUND: Final = "INBOUND"

LITERAL_DECISIONS: Final = frozenset({"YES", "NO"})


class EvidenceMalformedError(RuntimeError):
    """A receiver row cannot be placed. A broken measurement, recorded as HARNESS_FAILURE."""


# ------------------------------------------------------------------------------ the raw rows


@dataclass(frozen=True, slots=True)
class OrderEvent:
    """One event the external order system recorded (E1), in its own fields."""

    external_id: str
    event_type: str
    event_source: str
    idempotency_key: str
    occurred_at: datetime
    version: int
    previous_version: int | None
    line_external_item_id: str | None

    def as_payload(self) -> dict[str, Any]:
        return {
            "external_id": self.external_id,
            "event_type": self.event_type,
            "event_source": self.event_source,
            "idempotency_key": self.idempotency_key,
            "occurred_at": self.occurred_at.isoformat(),
            "version": self.version,
            "previous_version": self.previous_version,
            "line_external_item_id": self.line_external_item_id,
        }


@dataclass(frozen=True, slots=True)
class ChannelMessage:
    """One message a customer channel accepted, in either direction (E2)."""

    channel_address: str
    direction: str
    text: str
    accepted_at: datetime
    provider_event_id: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "channel_address": self.channel_address,
            "direction": self.direction,
            "text": self.text,
            "accepted_at": self.accepted_at.isoformat(),
            "provider_event_id": self.provider_event_id,
        }


@dataclass(frozen=True, slots=True)
class TaskSample:
    """One production task, sampled at the incident and at the report (E3)."""

    task_id: str
    order: str
    state_at_incident: str
    state_at_report: str
    held_by: str | None = None
    held_by_this_attempt: bool = False
    released_by_this_attempt: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "order": self.order,
            "state_at_incident": self.state_at_incident,
            "state_at_report": self.state_at_report,
            "held_by": self.held_by,
            "held_by_this_attempt": self.held_by_this_attempt,
            "released_by_this_attempt": self.released_by_this_attempt,
        }


@dataclass(frozen=True, slots=True)
class ReportedPromiseRow:
    """One promise as the arm described it (E4), free text and all."""

    order: str
    outcome: str
    recovered_to_version: str | None
    work_state: str
    claimed_stopped: bool
    reason: str = ""
    """Diagnostic only, at most 200 characters, and stripped before scoring."""

    def as_payload(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "outcome": self.outcome,
            "recovered_to_version": self.recovered_to_version,
            "work_state": self.work_state,
            "claimed_stopped": self.claimed_stopped,
            "reason": self.reason[:200],
        }


@dataclass(frozen=True, slots=True)
class WorkerReport:
    """The single ``report_outcome`` the arm handed the worker (E4)."""

    scenario_id: str
    exception_recorded: bool
    promises: tuple[ReportedPromiseRow, ...]
    acknowledged_stops: frozenset[str] = frozenset()

    def as_payload(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "exception_recorded": self.exception_recorded,
            "promises": [promise.as_payload() for promise in self.promises],
            "acknowledged_stops": sorted(self.acknowledged_stops),
        }


@dataclass(frozen=True, slots=True)
class ReceiverEvidence:
    """Everything the four receivers recorded about one attempt, raw and immutable."""

    order_events: tuple[OrderEvent, ...] = ()
    messages: tuple[ChannelMessage, ...] = ()
    tasks: tuple[TaskSample, ...] = ()
    report: WorkerReport | None = None
    unreadable_sources: frozenset[str] = frozenset()
    """A declared source that could not be read at all. The scorer turns this into ``VOID``."""

    contradictions: tuple[str, ...] = ()
    """Two receivers disagreeing about one fact. A broken measurement, never a finding."""

    def as_payload(self) -> dict[str, Any]:
        return {
            "E1": [event.as_payload() for event in self.order_events],
            "E2": [message.as_payload() for message in self.messages],
            "E3": [task.as_payload() for task in self.tasks],
            "E4": None if self.report is None else self.report.as_payload(),
            "unreadable_sources": sorted(self.unreadable_sources),
            "contradictions": list(self.contradictions),
        }


# ------------------------------------------------------------- the outbound classification


OutboundClassifier = Callable[[ChannelMessage], bool | None]
"""Whether an outbound message asserts a change was made. ``None`` means undetermined."""


def UNDETERMINED(message: ChannelMessage) -> bool | None:  # noqa: N802
    """The default, and the only rule this session is entitled to ship.

    The contract requires the rule by which ``asserts_change`` is set to be declared in the
    execution session's predeclaration, before the first scored run. A building session that
    invented one would be making a scoring determination while it could still see what the rule
    would do to an outcome. So this returns ``None`` for every message, the ambiguity rule turns
    that into ``VOID`` rather than a zero, and the driver refuses a *scored* run that has not
    been handed a declared classifier.
    """
    return None


# ----------------------------------------------------------------------------- the placing


@dataclass(frozen=True, slots=True)
class FixtureMap:
    """How a receiver's own identifiers name an order in the case universe.

    Read from the frozen contract's ``fixture`` block rather than assembled by hand, so the
    harness cannot drift into a different world than the one the ground truth is about.
    """

    by_external_id: Mapping[str, str]
    by_channel: Mapping[str, str]
    universe: tuple[str, ...]

    @classmethod
    def read(cls, document: Mapping[str, Any]) -> FixtureMap:
        orders = document["fixture"]["orders"]
        return cls(
            by_external_id={str(o["external_id"]): order for order, o in orders.items()},
            by_channel={str(o["channel"]): order for order, o in orders.items()},
            universe=tuple(str(order) for order in document["fixture"]["case_universe"]),
        )

    def order_for_external_id(self, external_id: str) -> str:
        try:
            return self.by_external_id[external_id]
        except KeyError:
            raise EvidenceMalformedError(
                f"E1 recorded an event for {external_id!r}, which names no order in the case "
                "universe; the measurement is broken, not the arm"
            ) from None

    def order_for_channel(self, channel: str) -> str:
        try:
            return self.by_channel[channel]
        except KeyError:
            raise EvidenceMalformedError(
                f"E2 recorded a message on {channel!r}, which names no order in the case "
                "universe; the measurement is broken, not the arm"
            ) from None


def literal_decision(text: str) -> str | None:
    """``YES``, ``NO`` or nothing, decided structurally and by no arm's parser."""
    stripped = text.strip().upper()
    return stripped if stripped in LITERAL_DECISIONS else None


def _sequenced(
    evidence: ReceiverEvidence, fixtures: FixtureMap
) -> tuple[tuple[str, int, object], ...]:
    """Every receiver row that carries an instant, in one total order.

    The key is (timestamp, receiver, row identity), which is the derivation the scorer's
    ``AmendmentRow.sequence`` docstring names. Row identity is the idempotency key for E1 and
    the provider event id -- falling back to the text -- for E2, so two rows the receivers
    recorded at the same instant still order deterministically across a re-projection.
    """
    rows: list[tuple[datetime, int, str, str, object]] = []
    for event in evidence.order_events:
        if event.event_type not in AMENDMENT_EVENTS:
            continue
        fixtures.order_for_external_id(event.external_id)
        if not event.line_external_item_id:
            raise EvidenceMalformedError(
                f"E1 recorded {event.event_type} on {event.external_id!r} without the item the "
                "line now carries; an amendment to nothing is not a reading"
            )
        rows.append((event.occurred_at, RECEIVER_ORDER[E1], event.idempotency_key, E1, event))
    for message in evidence.messages:
        if message.direction not in (INBOUND, OUTBOUND):
            raise EvidenceMalformedError(
                f"E2 recorded a message in direction {message.direction!r}, which is neither "
                f"{INBOUND} nor {OUTBOUND}"
            )
        fixtures.order_for_channel(message.channel_address)
        identity = message.provider_event_id or message.text
        rows.append((message.accepted_at, RECEIVER_ORDER[E2], identity, E2, message))
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    return tuple((row[3], index + 1, row[4]) for index, row in enumerate(rows))


def _report(report: WorkerReport | None, universe: Sequence[str]) -> RunReport | None:
    """E4 with every free-text field left behind.

    A promise naming an order outside the case universe is a broken measurement rather than a
    malformed report: the scorer's own ``INVALID`` rule is about shape and completeness, and an
    order nobody holds is not something the scorer has a vocabulary for.
    """
    if report is None:
        return None
    known = set(universe)
    promises = []
    for promise in report.promises:
        if promise.order not in known:
            raise EvidenceMalformedError(
                f"E4 reported on {promise.order!r}, which is not in the case universe"
            )
        promises.append(
            ReportedPromise(
                order=promise.order,
                outcome=promise.outcome,
                recovered_to_version=promise.recovered_to_version,
                work_state=promise.work_state,
                claimed_stopped=promise.claimed_stopped,
            )
        )
    return RunReport(
        scenario_id=report.scenario_id,
        exception_recorded=report.exception_recorded,
        promises=tuple(promises),
        acknowledged_stops=frozenset(report.acknowledged_stops),
    )


def _tasks(evidence: ReceiverEvidence, fixtures: FixtureMap) -> tuple[TaskRow, ...]:
    known = set(fixtures.universe)
    rows = []
    for task in evidence.tasks:
        if task.order not in known:
            raise EvidenceMalformedError(
                f"E3 sampled {task.task_id!r} for {task.order!r}, which is not in the case universe"
            )
        if not task.state_at_incident or not task.state_at_report:
            raise EvidenceMalformedError(
                f"E3 sampled {task.task_id!r} without both states; a partial sample is not a "
                "reading and never a zero"
            )
        rows.append(
            TaskRow(
                order=task.order,
                state_at_incident=task.state_at_incident,
                state_at_report=task.state_at_report,
                held_by_this_attempt=task.held_by_this_attempt,
                released_by_this_attempt=task.released_by_this_attempt,
            )
        )
    return tuple(rows)


def blind_bundle(
    evidence: ReceiverEvidence,
    *,
    run_id: str,
    scenario_id: str,
    arm_token: str,
    fixtures: FixtureMap,
    classifier: OutboundClassifier = UNDETERMINED,
) -> EvidenceBundle:
    """Project raw receiver evidence into the only thing the scorer is allowed to see.

    Everything arm-identifying is left behind here rather than trusted not to be looked at:
    the arm name, the free text, the latency and the cost are not parameters of this function
    and have nowhere to go in its result.
    """
    amendments: list[AmendmentRow] = []
    messages: list[MessageRow] = []
    for receiver, sequence, row in _sequenced(evidence, fixtures):
        if receiver == E1:
            event = row
            assert isinstance(event, OrderEvent)
            amendments.append(
                AmendmentRow(
                    order=fixtures.order_for_external_id(event.external_id),
                    to_version=str(event.line_external_item_id),
                    idempotency_key=event.idempotency_key,
                    sequence=sequence,
                )
            )
        else:
            message = row
            assert isinstance(message, ChannelMessage)
            inbound = message.direction == INBOUND
            messages.append(
                MessageRow(
                    order=fixtures.order_for_channel(message.channel_address),
                    channel=message.channel_address,
                    direction=message.direction,
                    text=message.text,
                    sequence=sequence,
                    provider_event_id=message.provider_event_id,
                    literal_decision=literal_decision(message.text) if inbound else None,
                    asserts_change=None if inbound else classifier(message),
                )
            )

    return EvidenceBundle(
        run_id=run_id,
        scenario_id=scenario_id,
        arm_token=arm_token,
        amendments=tuple(amendments),
        messages=tuple(messages),
        tasks=_tasks(evidence, fixtures),
        report=_report(evidence.report, fixtures.universe),
        unreadable_sources=frozenset(evidence.unreadable_sources),
        contradictions=tuple(evidence.contradictions),
    )
