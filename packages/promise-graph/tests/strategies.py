"""Hypothesis strategies over structurally valid promise graphs.

Worlds are built bottom-up (resources -> versions -> orders -> tasks -> reservations), so
every generated snapshot is valid by construction rather than by filtering. Only *value*
unknowns are ever injected, because those are the ones the engine must fail closed on.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import strategies as st

from promise_graph.model import (
    CommitmentLine,
    ConstraintKind,
    Customer,
    CustomerConstraint,
    CustomerPromise,
    EquipmentAlternative,
    ExceptionCategory,
    InventoryLedgerEntry,
    LedgerSourceKind,
    Order,
    OrderLine,
    OrderState,
    PhysicalException,
    ProductionTask,
    Recipe,
    RecipeLineRole,
    RecipeVersion,
    RecipeVersionLine,
    Record,
    Resource,
    ResourceKind,
    SubstitutionPolicyEntry,
    Supplier,
    SupplierCommitment,
    TaskState,
)
from promise_graph.snapshot import GraphSnapshot, reservations_for_line

ANCHOR = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
ROLES = list(RecipeLineRole)


@dataclass(frozen=True)
class World:
    """A generated snapshot plus the exception to run against it."""

    snapshot: GraphSnapshot
    exception: PhysicalException
    now: datetime


def amount(draw: st.DrawFn, low: int = 1, high: int = 50) -> Decimal:
    """A tidy one-decimal quantity. Never a float."""
    return Decimal(draw(st.integers(min_value=low, max_value=high))).scaleb(-1)


@st.composite
def worlds(draw: st.DrawFn) -> World:
    now = ANCHOR
    ingredient_count = draw(st.integers(min_value=2, max_value=4))
    ingredients = [f"res-i{i}" for i in range(ingredient_count)]
    equipment = ["res-e0", "res-e1"]
    resources = [
        Resource(id=rid, kind=ResourceKind.INGREDIENT, name=rid, unit="kg") for rid in ingredients
    ] + [Resource(id=rid, kind=ResourceKind.EQUIPMENT, name=rid) for rid in equipment]

    # --- recipe versions -----------------------------------------------------------------
    version_count = draw(st.integers(min_value=2, max_value=4))
    recipes = [Recipe(id="rec-0", name="rec-0")]
    versions: list[RecipeVersion] = []
    for index in range(version_count):
        used = draw(st.lists(st.sampled_from(ingredients), min_size=1, max_size=2, unique=True))
        lines = tuple(
            RecipeVersionLine(
                resource_id=resource_id,
                role=draw(st.sampled_from(ROLES)),
                qty_per_unit=amount(draw),
            )
            for resource_id in used
        )
        versions.append(
            RecipeVersion(
                id=f"rv-{index}",
                recipe_id="rec-0",
                version_no=index,
                lines=lines,
                equipment_ids=(draw(st.sampled_from(equipment)),),
                authored_by="jo",
                authored_at=now - timedelta(days=10),
            )
        )

    # --- orders, promises, tasks ---------------------------------------------------------
    order_count = draw(st.integers(min_value=1, max_value=4))
    customers: list[Customer] = []
    orders: list[Order] = []
    promises: list[CustomerPromise] = []
    tasks: list[ProductionTask] = []
    constraints: list[CustomerConstraint] = []
    starts = draw(
        st.lists(
            st.integers(min_value=60, max_value=1400),
            min_size=order_count,
            max_size=order_count,
            unique=True,
        )
    )
    for index in range(order_count):
        order_id = f"ord-{index}"
        line_id = f"ol-{index}"
        customers.append(
            Customer(id=f"cus-{index}", name=f"customer {index}", approval_channel=f"ch:{index}")
        )
        version = draw(st.sampled_from(versions))
        quantity = draw(st.integers(min_value=1, max_value=3))
        start = now + timedelta(minutes=starts[index])
        orders.append(
            Order(
                id=order_id,
                external_id=f"EXT-{index}",
                external_version=1,
                customer_id=f"cus-{index}",
                due_at=start + timedelta(hours=4),
                state=OrderState.ACCEPTED,
                lines=(
                    OrderLine(
                        id=line_id,
                        order_id=order_id,
                        recipe_version_id=version.id,
                        quantity=quantity,
                    ),
                ),
            )
        )
        promises.append(
            CustomerPromise(id=f"pr-{index}", order_id=order_id, due_at=start + timedelta(hours=4))
        )
        tasks.append(
            ProductionTask(
                id=f"task-{index}",
                order_line_id=line_id,
                state=TaskState.SCHEDULED,
                scheduled_start=start,
                scheduled_end=start + timedelta(hours=1),
                equipment_id=draw(st.sampled_from(equipment)),
            )
        )
        constraints.extend(_constraints_for(draw, order_id, index, ingredients, now))

    # --- supply --------------------------------------------------------------------------
    suppliers = [Supplier(id="sup-0", name="sup-0")]
    commitment_lines = draw(
        st.lists(st.sampled_from(ingredients), min_size=1, max_size=3, unique=True)
    )
    commitment = SupplierCommitment(
        id="com-0",
        supplier_id="sup-0",
        due_at=now + timedelta(minutes=draw(st.integers(min_value=1, max_value=120))),
        lines=tuple(
            CommitmentLine(
                id=f"cl-{resource_id}",
                commitment_id="com-0",
                resource_id=resource_id,
                quantity=amount(draw, high=80),
            )
            for resource_id in commitment_lines
        ),
    )
    ledger = [
        InventoryLedgerEntry(
            seq=index + 1,
            resource_id=resource_id,
            delta=amount(draw, low=0, high=60),
            source_kind=LedgerSourceKind.FIXTURE,
            source_id=f"fixture:{resource_id}",
            recorded_at=now - timedelta(hours=1),
        )
        for index, resource_id in enumerate(ingredients)
    ]

    # --- substitution policy -------------------------------------------------------------
    policies: list[SubstitutionPolicyEntry] = []
    for index, source in enumerate(versions):
        candidate = draw(st.sampled_from(versions))
        if candidate.id == source.id or not candidate.lines or not source.lines:
            continue
        if not draw(st.booleans()):
            continue
        source_line = source.lines[0]
        policies.append(
            SubstitutionPolicyEntry(
                id=f"pol-{index}",
                affected_resource_id=source_line.resource_id,
                role=source_line.role,
                source_version_id=source.id,
                candidate_version_id=candidate.id,
                substitute_resource_id=candidate.lines[0].resource_id,
                visible_change=draw(st.booleans()),
            )
        )

    resource_map = {resource.id: resource for resource in resources}
    version_map = {version.id: version for version in versions}
    reservations = [
        reservation
        for order in orders
        for line in order.lines
        for reservation in reservations_for_line(
            line, version_map[line.recipe_version_id], resource_map
        )
    ]

    snapshot = GraphSnapshot.build(
        resources=resources,
        suppliers=suppliers,
        commitments=[commitment],
        recipes=recipes,
        versions=versions,
        customers=customers,
        orders=orders,
        constraints=constraints,
        promises=promises,
        tasks=tasks,
        reservations=reservations,
        ledger=ledger,
        policies=policies,
        equipment_alternatives=[
            EquipmentAlternative(
                id="alt-0", equipment_id=equipment[0], alternative_equipment_id=equipment[1]
            ),
            EquipmentAlternative(
                id="alt-1", equipment_id=equipment[1], alternative_equipment_id=equipment[0]
            ),
        ],
        as_of=1,
    )
    return World(snapshot=snapshot, exception=_exception(draw, snapshot, now), now=now)


def _constraints_for(
    draw: st.DrawFn,
    order_id: str,
    index: int,
    ingredients: list[str],
    now: datetime,
) -> list[CustomerConstraint]:
    kinds = draw(
        st.lists(st.sampled_from(list(ConstraintKind)), min_size=0, max_size=2, unique=True)
    )
    result: list[CustomerConstraint] = []
    for position, kind in enumerate(kinds):
        resource_id: str | None = None
        substitute_id: str | None = None
        if kind is ConstraintKind.EXCLUDE_RESOURCE:
            resource_id = draw(st.sampled_from(ingredients))
        elif kind is ConstraintKind.PREAPPROVED_ALTERNATIVE:
            resource_id = draw(st.sampled_from(ingredients))
            substitute_id = draw(st.sampled_from(ingredients))
        result.append(
            CustomerConstraint(
                id=f"cn-{index}-{position}",
                order_id=order_id,
                kind=kind,
                resource_id=resource_id,
                substitute_resource_id=substitute_id,
                recorded_by="jo",
                recorded_at=now - timedelta(days=1),
            )
        )
    return result


def _exception(draw: st.DrawFn, snapshot: GraphSnapshot, now: datetime) -> PhysicalException:
    category = draw(st.sampled_from(list(ExceptionCategory)))
    if category is ExceptionCategory.SUPPLY_NOT_RECEIVED:
        commitment = snapshot.commitments["com-0"]
        scope = draw(
            st.lists(
                st.sampled_from([line.id for line in commitment.lines]),
                min_size=0,
                max_size=len(commitment.lines),
                unique=True,
            )
        )
        return PhysicalException(
            id="exc-0",
            category=category,
            commitment_id="com-0",
            scope_line_ids=tuple(sorted(scope)),
            reported_by="maya",
            reported_at=now,
        )
    if category is ExceptionCategory.STOCK_UNUSABLE:
        ingredient_ids = sorted(
            resource_id
            for resource_id, resource in snapshot.resources.items()
            if resource.kind is ResourceKind.INGREDIENT
        )
        return PhysicalException(
            id="exc-0",
            category=category,
            resource_id=draw(st.sampled_from(ingredient_ids)),
            reported_by="maya",
            reported_at=now,
        )
    return PhysicalException(
        id="exc-0",
        category=category,
        resource_id=draw(st.sampled_from(["res-e0", "res-e1"])),
        outage_until=now + timedelta(hours=draw(st.integers(min_value=1, max_value=30))),
        reported_by="maya",
        reported_at=now,
    )


# --------------------------------------------------------------------------- transformations


def add_on_hand(snapshot: GraphSnapshot, resource_id: str, quantity: Decimal) -> GraphSnapshot:
    """Add usable supply that is on hand right now."""
    entry = InventoryLedgerEntry(
        seq=snapshot.next_ledger_seq(),
        resource_id=resource_id,
        delta=quantity,
        source_kind=LedgerSourceKind.CORRECTION,
        source_id=f"topup:{resource_id}:{snapshot.next_ledger_seq()}",
        recorded_at=ANCHOR - timedelta(minutes=1),
    )
    return snapshot.append_ledger([entry])


def rebuild(snapshot: GraphSnapshot, *, reverse: bool = False) -> GraphSnapshot:
    """Rebuild from the same records, optionally in reverse input order."""

    def order(values: list[Any]) -> list[Any]:
        return list(reversed(values)) if reverse else values

    return GraphSnapshot.build(
        resources=order(list(snapshot.resources.values())),
        suppliers=order(list(snapshot.suppliers.values())),
        commitments=order(list(snapshot.commitments.values())),
        recipes=order(list(snapshot.recipes.values())),
        versions=order(list(snapshot.versions.values())),
        customers=order(list(snapshot.customers.values())),
        orders=order(list(snapshot.orders.values())),
        constraints=order(list(snapshot.constraints.values())),
        promises=order(list(snapshot.promises.values())),
        tasks=order(list(snapshot.tasks.values())),
        reservations=order(list(snapshot.reservations.values())),
        ledger=order(list(snapshot.ledger)),
        outages=order(list(snapshot.outages)),
        policies=order(list(snapshot.policies.values())),
        equipment_alternatives=order(list(snapshot.equipment_alternatives.values())),
        as_of=snapshot.as_of,
    )


def id_mapping(snapshot: GraphSnapshot) -> dict[str, str]:
    """A deterministic bijection over every entity id in the snapshot."""
    ids: set[str] = set()
    for mapping in (
        snapshot.resources,
        snapshot.suppliers,
        snapshot.commitments,
        snapshot.recipes,
        snapshot.versions,
        snapshot.customers,
        snapshot.orders,
        snapshot.constraints,
        snapshot.promises,
        snapshot.tasks,
        snapshot.reservations,
        snapshot.policies,
        snapshot.equipment_alternatives,
    ):
        ids.update(mapping)
    ids.update(snapshot.order_lines)
    ids.update(snapshot.commitment_lines)
    return {
        original: "z" + hashlib.sha256(original.encode("utf-8")).hexdigest()[:16]
        for original in sorted(ids)
    }


def remap(value: Any, mapping: dict[str, str]) -> Any:
    """Rewrite every mapped id inside a record, recursively."""
    if isinstance(value, Record):
        changes = {name: remap(getattr(value, name), mapping) for name in type(value).model_fields}
        return type(value)(**changes)
    if isinstance(value, tuple):
        return tuple(remap(item, mapping) for item in value)
    if isinstance(value, str):
        return mapping.get(value, value)
    return value


def relabel(
    snapshot: GraphSnapshot, exception: PhysicalException
) -> tuple[GraphSnapshot, PhysicalException, dict[str, str]]:
    """Rename every entity, keeping the graph's shape identical."""
    mapping = id_mapping(snapshot)
    rebuilt = GraphSnapshot.build(
        resources=[remap(item, mapping) for item in snapshot.resources.values()],
        suppliers=[remap(item, mapping) for item in snapshot.suppliers.values()],
        commitments=[remap(item, mapping) for item in snapshot.commitments.values()],
        recipes=[remap(item, mapping) for item in snapshot.recipes.values()],
        versions=[remap(item, mapping) for item in snapshot.versions.values()],
        customers=[remap(item, mapping) for item in snapshot.customers.values()],
        orders=[remap(item, mapping) for item in snapshot.orders.values()],
        constraints=[remap(item, mapping) for item in snapshot.constraints.values()],
        promises=[remap(item, mapping) for item in snapshot.promises.values()],
        tasks=[remap(item, mapping) for item in snapshot.tasks.values()],
        reservations=[remap(item, mapping) for item in snapshot.reservations.values()],
        ledger=[remap(item, mapping) for item in snapshot.ledger],
        outages=[remap(item, mapping) for item in snapshot.outages],
        policies=[remap(item, mapping) for item in snapshot.policies.values()],
        equipment_alternatives=[
            remap(item, mapping) for item in snapshot.equipment_alternatives.values()
        ],
        as_of=snapshot.as_of,
    )
    return rebuilt, remap(exception, mapping), mapping
