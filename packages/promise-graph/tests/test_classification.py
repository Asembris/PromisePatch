"""One test per rule id, the rejection-precedence ladder, and the analysis driver."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest

from promise_graph.classification import analyze, classify
from promise_graph.examples import hollow_oak as ho
from promise_graph.model import (
    REJECTION_PRECEDENCE,
    Classification,
    ReasonDetail,
    RejectionReason,
    RuleId,
)
from promise_graph.options import OptionSet, RejectedCandidate
from promise_graph.propagation import propagate
from tests.fixtures import adversarial as adv
from tests.fixtures import settle, settle_and_analyze

# --------------------------------------------------------------------------- one per rule id


def test_rule_unreach(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_E
    ]
    assert result.classification is Classification.UNAFFECTED
    assert result.rule_id is RuleId.R_UNREACH
    assert result.reason_detail is ReasonDetail.NOT_REACHABLE


def test_rule_covered(anchor: datetime) -> None:
    snapshot = adv.with_ample_raspberries(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_A
    ]
    assert result.classification is Classification.UNAFFECTED
    assert result.rule_id is RuleId.R_COVERED
    assert result.reason_detail is ReasonDetail.SHORTFALL_COVERED


def test_rule_preapproved(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_A
    ]
    assert result.classification is Classification.AUTO_RECOVERABLE
    assert result.rule_id is RuleId.R_PREAPPROVED


def test_rule_invisible_noask(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    result = settle_and_analyze(snapshot, ho.deck_oven_down(anchor), anchor).classifications[
        ho.PROMISE_A
    ]
    assert result.classification is Classification.AUTO_RECOVERABLE
    assert result.rule_id is RuleId.R_INVISIBLE_NOASK


def test_rule_visible_ask(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_B
    ]
    assert result.classification is Classification.APPROVAL_REQUIRED
    assert result.rule_id is RuleId.R_VISIBLE_ASK


def test_rule_not_preapproved(anchor: datetime) -> None:
    snapshot = adv.with_visible_change_and_no_ask(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_B
    ]
    assert result.classification is Classification.APPROVAL_REQUIRED
    assert result.rule_id is RuleId.R_NOT_PREAPPROVED


def test_rule_nosub_from_a_constraint(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_C
    ]
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_NOSUB
    assert result.reason_detail is ReasonDetail.NOSUB_CONSTRAINT


def test_rule_nosub_from_a_missing_variant(anchor: datetime) -> None:
    """The same rule id, a different cause, distinguished by the reason detail."""
    result = settle_and_analyze(
        ho.hollow_oak(anchor), ho.raspberry_only(anchor), anchor
    ).classifications[ho.PROMISE_D]
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_NOSUB
    assert result.reason_detail is ReasonDetail.NO_PREAUTHORED_VARIANT


def test_rule_excluded(anchor: datetime) -> None:
    snapshot = adv.with_excluded_substitute(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_B
    ]
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_EXCLUDED


def test_rule_substock(anchor: datetime) -> None:
    snapshot = adv.with_allocation_contention(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_B
    ]
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_SUBSTOCK


def test_rule_noequip(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    result = settle_and_analyze(snapshot, ho.deck_oven_down(anchor), anchor).classifications[
        ho.PROMISE_B
    ]
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_NOEQUIP


def test_rule_unknown_from_a_missing_constraint_snapshot(anchor: datetime) -> None:
    snapshot = adv.without_constraints(ho.with_lena_mutation(ho.hollow_oak(anchor)), ho.ORDER_B)
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_B
    ]
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_UNKNOWN
    assert result.reason_detail is ReasonDetail.NO_CONSTRAINT_SNAPSHOT


def test_rule_unknown_from_a_missing_quantity(anchor: datetime) -> None:
    snapshot = adv.with_unknown_raspberry_quantity(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_A
    ]
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_UNKNOWN
    assert result.reason_detail is ReasonDetail.UNKNOWN_QUANTITY


def test_rule_conflict(anchor: datetime) -> None:
    snapshot = adv.with_conflicting_constraints(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    result = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor).classifications[
        ho.PROMISE_A
    ]
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_CONFLICT
    assert len(result.cited_constraint_ids) == 2


def test_every_rule_id_is_covered_by_this_module() -> None:
    """A guard: adding a rule id without a dedicated test here fails immediately."""
    source = Path(__file__).read_text(encoding="utf-8")
    for rule in RuleId:
        marker = f"def test_rule_{rule.name.lower().removeprefix('r_')}"
        assert marker in source, f"no dedicated test for {rule.name}"


# --------------------------------------------------------------------------- ladder


@pytest.mark.parametrize(
    ("earlier", "later"),
    list(pairwise(REJECTION_PRECEDENCE)),
)
def test_rejection_ladder_is_ordered(
    earlier: RejectionReason, later: RejectionReason, anchor: datetime
) -> None:
    """Whenever two block reasons hold at once, the earlier one is the cited rule."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    impact = propagate(settled, exception, anchor)
    option_set = OptionSet(
        promise_id=ho.PROMISE_A,
        rejected=(
            RejectedCandidate(
                candidate_ref="later",
                order_line_id=ho.LINE_A,
                reason=later,
                detail=ReasonDetail.NONE,
            ),
            RejectedCandidate(
                candidate_ref="earlier",
                order_line_id=ho.LINE_A,
                reason=earlier,
                detail=ReasonDetail.NONE,
            ),
        ),
    )
    result = classify(settled, impact, ho.PROMISE_A, option_set)
    assert result.classification is Classification.BLOCKED
    expected_rule = classify(
        settled,
        impact,
        ho.PROMISE_A,
        OptionSet(
            promise_id=ho.PROMISE_A,
            rejected=(
                RejectedCandidate(
                    candidate_ref="only",
                    order_line_id=ho.LINE_A,
                    reason=earlier,
                    detail=ReasonDetail.NONE,
                ),
            ),
        ),
    ).rule_id
    assert result.rule_id is expected_rule


def test_blocked_without_any_rejection_still_cites_a_rule(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    impact = propagate(settled, exception, anchor)
    result = classify(settled, impact, ho.PROMISE_A, OptionSet(promise_id=ho.PROMISE_A))
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_NOSUB


# --------------------------------------------------------------------------- driver


def test_analyze_classifies_every_promise(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    analysis = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor)
    assert set(analysis.classifications) == set(snapshot.promises)
    assert set(analysis.option_sets) == set(snapshot.promises)
    assert analysis.classification_of(ho.PROMISE_A) is Classification.AUTO_RECOVERABLE


def test_analyze_commits_claims_in_allocation_order(anchor: datetime) -> None:
    """A's strawberry share is subtracted before B is validated."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    analysis = settle_and_analyze(snapshot, ho.raspberry_only(anchor), anchor)
    option_b = analysis.option_sets[ho.PROMISE_B].valid[0]
    assert option_b.required_quantity == Decimal("2.2")
    assert analysis.classification_of(ho.PROMISE_B) is Classification.APPROVAL_REQUIRED


def test_analyze_is_deterministic(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    first = analyze(settled, exception, anchor)
    second = analyze(settled, exception, anchor)
    assert first.classifications == second.classifications
    assert first.option_sets == second.option_sets
