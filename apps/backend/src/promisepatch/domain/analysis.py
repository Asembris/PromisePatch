"""Impact analysis and recovery planning: the deterministic engine's answer, made durable.

Two steps, and the split between them is the frozen one. ``ANALYZE_IMPACT`` propagates the
attested exception through a freshly loaded graph, classifies every promise and writes the
tracks and their paths; ``PLAN_RECOVERY`` validates the options for the tracks that survive
and writes them with the fingerprint each will later be revalidated against. Neither executes
anything: no order is amended, no reservation moves, no task is held and no customer is asked.

**Nothing here decides anything.** Reachability, quantified shortfall, classification, cited
rules and constraints, option eligibility and fingerprints all come out of ``promise_graph``
and are persisted verbatim. There is deliberately no ``if pre-approved then AUTO_RECOVERABLE``
in this file, and there must never be one: a second implementation of the classification
ladder would eventually disagree with the first, and the disagreement would be invisible.

**The snapshot is always fresh.** The graph is loaded through
:func:`~promisepatch.graph.loader.load_snapshot` in its own read-only, repeatable-read
transaction, after this transaction has taken the case row -- so the view is at least as
current as the lock, and no value is carried over from the intake command that preceded it.

**Lock order.** The executor already holds the ``case_steps`` row and the ``cases`` row. This
module then takes the ``promises`` rows it is about to claim a track on, in ascending id, so
two cases reaching the same promise queue rather than race. Everything else it writes are rows
it has just created. The domain event is appended last, by the step executor.

**Idempotency is a derived key, not a lookup.** Track, path and option ids are ``uuid5`` values
derived from the case, the promise and the engine's own option reference, so a replayed step
proposes the identical rows and the primary key refuses the duplicate. A *re-*analysis -- a
correcting attestation arriving after the first pass -- rewrites the same track rows and
replaces their paths and options, because those tables are the current materialisation of an
analysis rather than a ledger. The record of what was decided and why is ``audit_events``,
which nothing rewrites.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid5

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.classification import AnalysisResult, ClassificationResult, analyze
from promise_graph.classification import priority_order as engine_priority_order
from promise_graph.fingerprint import TrackScope, fingerprint, scope_for
from promise_graph.model import Classification, ExceptionCategory
from promise_graph.model import PhysicalException as EngineException
from promise_graph.options import OptionSet, approval_deadline
from promise_graph.options import RecoveryOption as EngineOption
from promise_graph.propagation import Impact, LineQuantification, Path
from promise_graph.snapshot import GraphSnapshot
from promisepatch.db.models import (
    Case,
    PhysicalException,
    RecoveryOption,
    Track,
    TrackPath,
    TrackWatch,
)
from promisepatch.db.models import Promise as PromiseRow
from promisepatch.db.types import TERMINAL_TRACK_STATES
from promisepatch.db.uow import Actor, GovernedWrite, UnitOfWork
from promisepatch.domain.cases import LockedCase
from promisepatch.domain.model import (
    EVENT_STEP_COMPLETED,
    EVENT_STEP_SKIPPED,
    AppendEvent,
    CaseChange,
    CreateStep,
    Disposition,
    StepOutcome,
)
from promisepatch.graph.loader import load_snapshot, snapshot_session

NAMESPACE: Final = UUID("2c9f7a61-4d38-5b0e-9c17-8f6a3b25de41")
"""The namespace every derived analysis identifier is minted in.

Derived rather than random for the same reason intake's are: an id that changes on replay is
an id that cannot make a replay idempotent.
"""

# ------------------------------------------------------------------------------- case states

CASE_ANALYZED: Final = "ANALYZED"
CASE_PLANNED: Final = "PLANNED"

ANALYSABLE_STATES: Final[frozenset[str]] = frozenset({"INTERPRETING", CASE_ANALYZED, CASE_PLANNED})
"""States in which running impact analysis means something.

``INTERPRETING`` is the first pass, straight off a resolved intake. ``ANALYZED`` and
``PLANNED`` are re-analysis after a correcting attestation: the physical truth moved, so the
classification has to be taken again against the truth that now stands. Anything else --
``CLARIFYING`` (the binding is still a question), ``NEEDS_HUMAN_INTERPRETATION``, ``RESOLVED``,
``CANCELLED`` -- means the step is describing work on a case that has moved past it, and it
skips rather than inventing an analysis nobody asked for.
"""

# ------------------------------------------------------------------------------ track states

TRACK_PENDING: Final = "PENDING"
TRACK_UNAFFECTED: Final = "UNAFFECTED"
TRACK_LINKED: Final = "LINKED"
"""The three durable postures a track can be in at the end of planning.

``PENDING`` is the frozen §13.4 vocabulary for a classified track that has not been confirmed:
``AUTO_RECOVERABLE``, ``APPROVAL_REQUIRED`` and ``BLOCKED`` all wait here for the worker's
"yes" before they become ``APPLYING``, ``WAITING_FOR_CUSTOMER`` or ``ESCALATED``. Planning is
therefore never allowed to write one of those three: each of them names an execution that has
not happened.
"""

# ------------------------------------------------------------------------------- step naming

STEP_ANALYZE_IMPACT: Final = "ANALYZE_IMPACT"
STEP_PLAN_RECOVERY: Final = "PLAN_RECOVERY"

ANALYSIS_STEP_KINDS: Final[frozenset[str]] = frozenset({STEP_ANALYZE_IMPACT, STEP_PLAN_RECOVERY})
"""Step kinds the worker routes here rather than to a pure handler: both need the graph."""


def analyze_step_key(statement_id: UUID) -> str:
    """The analysis a statement's attested facts call for.

    Named after the *statement* rather than the case, so a correcting attestation enqueues its
    own analysis instead of colliding with the one the first attestation already ran -- and so
    a replayed resolution proposes the identical key and the unique index refuses it.
    """
    return f"analyze:{statement_id}"


def plan_step_key(statement_id: UUID) -> str:
    """The plan that follows one analysis. Same identity, so the pair cannot drift apart."""
    return f"plan:{statement_id}"


def statement_of(step_key: str) -> UUID:
    """The statement an analysis step is about, read back out of its key."""
    return UUID(step_key.partition(":")[2])


# ------------------------------------------------------------------------------ event names

EVENT_CASE_ANALYZED: Final = "case.analyzed"
EVENT_TRACK_CLASSIFIED: Final = "track.classified"
EVENT_CASE_PLANNED: Final = "case.planned"
EVENT_ANALYSIS_SUPERSEDED: Final = "case.analysis_superseded"
"""The spine's account of analysis and planning.

Envelopes only, and deliberately silent about promises the exception never reached: a feed
that named an unaffected customer's order would break the selectivity guarantee in the one
place nobody looks. The authoritative detail lives in ``tracks``, ``track_paths`` and
``recovery_options``, behind the read APIs.
"""

# ------------------------------------------------------------------------------ audit types

AUDIT_IMPACT_ANALYZED: Final = "IMPACT_ANALYZED"
AUDIT_RECOVERY_PLANNED: Final = "RECOVERY_PLANNED"
AUDIT_PROMISE_ALREADY_IN_CASE: Final = "PROMISE_ALREADY_IN_CASE"

# --------------------------------------------------------------------------- watch entities

WATCH_ORDER: Final = "order"
WATCH_ORDER_LINE: Final = "order_line"
WATCH_RECIPE_VERSION: Final = "recipe_version"
WATCH_CONSTRAINT: Final = "order_constraint"
WATCH_RESERVATION: Final = "reservation"
WATCH_TASK: Final = "production_task"
WATCH_RESOURCE: Final = "resource"

SCOPE_WATCH_TYPES: Final[tuple[str, ...]] = (
    WATCH_ORDER,
    WATCH_ORDER_LINE,
    WATCH_TASK,
    WATCH_RESOURCE,
)
"""The watch rows a :class:`~promise_graph.fingerprint.TrackScope` can be rebuilt from.

Revalidation needs the scope back, not a description of it, so these four are exactly the
fields of ``TrackScope``. The other three -- pinned versions, constraints, reservations -- are
watched because an order-system change event names them, and are already inside the
fingerprint that the scope produces.
"""


class AnalysisStateError(RuntimeError):
    """The case is not in a shape this step can analyse or plan against."""


# --------------------------------------------------------------------------------- executor


async def execute(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    kind: str,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Run one analysis step against a case whose row this transaction already holds."""
    if kind == STEP_ANALYZE_IMPACT:
        return await _analyze(connection, case=case, step_key=step_key, now=now, worker=worker)
    return await _plan(connection, case=case, step_key=step_key, now=now, worker=worker)


# --------------------------------------------------------------------------------- analysis


async def _analyze(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Classify every promise against the exception, and write what the engine decided."""
    if case.state not in ANALYSABLE_STATES:
        return _skipped(STEP_ANALYZE_IMPACT, case.state)

    exception = await _bound_exception(connection, case.id)
    snapshot = await fresh_snapshot(connection)
    analysis = analyze(snapshot, exception, now)
    ranks = {
        promise_id: rank
        for rank, promise_id in enumerate(engine_priority_order(snapshot, analysis.impact), start=1)
    }

    claimed = sorted(
        promise_id
        for promise_id, result in analysis.classifications.items()
        if result.classification is not Classification.UNAFFECTED
    )
    await _lock_promises(connection, claimed)
    elsewhere = await _live_tracks_elsewhere(connection, claimed, case.id)

    records = tuple(
        _record_for(
            case_id=case.id,
            result=analysis.classifications[promise_id],
            paths=analysis.impact.paths_by_promise.get(promise_id, ()),
            impact=analysis.impact,
            rank=ranks.get(promise_id, 0),
            linked_to=elsewhere.get(promise_id),
        )
        for promise_id in sorted(analysis.classifications)
    )

    unit_of_work = UnitOfWork(connection)
    linked = tuple(record for record in records if record.state == TRACK_LINKED)
    if linked:
        # Its own audit row, because "this promise is already being recovered by another case"
        # is a different fact from "this is what the exception did to it", and an operator
        # looking for why a track is doing nothing needs to find that fact by name.
        async with unit_of_work.governed(
            event_type=AUDIT_PROMISE_ALREADY_IN_CASE,
            actor=Actor(kind="SYSTEM", id=worker),
            authority="NONE",
            case_id=case.id,
            before={"case_state": case.state},
            after={"linked": {record.promise_id: str(record.linked_track_id) for record in linked}},
            provenance={"step_key": step_key, "exception": exception.id},
            occurred_at=now,
        ) as write:
            for record in linked:
                await _write_track(write, record=record)

    async with unit_of_work.governed(
        event_type=AUDIT_IMPACT_ANALYZED,
        # The system executed a deterministic classification. No policy and no consent
        # permitted it, and no person decided it -- which is what ``NONE`` says. The worker who
        # attested the physical facts is named on their own PHYSICAL_FACT_RECORDED row; that
        # distinction is §11.8 and collapsing it here would lose it.
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        before={"case_state": case.state},
        after={
            "case_state": CASE_ANALYZED,
            "classifications": {record.promise_id: record.classification for record in records},
            "rules": {record.promise_id: record.rule_id for record in records},
        },
        provenance={
            "step_key": step_key,
            "exception": exception.id,
            "category": exception.category.value,
            "as_of": snapshot.as_of,
        },
        occurred_at=now,
    ) as write:
        for record in records:
            if record.state != TRACK_LINKED:
                await _write_track(write, record=record)
            await _replace_paths(write, record=record)

    statement_id = statement_of(step_key)
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=CASE_ANALYZED),
        successors=(CreateStep(step_key=plan_step_key(statement_id), kind=STEP_PLAN_RECOVERY),),
        events=(
            AppendEvent(
                type=EVENT_CASE_ANALYZED,
                payload={
                    "affected": len(analysis.impact.affected_promise_ids),
                    "considered": len(records),
                    "as_of": snapshot.as_of,
                },
                entity_refs=({"kind": "case", "id": str(case.id)},),
            ),
            *(
                AppendEvent(
                    type=EVENT_TRACK_CLASSIFIED,
                    payload={
                        "classification": record.classification,
                        "rule_id": record.rule_id,
                    },
                    entity_refs=({"kind": "track", "id": str(record.track_id)},),
                )
                # Only promises the exception actually reached. An event naming an unaffected
                # order would put unrelated customer work on every subscriber's feed, which is
                # exactly the write the selectivity guarantee forbids.
                for record in records
                if record.classification != Classification.UNAFFECTED.value
            ),
        ),
        result={
            "outcome": "ANALYZED",
            "as_of": snapshot.as_of,
            "classifications": {record.promise_id: record.classification for record in records},
            "rules": {record.promise_id: record.rule_id for record in records},
            "tracks": {record.promise_id: str(record.track_id) for record in records},
        },
    )


@dataclass(frozen=True, slots=True)
class _TrackRecord:
    """One promise's durable posture, assembled from engine output alone."""

    case_id: UUID
    track_id: UUID
    promise_id: str
    state: str
    classification: str
    rule_id: str
    reason_detail: str
    priority: int
    linked_track_id: UUID | None
    paths: tuple[dict[str, Any], ...]


def _record_for(
    *,
    case_id: UUID,
    result: ClassificationResult,
    paths: tuple[Path, ...],
    impact: Impact,
    rank: int,
    linked_to: UUID | None,
) -> _TrackRecord:
    """Turn one engine classification into the row it becomes. No decision is taken here."""
    track_id = track_id_for(case_id, result.promise_id)
    if result.classification is Classification.UNAFFECTED:
        state = TRACK_UNAFFECTED
    elif linked_to is not None:
        state = TRACK_LINKED
    else:
        state = TRACK_PENDING
    return _TrackRecord(
        case_id=case_id,
        track_id=track_id,
        promise_id=result.promise_id,
        state=state,
        classification=result.classification.value,
        rule_id=result.rule_id.value,
        reason_detail=result.reason_detail.value,
        priority=rank,
        linked_track_id=linked_to if state == TRACK_LINKED else None,
        paths=tuple(
            _path_row(track_id=track_id, ordinal=ordinal, path=path, impact=impact, result=result)
            for ordinal, path in enumerate(paths)
        ),
    )


def _path_row(
    *, track_id: UUID, ordinal: int, path: Path, impact: Impact, result: ClassificationResult
) -> dict[str, Any]:
    """One traversed path with the quantification that decided what it meant."""
    nodes = [
        {
            "node_ref": step.node_ref,
            "edge_kind": None if step.edge_kind is None else step.edge_kind.value,
            "role": None if step.role is None else step.role.value,
        }
        for step in path
    ]
    role = next((step.role for step in reversed(path) if step.role is not None), None)
    return {
        "id": path_id_for(track_id, ordinal),
        "track_id": track_id,
        "ordinal": ordinal,
        "nodes": nodes,
        "role": None if role is None else role.value,
        "quantification": _quantification_of(path, impact),
        "rule_id": result.rule_id.value,
    }


def _quantification_of(path: Path, impact: Impact) -> dict[str, Any] | None:
    """The engine's own arithmetic for the order line this path arrives at.

    Kept beside the path because "reachable but covered" and "reachable and short" are the
    same set of nodes and different outcomes, and the difference is these numbers.
    """
    order_line_id = next(
        (step.node_ref for step in path if step.node_ref in impact.quantifications_by_line), None
    )
    if order_line_id is None:
        return None
    on_path = {step.node_ref for step in path}
    for quantification in impact.quantifications_by_line[order_line_id]:
        if quantification.resource_id in on_path:
            return _quantification_row(quantification)
    return None


def _quantification_row(value: LineQuantification) -> dict[str, Any]:
    return {
        "order_line_id": value.order_line_id,
        "resource_id": value.resource_id,
        "reservation_id": value.reservation_id,
        "roles": [role.value for role in value.roles],
        "need": _text(value.need),
        "available_before_start": _text(value.available_before_start),
        "shortfall": _text(value.shortfall),
        "satisfied": value.satisfied,
        "unknown": value.unknown,
    }


# --------------------------------------------------------------------------------- planning


async def _plan(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Validate options against a freshly loaded graph and write the plan, or refuse to.

    The engine is re-run rather than trusted from the previous step, which is what makes the
    stale check real: if the physical truth moved between analysis and planning -- a correcting
    attestation, an order-system change -- the recomputed classification differs from the one
    on the track, and no plan is written for a world that no longer exists.
    """
    if case.state != CASE_ANALYZED:
        return _skipped(STEP_PLAN_RECOVERY, case.state)

    exception = await _bound_exception(connection, case.id)
    tracks = await _tracks_of_case(connection, case.id)
    snapshot = await fresh_snapshot(connection)
    analysis = analyze(snapshot, exception, now)

    drift = _drift(tracks, analysis)
    if drift:
        return _superseded(case=case, step_key=step_key, drift=drift, worker=worker, now=now)

    plans = tuple(
        _plan_for(snapshot=snapshot, analysis=analysis, track=track, now=now)
        for track in tracks
        if track.state == TRACK_PENDING
    )

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_RECOVERY_PLANNED,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        before={"case_state": case.state},
        after={
            "case_state": CASE_PLANNED,
            "options": {plan.promise_id: len(plan.options) for plan in plans},
            "chosen": {
                plan.promise_id: (None if plan.chosen_id is None else str(plan.chosen_id))
                for plan in plans
            },
            "fingerprints": {plan.promise_id: plan.fingerprint for plan in plans},
        },
        provenance={"step_key": step_key, "exception": exception.id, "as_of": snapshot.as_of},
        occurred_at=now,
    ) as write:
        for plan in plans:
            await _replace_options(write, plan=plan)
            await _replace_watch(write, plan=plan)
            await _write_plan(write, plan=plan)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=CASE_PLANNED),
        events=(
            AppendEvent(
                type=EVENT_CASE_PLANNED,
                payload={
                    "tracks": len(plans),
                    "options": sum(len(plan.options) for plan in plans),
                    "as_of": snapshot.as_of,
                },
                entity_refs=tuple({"kind": "track", "id": str(plan.track_id)} for plan in plans)
                or ({"kind": "case", "id": str(case.id)},),
            ),
        ),
        result={
            "outcome": "PLANNED",
            "as_of": snapshot.as_of,
            "chosen": {
                plan.promise_id: (None if plan.chosen_id is None else str(plan.chosen_id))
                for plan in plans
            },
            "fingerprints": {plan.promise_id: plan.fingerprint for plan in plans},
        },
    )


@dataclass(frozen=True, slots=True)
class _PlanRecord:
    """One live track's plan: the options that validated, the one chosen, and the watch."""

    track_id: UUID
    promise_id: str
    fingerprint: str
    chosen_id: UUID | None
    deadline_at: datetime | None
    options: tuple[dict[str, Any], ...]
    watch: tuple[tuple[str, str], ...]


def _plan_for(
    *, snapshot: GraphSnapshot, analysis: AnalysisResult, track: Any, now: datetime
) -> _PlanRecord:
    """Assemble one track's plan out of engine output. Selects nothing on its own."""
    promise_id: str = track.promise_id
    option_set: OptionSet = analysis.option_sets[promise_id]
    result = analysis.classifications[promise_id]
    scope = scope_for(snapshot, analysis.impact, option_set, promise_id)
    stamp = fingerprint(snapshot, scope)

    chosen = next(
        (option for option in option_set.valid if option.id == result.chosen_option_id), None
    )
    return _PlanRecord(
        track_id=track.id,
        promise_id=promise_id,
        fingerprint=stamp.hash,
        chosen_id=None if chosen is None else option_id_for(track.id, chosen.id),
        # The window as it stands at planning. Execution recomputes it at send time, because
        # §13.6 measures the deadline from the instant the request actually goes out.
        deadline_at=(
            approval_deadline(now, chosen.task_start)
            if chosen is not None and chosen.requires_approval and chosen.task_start is not None
            else None
        ),
        options=tuple(_option_row(track_id=track.id, option=option) for option in option_set.valid),
        watch=_watch_pairs(snapshot, scope, result, option_set),
    )


def _option_row(*, track_id: UUID, option: EngineOption) -> dict[str, Any]:
    """A validated candidate, as the row it becomes.

    Every version id here is one the engine read out of an existing ``substitution_policies``
    row, and the foreign key on ``recovery_options`` makes that structural: there is no shape
    of this dictionary that can name a recipe version nobody authored.
    """
    return {
        "id": option_id_for(track_id, option.id),
        "track_id": track_id,
        "kind": option.kind.value,
        "order_line_id": option.order_line_id,
        "from_version_id": option.from_version_id,
        "to_version_id": option.to_version_id,
        "from_equipment_id": option.from_equipment_id,
        "to_equipment_id": option.to_equipment_id,
        "affected_resource_id": option.affected_resource_id,
        "substitute_resource_id": option.substitute_resource_id,
        "required_quantity": option.required_quantity,
        "visible_change": option.visible_change,
        "requires_approval": option.requires_approval,
        "approval_rule": option.approval_rule.value,
        "cited_constraint_ids": list(option.cited_constraint_ids),
        "policy_id": option.policy_id,
        "task_start": option.task_start,
    }


def _watch_pairs(
    snapshot: GraphSnapshot,
    scope: TrackScope,
    result: ClassificationResult,
    option_set: OptionSet,
) -> tuple[tuple[str, str], ...]:
    """Exactly what a later change would have to touch to invalidate this plan.

    The first four types are the fields of :class:`~promise_graph.fingerprint.TrackScope`, so
    the scope can be rebuilt from them and the fingerprint recomputed without re-running
    propagation. The last three are named because an order-system change event names them.
    """
    pairs: set[tuple[str, str]] = {(WATCH_ORDER, scope.order_id)}
    pairs.update((WATCH_ORDER_LINE, line_id) for line_id in scope.order_line_ids)
    pairs.update((WATCH_TASK, task_id) for task_id in scope.task_ids)
    pairs.update((WATCH_RESOURCE, resource_id) for resource_id in scope.resource_ids)
    pairs.update(
        (WATCH_RECIPE_VERSION, snapshot.order_lines[line_id].recipe_version_id)
        for line_id in scope.order_line_ids
    )
    pairs.update(
        (WATCH_RECIPE_VERSION, option.to_version_id)
        for option in option_set.valid
        if option.to_version_id is not None
    )
    pairs.update(
        (WATCH_CONSTRAINT, constraint.id)
        for constraint in snapshot.constraints_for_order(scope.order_id)
    )
    pairs.update((WATCH_CONSTRAINT, constraint_id) for constraint_id in result.cited_constraint_ids)
    pairs.update(
        (WATCH_RESERVATION, reservation_id)
        for line_id in scope.order_line_ids
        for reservation_id in snapshot.reservations_by_order_line.get(line_id, ())
    )
    return tuple(sorted(pairs))


def scope_from_watch(rows: Sequence[tuple[str, str]], *, promise_id: str) -> TrackScope:
    """Rebuild a track's scope from its persisted watch rows.

    The inverse of the first four types :func:`_watch_pairs` writes, so a later revalidation
    can recompute the same fingerprint over the same entities without re-running propagation.
    """
    by_type: dict[str, list[str]] = {}
    for entity_type, entity_id in rows:
        by_type.setdefault(entity_type, []).append(entity_id)
    orders = sorted(by_type.get(WATCH_ORDER, ()))
    if len(orders) != 1:
        raise AnalysisStateError(
            f"track for {promise_id} watches {len(orders)} orders; a scope names exactly one"
        )
    return TrackScope(
        promise_id=promise_id,
        order_id=orders[0],
        order_line_ids=tuple(sorted(by_type.get(WATCH_ORDER_LINE, ()))),
        resource_ids=tuple(sorted(by_type.get(WATCH_RESOURCE, ()))),
        task_ids=tuple(sorted(by_type.get(WATCH_TASK, ()))),
    )


# ------------------------------------------------------------------------- stale protection


def _drift(tracks: Sequence[Any], analysis: AnalysisResult) -> Mapping[str, str]:
    """Where the freshly computed classification disagrees with the persisted one.

    Empty means the world the analysis described is still the world that exists. Anything else
    means this plan would be written against a state that has already been superseded, and the
    right answer is to write nothing at all.
    """
    moved: dict[str, str] = {}
    for track in tracks:
        result = analysis.classifications.get(track.promise_id)
        if result is None:
            moved[track.promise_id] = "no longer a promise in the graph"
            continue
        before = (track.classification, track.rule_id, track.reason_detail)
        after = (result.classification.value, result.rule_id.value, result.reason_detail.value)
        if before != after:
            moved[track.promise_id] = f"{'/'.join(before)} -> {'/'.join(after)}"
    known = {track.promise_id for track in tracks}
    for promise_id, result in analysis.classifications.items():
        if result.classification is not Classification.UNAFFECTED and promise_id not in known:
            moved[promise_id] = "newly affected since the analysis"
    return moved


def _superseded(
    *, case: LockedCase, step_key: str, drift: Mapping[str, str], worker: str, now: datetime
) -> StepOutcome:
    """Write no plan, keep the case at ``ANALYZED``, and say what moved.

    A fresh analysis is what unblocks this, and the statement that changed the physical truth
    has already enqueued one under its own key. Writing either answer over the other would be
    last-writer-wins on a customer promise.
    """
    return StepOutcome(
        disposition=Disposition.SKIPPED,
        event_type=EVENT_STEP_SKIPPED,
        events=(
            AppendEvent(
                type=EVENT_ANALYSIS_SUPERSEDED,
                payload={"promises": len(drift)},
                entity_refs=({"kind": "case", "id": str(case.id)},),
            ),
        ),
        result={
            "outcome": "SUPERSEDED",
            "step_key": step_key,
            "worker": worker,
            "at": now.isoformat(),
            "drift": dict(drift),
        },
    )


def _skipped(kind: str, case_state: str) -> StepOutcome:
    return StepOutcome(
        disposition=Disposition.SKIPPED,
        event_type=EVENT_STEP_SKIPPED,
        result={"outcome": "NOT_APPLICABLE", "kind": kind, "case_state": case_state},
    )


# ---------------------------------------------------------------------------------- writing


async def _write_track(write: GovernedWrite, *, record: _TrackRecord) -> None:
    """Upsert one track. A replay writes the identical values; a re-analysis writes new ones."""
    await write.execute(
        pg_insert(Track)
        .values(
            id=record.track_id,
            case_id=record.case_id,
            promise_id=record.promise_id,
            state=record.state,
            classification=record.classification,
            rule_id=record.rule_id,
            reason_detail=record.reason_detail,
            linked_track_id=record.linked_track_id,
            priority=record.priority,
            version=1,
        )
        .on_conflict_do_update(
            index_elements=[Track.id],
            set_={
                "state": record.state,
                "classification": record.classification,
                "rule_id": record.rule_id,
                "reason_detail": record.reason_detail,
                "linked_track_id": record.linked_track_id,
                "priority": record.priority,
                "version": Track.version + 1,
            },
        )
    )


async def _replace_paths(write: GovernedWrite, *, record: _TrackRecord) -> None:
    """The track's evidence, as this analysis found it.

    Replaced rather than appended, because ``track_paths`` is the current materialisation of
    one analysis and not a ledger: what was decided, and against what, is on the audit row.
    """
    keep = [row["id"] for row in record.paths]
    statement = delete(TrackPath).where(TrackPath.track_id == record.track_id)
    if keep:
        statement = statement.where(TrackPath.id.not_in(keep))
    await write.execute(statement)
    for row in record.paths:
        await write.execute(
            pg_insert(TrackPath)
            .values(**row)
            .on_conflict_do_update(
                index_elements=[TrackPath.id],
                set_={key: value for key, value in row.items() if key != "id"},
            )
        )


async def _replace_options(write: GovernedWrite, *, plan: _PlanRecord) -> None:
    keep = [row["id"] for row in plan.options]
    statement = delete(RecoveryOption).where(RecoveryOption.track_id == plan.track_id)
    if keep:
        statement = statement.where(RecoveryOption.id.not_in(keep))
    await write.execute(statement)
    for row in plan.options:
        await write.execute(
            pg_insert(RecoveryOption)
            .values(**row)
            .on_conflict_do_update(
                index_elements=[RecoveryOption.id],
                set_={key: value for key, value in row.items() if key != "id"},
            )
        )


async def _replace_watch(write: GovernedWrite, *, plan: _PlanRecord) -> None:
    await write.execute(delete(TrackWatch).where(TrackWatch.track_id == plan.track_id))
    for entity_type, entity_id in plan.watch:
        await write.execute(
            pg_insert(TrackWatch)
            .values(track_id=plan.track_id, entity_type=entity_type, entity_id=entity_id)
            .on_conflict_do_nothing()
        )


async def _write_plan(write: GovernedWrite, *, plan: _PlanRecord) -> None:
    """The track's planning posture. ``state`` is untouched: nothing has been executed.

    An update rather than an upsert: analysis created this row, and a plan for a track that
    does not exist would be a plan for a promise nobody classified.
    """
    result = await write.execute(
        update(Track)
        .where(Track.id == plan.track_id)
        .values(
            fingerprint=plan.fingerprint,
            chosen_option_id=plan.chosen_id,
            deadline_at=plan.deadline_at,
            version=Track.version + 1,
        )
    )
    if result.rowcount != 1:
        raise AnalysisStateError(f"track {plan.track_id} vanished between analysis and planning")


# ---------------------------------------------------------------------------------- reading


async def fresh_snapshot(connection: AsyncConnection) -> GraphSnapshot:
    """The whole graph, read now, in its own read-only repeatable-read transaction.

    A separate connection on purpose. The consistent whole-graph read the engine needs is
    ``REPEATABLE READ`` plus an ``ACCESS SHARE`` lock over the read set, and neither can be
    declared on a connection that is already inside a read-write transaction. Taking it after
    the case row is locked is what makes the view at least as current as the lock.
    """
    async with snapshot_session(connection.engine) as session:
        return await load_snapshot(session)


async def _bound_exception(connection: AsyncConnection, case_id: UUID) -> EngineException:
    """The attested exception this case is bound to, as the engine's own record."""
    row = (
        await connection.execute(
            select(PhysicalException)
            .join(Case, Case.exception_id == PhysicalException.id)
            .where(Case.id == case_id)
        )
    ).one_or_none()
    if row is None:
        raise AnalysisStateError(f"case {case_id} has no attested exception to analyse")
    return EngineException(
        id=str(row.id),
        category=ExceptionCategory(row.category),
        commitment_id=row.commitment_id,
        scope_line_ids=tuple(str(item) for item in row.scope_line_ids),
        resource_id=row.resource_id,
        quantity=row.quantity,
        outage_until=row.outage_until,
        reported_by=row.reported_by,
        reported_at=row.reported_at,
        raw_utterance=row.raw_utterance,
    )


async def _tracks_of_case(connection: AsyncConnection, case_id: UUID) -> Sequence[Any]:
    return (
        await connection.execute(
            select(Track).where(Track.case_id == case_id).order_by(Track.priority, Track.promise_id)
        )
    ).all()


async def _lock_promises(connection: AsyncConnection, promise_ids: Sequence[str]) -> None:
    """Take the promises this analysis is about to claim a track on, in ascending id.

    One order everywhere, so two cases reaching the same promise queue rather than deadlock,
    and the liveness check below cannot be overtaken between reading and writing.
    """
    if not promise_ids:
        return
    await connection.execute(
        select(PromiseRow.id)
        .where(PromiseRow.id.in_(list(promise_ids)))
        .order_by(PromiseRow.id)
        .with_for_update()
    )


async def _live_tracks_elsewhere(
    connection: AsyncConnection, promise_ids: Sequence[str], case_id: UUID
) -> Mapping[str, UUID]:
    """Promises another case is already recovering, and the track that holds each of them."""
    if not promise_ids:
        return {}
    rows = (
        await connection.execute(
            select(Track.promise_id, Track.id).where(
                Track.promise_id.in_(list(promise_ids)),
                Track.case_id != case_id,
                Track.state.not_in(TERMINAL_TRACK_STATES),
            )
        )
    ).all()
    return {row.promise_id: row.id for row in rows}


# ------------------------------------------------------------------------------ identifiers


def track_id_for(case_id: UUID, promise_id: str) -> UUID:
    """One track per promise per case, whatever happens to the process that writes it."""
    return uuid5(NAMESPACE, f"track:{case_id}:{promise_id}")


def option_id_for(track_id: UUID, option_ref: str) -> UUID:
    """Derived from the engine's own option reference, so the same candidate is the same row."""
    return uuid5(NAMESPACE, f"option:{track_id}:{option_ref}")


def path_id_for(track_id: UUID, ordinal: int) -> UUID:
    return uuid5(NAMESPACE, f"path:{track_id}:{ordinal}")


def _text(value: Decimal | None) -> str | None:
    """Quantities reach JSONB as text. A float in the payload would be a float in the record."""
    return None if value is None else str(value)
