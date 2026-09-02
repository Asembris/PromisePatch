"""Traversal from all three entry node types, path evidence, and quantification."""

from __future__ import annotations

from datetime import datetime, timedelta

from promise_graph.model import EdgeKind, ExceptionCategory, RecipeLineRole, TaskState
from promise_graph.propagation import propagate
from tests.fixtures import hollow_oak as ho
from tests.fixtures import settle


def test_supply_exception_reaches_exactly_the_raspberry_orders(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    assert impact.reached_promise_ids == {ho.PROMISE_A, ho.PROMISE_B, ho.PROMISE_C}
    assert impact.unreachable_promise_ids == {ho.PROMISE_D, ho.PROMISE_E, ho.PROMISE_F}
    assert impact.affected_promise_ids == {ho.PROMISE_A, ho.PROMISE_B, ho.PROMISE_C}
    assert impact.covered_promise_ids == frozenset()
    assert impact.affected_resource_ids == {ho.RASPBERRIES}
    assert impact.entry_node_refs == (ho.VP_TODAY_RASPBERRY,)
    assert not impact.equipment_origin


def test_paths_start_at_the_commitment_line_and_end_at_the_promise(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    path = impact.paths_by_promise[ho.PROMISE_B][0]
    assert [step.node_ref for step in path] == [
        ho.VP_TODAY_RASPBERRY,
        ho.RASPBERRIES,
        ho.RRC_V2,
        ho.LINE_B,
        ho.PROMISE_B,
    ]
    assert [step.edge_kind for step in path] == [
        None,
        EdgeKind.COMMITMENT_LINE_TO_RESOURCE,
        EdgeKind.RESOURCE_TO_RECIPE_VERSION,
        EdgeKind.RECIPE_VERSION_TO_ORDER_LINE,
        EdgeKind.ORDER_LINE_TO_PROMISE,
    ]


def test_the_role_is_carried_along_the_path(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    roles = {promise_id: paths[0][2].role for promise_id, paths in impact.paths_by_promise.items()}
    assert roles[ho.PROMISE_A] is RecipeLineRole.FILLING
    assert roles[ho.PROMISE_B] is RecipeLineRole.VISIBLE_DECORATION
    assert roles[ho.PROMISE_C] is RecipeLineRole.FILLING


def test_whole_delivery_enters_at_both_lines(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.whole_delivery(anchor)
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    assert impact.entry_node_refs == (ho.VP_TODAY_RASPBERRY, ho.VP_TODAY_STRAWBERRY)
    assert impact.affected_resource_ids == {ho.RASPBERRIES, ho.STRAWBERRIES}
    assert impact.reached_promise_ids == {ho.PROMISE_A, ho.PROMISE_B, ho.PROMISE_C}


def test_stock_exception_enters_at_the_resource(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.cream_unusable(anchor)
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    assert impact.category is ExceptionCategory.STOCK_UNUSABLE
    assert impact.entry_node_refs == (ho.HEAVY_CREAM,)
    assert impact.reached_promise_ids == {ho.PROMISE_E}
    path = impact.paths_by_promise[ho.PROMISE_E][0]
    assert path[0].node_ref == ho.HEAVY_CREAM
    assert path[0].edge_kind is None


def test_equipment_exception_enters_at_the_equipment(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.deck_oven_down(anchor)
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    assert impact.equipment_origin
    assert impact.reached_promise_ids == {ho.PROMISE_A, ho.PROMISE_B, ho.PROMISE_C}
    assert impact.equipment_blocked_line_ids == {ho.LINE_A, ho.LINE_B, ho.LINE_C}
    path = impact.paths_by_promise[ho.PROMISE_A][0]
    assert [step.edge_kind for step in path] == [
        None,
        EdgeKind.EQUIPMENT_TO_PRODUCTION_TASK,
        EdgeKind.PRODUCTION_TASK_TO_ORDER_LINE,
        EdgeKind.ORDER_LINE_TO_PROMISE,
    ]


def test_a_task_outside_the_outage_window_is_not_reached(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.deck_oven_down(anchor).model_copy(
        update={"outage_until": anchor + timedelta(minutes=330)}
    )
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    assert impact.reached_promise_ids == {ho.PROMISE_A}


def test_an_outage_without_an_end_reaches_every_later_task(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.deck_oven_down(anchor).model_copy(update={"outage_until": None})
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    assert impact.reached_promise_ids == {ho.PROMISE_A, ho.PROMISE_B, ho.PROMISE_C}


def test_a_done_task_is_not_reached_by_an_equipment_outage(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    tasks = dict(snapshot.tasks)
    tasks["task-ol-a"] = tasks["task-ol-a"].model_copy(update={"state": TaskState.DONE})
    exception = ho.deck_oven_down(anchor)
    impact = propagate(settle(snapshot.replace(tasks=tasks), exception, anchor), exception, anchor)
    assert ho.PROMISE_A not in impact.reached_promise_ids


def test_a_task_with_no_start_is_reached_but_unknown(anchor: datetime) -> None:
    from tests.fixtures.adversarial import with_unknown_task_start

    snapshot = with_unknown_task_start(ho.with_lena_mutation(ho.hollow_oak(anchor)), "task-ol-a")
    exception = ho.deck_oven_down(anchor)
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    assert ho.LINE_A in impact.unknown_line_ids
    assert ho.LINE_A not in impact.equipment_blocked_line_ids


def test_reachable_but_covered_is_distinct_from_no_path(anchor: datetime) -> None:
    from tests.fixtures.adversarial import with_ample_raspberries

    snapshot = with_ample_raspberries(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    exception = ho.raspberry_only(anchor)
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    assert impact.reached_promise_ids == {ho.PROMISE_A, ho.PROMISE_B, ho.PROMISE_C}
    assert impact.affected_promise_ids == frozenset()
    assert impact.covered_promise_ids == {ho.PROMISE_A, ho.PROMISE_B, ho.PROMISE_C}
    assert impact.paths_by_promise[ho.PROMISE_A]


def test_quantification_reports_need_and_shortfall(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    quantification = impact.quantifications_by_line[ho.LINE_A][0]
    assert quantification.resource_id == ho.RASPBERRIES
    assert quantification.reservation_id == f"{ho.LINE_A}:{ho.RASPBERRIES}"
    assert quantification.need is not None and quantification.shortfall is not None
    assert quantification.need > quantification.shortfall > 0
    assert not quantification.satisfied
    assert not quantification.unknown


def test_unknown_quantities_mark_the_line_unknown(anchor: datetime) -> None:
    from tests.fixtures.adversarial import with_unknown_raspberry_quantity

    snapshot = with_unknown_raspberry_quantity(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    exception = ho.raspberry_only(anchor)
    impact = propagate(settle(snapshot, exception, anchor), exception, anchor)
    assert impact.unknown_line_ids == {ho.LINE_A, ho.LINE_B, ho.LINE_C}
    assert impact.unsatisfied_line_ids == frozenset()


def test_lines_of_promise_lists_only_reached_lines(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    impact = propagate(settled, exception, anchor)
    assert impact.lines_of_promise(settled, ho.PROMISE_A) == (ho.LINE_A,)
    assert impact.lines_of_promise(settled, ho.PROMISE_D) == ()


def test_paths_do_not_depend_on_input_order(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    first = propagate(settled, exception, anchor)
    second = propagate(settled.replace(as_of=settled.as_of), exception, anchor)
    assert first.paths_by_promise == second.paths_by_promise
