"""Snapshot fingerprints and their human-readable diff.

A track's fingerprint is taken over exactly the state that could invalidate its plan: the
order's version and state, its lines' pinned versions, the order's constraint hash, its
reservations, its production tasks, and — for every resource on the track's paths and every
substitute named by its options — the resource's ledger position and commitment line states.

Anything outside that scope is *irrelevant by definition*, which is what makes "irrelevant
changes do not move the fingerprint" a testable property rather than an opinion.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from promise_graph.model import (
    OrderId,
    OrderLineId,
    PromiseId,
    ResourceId,
    TaskId,
)
from promise_graph.options import OptionSet
from promise_graph.propagation import Impact
from promise_graph.snapshot import GraphSnapshot


@dataclass(frozen=True)
class TrackScope:
    """The entities one track watches. Derived, never caller-supplied."""

    promise_id: PromiseId
    order_id: OrderId
    order_line_ids: tuple[OrderLineId, ...]
    resource_ids: tuple[ResourceId, ...]
    task_ids: tuple[TaskId, ...]


@dataclass(frozen=True)
class FingerprintInput:
    order_external_version: int
    order_state: str
    pinned_versions: tuple[tuple[str, str], ...]
    constraint_hash: str
    reservations: tuple[tuple[str, str, str], ...]
    tasks: tuple[tuple[str, str, str, str, str], ...]
    resources: tuple[tuple[str, int, tuple[tuple[str, str, str], ...]], ...]


@dataclass(frozen=True)
class Fingerprint:
    hash: str
    input: FingerprintInput


@dataclass(frozen=True)
class FieldDiff:
    field: str
    before: str
    after: str


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, fixed-point decimals, UTC timestamps."""
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def constraint_hash(snapshot: GraphSnapshot, order_id: OrderId) -> str:
    """Hash of an order's constraint snapshot, including provenance."""
    rows = [
        (
            constraint.id,
            str(constraint.kind),
            constraint.resource_id or "",
            constraint.substitute_resource_id or "",
            constraint.recorded_by,
            constraint.recorded_at.isoformat(),
        )
        for constraint in snapshot.constraints_for_order(order_id)
    ]
    return hashlib.sha256(canonical_json(sorted(rows)).encode("utf-8")).hexdigest()


def scope_for(
    snapshot: GraphSnapshot,
    impact: Impact,
    option_set: OptionSet,
    promise_id: PromiseId,
) -> TrackScope:
    """Everything this track's outcome depends on."""
    order_id = snapshot.promises[promise_id].order_id
    order = snapshot.orders[order_id]
    line_ids = tuple(sorted(line.id for line in order.lines))

    resources: set[ResourceId] = set(impact.affected_resource_ids)
    for line_id in line_ids:
        for quantification in impact.quantifications_by_line.get(line_id, ()):
            resources.add(quantification.resource_id)
    for option in option_set.valid:
        if option.substitute_resource_id is not None:
            resources.add(option.substitute_resource_id)
        if option.to_equipment_id is not None:
            resources.add(option.to_equipment_id)

    task_ids = tuple(
        sorted(
            task.id for line_id in line_ids if (task := snapshot.task_of_line(line_id)) is not None
        )
    )
    return TrackScope(
        promise_id=promise_id,
        order_id=order_id,
        order_line_ids=line_ids,
        resource_ids=tuple(sorted(resources)),
        task_ids=task_ids,
    )


def fingerprint_input(snapshot: GraphSnapshot, scope: TrackScope) -> FingerprintInput:
    order = snapshot.orders[scope.order_id]
    pinned = tuple(
        (line_id, snapshot.order_lines[line_id].recipe_version_id)
        for line_id in scope.order_line_ids
    )
    reservations: list[tuple[str, str, str]] = []
    for line_id in scope.order_line_ids:
        for reservation_id in snapshot.reservations_by_order_line.get(line_id, ()):
            reservation = snapshot.reservations[reservation_id]
            reservations.append(
                (
                    reservation.id,
                    reservation.resource_id,
                    _decimal(reservation.quantity),
                )
            )
    tasks = tuple(
        (
            task_id,
            str(snapshot.tasks[task_id].state),
            _instant(snapshot.tasks[task_id].scheduled_start),
            snapshot.tasks[task_id].equipment_id or "",
            snapshot.tasks[task_id].held_by_case_id or "",
        )
        for task_id in scope.task_ids
    )
    resources = tuple(
        (
            resource_id,
            max(
                (entry.seq for entry in snapshot.ledger_by_resource.get(resource_id, ())),
                default=0,
            ),
            tuple(
                (
                    line_id,
                    str(snapshot.commitment_lines[line_id].received_state),
                    _decimal(snapshot.commitment_lines[line_id].quantity),
                )
                for line_id in snapshot.commitment_lines_by_resource.get(resource_id, ())
            ),
        )
        for resource_id in scope.resource_ids
    )
    return FingerprintInput(
        order_external_version=order.external_version,
        order_state=str(order.state),
        pinned_versions=pinned,
        constraint_hash=constraint_hash(snapshot, scope.order_id),
        reservations=tuple(sorted(reservations)),
        tasks=tasks,
        resources=resources,
    )


def fingerprint(snapshot: GraphSnapshot, scope: TrackScope) -> Fingerprint:
    payload = fingerprint_input(snapshot, scope)
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return Fingerprint(hash=digest, input=payload)


def diff(before: FingerprintInput, after: FingerprintInput) -> tuple[FieldDiff, ...]:
    """Which fingerprint fields moved. Shown when a track goes STALE."""
    diffs: list[FieldDiff] = []
    for field_info in dataclasses.fields(before):
        old = getattr(before, field_info.name)
        new = getattr(after, field_info.name)
        if old != new:
            diffs.append(
                FieldDiff(
                    field=field_info.name,
                    before=canonical_json(old),
                    after=canonical_json(new),
                )
            )
    return tuple(diffs)


def _decimal(value: Decimal | None) -> str:
    return "" if value is None else format(value.normalize(), "f")


def _instant(value: datetime | None) -> str:
    return "" if value is None else value.isoformat()
