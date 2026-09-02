"""P6 — fingerprint sensitivity: exactly the in-scope state, and nothing else."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from promise_graph.availability import apply_exception_facts
from promise_graph.classification import analyze
from promise_graph.fingerprint import TrackScope, diff, fingerprint, scope_for
from promise_graph.model import InventoryLedgerEntry, LedgerSourceKind, OrderState
from promise_graph.snapshot import GraphSnapshot
from tests.strategies import World, worlds

pytestmark = pytest.mark.property


def tracked(world: World, pick: int) -> tuple[GraphSnapshot, TrackScope]:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    analysis = analyze(settled, world.exception, world.now)
    promise_ids = sorted(settled.promises)
    promise_id = promise_ids[pick % len(promise_ids)]
    scope = scope_for(settled, analysis.impact, analysis.option_sets[promise_id], promise_id)
    return settled, scope


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_the_fingerprint_is_reproducible(world: World, pick: int) -> None:
    settled, scope = tracked(world, pick)
    assert fingerprint(settled, scope).hash == fingerprint(settled, scope).hash


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_an_unrelated_order_version_is_irrelevant(world: World, pick: int) -> None:
    settled, scope = tracked(world, pick)
    before = fingerprint(settled, scope)
    orders = dict(settled.orders)
    changed = False
    for order_id, order in sorted(orders.items()):
        if order_id != scope.order_id:
            orders[order_id] = order.model_copy(update={"external_version": 999})
            changed = True
    if not changed:
        return
    after = fingerprint(settled.replace(orders=orders), scope)
    assert after.hash == before.hash
    assert diff(before.input, after.input) == ()


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_an_out_of_scope_resource_ledger_is_irrelevant(world: World, pick: int) -> None:
    settled, scope = tracked(world, pick)
    outside = [
        resource_id
        for resource_id in sorted(settled.resources)
        if resource_id not in scope.resource_ids
    ]
    if not outside:
        return
    before = fingerprint(settled, scope)
    entry = InventoryLedgerEntry(
        seq=settled.next_ledger_seq(),
        resource_id=outside[0],
        delta=Decimal("3.0"),
        source_kind=LedgerSourceKind.CORRECTION,
        source_id=f"noise:{outside[0]}",
        recorded_at=world.now,
    )
    after = fingerprint(settled.append_ledger([entry]), scope)
    assert after.hash == before.hash


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_a_customer_rename_is_irrelevant(world: World, pick: int) -> None:
    settled, scope = tracked(world, pick)
    before = fingerprint(settled, scope)
    customers = {
        customer_id: customer.model_copy(update={"name": customer.name + " (renamed)"})
        for customer_id, customer in settled.customers.items()
    }
    after = fingerprint(settled.replace(customers=customers), scope)
    assert after.hash == before.hash


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_the_as_of_stamp_is_irrelevant(world: World, pick: int) -> None:
    settled, scope = tracked(world, pick)
    before = fingerprint(settled, scope)
    after = fingerprint(settled.replace(as_of=settled.as_of + 1234), scope)
    assert after.hash == before.hash


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_the_tracked_order_version_is_relevant(world: World, pick: int) -> None:
    settled, scope = tracked(world, pick)
    before = fingerprint(settled, scope)
    orders = dict(settled.orders)
    order_id = scope.order_id
    orders[order_id] = orders[order_id].model_copy(update={"external_version": 999})
    after = fingerprint(settled.replace(orders=orders), scope)
    assert after.hash != before.hash
    assert [change.field for change in diff(before.input, after.input)] == [
        "order_external_version"
    ]


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_the_tracked_order_state_is_relevant(world: World, pick: int) -> None:
    settled, scope = tracked(world, pick)
    before = fingerprint(settled, scope)
    orders = dict(settled.orders)
    order_id = scope.order_id
    orders[order_id] = orders[order_id].model_copy(update={"state": OrderState.CANCELLED})
    after = fingerprint(settled.replace(orders=orders), scope)
    assert after.hash != before.hash


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_a_tracked_task_reschedule_is_relevant(world: World, pick: int) -> None:
    settled, scope = tracked(world, pick)
    task_ids = scope.task_ids
    if not task_ids:
        return
    before = fingerprint(settled, scope)
    tasks = dict(settled.tasks)
    task = tasks[task_ids[0]]
    assert task.scheduled_start is not None
    tasks[task_ids[0]] = task.model_copy(
        update={"scheduled_start": task.scheduled_start.replace(microsecond=1)}
    )
    after = fingerprint(settled.replace(tasks=tasks), scope)
    assert after.hash != before.hash


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_an_in_scope_resource_ledger_is_relevant(world: World, pick: int) -> None:
    settled, scope = tracked(world, pick)
    resource_ids = scope.resource_ids
    if not resource_ids:
        return
    before = fingerprint(settled, scope)
    entry = InventoryLedgerEntry(
        seq=settled.next_ledger_seq(),
        resource_id=resource_ids[0],
        delta=Decimal("3.0"),
        source_kind=LedgerSourceKind.CORRECTION,
        source_id=f"topup:{resource_ids[0]}",
        recorded_at=world.now,
    )
    after = fingerprint(settled.append_ledger([entry]), scope)
    assert after.hash != before.hash
