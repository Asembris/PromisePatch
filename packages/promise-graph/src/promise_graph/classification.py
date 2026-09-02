"""Impact classification with cited rules, and the per-case analysis driver.

The decision order is fixed and is the source of every fixture expectation:

1. not reachable                      -> ``UNAFFECTED``      ``R-UNREACH``
2. reachable but the shortfall is covered -> ``UNAFFECTED``  ``R-COVERED``
3. an unknown value on the path       -> ``BLOCKED``         ``R-UNKNOWN``
4. a validated option needing no approval -> ``AUTO_RECOVERABLE``
5. validated options that all need approval -> ``APPROVAL_REQUIRED``
6. no validated option                -> ``BLOCKED``, rule chosen by the rejection ladder

Nothing here reads an entity id, a customer name or an utterance. Classifications depend on
stored state and rules only, which is what Proof H asserts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from promise_graph.model import (
    REJECTION_PRECEDENCE,
    Classification,
    ConstraintId,
    PhysicalException,
    PromiseId,
    ReasonDetail,
    RejectionReason,
    RuleId,
)
from promise_graph.options import (
    OptionSet,
    PlanClaims,
    RecoveryOption,
    claims_for_option,
    enumerate_options,
)
from promise_graph.propagation import Impact, propagate
from promise_graph.snapshot import GraphSnapshot

_REASON_TO_RULE: Mapping[RejectionReason, RuleId] = {
    RejectionReason.CONFLICT: RuleId.R_CONFLICT,
    RejectionReason.UNKNOWN: RuleId.R_UNKNOWN,
    RejectionReason.NOSUB_CONSTRAINT: RuleId.R_NOSUB,
    RejectionReason.NO_PREAUTHORED_VARIANT: RuleId.R_NOSUB,
    RejectionReason.EXCLUDED: RuleId.R_EXCLUDED,
    RejectionReason.SUBSTOCK: RuleId.R_SUBSTOCK,
    RejectionReason.NOEQUIP: RuleId.R_NOEQUIP,
}


@dataclass(frozen=True)
class ClassificationResult:
    promise_id: PromiseId
    classification: Classification
    rule_id: RuleId
    reason_detail: ReasonDetail
    cited_constraint_ids: tuple[ConstraintId, ...] = ()
    chosen_option_id: str | None = None
    note: str = ""


@dataclass(frozen=True)
class AnalysisResult:
    """Everything one propagation pass produced, for every open promise."""

    impact: Impact
    option_sets: Mapping[PromiseId, OptionSet]
    classifications: Mapping[PromiseId, ClassificationResult]

    def classification_of(self, promise_id: PromiseId) -> Classification:
        return self.classifications[promise_id].classification


def classify(
    snapshot: GraphSnapshot,
    impact: Impact,
    promise_id: PromiseId,
    option_set: OptionSet,
) -> ClassificationResult:
    """Classify one promise against its impact and validated options."""
    if promise_id in impact.unreachable_promise_ids:
        return ClassificationResult(
            promise_id=promise_id,
            classification=Classification.UNAFFECTED,
            rule_id=RuleId.R_UNREACH,
            reason_detail=ReasonDetail.NOT_REACHABLE,
            note="no path from the exception to this promise",
        )
    if promise_id in impact.covered_promise_ids:
        return ClassificationResult(
            promise_id=promise_id,
            classification=Classification.UNAFFECTED,
            rule_id=RuleId.R_COVERED,
            reason_detail=ReasonDetail.SHORTFALL_COVERED,
            note="reachable, but every reservation is still satisfiable",
        )

    order_id = snapshot.promises[promise_id].order_id
    line_ids = {line.id for line in snapshot.orders[order_id].lines}
    if line_ids & impact.unknown_line_ids:
        return ClassificationResult(
            promise_id=promise_id,
            classification=Classification.BLOCKED,
            rule_id=RuleId.R_UNKNOWN,
            reason_detail=ReasonDetail.UNKNOWN_QUANTITY,
            note="unknown quantity or schedule on the dependency path; failing closed",
        )

    automatic = _preferred(option_set.valid, requires_approval=False)
    if automatic is not None:
        return ClassificationResult(
            promise_id=promise_id,
            classification=Classification.AUTO_RECOVERABLE,
            rule_id=automatic.approval_rule,
            reason_detail=automatic.approval_detail,
            cited_constraint_ids=automatic.cited_constraint_ids,
            chosen_option_id=automatic.id,
        )

    needs_approval = _preferred(option_set.valid, requires_approval=True)
    if needs_approval is not None:
        return ClassificationResult(
            promise_id=promise_id,
            classification=Classification.APPROVAL_REQUIRED,
            rule_id=needs_approval.approval_rule,
            reason_detail=needs_approval.approval_detail,
            cited_constraint_ids=needs_approval.cited_constraint_ids,
            chosen_option_id=needs_approval.id,
        )

    return _blocked(promise_id, option_set)


def _preferred(
    options: tuple[RecoveryOption, ...], *, requires_approval: bool
) -> RecoveryOption | None:
    for option in options:
        if option.requires_approval is requires_approval:
            return option
    return None


def _blocked(promise_id: PromiseId, option_set: OptionSet) -> ClassificationResult:
    """Pick the cited rule by the fixed rejection-precedence ladder."""
    for reason in REJECTION_PRECEDENCE:
        for rejected in option_set.rejected:
            if rejected.reason is reason:
                return ClassificationResult(
                    promise_id=promise_id,
                    classification=Classification.BLOCKED,
                    rule_id=_REASON_TO_RULE[reason],
                    reason_detail=rejected.detail,
                    cited_constraint_ids=rejected.cited_constraint_ids,
                    note=rejected.note,
                )
    return ClassificationResult(
        promise_id=promise_id,
        classification=Classification.BLOCKED,
        rule_id=RuleId.R_NOSUB,
        reason_detail=ReasonDetail.NO_PREAUTHORED_VARIANT,
        note="no recovery candidate exists for this promise",
    )


def analyze(snapshot: GraphSnapshot, exception: PhysicalException, now: datetime) -> AnalysisResult:
    """Propagate, validate options in allocation priority order, and classify every promise.

    Priority is the allocation order — earliest affected task start first — so a
    higher-priority track's committed substitute claim is subtracted before a later track is
    validated. A track that fails validation commits nothing.
    """
    impact = propagate(snapshot, exception, now)
    option_sets: dict[PromiseId, OptionSet] = {}
    classifications: dict[PromiseId, ClassificationResult] = {}

    claims = PlanClaims()
    for promise_id in _priority_order(snapshot, impact):
        option_set = enumerate_options(snapshot, impact, promise_id, now, claims)
        option_sets[promise_id] = option_set
        result = classify(snapshot, impact, promise_id, option_set)
        classifications[promise_id] = result
        if result.chosen_option_id is not None:
            chosen = next(
                option for option in option_set.valid if option.id == result.chosen_option_id
            )
            committed = claims_for_option(snapshot, chosen)
            claims = claims.extend(committed.resource_claims, committed.equipment_claims)

    for promise_id in sorted(snapshot.promises):
        if promise_id not in classifications:
            option_sets[promise_id] = OptionSet(promise_id=promise_id)
            classifications[promise_id] = classify(
                snapshot, impact, promise_id, option_sets[promise_id]
            )
    return AnalysisResult(
        impact=impact,
        option_sets=dict(sorted(option_sets.items())),
        classifications=dict(sorted(classifications.items())),
    )


def _priority_order(snapshot: GraphSnapshot, impact: Impact) -> tuple[PromiseId, ...]:
    """Affected promises ordered exactly as the allocator orders their tasks."""
    keyed: list[tuple[str, str, PromiseId]] = []
    for promise_id in impact.affected_promise_ids:
        order = snapshot.orders[snapshot.promises[promise_id].order_id]
        starts = [
            task.scheduled_start.isoformat()
            for line in order.lines
            if (task := snapshot.task_of_line(line.id)) is not None
            and task.scheduled_start is not None
        ]
        keyed.append((min(starts) if starts else "", order.external_id, promise_id))
    return tuple(promise_id for _, _, promise_id in sorted(keyed))
