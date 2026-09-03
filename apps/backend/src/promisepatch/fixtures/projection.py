"""One structural projection from a :class:`~promise_graph.snapshot.GraphSnapshot` to rows.

This module knows the *shape* of the graph and nothing about any particular bakery. It never
names a resource, a quantity, an order or a policy: every value it emits is read off the
snapshot it was handed. That is the whole point. The Hollow Oak numbers are authored once, in
``promise_graph.examples.hollow_oak``, and a second copy of them here would be a second thing
to keep in step and a silent way for the demo to stop matching the engine's own tests.

Two columns have no counterpart in the engine, and both are supplied by the caller rather than
invented here:

* ``orders.updated_at`` is mirror bookkeeping. The engine has no opinion about when a mirrored
  order was last written, so the loader ignores it and the projection takes it as a parameter.
* ``workers`` are staff identity, not graph. They are projected separately, from seeds, because
  a password hash is not a fact about the promise graph.

The table order is insert order and is foreign-key safe: a row is never written before the row
it references.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from promise_graph.fingerprint import canonical_json
from promise_graph.snapshot import GraphSnapshot
from promisepatch.graph.channel import split_channel

Row = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TableRows:
    """The rows destined for one table, in deterministic order."""

    table: str
    rows: tuple[Row, ...]


@dataclass(frozen=True, slots=True)
class StaffSeed:
    """A member of staff the demo needs a login for.

    The password is not here: it is configuration, it is a secret, and it must not be able to
    reach a digest, a log line or a repr by riding along on a data record.
    """

    worker_id: str
    username: str
    display_name: str
    role: str


PROJECTED_TABLES: Final[tuple[str, ...]] = (
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
)
"""Every table a projected graph writes to, in foreign-key-safe insert order."""

STAFF_TABLE: Final = "workers"

VOLATILE_COLUMNS: Final[frozenset[tuple[str, str]]] = frozenset({(STAFF_TABLE, "password_hash")})
"""Columns excluded from the digest because they are correctly different every time.

An Argon2 hash carries a random salt, so two hashes of the same password never match. Hashing
them into the fixture digest would make every reset look like a different fixture and destroy
the only property the digest exists to state.
"""


def project(snapshot: GraphSnapshot, *, mirrored_at: datetime) -> tuple[TableRows, ...]:
    """Project a whole graph to rows, in insert order."""
    projected = (
        _resources(snapshot),
        _resource_aliases(snapshot),
        _suppliers(snapshot),
        _supplier_commitments(snapshot),
        _commitment_lines(snapshot),
        _recipes(snapshot),
        _recipe_versions(snapshot),
        _recipe_version_lines(snapshot),
        _recipe_version_equipment(snapshot),
        _substitution_policies(snapshot),
        _equipment_alternatives(snapshot),
        _customers(snapshot),
        _orders(snapshot, mirrored_at=mirrored_at),
        _order_lines(snapshot),
        _order_constraints(snapshot),
        _promises(snapshot),
        _production_tasks(snapshot),
        _reservations(snapshot),
        _inventory_ledger(snapshot),
        _equipment_outages(snapshot),
    )
    if tuple(table.table for table in projected) != PROJECTED_TABLES:
        raise RuntimeError("projected tables no longer match the declared insert order")
    return projected


def project_staff(
    seeds: Sequence[StaffSeed], *, password_hashes: Mapping[str, str], created_at: datetime
) -> TableRows:
    """Project staff seeds to ``workers`` rows, each with the hash of its configured password."""
    return TableRows(
        table=STAFF_TABLE,
        rows=tuple(
            {
                "id": seed.worker_id,
                "username": seed.username,
                "display_name": seed.display_name,
                "role": seed.role,
                "password_hash": password_hashes[seed.worker_id],
                "created_at": created_at,
            }
            for seed in sorted(seeds, key=lambda seed: seed.worker_id)
        ),
    )


def digest(*, fixture_name: str, anchor: datetime, tables: Sequence[TableRows]) -> str:
    """A stable fingerprint of the domain state a reset installs.

    Two resets at the same anchor produce the same digest; a reset at any other anchor produces
    a different one, because every fixture instant is an offset from it. What the digest states
    is exactly the claim idempotency needs: *this* fixture, at *this* anchor, is now loaded.
    The audit and event ledgers are outside it on purpose -- they are supposed to grow.
    """
    payload = {
        "fixture": fixture_name,
        "anchor": anchor,
        "tables": {
            table.table: [_digestible(table.table, row) for row in table.rows] for table in tables
        },
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _digestible(table: str, row: Row) -> dict[str, Any]:
    return {
        column: value
        for column, value in sorted(row.items())
        if (table, column) not in VOLATILE_COLUMNS
    }


# --------------------------------------------------------------------------- per table


def _resources(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="resources",
        rows=tuple(
            {
                "id": resource.id,
                "kind": str(resource.kind),
                "name": resource.name,
                "unit": resource.unit,
            }
            for resource in snapshot.resources.values()
        ),
    )


def _resource_aliases(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="resource_aliases",
        rows=tuple(
            {"resource_id": resource.id, "alias": alias, "ordinal": ordinal}
            for resource in snapshot.resources.values()
            for ordinal, alias in enumerate(resource.aliases)
        ),
    )


def _suppliers(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="suppliers",
        rows=tuple(
            {"id": supplier.id, "name": supplier.name} for supplier in snapshot.suppliers.values()
        ),
    )


def _supplier_commitments(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="supplier_commitments",
        rows=tuple(
            {
                "id": commitment.id,
                "supplier_id": commitment.supplier_id,
                "due_at": commitment.due_at,
            }
            for commitment in snapshot.commitments.values()
        ),
    )


def _commitment_lines(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="commitment_lines",
        rows=tuple(
            {
                "id": line.id,
                "commitment_id": line.commitment_id,
                "resource_id": line.resource_id,
                "quantity": line.quantity,
                "received_state": str(line.received_state),
                "received_qty": line.received_qty,
                "settled_at": line.settled_at,
                "attested_by": line.attested_by,
            }
            for line in snapshot.commitment_lines.values()
        ),
    )


def _recipes(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="recipes",
        rows=tuple({"id": recipe.id, "name": recipe.name} for recipe in snapshot.recipes.values()),
    )


def _recipe_versions(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="recipe_versions",
        rows=tuple(
            {
                "id": version.id,
                "recipe_id": version.recipe_id,
                "version_no": version.version_no,
                "authored_by": version.authored_by,
                "authored_at": version.authored_at,
            }
            for version in snapshot.versions.values()
        ),
    )


def _recipe_version_lines(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="recipe_version_lines",
        rows=tuple(
            {
                "version_id": version.id,
                "resource_id": line.resource_id,
                "role": str(line.role),
                "qty_per_unit": line.qty_per_unit,
            }
            for version in snapshot.versions.values()
            for line in version.lines
        ),
    )


def _recipe_version_equipment(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="recipe_version_equipment",
        rows=tuple(
            {"version_id": version.id, "equipment_id": equipment_id}
            for version in snapshot.versions.values()
            for equipment_id in version.equipment_ids
        ),
    )


def _substitution_policies(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="substitution_policies",
        rows=tuple(
            {
                "id": policy.id,
                "affected_resource_id": policy.affected_resource_id,
                "role": str(policy.role),
                "source_version_id": policy.source_version_id,
                "candidate_version_id": policy.candidate_version_id,
                "substitute_resource_id": policy.substitute_resource_id,
                "visible_change": policy.visible_change,
            }
            for policy in snapshot.policies.values()
        ),
    )


def _equipment_alternatives(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="equipment_alternatives",
        rows=tuple(
            {
                "id": alternative.id,
                "equipment_id": alternative.equipment_id,
                "alternative_equipment_id": alternative.alternative_equipment_id,
            }
            for alternative in snapshot.equipment_alternatives.values()
        ),
    )


def _customers(snapshot: GraphSnapshot) -> TableRows:
    rows = []
    for customer in snapshot.customers.values():
        kind, address = split_channel(customer.approval_channel)
        rows.append(
            {
                "id": customer.id,
                "name": customer.name,
                "approval_channel_kind": kind,
                "approval_channel_address": address,
            }
        )
    return TableRows(table="customers", rows=tuple(rows))


def _orders(snapshot: GraphSnapshot, *, mirrored_at: datetime) -> TableRows:
    return TableRows(
        table="orders",
        rows=tuple(
            {
                "id": order.id,
                "external_id": order.external_id,
                "external_version": order.external_version,
                "customer_id": order.customer_id,
                "due_at": order.due_at,
                "state": str(order.state),
                "mirror_source_event_id": None,
                "updated_at": mirrored_at,
            }
            for order in snapshot.orders.values()
        ),
    )


def _order_lines(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="order_lines",
        rows=tuple(
            {
                "id": line.id,
                "order_id": line.order_id,
                "recipe_version_id": line.recipe_version_id,
                "quantity": line.quantity,
                "customization_note": line.customization_note,
            }
            for line in snapshot.order_lines.values()
        ),
    )


def _order_constraints(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="order_constraints",
        rows=tuple(
            {
                "id": constraint.id,
                "order_id": constraint.order_id,
                "kind": str(constraint.kind),
                "resource_id": constraint.resource_id,
                "substitute_resource_id": constraint.substitute_resource_id,
                "recorded_by": constraint.recorded_by,
                "recorded_at": constraint.recorded_at,
            }
            for constraint in snapshot.constraints.values()
        ),
    )


def _promises(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="promises",
        rows=tuple(
            {
                "id": promise.id,
                "order_id": promise.order_id,
                "due_at": promise.due_at,
                # A read model maintained by case transitions. An order book with no open
                # exception has nothing to say here, and saying nothing is the correct state.
                "current_classification": None,
                "current_track_state": None,
                "current_case_id": None,
                "current_track_id": None,
            }
            for promise in snapshot.promises.values()
        ),
    )


def _production_tasks(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="production_tasks",
        rows=tuple(
            {
                "id": task.id,
                "order_line_id": task.order_line_id,
                "state": str(task.state),
                "scheduled_start": task.scheduled_start,
                "scheduled_end": task.scheduled_end,
                "equipment_id": task.equipment_id,
                "held_by_case_id": task.held_by_case_id,
            }
            for task in snapshot.tasks.values()
        ),
    )


def _reservations(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="reservations",
        rows=tuple(
            {
                "id": reservation.id,
                "order_line_id": reservation.order_line_id,
                "resource_id": reservation.resource_id,
                "quantity": reservation.quantity,
                "source_recipe_version_id": reservation.source_recipe_version_id,
            }
            for reservation in snapshot.reservations.values()
        ),
    )


def _inventory_ledger(snapshot: GraphSnapshot) -> TableRows:
    """Ledger postings, in sequence order and without their sequence numbers.

    ``seq`` is deliberately omitted. The rows are written in the order the engine holds them
    into a table whose identity was just restarted, so the database assigns exactly the same
    numbers -- which makes the sequence a property of the ledger rather than a value copied
    into it, and leaves the generator correct for the next posting.
    """
    return TableRows(
        table="inventory_ledger",
        rows=tuple(
            {
                "resource_id": entry.resource_id,
                "delta": entry.delta,
                "source_kind": str(entry.source_kind),
                "source_id": entry.source_id,
                "recorded_at": entry.recorded_at,
            }
            for entry in snapshot.ledger
        ),
    )


def _equipment_outages(snapshot: GraphSnapshot) -> TableRows:
    return TableRows(
        table="equipment_outages",
        rows=tuple(
            {
                "id": outage.id,
                "equipment_id": outage.equipment_id,
                "starts_at": outage.starts_at,
                "ends_at": outage.ends_at,
            }
            for outage in snapshot.outages
        ),
    )
