"""Snapshot construction, indexes, structural validation and pure transformations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import (
    CustomerPromise,
    InventoryReservation,
    Order,
    OrderLine,
    ProductionTask,
    RecipeLineRole,
    Resource,
    ResourceKind,
    TaskState,
)
from promise_graph.snapshot import GraphSnapshot, SnapshotIntegrityError, reservations_for_line

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)


def test_build_indexes_the_graph(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    assert snapshot.order_lines[ho.LINE_A].order_id == ho.ORDER_A
    assert snapshot.promise_by_order[ho.ORDER_A] == ho.PROMISE_A
    assert snapshot.task_by_order_line[ho.LINE_A] == "task-ol-a"
    assert ho.LINE_A in snapshot.order_lines_by_version[ho.RAC_V3]
    assert (ho.RAC_V3, RecipeLineRole.FILLING) in snapshot.versions_by_resource[ho.RASPBERRIES]
    assert snapshot.commitment_lines[ho.VP_TODAY_RASPBERRY].resource_id == ho.RASPBERRIES
    assert ho.VP_TODAY_RASPBERRY in snapshot.commitment_lines_by_resource[ho.RASPBERRIES]
    assert snapshot.alternatives_by_equipment[ho.DECK_OVEN] == (ho.CONVECTION_OVEN,)
    assert (
        snapshot.policy_by_key[(ho.RASPBERRIES, RecipeLineRole.FILLING, ho.RAC_V3)]
        == ho.POLICY_ALMOND_FILLING
    )


def test_lookups(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    assert snapshot.order_of_line(ho.LINE_B).id == ho.ORDER_B
    assert snapshot.promise_of_line(ho.LINE_B) == ho.PROMISE_B
    task = snapshot.task_of_line(ho.LINE_B)
    assert task is not None and task.equipment_id == ho.DECK_OVEN
    assert [c.id for c in snapshot.constraints_for_order(ho.ORDER_C)] == [ho.CONSTRAINT_C_NOSUB]
    assert snapshot.next_ledger_seq() == max(e.seq for e in snapshot.ledger) + 1


def test_snapshot_is_input_order_independent(anchor: datetime) -> None:
    """Two snapshots built from the same records in different orders compare equal."""
    forward = ho.hollow_oak(anchor)
    shuffled = GraphSnapshot.build(
        resources=list(reversed(list(forward.resources.values()))),
        suppliers=list(reversed(list(forward.suppliers.values()))),
        commitments=list(reversed(list(forward.commitments.values()))),
        recipes=list(reversed(list(forward.recipes.values()))),
        versions=list(reversed(list(forward.versions.values()))),
        customers=list(reversed(list(forward.customers.values()))),
        orders=list(reversed(list(forward.orders.values()))),
        constraints=list(reversed(list(forward.constraints.values()))),
        promises=list(reversed(list(forward.promises.values()))),
        tasks=list(reversed(list(forward.tasks.values()))),
        reservations=list(reversed(list(forward.reservations.values()))),
        ledger=list(reversed(forward.ledger)),
        outages=list(reversed(forward.outages)),
        policies=list(reversed(list(forward.policies.values()))),
        equipment_alternatives=list(reversed(list(forward.equipment_alternatives.values()))),
        as_of=forward.as_of,
    )
    assert shuffled == forward
    assert shuffled.versions_by_resource == forward.versions_by_resource
    assert shuffled.reservations_by_resource == forward.reservations_by_resource


def test_duplicate_ids_are_rejected() -> None:
    resource = Resource(id="res-1", kind=ResourceKind.INGREDIENT, name="x")
    with pytest.raises(SnapshotIntegrityError, match="duplicate resource id"):
        GraphSnapshot.build(resources=[resource, resource])


def test_dangling_recipe_version_pin_is_rejected(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    order = snapshot.orders[ho.ORDER_A]
    broken = order.model_copy(
        update={
            "lines": (order.lines[0].model_copy(update={"recipe_version_id": "rv-does-not-exist"}),)
        }
    )
    orders = dict(snapshot.orders)
    orders[ho.ORDER_A] = broken
    with pytest.raises(SnapshotIntegrityError, match="pins unknown recipe version"):
        snapshot.replace(orders=orders)


def test_dangling_reservation_is_rejected(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    reservations = dict(snapshot.reservations)
    reservations["bad"] = InventoryReservation(
        id="bad",
        order_line_id="ol-nope",
        resource_id=ho.RASPBERRIES,
        quantity=Decimal("1"),
        source_recipe_version_id=ho.RAC_V3,
    )
    with pytest.raises(SnapshotIntegrityError, match="names unknown order line"):
        snapshot.replace(reservations=reservations)


def test_dangling_task_equipment_is_rejected(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    tasks = dict(snapshot.tasks)
    tasks["task-ol-a"] = tasks["task-ol-a"].model_copy(update={"equipment_id": ho.RASPBERRIES})
    with pytest.raises(SnapshotIntegrityError, match="names unknown equipment"):
        snapshot.replace(tasks=tasks)


def test_dangling_promise_order_is_rejected(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    promises = dict(snapshot.promises)
    promises["pr-x"] = CustomerPromise(id="pr-x", order_id="ord-nope", due_at=anchor)
    with pytest.raises(SnapshotIntegrityError, match="names unknown order"):
        snapshot.replace(promises=promises)


def test_dangling_task_order_line_is_rejected(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    tasks = dict(snapshot.tasks)
    tasks["task-x"] = ProductionTask(
        id="task-x",
        order_line_id="ol-nope",
        state=TaskState.SCHEDULED,
        scheduled_start=anchor,
    )
    with pytest.raises(SnapshotIntegrityError, match="names unknown order line"):
        snapshot.replace(tasks=tasks)


def test_unknown_values_are_representable_not_errors(anchor: datetime) -> None:
    """A ``None`` quantity is data the engine must fail closed on, not a structural error."""
    snapshot = ho.hollow_oak(anchor)
    commitment = snapshot.commitments[ho.VP_TODAY]
    lines = tuple(line.model_copy(update={"quantity": None}) for line in commitment.lines)
    commitments = dict(snapshot.commitments)
    commitments[ho.VP_TODAY] = commitment.model_copy(update={"lines": lines})
    assert (
        snapshot.replace(commitments=commitments).commitment_lines[ho.VP_TODAY_RASPBERRY].quantity
        is None
    )


def test_replace_leaves_the_original_untouched(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    before = snapshot.orders[ho.ORDER_D].lines[0].recipe_version_id
    repinned = snapshot.repin_order_line(ho.LINE_D, ho.LCL_V1)
    assert snapshot.orders[ho.ORDER_D].lines[0].recipe_version_id == before
    assert repinned.orders[ho.ORDER_D].lines[0].recipe_version_id == ho.LCL_V1


def test_repin_recomputes_reservations(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    assert any(
        snapshot.reservations[r].resource_id == ho.RASPBERRIES
        for r in snapshot.reservations_by_order_line[ho.LINE_D]
    )
    repinned = snapshot.repin_order_line(ho.LINE_D, ho.LCL_V1)
    resources = {
        repinned.reservations[r].resource_id for r in repinned.reservations_by_order_line[ho.LINE_D]
    }
    assert ho.RASPBERRIES not in resources
    assert ho.LEMON_CURD in resources


def test_repin_rejects_an_unknown_version(anchor: datetime) -> None:
    with pytest.raises(SnapshotIntegrityError, match="unknown recipe version"):
        ho.hollow_oak(anchor).repin_order_line(ho.LINE_D, "rv-invented")


def test_reservations_scale_with_order_quantity(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    line = snapshot.order_lines[ho.LINE_F]
    version = snapshot.versions[ho.DANISH_V1]
    derived = reservations_for_line(line, version, snapshot.resources)
    blueberries = next(r for r in derived if r.resource_id == ho.BLUEBERRIES)
    assert blueberries.quantity == Decimal("0.05") * 24


def test_reservations_skip_equipment(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    derived = reservations_for_line(
        snapshot.order_lines[ho.LINE_A], snapshot.versions[ho.RAC_V3], snapshot.resources
    )
    assert all(snapshot.resources[r.resource_id].kind is ResourceKind.INGREDIENT for r in derived)


def test_append_ledger_and_add_outage_are_no_ops_when_empty(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    assert snapshot.append_ledger(()) is snapshot
    assert snapshot.settle_commitment_lines(()) is snapshot
    with_outage = snapshot.add_outage(ho.outage(anchor))
    assert with_outage.outages_by_equipment[ho.DECK_OVEN][0].equipment_id == ho.DECK_OVEN


def test_settlement_only_touches_the_named_commitment(anchor: datetime) -> None:
    from promise_graph.model import ReceivedState
    from promise_graph.snapshot import LineSettlement

    snapshot = ho.hollow_oak(anchor)
    settled = snapshot.settle_commitment_lines(
        [
            LineSettlement(
                commitment_line_id=ho.VP_TODAY_RASPBERRY,
                to_state=ReceivedState.NOT_RECEIVED,
                received_qty=None,
                settled_at=anchor,
                attested_by="maya",
            )
        ]
    )
    assert settled.commitment_lines[ho.VP_TODAY_RASPBERRY].received_state is (
        ReceivedState.NOT_RECEIVED
    )
    assert settled.commitments[ho.VP_TOMORROW] is snapshot.commitments[ho.VP_TOMORROW]


def test_empty_snapshot_is_valid() -> None:
    empty = GraphSnapshot.build()
    assert empty.order_lines == {}
    assert empty.next_ledger_seq() == 1


def test_orders_must_name_a_known_customer(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    orders = dict(snapshot.orders)
    orders["ord-x"] = Order(
        id="ord-x",
        external_id="EXT-X",
        external_version=1,
        customer_id="cus-nope",
        due_at=anchor,
        state="ACCEPTED",
        lines=(OrderLine(id="ol-x", order_id="ord-x", recipe_version_id=ho.LCL_V1, quantity=1),),
    )
    with pytest.raises(SnapshotIntegrityError, match="names unknown customer"):
        snapshot.replace(orders=orders)
