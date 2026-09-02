"""Directional reachability from a physical exception to the promises it threatens.

Impact flows from the physical world toward the promise::

    SupplierCommitment.line -> Resource -> RecipeVersion -> OrderLine -> CustomerPromise
    Resource(EQUIPMENT)     -> ProductionTask ------------> OrderLine -> CustomerPromise

Reachability alone never makes a promise affected (spec invariant 11.4.4). Every reached
order line is quantified against current availability, and a reached-but-covered promise is
kept in the evidence as a distinct state from "no path" — the Evidence screen shows them
differently and Proof D depends on the distinction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from promise_graph.availability import AllocationResult, allocate
from promise_graph.model import (
    EdgeKind,
    ExceptionCategory,
    OrderLineId,
    PhysicalException,
    PromiseId,
    RecipeLineRole,
    ReservationId,
    ResourceId,
    TaskState,
)
from promise_graph.snapshot import GraphSnapshot

_LIVE_TASK_STATES = frozenset({TaskState.SCHEDULED, TaskState.STARTED, TaskState.HELD})


@dataclass(frozen=True)
class PathStep:
    """One node on a traversed path, with the edge that led into it."""

    node_ref: str
    edge_kind: EdgeKind | None = None
    role: RecipeLineRole | None = None


Path = tuple[PathStep, ...]


@dataclass(frozen=True)
class LineQuantification:
    """Whether a reached order line's claim on a failed resource can still be met."""

    order_line_id: OrderLineId
    resource_id: ResourceId
    reservation_id: ReservationId | None
    roles: tuple[RecipeLineRole, ...]
    need: Decimal | None
    available_before_start: Decimal | None
    shortfall: Decimal | None
    satisfied: bool
    unknown: bool


@dataclass(frozen=True)
class Impact:
    """The result of one propagation run."""

    exception_id: str
    category: ExceptionCategory
    entry_node_refs: tuple[str, ...]
    affected_resource_ids: frozenset[ResourceId]
    paths_by_promise: Mapping[PromiseId, tuple[Path, ...]]
    quantifications_by_line: Mapping[OrderLineId, tuple[LineQuantification, ...]]
    reached_promise_ids: frozenset[PromiseId]
    reached_order_line_ids: frozenset[OrderLineId]
    unsatisfied_line_ids: frozenset[OrderLineId]
    unknown_line_ids: frozenset[OrderLineId]
    equipment_blocked_line_ids: frozenset[OrderLineId]
    unreachable_promise_ids: frozenset[PromiseId]
    affected_promise_ids: frozenset[PromiseId]
    covered_promise_ids: frozenset[PromiseId]

    @property
    def equipment_origin(self) -> bool:
        return self.category is ExceptionCategory.EQUIPMENT_UNAVAILABLE

    def lines_of_promise(self, snapshot: GraphSnapshot, promise_id: PromiseId) -> tuple[str, ...]:
        promise = snapshot.promises[promise_id]
        return tuple(
            sorted(
                line.id
                for line in snapshot.orders[promise.order_id].lines
                if line.id in self.reached_order_line_ids
            )
        )


def propagate(snapshot: GraphSnapshot, exception: PhysicalException, now: datetime) -> Impact:
    """Traverse propagating edges from the exception's bound node(s) and quantify each hit."""
    if exception.category is ExceptionCategory.EQUIPMENT_UNAVAILABLE:
        return _propagate_equipment(snapshot, exception, now)
    return _propagate_supply(snapshot, exception, now)


# --------------------------------------------------------------------------- ingredient path


def _entry_resources(snapshot: GraphSnapshot, exception: PhysicalException) -> tuple[str, ...]:
    if exception.category is ExceptionCategory.STOCK_UNUSABLE:
        return (str(exception.resource_id),)
    commitment = snapshot.commitments[str(exception.commitment_id)]
    scope = set(exception.scope_line_ids) or {line.id for line in commitment.lines}
    return tuple(sorted({line.resource_id for line in commitment.lines if line.id in scope}))


def _entry_refs(snapshot: GraphSnapshot, exception: PhysicalException) -> tuple[str, ...]:
    if exception.category is ExceptionCategory.STOCK_UNUSABLE:
        return (str(exception.resource_id),)
    commitment = snapshot.commitments[str(exception.commitment_id)]
    scope = set(exception.scope_line_ids) or {line.id for line in commitment.lines}
    return tuple(sorted(line.id for line in commitment.lines if line.id in scope))


def _propagate_supply(
    snapshot: GraphSnapshot, exception: PhysicalException, now: datetime
) -> Impact:
    entry_resources = _entry_resources(snapshot, exception)
    entry_refs = _entry_refs(snapshot, exception)
    is_supply = exception.category is ExceptionCategory.SUPPLY_NOT_RECEIVED

    paths: dict[PromiseId, list[Path]] = {}
    line_roles: dict[tuple[OrderLineId, ResourceId], set[RecipeLineRole]] = {}
    reached_lines: set[OrderLineId] = set()

    for resource_id in entry_resources:
        head: list[PathStep] = []
        if is_supply:
            for line_id in entry_refs:
                if snapshot.commitment_lines[line_id].resource_id == resource_id:
                    head = [PathStep(node_ref=line_id)]
                    break
        prefix: tuple[PathStep, ...] = (
            (*head, PathStep(resource_id, EdgeKind.COMMITMENT_LINE_TO_RESOURCE))
            if head
            else (PathStep(resource_id),)
        )
        for version_id, role in snapshot.versions_by_resource.get(resource_id, ()):
            version_step = PathStep(version_id, EdgeKind.RESOURCE_TO_RECIPE_VERSION, role)
            for order_line_id in snapshot.order_lines_by_version.get(version_id, ()):
                promise_id = snapshot.promise_of_line(order_line_id)
                if promise_id is None:
                    continue
                reached_lines.add(order_line_id)
                line_roles.setdefault((order_line_id, resource_id), set()).add(role)
                path: Path = (
                    *prefix,
                    version_step,
                    PathStep(order_line_id, EdgeKind.RECIPE_VERSION_TO_ORDER_LINE, role),
                    PathStep(promise_id, EdgeKind.ORDER_LINE_TO_PROMISE, role),
                )
                paths.setdefault(promise_id, []).append(path)

    allocations: dict[ResourceId, AllocationResult] = {
        resource_id: allocate(snapshot, resource_id, now) for resource_id in entry_resources
    }

    quantifications: dict[OrderLineId, list[LineQuantification]] = {}
    unsatisfied: set[OrderLineId] = set()
    unknown: set[OrderLineId] = set()
    for (order_line_id, resource_id), roles in sorted(line_roles.items(), key=lambda item: item[0]):
        quantification = _quantify(
            snapshot, allocations[resource_id], order_line_id, resource_id, tuple(sorted(roles))
        )
        quantifications.setdefault(order_line_id, []).append(quantification)
        if quantification.unknown:
            unknown.add(order_line_id)
        elif not quantification.satisfied:
            unsatisfied.add(order_line_id)

    return _assemble(
        snapshot=snapshot,
        exception=exception,
        entry_refs=entry_refs,
        affected_resource_ids=frozenset(entry_resources),
        paths=paths,
        quantifications=quantifications,
        reached_lines=reached_lines,
        unsatisfied=unsatisfied,
        unknown=unknown,
        equipment_blocked=set(),
    )


def _quantify(
    snapshot: GraphSnapshot,
    allocation_result: AllocationResult,
    order_line_id: OrderLineId,
    resource_id: ResourceId,
    roles: tuple[RecipeLineRole, ...],
) -> LineQuantification:
    reservation_id: ReservationId | None = None
    for candidate in snapshot.reservations_by_order_line.get(order_line_id, ()):
        if snapshot.reservations[candidate].resource_id == resource_id:
            reservation_id = candidate
            break

    if allocation_result.unknown:
        return LineQuantification(
            order_line_id=order_line_id,
            resource_id=resource_id,
            reservation_id=reservation_id,
            roles=roles,
            need=None,
            available_before_start=None,
            shortfall=None,
            satisfied=False,
            unknown=True,
        )

    allocation = None if reservation_id is None else allocation_result.for_claim(reservation_id)
    if allocation is None:
        # No live claim on this resource for this line: nothing to leave unsatisfied.
        return LineQuantification(
            order_line_id=order_line_id,
            resource_id=resource_id,
            reservation_id=reservation_id,
            roles=roles,
            need=None,
            available_before_start=None,
            shortfall=None,
            satisfied=True,
            unknown=False,
        )
    return LineQuantification(
        order_line_id=order_line_id,
        resource_id=resource_id,
        reservation_id=reservation_id,
        roles=roles,
        need=allocation.need,
        available_before_start=allocation.available_before_start,
        shortfall=allocation.shortfall,
        satisfied=allocation.satisfied,
        unknown=False,
    )


# --------------------------------------------------------------------------- equipment path


def _propagate_equipment(
    snapshot: GraphSnapshot, exception: PhysicalException, now: datetime
) -> Impact:
    equipment_id = str(exception.resource_id)
    window_start = now
    window_end = exception.outage_until

    paths: dict[PromiseId, list[Path]] = {}
    reached_lines: set[OrderLineId] = set()
    blocked: set[OrderLineId] = set()
    unknown: set[OrderLineId] = set()

    for task_id in snapshot.tasks_by_equipment.get(equipment_id, ()):
        task = snapshot.tasks[task_id]
        if task.state not in _LIVE_TASK_STATES:
            continue
        promise_id = snapshot.promise_of_line(task.order_line_id)
        if promise_id is None:
            continue
        if task.scheduled_start is None:
            reached_lines.add(task.order_line_id)
            unknown.add(task.order_line_id)
        elif not _overlaps(task.scheduled_start, task.scheduled_end, window_start, window_end):
            continue
        else:
            reached_lines.add(task.order_line_id)
            blocked.add(task.order_line_id)
        paths.setdefault(promise_id, []).append(
            (
                PathStep(equipment_id),
                PathStep(task_id, EdgeKind.EQUIPMENT_TO_PRODUCTION_TASK),
                PathStep(task.order_line_id, EdgeKind.PRODUCTION_TASK_TO_ORDER_LINE),
                PathStep(promise_id, EdgeKind.ORDER_LINE_TO_PROMISE),
            )
        )

    return _assemble(
        snapshot=snapshot,
        exception=exception,
        entry_refs=(equipment_id,),
        affected_resource_ids=frozenset({equipment_id}),
        paths=paths,
        quantifications={},
        reached_lines=reached_lines,
        unsatisfied=blocked,
        unknown=unknown,
        equipment_blocked=blocked,
    )


def _overlaps(
    start: datetime, end: datetime | None, window_start: datetime, window_end: datetime | None
) -> bool:
    task_end = end if end is not None else start
    if task_end < window_start:
        return False
    return not (window_end is not None and start >= window_end)


# --------------------------------------------------------------------------- assembly


def _assemble(
    *,
    snapshot: GraphSnapshot,
    exception: PhysicalException,
    entry_refs: tuple[str, ...],
    affected_resource_ids: frozenset[ResourceId],
    paths: dict[PromiseId, list[Path]],
    quantifications: dict[OrderLineId, list[LineQuantification]],
    reached_lines: set[OrderLineId],
    unsatisfied: set[OrderLineId],
    unknown: set[OrderLineId],
    equipment_blocked: set[OrderLineId],
) -> Impact:
    reached_promises = frozenset(paths)
    all_promises = frozenset(snapshot.promises)
    affected: set[PromiseId] = set()
    for promise_id in reached_promises:
        order_id = snapshot.promises[promise_id].order_id
        line_ids = {line.id for line in snapshot.orders[order_id].lines}
        if line_ids & (unsatisfied | unknown):
            affected.add(promise_id)
    return Impact(
        exception_id=exception.id,
        category=exception.category,
        entry_node_refs=entry_refs,
        affected_resource_ids=affected_resource_ids,
        paths_by_promise={
            promise_id: tuple(sorted(promise_paths, key=_path_key))
            for promise_id, promise_paths in sorted(paths.items())
        },
        quantifications_by_line={
            line_id: tuple(items) for line_id, items in sorted(quantifications.items())
        },
        reached_promise_ids=reached_promises,
        reached_order_line_ids=frozenset(reached_lines),
        unsatisfied_line_ids=frozenset(unsatisfied),
        unknown_line_ids=frozenset(unknown),
        equipment_blocked_line_ids=frozenset(equipment_blocked),
        unreachable_promise_ids=all_promises - reached_promises,
        affected_promise_ids=frozenset(affected),
        covered_promise_ids=reached_promises - frozenset(affected),
    )


def _path_key(path: Path) -> tuple[str, ...]:
    return tuple(step.node_ref for step in path)
