"""A worker withdrawing an exception they no longer stand behind. The fifth intent.

**It stops future work. It never reverses the past, and it never reverses a fact.**

§14.1 gives this operation two paths and nothing in between, decided by one question -- has this
case already done something a customer can feel?

* **Nothing consequential yet.** Every live track is ``WITHDRAWN``, the work that had not run
  yet is stood down, and the case reaches ``CANCELLED``, which is terminal.
* **Something already applied.** The reversible writes are reversed -- the production holds this
  case took, and the requests and effects that had not gone out -- every live track is
  ``ESCALATED`` so the owner knows what is on their desk, and the case reaches the reconciling
  boundary, which finishes it at ``RESOLVED`` carrying ``needs_owner_attention``.

*Consequential* is ARCHITECTURE_PLAN §11.8's definition read off the database rather than
restated: a write that touches a customer promise -- an order amendment, a message a customer
has actually received, a production task this case put on hold. It is deliberately **not** the
physical fact. Facts and recovery authorisation are separate authorities (§11.8), so a
withdrawal leaves ``exception_facts``, the settled commitment lines and the inventory ledger
exactly where they are. The raspberries that did not arrive still did not arrive. Only a later
correcting attestation changes that, through its own intent, with its own audit event -- and
this module cannot reach one.

**Nothing here claims an external effect was undone.** An amendment the order system already
accepted, and a message a customer already has, are reported as *applied*, and the track that
caused them is handed to the owner. There is no branch that recalls a sent message and none
that reverses an amendment, because neither is a thing this system can do and reporting it
would be the exact lie the product exists not to tell.

**A customer's own decision survives.** A decided approval request is left untouched: their
literal yes or no is a thing they said, and a worker withdrawing their own exception does not
get to unsay it.

**Fail-closed everywhere it can be asked twice.** A withdrawal of a terminal case is refused;
one quoting a command id already spent on a different request is a conflict rather than a
retry; a redelivery of the same request is a success that writes nothing a second time. All of
it decides under the case lock, so a withdrawal racing a worker's step serialises against it
rather than interleaving with it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.model import ApprovalRequestState
from promisepatch.db.clock import database_now
from promisepatch.db.events import append_event
from promisepatch.db.models import (
    ApprovalRequest,
    Case,
    CaseStep,
    OutboxMessage,
    ProductionTask,
    Track,
)
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.db.types import TERMINAL_TRACK_STATES
from promisepatch.db.uow import GovernedWrite, UnitOfWork
from promisepatch.domain.cases import (
    CASE_RECONCILING,
    STEP_RECONCILE_CASE,
    TIMER_PLAN_AUTO_ESCALATION,
    apply_case_change,
    lock_case,
    reconcile_step,
)
from promisepatch.domain.intake import actor_for, require_permitted, require_worker
from promisepatch.domain.model import (
    CASE_SUBJECT,
    EFFECT_ORDER_AMEND,
    TERMINAL_CASE_STATES,
    CaseChange,
)
from promisepatch.domain.timers import cancel_timer
from promisepatch.observability import get_logger

logger = get_logger(__name__)

CASE_CANCELLED: Final = "CANCELLED"
"""§14.1: "retracted before any consequential write", and terminal."""

TRACK_WITHDRAWN: Final = "WITHDRAWN"
TRACK_ESCALATED: Final = "ESCALATED"

STEP_WITHDRAW_EXCEPTION: Final = "WITHDRAW_EXCEPTION"
"""The accepted-command row a withdrawal writes, keyed on the caller's own command id.

Stored as a ``DONE`` step for the same reason a confirmation is: the work the row names is the
transaction it is written in, so nothing will ever claim it, and a redelivery is a primary-key
conflict anywhere in the database rather than only within this case.
"""

UNSETTLED_STEP_STATES: Final[tuple[str, ...]] = ("PENDING", "RETRYING")
"""Step postures a withdrawal may stand down, because nobody has claimed them.

``IN_FLIGHT`` is absent deliberately. A claimed step is owned by a worker running it right now;
this transaction holds the case row that worker will need, so it settles *after* the withdrawal
commits, finds a terminal or reconciling case, and declines on its own terms. Reaching into it
here would be two writers on one row.
"""

ESCALATION_WITHDRAWN_AFTER_EFFECTS: Final = "WITHDRAWN_AFTER_EFFECTS"
"""Why a track is on the owner's desk: the worker withdrew after something had already gone out."""

WITHDRAWN_BY_WORKER: Final = "WITHDRAWN_BY_WORKER"
"""Why a track stopped when nothing had gone out. Not an escalation; nobody has to do anything."""

EVENT_EXCEPTION_WITHDRAWN: Final = "case.exception_withdrawn"
EVENT_TRACK_WITHDRAWN: Final = "track.withdrawn"
EVENT_TRACK_ESCALATED: Final = "track.escalated"

AUDIT_EXCEPTION_WITHDRAWN: Final = "EXCEPTION_WITHDRAWN"


def withdraw_step_key(command_id: UUID) -> str:
    """One withdrawal per command id, so a redelivery collides rather than repeating."""
    return f"withdraw:{command_id}"


# --------------------------------------------------------------------------------- refusals


class CaseNotWithdrawableError(RuntimeError):
    """The case has already finished, so there is no future work to stop.

    Refused rather than treated as a no-op success: a caller told "withdrawn" about a case that
    resolved an hour ago would believe something had been stopped that had already happened.
    """


class WithdrawalConflictError(RuntimeError):
    """The same command id arrived carrying a different request.

    Two different requests are claiming one identity, and accepting either would silently
    discard the other. The caller has a bug in how it mints command ids.
    """


class WithdrawalStateError(RuntimeError):
    """A row moved under a lock this transaction was holding. Nothing commits."""


# ------------------------------------------------------------------------------- what it did


class ReversalKind(StrEnum):
    """A thing this withdrawal actually stood down. Every one of them was still in the future."""

    TASK_HOLD = "TASK_HOLD"
    """A production task this case had put on hold, released back to the kitchen."""

    OPEN_REQUEST = "OPEN_REQUEST"
    """An approval request superseded, so nothing it carries authorises anything any more."""

    UNSENT_EFFECT = "UNSENT_EFFECT"
    """An order amendment or message that was queued and that nobody had dispatched."""

    PLANNED_WORK = "PLANNED_WORK"
    """A step that was enqueued and unclaimed. It will not run."""


class AppliedKind(StrEnum):
    """A thing that had already happened. None of these is reversed, and none is reported as."""

    ORDER_AMENDED = "ORDER_AMENDED"
    """The external order system accepted an amendment. It is the system of record; it stands."""

    CUSTOMER_ASKED = "CUSTOMER_ASKED"
    """A request reached a customer. A sent message cannot be unsent."""

    EFFECT_IN_FLIGHT = "EFFECT_IN_FLIGHT"
    """A dispatcher holds this effect right now. Whether it lands is not knowable here."""


@dataclass(frozen=True, slots=True)
class WithdrawalResult:
    """What a withdrawal stopped, what it could not stop, and where the case ended up.

    ``created`` is false for a redelivery of a withdrawal already accepted, which is a success
    and not an error: the case was withdrawn, exactly once.

    ``applied`` is the half a caller must never round down. Each entry is something a customer
    or an order system already has, and the count beside it is how many -- so a surface can say
    "one order was already changed" rather than implying the withdrawal caught everything.
    """

    case_id: UUID
    command_id: UUID
    state: str
    created: bool
    withdrawn: tuple[UUID, ...] = ()
    escalated: tuple[UUID, ...] = ()
    reversals: tuple[tuple[ReversalKind, int], ...] = ()
    applied: tuple[tuple[AppliedKind, int], ...] = ()

    @property
    def had_applied_effects(self) -> bool:
        """Whether anything had already reached a customer or the order system."""
        return bool(self.applied)


def request_hash(**fields: object) -> str:
    """A stable fingerprint of what a caller asked for. Canonical JSON, sorted keys."""
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


# ----------------------------------------------------------------------------- the operation


async def withdraw_exception(
    database: RuntimeDatabase,
    *,
    case_id: UUID,
    command_id: UUID,
    worker_id: str,
    correlation_id: UUID | None = None,
) -> WithdrawalResult:
    """Withdraw one exception on a worker's own authority, and report honestly what that cost.

    One transaction, no network call and no outbound effect of its own. What commits is the case
    at ``CANCELLED`` or at the reconciling boundary, every live track settled, the reversible
    writes reversed, the accepted command, and the audit row naming who withdrew it. A process
    that dies before the commit leaves the case exactly as it was.
    """
    fingerprint_of_request = request_hash(case=str(case_id), worker=worker_id, withdrawn=True)

    async with database.begin() as connection:
        existing = await _existing_withdrawal(connection, command_id, fingerprint_of_request)
        if existing is not None:
            return WithdrawalResult(
                case_id=existing.case_id,
                command_id=command_id,
                state=existing.state,
                created=False,
            )

    try:
        async with database.begin() as connection:
            outcome = await _withdraw(
                connection,
                case_id=case_id,
                command_id=command_id,
                worker_id=worker_id,
                fingerprint_of_request=fingerprint_of_request,
                correlation_id=correlation_id,
            )
    except IntegrityError:
        # Two identical withdrawals raced. Whichever lost reads back what the winner wrote, and
        # the hash still decides whether they were really the same request.
        async with database.begin() as connection:
            existing = await _existing_withdrawal(connection, command_id, fingerprint_of_request)
        if existing is None:
            raise
        return WithdrawalResult(
            case_id=existing.case_id,
            command_id=command_id,
            state=existing.state,
            created=False,
        )

    if outcome.created:
        logger.info(
            "withdrawal.accepted",
            case_id=str(case_id),
            worker=worker_id,
            state=outcome.state,
            withdrawn=len(outcome.withdrawn),
            escalated=len(outcome.escalated),
            applied=len(outcome.applied),
        )
    return outcome


async def _withdraw(
    connection: AsyncConnection,
    *,
    case_id: UUID,
    command_id: UUID,
    worker_id: str,
    fingerprint_of_request: str,
    correlation_id: UUID | None,
) -> WithdrawalResult:
    """The withdrawing transaction. Lock order: worker, case, tracks, then everything derived."""
    await require_worker(connection, worker_id)
    case = await lock_case(connection, case_id)

    # Under the lock, and only now. Two deliveries of one command can both pass the check
    # outside it, and the loser would otherwise arrive here to find the case already terminal
    # and report a wrong-state error for work it had itself asked for.
    settled = await _existing_withdrawal(connection, command_id, fingerprint_of_request)
    if settled is not None:
        return WithdrawalResult(
            case_id=settled.case_id, command_id=command_id, state=settled.state, created=False
        )

    if case.state in TERMINAL_CASE_STATES:
        raise CaseNotWithdrawableError(f"case {case_id} is {case.state} and has already finished")
    await require_permitted(connection, case_id=case_id, worker_id=worker_id)

    tracks = (
        await connection.execute(
            select(Track).where(Track.case_id == case_id).order_by(Track.id).with_for_update()
        )
    ).all()
    live = tuple(track for track in tracks if track.state not in TERMINAL_TRACK_STATES)

    applied = await _applied_effects(connection, case_id)
    holds = await _held_tasks(connection, case_id)
    requests = await _open_requests(connection, case_id)
    unsent = await _unsent_effects(connection, case_id)
    now = await database_now(connection)

    # ARCHITECTURE_PLAN §11.8, read off rows: a write that touches a customer promise. An effect
    # a customer or the order system already has, or a production hold this case took. A queued
    # effect nobody dispatched is not one of those -- it is exactly what this operation exists
    # to stop.
    consequential = bool(applied) or bool(holds)
    destination = CASE_RECONCILING if consequential else CASE_CANCELLED
    track_state = TRACK_ESCALATED if consequential else TRACK_WITHDRAWN

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_EXCEPTION_WITHDRAWN,
        actor=await actor_for(connection, worker_id),
        # A human said no. The same authority that confirms a plan, exercised the other way:
        # recovery authorisation is held by the worker, and withdrawing it is that authority
        # being used rather than absent.
        authority="HUMAN_APPROVAL",
        case_id=case_id,
        before={"case_state": case.state, "live_tracks": [str(track.id) for track in live]},
        after={
            "case_state": destination,
            "track_state": track_state,
            "reversed": {
                ReversalKind.TASK_HOLD.value: len(holds),
                ReversalKind.OPEN_REQUEST.value: len(requests),
                ReversalKind.UNSENT_EFFECT.value: len(unsent),
            },
            "applied": [
                {"effect": str(effect_id), "kind": kind, "state": state}
                for effect_id, kind, state in applied
            ],
        },
        provenance={"withdrawn_by": worker_id, "command_id": str(command_id)},
        correlation_id=correlation_id,
        occurred_at=now,
    ) as write:
        await apply_case_change(
            write,
            case=case,
            change=CaseChange(
                state=destination,
                needs_owner_attention=True if consequential else None,
            ),
            now=now,
        )
        for track in live:
            await _settle_track(write, track=track, state=track_state)
        for request_id in requests:
            await _supersede_request(write, request_id=request_id)
        released = await _release_holds(write, case_id=case_id, tasks=holds)
        stood_down = await _refuse_unsent(write, effects=unsent, worker_id=worker_id)
        planned = await _stand_down_steps(write, case_id=case_id, command_id=command_id)
        # Nothing is waiting for a confirmation any more, so §14.1's limit on that wait
        # goes with it: a case that stood down must not be escalated later by a deadline
        # for a plan it withdrew.
        await cancel_timer(
            connection,
            kind=TIMER_PLAN_AUTO_ESCALATION,
            subject_type=CASE_SUBJECT,
            subject_id=str(case_id),
        )

        await _record_withdrawal(
            connection,
            case_id=case_id,
            command_id=command_id,
            worker_id=worker_id,
            fingerprint_of_request=fingerprint_of_request,
            destination=destination,
            now=now,
        )
        if consequential:
            # The reconciling boundary needs something enqueued to carry the case off it, or a
            # withdrawn case would sit there for ever looking busy. The reconciler is the step
            # that already knows how to finish one.
            await _enqueue_reconcile(connection, case_id=case_id)

        # Last: from here the transaction holds the spine's ordering lock, and everything above
        # has already taken every lock this transaction will ever need.
        await append_event(
            connection,
            event_type=EVENT_EXCEPTION_WITHDRAWN,
            correlation_id=write.correlation_id,
            occurred_at=now,
            case_id=case_id,
            entity_refs=[{"kind": "case", "id": str(case_id)}],
            payload={
                "state": destination,
                "withdrawn_by": worker_id,
                "tracks": len(live),
                "applied": len(applied),
                "reversed": released + len(requests) + stood_down + planned,
            },
        )
        for track in live:
            await append_event(
                connection,
                event_type=EVENT_TRACK_ESCALATED if consequential else EVENT_TRACK_WITHDRAWN,
                correlation_id=write.correlation_id,
                occurred_at=now,
                case_id=case_id,
                entity_refs=[{"kind": "track", "id": str(track.id)}],
                payload={
                    "reason": (
                        ESCALATION_WITHDRAWN_AFTER_EFFECTS if consequential else WITHDRAWN_BY_WORKER
                    )
                },
            )

    return WithdrawalResult(
        case_id=case_id,
        command_id=command_id,
        state=destination,
        created=True,
        withdrawn=() if consequential else tuple(track.id for track in live),
        escalated=tuple(track.id for track in live) if consequential else (),
        reversals=_counted(
            (
                (ReversalKind.TASK_HOLD, released),
                (ReversalKind.OPEN_REQUEST, len(requests)),
                (ReversalKind.UNSENT_EFFECT, stood_down),
                (ReversalKind.PLANNED_WORK, planned),
            )
        ),
        applied=_applied_counts(applied),
    )


def _counted(pairs: tuple[tuple[ReversalKind, int], ...]) -> tuple[tuple[ReversalKind, int], ...]:
    """Only the things that actually happened. A zero is not a finding."""
    return tuple((kind, count) for kind, count in pairs if count)


def _applied_counts(
    applied: tuple[tuple[UUID, str, str], ...],
) -> tuple[tuple[AppliedKind, int], ...]:
    """The already-applied effects, grouped by what a person would call them.

    An effect a dispatcher is holding right now is reported as in flight rather than as either
    sent or unsent, because this transaction genuinely does not know which it will become and
    guessing would put a claim in the record that nothing observed.
    """
    counts: dict[AppliedKind, int] = {}
    for _, kind, state in applied:
        grouped = _applied_kind(kind, state)
        counts[grouped] = counts.get(grouped, 0) + 1
    return tuple((kind, counts[kind]) for kind in AppliedKind if kind in counts)


def _applied_kind(kind: str, state: str) -> AppliedKind:
    if state == "IN_FLIGHT":
        return AppliedKind.EFFECT_IN_FLIGHT
    if kind == EFFECT_ORDER_AMEND:
        return AppliedKind.ORDER_AMENDED
    return AppliedKind.CUSTOMER_ASKED


# ------------------------------------------------------------------------------ reading rows


async def _applied_effects(
    connection: AsyncConnection, case_id: UUID
) -> tuple[tuple[UUID, str, str], ...]:
    """Effects of this case that a customer or the order system may already have.

    ``DELIVERED`` is unambiguous. ``IN_FLIGHT`` is counted with it on purpose: a dispatcher owns
    that row and may be inside the provider call at this instant, so treating it as stoppable
    would be this transaction claiming to know something it cannot see.
    """
    rows = (
        await connection.execute(
            select(OutboxMessage.id, OutboxMessage.kind, OutboxMessage.state)
            .where(
                OutboxMessage.payload["case_id"].astext == str(case_id),
                OutboxMessage.state.in_(("DELIVERED", "IN_FLIGHT")),
            )
            .order_by(OutboxMessage.created_at, OutboxMessage.id)
        )
    ).all()
    return tuple((row.id, row.kind, row.state) for row in rows)


async def _unsent_effects(connection: AsyncConnection, case_id: UUID) -> tuple[UUID, ...]:
    """Effects of this case that are queued and that nobody has claimed.

    Taken ``FOR UPDATE SKIP LOCKED`` so a dispatcher mid-claim is left alone rather than waited
    on. A row this misses is one that really is going out, and it is counted as applied on the
    next read rather than reported as stopped here.
    """
    rows = (
        await connection.execute(
            select(OutboxMessage.id)
            .where(
                OutboxMessage.payload["case_id"].astext == str(case_id),
                OutboxMessage.state == "PENDING",
            )
            .order_by(OutboxMessage.id)
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    return tuple(rows)


async def _held_tasks(connection: AsyncConnection, case_id: UUID) -> tuple[str, ...]:
    """Production tasks this case put on hold. Only this case's -- never another's."""
    rows = (
        await connection.execute(
            select(ProductionTask.id)
            .where(ProductionTask.held_by_case_id == case_id, ProductionTask.state == "HELD")
            .order_by(ProductionTask.id)
        )
    ).scalars()
    return tuple(rows)


async def _open_requests(connection: AsyncConnection, case_id: UUID) -> tuple[UUID, ...]:
    """Approval requests of this case that could still receive an authoritative answer.

    A decided request is left exactly alone. The customer's literal word is a decision they
    made, and a worker withdrawing their own exception does not get to unmake it.
    """
    rows = (
        await connection.execute(
            select(ApprovalRequest.id)
            .join(Track, Track.id == ApprovalRequest.track_id)
            .where(
                Track.case_id == case_id,
                ApprovalRequest.decided.is_(False),
                ApprovalRequest.state.in_(
                    (
                        ApprovalRequestState.SENT.value,
                        ApprovalRequestState.CONFIRMATION_PENDING.value,
                    )
                ),
            )
            .order_by(ApprovalRequest.id)
        )
    ).scalars()
    return tuple(rows)


# ------------------------------------------------------------------------------ writing rows


async def _settle_track(write: GovernedWrite, *, track: Any, state: str) -> None:
    """Move one live track to its settled posture. Fenced on the version this transaction read."""
    result = await write.execute(
        update(Track)
        .where(Track.id == track.id, Track.version == track.version)
        .values(state=state, version=Track.version + 1)
    )
    if result.rowcount != 1:
        raise WithdrawalStateError(f"track {track.id} changed under a held lock")


async def _supersede_request(write: GovernedWrite, *, request_id: UUID) -> None:
    """§14.4's supersede, used here for the same reason: the request authorises nothing now.

    Two columns and nothing else. The captured world, the option code, the provider reference
    and anything the customer already said all stay exactly where they are -- what changes is
    that none of it can authorise a change to an order any more. It is also what stops a queued
    message going out at all: the dispatcher already refuses to deliver a message whose request
    is no longer open, which is a rule this module did not have to add.
    """
    await write.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == request_id,
            ApprovalRequest.state != ApprovalRequestState.SUPERSEDED.value,
        )
        .values(state=ApprovalRequestState.SUPERSEDED.value)
    )
    await write.execute(
        update(Track)
        .where(Track.approval_request_id == request_id)
        .values(approval_request_id=None, version=Track.version + 1)
    )


async def _release_holds(write: GovernedWrite, *, case_id: UUID, tasks: tuple[str, ...]) -> int:
    """Give the kitchen back the work this case had stopped. §23's "task hold" reversed.

    Scoped to holds this case took, so a task another case is holding for its own blocked
    promise is untouched. The physical fact is not reversed by any of this: if the shortfall is
    real the promise is still at risk, which is why every live track lands on the owner's desk in
    the same transaction.

    **This writes the literal ``SCHEDULED``, and that is safe only because a started task is
    never held.** ``recovery.hold_tasks`` matches ``SCHEDULED`` and nothing else, so every row
    this statement can reach really was scheduled before it was held. Widening that predicate
    without giving this table a memory of the prior state would make a withdrawal -- the one
    operation whose whole promise is that it reverses no physical fact -- rewrite begun work
    into work that never began. See ADR-0017 and ``docs/started-work-contract.md``.
    """
    if not tasks:
        return 0
    result = await write.execute(
        update(ProductionTask)
        .where(
            ProductionTask.id.in_(tasks),
            ProductionTask.held_by_case_id == case_id,
            ProductionTask.state == "HELD",
        )
        .values(state="SCHEDULED", held_by_case_id=None)
    )
    return int(result.rowcount)


async def _refuse_unsent(write: GovernedWrite, *, effects: tuple[UUID, ...], worker_id: str) -> int:
    """Stand down the effects that had not gone out, before a dispatcher can claim one.

    ``FAILED`` is the outbox's own word for "this will not be delivered, and will not be
    retried" -- the same posture an approval message reaches when its window closes before
    dispatch. The reason is written beside it, so the ledger says a person withdrew the exception
    rather than leaving a reader to infer a provider fault that never happened.
    """
    if not effects:
        return 0
    result = await write.execute(
        update(OutboxMessage)
        .where(OutboxMessage.id.in_(effects), OutboxMessage.state == "PENDING")
        .values(
            state="FAILED",
            next_attempt_at=None,
            error=f"withdrawn by {worker_id} before this effect was dispatched",
        )
    )
    return int(result.rowcount)


async def _stand_down_steps(write: GovernedWrite, *, case_id: UUID, command_id: UUID) -> int:
    """Settle the work nobody had claimed. A claimed step settles itself against the new state.

    ``SKIPPED`` rather than deleted: the ledger is the evidence that the case stopped here, and a
    row that vanished would make a withdrawn case look like one that never planned anything. The
    withdrawal's own command row is excluded -- it is being written in this transaction.
    """
    result = await write.execute(
        update(CaseStep)
        .where(
            CaseStep.case_id == case_id,
            CaseStep.state.in_(UNSETTLED_STEP_STATES),
            CaseStep.id != command_id,
        )
        .values(state="SKIPPED")
    )
    return int(result.rowcount)


async def _enqueue_reconcile(connection: AsyncConnection, *, case_id: UUID) -> None:
    """The one step a reconciling case still has, or nothing because it already exists."""
    await connection.execute(
        pg_insert(CaseStep)
        .values(
            id=uuid4(),
            case_id=case_id,
            track_id=None,
            step_key=(await reconcile_step(connection, case_id)).step_key,
            kind=STEP_RECONCILE_CASE,
            state="PENDING",
            attempts=0,
        )
        .on_conflict_do_nothing(index_elements=[CaseStep.case_id, CaseStep.step_key])
    )


async def _record_withdrawal(
    connection: AsyncConnection,
    *,
    case_id: UUID,
    command_id: UUID,
    worker_id: str,
    fingerprint_of_request: str,
    destination: str,
    now: datetime,
) -> None:
    """Store the accepted command, keyed on the caller's own identity for it."""
    await connection.execute(
        pg_insert(CaseStep).values(
            id=command_id,
            case_id=case_id,
            step_key=withdraw_step_key(command_id),
            kind=STEP_WITHDRAW_EXCEPTION,
            state="DONE",
            attempts=0,
            request_hash=fingerprint_of_request,
            result={"withdrawn_by": worker_id, "case_state": destination},
            started_at=now,
            done_at=now,
        )
    )


@dataclass(frozen=True, slots=True)
class _Existing:
    case_id: UUID
    state: str


async def _existing_withdrawal(
    connection: AsyncConnection, command_id: UUID, fingerprint_of_request: str
) -> _Existing | None:
    """Has this exact command already been accepted? Answered from the row it wrote.

    A command id spent on a *different* intent lands here too -- a confirmation's id reused for a
    withdrawal is two different requests wearing one name, and is refused rather than read as a
    retry of either.
    """
    row = (
        await connection.execute(
            select(CaseStep.case_id, CaseStep.kind, CaseStep.request_hash, Case.state)
            .join(Case, Case.id == CaseStep.case_id)
            .where(CaseStep.id == command_id)
        )
    ).one_or_none()
    if row is None:
        return None
    if row.kind != STEP_WITHDRAW_EXCEPTION or row.request_hash != fingerprint_of_request:
        raise WithdrawalConflictError(
            f"command {command_id} was already accepted carrying a different request"
        )
    return _Existing(case_id=row.case_id, state=row.state)


__all__ = [
    "AUDIT_EXCEPTION_WITHDRAWN",
    "CASE_CANCELLED",
    "ESCALATION_WITHDRAWN_AFTER_EFFECTS",
    "EVENT_EXCEPTION_WITHDRAWN",
    "EVENT_TRACK_WITHDRAWN",
    "STEP_WITHDRAW_EXCEPTION",
    "WITHDRAWN_BY_WORKER",
    "AppliedKind",
    "CaseNotWithdrawableError",
    "ReversalKind",
    "WithdrawalConflictError",
    "WithdrawalResult",
    "WithdrawalStateError",
    "withdraw_exception",
    "withdraw_step_key",
]
