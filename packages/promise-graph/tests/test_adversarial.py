"""Engineering fixtures: contention, conflicting constraints, and unknown state."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import Classification, ReasonDetail, RuleId
from tests.fixtures import adversarial as adv
from tests.fixtures import classifications, settle_and_analyze

BLOCKED = Classification.BLOCKED
AUTO = Classification.AUTO_RECOVERABLE


# --------------------------------------------------------------------------- contention


def test_contention_gives_the_earlier_task_the_substitute(anchor: datetime) -> None:
    snapshot = adv.with_allocation_contention(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    analysis = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor)
    assert analysis.classification_of(ho.PROMISE_A) is AUTO
    assert analysis.classification_of(ho.PROMISE_B) is BLOCKED
    assert analysis.classifications[ho.PROMISE_B].rule_id is RuleId.R_SUBSTOCK


def test_contention_follows_the_schedule_not_the_identity(anchor: datetime) -> None:
    """Swap A's and B's windows and the winner swaps with them."""
    snapshot = adv.with_swapped_task_starts(
        adv.with_allocation_contention(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    )
    analysis = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor)
    assert analysis.classification_of(ho.PROMISE_B) is not BLOCKED
    assert analysis.classification_of(ho.PROMISE_A) is BLOCKED
    assert analysis.classifications[ho.PROMISE_A].rule_id is RuleId.R_SUBSTOCK


def test_contention_leaves_unrelated_promises_untouched(anchor: datetime) -> None:
    snapshot = adv.with_allocation_contention(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = classifications(settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor))
    assert result[ho.PROMISE_D] is Classification.UNAFFECTED
    assert result[ho.PROMISE_E] is Classification.UNAFFECTED
    assert result[ho.PROMISE_F] is Classification.UNAFFECTED


# --------------------------------------------------------------------------- conflicts


def test_conflicting_constraints_block_and_cite_both_rules(anchor: datetime) -> None:
    snapshot = adv.with_conflicting_constraints(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_A
    ]
    assert result.classification is BLOCKED
    assert result.rule_id is RuleId.R_CONFLICT
    assert set(result.cited_constraint_ids) == {
        ho.CONSTRAINT_A_PREAPPROVED,
        adv.CONSTRAINT_A_EXCLUDE_STRAWBERRIES,
    }


def test_a_conflict_does_not_leak_into_other_orders(anchor: datetime) -> None:
    snapshot = adv.with_conflicting_constraints(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    analysis = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor)
    assert analysis.classification_of(ho.PROMISE_B) is Classification.APPROVAL_REQUIRED


def test_a_conflict_frees_the_substitute_for_the_next_track(anchor: datetime) -> None:
    """A blocks and commits nothing, so B's strawberry check sees the full 8.0 kg."""
    snapshot = adv.with_conflicting_constraints(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    analysis = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor)
    option_b = analysis.option_sets[ho.PROMISE_B].valid[0]
    assert option_b.required_quantity == Decimal("2.2")


# --------------------------------------------------------------------------- unknowns


def test_a_missing_constraint_snapshot_fails_closed(anchor: datetime) -> None:
    snapshot = adv.without_constraints(ho.with_lena_mutation(ho.hollow_oak(anchor)), ho.ORDER_B)
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_B
    ]
    assert result.classification is BLOCKED
    assert result.reason_detail is ReasonDetail.NO_CONSTRAINT_SNAPSHOT


def test_an_unknown_quantity_fails_closed_for_every_reached_promise(anchor: datetime) -> None:
    snapshot = adv.with_unknown_raspberry_quantity(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = classifications(settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor))
    assert result[ho.PROMISE_A] is BLOCKED
    assert result[ho.PROMISE_B] is BLOCKED
    assert result[ho.PROMISE_C] is BLOCKED
    assert result[ho.PROMISE_D] is Classification.UNAFFECTED


def test_an_unknown_task_start_fails_closed_for_that_promise_only(anchor: datetime) -> None:
    snapshot = adv.with_unknown_task_start(
        ho.with_lena_mutation(ho.hollow_oak(anchor)), "task-ol-b"
    )
    result = classifications(settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor))
    assert result[ho.PROMISE_B] is BLOCKED
    assert result[ho.PROMISE_A] is BLOCKED  # allocation order is undefined, so all fail closed
    assert result[ho.PROMISE_E] is Classification.UNAFFECTED


def test_an_excluded_substitute_blocks_without_a_conflict(anchor: datetime) -> None:
    snapshot = adv.with_excluded_substitute(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_B
    ]
    assert result.rule_id is RuleId.R_EXCLUDED
    assert result.cited_constraint_ids == (adv.CONSTRAINT_B_EXCLUDE_STRAWBERRIES,)


def test_ample_supply_makes_a_reached_promise_unaffected(anchor: datetime) -> None:
    snapshot = adv.with_ample_raspberries(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = classifications(settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor))
    assert all(value is Classification.UNAFFECTED for value in result.values())
