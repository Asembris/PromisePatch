"""The immutable in-memory graph.

``GraphSnapshot`` holds every Phase-0 record plus the adjacency indexes the traversal and
availability code needs. It is built once and never mutated: every transformation returns a
new snapshot.

Two kinds of problem are distinguished on purpose:

* **Structural violations** (an order line pinned to a version that does not exist, a task
  naming an unknown order line) raise :class:`SnapshotIntegrityError`. Spec invariant 11.4.2
  says these cannot exist, and the eventual database enforces it with foreign keys.
* **Value unknowns** (a ``None`` quantity, a ``None`` task start, an order with no constraint
  snapshot) are perfectly representable. They flow through the engine and fail closed to
  ``BLOCKED``. Fail-closed is a classification outcome, never an exception.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from promise_graph.model import (
    CommitmentId,
    CommitmentLine,
    CommitmentLineId,
    ConstraintId,
    Customer,
    CustomerConstraint,
    CustomerId,
    CustomerPromise,
    EquipmentAlternative,
    EquipmentOutage,
    InventoryLedgerEntry,
    InventoryReservation,
    Order,
    OrderId,
    OrderLine,
    OrderLineId,
    PolicyId,
    ProductionTask,
    PromiseId,
    ReceivedState,
    Recipe,
    RecipeId,
    RecipeLineRole,
    RecipeVersion,
    RecipeVersionId,
    ReservationId,
    Resource,
    ResourceId,
    ResourceKind,
    SubstitutionPolicyEntry,
    Supplier,
    SupplierCommitment,
    SupplierId,
    TaskId,
)


class SnapshotIntegrityError(Exception):
    """Raised when the records handed to the snapshot are structurally inconsistent."""


PolicyKey = tuple[ResourceId, RecipeLineRole, RecipeVersionId]


@dataclass(frozen=True)
class LineSettlement:
    """A commitment line moving from open to settled."""

    commitment_line_id: CommitmentLineId
    to_state: ReceivedState
    received_qty: Decimal | None
    settled_at: datetime
    attested_by: str


@dataclass(frozen=True)
class GraphSnapshot:
    """An immutable, indexed view of the promise graph at one point in time."""

    resources: Mapping[ResourceId, Resource]
    suppliers: Mapping[SupplierId, Supplier]
    commitments: Mapping[CommitmentId, SupplierCommitment]
    recipes: Mapping[RecipeId, Recipe]
    versions: Mapping[RecipeVersionId, RecipeVersion]
    customers: Mapping[CustomerId, Customer]
    orders: Mapping[OrderId, Order]
    constraints: Mapping[ConstraintId, CustomerConstraint]
    promises: Mapping[PromiseId, CustomerPromise]
    tasks: Mapping[TaskId, ProductionTask]
    reservations: Mapping[ReservationId, InventoryReservation]
    ledger: tuple[InventoryLedgerEntry, ...]
    outages: tuple[EquipmentOutage, ...]
    policies: Mapping[PolicyId, SubstitutionPolicyEntry]
    equipment_alternatives: Mapping[PolicyId, EquipmentAlternative]
    as_of: int

    # --- derived indexes, rebuilt on every construction ---------------------------------
    order_lines: Mapping[OrderLineId, OrderLine] = field(init=False, repr=False, compare=False)
    commitment_lines: Mapping[CommitmentLineId, CommitmentLine] = field(
        init=False, repr=False, compare=False
    )
    versions_by_resource: Mapping[
        ResourceId, tuple[tuple[RecipeVersionId, RecipeLineRole], ...]
    ] = field(init=False, repr=False, compare=False)
    order_lines_by_version: Mapping[RecipeVersionId, tuple[OrderLineId, ...]] = field(
        init=False, repr=False, compare=False
    )
    promise_by_order: Mapping[OrderId, PromiseId] = field(init=False, repr=False, compare=False)
    task_by_order_line: Mapping[OrderLineId, TaskId] = field(init=False, repr=False, compare=False)
    tasks_by_equipment: Mapping[ResourceId, tuple[TaskId, ...]] = field(
        init=False, repr=False, compare=False
    )
    reservations_by_resource: Mapping[ResourceId, tuple[ReservationId, ...]] = field(
        init=False, repr=False, compare=False
    )
    reservations_by_order_line: Mapping[OrderLineId, tuple[ReservationId, ...]] = field(
        init=False, repr=False, compare=False
    )
    constraints_by_order: Mapping[OrderId, tuple[ConstraintId, ...]] = field(
        init=False, repr=False, compare=False
    )
    commitment_lines_by_resource: Mapping[ResourceId, tuple[CommitmentLineId, ...]] = field(
        init=False, repr=False, compare=False
    )
    ledger_by_resource: Mapping[ResourceId, tuple[InventoryLedgerEntry, ...]] = field(
        init=False, repr=False, compare=False
    )
    outages_by_equipment: Mapping[ResourceId, tuple[EquipmentOutage, ...]] = field(
        init=False, repr=False, compare=False
    )
    policy_by_key: Mapping[PolicyKey, PolicyId] = field(init=False, repr=False, compare=False)
    alternatives_by_equipment: Mapping[ResourceId, tuple[ResourceId, ...]] = field(
        init=False, repr=False, compare=False
    )

    # ------------------------------------------------------------------ construction

    @classmethod
    def build(
        cls,
        *,
        resources: Sequence[Resource] = (),
        suppliers: Sequence[Supplier] = (),
        commitments: Sequence[SupplierCommitment] = (),
        recipes: Sequence[Recipe] = (),
        versions: Sequence[RecipeVersion] = (),
        customers: Sequence[Customer] = (),
        orders: Sequence[Order] = (),
        constraints: Sequence[CustomerConstraint] = (),
        promises: Sequence[CustomerPromise] = (),
        tasks: Sequence[ProductionTask] = (),
        reservations: Sequence[InventoryReservation] = (),
        ledger: Sequence[InventoryLedgerEntry] = (),
        outages: Sequence[EquipmentOutage] = (),
        policies: Sequence[SubstitutionPolicyEntry] = (),
        equipment_alternatives: Sequence[EquipmentAlternative] = (),
        as_of: int = 0,
    ) -> GraphSnapshot:
        """Build a snapshot from unordered record sequences.

        Input order never matters: every mapping and index is keyed or sorted, so two
        snapshots built from the same records in different orders compare equal.
        """
        return cls(
            resources=_by_id(resources, "resource"),
            suppliers=_by_id(suppliers, "supplier"),
            commitments=_by_id(commitments, "commitment"),
            recipes=_by_id(recipes, "recipe"),
            versions=_by_id(versions, "recipe version"),
            customers=_by_id(customers, "customer"),
            orders=_by_id(orders, "order"),
            constraints=_by_id(constraints, "constraint"),
            promises=_by_id(promises, "promise"),
            tasks=_by_id(tasks, "task"),
            reservations=_by_id(reservations, "reservation"),
            ledger=tuple(sorted(ledger, key=lambda entry: entry.seq)),
            outages=tuple(sorted(outages, key=lambda outage: outage.id)),
            policies=_by_id(policies, "substitution policy"),
            equipment_alternatives=_by_id(equipment_alternatives, "equipment alternative"),
            as_of=as_of,
        )

    def __post_init__(self) -> None:
        self._validate_structure()
        self._build_indexes()

    def replace(self, **changes: Any) -> GraphSnapshot:
        """Return a new snapshot with primary collections replaced and indexes rebuilt."""
        return dataclasses.replace(self, **changes)

    # ------------------------------------------------------------------ validation

    def _validate_structure(self) -> None:
        resources = self.resources
        versions = self.versions

        for supplier_commitment in self.commitments.values():
            _require(
                supplier_commitment.supplier_id in self.suppliers,
                f"commitment {supplier_commitment.id} names unknown supplier",
            )
            for line in supplier_commitment.lines:
                _require(
                    line.resource_id in resources,
                    f"commitment line {line.id} names unknown resource",
                )

        for version in versions.values():
            _require(
                version.recipe_id in self.recipes,
                f"recipe version {version.id} names unknown recipe",
            )
            for version_line in version.lines:
                _require(
                    version_line.resource_id in resources,
                    f"recipe version {version.id} names unknown resource",
                )
            for equipment_id in version.equipment_ids:
                _require(
                    equipment_id in resources,
                    f"recipe version {version.id} names unknown equipment",
                )

        order_line_ids: set[OrderLineId] = set()
        for order in self.orders.values():
            _require(
                order.customer_id in self.customers,
                f"order {order.id} names unknown customer",
            )
            for order_line in order.lines:
                _require(
                    order_line.recipe_version_id in versions,
                    f"order line {order_line.id} pins unknown recipe version",
                )
                order_line_ids.add(order_line.id)

        for constraint in self.constraints.values():
            _require(
                constraint.order_id in self.orders,
                f"constraint {constraint.id} names unknown order",
            )
            for constrained in (constraint.resource_id, constraint.substitute_resource_id):
                _require(
                    constrained is None or constrained in resources,
                    f"constraint {constraint.id} names unknown resource",
                )

        for promise in self.promises.values():
            _require(
                promise.order_id in self.orders,
                f"promise {promise.id} names unknown order",
            )

        for task in self.tasks.values():
            _require(
                task.order_line_id in order_line_ids,
                f"task {task.id} names unknown order line",
            )
            if task.equipment_id is not None:
                _require(
                    task.equipment_id in resources
                    and resources[task.equipment_id].kind is ResourceKind.EQUIPMENT,
                    f"task {task.id} names unknown equipment",
                )

        for reservation in self.reservations.values():
            _require(
                reservation.order_line_id in order_line_ids,
                f"reservation {reservation.id} names unknown order line",
            )
            _require(
                reservation.resource_id in resources,
                f"reservation {reservation.id} names unknown resource",
            )
            _require(
                reservation.source_recipe_version_id in versions,
                f"reservation {reservation.id} names unknown recipe version",
            )

        for entry in self.ledger:
            _require(
                entry.resource_id in resources,
                f"ledger entry {entry.seq} names unknown resource",
            )

        for outage in self.outages:
            _require(
                outage.equipment_id in resources,
                f"outage {outage.id} names unknown equipment",
            )

        for policy in self.policies.values():
            _require(
                policy.source_version_id in versions and policy.candidate_version_id in versions,
                f"policy {policy.id} names unknown recipe version",
            )
            _require(
                policy.affected_resource_id in resources
                and policy.substitute_resource_id in resources,
                f"policy {policy.id} names unknown resource",
            )

        for alternative in self.equipment_alternatives.values():
            _require(
                alternative.equipment_id in resources
                and alternative.alternative_equipment_id in resources,
                f"equipment alternative {alternative.id} names unknown equipment",
            )

    # ------------------------------------------------------------------ indexes

    def _build_indexes(self) -> None:
        order_lines: dict[OrderLineId, OrderLine] = {}
        for order in _sorted_values(self.orders):
            for order_line in sorted(order.lines, key=lambda line: line.id):
                order_lines[order_line.id] = order_line

        commitment_lines: dict[CommitmentLineId, CommitmentLine] = {}
        commitment_lines_by_resource: dict[ResourceId, list[CommitmentLineId]] = {}
        for commitment in _sorted_values(self.commitments):
            for line in sorted(commitment.lines, key=lambda item: item.id):
                commitment_lines[line.id] = line
                commitment_lines_by_resource.setdefault(line.resource_id, []).append(line.id)

        versions_by_resource: dict[ResourceId, list[tuple[RecipeVersionId, RecipeLineRole]]] = {}
        for version in _sorted_values(self.versions):
            for version_line in sorted(
                version.lines, key=lambda item: (item.resource_id, item.role)
            ):
                versions_by_resource.setdefault(version_line.resource_id, []).append(
                    (version.id, version_line.role)
                )

        order_lines_by_version: dict[RecipeVersionId, list[OrderLineId]] = {}
        for line_id, order_line in order_lines.items():
            order_lines_by_version.setdefault(order_line.recipe_version_id, []).append(line_id)

        promise_by_order = {
            promise.order_id: promise.id for promise in _sorted_values(self.promises)
        }

        task_by_order_line: dict[OrderLineId, TaskId] = {}
        tasks_by_equipment: dict[ResourceId, list[TaskId]] = {}
        for task in _sorted_values(self.tasks):
            task_by_order_line[task.order_line_id] = task.id
            if task.equipment_id is not None:
                tasks_by_equipment.setdefault(task.equipment_id, []).append(task.id)

        reservations_by_resource: dict[ResourceId, list[ReservationId]] = {}
        reservations_by_order_line: dict[OrderLineId, list[ReservationId]] = {}
        for reservation in _sorted_values(self.reservations):
            reservations_by_resource.setdefault(reservation.resource_id, []).append(reservation.id)
            reservations_by_order_line.setdefault(reservation.order_line_id, []).append(
                reservation.id
            )

        constraints_by_order: dict[OrderId, list[ConstraintId]] = {}
        for constraint in _sorted_values(self.constraints):
            constraints_by_order.setdefault(constraint.order_id, []).append(constraint.id)

        ledger_by_resource: dict[ResourceId, list[InventoryLedgerEntry]] = {}
        for entry in self.ledger:
            ledger_by_resource.setdefault(entry.resource_id, []).append(entry)

        outages_by_equipment: dict[ResourceId, list[EquipmentOutage]] = {}
        for outage in self.outages:
            outages_by_equipment.setdefault(outage.equipment_id, []).append(outage)

        policy_by_key: dict[PolicyKey, PolicyId] = {}
        for policy in _sorted_values(self.policies):
            policy_by_key[(policy.affected_resource_id, policy.role, policy.source_version_id)] = (
                policy.id
            )

        alternatives_by_equipment: dict[ResourceId, list[ResourceId]] = {}
        for alternative in _sorted_values(self.equipment_alternatives):
            alternatives_by_equipment.setdefault(alternative.equipment_id, []).append(
                alternative.alternative_equipment_id
            )

        _set(self, "order_lines", order_lines)
        _set(self, "commitment_lines", commitment_lines)
        _set(self, "versions_by_resource", _freeze_lists(versions_by_resource))
        _set(self, "order_lines_by_version", _freeze_sorted(order_lines_by_version))
        _set(self, "promise_by_order", promise_by_order)
        _set(self, "task_by_order_line", task_by_order_line)
        _set(self, "tasks_by_equipment", _freeze_sorted(tasks_by_equipment))
        _set(self, "reservations_by_resource", _freeze_sorted(reservations_by_resource))
        _set(self, "reservations_by_order_line", _freeze_sorted(reservations_by_order_line))
        _set(self, "constraints_by_order", _freeze_sorted(constraints_by_order))
        _set(self, "commitment_lines_by_resource", _freeze_sorted(commitment_lines_by_resource))
        _set(self, "ledger_by_resource", _freeze_lists(ledger_by_resource))
        _set(self, "outages_by_equipment", _freeze_lists(outages_by_equipment))
        _set(self, "policy_by_key", policy_by_key)
        _set(self, "alternatives_by_equipment", _freeze_sorted(alternatives_by_equipment))

    # ------------------------------------------------------------------ lookups

    def order_of_line(self, order_line_id: OrderLineId) -> Order:
        return self.orders[self.order_lines[order_line_id].order_id]

    def promise_of_line(self, order_line_id: OrderLineId) -> PromiseId | None:
        return self.promise_by_order.get(self.order_lines[order_line_id].order_id)

    def task_of_line(self, order_line_id: OrderLineId) -> ProductionTask | None:
        task_id = self.task_by_order_line.get(order_line_id)
        return None if task_id is None else self.tasks[task_id]

    def constraints_for_order(self, order_id: OrderId) -> tuple[CustomerConstraint, ...]:
        return tuple(
            self.constraints[constraint_id]
            for constraint_id in self.constraints_by_order.get(order_id, ())
        )

    def next_ledger_seq(self) -> int:
        return max((entry.seq for entry in self.ledger), default=0) + 1

    # ------------------------------------------------------------------ transformations

    def append_ledger(self, entries: Iterable[InventoryLedgerEntry]) -> GraphSnapshot:
        new_entries = tuple(entries)
        if not new_entries:
            return self
        return self.replace(ledger=tuple(sorted(self.ledger + new_entries, key=lambda e: e.seq)))

    def add_outage(self, outage: EquipmentOutage) -> GraphSnapshot:
        return self.replace(outages=tuple(sorted((*self.outages, outage), key=lambda o: o.id)))

    def settle_commitment_lines(self, settlements: Sequence[LineSettlement]) -> GraphSnapshot:
        """Return a snapshot whose named lines have moved from ``EXPECTED`` to a settled state."""
        if not settlements:
            return self
        by_line = {settlement.commitment_line_id: settlement for settlement in settlements}
        commitments: dict[CommitmentId, SupplierCommitment] = {}
        for commitment_id, commitment in self.commitments.items():
            if not any(line.id in by_line for line in commitment.lines):
                commitments[commitment_id] = commitment
                continue
            lines = tuple(
                line
                if line.id not in by_line
                else line.model_copy(
                    update={
                        "received_state": by_line[line.id].to_state,
                        "received_qty": by_line[line.id].received_qty,
                        "settled_at": by_line[line.id].settled_at,
                        "attested_by": by_line[line.id].attested_by,
                    }
                )
                for line in commitment.lines
            )
            commitments[commitment_id] = commitment.model_copy(update={"lines": lines})
        return self.replace(commitments=commitments)

    def repin_order_line(
        self, order_line_id: OrderLineId, recipe_version_id: RecipeVersionId
    ) -> GraphSnapshot:
        """Re-pin one order line to another existing version and recompute its reservations.

        This is the shape of both the external order-system mutation and a governed recovery
        amendment. It never creates a version: the target must already exist.
        """
        if recipe_version_id not in self.versions:
            raise SnapshotIntegrityError(f"unknown recipe version {recipe_version_id}")
        order_line = self.order_lines[order_line_id]
        order = self.orders[order_line.order_id]
        new_line = order_line.model_copy(update={"recipe_version_id": recipe_version_id})
        new_lines = tuple(new_line if line.id == order_line_id else line for line in order.lines)
        orders = dict(self.orders)
        orders[order.id] = order.model_copy(update={"lines": new_lines})

        reservations = {
            reservation_id: reservation
            for reservation_id, reservation in self.reservations.items()
            if reservation.order_line_id != order_line_id
        }
        for reservation in reservations_for_line(
            new_line, self.versions[recipe_version_id], self.resources
        ):
            reservations[reservation.id] = reservation
        return self.replace(orders=orders, reservations=reservations)


def reservations_for_line(
    order_line: OrderLine,
    version: RecipeVersion,
    resources: Mapping[ResourceId, Resource],
) -> tuple[InventoryReservation, ...]:
    """Derive a line's reservations from its pinned version (invariant 11.4.3)."""
    derived: list[InventoryReservation] = []
    for version_line in sorted(version.lines, key=lambda item: item.resource_id):
        if resources[version_line.resource_id].kind is not ResourceKind.INGREDIENT:
            continue
        quantity = (
            None
            if version_line.qty_per_unit is None
            else version_line.qty_per_unit * order_line.quantity
        )
        derived.append(
            InventoryReservation(
                id=f"{order_line.id}:{version_line.resource_id}",
                order_line_id=order_line.id,
                resource_id=version_line.resource_id,
                quantity=quantity,
                source_recipe_version_id=version.id,
            )
        )
    return tuple(derived)


# --------------------------------------------------------------------------- helpers


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotIntegrityError(message)


class _HasId(Protocol):
    @property
    def id(self) -> str: ...


def _by_id[R: _HasId](records: Sequence[R], label: str) -> dict[str, R]:
    result: dict[str, R] = {}
    for record in records:
        if record.id in result:
            raise SnapshotIntegrityError(f"duplicate {label} id {record.id}")
        result[record.id] = record
    return dict(sorted(result.items()))


def _sorted_values[V](mapping: Mapping[str, V]) -> list[V]:
    return [mapping[key] for key in sorted(mapping)]


def _freeze_sorted[K](mapping: Mapping[K, list[str]]) -> dict[K, tuple[str, ...]]:
    return {key: tuple(sorted(values)) for key, values in _sorted_items(mapping)}


def _freeze_lists[K, V](mapping: Mapping[K, list[V]]) -> dict[K, tuple[V, ...]]:
    return {key: tuple(values) for key, values in _sorted_items(mapping)}


def _sorted_items[K, V](mapping: Mapping[K, V]) -> list[tuple[K, V]]:
    return sorted(mapping.items(), key=lambda item: str(item[0]))


def _set(instance: object, name: str, value: object) -> None:
    object.__setattr__(instance, name, value)
