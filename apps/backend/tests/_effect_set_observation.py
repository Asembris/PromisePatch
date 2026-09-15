"""Reading a running case the way the frozen manifest counts: four partitions and five effects.

The manifest declares, per scenario and per checkpoint, which orders fall in which partition and
what was *done* to each of them. This module is the other half of that sentence: it reads those
same two things off a real case in a real database, with a real order system beside it, and
hands them back as whole sets and a whole multiset so the judge can compare them exactly.

Three properties matter and are deliberate.

**It observes and never expects.** Nothing here reads the manifest, holds a label, or knows what
any scenario declares. It reports what the world holds; ``_effect_set_judge`` decides whether
that is what was promised. The two live apart so that no future edit can make a reading quietly
agree with an expectation.

**Effects are counted from durable conditions, not intentions.** An amendment counts when the
order system accepted it, a message when the provider took it, a reservation change when the set
of claims is no longer the set this window opened with, a hold when this case is the holder, and
an escalation when the track ended on the owner's desk. Case tracks, analysis rows and audit
rows record that a promise was *considered*; the manifest is explicit that considering is
evidence rather than an effect, and none of them is counted.

**Attribution is by window and by identity.** A :class:`Baseline` is taken the instant before the
incident opens, and every count is measured against it and against this case's own id. An
external edit a customer made in the order system is that customer's own command, before or
after the exception, and can never become an incident-caused effect.

Lifted verbatim from ``test_whole_delivery_counterfactual.py``, which was the first test to need
it, so that the suite counts effects in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from _effect_set_judge import Observation
from _effect_sets import Effects, Partition, orders
from _intake_support import Intake
from _order_system_support import Boundary
from sqlalchemy import select

from promise_graph.model import Classification
from promisepatch.db.models import OutboxMessage, Reservation
from promisepatch.domain import recovery
from promisepatch.domain.approvals import EFFECT_MESSAGE_SEND
from promisepatch.domain.model import EFFECT_CASE_ID, EFFECT_ORDER_AMEND, EFFECT_TRACK_ID

ORDERS: Final = orders()
"""The manifest's own order table: which promise, line and external id each label names."""

PARTITION_OF: Final = {
    Classification.AUTO_RECOVERABLE.value: "auto_repairable",
    Classification.APPROVAL_REQUIRED.value: "consent_required",
    Classification.BLOCKED.value: "blocked",
    Classification.UNAFFECTED.value: "untouched",
}
"""The manifest's four partitions, said in the durable vocabulary the tracks are stored in.

Definitional, and a straight reading of the manifest's own ``vocabulary.partitions`` text: a
recovery the constraints already permit, a recovery needing permission first, no recovery this
system may take, and an exception that does not threaten the promise. Nothing is inferred.
"""


@dataclass(frozen=True)
class Baseline:
    """What the world held the instant before the worker spoke.

    The incident window opens here, which is the whole of the attribution rule: an external edit
    already in both systems by this point cannot be counted against a case that has not started
    yet.
    """

    reservations: dict[str, frozenset[tuple[str, str, str]]]
    external_versions: dict[str, int]
    external_events: dict[str, int]


async def reservations_by_line(intake: Intake) -> dict[str, frozenset[tuple[str, str, str]]]:
    """Every reservation each of the six order lines holds, as a comparable set of claims."""
    async with intake.database.connect() as connection:
        rows = (await connection.execute(select(Reservation))).all()
    grouped: dict[str, set[tuple[str, str, str]]] = {
        order["line"]: set() for order in ORDERS.values()
    }
    for row in rows:
        if row.order_line_id in grouped:
            grouped[row.order_line_id].add(
                (row.resource_id, str(row.quantity), row.source_recipe_version_id)
            )
    return {line: frozenset(claims) for line, claims in grouped.items()}


async def baseline_of(intake: Intake, wired: Boundary) -> Baseline:
    return Baseline(
        reservations=await reservations_by_line(intake),
        external_versions={
            order["external_id"]: wired.external_order(order["external_id"]).version
            for order in ORDERS.values()
        },
        external_events={
            order["external_id"]: wired.simulator.event_count(order["external_id"])
            for order in ORDERS.values()
        },
    )


async def outbox_of(intake: Intake, case_id: UUID) -> list[Any]:
    """Every outbound effect this case enqueued, attributed by the payload's own case id."""
    async with intake.database.connect() as connection:
        return list(
            (
                await connection.execute(
                    select(OutboxMessage)
                    .where(OutboxMessage.payload[EFFECT_CASE_ID].astext == str(case_id))
                    .order_by(OutboxMessage.created_at)
                )
            ).all()
        )


async def partition_of(intake: Intake, case_id: UUID) -> Partition:
    """The four partitions, read from the durable tracks this case decided."""
    members: dict[str, set[str]] = {name: set() for name in PARTITION_OF.values()}
    by_promise = {track.promise_id: track for track in await intake.tracks(case_id)}
    for order, entry in ORDERS.items():
        track = by_promise.get(entry["promise"])
        assert track is not None, f"{order} has no track in this case"
        members[PARTITION_OF[track.classification]].add(order)
    return {name: frozenset(found) for name, found in members.items()}


async def census(intake: Intake, *, case_id: UUID, since: Baseline) -> Effects:
    """Every incident-caused operational effect this case produced, per order and kind.

    A case that has not decided anything yet has no tracks, and a promise with no track has had
    nothing done to it. That is a real state -- it is where an unanswered clarification leaves
    every promise -- so it counts as zero rather than raising.
    """
    tracks = {track.promise_id: track for track in await intake.tracks(case_id)}
    outbox = await outbox_of(intake, case_id)
    reservations = await reservations_by_line(intake)
    tasks = await intake.tasks()

    found: Effects = {}

    def record(order: str, kind: str, count: int) -> None:
        if count:
            found[(order, kind)] = count

    for order, entry in ORDERS.items():
        track = tracks.get(entry["promise"])
        mine = [
            row
            for row in outbox
            if track is not None
            and row.payload.get(EFFECT_TRACK_ID) == str(track.id)
            and row.state == "DELIVERED"
        ]
        record(order, "order_amendment", sum(row.kind == EFFECT_ORDER_AMEND for row in mine))
        record(order, "customer_message", sum(row.kind == EFFECT_MESSAGE_SEND for row in mine))
        record(
            order,
            "reservation_change",
            int(reservations[entry["line"]] != since.reservations[entry["line"]]),
        )
        held = tasks.get(f"task-{entry['line']}")
        record(order, "task_hold", int(held is not None and held[1] == case_id))
        escalated = track is not None and track.state == recovery.TRACK_ESCALATED
        record(order, "owner_escalation", int(escalated))
    return found


async def observe(intake: Intake, *, case_id: UUID, since: Baseline) -> Observation:
    """One checkpoint, read whole: the four partitions and the cumulative effect multiset.

    Both halves come from the same quiescent instant, which is what the manifest's checkpoints
    are: a scenario never depends on catching the system mid-step, so a caller reads only after
    asserting that nothing is outstanding.
    """
    return Observation(
        partition=await partition_of(intake, case_id),
        effects=await census(intake, case_id=case_id, since=since),
    )
