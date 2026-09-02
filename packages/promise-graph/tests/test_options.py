"""Option enumeration: one test per rejection reason, plus the approval-requirement rules."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from promise_graph.model import (
    OptionKind,
    PhysicalException,
    ReasonDetail,
    RejectionReason,
    RuleId,
)
from promise_graph.options import (
    OptionSet,
    PlanClaims,
    approval_deadline,
    claims_for_option,
    enumerate_options,
    evaluate_constraints,
)
from promise_graph.propagation import propagate
from promise_graph.snapshot import GraphSnapshot
from tests.fixtures import adversarial as adv
from tests.fixtures import hollow_oak as ho
from tests.fixtures import settle


def options_for(
    snapshot: GraphSnapshot,
    exception: PhysicalException,
    promise_id: str,
    now: datetime,
) -> OptionSet:
    settled = settle(snapshot, exception, now)
    impact = propagate(settled, exception, now)
    return enumerate_options(settled, impact, promise_id, now)


# --------------------------------------------------------------------------- deadline


def test_approval_deadline_takes_the_earlier_bound(anchor: datetime) -> None:
    soon = anchor + timedelta(hours=3)
    assert approval_deadline(anchor, soon) == soon - timedelta(minutes=60)
    far = anchor + timedelta(days=5)
    assert approval_deadline(anchor, far) == anchor + timedelta(hours=24)


def test_approval_deadline_can_land_in_the_past(anchor: datetime) -> None:
    """A task starting within the hour leaves no window; the caller escalates instead."""
    assert approval_deadline(anchor, anchor + timedelta(minutes=30)) < anchor


# --------------------------------------------------------------------------- constraints


def test_constraint_evaluation_reads_every_kind(anchor: datetime) -> None:
    snapshot = adv.with_conflicting_constraints(ho.hollow_oak(anchor))
    evaluation = evaluate_constraints(snapshot, ho.ORDER_A)
    assert evaluation.has_snapshot
    assert evaluation.preapproval_for(ho.RASPBERRIES, ho.STRAWBERRIES) is not None
    assert evaluation.preapproval_for(ho.RASPBERRIES, ho.BLUEBERRIES) is None
    assert evaluation.exclusions == {ho.STRAWBERRIES: adv.CONSTRAINT_A_EXCLUDE_STRAWBERRIES}
    assert evaluation.conflicts == (
        (ho.CONSTRAINT_A_PREAPPROVED, adv.CONSTRAINT_A_EXCLUDE_STRAWBERRIES),
    )


def test_an_order_with_no_constraint_rows_is_unknown(anchor: datetime) -> None:
    evaluation = evaluate_constraints(ho.hollow_oak(anchor), ho.ORDER_E)
    assert not evaluation.has_snapshot


# --------------------------------------------------------------------------- valid options


def test_a_preapproved_substitution_needs_no_approval(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    option_set = options_for(snapshot, ho.raspberry_only(anchor), ho.PROMISE_A, anchor)
    option = option_set.valid[0]
    assert option.kind is OptionKind.SUBSTITUTE_RESOURCE
    assert option.from_version_id == ho.RAC_V3
    assert option.to_version_id == ho.RAC_V4
    assert option.substitute_resource_id == ho.STRAWBERRIES
    assert option.required_quantity == Decimal("2.4")
    assert option.requires_approval is False
    assert option.approval_rule is RuleId.R_PREAPPROVED
    assert option.cited_constraint_ids == (ho.CONSTRAINT_A_PREAPPROVED,)


def test_a_visible_change_under_ask_needs_approval(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    option = options_for(snapshot, ho.raspberry_only(anchor), ho.PROMISE_B, anchor).valid[0]
    assert option.visible_change
    assert option.requires_approval
    assert option.approval_rule is RuleId.R_VISIBLE_ASK
    assert option.cited_constraint_ids == (ho.CONSTRAINT_B_ASK,)


def test_a_visible_change_without_ask_is_still_not_preapproved(anchor: datetime) -> None:
    snapshot = adv.with_visible_change_and_no_ask(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    option = options_for(snapshot, ho.raspberry_only(anchor), ho.PROMISE_B, anchor).valid[0]
    assert option.requires_approval
    assert option.approval_rule is RuleId.R_NOT_PREAPPROVED
    assert option.approval_detail is ReasonDetail.NOT_PREAPPROVED


def test_an_invisible_change_without_preapproval_is_automatic(anchor: datetime) -> None:
    """A's filling swap is not visible, so dropping its pre-approval still leaves it AUTO."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    constraints = dict(snapshot.constraints)
    del constraints[ho.CONSTRAINT_A_PREAPPROVED]
    constraints[ho.CONSTRAINT_D_ASK + "-a"] = snapshot.constraints[ho.CONSTRAINT_D_ASK].model_copy(
        update={"id": ho.CONSTRAINT_D_ASK + "-a", "order_id": ho.ORDER_A}
    )
    option = options_for(
        snapshot.replace(constraints=constraints), ho.raspberry_only(anchor), ho.PROMISE_A, anchor
    ).valid[0]
    assert option.requires_approval is False
    assert option.approval_rule is RuleId.R_INVISIBLE_NOASK
    assert option.approval_detail is ReasonDetail.NOT_VISIBLE_NO_ASK


# --------------------------------------------------------------------------- rejections


def test_rejection_no_preauthored_variant(anchor: datetime) -> None:
    option_set = options_for(ho.hollow_oak(anchor), ho.raspberry_only(anchor), ho.PROMISE_D, anchor)
    assert option_set.valid == ()
    assert option_set.rejected[0].reason is RejectionReason.NO_PREAUTHORED_VARIANT


def test_rejection_no_substitution_constraint(anchor: datetime) -> None:
    option_set = options_for(ho.hollow_oak(anchor), ho.raspberry_only(anchor), ho.PROMISE_C, anchor)
    rejected = option_set.rejected[0]
    assert rejected.reason is RejectionReason.NOSUB_CONSTRAINT
    assert rejected.cited_constraint_ids == (ho.CONSTRAINT_C_NOSUB,)


def test_rejection_excluded_substitute(anchor: datetime) -> None:
    snapshot = adv.with_excluded_substitute(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    rejected = options_for(snapshot, ho.raspberry_only(anchor), ho.PROMISE_B, anchor).rejected[0]
    assert rejected.reason is RejectionReason.EXCLUDED
    assert rejected.cited_constraint_ids == (adv.CONSTRAINT_B_EXCLUDE_STRAWBERRIES,)


def test_rejection_conflicting_constraints(anchor: datetime) -> None:
    snapshot = adv.with_conflicting_constraints(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    rejected = options_for(snapshot, ho.raspberry_only(anchor), ho.PROMISE_A, anchor).rejected[0]
    assert rejected.reason is RejectionReason.CONFLICT
    assert set(rejected.cited_constraint_ids) == {
        ho.CONSTRAINT_A_PREAPPROVED,
        adv.CONSTRAINT_A_EXCLUDE_STRAWBERRIES,
    }


def test_rejection_unknown_constraint_snapshot(anchor: datetime) -> None:
    snapshot = adv.without_constraints(ho.with_lena_mutation(ho.hollow_oak(anchor)), ho.ORDER_B)
    rejected = options_for(snapshot, ho.raspberry_only(anchor), ho.PROMISE_B, anchor).rejected[0]
    assert rejected.reason is RejectionReason.UNKNOWN
    assert rejected.detail is ReasonDetail.NO_CONSTRAINT_SNAPSHOT


def test_rejection_insufficient_substitute_stock(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.whole_delivery(anchor)
    rejected = options_for(snapshot, exception, ho.PROMISE_A, anchor).rejected[0]
    assert rejected.reason is RejectionReason.SUBSTOCK
    assert rejected.detail is ReasonDetail.INSUFFICIENT_SUBSTITUTE_STOCK


def test_rejection_no_alternative_equipment(anchor: datetime) -> None:
    """B's window overlaps A's committed reassignment, and capacity is one."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.deck_oven_down(anchor)
    settled = settle(snapshot, exception, anchor)
    impact = propagate(settled, exception, anchor)
    option_a = enumerate_options(settled, impact, ho.PROMISE_A, anchor).valid[0]
    claims = claims_for_option(settled, option_a)
    option_set_b = enumerate_options(settled, impact, ho.PROMISE_B, anchor, claims)
    assert option_set_b.valid == ()
    assert option_set_b.rejected[0].reason is RejectionReason.NOEQUIP


def test_rejection_unknown_task_start(anchor: datetime) -> None:
    snapshot = adv.with_unknown_task_start(
        ho.with_lena_mutation(ho.hollow_oak(anchor)), "task-ol-b"
    )
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    impact = propagate(settled, exception, anchor)
    # The line is unknown rather than unsatisfied, so no candidate is even attempted.
    assert ho.LINE_B in impact.unknown_line_ids
    assert enumerate_options(settled, impact, ho.PROMISE_B, anchor).valid == ()


def test_a_rejected_candidate_commits_no_supply(anchor: datetime) -> None:
    """Whole delivery: A is rejected, and B still sees the full 2.0 kg fallback stock."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.whole_delivery(anchor)
    settled = settle(snapshot, exception, anchor)
    impact = propagate(settled, exception, anchor)
    option_set_a = enumerate_options(settled, impact, ho.PROMISE_A, anchor)
    assert option_set_a.valid == ()
    rejected_b = enumerate_options(settled, impact, ho.PROMISE_B, anchor, PlanClaims()).rejected[0]
    assert "2.000 available" in rejected_b.note


# --------------------------------------------------------------------------- claims


def test_a_validated_option_commits_its_substitute_share(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    option = options_for(snapshot, ho.raspberry_only(anchor), ho.PROMISE_A, anchor).valid[0]
    claims = claims_for_option(settle(snapshot, ho.raspberry_only(anchor), anchor), option)
    assert len(claims.resource_claims) == 1
    claim = claims.resource_claims[0]
    assert claim.resource_id == ho.STRAWBERRIES
    assert claim.quantity == Decimal("2.4")
    assert claim.is_candidate


def test_an_equipment_option_commits_its_window(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.deck_oven_down(anchor)
    settled = settle(snapshot, exception, anchor)
    impact = propagate(settled, exception, anchor)
    option = enumerate_options(settled, impact, ho.PROMISE_A, anchor).valid[0]
    claims = claims_for_option(settled, option)
    assert len(claims.equipment_claims) == 1
    assert claims.equipment_claims[0].equipment_id == ho.CONVECTION_OVEN


def test_plan_claims_extend_without_mutating(anchor: datetime) -> None:
    base = PlanClaims()
    extended = base.extend(resource_claims=(), equipment_claims=())
    assert base.resource_claims == () and extended.resource_claims == ()


def test_unaffected_promises_get_an_empty_option_set(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    option_set = options_for(snapshot, ho.raspberry_only(anchor), ho.PROMISE_E, anchor)
    assert option_set.valid == () and option_set.rejected == ()
