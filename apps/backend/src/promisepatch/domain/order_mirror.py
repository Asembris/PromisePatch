"""Applying an external order system's own changes to the mirror PromisePatch reads.

The external order system is the system of record. ``orders`` and ``order_lines`` here are a
*mirror* of it, and this module is the only thing in PromisePatch that applies an ordinary
customer change to them. A recovery amendment does not: it asks the order system to change the
order, and learns the result the same way every other change arrives -- through an event.

**Nothing decides here except what the mirror should now say.** The decision is
:func:`decide`, a pure function of two numbers and an id, so "would this event be applied,
ignored or refused" is answerable without a database. What the transaction adds is the lock, the
translation from catalogue identity to authored recipe version, and the audit row that records
who the change came from.

**Four orderings, and each of them has to be safe.**

``version == mirror + 1``
    The next change in the line. Applied.
``the event this mirror already applied``
    A redelivered webhook. A no-op, audited as a duplicate. The version does not move again.
``version <= mirror``
    An old event overtaken by a newer one. Ignored without touching a single column -- rolling
    the mirror back would replace current truth with history, and even bumping ``updated_at``
    would falsely invalidate plans that are still correct.
``version > mirror + 1``
    A gap. Something was missed, and this event describes only the lines it changed, so
    applying it could leave the mirror in a state the order system was never in. The mirror is
    repaired instead: the authoritative order is fetched whole and applied as a snapshot.

**Fail closed, always.** An order this deployment does not mirror, a catalogue item no
``order_line_mappings`` row translates, a line the order does not have -- each one aborts the
whole transaction and is recorded as an integration failure. Nothing is guessed, and in
particular no ``RecipeVersion`` is ever created because an external system named one: the
recovery model rests on every version having been authored by a person beforehand.

**The authority and the executor are different parties, and the audit says so.** The change
came from the external order system; the transaction was executed by a PromisePatch worker;
nobody approved anything, so the authority is ``NONE``. Recording it as a worker's decision
would be a lie about who moved a customer's order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

import pydantic
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from order_contract.events import EVENT_ORDER_UPDATED, SCHEMA_VERSION, OrderEvent, OrderSnapshot
from promise_graph.model import OrderLine as EngineOrderLine
from promise_graph.model import RecipeVersion as EngineRecipeVersion
from promise_graph.model import RecipeVersionLine as EngineRecipeVersionLine
from promise_graph.model import ResourceKind
from promise_graph.snapshot import reservations_for_line
from promisepatch.db.clock import database_now
from promisepatch.db.events import append_event
from promisepatch.db.models import (
    InboxEvent,
    Order,
    OrderLine,
    OrderLineMapping,
    RecipeVersion,
    RecipeVersionLine,
    Reservation,
    Resource,
)
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.db.uow import Actor, GovernedWrite, UnitOfWork
from promisepatch.observability import get_logger

logger = get_logger(__name__)

ORDER_SYSTEM_SOURCE: Final = "external-order-system"
"""The ``inbox_events.source`` every order-system delivery is stored under.

Paired with the provider's own ``event_id``, it is what the unique index deduplicates on, so a
webhook delivered ten times is one logical record and at most one mirror change.
"""

EXTERNAL_ORDER_SYSTEM: Final = "EXTERNAL_ORDER_SYSTEM"
"""The provenance value naming where an applied change came from.

The audit row's ``actor`` is the worker that executed the transaction and its ``authority`` is
``NONE``; this is the third fact, and without it the ledger could not distinguish a change the
order system made from one PromisePatch decided on.
"""

AUDIT_MIRROR_UPDATED: Final = "ORDER_MIRROR_UPDATED"
AUDIT_MIRROR_STALE: Final = "ORDER_MIRROR_STALE_EVENT"
AUDIT_MIRROR_REJECTED: Final = "ORDER_MIRROR_REJECTED"
"""The three things that can happen to an arriving event, as the ledger records them.

Both no-op dispositions -- a redelivery and an overtaken event -- are audited as
``ORDER_MIRROR_STALE_EVENT``, with which of the two it was on the provenance. They are one
audited fact from a reader's point of view: an event arrived and the mirror deliberately did
not move. Two types would suggest the answer to "did the mirror change" depends on which,
and it does not.
"""

EVENT_MIRROR_UPDATED: Final = "order.mirror_updated"
EVENT_MIRROR_RESYNCED: Final = "order.mirror_resynced"
EVENT_MIRROR_STALE_IGNORED: Final = "order.mirror_stale_event_ignored"
EVENT_MIRROR_REJECTED: Final = "order.mirror_rejected"
"""Envelopes, not order state.

Each one names the order it is about and how current the mirror now is. The order itself, the
customer and what they bought stay in the mirror and the audit ledger, where a reader has to be
entitled to look.
"""


class Disposition(StrEnum):
    """What an arriving event should do to the mirror."""

    APPLY = "APPLY"
    DUPLICATE = "DUPLICATE"
    """Already applied. The mirror is exactly what this event describes, and stays there."""
    STALE = "STALE"
    """Overtaken. Older than what the mirror holds, and applying it would roll truth back."""
    GAP = "GAP"
    """A change is missing. Repair from the authoritative order rather than guess at it."""


class MirrorRejectedError(RuntimeError):
    """The event cannot be applied to this mirror at all, and never will be.

    Raised inside the transaction so nothing partial commits. The record is then failed and
    audited in a transaction of its own, which is the only way an integration failure can be
    both durable and free of half-applied state.
    """


@dataclass(frozen=True, slots=True)
class MirrorOutcome:
    """What one stored order-system record did."""

    inbox_id: UUID
    disposition: Disposition | None
    external_order_id: str | None
    external_version: int | None
    error: str | None = None

    @property
    def applied(self) -> bool:
        return self.disposition in (Disposition.APPLY, Disposition.GAP)


class AuthoritativeFetch(Protocol):
    """How the worker reads an order whole, when an event alone is not enough to trust.

    A protocol rather than a client, because this module may not open a socket: the worker
    supplies something that can, and does so with no transaction held.
    """

    async def __call__(self, external_order_id: str) -> OrderSnapshot: ...


# ------------------------------------------------------------------------------ the decision


def decide(*, mirror_version: int, applied_event_id: UUID | None, event: OrderEvent) -> Disposition:
    """Which of the four orderings this event is, from numbers alone.

    ``previous_version`` decides it when the sender supplied one, because it states exactly
    which version the sender believed it was moving from. Falling back to ``version ==
    mirror + 1`` keeps an event without it readable rather than treating it as a gap.
    """
    incoming = event.order.version
    if applied_event_id is not None and applied_event_id == event.event_id:
        return Disposition.DUPLICATE
    if incoming <= mirror_version:
        return Disposition.STALE
    expected_previous = (
        event.previous_version if event.previous_version is not None else incoming - 1
    )
    return Disposition.APPLY if expected_previous == mirror_version else Disposition.GAP


def parse(body: str | None) -> OrderEvent:
    """Read one stored delivery as the contract, or refuse it.

    Reads the stored row rather than a live request, so replaying an inbox record a year later
    produces the same reading it produced on the day.
    """
    try:
        event = OrderEvent.model_validate_json(body or "")
    except pydantic.ValidationError as error:
        raise MirrorRejectedError(
            f"unreadable order event: {error.error_count()} problems"
        ) from error
    if event.schema_version != SCHEMA_VERSION:
        raise MirrorRejectedError(
            f"order event schema version {event.schema_version} is not the {SCHEMA_VERSION} "
            "this build understands"
        )
    if event.type != EVENT_ORDER_UPDATED:
        # ``order.cancelled`` is part of the contract and is not yet something this build can
        # apply. Refusing it is the only safe answer: quietly ignoring a cancellation would
        # leave PromisePatch planning recoveries for an order that no longer exists.
        raise MirrorRejectedError(f"order event type {event.type!r} is not applied by this build")
    return event


# ----------------------------------------------------------------------------- processing


async def process_one(
    database: RuntimeDatabase, *, worker: str, fetch: AuthoritativeFetch | None = None
) -> MirrorOutcome | None:
    """Apply at most one stored order-system record. ``None`` when there is nothing waiting.

    Separate from the general inbox sweep for one reason that matters: repairing a version gap
    needs an authoritative read over the network, and a network call inside a transaction would
    hold a connection, its locks and its snapshot for the length of a round trip. So the
    transaction ends, the order is fetched with nothing held, and a second transaction applies
    it.
    """
    candidate = await _next_record(database)
    if candidate is None:
        return None

    inbox_id, body = candidate
    try:
        event = parse(body)
    except MirrorRejectedError as rejection:
        return await _reject(database, inbox_id=inbox_id, worker=worker, error=str(rejection))

    try:
        outcome = await _apply_record(database, inbox_id=inbox_id, event=event, worker=worker)
        if outcome is not None and outcome.disposition is Disposition.GAP:
            outcome = await _repair_gap(
                database, inbox_id=inbox_id, event=event, worker=worker, fetch=fetch
            )
    except MirrorRejectedError as rejection:
        return await _reject(
            database,
            inbox_id=inbox_id,
            worker=worker,
            error=str(rejection),
            external_order_id=event.order.external_id,
        )

    if outcome is not None:
        logger.info(
            "worker.order_mirror.processed",
            inbox_id=str(inbox_id),
            external_order_id=outcome.external_order_id,
            external_version=outcome.external_version,
            disposition=None if outcome.disposition is None else outcome.disposition.value,
            worker=worker,
        )
    return outcome


async def _next_record(database: RuntimeDatabase) -> tuple[UUID, str | None] | None:
    """The oldest unprocessed order-system delivery, read under a lock this transaction drops.

    The lock is not the safety property -- the apply transaction settles the row under a
    ``state = 'RECEIVED'`` predicate and does nothing if somebody beat it to it. What
    ``SKIP LOCKED`` buys is that two workers sweeping at once look at different rows instead of
    doing the same work twice.
    """
    async with database.begin() as connection:
        row = (
            await connection.execute(
                select(InboxEvent.id, InboxEvent.raw_body)
                .where(InboxEvent.source == ORDER_SYSTEM_SOURCE, InboxEvent.state == "RECEIVED")
                .order_by(InboxEvent.received_at, InboxEvent.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).one_or_none()
    return None if row is None else (row.id, row.raw_body)


async def _apply_record(
    database: RuntimeDatabase, *, inbox_id: UUID, event: OrderEvent, worker: str
) -> MirrorOutcome | None:
    """One transaction: lock the order, decide, apply or refuse, settle the record.

    Returns ``None`` when another worker settled the record first, and a ``GAP`` outcome without
    having written anything when the mirror needs repairing from the authoritative order.
    """
    async with database.begin() as connection:
        now = await database_now(connection)
        order = await _lock_order(connection, event.order.external_id)
        disposition = decide(
            mirror_version=order.external_version,
            applied_event_id=order.mirror_source_event_id,
            event=event,
        )
        if disposition is Disposition.GAP:
            return MirrorOutcome(
                inbox_id=inbox_id,
                disposition=Disposition.GAP,
                external_order_id=event.order.external_id,
                external_version=order.external_version,
            )

        if disposition is Disposition.APPLY:
            settled = await _settle(
                connection,
                inbox_id=inbox_id,
                state="PROCESSED",
                normalized=_normalized(event, disposition),
                now=now,
            )
            if not settled:
                return None
            await _write_snapshot(
                connection,
                order=order,
                snapshot=event.order,
                event_id=event.event_id,
                worker=worker,
                now=now,
                inbox_id=inbox_id,
                mode="event",
                domain_event=EVENT_MIRROR_UPDATED,
            )
            return MirrorOutcome(
                inbox_id=inbox_id,
                disposition=disposition,
                external_order_id=event.order.external_id,
                external_version=event.order.version,
            )

        settled = await _settle(
            connection,
            inbox_id=inbox_id,
            state="IGNORED",
            normalized=_normalized(event, disposition),
            now=now,
        )
        if not settled:
            return None
        await _audit_without_change(
            connection,
            audit_type=AUDIT_MIRROR_STALE,
            worker=worker,
            now=now,
            order_id=order.id,
            provenance={
                "source": EXTERNAL_ORDER_SYSTEM,
                "external_order_id": event.order.external_id,
                "event_id": str(event.event_id),
                "inbox_event_id": str(inbox_id),
                "event_version": event.order.version,
                "mirror_version": order.external_version,
                "disposition": disposition.value,
            },
            domain_event=EVENT_MIRROR_STALE_IGNORED,
            payload={"disposition": disposition.value, "external_version": order.external_version},
        )
        return MirrorOutcome(
            inbox_id=inbox_id,
            disposition=disposition,
            external_order_id=event.order.external_id,
            external_version=order.external_version,
        )


async def _repair_gap(
    database: RuntimeDatabase,
    *,
    inbox_id: UUID,
    event: OrderEvent,
    worker: str,
    fetch: AuthoritativeFetch | None,
) -> MirrorOutcome:
    """Fetch the order whole and make the mirror equal to it.

    Applying the gapped event itself would be the unsafe shortcut: it describes the lines *it*
    changed, and a change we never saw may have touched another one. The authoritative snapshot
    has no such hole, and applying it is the same code path an ordinary event takes -- so the
    mirror lands on a state the order system was really in, never on a partial one.
    """
    if fetch is None:
        raise MirrorRejectedError(
            "the mirror is behind the order system and no authoritative order fetch is "
            "configured, so the gap cannot be repaired"
        )
    snapshot = await fetch(event.order.external_id)

    async with database.begin() as connection:
        now = await database_now(connection)
        order = await _lock_order(connection, event.order.external_id)
        if snapshot.version < order.external_version:
            raise MirrorRejectedError(
                f"the order system answered with version {snapshot.version}, "
                f"behind the mirror's {order.external_version}"
            )
        settled = await _settle(
            connection,
            inbox_id=inbox_id,
            state="PROCESSED",
            normalized=_normalized(event, Disposition.GAP) | {"resynced_to": snapshot.version},
            now=now,
        )
        if not settled:
            return MirrorOutcome(
                inbox_id=inbox_id,
                disposition=None,
                external_order_id=event.order.external_id,
                external_version=order.external_version,
            )
        if snapshot.version > order.external_version:
            await _write_snapshot(
                connection,
                order=order,
                snapshot=snapshot,
                # The mirror was made equal to a fetched order, not to this event, so the event
                # that last moved it is deliberately unknown. Recording this event's id would
                # claim a lineage the mirror does not have.
                event_id=None,
                worker=worker,
                now=now,
                inbox_id=inbox_id,
                mode="resync",
                domain_event=EVENT_MIRROR_RESYNCED,
            )
        return MirrorOutcome(
            inbox_id=inbox_id,
            disposition=Disposition.GAP,
            external_order_id=event.order.external_id,
            external_version=snapshot.version,
        )


async def _reject(
    database: RuntimeDatabase,
    *,
    inbox_id: UUID,
    worker: str,
    error: str,
    external_order_id: str | None = None,
) -> MirrorOutcome:
    """Record an integration failure, in a transaction of its own.

    Its own transaction because the one that discovered the problem was aborted on the way out,
    taking any audit row it had written with it. Recording the failure separately is what makes
    "the mirror was not half-applied" and "somebody can see why" both true.
    """
    async with database.begin() as connection:
        now = await database_now(connection)
        await _settle(
            connection,
            inbox_id=inbox_id,
            state="FAILED",
            normalized=None,
            now=now,
            error=error,
        )
        await _audit_without_change(
            connection,
            audit_type=AUDIT_MIRROR_REJECTED,
            worker=worker,
            now=now,
            order_id=None,
            provenance={
                "source": EXTERNAL_ORDER_SYSTEM,
                "external_order_id": external_order_id,
                "inbox_event_id": str(inbox_id),
                "error": error,
            },
            domain_event=EVENT_MIRROR_REJECTED,
            payload={"error": error},
        )
    logger.warning(
        "worker.order_mirror.rejected",
        inbox_id=str(inbox_id),
        external_order_id=external_order_id,
        error=error,
        worker=worker,
    )
    return MirrorOutcome(
        inbox_id=inbox_id,
        disposition=None,
        external_order_id=external_order_id,
        external_version=None,
        error=error,
    )


# ----------------------------------------------------------------------------- the writes


async def _write_snapshot(
    connection: AsyncConnection,
    *,
    order: Any,
    snapshot: OrderSnapshot,
    event_id: UUID | None,
    worker: str,
    now: datetime,
    inbox_id: UUID,
    mode: str,
    domain_event: str,
) -> None:
    """Make the mirror say what the order system says, inside one audited transition."""
    changes = [
        await _resolve_line(connection, order_id=order.id, line=line) for line in snapshot.lines
    ]

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_MIRROR_UPDATED,
        # The worker executed the transaction; it did not decide anything. The authority is
        # ``NONE`` because no policy and no consent permitted this -- the order system changed
        # one of its own orders, and PromisePatch is recording that it did.
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        before={
            "external_version": order.external_version,
            "state": order.state,
            "lines": {change.line_id: change.previous_version_id for change in changes},
        },
        after={
            "external_version": snapshot.version,
            "state": snapshot.state,
            "lines": {change.line_id: change.recipe_version_id for change in changes},
        },
        provenance={
            "source": EXTERNAL_ORDER_SYSTEM,
            "executor": worker,
            "external_order_id": snapshot.external_id,
            "event_id": None if event_id is None else str(event_id),
            "inbox_event_id": str(inbox_id),
            "mode": mode,
        },
        occurred_at=now,
    ) as write:
        for change in changes:
            await _apply_line(write, change=change)
        await write.execute(
            update(Order)
            .where(Order.id == order.id, Order.external_version == order.external_version)
            .values(
                external_version=snapshot.version,
                state=snapshot.state,
                mirror_source_event_id=event_id,
                updated_at=now,
            )
        )

    # Last, and after every row this transaction touches: appending an event takes the spine's
    # ordering lock and holds it until commit, so nothing may queue behind it here.
    await append_event(
        connection,
        event_type=domain_event,
        correlation_id=uuid4(),
        occurred_at=now,
        entity_refs=[{"kind": "order", "id": order.id}],
        payload={
            "external_order_id": snapshot.external_id,
            "external_version": snapshot.version,
            "changed_line_ids": [change.line_id for change in changes if change.changed],
        },
    )


@dataclass(frozen=True, slots=True)
class _LineChange:
    """One mirrored line, and the authored version it should now be pinned to."""

    line_id: str
    previous_version_id: str
    recipe_version_id: str
    quantity: int
    previous_quantity: int
    reservations: tuple[Any, ...]

    @property
    def changed(self) -> bool:
        return (
            self.recipe_version_id != self.previous_version_id
            or self.quantity != self.previous_quantity
        )


async def _resolve_line(connection: AsyncConnection, *, order_id: str, line: Any) -> _LineChange:
    """Translate one external line into mirrored rows, or refuse to.

    Two translations happen here and neither is allowed to guess. The catalogue item becomes an
    authored ``RecipeVersion`` through ``order_line_mappings``, which PromisePatch owns; the
    external line identifies a row this order already has. An item nobody mapped, or a line this
    order does not have, is a data problem for the owner -- never a row invented at runtime to
    make an event fit.
    """
    mirrored = (
        await connection.execute(
            select(OrderLine).where(
                OrderLine.id == line.external_line_id, OrderLine.order_id == order_id
            )
        )
    ).one_or_none()
    if mirrored is None:
        raise MirrorRejectedError(
            f"order {order_id} has no mirrored line {line.external_line_id!r}"
        )

    version_id = (
        await connection.execute(
            select(OrderLineMapping.recipe_version_id).where(
                OrderLineMapping.external_item_id == line.external_item_id
            )
        )
    ).scalar_one_or_none()
    if version_id is None:
        raise MirrorRejectedError(
            f"no order_line_mappings row translates catalogue item "
            f"{line.external_item_id!r}; nothing here may invent a recipe version"
        )

    return _LineChange(
        line_id=mirrored.id,
        previous_version_id=mirrored.recipe_version_id,
        recipe_version_id=version_id,
        quantity=line.quantity,
        previous_quantity=mirrored.quantity,
        reservations=await _derived_reservations(
            connection,
            order_id=order_id,
            line_id=mirrored.id,
            version_id=version_id,
            quantity=line.quantity,
        ),
    )


async def _apply_line(write: GovernedWrite, *, change: _LineChange) -> None:
    """Re-pin the line and rewrite its reservations, so §11.4.3 still holds afterwards.

    A line's reservations *are* its pinned version times its quantity. Changing the pin without
    them would leave the graph describing a cake made of the previous recipe's ingredients,
    which is a worse state than not having applied the change at all.
    """
    if not change.changed:
        return
    await write.execute(
        update(OrderLine)
        .where(OrderLine.id == change.line_id)
        .values(recipe_version_id=change.recipe_version_id, quantity=change.quantity)
    )
    await write.execute(delete(Reservation).where(Reservation.order_line_id == change.line_id))
    for reservation in change.reservations:
        await write.execute(
            insert(Reservation).values(
                id=reservation.id,
                order_line_id=reservation.order_line_id,
                resource_id=reservation.resource_id,
                quantity=reservation.quantity,
                source_recipe_version_id=reservation.source_recipe_version_id,
            )
        )


async def _derived_reservations(
    connection: AsyncConnection, *, order_id: str, line_id: str, version_id: str, quantity: int
) -> tuple[Any, ...]:
    """The reservations this pin implies, derived by the engine's own function.

    Derived rather than written by hand, so the mirrored graph satisfies the same invariant the
    engine asserts about every other line. A second implementation of the arithmetic here would
    eventually disagree with the one the engine tests.
    """
    version_row = (
        await connection.execute(select(RecipeVersion).where(RecipeVersion.id == version_id))
    ).one_or_none()
    if version_row is None:
        raise MirrorRejectedError(f"recipe version {version_id!r} is mapped but does not exist")

    line_rows = (
        await connection.execute(
            select(RecipeVersionLine).where(RecipeVersionLine.version_id == version_id)
        )
    ).all()
    resource_rows = (
        await connection.execute(
            select(Resource.id, Resource.kind).where(
                Resource.id.in_([row.resource_id for row in line_rows] or [""])
            )
        )
    ).all()

    version = EngineRecipeVersion(
        id=version_row.id,
        recipe_id=version_row.recipe_id,
        version_no=version_row.version_no,
        lines=tuple(
            EngineRecipeVersionLine(
                resource_id=row.resource_id, role=row.role, qty_per_unit=row.qty_per_unit
            )
            for row in line_rows
        ),
        authored_by=version_row.authored_by,
        authored_at=version_row.authored_at,
    )
    resources = {
        row.id: _ResourceKind(id=row.id, kind=ResourceKind(row.kind)) for row in resource_rows
    }
    order_line = EngineOrderLine(
        id=line_id, order_id=order_id, recipe_version_id=version_id, quantity=quantity
    )
    return reservations_for_line(order_line, version, resources)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class _ResourceKind:
    """Just enough of a resource for the reservation derivation: its identity and its kind."""

    id: str
    kind: ResourceKind


# ----------------------------------------------------------------------------- bookkeeping


async def _lock_order(connection: AsyncConnection, external_id: str) -> Any:
    """Take the mirrored order for update, or refuse an event about an order we do not hold.

    An unsolicited event for an unknown order does not onboard one. PromisePatch mirrors the
    orders it was given; creating one from an event would mean an external system could add
    customer promises to this bakery's book by sending a message.
    """
    row = (
        await connection.execute(
            select(Order).where(Order.external_id == external_id).with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise MirrorRejectedError(f"no mirrored order for external id {external_id!r}")
    return row


async def _settle(
    connection: AsyncConnection,
    *,
    inbox_id: UUID,
    state: str,
    normalized: Mapping[str, Any] | None,
    now: datetime,
    error: str | None = None,
) -> bool:
    """Move the stored record out of ``RECEIVED``. ``False`` if somebody else already did.

    The predicate is what makes two workers safe without a durable claim: whichever commits
    first settles the row, and the other's transaction affects no rows and is rolled back
    without having applied anything.
    """
    result = await connection.execute(
        update(InboxEvent)
        .where(InboxEvent.id == inbox_id, InboxEvent.state == "RECEIVED")
        .values(
            state=state,
            normalized=None if normalized is None else dict(normalized),
            processed_at=now,
            error=error,
        )
    )
    return result.rowcount == 1


def _normalized(event: OrderEvent, disposition: Disposition) -> dict[str, Any]:
    """What the rest of the system reads off the record. The raw body stays on the row."""
    return {
        "source": ORDER_SYSTEM_SOURCE,
        "event_id": str(event.event_id),
        "type": event.type,
        "external_order_id": event.order.external_id,
        "external_version": event.order.version,
        "previous_version": event.previous_version,
        "disposition": disposition.value,
    }


async def _audit_without_change(
    connection: AsyncConnection,
    *,
    audit_type: str,
    worker: str,
    now: datetime,
    order_id: str | None,
    provenance: Mapping[str, Any],
    domain_event: str,
    payload: Mapping[str, Any],
) -> None:
    """Record that something arrived and changed nothing, and say why.

    A governed block with no governed write in it, deliberately: the authorisation is taken out
    and spent on nothing, which is exactly what happened. An ignored event that left no trace
    would make "the mirror never went backwards" unprovable after the fact.
    """
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=audit_type,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        provenance=dict(provenance),
        occurred_at=now,
    ):
        pass
    await append_event(
        connection,
        event_type=domain_event,
        correlation_id=uuid4(),
        occurred_at=now,
        entity_refs=[] if order_id is None else [{"kind": "order", "id": order_id}],
        payload=dict(payload),
    )


def sources() -> Sequence[str]:
    """Every inbox source this module owns. Read by the general sweep, which skips them."""
    return (ORDER_SYSTEM_SOURCE,)
