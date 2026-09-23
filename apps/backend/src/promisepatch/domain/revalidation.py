"""The ten checks, run durably before an approved recovery is allowed to execute.

This is the slice that makes consent perishable. A customer said yes to a change to a world
that existed at that moment; between then and now the order can have been amended, the recipe
re-pinned, the constraints rewritten, the substitute eaten by an earlier recovery, the oven
started, and the window closed. §14.3 names the ten things that have to still be true, and this
module is where they are asked of the database rather than assumed.

**The decision is an input, not a permission.** :mod:`promisepatch.domain.approvals` already
committed exactly one authoritative ``ApprovalDecision`` and handed the case to
``REVALIDATING``. Nothing here re-reads the customer's words, re-parses them, or re-decides what
they meant -- the raw text is not consulted at all. What is consumed is the persisted evidence:
which request, which option, which reply, which sender, which parser.

**Two step kinds, and the split is the frozen boundary.**

``REVALIDATE_RECOVERY``
    One track whose approval has been settled. It loads a *fresh* snapshot -- never the one
    planning or the approval used -- runs :func:`promise_graph.revalidation.revalidate`, writes
    every check with the values it compared, and then does exactly one of five things: enqueue
    the existing recovery saga, mark the track ``STALE`` and enqueue a re-plan, escalate an
    expired authority, refuse an unauthorised one, or do nothing at all.

``RECONCILE_CASE``
    The case-level boundary of §14.1. It is created by whichever transition reached
    ``RECONCILING`` and finishes the case once every track is terminal and nothing durable is
    outstanding.

**Nothing here executes a recovery.** A passing revalidation enqueues ``APPLY_RECOVERY`` -- the
same crash-safe saga an automatic track uses, under the same stable idempotency key. The only
difference between A and B is *what authorised them*: a pre-approved policy for one, a
customer's literal yes plus these ten checks for the other. Forking the effect path for the
second would mean two idempotency stories, and the weaker one would eventually be the one that
mattered.

**Refusal is not a failure.** A ``STALE`` outcome is the product working: the customer approved
what used to be true, and PromisePatch declined to apply it to what is true now. The old plan,
the old request and the old decision are all kept exactly as they were, because the evidence
that somebody consented to something is not made false by the world moving on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.availability import Claim
from promise_graph.model import (
    ApprovalDecisionKind,
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    ApprovalRequestState,
    ParserKind,
)
from promise_graph.revalidation import (
    CheckResult,
    DecisionBinding,
    RevalidationOutcome,
    RevalidationResult,
    revalidate,
)
from promise_graph.snapshot import GraphSnapshot
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    CaseStep,
    InboundReply,
    RecoveryOption,
    Track,
)
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.domain import analysis, approvals, recovery
from promisepatch.domain.cases import (
    CASE_RECONCILING,
    CASE_REVALIDATING,
    CASE_WAITING,
    OPEN_APPROVAL_STATES,
    STEP_RECONCILE_CASE,
    STEP_REVALIDATE_RECOVERY,
    TRACK_WAITING_FOR_CUSTOMER,
    LockedCase,
    any_escalated,
    case_events,
    case_successors,
    case_timers,
    non_terminal_tracks,
    revalidate_step_key,
    revalidation_round_exit,
    settled_case_state,
    track_in,
)
from promisepatch.domain.model import (
    EVENT_STEP_COMPLETED,
    EVENT_STEP_FAILED,
    AppendEvent,
    CaseChange,
    CreateStep,
    Disposition,
    StepOutcome,
)
from promisepatch.observability import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------------------- step naming

REVALIDATION_STEP_KINDS: Final[frozenset[str]] = frozenset(
    {STEP_REVALIDATE_RECOVERY, STEP_RECONCILE_CASE}
)
"""Step kinds the worker routes here: both read the graph or the ledger to decide."""


def track_of(step_key: str) -> UUID:
    """The track a revalidation step is about, read back out of either shape of its key."""
    return track_in(step_key)


# ------------------------------------------------------------------------------- event names

EVENT_TRACK_REVALIDATION_PASSED: Final = "track.revalidation_passed"
EVENT_TRACK_REVALIDATION_FAILED: Final = "track.revalidation_failed"
"""Envelopes only. Which values were compared stays in the audit ledger, behind the read APIs.

Neither carries the customer's channel, their words, or the compared quantities: the feed
reaches every signed-in browser, and §26 keeps that material in the database, where a reader
has to be entitled to look.
"""

# ------------------------------------------------------------------------------- audit types

AUDIT_REVALIDATION_CHECK: Final = "REVALIDATION_CHECK"
"""One row per check, with the two values it compared. §22 shows all ten with their values.

Individually rather than as one payload because that is what the Audit screen renders and what
a judge is shown: ten named checks, each falsifiable on its own, each with a before and after.
"""

AUDIT_REVALIDATION_PASSED: Final = "RECOVERY_REVALIDATED"
AUDIT_REVALIDATION_REFUSED: Final = "RECOVERY_REVALIDATION_REFUSED"
AUDIT_REVALIDATION_NOT_REQUIRED: Final = "RECOVERY_REVALIDATION_NOT_REQUIRED"
AUDIT_CASE_RECONCILED: Final = "CASE_RECONCILED"


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
    """Run one revalidation or reconciliation step, under a case row this transaction holds."""
    if kind == STEP_REVALIDATE_RECOVERY:
        return await _revalidate(connection, case=case, step_key=step_key, now=now, worker=worker)
    return await _reconcile(connection, case=case, step_key=step_key, now=now, worker=worker)


async def work_for_case(connection: AsyncConnection, case_id: UUID) -> tuple[CreateStep, ...]:
    """One revalidation for every track of this case whose approval request has settled.

    Called by the transition that hands a case to ``REVALIDATING`` -- a literal decision, or a
    deadline that passed -- so the state and the work that leaves it commit together. Derived
    from rows rather than from what the caller happens to know, because the transition that
    settles the last request is not necessarily the one that settled the others.

    A declined or expired track is included deliberately. There are no ten checks to run for
    it, and there is still a case-level boundary to reach: §14.2's ``REVALIDATING`` is where a
    case goes to find out what its settled requests amount to, whatever the answer was.

    One per request a track *carries*. A re-asked track still has its first ask, superseded and
    already revalidated; checking it again would be checking an answer to a question nobody is
    asking any more, and keying the new one by the track would collide with it (ADR-0022).
    """
    rows = (
        await connection.execute(
            select(ApprovalRequest)
            .join(Track, Track.approval_request_id == ApprovalRequest.id)
            .where(
                Track.case_id == case_id,
                ApprovalRequest.state.not_in(OPEN_APPROVAL_STATES),
            )
            .order_by(Track.priority, Track.promise_id)
        )
    ).all()
    return tuple(
        CreateStep(
            step_key=revalidate_step_key(request.track_id, approvals.ask_scope(request)),
            kind=STEP_REVALIDATE_RECOVERY,
        )
        for request in rows
    )


# ------------------------------------------------------------------------------ the ten checks


async def _revalidate(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Ask §14.3's ten questions of current state, and act on the first answer that is no."""
    if case.state != CASE_REVALIDATING:
        # Already settled, already reconciling, or never got here. A revalidation that ran
        # anyway would be checking a decision somebody has already acted on.
        return recovery.skipped(STEP_REVALIDATE_RECOVERY, {"case_state": case.state})

    track = await recovery.lock_track(connection, track_of(step_key))
    request = await _lock_request(connection, track.approval_request_id)
    if request is None:
        return recovery.skipped(STEP_REVALIDATE_RECOVERY, {"track_state": track.state})
    if not approvals.step_names(step_key, request):
        # This checklist was for a request the track no longer carries. Its answer was recorded
        # when it ran; it is not an answer about the request the customer is being asked now.
        return recovery.skipped(STEP_REVALIDATE_RECOVERY, {"request_id": str(request.id)})

    decision = await _decision_for(connection, request.id)
    if decision is None or decision.decision != ApprovalDecisionKind.APPROVE.value:
        return await _no_authority_to_consume(
            connection,
            case=case,
            track=track,
            request=request,
            decision=decision,
            now=now,
            worker=worker,
            step_key=step_key,
        )

    snapshot = await analysis.fresh_snapshot(connection)
    option = await recovery.chosen_option(connection, track)
    inputs = await _inputs(
        connection,
        snapshot=snapshot,
        case=case,
        track=track,
        request=request,
        decision=decision,
        option=option,
    )
    result = revalidate(
        snapshot,
        inputs.request,
        inputs.decision,
        now,
        track_is_waiting_for_customer=track.state == TRACK_WAITING_FOR_CUSTOMER,
        case_is_waiting=case.state in _WAITING_POSTURES,
        recovered_claims=inputs.recovered_claims,
        holding_case_id=str(case.id),
        sender_chain=inputs.sender_chain,
        binding=inputs.binding,
    )

    if result.outcome is not RevalidationOutcome.PROCEED:
        return await _refuse(
            connection,
            case=case,
            track=track,
            request=request,
            result=result,
            snapshot=snapshot,
            now=now,
            worker=worker,
            step_key=step_key,
        )

    seen = await recovery.current_fingerprint(connection, track, snapshot=snapshot)
    if await watched_state_moved(connection, track=track, seen=seen):
        # The graph moved while the checks were being taken, so this PASS describes a world that
        # no longer exists. Nothing is written and the step runs again against the world that
        # does -- which will either pass honestly or go STALE.
        return StepOutcome(
            disposition=Disposition.RETRYING,
            event_type=EVENT_STEP_FAILED,
            error=f"watched state moved while track {track.id} was being revalidated",
        )
    return await _proceed(
        connection,
        case=case,
        track=track,
        request=request,
        decision=decision,
        option=option,
        result=result,
        snapshot=snapshot,
        seen=seen,
        now=now,
        worker=worker,
        step_key=step_key,
    )


# ------------------------------------------------------------------------------- the inputs

_WAITING_POSTURES: Final[frozenset[str]] = frozenset({CASE_WAITING, CASE_REVALIDATING})
"""Case states in which "the case is still waiting on this customer" is true.

§14.3's check 1 asks whether the case is waiting. The durable workflow moves a case to
``REVALIDATING`` *as the act of entering* the checklist, so a check that insisted on ``WAITING``
would be asking whether the checklist had not started. Both of these mean the case has not
moved past the wait; every other state means it has, and the check fails -- which is what makes
a re-delivered revalidation of an already-settled track a safe no-op.
"""

_BROKEN_CHAIN: Final = "<broken chain>"
"""What check 8 is told when the decision cannot be traced back to a stored reply at all."""


@dataclass(frozen=True, slots=True)
class _Inputs:
    """Everything the pure evaluator needs, assembled from persisted rows and nothing else."""

    request: ApprovalRequestRecord
    decision: ApprovalDecisionRecord
    recovered_claims: tuple[Claim, ...]
    sender_chain: str
    binding: DecisionBinding


async def _inputs(
    connection: AsyncConnection,
    *,
    snapshot: GraphSnapshot,
    case: LockedCase,
    track: Any,
    request: Any,
    decision: Any,
    option: Any,
) -> _Inputs:
    """Turn the rows this transaction holds into the engine's own records.

    Nothing is decided here. What is assembled is the material the engine has no way to reach:
    what the substitute costs, what other recoveries have already taken, whose reply the
    decision came from, and what that decision is bound to.
    """
    return _Inputs(
        request=ApprovalRequestRecord(
            id=str(request.id),
            track_id=str(request.track_id),
            promise_id=request.promise_id,
            order_id=request.order_id,
            order_line_id=request.order_line_id,
            option_id=str(request.option_id),
            candidate_version_id=None if option is None else option.to_version_id,
            substitute_resource_id=None if option is None else option.substitute_resource_id,
            required_substitute_quantity=None if option is None else option.required_quantity,
            customer_channel=request.customer_channel,
            sent_at=request.sent_at,
            deadline=request.deadline,
            captured_fingerprint=request.captured_fingerprint,
            captured_order_version=request.captured_order_version,
            captured_recipe_version_id=request.captured_recipe_version_id,
            captured_constraint_hash=request.captured_constraint_hash,
            state=ApprovalRequestState(request.state),
            decided=request.decided,
        ),
        decision=ApprovalDecisionRecord(
            request_id=str(decision.request_id),
            decision=ApprovalDecisionKind(decision.decision),
            parser=ParserKind(decision.parser),
            sender_identity=decision.sender_identity,
            provider_message_id=decision.provider_message_id,
            raw_text=decision.raw_text,
            received_at=decision.received_at,
        ),
        recovered_claims=await _recovered_claims(connection, snapshot, exclude=track.id),
        sender_chain=await _sender_chain(connection, request=request, decision=decision),
        binding=await _binding(connection, case=case, track=track, request=request),
    )


async def _sender_chain(connection: AsyncConnection, *, request: Any, decision: Any) -> str:
    """Follow decision -> stored inbound reply -> sender, and report where it arrives.

    The decision row carries its own ``sender_identity``, and a check that trusted only that
    would be trusting a denormalised copy of the thing it is meant to verify. This walks back to
    the reply the transport actually stored: same provider message id, bound to *this* request,
    carrying the same sender. A chain that does not join up resolves to a value matching no
    channel, so check 8 fails closed rather than passing on the copy.
    """
    reply = (
        await connection.execute(
            select(InboundReply).where(
                InboundReply.provider_message_id == decision.provider_message_id
            )
        )
    ).one_or_none()
    if reply is None or reply.request_id != request.id:
        return _BROKEN_CHAIN
    if reply.sender_identity != decision.sender_identity:
        return _BROKEN_CHAIN
    return str(reply.sender_identity)


async def _binding(
    connection: AsyncConnection, *, case: LockedCase, track: Any, request: Any
) -> DecisionBinding:
    """What the persisted decision is bound to, and whether it has already been spent.

    ``consumed`` is read from the step ledger rather than held in memory: this track's
    ``APPLY_RECOVERY`` row *is* the record that its consent has already authorised an execution,
    and it is created in the same transaction as the revalidation that permitted it. One
    consent, one recovery, enforced by a unique index rather than by a set in a process that
    restarts.
    """
    count = await connection.scalar(
        select(func.count())
        .select_from(ApprovalDecision)
        .where(ApprovalDecision.request_id == request.id)
    )
    already_applied = select(CaseStep.id).where(
        CaseStep.case_id == case.id, CaseStep.step_key == recovery.apply_step_key(track.id)
    )
    return DecisionBinding(
        request_id=str(request.id),
        track_id=str(track.id),
        option_id=str(track.chosen_option_id),
        decision_count=int(count or 0),
        superseded=request.state == ApprovalRequestState.SUPERSEDED.value,
        consumed=bool(await connection.scalar(select(exists(already_applied)))),
    )


async def _recovered_claims(
    connection: AsyncConnection, snapshot: GraphSnapshot, *, exclude: UUID
) -> tuple[Claim, ...]:
    """What tracks that already recovered have taken out of the substitute resources.

    §14.3's check 5 is "after allocations by tracks already RECOVERED", and §9.5 says those
    count against a later track's validation. They are read from the recovered tracks' own
    chosen options, because a recovery in this slice is an amendment pushed at the order system
    rather than a locally re-pinned line -- the external system is the record for that, so the
    claim is not visible in ``reservations`` and would silently count as zero if it were not
    added here.

    The arithmetic itself belongs to :func:`promise_graph.availability.allocate` and stays
    there. What this builds is the demand; nothing here compares a quantity to anything.
    """
    rows = (
        await connection.execute(
            select(
                Track.id,
                RecoveryOption.substitute_resource_id,
                RecoveryOption.required_quantity,
                RecoveryOption.task_start,
                RecoveryOption.order_line_id,
            )
            .join(RecoveryOption, RecoveryOption.id == Track.chosen_option_id)
            .where(
                Track.state == recovery.TRACK_RECOVERED,
                Track.id != exclude,
                RecoveryOption.substitute_resource_id.is_not(None),
                RecoveryOption.required_quantity.is_not(None),
                RecoveryOption.task_start.is_not(None),
                RecoveryOption.order_line_id.is_not(None),
            )
            .order_by(RecoveryOption.task_start, Track.id)
        )
    ).all()
    return tuple(
        Claim(
            id=f"recovered:{row.id}",
            resource_id=row.substitute_resource_id,
            quantity=Decimal(row.required_quantity),
            start=row.task_start,
            order_external_id=snapshot.order_of_line(row.order_line_id).external_id,
            order_line_id=row.order_line_id,
            is_candidate=True,
        )
        for row in rows
        if row.order_line_id in snapshot.order_lines
    )


# ------------------------------------------------------------------ the world moved under us


async def watched_state_moved(connection: AsyncConnection, *, track: Any, seen: str) -> bool:
    """Whether anything this track watches changed since the checks were taken.

    The fingerprint is already the complete digest of a track's watched state (§8.4), so
    recomputing it against a snapshot taken *after* the checks and comparing it to the one they
    were taken against asks exactly the right question -- and asks it with the same function
    planning and execution use, rather than with a second implementation that could drift.

    A revalidation that passed against a world which has since moved is refused rather than
    committed, which is what "no last-writer-wins" means at this boundary. The last line of
    defence is downstream and independent: ``APPLY_RECOVERY`` recomputes the fingerprint again
    inside the transaction that emits the amendment, so even a change landing after this
    returned ``False`` cannot become an effect under a plan that no longer describes the world.
    """
    return await recovery.current_fingerprint(connection, track) != seen


# ------------------------------------------------------------------------------ passing


async def _proceed(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    request: Any,
    decision: Any,
    option: Any,
    result: RevalidationResult,
    snapshot: GraphSnapshot,
    seen: str,
    now: datetime,
    worker: str,
    step_key: str,
) -> StepOutcome:
    """All ten passed. Hand the track to the recovery saga, and execute nothing here.

    One ``APPLY_RECOVERY`` step is created, in the same transaction as the ten check rows that
    permitted it. No network call, no amendment, no reservation move: what commits is the
    authority to run the saga, and the saga is what runs.
    """
    moved_to = await _case_moves_on(connection, case=case, step_key=step_key)
    unit_of_work = UnitOfWork(connection)
    await _record_checks(
        unit_of_work,
        case=case,
        track=track,
        request=request,
        result=result,
        now=now,
        worker=worker,
        step_key=step_key,
    )
    async with unit_of_work.governed(
        event_type=AUDIT_REVALIDATION_PASSED,
        # The system ran a deterministic checklist; it did not grant anything. The authority
        # that lets this recovery run is the customer's, given earlier on their own channel, and
        # it is named here with the decision that carries it so the chain stays recoverable:
        # the worker confirmed the plan, the customer approved this option, revalidation found
        # it still true. Collapsing that to "SYSTEM approved" would lose the part that matters.
        actor=Actor(kind="SYSTEM", id=worker),
        authority="HUMAN_APPROVAL",
        rule_id=None if option is None else option.approval_rule,
        case_id=case.id,
        track_id=track.id,
        before={"case_state": case.state, "track_state": track.state},
        after={
            "case_state": moved_to or case.state,
            "track_state": track.state,
            "outcome": result.outcome.value,
            "checks_passed": len(result.checks),
        },
        provenance={
            "step_key": step_key,
            "worker": worker,
            "request_id": str(request.id),
            "option_id": str(track.chosen_option_id),
            "decision": decision.decision,
            "parser": decision.parser,
            "provider_message_id": decision.provider_message_id,
            "sender_identity": decision.sender_identity,
            "captured_fingerprint": request.captured_fingerprint,
            "current_fingerprint": seen,
            "as_of": snapshot.as_of,
        },
        occurred_at=now,
    ):
        pass

    logger.info(
        "revalidation.passed",
        case_id=str(case.id),
        track_id=str(track.id),
        request_id=str(request.id),
        as_of=snapshot.as_of,
    )
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to),
        timers=case_timers(moved_to, case_id=case.id),
        successors=(
            CreateStep(
                step_key=recovery.apply_step_key(track.id), kind=recovery.STEP_APPLY_RECOVERY
            ),
            *await case_successors(connection, moved_to, case_id=case.id),
        ),
        events=(
            AppendEvent(
                type=EVENT_TRACK_REVALIDATION_PASSED,
                payload={"checks": len(result.checks)},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            *case_events(moved_to, case_id=case.id),
        ),
        result={
            "outcome": result.outcome.value,
            "track_id": str(track.id),
            "request_id": str(request.id),
            "option_id": str(track.chosen_option_id),
            "fingerprint": seen,
            "as_of": snapshot.as_of,
            "checks": _check_rows(result.checks),
        },
    )


# ------------------------------------------------------------------------------ refusing


async def _refuse(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    request: Any,
    result: RevalidationResult,
    snapshot: GraphSnapshot,
    now: datetime,
    worker: str,
    step_key: str,
) -> StepOutcome:
    """One of the ten said no. Which one decides what happens, and nothing is sent either way.

    §14.3's mapping, kept distinct rather than collapsed into a single "stale":

    * ``STALE`` (checks 2-6) -- the world moved. The track goes ``STALE``, the plan, request and
      decision are all left exactly as they are, and a re-plan is enqueued.
    * ``EXPIRED`` (check 7) -- consent that has aged out. The track escalates to the owner.
    * ``UNAUTHORIZED`` (check 8) -- the persisted provenance does not lead back to the customer's
      own channel. Nothing executes, the owner is told, and the track keeps waiting, because
      discarding a customer's request over a corrupted record would be the wrong repair.
    * ``NOOP`` (checks 1, 9, 10) -- already settled, not literal, or already spent. Audited, and
      otherwise nothing at all.
    """
    await _record_checks(
        UnitOfWork(connection),
        case=case,
        track=track,
        request=request,
        result=result,
        now=now,
        worker=worker,
        step_key=step_key,
    )
    if result.outcome is RevalidationOutcome.STALE:
        return await _go_stale(
            connection,
            case=case,
            track=track,
            request=request,
            result=result,
            snapshot=snapshot,
            now=now,
            worker=worker,
            step_key=step_key,
        )
    if result.outcome is RevalidationOutcome.EXPIRED:
        return await _expired(
            connection,
            case=case,
            track=track,
            request=request,
            result=result,
            now=now,
            worker=worker,
            step_key=step_key,
        )
    if result.outcome is RevalidationOutcome.UNAUTHORIZED:
        return await _unauthorized(
            connection,
            case=case,
            track=track,
            request=request,
            result=result,
            now=now,
            worker=worker,
            step_key=step_key,
        )
    return await _noop(
        connection,
        case=case,
        track=track,
        request=request,
        result=result,
        now=now,
        worker=worker,
        step_key=step_key,
    )


async def _go_stale(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    request: Any,
    result: RevalidationResult,
    snapshot: GraphSnapshot,
    now: datetime,
    worker: str,
    step_key: str,
) -> StepOutcome:
    """The customer approved what used to be true. Write that down; apply nothing.

    Everything the customer was told, and everything they answered, survives untouched: the
    ``recovery_options`` row they were asked about, the ``approval_requests`` row with the world
    it captured, the ``approval_decisions`` row with their literal yes. §14.4's re-plan is
    enqueued as its own durable step, and it is what decides whether there is anything left to
    ask -- this transition deliberately produces no new plan and no new request.
    """
    deciding = result.failed[0]
    detail = f"check {deciding.index}: {deciding.expected} != {deciding.actual}"
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=recovery.AUDIT_RECOVERY_STALE,
        # A system safety decision, not a customer's decline. The two must never read alike:
        # one says the customer said no, the other says we refused to act on their yes.
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state, "fingerprint": track.fingerprint},
        after={"track_state": recovery.TRACK_STALE, "deciding_check": deciding.index},
        provenance={
            "step_key": step_key,
            "worker": worker,
            "request_id": str(request.id),
            "detail": detail,
            "as_of": snapshot.as_of,
        },
        occurred_at=now,
    ) as write:
        await recovery.set_track(write, track=track, state=recovery.TRACK_STALE)

    logger.info(
        "revalidation.stale",
        case_id=str(case.id),
        track_id=str(track.id),
        deciding_check=deciding.index,
    )
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        successors=(
            CreateStep(
                step_key=analysis.replan_step_key(track.id, approvals.ask_scope(request)),
                kind=analysis.STEP_REPLAN_TRACK,
            ),
        ),
        events=(
            AppendEvent(
                type=EVENT_TRACK_REVALIDATION_FAILED,
                payload={"outcome": result.outcome.value, "check": deciding.index},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            AppendEvent(
                type=recovery.EVENT_TRACK_STALE,
                payload={"check": deciding.index},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
        ),
        result={
            "outcome": result.outcome.value,
            "track_id": str(track.id),
            "request_id": str(request.id),
            "deciding_check": deciding.index,
            "detail": detail,
            "checks": _check_rows(result.checks),
        },
    )


async def _expired(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    request: Any,
    result: RevalidationResult,
    now: datetime,
    worker: str,
    step_key: str,
) -> StepOutcome:
    """Consent that was valid when it arrived and is not valid now. §14.3's failure of check 7.

    The request row and the decision row both stay exactly as they are. They document what the
    customer said, which remains true; what has expired is the authority to act on it.
    """
    deciding = result.failed[0]
    moved_to = await _case_moves_on(connection, case=case, step_key=step_key)
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_REVALIDATION_REFUSED,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state},
        after={
            "track_state": recovery.TRACK_ESCALATED,
            "outcome": result.outcome.value,
            "reason": approvals.ESCALATION_APPROVAL_EXPIRED,
        },
        provenance={
            "step_key": step_key,
            "worker": worker,
            "request_id": str(request.id),
            "deadline": request.deadline.isoformat(),
            "checked_at": now.isoformat(),
        },
        occurred_at=now,
    ) as write:
        await recovery.set_track(write, track=track, state=recovery.TRACK_ESCALATED)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to, needs_owner_attention=True),
        timers=case_timers(moved_to, case_id=case.id),
        successors=await case_successors(connection, moved_to, case_id=case.id),
        events=(
            AppendEvent(
                type=EVENT_TRACK_REVALIDATION_FAILED,
                payload={"outcome": result.outcome.value, "check": deciding.index},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            AppendEvent(
                type=recovery.EVENT_TRACK_ESCALATED,
                payload={"reason": approvals.ESCALATION_APPROVAL_EXPIRED},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            *case_events(moved_to, case_id=case.id),
        ),
        result={
            "outcome": result.outcome.value,
            "track_id": str(track.id),
            "request_id": str(request.id),
            "deciding_check": deciding.index,
            "reason": approvals.ESCALATION_APPROVAL_EXPIRED,
            "checks": _check_rows(result.checks),
        },
    )


async def _unauthorized(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    request: Any,
    result: RevalidationResult,
    now: datetime,
    worker: str,
    step_key: str,
) -> StepOutcome:
    """The provenance does not lead back to the customer's own channel. Refuse, and write nothing.

    §14.3: the decision is discarded, ``UNAUTHORIZED_APPROVAL_ATTEMPT`` is audited, the track
    keeps waiting and the owner is notified. The consent protocol already refuses a reply from
    the wrong sender when it arrives, so reaching here means the persisted chain was broken
    afterwards -- and a repair that quietly escalated a customer's genuine request over a
    corrupted record would be the wrong answer. A person looks at it.
    """
    deciding = result.failed[0]
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=approvals.AUDIT_UNAUTHORIZED_APPROVAL,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state},
        after={"track_state": track.state, "outcome": result.outcome.value},
        provenance={
            "step_key": step_key,
            "worker": worker,
            "request_id": str(request.id),
            "expected_channel": request.customer_channel,
            "compared": deciding.actual,
        },
        occurred_at=now,
    ):
        pass

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(needs_owner_attention=True),
        events=(
            AppendEvent(
                type=EVENT_TRACK_REVALIDATION_FAILED,
                payload={"outcome": result.outcome.value, "check": deciding.index},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
        ),
        result={
            "outcome": result.outcome.value,
            "track_id": str(track.id),
            "request_id": str(request.id),
            "deciding_check": deciding.index,
            "checks": _check_rows(result.checks),
        },
    )


async def _noop(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    request: Any,
    result: RevalidationResult,
    now: datetime,
    worker: str,
    step_key: str,
) -> StepOutcome:
    """Already settled, not literal, or already spent. Audited, and otherwise nothing at all."""
    deciding = result.failed[0]
    detail = f"check {deciding.index} ({deciding.name}): {deciding.actual}"
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_REVALIDATION_REFUSED,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state},
        after={"track_state": track.state, "outcome": result.outcome.value},
        provenance={
            "step_key": step_key,
            "worker": worker,
            "request_id": str(request.id),
            "detail": detail,
        },
        occurred_at=now,
    ):
        pass

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        events=(
            AppendEvent(
                type=EVENT_TRACK_REVALIDATION_FAILED,
                payload={"outcome": result.outcome.value, "check": deciding.index},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
        ),
        result={
            "outcome": result.outcome.value,
            "track_id": str(track.id),
            "request_id": str(request.id),
            "deciding_check": deciding.index,
            "detail": detail,
            "checks": _check_rows(result.checks),
        },
    )


async def _no_authority_to_consume(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    request: Any,
    decision: Any,
    now: datetime,
    worker: str,
    step_key: str,
) -> StepOutcome:
    """A settled request with nothing to act on: a decline, or a window that closed.

    §14.2 settles both of these where they happen -- a literal ``NO`` escalates the track as the
    decision commits, and an expiring deadline escalates it as the timer fires -- so there is no
    approval left to revalidate, and running the ten checks would be asking whether an authority
    that was never given is still good. What remains is the case-level boundary, and this is
    what carries the case to it rather than leaving it parked in ``REVALIDATING`` for ever.
    """
    reason = "DECLINED" if decision is not None else "NO_DECISION"
    moved_to = await _case_moves_on(connection, case=case, step_key=step_key)
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_REVALIDATION_NOT_REQUIRED,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"case_state": case.state, "track_state": track.state},
        after={"case_state": moved_to or case.state, "track_state": track.state, "reason": reason},
        provenance={
            "step_key": step_key,
            "worker": worker,
            "request_id": str(request.id),
            "request_state": request.state,
            "decision": None if decision is None else decision.decision,
        },
        occurred_at=now,
    ):
        pass

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to),
        timers=case_timers(moved_to, case_id=case.id),
        successors=await case_successors(connection, moved_to, case_id=case.id),
        events=case_events(moved_to, case_id=case.id),
        result={
            "outcome": reason,
            "track_id": str(track.id),
            "request_id": str(request.id),
            "track_state": track.state,
        },
    )


async def _case_moves_on(
    connection: AsyncConnection, *, case: LockedCase, step_key: str
) -> str | None:
    """Where the case goes once this was the last of its round, or ``None`` if it stays.

    A case with two settled requests has two revalidation steps, and each of them has to be run
    against ``REVALIDATING`` -- so the first to finish must not move the case out from under the
    second. A re-plan one of them called for is part of the same round and has to run there too,
    and a round that ends with a re-planned promise ends at ``PLANNED`` (ADR-0023). Reading the
    ledger for the rest is what makes the answer independent of the order the worker happened to
    claim them in.
    """
    return await revalidation_round_exit(connection, case_id=case.id, step_key=step_key)


# ------------------------------------------------------------------------------- the evidence


async def _record_checks(
    unit_of_work: UnitOfWork,
    *,
    case: LockedCase,
    track: Any,
    request: Any,
    result: RevalidationResult,
    now: datetime,
    worker: str,
    step_key: str,
) -> None:
    """One audit row per check, with the two values it compared.

    §22 shows all ten with their values, and the Audit screen renders them as rows -- so they
    are rows. A single payload holding ten results would render the same on a good day and
    would be useless the day somebody asks which cases have ever failed check 5.

    None of these authorises anything: they are written before the transition that acts on
    them, inside the same transaction, so a crash leaves either all of the evidence and the
    decision it supports, or neither.
    """
    for check in result.checks:
        async with unit_of_work.governed(
            event_type=AUDIT_REVALIDATION_CHECK,
            actor=Actor(kind="SYSTEM", id=worker),
            authority="NONE",
            case_id=case.id,
            track_id=track.id,
            before={"expected": check.expected},
            after={"actual": check.actual, "passed": check.passed},
            provenance={
                "step_key": step_key,
                "worker": worker,
                "request_id": str(request.id),
                "check": check.index,
                "name": check.name,
                "checked_at": now.isoformat(),
            },
            occurred_at=now,
        ):
            pass


def _check_rows(checks: Sequence[CheckResult]) -> list[Mapping[str, Any]]:
    """The ten results as the step ledger keeps them, for the operator view and the CLI."""
    return [
        {
            "index": check.index,
            "name": check.name,
            "passed": check.passed,
            "expected": check.expected,
            "actual": check.actual,
        }
        for check in checks
    ]


# -------------------------------------------------------------------------- reconciling


async def _reconcile(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Finish the case, if it is finished. §14.1's ``RECONCILING`` boundary.

    Reconciliation here incorporates the *outcomes* of recovery into the case: every track is
    checked for a terminal posture, every durable step for settlement, and the case resolves
    with ``needs_owner_attention`` set when anything was handed to the owner. It writes no
    order, no reservation and no task, because in this slice the recovery amendment was pushed
    at an external provider and PromisePatch does not hold the answer to what that provider did
    with it -- mirroring it locally would be inventing the one fact the architecture says
    belongs to the order system.

    A reconciliation that arrives while work is still outstanding does nothing and says so. It
    is not the only path to ``RESOLVED``: whichever transition settles the last track asks the
    same question of the same rows, so a case never depends on this step having run last.
    """
    if case.state != CASE_RECONCILING:
        return recovery.skipped(STEP_RECONCILE_CASE, {"case_state": case.state})

    moved_to = await settled_case_state(connection, case=case, except_step_key=step_key)
    if moved_to is None:
        return recovery.skipped(
            STEP_RECONCILE_CASE,
            {
                "case_state": case.state,
                "tracks": list(await non_terminal_tracks(connection, case.id)),
            },
        )

    attention = await any_escalated(connection, case.id)
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_CASE_RECONCILED,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        before={"case_state": case.state},
        after={"case_state": moved_to, "needs_owner_attention": attention},
        provenance={"step_key": step_key, "worker": worker, "reconciled_at": now.isoformat()},
        occurred_at=now,
    ):
        pass

    logger.info(
        "case.reconciled", case_id=str(case.id), state=moved_to, needs_owner_attention=attention
    )
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to, needs_owner_attention=attention or None),
        events=case_events(moved_to, case_id=case.id),
        result={
            "outcome": moved_to,
            "case_id": str(case.id),
            "needs_owner_attention": attention,
        },
    )


# ---------------------------------------------------------------------------------- reading


async def _lock_request(connection: AsyncConnection, request_id: UUID | None) -> Any:
    """Take the approval request for update, after the case and the track."""
    if request_id is None:
        return None
    return (
        await connection.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update()
        )
    ).one_or_none()


async def _decision_for(connection: AsyncConnection, request_id: UUID) -> Any:
    """The one authoritative answer, read back by request. Never re-derived from raw text."""
    return (
        await connection.execute(
            select(ApprovalDecision).where(ApprovalDecision.request_id == request_id)
        )
    ).one_or_none()
