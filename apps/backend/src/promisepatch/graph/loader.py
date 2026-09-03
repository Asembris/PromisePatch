"""The one adapter from stored rows to a :class:`~promise_graph.snapshot.GraphSnapshot`.

Everything the engine decides with comes through here, so this module has one job and one
rule. The job is to read the whole graph in a single consistent transaction and stamp it with
the point on the event spine it was read at. The rule is that **no SQLAlchemy object crosses
the boundary**: rows are read as plain column mappings and constructed into ``promise_graph``
records, never handed over as ORM instances. An ORM instance carries a session, a lazy loader
and an identity map, and any of the three would make a "pure" engine quietly do I/O.

Three shapes of fidelity matter, and they are load-bearing rather than tidy:

* **Quantities stay :class:`~decimal.Decimal`.** The column is ``NUMERIC``, the driver returns
  ``Decimal``, and the record normalises the scale. No float appears anywhere on the path.
* **``None`` stays unknown.** An absent quantity is not zero. Coercing it would turn a promise
  the engine must fail closed on into one it believes is satisfied, which is the single most
  dangerous thing this module could do.
* **Order is reconstructed, not remembered.** Child collections are keyed sets in the database,
  so they are rebuilt in the canonical order the engine's own indexes impose: commitment lines
  by id, version lines by ``(resource_id, role)``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.sql import ColumnElement, FromClause

from promise_graph.model import (
    CommitmentId,
    CommitmentLine,
    Customer,
    CustomerConstraint,
    CustomerPromise,
    EquipmentAlternative,
    EquipmentOutage,
    InventoryLedgerEntry,
    InventoryReservation,
    Order,
    OrderId,
    OrderLine,
    ProductionTask,
    Recipe,
    RecipeVersion,
    RecipeVersionId,
    RecipeVersionLine,
    Resource,
    ResourceId,
    SubstitutionPolicyEntry,
    Supplier,
    SupplierCommitment,
)
from promise_graph.snapshot import GraphSnapshot
from promisepatch.db import models
from promisepatch.db.base import SCHEMA
from promisepatch.graph.channel import join_channel

SNAPSHOT_ISOLATION = "REPEATABLE READ"
"""The isolation a whole-graph read needs.

READ COMMITTED takes a fresh database snapshot per statement, so a reset committing halfway
through twenty selects would be read as half of one graph and half of another -- a shape that
never existed and that the engine would classify with a straight face.
"""

READ_TABLES: tuple[str, ...] = (
    "resources",
    "resource_aliases",
    "suppliers",
    "supplier_commitments",
    "commitment_lines",
    "recipes",
    "recipe_versions",
    "recipe_version_lines",
    "recipe_version_equipment",
    "substitution_policies",
    "equipment_alternatives",
    "customers",
    "orders",
    "order_lines",
    "order_constraints",
    "promises",
    "production_tasks",
    "reservations",
    "inventory_ledger",
    "equipment_outages",
    "domain_events",
)
"""Every table one whole-graph read touches, locked together before the first select.

**Repeatable read alone is not enough, because ``TRUNCATE`` is not MVCC-safe.** A reader
holding an older snapshot does not see a truncated table as it was; it sees it as *empty*. A
fixture reset truncates, so a reader that merely started first would load a graph with no
resources, no orders and no promises -- and the engine, given no reachable promise, would
answer ``UNAFFECTED`` for every one of them. That is the fail-open this system exists to
prevent, arrived at without a single error being raised.

Taking the whole read set in ``ACCESS SHARE`` up front closes it. That is the same lock every
``SELECT`` takes anyway, so it blocks nothing a plain read would not, but taking it *before*
the snapshot means a concurrent truncation can only happen wholly before this read or wholly
after it. The reset waits, which is correct: emptying the database is the operation that
should yield, not the one trying to answer a question about a customer promise.
"""

_LOCK_READ_SET = text(
    "LOCK TABLE "
    + ", ".join(f'{SCHEMA}."{table}"' for table in sorted(READ_TABLES))
    + " IN ACCESS SHARE MODE"
)


@asynccontextmanager
async def snapshot_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A read-only, repeatable-read session for exactly one whole-graph read.

    ``READ ONLY`` is declared as well as ``REPEATABLE READ`` because it says what this
    transaction is for: the database refuses a write through it, so a reader cannot become a
    writer by accident.
    """
    connection = await engine.connect()
    try:
        await connection.execution_options(
            isolation_level=SNAPSHOT_ISOLATION, postgresql_readonly=True
        )
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
    finally:
        await connection.rollback()
        await connection.close()


async def load_snapshot(session: AsyncSession) -> GraphSnapshot:
    """Build the whole promise graph from the database, stamped with its ``as_of``.

    The scope is deliberately everything. A scoped loader is a real need once the case engine
    re-plans a single promise, but it is a different query shape with a different correctness
    argument, and writing it before anything asks for it would be guessing.

    The read set is locked first, for the reason set out on :data:`READ_TABLES`: repeatable
    read fixes what a concurrent *update* looks like, but only a lock fixes what a concurrent
    truncation looks like.
    """
    await session.execute(_LOCK_READ_SET)
    return GraphSnapshot.build(
        resources=await _resources(session),
        suppliers=await _suppliers(session),
        commitments=await _commitments(session),
        recipes=await _recipes(session),
        versions=await _versions(session),
        customers=await _customers(session),
        orders=await _orders(session),
        constraints=await _constraints(session),
        promises=await _promises(session),
        tasks=await _tasks(session),
        reservations=await _reservations(session),
        ledger=await _ledger(session),
        outages=await _outages(session),
        policies=await _policies(session),
        equipment_alternatives=await _equipment_alternatives(session),
        as_of=await _as_of(session),
    )


async def _as_of(session: AsyncSession) -> int:
    """The point on the event spine this view is current to.

    ``domain_events`` is the single global order every consumer checkpoints against, so the
    highest sequence visible in this transaction is exactly how current the graph is. An empty
    spine is ``0``: nothing has happened yet, which is a true answer rather than a missing one.
    """
    spine = models.DomainEvent.__table__
    result = await session.execute(select(func.coalesce(func.max(spine.c.seq), 0)))
    return int(result.scalar_one())


# --------------------------------------------------------------------------- readers


async def _rows(
    session: AsyncSession, table: FromClause, *order_by: ColumnElement[Any]
) -> Sequence[RowMapping]:
    """Read a table as plain column mappings.

    Selecting the :class:`~sqlalchemy.Table` rather than the mapped class is what keeps the ORM
    out of the result: what comes back is rows of columns, with no instance, no session and no
    lazy loading attached.
    """
    result = await session.execute(select(table).order_by(*order_by))
    return result.mappings().all()


async def _resources(session: AsyncSession) -> list[Resource]:
    table = models.Resource.__table__
    aliases = models.ResourceAlias.__table__
    by_resource: dict[ResourceId, list[str]] = defaultdict(list)
    for row in await _rows(session, aliases, aliases.c.resource_id, aliases.c.ordinal):
        by_resource[row["resource_id"]].append(row["alias"])
    return [
        Resource(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            unit=row["unit"],
            aliases=tuple(by_resource.get(row["id"], ())),
        )
        for row in await _rows(session, table, table.c.id)
    ]


async def _suppliers(session: AsyncSession) -> list[Supplier]:
    table = models.Supplier.__table__
    return [
        Supplier(id=row["id"], name=row["name"]) for row in await _rows(session, table, table.c.id)
    ]


async def _commitments(session: AsyncSession) -> list[SupplierCommitment]:
    table = models.SupplierCommitment.__table__
    lines = models.CommitmentLine.__table__
    by_commitment: dict[CommitmentId, list[CommitmentLine]] = defaultdict(list)
    for row in await _rows(session, lines, lines.c.commitment_id, lines.c.id):
        by_commitment[row["commitment_id"]].append(
            CommitmentLine(
                id=row["id"],
                commitment_id=row["commitment_id"],
                resource_id=row["resource_id"],
                quantity=row["quantity"],
                received_state=row["received_state"],
                received_qty=row["received_qty"],
                settled_at=row["settled_at"],
                attested_by=row["attested_by"],
            )
        )
    return [
        SupplierCommitment(
            id=row["id"],
            supplier_id=row["supplier_id"],
            due_at=row["due_at"],
            lines=tuple(by_commitment.get(row["id"], ())),
        )
        for row in await _rows(session, table, table.c.id)
    ]


async def _recipes(session: AsyncSession) -> list[Recipe]:
    table = models.Recipe.__table__
    return [
        Recipe(id=row["id"], name=row["name"]) for row in await _rows(session, table, table.c.id)
    ]


async def _versions(session: AsyncSession) -> list[RecipeVersion]:
    table = models.RecipeVersion.__table__
    lines = models.RecipeVersionLine.__table__
    equipment = models.RecipeVersionEquipment.__table__

    by_version: dict[RecipeVersionId, list[RecipeVersionLine]] = defaultdict(list)
    for row in await _rows(session, lines, lines.c.version_id, lines.c.resource_id, lines.c.role):
        by_version[row["version_id"]].append(
            RecipeVersionLine(
                resource_id=row["resource_id"],
                role=row["role"],
                qty_per_unit=row["qty_per_unit"],
            )
        )

    equipment_by_version: dict[RecipeVersionId, list[ResourceId]] = defaultdict(list)
    for row in await _rows(session, equipment, equipment.c.version_id, equipment.c.equipment_id):
        equipment_by_version[row["version_id"]].append(row["equipment_id"])

    return [
        RecipeVersion(
            id=row["id"],
            recipe_id=row["recipe_id"],
            version_no=row["version_no"],
            lines=tuple(by_version.get(row["id"], ())),
            equipment_ids=tuple(equipment_by_version.get(row["id"], ())),
            authored_by=row["authored_by"],
            authored_at=row["authored_at"],
        )
        for row in await _rows(session, table, table.c.id)
    ]


async def _customers(session: AsyncSession) -> list[Customer]:
    table = models.Customer.__table__
    return [
        Customer(
            id=row["id"],
            name=row["name"],
            approval_channel=join_channel(
                row["approval_channel_kind"], row["approval_channel_address"]
            ),
        )
        for row in await _rows(session, table, table.c.id)
    ]


async def _orders(session: AsyncSession) -> list[Order]:
    table = models.Order.__table__
    lines = models.OrderLine.__table__
    by_order: dict[OrderId, list[OrderLine]] = defaultdict(list)
    for row in await _rows(session, lines, lines.c.order_id, lines.c.id):
        by_order[row["order_id"]].append(
            OrderLine(
                id=row["id"],
                order_id=row["order_id"],
                recipe_version_id=row["recipe_version_id"],
                quantity=row["quantity"],
                customization_note=row["customization_note"],
            )
        )
    return [
        Order(
            id=row["id"],
            external_id=row["external_id"],
            external_version=row["external_version"],
            customer_id=row["customer_id"],
            due_at=row["due_at"],
            state=row["state"],
            lines=tuple(by_order.get(row["id"], ())),
        )
        for row in await _rows(session, table, table.c.id)
    ]


async def _constraints(session: AsyncSession) -> list[CustomerConstraint]:
    table = models.OrderConstraint.__table__
    return [
        CustomerConstraint(
            id=row["id"],
            order_id=row["order_id"],
            kind=row["kind"],
            resource_id=row["resource_id"],
            substitute_resource_id=row["substitute_resource_id"],
            recorded_by=row["recorded_by"],
            recorded_at=row["recorded_at"],
        )
        for row in await _rows(session, table, table.c.id)
    ]


async def _promises(session: AsyncSession) -> list[CustomerPromise]:
    table = models.Promise.__table__
    return [
        CustomerPromise(id=row["id"], order_id=row["order_id"], due_at=row["due_at"])
        for row in await _rows(session, table, table.c.id)
    ]


async def _tasks(session: AsyncSession) -> list[ProductionTask]:
    table = models.ProductionTask.__table__
    return [
        ProductionTask(
            id=row["id"],
            order_line_id=row["order_line_id"],
            state=row["state"],
            scheduled_start=row["scheduled_start"],
            scheduled_end=row["scheduled_end"],
            equipment_id=row["equipment_id"],
            held_by_case_id=None if row["held_by_case_id"] is None else str(row["held_by_case_id"]),
        )
        for row in await _rows(session, table, table.c.id)
    ]


async def _reservations(session: AsyncSession) -> list[InventoryReservation]:
    table = models.Reservation.__table__
    return [
        InventoryReservation(
            id=row["id"],
            order_line_id=row["order_line_id"],
            resource_id=row["resource_id"],
            quantity=row["quantity"],
            source_recipe_version_id=row["source_recipe_version_id"],
        )
        for row in await _rows(session, table, table.c.id)
    ]


async def _ledger(session: AsyncSession) -> list[InventoryLedgerEntry]:
    table = models.InventoryLedgerEntry.__table__
    return [
        InventoryLedgerEntry(
            seq=row["seq"],
            resource_id=row["resource_id"],
            delta=row["delta"],
            source_kind=row["source_kind"],
            source_id=row["source_id"],
            recorded_at=row["recorded_at"],
        )
        for row in await _rows(session, table, table.c.seq)
    ]


async def _outages(session: AsyncSession) -> list[EquipmentOutage]:
    table = models.EquipmentOutage.__table__
    return [
        EquipmentOutage(
            id=row["id"],
            equipment_id=row["equipment_id"],
            starts_at=row["starts_at"],
            ends_at=row["ends_at"],
        )
        for row in await _rows(session, table, table.c.id)
    ]


async def _policies(session: AsyncSession) -> list[SubstitutionPolicyEntry]:
    table = models.SubstitutionPolicy.__table__
    return [
        SubstitutionPolicyEntry(
            id=row["id"],
            affected_resource_id=row["affected_resource_id"],
            role=row["role"],
            source_version_id=row["source_version_id"],
            candidate_version_id=row["candidate_version_id"],
            substitute_resource_id=row["substitute_resource_id"],
            visible_change=row["visible_change"],
        )
        for row in await _rows(session, table, table.c.id)
    ]


async def _equipment_alternatives(session: AsyncSession) -> list[EquipmentAlternative]:
    table = models.EquipmentAlternative.__table__
    return [
        EquipmentAlternative(
            id=row["id"],
            equipment_id=row["equipment_id"],
            alternative_equipment_id=row["alternative_equipment_id"],
        )
        for row in await _rows(session, table, table.c.id)
    ]
