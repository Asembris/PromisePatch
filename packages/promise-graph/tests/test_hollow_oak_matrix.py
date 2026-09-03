"""The frozen fixture matrix.

Every row asserts the classification **and** the cited rule id, because a right answer for
the wrong reason would still break the demo's evidence screen.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import Classification, ReasonDetail, RuleId
from promise_graph.snapshot import GraphSnapshot
from tests.fixtures import classifications, settle_and_analyze

ANCHORS = [
    datetime(2026, 3, 4, 7, 0, tzinfo=UTC),
    datetime(2026, 7, 19, 22, 45, tzinfo=UTC),
    datetime(2027, 1, 1, 0, 0, tzinfo=UTC),
]

A, B, C, D, E, F = (
    ho.PROMISE_A,
    ho.PROMISE_B,
    ho.PROMISE_C,
    ho.PROMISE_D,
    ho.PROMISE_E,
    ho.PROMISE_F,
)

UNAFFECTED = Classification.UNAFFECTED
AUTO = Classification.AUTO_RECOVERABLE
APPROVAL = Classification.APPROVAL_REQUIRED
BLOCKED = Classification.BLOCKED


@pytest.mark.parametrize("anchor", ANCHORS)
def test_canonical_result(anchor: datetime) -> None:
    """A AUTO / B APPROVAL / C BLOCKED / D-E-F UNAFFECTED, at any recording hour."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    analysis = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor)
    assert classifications(analysis) == {
        A: AUTO,
        B: APPROVAL,
        C: BLOCKED,
        D: UNAFFECTED,
        E: UNAFFECTED,
        F: UNAFFECTED,
    }


def test_canonical_cited_rules(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    results = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications

    assert results[A].rule_id is RuleId.R_PREAPPROVED
    assert results[A].cited_constraint_ids == (ho.CONSTRAINT_A_PREAPPROVED,)

    assert results[B].rule_id is RuleId.R_VISIBLE_ASK
    assert results[B].cited_constraint_ids == (ho.CONSTRAINT_B_ASK,)

    assert results[C].rule_id is RuleId.R_NOSUB
    assert results[C].reason_detail is ReasonDetail.NOSUB_CONSTRAINT
    assert results[C].cited_constraint_ids == (ho.CONSTRAINT_C_NOSUB,)

    for promise_id in (D, E, F):
        assert results[promise_id].rule_id is RuleId.R_UNREACH


def test_lena_before_mutation_is_blocked(anchor: datetime) -> None:
    """Raspberry Lemon Layer v2 has no pre-authored variant, so D cannot be recovered."""
    analysis = settle_and_analyze(ho.hollow_oak(anchor), ho.raspberry_only(anchor), anchor)
    result = analysis.classifications[D]
    assert result.classification is BLOCKED
    assert result.rule_id is RuleId.R_NOSUB
    assert result.reason_detail is ReasonDetail.NO_PREAUTHORED_VARIANT


def test_lena_mutation_changes_only_lena(anchor: datetime) -> None:
    before = settle_and_analyze(ho.hollow_oak(anchor), ho.raspberry_only(anchor), anchor)
    after = settle_and_analyze(
        ho.with_lena_mutation(ho.hollow_oak(anchor)), ho.raspberry_only(anchor), anchor
    )
    before_map = classifications(before)
    after_map = classifications(after)
    assert {
        promise_id
        for promise_id in before_map
        if before_map[promise_id] is not after_map[promise_id]
    } == {D}


@pytest.mark.parametrize("anchor", ANCHORS)
def test_whole_delivery_blocks_a_and_b(anchor: datetime) -> None:
    """Without the strawberries, both substitutions run out of stock."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    analysis = settle_and_analyze(snapshot, ho.whole_delivery(anchor), anchor)
    assert classifications(analysis) == {
        A: BLOCKED,
        B: BLOCKED,
        C: BLOCKED,
        D: UNAFFECTED,
        E: UNAFFECTED,
        F: UNAFFECTED,
    }
    assert analysis.classifications[A].rule_id is RuleId.R_SUBSTOCK
    assert analysis.classifications[B].rule_id is RuleId.R_SUBSTOCK


def test_deck_oven_uses_the_equipment_path(anchor: datetime) -> None:
    """A reassigns, B loses the race for the one convection oven, C reassigns later."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    analysis = settle_and_analyze(snapshot, ho.deck_oven_down(anchor), anchor)
    assert classifications(analysis) == {
        A: AUTO,
        B: BLOCKED,
        C: AUTO,
        D: UNAFFECTED,
        E: UNAFFECTED,
        F: UNAFFECTED,
    }
    assert analysis.classifications[B].rule_id is RuleId.R_NOEQUIP
    assert analysis.classifications[A].reason_detail is ReasonDetail.EQUIPMENT_REASSIGNED


def test_equipment_reassignment_is_not_gated_by_customer_constraints(
    anchor: datetime,
) -> None:
    """C carries NO_SUBSTITUTION and is still AUTO: the product does not change."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    analysis = settle_and_analyze(snapshot, ho.deck_oven_down(anchor), anchor)
    assert analysis.classifications[C].classification is AUTO
    option = analysis.option_sets[C].valid[0]
    assert option.to_equipment_id == ho.CONVECTION_OVEN
    assert option.requires_approval is False


def test_deck_oven_result_differs_from_the_ingredient_result(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    ingredient = classifications(settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor))
    equipment = classifications(settle_and_analyze(snapshot, ho.deck_oven_down(anchor), anchor))
    assert ingredient != equipment


def test_stock_unusable_enters_at_the_third_node_type(anchor: datetime) -> None:
    """No cream variant is authored, and E has no constraint snapshot: fail closed."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    analysis = settle_and_analyze(snapshot, ho.cream_unusable(anchor), anchor)
    assert classifications(analysis) == {
        A: UNAFFECTED,
        B: UNAFFECTED,
        C: UNAFFECTED,
        D: UNAFFECTED,
        E: BLOCKED,
        F: UNAFFECTED,
    }
    assert analysis.classifications[E].rule_id is RuleId.R_UNKNOWN
    assert analysis.classifications[E].reason_detail is ReasonDetail.NO_CONSTRAINT_SNAPSHOT


def test_charlotte_variant_alone_does_not_unblock_c(anchor: datetime) -> None:
    """With the variant authored but NO_SUBSTITUTION kept, the constraint still decides."""
    snapshot = ho.with_charlotte_variant(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[C]
    assert result.classification is BLOCKED
    assert result.rule_id is RuleId.R_NOSUB
    assert result.reason_detail is ReasonDetail.NOSUB_CONSTRAINT
    assert result.cited_constraint_ids == (ho.CONSTRAINT_C_NOSUB,)


def test_c_with_ask_becomes_approval_required(anchor: datetime) -> None:
    """Proof C: swapping the constraint for ASK moves C from BLOCKED to APPROVAL_REQUIRED."""
    snapshot = ho.with_c_ask(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    analysis = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor)
    result = analysis.classifications[C]
    assert result.classification is APPROVAL
    assert result.rule_id is RuleId.R_VISIBLE_ASK
    assert result.cited_constraint_ids == (ho.CONSTRAINT_C_ASK,)
    assert classifications(analysis)[A] is AUTO
    assert classifications(analysis)[B] is APPROVAL


def test_unaffected_promises_carry_no_options_and_no_paths(anchor: datetime) -> None:
    """Selectivity is evidence: nothing is computed, proposed or cited for D, E and F."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    analysis = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor)
    for promise_id in (D, E, F):
        assert analysis.option_sets[promise_id].valid == ()
        assert analysis.option_sets[promise_id].rejected == ()
        assert analysis.impact.paths_by_promise.get(promise_id) is None
        assert promise_id in analysis.impact.unreachable_promise_ids


def test_fixture_quantity_constraints_hold(anchor: datetime) -> None:
    """The three frozen statements that pin the berry quantities (see the fixture docstring)."""
    snapshot = ho.hollow_oak(anchor)
    need_a = _need(snapshot, ho.RAC_V4, ho.STRAWBERRIES)
    need_b = _need(snapshot, ho.RRC_V3, ho.STRAWBERRIES)
    fallback_stock = Decimal("2.0")
    todays_delivery = Decimal("6.0")

    assert need_a > fallback_stock, "whole-delivery scope must block A on substitute stock"
    assert need_b > fallback_stock, "whole-delivery scope must block B on substitute stock"
    assert need_a + need_b <= fallback_stock + todays_delivery, "canonical run must fit both"

    on_hand_raspberries = Decimal("0.3")
    for version_id in (ho.RAC_V3, ho.RRC_V2, ho.CHARLOTTE_V1, ho.RLL_V2):
        assert _need(snapshot, version_id, ho.RASPBERRIES) > on_hand_raspberries


def test_allocation_priority_follows_task_start(anchor: datetime) -> None:
    """A's window opens before B's, so A is validated first and B sees the remainder."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    task_a = snapshot.task_of_line(ho.LINE_A)
    task_b = snapshot.task_of_line(ho.LINE_B)
    assert task_a is not None and task_b is not None
    assert task_a.scheduled_start is not None and task_b.scheduled_start is not None
    assert task_a.scheduled_start < task_b.scheduled_start


def test_fixture_uses_only_preauthored_versions(anchor: datetime) -> None:
    """Every policy candidate already exists in the fixture; nothing is synthesized."""
    snapshot = ho.hollow_oak(anchor)
    for policy in snapshot.policies.values():
        assert policy.candidate_version_id in snapshot.versions
        assert policy.source_version_id in snapshot.versions
        assert snapshot.versions[policy.candidate_version_id].authored_at < anchor


def test_next_day_delivery_cannot_serve_a_today_task(anchor: datetime) -> None:
    """D's task at +21h precedes the +23h raspberry commitment, so it is not covered."""
    snapshot = ho.hollow_oak(anchor)
    task = snapshot.task_of_line(ho.LINE_D)
    assert task is not None and task.scheduled_start is not None
    assert task.scheduled_start < snapshot.commitments[ho.VP_TOMORROW].due_at
    assert task.scheduled_start == anchor + timedelta(minutes=1260)


def _need(snapshot: GraphSnapshot, version_id: str, resource_id: str) -> Decimal:
    for line in snapshot.versions[version_id].lines:
        if line.resource_id == resource_id:
            assert line.qty_per_unit is not None
            return Decimal(line.qty_per_unit)
    raise AssertionError(f"{version_id} does not use {resource_id}")


def test_fixture_child_collections_are_in_canonical_order(anchor: datetime) -> None:
    """Order within a commitment or a version is not a fact any keyed store can hold.

    The fixture is authored in the order such a store must return, so a persisted copy of this
    graph compares equal to it directly instead of only after re-sorting.
    """
    base = ho.hollow_oak(anchor)
    for snapshot in (base, ho.with_charlotte_variant(base)):
        for commitment in snapshot.commitments.values():
            assert commitment.lines == tuple(sorted(commitment.lines, key=lambda line: line.id))
        for version in snapshot.versions.values():
            assert version.lines == tuple(
                sorted(version.lines, key=lambda line: (line.resource_id, line.role))
            )
            assert version.equipment_ids == tuple(sorted(version.equipment_ids))
