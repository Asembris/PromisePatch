"""Evidence records: the single rendering of an analysis for UI, audit and narration.

Nothing here decides anything. It assembles what the other modules already decided into one
serialisable shape so the Evidence screen, the audit event payload and the plan-summary
context cannot drift apart by recomputing the same thing differently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from promise_graph.availability import AvailabilityView, available_by
from promise_graph.classification import AnalysisResult, ClassificationResult
from promise_graph.model import (
    ConstraintId,
    CustomerId,
    OrderId,
    PromiseId,
    ResourceId,
)
from promise_graph.options import OptionSet, RecoveryOption, RejectedCandidate
from promise_graph.propagation import LineQuantification, Path
from promise_graph.snapshot import GraphSnapshot


class Reachability(StrEnum):
    """Distinguishing "no path" from "reachable but covered" is a demo requirement."""

    NO_PATH = "NO_PATH"
    REACHABLE_COVERED = "REACHABLE_COVERED"
    AFFECTED = "AFFECTED"


@dataclass(frozen=True)
class ConstraintCitation:
    id: ConstraintId
    kind: str
    resource_id: str
    substitute_resource_id: str
    recorded_by: str
    recorded_at: str


@dataclass(frozen=True)
class PromiseEvidence:
    promise_id: PromiseId
    order_id: OrderId
    customer_id: CustomerId
    reachability: Reachability
    paths: tuple[Path, ...]
    quantifications: tuple[LineQuantification, ...]
    availability: tuple[AvailabilityView, ...]
    classification: ClassificationResult
    citations: tuple[ConstraintCitation, ...]
    valid_options: tuple[RecoveryOption, ...]
    rejected_candidates: tuple[RejectedCandidate, ...]


@dataclass(frozen=True)
class CaseEvidence:
    exception_id: str
    category: str
    entry_node_refs: tuple[str, ...]
    promises: Mapping[PromiseId, PromiseEvidence]
    affected_promise_ids: tuple[PromiseId, ...]
    unaffected_promise_ids: tuple[PromiseId, ...]


def build_promise_evidence(
    snapshot: GraphSnapshot,
    analysis: AnalysisResult,
    promise_id: PromiseId,
    now: datetime,
) -> PromiseEvidence:
    impact = analysis.impact
    option_set: OptionSet = analysis.option_sets[promise_id]
    classification = analysis.classifications[promise_id]
    order_id = snapshot.promises[promise_id].order_id
    order = snapshot.orders[order_id]

    if promise_id in impact.unreachable_promise_ids:
        reachability = Reachability.NO_PATH
    elif promise_id in impact.affected_promise_ids:
        reachability = Reachability.AFFECTED
    else:
        reachability = Reachability.REACHABLE_COVERED

    quantifications = tuple(
        quantification
        for line in order.lines
        for quantification in impact.quantifications_by_line.get(line.id, ())
    )

    resource_ids: set[ResourceId] = {q.resource_id for q in quantifications}
    for option in option_set.valid:
        if option.substitute_resource_id is not None:
            resource_ids.add(option.substitute_resource_id)
    views = tuple(
        available_by(snapshot, resource_id, _reference_time(snapshot, order_id, now), now)
        for resource_id in sorted(resource_ids)
    )

    citations = tuple(
        ConstraintCitation(
            id=constraint.id,
            kind=str(constraint.kind),
            resource_id=constraint.resource_id or "",
            substitute_resource_id=constraint.substitute_resource_id or "",
            recorded_by=constraint.recorded_by,
            recorded_at=constraint.recorded_at.isoformat(),
        )
        for constraint in snapshot.constraints_for_order(order_id)
        if constraint.id in classification.cited_constraint_ids
    )

    return PromiseEvidence(
        promise_id=promise_id,
        order_id=order_id,
        customer_id=order.customer_id,
        reachability=reachability,
        paths=impact.paths_by_promise.get(promise_id, ()),
        quantifications=quantifications,
        availability=views,
        classification=classification,
        citations=citations,
        valid_options=option_set.valid,
        rejected_candidates=option_set.rejected,
    )


def build_case_evidence(
    snapshot: GraphSnapshot, analysis: AnalysisResult, now: datetime
) -> CaseEvidence:
    """Per-promise evidence plus the explicit unaffected list — selectivity is evidence."""
    promises = {
        promise_id: build_promise_evidence(snapshot, analysis, promise_id, now)
        for promise_id in sorted(snapshot.promises)
    }
    return CaseEvidence(
        exception_id=analysis.impact.exception_id,
        category=str(analysis.impact.category),
        entry_node_refs=analysis.impact.entry_node_refs,
        promises=promises,
        affected_promise_ids=tuple(sorted(analysis.impact.affected_promise_ids)),
        unaffected_promise_ids=tuple(
            promise_id
            for promise_id, evidence in promises.items()
            if evidence.reachability is not Reachability.AFFECTED
        ),
    )


def _reference_time(snapshot: GraphSnapshot, order_id: OrderId, now: datetime) -> datetime:
    """Availability is quoted as of the earliest production start on the order."""
    starts = [
        task.scheduled_start
        for line in snapshot.orders[order_id].lines
        if (task := snapshot.task_of_line(line.id)) is not None and task.scheduled_start is not None
    ]
    return min(starts) if starts else now
