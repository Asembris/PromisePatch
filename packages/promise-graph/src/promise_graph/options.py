"""Recovery-option enumeration and validation.

An option is only ever a *selection* of something a human already authored: a pre-authored
variant ``RecipeVersion`` named by the substitution policy, or an alternative piece of
equipment. Nothing here creates, derives or synthesizes a version.

Two scopes of gate apply, and keeping them apart matters:

* **Order-scoped constraints** (``NO_SUBSTITUTION``, ``EXCLUDE_RESOURCE``,
  ``PREAPPROVED_ALTERNATIVE``, ``ASK_BEFORE_VISIBLE_CHANGE``) govern
  ``SUBSTITUTE_RESOURCE`` only. A ``REASSIGN_EQUIPMENT`` option does not change the product,
  so no customer constraint gates it and it never requires customer approval.
* **Availability** gates both, through the same deterministic allocator, counting claims
  already committed by higher-priority tracks. A *rejected* candidate commits nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from promise_graph.availability import Claim, allocate
from promise_graph.model import (
    ConstraintId,
    ConstraintKind,
    CustomerConstraint,
    OptionKind,
    OrderId,
    OrderLine,
    OrderLineId,
    PromiseId,
    ReasonDetail,
    RecipeLineRole,
    RecipeVersionId,
    RejectionReason,
    ResourceId,
    RuleId,
    TaskState,
)
from promise_graph.propagation import Impact
from promise_graph.snapshot import GraphSnapshot

APPROVAL_WINDOW = timedelta(hours=24)
TASK_START_MARGIN = timedelta(minutes=60)

_LIVE_TASK_STATES = frozenset({TaskState.SCHEDULED, TaskState.STARTED, TaskState.HELD})


def approval_deadline(now: datetime, task_start: datetime) -> datetime:
    """``min(now + 24h, task start - 60min)``. May be in the past: that is the caller's signal."""
    return min(now + APPROVAL_WINDOW, task_start - TASK_START_MARGIN)


# --------------------------------------------------------------------------- constraints


@dataclass(frozen=True)
class ConstraintEvaluation:
    """Closed-world reading of one order's constraint snapshot."""

    order_id: OrderId
    has_snapshot: bool
    no_substitution_ids: tuple[ConstraintId, ...]
    ask_ids: tuple[ConstraintId, ...]
    preapprovals: tuple[CustomerConstraint, ...]
    exclusions: Mapping[ResourceId, ConstraintId]
    conflicts: tuple[tuple[ConstraintId, ConstraintId], ...]

    def preapproval_for(
        self, affected: ResourceId, substitute: ResourceId
    ) -> CustomerConstraint | None:
        for constraint in self.preapprovals:
            if (
                constraint.resource_id == affected
                and constraint.substitute_resource_id == substitute
            ):
                return constraint
        return None


def evaluate_constraints(snapshot: GraphSnapshot, order_id: OrderId) -> ConstraintEvaluation:
    """Read an order's constraints. No rows at all is *unknown*, and unknown fails closed."""
    constraints = snapshot.constraints_for_order(order_id)
    no_substitution = tuple(c.id for c in constraints if c.kind is ConstraintKind.NO_SUBSTITUTION)
    ask = tuple(c.id for c in constraints if c.kind is ConstraintKind.ASK_BEFORE_VISIBLE_CHANGE)
    preapprovals = tuple(c for c in constraints if c.kind is ConstraintKind.PREAPPROVED_ALTERNATIVE)
    exclusions = {
        str(c.resource_id): c.id for c in constraints if c.kind is ConstraintKind.EXCLUDE_RESOURCE
    }
    conflicts = tuple(
        (preapproval.id, exclusions[str(preapproval.substitute_resource_id)])
        for preapproval in preapprovals
        if str(preapproval.substitute_resource_id) in exclusions
    )
    return ConstraintEvaluation(
        order_id=order_id,
        has_snapshot=bool(constraints),
        no_substitution_ids=no_substitution,
        ask_ids=ask,
        preapprovals=preapprovals,
        exclusions=exclusions,
        conflicts=conflicts,
    )


# --------------------------------------------------------------------------- options


@dataclass(frozen=True)
class RecoveryOption:
    id: str
    kind: OptionKind
    promise_id: PromiseId
    order_line_id: OrderLineId
    from_version_id: RecipeVersionId | None = None
    to_version_id: RecipeVersionId | None = None
    from_equipment_id: ResourceId | None = None
    to_equipment_id: ResourceId | None = None
    affected_resource_id: ResourceId | None = None
    substitute_resource_id: ResourceId | None = None
    required_quantity: Decimal | None = None
    visible_change: bool = False
    requires_approval: bool = False
    approval_rule: RuleId = RuleId.R_INVISIBLE_NOASK
    approval_detail: ReasonDetail = ReasonDetail.NONE
    cited_constraint_ids: tuple[ConstraintId, ...] = ()
    policy_id: str | None = None
    task_start: datetime | None = None


@dataclass(frozen=True)
class RejectedCandidate:
    candidate_ref: str
    order_line_id: OrderLineId | None
    reason: RejectionReason
    detail: ReasonDetail
    cited_constraint_ids: tuple[ConstraintId, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class OptionSet:
    promise_id: PromiseId
    valid: tuple[RecoveryOption, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()


@dataclass(frozen=True)
class EquipmentClaim:
    claim_id: str
    equipment_id: ResourceId
    start: datetime
    end: datetime


@dataclass(frozen=True)
class PlanClaims:
    """Claims already committed by higher-priority tracks in the same planning pass."""

    resource_claims: tuple[Claim, ...] = field(default_factory=tuple)
    equipment_claims: tuple[EquipmentClaim, ...] = field(default_factory=tuple)

    def extend(
        self,
        resource_claims: Sequence[Claim] = (),
        equipment_claims: Sequence[EquipmentClaim] = (),
    ) -> PlanClaims:
        return PlanClaims(
            resource_claims=(*self.resource_claims, *resource_claims),
            equipment_claims=(*self.equipment_claims, *equipment_claims),
        )


def enumerate_options(
    snapshot: GraphSnapshot,
    impact: Impact,
    promise_id: PromiseId,
    now: datetime,
    claims: PlanClaims | None = None,
) -> OptionSet:
    """Validated and rejected recovery candidates for one affected promise."""
    committed = claims or PlanClaims()
    if promise_id not in impact.affected_promise_ids:
        return OptionSet(promise_id=promise_id)
    if impact.equipment_origin:
        return _equipment_options(snapshot, impact, promise_id, committed)
    return _substitution_options(snapshot, impact, promise_id, now, committed)


# --------------------------------------------------------------------------- substitution


def _substitution_options(
    snapshot: GraphSnapshot,
    impact: Impact,
    promise_id: PromiseId,
    now: datetime,
    committed: PlanClaims,
) -> OptionSet:
    order_id = snapshot.promises[promise_id].order_id
    evaluation = evaluate_constraints(snapshot, order_id)

    gate = _order_level_gate(evaluation)
    if gate is not None:
        return OptionSet(promise_id=promise_id, rejected=(gate,))

    valid: list[RecoveryOption] = []
    rejected: list[RejectedCandidate] = []
    for order_line_id in sorted(impact.lines_of_promise(snapshot, promise_id)):
        if order_line_id not in impact.unsatisfied_line_ids:
            continue
        for quantification in impact.quantifications_by_line.get(order_line_id, ()):
            if quantification.satisfied or quantification.unknown:
                continue
            for role in quantification.roles:
                outcome = _candidate_for(
                    snapshot,
                    promise_id,
                    order_line_id,
                    quantification.resource_id,
                    role,
                    evaluation,
                    now,
                    committed,
                )
                if isinstance(outcome, RecoveryOption):
                    valid.append(outcome)
                else:
                    rejected.append(outcome)
    return OptionSet(promise_id=promise_id, valid=tuple(valid), rejected=tuple(rejected))


def _order_level_gate(evaluation: ConstraintEvaluation) -> RejectedCandidate | None:
    """Gates that block every substitution on the order, in rejection-precedence order."""
    if evaluation.conflicts:
        cited = tuple(sorted({cid for pair in evaluation.conflicts for cid in pair}))
        return RejectedCandidate(
            candidate_ref=f"order:{evaluation.order_id}",
            order_line_id=None,
            reason=RejectionReason.CONFLICT,
            detail=ReasonDetail.CONFLICTING_CONSTRAINTS,
            cited_constraint_ids=cited,
            note="a pre-approval names an excluded resource",
        )
    if not evaluation.has_snapshot:
        return RejectedCandidate(
            candidate_ref=f"order:{evaluation.order_id}",
            order_line_id=None,
            reason=RejectionReason.UNKNOWN,
            detail=ReasonDetail.NO_CONSTRAINT_SNAPSHOT,
            note="no constraint snapshot recorded; treated as NO_SUBSTITUTION",
        )
    if evaluation.no_substitution_ids:
        return RejectedCandidate(
            candidate_ref=f"order:{evaluation.order_id}",
            order_line_id=None,
            reason=RejectionReason.NOSUB_CONSTRAINT,
            detail=ReasonDetail.NOSUB_CONSTRAINT,
            cited_constraint_ids=evaluation.no_substitution_ids,
        )
    return None


def _candidate_for(
    snapshot: GraphSnapshot,
    promise_id: PromiseId,
    order_line_id: OrderLineId,
    affected_resource_id: ResourceId,
    role: RecipeLineRole,
    evaluation: ConstraintEvaluation,
    now: datetime,
    committed: PlanClaims,
) -> RecoveryOption | RejectedCandidate:
    order_line = snapshot.order_lines[order_line_id]
    source_version_id = order_line.recipe_version_id
    candidate_ref = f"{order_line_id}:{affected_resource_id}:{role}"

    policy_id = snapshot.policy_by_key.get((affected_resource_id, role, source_version_id))
    if policy_id is None:
        return RejectedCandidate(
            candidate_ref=candidate_ref,
            order_line_id=order_line_id,
            reason=RejectionReason.NO_PREAUTHORED_VARIANT,
            detail=ReasonDetail.NO_PREAUTHORED_VARIANT,
            note="no pre-authored variant version is named by the substitution policy",
        )
    policy = snapshot.policies[policy_id]
    substitute_id = policy.substitute_resource_id

    if substitute_id in evaluation.exclusions:
        return RejectedCandidate(
            candidate_ref=candidate_ref,
            order_line_id=order_line_id,
            reason=RejectionReason.EXCLUDED,
            detail=ReasonDetail.EXCLUDED_SUBSTITUTE,
            cited_constraint_ids=(evaluation.exclusions[substitute_id],),
        )

    required = _required_quantity(snapshot, policy.candidate_version_id, substitute_id, order_line)
    task = snapshot.task_of_line(order_line_id)
    task_start = None if task is None else task.scheduled_start
    if required is None or task_start is None:
        return RejectedCandidate(
            candidate_ref=candidate_ref,
            order_line_id=order_line_id,
            reason=RejectionReason.UNKNOWN,
            detail=ReasonDetail.UNKNOWN_QUANTITY,
            note="substitute requirement or task start is unknown",
        )

    option_id = f"opt:{candidate_ref}"
    claim = Claim(
        id=f"candidate:{option_id}",
        resource_id=substitute_id,
        quantity=required,
        start=task_start,
        order_external_id=snapshot.order_of_line(order_line_id).external_id,
        order_line_id=order_line_id,
        is_candidate=True,
    )
    result = allocate(
        snapshot, substitute_id, now, extra_claims=(*committed.resource_claims, claim)
    )
    allocation = result.for_claim(claim.id)
    if result.unknown or allocation is None:
        return RejectedCandidate(
            candidate_ref=candidate_ref,
            order_line_id=order_line_id,
            reason=RejectionReason.UNKNOWN,
            detail=ReasonDetail.UNKNOWN_QUANTITY,
            note="substitute availability is unknown",
        )
    if not allocation.satisfied:
        return RejectedCandidate(
            candidate_ref=candidate_ref,
            order_line_id=order_line_id,
            reason=RejectionReason.SUBSTOCK,
            detail=ReasonDetail.INSUFFICIENT_SUBSTITUTE_STOCK,
            note=f"needs {required}, {allocation.available_before_start} available before start",
        )

    preapproval = evaluation.preapproval_for(affected_resource_id, substitute_id)
    cited: tuple[ConstraintId, ...]
    if preapproval is not None:
        requires_approval = False
        rule, detail = RuleId.R_PREAPPROVED, ReasonDetail.PREAPPROVAL_COVERS
        cited = (preapproval.id,)
    elif not policy.visible_change:
        requires_approval = False
        rule, detail = RuleId.R_INVISIBLE_NOASK, ReasonDetail.NOT_VISIBLE_NO_ASK
        cited = ()
    elif evaluation.ask_ids:
        requires_approval = True
        rule, detail = RuleId.R_VISIBLE_ASK, ReasonDetail.VISIBLE_CHANGE_ASK
        cited = evaluation.ask_ids
    else:
        requires_approval = True
        rule, detail = RuleId.R_NOT_PREAPPROVED, ReasonDetail.NOT_PREAPPROVED
        cited = ()

    return RecoveryOption(
        id=option_id,
        kind=OptionKind.SUBSTITUTE_RESOURCE,
        promise_id=promise_id,
        order_line_id=order_line_id,
        from_version_id=source_version_id,
        to_version_id=policy.candidate_version_id,
        affected_resource_id=affected_resource_id,
        substitute_resource_id=substitute_id,
        required_quantity=required,
        visible_change=policy.visible_change,
        requires_approval=requires_approval,
        approval_rule=rule,
        approval_detail=detail,
        cited_constraint_ids=cited,
        policy_id=policy_id,
        task_start=task_start,
    )


def _required_quantity(
    snapshot: GraphSnapshot,
    candidate_version_id: RecipeVersionId,
    substitute_id: ResourceId,
    order_line: OrderLine,
) -> Decimal | None:
    """How much of the substitute the pre-authored variant needs for this line."""
    for version_line in snapshot.versions[candidate_version_id].lines:
        if version_line.resource_id == substitute_id:
            if version_line.qty_per_unit is None:
                return None
            return version_line.qty_per_unit * order_line.quantity
    return None


def claims_for_option(snapshot: GraphSnapshot, option: RecoveryOption) -> PlanClaims:
    """The supply a validated option commits, for the benefit of lower-priority tracks."""
    if option.kind is OptionKind.SUBSTITUTE_RESOURCE:
        if (
            option.substitute_resource_id is None
            or option.required_quantity is None
            or option.task_start is None
        ):
            return PlanClaims()
        return PlanClaims(
            resource_claims=(
                Claim(
                    id=f"committed:{option.id}",
                    resource_id=option.substitute_resource_id,
                    quantity=option.required_quantity,
                    start=option.task_start,
                    order_external_id=snapshot.order_of_line(option.order_line_id).external_id,
                    order_line_id=option.order_line_id,
                    is_candidate=True,
                ),
            )
        )
    task = snapshot.task_of_line(option.order_line_id)
    if task is None or task.scheduled_start is None or option.to_equipment_id is None:
        return PlanClaims()
    end = task.scheduled_end if task.scheduled_end is not None else task.scheduled_start
    return PlanClaims(
        equipment_claims=(
            EquipmentClaim(
                claim_id=f"committed:{option.id}",
                equipment_id=option.to_equipment_id,
                start=task.scheduled_start,
                end=end,
            ),
        )
    )


# --------------------------------------------------------------------------- equipment


def _equipment_options(
    snapshot: GraphSnapshot,
    impact: Impact,
    promise_id: PromiseId,
    committed: PlanClaims,
) -> OptionSet:
    valid: list[RecoveryOption] = []
    rejected: list[RejectedCandidate] = []
    for order_line_id in sorted(impact.lines_of_promise(snapshot, promise_id)):
        if order_line_id not in impact.equipment_blocked_line_ids:
            continue
        task = snapshot.task_of_line(order_line_id)
        if task is None or task.scheduled_start is None or task.equipment_id is None:
            continue
        end = task.scheduled_end if task.scheduled_end is not None else task.scheduled_start
        chosen: str | None = None
        for alternative_id in snapshot.alternatives_by_equipment.get(task.equipment_id, ()):
            if _equipment_free(snapshot, alternative_id, task.scheduled_start, end, committed):
                chosen = alternative_id
                break
        if chosen is None:
            rejected.append(
                RejectedCandidate(
                    candidate_ref=f"{order_line_id}:equipment",
                    order_line_id=order_line_id,
                    reason=RejectionReason.NOEQUIP,
                    detail=ReasonDetail.NO_ALTERNATIVE_EQUIPMENT,
                    note="no alternative equipment is free before the scheduled start",
                )
            )
            continue
        valid.append(
            RecoveryOption(
                id=f"opt:{order_line_id}:equipment",
                kind=OptionKind.REASSIGN_EQUIPMENT,
                promise_id=promise_id,
                order_line_id=order_line_id,
                from_equipment_id=task.equipment_id,
                to_equipment_id=chosen,
                requires_approval=False,
                approval_rule=RuleId.R_INVISIBLE_NOASK,
                approval_detail=ReasonDetail.EQUIPMENT_REASSIGNED,
                task_start=task.scheduled_start,
            )
        )
    return OptionSet(promise_id=promise_id, valid=tuple(valid), rejected=tuple(rejected))


def _equipment_free(
    snapshot: GraphSnapshot,
    equipment_id: ResourceId,
    start: datetime,
    end: datetime,
    committed: PlanClaims,
) -> bool:
    """Capacity is one task per piece of equipment in the MVP; displacement is not attempted."""
    for outage in snapshot.outages_by_equipment.get(equipment_id, ()):
        outage_end = outage.ends_at
        overlaps_outage = outage.starts_at < end and (outage_end is None or start < outage_end)
        if overlaps_outage:
            return False
    for task_id in snapshot.tasks_by_equipment.get(equipment_id, ()):
        other = snapshot.tasks[task_id]
        if other.state not in _LIVE_TASK_STATES or other.scheduled_start is None:
            continue
        other_end = (
            other.scheduled_end if other.scheduled_end is not None else other.scheduled_start
        )
        if start < other_end and other.scheduled_start < end:
            return False
    for claim in committed.equipment_claims:
        if claim.equipment_id != equipment_id:
            continue
        if start < claim.end and claim.start < end:
            return False
    return True
