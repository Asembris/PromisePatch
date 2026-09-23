"""Confirming a plan, and executing the recoveries it authorised, as a crash-safe saga.

Five transactions, and the boundaries between them are the whole design. Every one of them
either commits completely or leaves the database exactly as it found it, and the work that
survives each boundary is a row rather than anything a process is holding.

``confirm_plan``
    A worker says yes. One short governed transaction moves the case to ``EXECUTING``,
    escalates the tracks nothing can recover, holds their production tasks, and enqueues one
    ``APPLY_RECOVERY`` step per automatically recoverable track and one ``REQUEST_APPROVAL``
    step per track whose customer has to be asked. **No network call, and no outbound effect.**
    Confirmation authorises later execution; it does not perform any.

``APPLY_RECOVERY``
    A leased, fenced step re-checks that the plan still describes the world, moves the track
    to ``APPLYING`` and enqueues the outbound amendment in the same transaction. Still no
    network call: the effect is a row, and the dispatcher sends it afterwards.

Outbox dispatch
    :mod:`promisepatch.domain.outbox` claims the message, commits that claim, and only then
    calls the provider with no transaction open at all.

``FINALIZE_RECOVERY``
    Enqueued by the delivery acknowledgement itself, so it exists only once the provider's
    acceptance is durable. It proves the acknowledgement from the row -- never from something
    an adapter said in memory -- and, where the provider is a system of record, waits until the
    mirror shows the change that provider says it made. Only then does the track become
    ``RECOVERED``.

``ABANDON_RECOVERY``
    The same shape for the other ending. A delivery that failed terminally escalates its track
    with ``DOWNSTREAM_UNAVAILABLE`` rather than leaving it in ``APPLYING`` for ever, because a
    case must never look like it is still trying when nothing is.

**Confirmation is not blanket authority.** A worker's yes permits exactly the recoveries the
order's own constraints already allow -- §15's "Apply AUTO recovery ... Worker confirms plan".
It does not permit a visible change the customer has not agreed to. What it authorises for an
``APPROVAL_REQUIRED`` track is therefore *asking*, and nothing else: the step it enqueues writes
a durable request and a message, and the track stays ``PENDING`` until the customer has actually
been contacted. Applying that change needs the customer's own literal consent, which is a
different authority, arrives on a different path, and is handled in
:mod:`promisepatch.domain.approvals`.

**Execution consumes the plan; it never re-makes it.** The option applied is the row planning
chose, read back by id. If the world has moved -- the fingerprint no longer matches what was
planned against -- the track goes ``STALE`` and *nothing* is sent. There is deliberately no
branch here that picks a different option, because a plan silently replaced by another plan is
the one failure a worker could not have caught by reading the screen.

**Recovered means observed, not acknowledged.** The order system owns the order; PromisePatch
keeps a mirror of it. An acknowledgement says the order system accepted the amendment, which is
not the same as PromisePatch having seen the result -- and until it has, every read model and
every later plan still describes the order as it was. So a recovery whose provider made an
authoritative statement waits, durably, until the mirror agrees with it. The two orderings that
can happen -- the echo arriving before the acknowledgement, or after it -- converge on one
finish, because both are decided from rows rather than from what arrived first.

**The honest guarantee is unchanged.** At-least-once delivery under a stable idempotency key.
The key is derived once from persisted identity (§12.3) and stored on the outbox row, so every
retry after every crash presents the identical key; whether that becomes one effect or two in
the outside world is the provider's to decide, and never ours to claim.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.fingerprint import fingerprint
from promise_graph.model import (
    ApprovalDecisionKind,
    ApprovalRequestState,
    Classification,
    ParserKind,
)
from promise_graph.snapshot import GraphSnapshot
from promisepatch.db.clock import database_now
from promisepatch.db.events import append_event
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    Case,
    CaseStep,
    Order,
    OrderLine,
    OutboxMessage,
    PlanApproval,
    ProductionTask,
    RecoveryOption,
    Track,
    TrackPath,
    TrackWatch,
)
from promisepatch.db.models import Promise as PromiseRow
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.db.uow import Actor, GovernedWrite, UnitOfWork
from promisepatch.domain import crash, plan_identity, retry
from promisepatch.domain.analysis import fresh_snapshot, scope_from_watch
from promisepatch.domain.cases import (
    CASE_EXECUTING,
    CASE_PLANNED,
    CASE_RECONCILING,
    CASE_REVALIDATING,
    STEP_RECONCILE_CASE,
    TIMER_PLAN_AUTO_ESCALATION,
    TRACK_WAITING_FOR_CUSTOMER,
    LockedCase,
    apply_case_change,
    case_events,
    case_successors,
    lock_case,
    reconcile_step_key,
    revalidate_step_key,
    settled_case_state,
)
from promisepatch.domain.intake import actor_for, require_permitted, require_worker
from promisepatch.domain.model import (
    CASE_SUBJECT,
    EFFECT_TRACK_ID,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_FAILED,
    EVENT_STEP_SKIPPED,
    AppendEvent,
    CaseChange,
    Disposition,
    EmitEffect,
    StepOutcome,
)
from promisepatch.domain.model import (
    EFFECT_ORDER_AMEND as _EFFECT_ORDER_AMEND,
)
from promisepatch.domain.timers import cancel_timer
from promisepatch.observability import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------------------ track states

TRACK_PENDING: Final = "PENDING"
TRACK_APPLYING: Final = "APPLYING"
TRACK_RECOVERED: Final = "RECOVERED"
TRACK_ESCALATED: Final = "ESCALATED"
TRACK_STALE: Final = "STALE"
"""The §13.4 postures a recovery writes.

``WAITING_FOR_CUSTOMER`` is deliberately absent *here*. It names a track whose approval request
has actually been sent, which is a different authority arriving on a different path, and
:mod:`promisepatch.domain.approvals` is the only module that writes it.
"""

# ------------------------------------------------------------------------------- step naming

STEP_CONFIRM_PLAN: Final = "CONFIRM_PLAN"
"""The durable record of one accepted confirmation command. Never claimed, never executed.

Written ``DONE`` inside the confirming transaction, because the work it names is the
transaction itself. Its row is what makes a redelivered command idempotent: ``case_steps.id``
is the caller's own command id, so the second delivery collides on the primary key, and
``request_hash`` then decides whether it was the same request or a different one wearing the
same name.
"""

STEP_APPLY_RECOVERY: Final = "APPLY_RECOVERY"
STEP_FINALIZE_RECOVERY: Final = "FINALIZE_RECOVERY"
STEP_ABANDON_RECOVERY: Final = "ABANDON_RECOVERY"

STEP_ESCALATE_PLAN: Final = "ESCALATE_PLAN"
"""§14.1's ten minutes ran out and no worker said yes. The plan goes to the owner instead.

Created by a ``timers`` row rather than by a sweep, so downtime delays it and never loses it,
and it runs here because what it does to each promise -- hand it to the owner and hold its
kitchen work -- is this module's own vocabulary. It authorises nothing: a plan nobody confirmed
is never executed, and this is the ending that says so rather than a second way to act on one.
"""

RECOVERY_STEP_KINDS: Final[frozenset[str]] = frozenset(
    {STEP_APPLY_RECOVERY, STEP_FINALIZE_RECOVERY, STEP_ABANDON_RECOVERY, STEP_ESCALATE_PLAN}
)

_APPLICABLE_CASE_STATES: Final[frozenset[str]] = frozenset(
    {CASE_EXECUTING, CASE_REVALIDATING, CASE_RECONCILING}
)
"""Case postures in which a recovery step is doing work somebody asked for.

``EXECUTING`` is the automatic path, released by a worker's confirmation. ``RECONCILING`` is the
approved path, released by a revalidation that passed. ``REVALIDATING`` is the same case a
moment earlier, when another track's checks are still outstanding. Everything else -- planned,
waiting, resolved, cancelled -- means the step is describing work on a case that has moved past
it, and it skips rather than amending an order nobody is expecting.
"""
"""Step kinds the worker routes here: each one reads the graph or the outbox to decide."""


def confirm_step_key(command_id: UUID) -> str:
    """The confirmation a command made. Derived from the command, so a retry names the same row."""
    return f"confirm:{command_id}"


def apply_step_key(track_id: UUID) -> str:
    """One application per track, whatever happens to the process that enqueued it."""
    return f"apply:{track_id}"


def finalize_step_key(track_id: UUID) -> str:
    """The completion the delivery acknowledgement makes runnable. Same identity as the apply."""
    return f"finalize:{track_id}"


def abandon_step_key(track_id: UUID) -> str:
    """The other ending, for a delivery that will not be retried again."""
    return f"abandon:{track_id}"


def escalate_plan_step_key(timer_id: UUID) -> str:
    """Derived from the deadline that fired, so firing one twice enqueues one step.

    Keyed on the timer rather than on the case, because a case may legitimately enter
    ``PLANNED`` more than once -- a re-planned track returns it there -- and each wait is its own
    deadline with its own ending. A key derived from the case would let the first wait's step
    silently swallow the second one's.
    """
    return f"plan-escalated:{timer_id}"


def track_of(step_key: str) -> UUID:
    """The track a recovery step is about, read back out of its key."""
    return UUID(step_key.partition(":")[2])


# ------------------------------------------------------------------------------ effect naming

EFFECT_ORDER_AMEND: Final = _EFFECT_ORDER_AMEND
"""The §13.3 outbox kind for a governed recovery amendment pushed at the order system.

Declared in :mod:`promisepatch.domain.model` and re-exported here, so the adapter that sends one
can name it without importing this module -- which reads the database, and which an adapter is
structurally forbidden from reaching.
"""

CONTINUATION: Final = "continuation"
"""Payload key naming the steps that a delivered or terminally failed effect makes runnable.

Stored on the row rather than held by the dispatcher, which is what makes the hand-off
crash-safe: the step that finishes a recovery is enqueued by the same transaction that records
the provider's answer, so there is no window in which the answer is durable and the work it
unblocks has been forgotten.
"""

DELIVERED: Final = "delivered"
FAILED: Final = "failed"


def amend_idempotency_key(*, track_id: UUID, option_id: UUID, order_version: int) -> str:
    """The §12.3 key for an order-system amendment, from persisted identity alone.

    Track, option and the order version the plan was made against -- no attempt number, no
    worker, no clock, no fresh UUID. It is computed once, stored on the outbox row, and every
    later attempt presents the row's key rather than deriving one again, so a retry after any
    crash is the same logical effect and not a second one.
    """
    return f"pp:amend:{track_id}:{option_id}:{order_version}"


# ------------------------------------------------------------------------------- event names

EVENT_EXECUTION_CONFIRMED: Final = "case.execution_confirmed"
EVENT_TRACK_APPLYING: Final = "track.applying"
EVENT_TRACK_RECOVERED: Final = "track.recovered"
EVENT_TRACK_ESCALATED: Final = "track.escalated"
EVENT_TRACK_STALE: Final = "track.stale"
"""Envelopes, not business state.

Each one names the track it is about and says what became of it. The evidence behind that --
which option, against which order version, cited by which rule -- stays in ``tracks``,
``recovery_options`` and the audit ledger, where a reader has to be entitled to look.
"""

# ------------------------------------------------------------------------------- audit types

AUDIT_PLAN_CONFIRMED: Final = "PLAN_CONFIRMED"
AUDIT_RECOVERY_APPLIED: Final = "RECOVERY_APPLIED"
AUDIT_RECOVERY_COMPLETED: Final = "RECOVERY_COMPLETED"
AUDIT_RECOVERY_STALE: Final = "RECOVERY_STALE"
AUDIT_RECOVERY_ABANDONED: Final = "RECOVERY_ABANDONED"
AUDIT_PLAN_AUTO_ESCALATED: Final = "PLAN_AUTO_ESCALATED"

# -------------------------------------------------------------------------- escalation reasons

ESCALATION_BLOCKED: Final = "BLOCKED"
ESCALATION_NO_CHOSEN_OPTION: Final = "NO_CHOSEN_OPTION"
ESCALATION_DOWNSTREAM_UNAVAILABLE: Final = "DOWNSTREAM_UNAVAILABLE"
ESCALATION_MIRROR_NOT_RECONCILED: Final = "MIRROR_NOT_RECONCILED"
ESCALATION_PLAN_STALE: Final = "PLAN_STALE"
ESCALATION_PLAN_UNCONFIRMED: Final = "PLAN_UNCONFIRMED"
"""Why a track was handed to the owner.

Recorded on the audit row and the domain event rather than on ``tracks.reason_detail``, which
already holds the engine's reason for the *classification* -- the thing an operator needs most
when asking why a track escalated at all. Overwriting it would answer the second question by
destroying the answer to the first.
"""


class PlanNotConfirmableError(RuntimeError):
    """The case is not waiting for a plan confirmation."""


class ConfirmationConflictError(RuntimeError):
    """The same command id arrived carrying a different confirmation.

    Two different requests are claiming one identity, and accepting either would silently
    discard the other. The caller has a bug in how it mints command ids.
    """


class StalePlanError(RuntimeError):
    """The plan being confirmed is not the plan this case is currently offering.

    The worker read one thing and said yes to it; the rows now say something else. Between the
    two, a track may have been re-planned against changed stock, a promise may have joined or
    left the untouched band, or another case may have taken one over. Accepting the yes would
    authorise recoveries nobody agreed to, so this fails closed and the surface re-reads the
    case. Nothing about the plan is changed here -- a refused confirmation leaves the case
    exactly where it was, still waiting.
    """


class HumanApprovalMissingError(RuntimeError):
    """Nothing establishes that a human approved this plan, so there is no yes to carry out.

    Raised when a caller asks to confirm a plan that carries no approval row, or names an
    approval belonging to a different case or a different plan. It is not "you got the arguments
    wrong": it is the whole boundary. A surface this system authenticates a *service* on -- the
    MCP tools' intent API -- can consume an approval a person left and can mint none, so for
    that surface this refusal is the normal answer to a plan nobody has agreed to yet.

    Declared here rather than in :mod:`promisepatch.domain.plan_approval` so every refusal a
    confirmation can produce is readable in one place, and so that module can depend on this one
    without this one depending back.
    """


class RecoveryStateError(RuntimeError):
    """A recovery step describes a shape of the world that cannot be true."""


# ------------------------------------------------------------------- confirming a plan


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    """What a confirmation did, in terms a caller can act on.

    ``created`` is false for a redelivery of a confirmation that was already accepted, which is
    a success and not an error: the case was confirmed, exactly once.
    """

    case_id: UUID
    command_id: UUID
    state: str
    created: bool
    confirmed_by: str = ""
    """The worker whose approval this carried out, and on a redelivery the worker the original
    confirmation recorded. Never a caller's claim about who they are -- there is no such claim to
    make, because nothing on the way in carries a person."""
    approved_via: str = ""
    """The channel that authenticated them. Empty only where a confirmation predates this
    column, which is a row written before an approval was a separate thing at all."""
    applying: tuple[UUID, ...] = ()
    escalated: tuple[UUID, ...] = ()
    awaiting_approval: tuple[UUID, ...] = ()


def request_hash(**fields: object) -> str:
    """A stable fingerprint of what a caller asked for. Canonical JSON, sorted keys."""
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


async def confirm_plan(
    database: RuntimeDatabase,
    *,
    case_id: UUID,
    command_id: UUID,
    approval_id: UUID | None,
    plan_id: str,
    correlation_id: UUID | None = None,
) -> ConfirmationResult:
    """Carry out a human's yes to **one specific plan**, and enqueue only what it authorises.

    **There is no ``worker_id`` argument, and that is the point.** Who approved this plan is not
    something a caller states; it is read from the durable approval row
    :mod:`promisepatch.domain.plan_approval` wrote when a person agreed on a channel this system
    authenticated them on. A surface that holds only a service credential can find such a row
    and can create none, so calling this function is carrying out somebody's decision rather
    than making one -- and there is no field anywhere on the path through which a conversation,
    a model or a compromised host could name the person whose yes it is.

    ``approval_id`` is ``None`` when the caller looked and found no approval, and that is a
    refusal rather than an argument error. It is also the *last* thing checked: a caller learns
    that a case does not exist, is not offering a plan, or is offering a different one before it
    learns anything about who has agreed to what, because those are facts about the case and
    this is a fact about authority.

    ``plan_id`` is the identity of the plan the worker was shown -- see
    :mod:`promisepatch.domain.plan_identity` -- and it is checked twice: against the approval,
    which is bound to one exact plan, and against the plan the case is currently offering, under
    the same lock the confirmation is written with. A confirmation that quotes a plan the case
    has moved past is refused rather than applied to whatever is there now, because those are
    different sets of orders and only one of them was read out.

    One transaction, no network call and no outbound effect. What commits is: the case at
    ``EXECUTING``, every blocked track escalated with its production task held, one
    ``APPLY_RECOVERY`` step per automatically recoverable track, the confirmation itself, and
    the audit row that says whose approval it carried out. A process that dies before the commit
    leaves the case ``PLANNED`` with nothing enqueued; one that dies after leaves work another
    worker picks up.
    """
    # The plan is part of the request, so two confirmations of *different* plans under one
    # command id are a conflict rather than a retry -- the same rule intake applies to two
    # different statements claiming one identity. So is the approval: one command id may carry
    # out one person's decision, never two. The approver is not hashed separately because the
    # approval already decides who they are.
    fingerprint_of_request = request_hash(
        case=str(case_id), approval=str(approval_id), plan=plan_id, confirmed=True
    )

    async with database.begin() as connection:
        existing = await _existing_confirmation(connection, command_id, fingerprint_of_request)
        if existing is not None:
            return ConfirmationResult(
                case_id=existing.case_id,
                command_id=command_id,
                state=existing.state,
                created=False,
                confirmed_by=existing.confirmed_by,
                approved_via=existing.approved_via,
            )

    try:
        async with database.begin() as connection:
            outcome = await _confirm(
                connection,
                case_id=case_id,
                command_id=command_id,
                approval_id=approval_id,
                plan_id=plan_id,
                fingerprint_of_request=fingerprint_of_request,
                correlation_id=correlation_id,
            )
            crash.at(crash.BEFORE_CONFIRMATION_COMMIT)
    except IntegrityError:
        # Two identical confirmations raced. Whichever lost reads back what the winner wrote,
        # and the hash still decides whether they were really the same request.
        async with database.begin() as connection:
            existing = await _existing_confirmation(connection, command_id, fingerprint_of_request)
        if existing is None:
            raise
        return ConfirmationResult(
            case_id=existing.case_id,
            command_id=command_id,
            state=existing.state,
            created=False,
            confirmed_by=existing.confirmed_by,
            approved_via=existing.approved_via,
        )

    crash.at(crash.AFTER_CONFIRMATION_COMMIT)
    if not outcome.created:
        return outcome
    logger.info(
        "recovery.plan.confirmed",
        case_id=str(case_id),
        worker=outcome.confirmed_by,
        applying=len(outcome.applying),
        escalated=len(outcome.escalated),
        awaiting_approval=len(outcome.awaiting_approval),
    )
    return outcome


async def _confirm(
    connection: AsyncConnection,
    *,
    case_id: UUID,
    command_id: UUID,
    approval_id: UUID | None,
    plan_id: str,
    fingerprint_of_request: str,
    correlation_id: UUID | None,
) -> ConfirmationResult:
    """The confirming transaction. Lock order: case, tracks, then everything derived.

    The approval is read here, inside the transaction that acts on it, and the worker this
    confirmation is attributed to is taken from that row and from nowhere else.
    """
    case = await lock_case(connection, case_id)

    # Under the lock, and only now. Two deliveries of one command can both pass the check
    # outside it, and the loser would otherwise arrive here to find the case already
    # ``EXECUTING`` and report a wrong-state error for work it had itself asked for.
    settled = await _existing_confirmation(connection, command_id, fingerprint_of_request)
    if settled is not None:
        return ConfirmationResult(
            case_id=settled.case_id,
            command_id=command_id,
            state=settled.state,
            created=False,
            confirmed_by=settled.confirmed_by,
            approved_via=settled.approved_via,
        )

    if case.state != CASE_PLANNED:
        raise PlanNotConfirmableError(f"case {case_id} is {case.state}, not {CASE_PLANNED}")

    tracks = (
        await connection.execute(
            select(Track).where(Track.case_id == case_id).order_by(Track.id).with_for_update()
        )
    ).all()
    # Under the case lock and the track locks, so what is compared is what will be acted on.
    # Recomputed rather than read from a column: the identity is a statement about the rows as
    # they are now, and a stored one would only be a statement about when it was written.
    current = await current_plan_id(connection, case_id=case_id, case_version=case.version)
    if current != plan_id:
        raise StalePlanError(f"case {case_id} is offering a different plan than the one confirmed")

    # Last of the checks, and deliberately. Everything above is a fact about the case, which a
    # caller is owed before it is told anything about who has agreed to what; this is the fact
    # about authority, and it is the one a surface holding only a service credential cannot
    # change by trying again. Read under the lock, so the approval that is spent is the approval
    # that exists at the moment the work is enqueued.
    approval = await _approval(
        connection, approval_id=approval_id, case_id=case_id, plan_id=plan_id
    )
    worker_id = approval.approved_by
    await require_worker(connection, worker_id)
    await require_permitted(connection, case_id=case_id, worker_id=worker_id)
    plan = _partition(tracks)
    now = await database_now(connection)

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_PLAN_CONFIRMED,
        actor=await actor_for(connection, worker_id),
        # A human said yes. This is the one authority in the whole slice that is not the
        # engine's own bookkeeping, and §11.8 names it exactly: recovery authorization is held
        # by worker plan confirmation, and is audited as such.
        authority="HUMAN_APPROVAL",
        case_id=case_id,
        before={"case_state": case.state},
        after={
            "case_state": CASE_EXECUTING,
            "applying": [str(track.id) for track in plan.auto],
            "escalated": {str(track.id): reason for track, reason in plan.escalate},
            "awaiting_approval": [str(track.id) for track in plan.approval],
        },
        provenance={
            "confirmed_by": worker_id,
            "command_id": str(command_id),
            # Whose decision this carried out, and where they were when they made it. Without
            # these two the ledger would say a human approved and leave no way to check it.
            "approval_id": str(approval_id),
            "approved_via": approval.channel,
        },
        correlation_id=correlation_id,
        occurred_at=now,
    ) as write:
        await apply_case_change(
            write,
            case=case,
            change=CaseChange(
                state=CASE_EXECUTING,
                needs_owner_attention=True if plan.escalate else None,
            ),
            now=now,
        )
        held: dict[UUID, tuple[str, ...]] = {}
        for track, _ in plan.escalate:
            await _escalate_track(write, track=track)
            held[track.id] = await hold_tasks(write, track=track, case_id=case_id)

        # §14.1's ten minutes were a limit on this wait, and the wait is over. Cancelled in the
        # same transaction as the yes that ended it, so a deadline and the answer to it cannot
        # be separated by a crash. The firing itself is guarded as well; this is what stops a
        # case that returns to ``PLANNED`` later from inheriting the previous wait's clock.
        await cancel_timer(
            connection,
            kind=TIMER_PLAN_AUTO_ESCALATION,
            subject_type=CASE_SUBJECT,
            subject_id=str(case_id),
        )

        await _record_confirmation(
            connection,
            case_id=case_id,
            command_id=command_id,
            worker_id=worker_id,
            approved_via=approval.channel,
            fingerprint_of_request=fingerprint_of_request,
            plan=plan,
            now=now,
        )
        for track in plan.auto:
            await _enqueue(
                connection,
                case_id=case_id,
                track_id=track.id,
                step_key=apply_step_key(track.id),
                kind=STEP_APPLY_RECOVERY,
            )
        # Deferred: the approval protocol reads this module's fenced track writes, so a
        # module-level import in both directions would be a cycle. This edge runs once per
        # confirmation. What it enqueues is permission to *ask*, never permission to apply.
        from promisepatch.domain.approvals import STEP_REQUEST_APPROVAL, request_step_key

        asked_before = await _tracks_asked_before(connection, plan.approval)
        for track in plan.approval:
            await _enqueue(
                connection,
                case_id=case_id,
                track_id=track.id,
                # ADR-0022: a track's first ask keeps its per-track key; a track asked before
                # was re-planned after §14.4 superseded that request, and this confirmation
                # opens a new episode named by the plan it confirms.
                step_key=request_step_key(track.id, plan_id if track.id in asked_before else None),
                kind=STEP_REQUEST_APPROVAL,
            )
        if not plan.auto and not plan.approval:
            # §14.2: a case with nothing to apply and nobody to ask never waits. It has one
            # thing left to do, which is finish, and that is a row like everything else --
            # otherwise an all-BLOCKED case would sit in ``EXECUTING`` for ever with an empty
            # ledger, looking busy.
            await _enqueue(
                connection,
                case_id=case_id,
                track_id=None,
                step_key=reconcile_step_key(case_id),
                kind=STEP_RECONCILE_CASE,
            )

        # Last: from here the transaction holds the spine's ordering lock, and everything
        # above has already taken every lock this transaction will ever need.
        await append_event(
            connection,
            event_type=EVENT_EXECUTION_CONFIRMED,
            correlation_id=write.correlation_id,
            occurred_at=now,
            case_id=case_id,
            entity_refs=[{"kind": "case", "id": str(case_id)}],
            payload={
                "state": CASE_EXECUTING,
                "confirmed_by": worker_id,
                "applying": len(plan.auto),
                "escalated": len(plan.escalate),
                "awaiting_approval": len(plan.approval),
            },
        )
        for track, reason in plan.escalate:
            await append_event(
                connection,
                event_type=EVENT_TRACK_ESCALATED,
                correlation_id=write.correlation_id,
                occurred_at=now,
                case_id=case_id,
                entity_refs=[{"kind": "track", "id": str(track.id)}],
                payload={
                    "reason": reason,
                    "rule_id": track.rule_id,
                    "tasks_held": len(held.get(track.id, ())),
                },
            )

    return ConfirmationResult(
        case_id=case_id,
        command_id=command_id,
        state=CASE_EXECUTING,
        created=True,
        confirmed_by=worker_id,
        approved_via=approval.channel,
        applying=tuple(track.id for track in plan.auto),
        escalated=tuple(track.id for track, _ in plan.escalate),
        awaiting_approval=tuple(track.id for track in plan.approval),
    )


@dataclass(frozen=True, slots=True)
class _Plan:
    """What a confirmation is about to do to each live track, decided before anything is written."""

    auto: tuple[Any, ...]
    approval: tuple[Any, ...]
    escalate: tuple[tuple[Any, str], ...]


def _partition(tracks: Sequence[Any]) -> _Plan:
    """Sort live tracks into the three things a worker's yes can mean for them.

    A track that is not ``PENDING`` is not live: it is already terminal, already linked to
    another case's, or already being executed, and a confirmation has nothing to say about it.

    An ``AUTO_RECOVERABLE`` track with no chosen option escalates rather than executes. It
    should be unreachable -- planning writes a chosen option for every automatic track -- and
    failing closed on it costs one branch, where guessing an option would cost a customer's
    order.
    """
    auto: list[Any] = []
    approval: list[Any] = []
    escalate: list[tuple[Any, str]] = []
    for track in tracks:
        if track.state != TRACK_PENDING:
            continue
        if track.classification == Classification.AUTO_RECOVERABLE.value:
            if track.chosen_option_id is None:
                escalate.append((track, ESCALATION_NO_CHOSEN_OPTION))
            else:
                auto.append(track)
        elif track.classification == Classification.APPROVAL_REQUIRED.value:
            # Left exactly where planning put it, and given work of a different kind. The
            # customer has not been asked yet, so there is still nothing to wait for; what this
            # worker's yes authorises is the asking.
            approval.append(track)
        else:
            escalate.append((track, ESCALATION_BLOCKED))
    return _Plan(auto=tuple(auto), approval=tuple(approval), escalate=tuple(escalate))


async def _escalate_track(write: GovernedWrite, *, track: Any) -> None:
    """Hand one track to the owner. Fenced on the version this transaction read."""
    result = await write.execute(
        update(Track)
        .where(Track.id == track.id, Track.version == track.version)
        .values(state=TRACK_ESCALATED, version=Track.version + 1)
    )
    if result.rowcount != 1:
        raise RecoveryStateError(f"track {track.id} changed under a held lock")


async def hold_tasks(write: GovernedWrite, *, track: Any, case_id: UUID) -> tuple[str, ...]:
    """Put the kitchen work for a blocked promise on hold, and say which tasks those were.

    §13.5: a blocked track never messages a customer and never touches the order, and this is
    the one write it does perform -- so the kitchen does not start a cake that cannot be
    finished. It is reversible by the owner, and it is authorised by the same confirmation as
    everything else in this transaction (§15, "Hold a production task for a BLOCKED promise").

    Only the lines this track's own evidence reaches. The order may have other lines, and a
    hold on work the exception never touched would be exactly the selective-continuation
    failure the spec forbids.

    **The ``SCHEDULED`` predicate is the contract, not an optimisation.** A hold prevents work
    from starting; it cannot stop work that has started, and a row that said otherwise would
    assert a physical stop nobody performed. It is also the only thing keeping release honest:
    ``withdrawal._release_holds`` restores the literal ``SCHEDULED`` and ``production_tasks``
    remembers no prior state, so a started task held here would come back from a withdrawal
    claiming it had never begun. Started work on a blocked promise is escalated to its owner
    instead, which is true. Do not widen this to ``STARTED`` -- see ADR-0017 and
    ``docs/started-work-contract.md`` for the three changes that would have to land first.
    """
    line_ids = await _affected_lines(write.connection, track=track)
    if not line_ids:
        return ()
    rows = (
        await write.execute(
            update(ProductionTask)
            .where(
                ProductionTask.order_line_id.in_(sorted(line_ids)),
                ProductionTask.state == "SCHEDULED",
            )
            .values(state="HELD", held_by_case_id=case_id)
            .returning(ProductionTask.id)
        )
    ).scalars()
    return tuple(sorted(rows))


async def _affected_lines(connection: AsyncConnection, *, track: Any) -> set[str]:
    """The order lines this track's persisted paths actually arrive at.

    Read from ``track_paths`` rather than recomputed, because the evidence a person can see on
    the screen and the rows a hold is taken against must be the same set or the screen is
    lying.
    """
    rows = (
        await connection.execute(
            select(TrackPath.quantification).where(TrackPath.track_id == track.id)
        )
    ).scalars()
    return {
        str(quantification["order_line_id"])
        for quantification in rows
        if quantification and quantification.get("order_line_id")
    }


async def _record_confirmation(
    connection: AsyncConnection,
    *,
    case_id: UUID,
    command_id: UUID,
    worker_id: str,
    approved_via: str,
    fingerprint_of_request: str,
    plan: _Plan,
    now: datetime,
) -> None:
    """Store the accepted command, keyed on the caller's own identity for it.

    ``id`` is the command id, so a redelivery is a primary-key conflict anywhere in the
    database rather than only within this case, and ``request_hash`` is what tells a retry of
    the same request apart from a different one reusing the name.
    """
    await connection.execute(
        pg_insert(CaseStep).values(
            id=command_id,
            case_id=case_id,
            step_key=confirm_step_key(command_id),
            kind=STEP_CONFIRM_PLAN,
            # Done, because the work this row names is the transaction it is being written in.
            # Nothing will ever claim it; the claim sweep looks only at unsettled rows.
            state="DONE",
            attempts=0,
            request_hash=fingerprint_of_request,
            result={
                "confirmed_by": worker_id,
                "approved_via": approved_via,
                "applying": [str(track.id) for track in plan.auto],
                "escalated": [str(track.id) for track, _ in plan.escalate],
                "awaiting_approval": [str(track.id) for track in plan.approval],
            },
            started_at=now,
            done_at=now,
        )
    )


@dataclass(frozen=True, slots=True)
class _Approval:
    """The durable approval a confirmation is carrying out, as this module needs to read it."""

    id: UUID
    approved_by: str
    channel: str


async def _approval(
    connection: AsyncConnection, *, approval_id: UUID | None, case_id: UUID, plan_id: str
) -> _Approval:
    """The human approval this confirmation claims, checked against what it claims to be for.

    Three things have to agree before a yes is worth anything: the approval exists, it belongs
    to *this* case, and it was given for *this* plan. ``None`` means the caller looked and found
    none, which reaches the same refusal as a mismatch -- there is nothing to tell apart, because
    in both cases nobody has agreed to the plan being confirmed. The case and plan checks are
    what stop an approval being carried from one case to another, or from the plan somebody read
    to the plan the case is offering now -- a caller holding a real approval id for a real case
    still cannot spend it anywhere else.

    Read with a plain ``SELECT`` rather than through
    :mod:`promisepatch.domain.plan_approval`, which depends on this module. The row is the
    authority; reaching it through the module that writes it would be a cycle and would add
    nothing, because there is no rule about an approval that is not stated by its columns.
    """
    row = (
        None
        if approval_id is None
        else (
            await connection.execute(
                select(
                    PlanApproval.id,
                    PlanApproval.case_id,
                    PlanApproval.plan_id,
                    PlanApproval.approved_by,
                    PlanApproval.channel,
                ).where(PlanApproval.id == approval_id)
            )
        ).one_or_none()
    )
    if row is None or row.case_id != case_id or row.plan_id != plan_id:
        raise HumanApprovalMissingError(
            f"approval {approval_id} does not record a human approving this plan on {case_id}"
        )
    return _Approval(id=row.id, approved_by=row.approved_by, channel=row.channel)


@dataclass(frozen=True, slots=True)
class _Existing:
    case_id: UUID
    state: str
    confirmed_by: str
    approved_via: str


async def _existing_confirmation(
    connection: AsyncConnection, command_id: UUID, fingerprint_of_request: str
) -> _Existing | None:
    """Has this exact command already been accepted? Answered from the row it wrote."""
    row = (
        await connection.execute(
            select(
                CaseStep.case_id,
                CaseStep.kind,
                CaseStep.request_hash,
                CaseStep.result,
                Case.state,
            )
            .join(Case, Case.id == CaseStep.case_id)
            .where(CaseStep.id == command_id)
        )
    ).one_or_none()
    if row is None:
        return None
    if row.kind != STEP_CONFIRM_PLAN or row.request_hash != fingerprint_of_request:
        raise ConfirmationConflictError(
            f"command {command_id} was already accepted carrying a different request"
        )
    # Read back from what the original confirmation wrote, rather than recomputed. A redelivery
    # reports the decision that was actually carried out, including whose it was -- which is the
    # only honest answer when the case has since moved on and the plan no longer exists.
    recorded = row.result if isinstance(row.result, dict) else {}
    return _Existing(
        case_id=row.case_id,
        state=row.state,
        confirmed_by=str(recorded.get("confirmed_by", "")),
        approved_via=str(recorded.get("approved_via", "")),
    )


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
    """Run one recovery step against a case whose row this transaction already holds."""
    if kind == STEP_APPLY_RECOVERY:
        return await _apply(connection, case=case, step_key=step_key, now=now, worker=worker)
    if kind == STEP_FINALIZE_RECOVERY:
        return await _finalize(connection, case=case, step_key=step_key, now=now, worker=worker)
    if kind == STEP_ESCALATE_PLAN:
        return await _escalate_plan(
            connection, case=case, step_key=step_key, now=now, worker=worker
        )
    return await _abandon(connection, case=case, step_key=step_key, now=now, worker=worker)


# ------------------------------------------------------------------------- applying a recovery


async def _apply(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Check that the plan still describes the world, then queue its one outbound effect.

    Nothing is sent from here. What commits is the track at ``APPLYING`` and an outbox row, in
    one transaction, so a crash on either side of the commit is recoverable: before it, there
    is no effect and no ``APPLYING`` track; after it, both, and the dispatcher finds the row.
    """
    if case.state not in _APPLICABLE_CASE_STATES:
        return skipped(STEP_APPLY_RECOVERY, {"case_state": case.state})

    track = await lock_track(connection, track_of(step_key))
    option = await chosen_option(connection, track)
    authority = await authorization_for(connection, track=track, option=option)
    if authority is None:
        # Either somebody already moved this track -- reclaimed and applied, escalated,
        # withdrawn -- or nothing in the database permits the change it describes. Both are
        # refusals to apply, and neither is an error: applying anyway would be a second
        # amendment for one plan, or a first one nobody authorised.
        return skipped(
            STEP_APPLY_RECOVERY,
            {"track_state": track.state, "classification": track.classification},
        )
    if option is None:
        return await mark_stale(
            connection,
            case=case,
            track=track,
            now=now,
            worker=worker,
            step_key=step_key,
            detail="the chosen option is gone",
        )

    planned, current = track.fingerprint, await current_fingerprint(connection, track)
    if planned != current:
        return await mark_stale(
            connection,
            case=case,
            track=track,
            now=now,
            worker=worker,
            step_key=step_key,
            detail=f"fingerprint {planned} -> {current}",
        )

    order = await _order_of(connection, track.promise_id)
    key = amend_idempotency_key(
        track_id=track.id, option_id=option.id, order_version=order.external_version
    )
    payload = _amend_payload(track=track, option=option, order=order)

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_RECOVERY_APPLIED,
        # The system executed an action a human already authorised; it did not invent the
        # authorisation. The authority named is what permits this change to this customer's
        # order -- their own literal approval, their own pre-approval, or the policy that
        # authored the variant -- and the worker whose confirmation released it is on the
        # provenance beside it.
        actor=Actor(kind="SYSTEM", id=worker),
        authority=authority.value,
        rule_id=option.approval_rule,
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state, "track_version": track.version},
        after={
            "track_state": TRACK_APPLYING,
            "track_version": track.version + 1,
            "option_id": str(option.id),
            "from_version_id": option.from_version_id,
            "to_version_id": option.to_version_id,
            "idempotency_key": key,
        },
        provenance={
            "step_key": step_key,
            "worker": worker,
            "fingerprint": planned,
            "order_external_version": order.external_version,
            "cited_constraint_ids": list(option.cited_constraint_ids),
            **(await authorization_provenance(connection, track=track, authority=authority)),
        },
        occurred_at=now,
    ) as write:
        await set_track(write, track=track, state=TRACK_APPLYING)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        effects=(EmitEffect(kind=EFFECT_ORDER_AMEND, payload=payload, idempotency_key=key),),
        events=(
            AppendEvent(
                type=EVENT_TRACK_APPLYING,
                payload={"kind": option.kind, "idempotency_key": key},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
        ),
        result={
            "outcome": "APPLYING",
            "track_id": str(track.id),
            "option_id": str(option.id),
            "idempotency_key": key,
            "fingerprint": planned,
            "authority": authority.value,
        },
    )


def _amend_payload(*, track: Any, option: Any, order: Any) -> Mapping[str, Any]:
    """What the order system is being asked to do, and what to do here once it answers.

    Every value is copied from rows that already existed: the option planning chose, and the
    order version it was chosen against. Nothing here selects anything.
    """
    return {
        EFFECT_TRACK_ID: str(track.id),
        "promise_id": track.promise_id,
        "option_id": str(option.id),
        "option_kind": option.kind,
        "order_id": order.id,
        "order_external_id": order.external_id,
        "order_external_version": order.external_version,
        "order_line_id": option.order_line_id,
        "from_version_id": option.from_version_id,
        "to_version_id": option.to_version_id,
        CONTINUATION: {
            DELIVERED: {
                "step_key": finalize_step_key(track.id),
                "kind": STEP_FINALIZE_RECOVERY,
                "track_id": str(track.id),
            },
            FAILED: {
                "step_key": abandon_step_key(track.id),
                "kind": STEP_ABANDON_RECOVERY,
                "track_id": str(track.id),
            },
        },
    }


class Authority(StrEnum):
    """What permits one recovery to touch one customer's order. Read, never assumed.

    The three values are the frozen ``audit_events.authority`` vocabulary, and which of them
    applies is decided by rows: a policy that authored the variant, a constraint this customer
    recorded on this order, or the customer's own literal consent plus a revalidation that
    found the plan still true. There is no fourth, and there is deliberately no "the worker
    said so": a worker's confirmation permits *asking*, and is on the provenance of all three.
    """

    POLICY = "POLICY"
    CONSTRAINT = "CONSTRAINT"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"


async def authorization_for(
    connection: AsyncConnection, *, track: Any, option: Any
) -> Authority | None:
    """What permits applying this track's plan right now, or ``None`` if nothing does.

    Two shapes, and keeping them apart is the whole authority model.

    *Automatic.* A ``PENDING`` track classified ``AUTO_RECOVERABLE`` whose chosen option needs
    no approval. The worker's confirmation released it, and the order's own constraints already
    allowed it.

    *Approved.* A ``WAITING_FOR_CUSTOMER`` track classified ``APPROVAL_REQUIRED`` whose
    ``approval_requests`` row carries exactly one ``APPROVE`` decision from the literal parser
    for **this** option, and whose revalidation has recorded a ``PROCEED``. Each conjunct is a
    row: the request binds the option, the decision binds the request, and the revalidation
    binds the moment. Take any one away and this returns ``None``, so the amendment is refused
    rather than sent.

    A track in any other posture authorises nothing, whatever enqueued the step -- which is what
    makes "a worker's yes never authorises a change a customer has not agreed to" structural
    rather than a matter of which branch ran.
    """
    if option is None:
        return None
    if (
        track.state == TRACK_PENDING
        and track.classification == Classification.AUTO_RECOVERABLE.value
        and not option.requires_approval
    ):
        return Authority.CONSTRAINT if option.cited_constraint_ids else Authority.POLICY
    if (
        track.state == TRACK_WAITING_FOR_CUSTOMER
        and track.classification == Classification.APPROVAL_REQUIRED.value
        and await _approved_and_revalidated(connection, track=track, option=option)
    ):
        return Authority.HUMAN_APPROVAL
    return None


async def _approved_and_revalidated(
    connection: AsyncConnection, *, track: Any, option: Any
) -> bool:
    """The persisted chain from this option back to a customer's word and forward to a PROCEED."""
    request = (
        await connection.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.id == track.approval_request_id,
                ApprovalRequest.track_id == track.id,
                ApprovalRequest.option_id == option.id,
                ApprovalRequest.state == ApprovalRequestState.ANSWERED.value,
                ApprovalRequest.decided.is_(True),
            )
        )
    ).one_or_none()
    if request is None:
        return False

    decision = (
        await connection.execute(
            select(ApprovalDecision).where(
                ApprovalDecision.request_id == request.id,
                ApprovalDecision.decision == ApprovalDecisionKind.APPROVE.value,
                ApprovalDecision.parser == ParserKind.LITERAL.value,
                ApprovalDecision.sender_identity == request.customer_channel,
            )
        )
    ).one_or_none()
    if decision is None:
        return False

    # Deferred for the cycle the confirmation's own import names. The PROCEED that counts is the
    # one recorded for *this* request: a re-asked track also carries its first ask's settled
    # revalidation, and that answer was about a request the customer's current yes is not.
    from promisepatch.domain.approvals import ask_scope

    revalidated = (
        await connection.execute(
            select(CaseStep.result).where(
                CaseStep.case_id == track.case_id,
                CaseStep.step_key == revalidate_step_key(track.id, ask_scope(request)),
                CaseStep.state == "DONE",
            )
        )
    ).one_or_none()
    if revalidated is None or not revalidated.result:
        return False
    return bool(revalidated.result.get("outcome") == "PROCEED")


async def authorization_provenance(
    connection: AsyncConnection, *, track: Any, authority: Authority
) -> Mapping[str, Any]:
    """The chain behind a customer-approved amendment, for the audit row that applies it.

    §46: worker confirmed the plan, customer approved this specific change, revalidation passed.
    An audit row that said only "SYSTEM" would leave a reader unable to answer who permitted the
    only write in the system that touches somebody's order without a person present.
    """
    if authority is not Authority.HUMAN_APPROVAL:
        return {}
    row = (
        await connection.execute(
            select(
                ApprovalDecision.id,
                ApprovalDecision.decision,
                ApprovalDecision.parser,
                ApprovalDecision.sender_identity,
                ApprovalDecision.provider_message_id,
                ApprovalRequest.id.label("request_id"),
            )
            .join(ApprovalRequest, ApprovalRequest.id == ApprovalDecision.request_id)
            # The request the track carries, not every request it ever had: a re-asked track's
            # superseded request keeps its own decision, and that decision authorised nothing.
            .where(
                ApprovalRequest.track_id == track.id,
                ApprovalRequest.id == track.approval_request_id,
            )
        )
    ).one_or_none()
    if row is None:  # pragma: no cover - authorisation proved it a statement ago
        return {}
    return {
        "approval_request_id": str(row.request_id),
        "approval_decision_id": str(row.id),
        "customer_decision": row.decision,
        "parser": row.parser,
        "provider_message_id": row.provider_message_id,
        "sender_identity": row.sender_identity,
    }


async def mark_stale(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    now: datetime,
    worker: str,
    detail: str,
    step_key: str | None = None,
) -> StepOutcome:
    """The plan no longer describes the world. Send nothing, and hand the promise to a person.

    §23: a recovery that has become invalid before execution goes ``STALE`` and nothing is
    written. Nothing is: no amendment reaches the order system, no message reaches a customer,
    and the finding itself is recorded as ``track.stale`` with the two fingerprints that
    disagreed. That is the clause this function has always honoured and still does.

    What §23 puts *after* the arrow -- a re-plan -- belongs to the one path that has the
    machinery for it. ``revalidation`` marks a track ``STALE`` and enqueues ``REPLAN_TRACK`` in
    the same transaction, so it leaves the track in a state something is already coming to carry
    off again. These callers are the confirmation-driven ones, where no such successor exists
    and where deriving one would replace a plan a worker confirmed with a plan nobody has seen,
    applied on a confirmation given for a different one.

    Leaving the track ``STALE`` regardless is what this used to do, and ``STALE`` is not
    terminal: the case could not reconcile, could not resolve, and no timer, step or sweep could
    ever move either of them again, while the screen pointed the owner at a re-planned outcome
    that was never going to exist. So the promise goes to the owner instead, with its kitchen
    work held -- §13.5's answer for a promise the system cannot carry any further on its own,
    and the one write that answer performs. The customer's order is untouched, which is what
    §23's "nothing written" is protecting.
    """
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_RECOVERY_STALE,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state, "fingerprint": track.fingerprint},
        after={"track_state": TRACK_ESCALATED, "reason": ESCALATION_PLAN_STALE},
        provenance={"worker": worker, "detail": detail},
        occurred_at=now,
    ) as write:
        await set_track(write, track=track, state=TRACK_ESCALATED)
        held = await hold_tasks(write, track=track, case_id=case.id)
        moved_to = await settled_case_state(connection, case=case, except_step_key=step_key)
    successors = await case_successors(connection, moved_to, case_id=case.id)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to, needs_owner_attention=True),
        successors=successors,
        events=(
            AppendEvent(
                type=EVENT_TRACK_STALE,
                payload={"detail": detail},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            AppendEvent(
                type=EVENT_TRACK_ESCALATED,
                payload={"reason": ESCALATION_PLAN_STALE, "tasks_held": len(held)},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            *case_events(moved_to, case_id=case.id),
        ),
        result={
            "outcome": "ESCALATED",
            "track_id": str(track.id),
            "detail": detail,
            "reason": ESCALATION_PLAN_STALE,
            "tasks_held": len(held),
        },
    )


# ------------------------------------------------------------------------ finishing a recovery


async def _finalize(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Recover the track, but only against an acknowledgement that is already durable.

    The proof is the outbox row, read back by the key the apply step recorded. An adapter that
    returned successfully in memory proves nothing here: the process could have died before
    that answer was written down, and a track marked ``RECOVERED`` on the strength of it would
    be claiming an effect nobody could show afterwards.
    """
    if case.state not in _APPLICABLE_CASE_STATES:
        return skipped(STEP_FINALIZE_RECOVERY, {"case_state": case.state})

    track = await lock_track(connection, track_of(step_key))
    if track.state != TRACK_APPLYING:
        return skipped(STEP_FINALIZE_RECOVERY, {"track_state": track.state})

    key = await _applied_key(connection, track)
    effect = await _effect_for(connection, key)
    if effect is None or effect.state != "DELIVERED" or effect.provider_ref is None:
        # Fail closed rather than settle. The step was enqueued by a delivery acknowledgement,
        # so this should be unreachable; if it happens, retrying and eventually escalating is
        # the only answer that does not invent a recovery.
        return StepOutcome(
            disposition=Disposition.RETRYING,
            event_type=EVENT_STEP_FAILED,
            error=f"effect {key} is not durably delivered",
        )
    if str(effect.payload.get("option_id")) != str(track.chosen_option_id):
        raise RecoveryStateError(
            f"effect {key} amends option {effect.payload.get('option_id')}, "
            f"but track {track.id} chose {track.chosen_option_id}"
        )

    option = await chosen_option(connection, track)
    outstanding = await mirror_reconciliation(connection, effect=effect, option=option)
    if outstanding is not None:
        return await _await_mirror(
            connection,
            case=case,
            track=track,
            step_key=step_key,
            now=now,
            worker=worker,
            detail=outstanding,
        )
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_RECOVERY_COMPLETED,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="CONSTRAINT" if option and option.cited_constraint_ids else "POLICY",
        rule_id=None if option is None else option.approval_rule,
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state, "track_version": track.version},
        after={
            "track_state": TRACK_RECOVERED,
            "track_version": track.version + 1,
            "provider_ref": effect.provider_ref,
            "idempotency_key": key,
        },
        provenance={"step_key": step_key, "worker": worker, "attempts": effect.attempts},
        occurred_at=now,
    ) as write:
        await set_track(write, track=track, state=TRACK_RECOVERED)
        # After the write, so the answer includes it: this may have been the last runnable
        # piece of work, and the case is then waiting on a customer somebody else contacted --
        # or reconciling, with nothing left but to finish.
        moved_to = await settled_case_state(connection, case=case, except_step_key=step_key)
    successors = await case_successors(connection, moved_to, case_id=case.id)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to),
        successors=successors,
        events=(
            AppendEvent(
                type=EVENT_TRACK_RECOVERED,
                payload={"provider_ref": effect.provider_ref, "attempts": effect.attempts},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            *case_events(moved_to, case_id=case.id),
        ),
        result={
            "outcome": "RECOVERED",
            "track_id": str(track.id),
            "provider_ref": effect.provider_ref,
            "idempotency_key": key,
        },
    )


async def mirror_reconciliation(
    connection: AsyncConnection, *, effect: Any, option: Any
) -> str | None:
    """What still stands between a delivered amendment and a recovery that may claim to be done.

    ``None`` means nothing does. Anything else is a sentence saying which part of the world has
    not caught up yet, and the recovery waits for it.

    **Why waiting is the correct default with a real order system.** The order system owns the
    order; PromisePatch owns a mirror of it. A provider acknowledgement says the order system
    accepted the change -- it does not say PromisePatch has *seen* it, and until it has, every
    read model, every fingerprint and every later plan is still describing the order as it was.
    Marking the track ``RECOVERED`` there would be claiming reconciliation on the strength of a
    message rather than of observed state.

    **Why an effect with no authoritative result reconciles immediately.** Not every provider is
    a system of record. One that merely accepted a call has made no statement there is anything
    to observe, so requiring an echo from it would mean waiting for a message nobody will ever
    send. The presence of ``result`` is what distinguishes the two, and it is on the row, which
    is why the distinction survives a crash.

    Three things are compared, and each is read from a different place on purpose: the order the
    provider says it changed, the version it says that order is now at, and the variant *the
    plan* chose. The last one is the one that matters most -- it ties the mirror to the option a
    worker confirmed and a customer may have approved, not merely to whatever the order system
    most recently said.
    """
    result = effect.result
    if not result:
        return None

    external_id = str(result.get("external_order_id"))
    order = (
        await connection.execute(select(Order).where(Order.external_id == external_id))
    ).one_or_none()
    if order is None:
        return f"no mirrored order for external id {external_id!r}"

    expected_version = int(result.get("external_version", 0))
    if order.external_version < expected_version:
        return (
            f"the mirror of {external_id} is at external version {order.external_version}, "
            f"behind the {expected_version} the order system reported"
        )

    if option is None:
        return "the chosen option is gone"
    line = (
        await connection.execute(select(OrderLine).where(OrderLine.id == option.order_line_id))
    ).one_or_none()
    if line is None:
        return f"no mirrored line {option.order_line_id!r}"
    if line.recipe_version_id != option.to_version_id:
        return (
            f"the mirror pins line {option.order_line_id} to {line.recipe_version_id}, "
            f"not the {option.to_version_id} this recovery applied"
        )
    return None


async def _await_mirror(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    step_key: str,
    now: datetime,
    worker: str,
    detail: str,
) -> StepOutcome:
    """Wait for the order system's own account of the change, durably and with a bound.

    Waiting is a ``next_attempt_at`` on the step row, so a process that dies while waiting loses
    nothing and no worker holds anything in memory. The event that ends the wait arrives on a
    completely separate path -- a signed webhook, the inbox, the mirror -- so the two orderings
    converge on the same finish: an echo that arrives before the acknowledgement finds this step
    reconciling on its first attempt, and one that arrives after finds it on a later one.

    The bound is what stops a track sitting in ``APPLYING`` for ever when the echo never comes.
    A recovery that cannot be observed is not a recovery, so it is handed to the owner with the
    reason spelled out rather than left looking as though it were still trying.
    """
    if not retry.is_exhausted(await _attempts_of(connection, case.id, step_key)):
        return StepOutcome(
            disposition=Disposition.RETRYING,
            event_type=EVENT_STEP_FAILED,
            error=f"awaiting the order system's own account of this change: {detail}",
        )

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_RECOVERY_ABANDONED,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state, "track_version": track.version},
        after={
            "track_state": TRACK_ESCALATED,
            "track_version": track.version + 1,
            "reason": ESCALATION_MIRROR_NOT_RECONCILED,
        },
        provenance={"step_key": step_key, "worker": worker, "detail": detail},
        occurred_at=now,
    ) as write:
        await set_track(write, track=track, state=TRACK_ESCALATED)
        moved_to = await settled_case_state(connection, case=case, except_step_key=step_key)
    successors = await case_successors(connection, moved_to, case_id=case.id)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to, needs_owner_attention=True),
        successors=successors,
        events=(
            AppendEvent(
                type=EVENT_TRACK_ESCALATED,
                payload={"reason": ESCALATION_MIRROR_NOT_RECONCILED},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            *case_events(moved_to, case_id=case.id),
        ),
        result={
            "outcome": "ESCALATED",
            "track_id": str(track.id),
            "reason": ESCALATION_MIRROR_NOT_RECONCILED,
            "detail": detail,
        },
    )


async def _attempts_of(connection: AsyncConnection, case_id: UUID, step_key: str) -> int:
    """How many times this step has been claimed, read from the row this transaction holds.

    Read rather than passed in, because the executor contract deliberately gives a step the
    world it locked and not the bookkeeping of its own claim. One statement against a row
    already locked by this transaction is cheaper than widening that contract for one caller.
    """
    attempts = (
        await connection.execute(
            select(CaseStep.attempts).where(
                CaseStep.case_id == case_id, CaseStep.step_key == step_key
            )
        )
    ).scalar_one_or_none()
    return int(attempts or 1)


async def _abandon(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """The amendment will not be retried again. Escalate rather than keep claiming to be busy.

    §11.6: after the retry bound the track escalates with ``DOWNSTREAM_UNAVAILABLE`` and the
    case carries on with its other tracks. It never reports a success it did not observe.
    """
    track = await lock_track(connection, track_of(step_key))
    if track.state != TRACK_APPLYING:
        return skipped(STEP_ABANDON_RECOVERY, {"track_state": track.state})

    key = await _applied_key(connection, track)
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_RECOVERY_ABANDONED,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state, "track_version": track.version},
        after={
            "track_state": TRACK_ESCALATED,
            "track_version": track.version + 1,
            "reason": ESCALATION_DOWNSTREAM_UNAVAILABLE,
        },
        provenance={"step_key": step_key, "worker": worker, "idempotency_key": key},
        occurred_at=now,
    ) as write:
        await set_track(write, track=track, state=TRACK_ESCALATED)
        moved_to = await settled_case_state(connection, case=case, except_step_key=step_key)
    successors = await case_successors(connection, moved_to, case_id=case.id)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to, needs_owner_attention=True),
        successors=successors,
        events=(
            AppendEvent(
                type=EVENT_TRACK_ESCALATED,
                payload={"reason": ESCALATION_DOWNSTREAM_UNAVAILABLE},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            *case_events(moved_to, case_id=case.id),
        ),
        result={
            "outcome": "ESCALATED",
            "track_id": str(track.id),
            "reason": ESCALATION_DOWNSTREAM_UNAVAILABLE,
        },
    )


# ------------------------------------------------------------------- the plan window closes


async def _escalate_plan(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """§14.1's ten minutes passed and nobody confirmed the plan. It goes to the owner.

    The confirmation gate is not being removed here and nothing is executed on the strength of
    this: a plan no worker said yes to is never applied, no customer is asked anything, and no
    order is touched. What ends is the *waiting*. §14.1 defines ``PLANNED`` as awaiting a
    worker's yes and bounds that wait at ten minutes, and ``ARCHITECTURE_PLAN`` makes the bound
    a persisted ``timers`` row rather than a nicety. Without it a case whose worker never
    reopened it would wait for a person for ever, and the promises in it would stop moving with
    no deadline, no escalation and nobody told.

    Every live track goes, because the thing that expired is the plan rather than any one track
    of it. Each takes §13.5's hold with it: the kitchen is not asked to carry on with work whose
    recovery this case has just stopped being able to authorise, which is the same reason
    §13.6's closed window and §23's unanswered deadline both hold.

    ``TIMER_NOOP`` in §11.5's sense: a deadline for a plan somebody already confirmed, withdrew
    or replaced changes nothing, and the case's own state is what says so.
    """
    if case.state != CASE_PLANNED:
        return skipped(STEP_ESCALATE_PLAN, {"case_state": case.state})

    tracks = (
        await connection.execute(
            select(Track)
            .where(Track.case_id == case.id, Track.state == TRACK_PENDING)
            .order_by(Track.id)
            .with_for_update()
        )
    ).all()
    if not tracks:
        # A planned case with nothing live is a shape the planner does not produce. Refusing to
        # invent an ending for it costs one branch; guessing would move a case on no evidence.
        return skipped(STEP_ESCALATE_PLAN, {"live_tracks": 0})

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_PLAN_AUTO_ESCALATED,
        # A deadline passing, authorised by nobody. In particular *not* by the worker whose yes
        # this is the absence of: recording a human authority here would make a plan nobody read
        # look like a plan somebody accepted.
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        before={"case_state": case.state, "live_tracks": [str(track.id) for track in tracks]},
        after={
            "case_state": CASE_RECONCILING,
            "track_state": TRACK_ESCALATED,
            "reason": ESCALATION_PLAN_UNCONFIRMED,
        },
        provenance={"step_key": step_key, "worker": worker},
        occurred_at=now,
    ) as write:
        held: dict[UUID, tuple[str, ...]] = {}
        for track in tracks:
            await _escalate_track(write, track=track)
            held[track.id] = await hold_tasks(write, track=track, case_id=case.id)
    successors = await case_successors(connection, CASE_RECONCILING, case_id=case.id)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=CASE_RECONCILING, needs_owner_attention=True),
        successors=successors,
        events=(
            *(
                AppendEvent(
                    type=EVENT_TRACK_ESCALATED,
                    payload={
                        "reason": ESCALATION_PLAN_UNCONFIRMED,
                        "rule_id": track.rule_id,
                        "tasks_held": len(held[track.id]),
                    },
                    entity_refs=({"kind": "track", "id": str(track.id)},),
                )
                for track in tracks
            ),
            *case_events(CASE_RECONCILING, case_id=case.id),
        ),
        result={
            "outcome": "ESCALATED",
            "reason": ESCALATION_PLAN_UNCONFIRMED,
            "tracks": [str(track.id) for track in tracks],
            "tasks_held": sum(len(ids) for ids in held.values()),
            "case_state": CASE_RECONCILING,
        },
    )


# ---------------------------------------------------------------------------------- reading


async def lock_track(connection: AsyncConnection, track_id: UUID) -> Any:
    """Take the track row for update. After the case row, and before anything derived from it."""
    row = (
        await connection.execute(select(Track).where(Track.id == track_id).with_for_update())
    ).one_or_none()
    if row is None:
        raise RecoveryStateError(f"track {track_id} does not exist")
    return row


async def chosen_option(connection: AsyncConnection, track: Any) -> Any:
    """The option planning chose, read back by id. Nothing here selects among candidates."""
    if track.chosen_option_id is None:
        return None
    return (
        await connection.execute(
            select(RecoveryOption).where(
                RecoveryOption.id == track.chosen_option_id,
                RecoveryOption.track_id == track.id,
            )
        )
    ).one_or_none()


async def current_plan_id(connection: AsyncConnection, *, case_id: UUID, case_version: int) -> str:
    """The identity of the plan this case is offering right now, from the rows themselves.

    The other producer of the same value is
    :func:`promisepatch.domain.analysis.plan_entry_of`, which builds it out of the read model a
    surface was shown. Two producers is deliberate: the read is a query with joins and the
    confirmation is a locked scan, and a shared query would make the comparison a comparison of
    one read with itself. What they share is the shape, and a test drives both.
    """
    rows = (
        await connection.execute(
            select(
                Track.id,
                Track.state,
                Track.classification,
                Track.chosen_option_id,
                Track.fingerprint,
                RecoveryOption.to_version_id,
            )
            .outerjoin(
                RecoveryOption,
                (RecoveryOption.id == Track.chosen_option_id)
                & (RecoveryOption.track_id == Track.id),
            )
            .where(Track.case_id == case_id)
        )
    ).all()
    return plan_identity.plan_id(
        case_id=str(case_id),
        case_version=case_version,
        entries=[
            plan_identity.PlanEntry(
                track_id=str(row.id),
                track_state=row.state,
                classification=row.classification,
                chosen_option_id=(
                    None if row.chosen_option_id is None else str(row.chosen_option_id)
                ),
                to_version_id=row.to_version_id,
                fingerprint=row.fingerprint,
            )
            for row in rows
        ],
    )


async def current_fingerprint(
    connection: AsyncConnection, track: Any, *, snapshot: GraphSnapshot | None = None
) -> str:
    """Recompute this track's fingerprint over the state it is watching, as it stands now.

    The scope is rebuilt from the persisted ``track_watch`` rows rather than by re-running
    propagation, so the entities compared are exactly the ones planning declared -- and a
    change outside them is irrelevant by definition rather than by assumption.

    A caller that has already loaded a snapshot passes it in. Loading a second one would be a
    second read of the graph at a second instant, and a comparison made across two instants
    proves nothing about either.
    """
    rows = (
        await connection.execute(
            select(TrackWatch.entity_type, TrackWatch.entity_id).where(
                TrackWatch.track_id == track.id
            )
        )
    ).all()
    scope = scope_from_watch(
        [(row.entity_type, row.entity_id) for row in rows], promise_id=track.promise_id
    )
    return fingerprint(snapshot or await fresh_snapshot(connection), scope).hash


async def _order_of(connection: AsyncConnection, promise_id: str) -> Any:
    """The mirrored order behind a promise. Its version is part of the effect's identity."""
    row = (
        await connection.execute(
            select(Order)
            .join(PromiseRow, PromiseRow.order_id == Order.id)
            .where(PromiseRow.id == promise_id)
        )
    ).one_or_none()
    if row is None:
        raise RecoveryStateError(f"promise {promise_id} has no mirrored order")
    return row


async def _applied_key(connection: AsyncConnection, track: Any) -> str:
    """The idempotency key the apply step recorded, read back rather than derived again.

    Deriving it a second time would reach for the order's *current* version, and a plan whose
    order has moved would produce a different key for the same logical recovery -- which is
    precisely the mistake the persisted key exists to prevent.
    """
    row = (
        await connection.execute(
            select(CaseStep.result).where(
                CaseStep.case_id == track.case_id,
                CaseStep.step_key == apply_step_key(track.id),
            )
        )
    ).one_or_none()
    key = None if row is None or not row.result else row.result.get("idempotency_key")
    if not key:
        raise RecoveryStateError(f"track {track.id} has no applied effect to finish")
    return str(key)


async def _effect_for(connection: AsyncConnection, idempotency_key: str) -> Any:
    return (
        await connection.execute(
            select(OutboxMessage).where(OutboxMessage.idempotency_key == idempotency_key)
        )
    ).one_or_none()


# ---------------------------------------------------------------------------------- writing


async def set_track(
    write: GovernedWrite, *, track: Any, state: str | None = None, **values: Any
) -> None:
    """One row, or this transaction does not commit.

    The version this transaction read is repeated as a predicate. A worker whose lease expired
    and was reclaimed while it worked matches nothing here, so it overwrites nothing.

    ``state`` is optional because not every consequential change to a track is a change of
    posture: binding a track to the approval request just created for it moves nothing in
    §13.4 and still has to be fenced and versioned like everything else.
    """
    changes: dict[str, Any] = {"version": Track.version + 1, **values}
    if state is not None:
        changes["state"] = state
    result = await write.execute(
        update(Track).where(Track.id == track.id, Track.version == track.version).values(**changes)
    )
    if result.rowcount != 1:
        raise RecoveryStateError(
            f"track {track.id} changed under a held lock; expected version {track.version}"
        )


async def _tracks_asked_before(connection: AsyncConnection, tracks: Sequence[Any]) -> set[UUID]:
    """Which of these tracks already have an approval request, superseded or not.

    Read under the track locks the confirmation holds. A confirmed case returns to ``PLANNED``
    only through a re-plan that supersedes the request it replaces, so a track with no request
    here is being asked for the first time and a track with one is being asked again.
    """
    if not tracks:
        return set()
    rows = await connection.execute(
        select(ApprovalRequest.track_id)
        .where(ApprovalRequest.track_id.in_([track.id for track in tracks]))
        .distinct()
    )
    return set(rows.scalars())


async def _enqueue(
    connection: AsyncConnection, *, case_id: UUID, track_id: UUID | None, step_key: str, kind: str
) -> None:
    """Create a recovery step, or do nothing because it already exists.

    Its own insert rather than :func:`~promisepatch.domain.steps.enqueue_step` because a
    recovery step names the track it is about, and a step ledger that could not say which
    promise a piece of work belonged to would be unreadable on the evidence screen.
    """
    await connection.execute(
        pg_insert(CaseStep)
        .values(
            id=uuid4(),
            case_id=case_id,
            track_id=track_id,
            step_key=step_key,
            kind=kind,
            state="PENDING",
            attempts=0,
        )
        .on_conflict_do_nothing(index_elements=[CaseStep.case_id, CaseStep.step_key])
    )


def skipped(kind: str, because: Mapping[str, Any]) -> StepOutcome:
    return StepOutcome(
        disposition=Disposition.SKIPPED,
        event_type=EVENT_STEP_SKIPPED,
        result={"outcome": "NOT_APPLICABLE", "kind": kind, **because},
    )
