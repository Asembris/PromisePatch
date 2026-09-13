"""The three things a worker can say to an intake case, as reusable application services.

Every one of them does the same four things and nothing else: check that the case is in a
state where these words mean something, store the words, enqueue the durable work, and
announce it. **None of them interprets, and none of them touches physical state.** The
interpreter runs in the worker, under a lease, inside a transaction that can be rolled back
and re-run -- which is the only place a decision that settles a delivery belongs.

That split is why these functions are safe to call from a CLI, an HTTP handler or an MCP tool
without any of them growing a copy of the rules. The transport chooses who is speaking; the
domain decides whether they may.

**Idempotency is a row, not a memory.** Each command carries a caller-chosen ``command_id``
that becomes the primary key of the statement it stores, and a hash of the request that
becomes a column on it. A redelivery of the same request finds its own row and returns the
same answer; a *different* request under the same id is a conflict, loudly, because two
different things were said and only one of them can be what happened. Nothing is kept in
process memory, so a restart between the two deliveries changes nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.clock import database_now
from promisepatch.db.events import append_event
from promisepatch.db.models import Case, CaseReport, ExceptionClarification, Worker
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.domain.cases import lock_case
from promisepatch.domain.observation import (
    AUDIT_CASE_OPENED,
    AUDIT_CLARIFICATION_ANSWERED,
    AUDIT_CORRECTION_REPORTED,
    CASE_CLARIFYING,
    CASE_RECEIVED,
    EVENT_CASE_OPENED,
    EVENT_CLARIFICATION_ANSWERED,
    EVENT_CORRECTION_REPORTED,
    STEP_BEGIN_INTERPRETATION,
    ReportKind,
    begin_step_key,
)
from promisepatch.domain.physical import case_id_for
from promisepatch.domain.steps import enqueue_step
from promisepatch.observability import get_logger

logger = get_logger(__name__)

OWNER_ROLE = "owner"
"""The role that may speak on any case, not only on the one it opened."""


class IntakeConflictError(RuntimeError):
    """The same command id arrived carrying a different request.

    Not a retry and not a race: two different statements are claiming one identity, and
    choosing either would silently discard the other. The caller has a bug in how it mints
    command ids, and finding that out now is much cheaper than finding it out from a delivery
    that was settled from the wrong sentence.
    """


class UnknownWorkerError(RuntimeError):
    """Nobody by that id works here. A statement needs an attestor who exists."""


class NotAwaitingClarificationError(RuntimeError):
    """The case is not waiting on an answer, so this answer is not about anything."""


class NotPermittedError(RuntimeError):
    """This worker may not speak on this case under the current rules."""


class NothingToCorrectError(RuntimeError):
    """A correction needs a fact to correct, and this case has not attested one."""


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """What a command did, in terms a caller can act on.

    ``created`` is false for a redelivery of a request that was already accepted, which is a
    success: the statement is stored and the work is enqueued, exactly once.
    """

    case_id: UUID
    statement_id: UUID
    state: str
    created: bool


def request_hash(**fields: object) -> str:
    """A stable fingerprint of what a caller asked for.

    Canonical JSON with sorted keys, so two encodings of one request hash alike and a changed
    word does not. It is what makes "the same command id, but a different request" a detectable
    condition rather than a silent overwrite.
    """
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


# --------------------------------------------------------------------------- opening a case


async def open_physical_exception(
    database: RuntimeDatabase,
    *,
    command_id: UUID,
    worker_id: str,
    raw_text: str,
    observed_at: datetime,
    correlation_id: UUID | None = None,
) -> IntakeResult:
    """Open a case for one spoken physical exception, or recognise one already open.

    The case id is derived from the command id, so the retry that opens "a second case" is not
    a thing that can happen: the second delivery collides on the primary key of a row it
    already wrote, reads it back, and returns the same case.

    The case is ``RECEIVED`` when this returns and the interpreter has not run. That ordering is
    the point -- the words are durable before anything is concluded from them, so a process
    that dies here leaves a case a worker can see and nothing that was guessed.
    """
    case_id = case_id_for(command_id)
    fingerprint = request_hash(worker=worker_id, text=raw_text, observed_at=observed_at.isoformat())

    async with database.begin() as connection:
        existing = await _existing(connection, command_id, fingerprint)
        if existing is not None:
            return IntakeResult(
                case_id=existing.case_id,
                statement_id=command_id,
                state=existing.state,
                created=False,
            )

    try:
        async with database.begin() as connection:
            await require_worker(connection, worker_id)
            now = await database_now(connection)
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type=AUDIT_CASE_OPENED,
                actor=await actor_for(connection, worker_id),
                # A worker reporting what they saw is not exercising a policy or a consent;
                # they are the source of the observation, and `NONE` says exactly that.
                authority="NONE",
                case_id=case_id,
                after={"case_state": CASE_RECEIVED, "reported_by": worker_id},
                provenance={"raw_utterance": raw_text, "observed_at": observed_at.isoformat()},
                correlation_id=correlation_id,
                occurred_at=now,
            ) as write:
                await write.execute(
                    insert(Case).values(
                        id=case_id,
                        state=CASE_RECEIVED,
                        opened_by=worker_id,
                        opened_at=observed_at,
                        version=1,
                        updated_at=now,
                    )
                )
                await write.execute(
                    insert(CaseReport).values(
                        id=command_id,
                        case_id=case_id,
                        kind=ReportKind.REPORT.value,
                        ordinal=1,
                        reported_by=worker_id,
                        raw_text=raw_text,
                        observed_at=observed_at,
                        recorded_at=now,
                        request_hash=fingerprint,
                    )
                )
                await enqueue_step(
                    connection,
                    case_id=case_id,
                    step_key=begin_step_key(command_id),
                    kind=STEP_BEGIN_INTERPRETATION,
                )
                await append_event(
                    connection,
                    event_type=EVENT_CASE_OPENED,
                    correlation_id=write.correlation_id,
                    occurred_at=now,
                    case_id=case_id,
                    entity_refs=[{"kind": "case", "id": str(case_id)}],
                    payload={"state": CASE_RECEIVED, "reported_by": worker_id},
                )
    except IntegrityError:
        # Two identical commands raced. Whichever lost reads back what the winner wrote, and
        # the hash comparison is still what decides whether they were really the same request.
        async with database.begin() as connection:
            existing = await _existing(connection, command_id, fingerprint)
        if existing is None:
            raise
        return IntakeResult(
            case_id=existing.case_id, statement_id=command_id, state=existing.state, created=False
        )

    logger.info("intake.case.opened", case_id=str(case_id), worker=worker_id)
    return IntakeResult(case_id=case_id, statement_id=command_id, state=CASE_RECEIVED, created=True)


# ------------------------------------------------------------------- answering a clarification


async def answer_clarification(
    database: RuntimeDatabase,
    *,
    case_id: UUID,
    command_id: UUID,
    worker_id: str,
    raw_text: str,
    observed_at: datetime | None = None,
    correlation_id: UUID | None = None,
) -> IntakeResult:
    """Record a worker's answer to the open question, and hand it back to the interpreter.

    The answer is stored verbatim and interpreted nowhere near here. What this function
    decides is only whether the case is waiting on an answer and whether this worker is one of
    the people who may give it -- and it holds the case row while deciding, so an answer and a
    worker's step cannot both move the case at once.
    """
    fingerprint = request_hash(case=str(case_id), worker=worker_id, text=raw_text)

    async with database.begin() as connection:
        existing = await _existing(connection, command_id, fingerprint)
        if existing is not None:
            return IntakeResult(
                case_id=existing.case_id,
                statement_id=command_id,
                state=existing.state,
                created=False,
            )

    async with database.begin() as connection:
        await require_worker(connection, worker_id)
        case = await lock_case(connection, case_id)
        if case.state != CASE_CLARIFYING:
            raise NotAwaitingClarificationError(
                f"case {case_id} is {case.state}, not {CASE_CLARIFYING}"
            )
        await require_permitted(connection, case_id=case_id, worker_id=worker_id)

        clarification = (
            await connection.execute(
                select(ExceptionClarification)
                .where(
                    ExceptionClarification.case_id == case_id,
                    ExceptionClarification.answered_at.is_(None),
                )
                .with_for_update()
            )
        ).one_or_none()
        if clarification is None:
            raise NotAwaitingClarificationError(f"case {case_id} has no open clarification")

        now = await database_now(connection)
        seen = observed_at or now
        unit_of_work = UnitOfWork(connection)
        async with unit_of_work.governed(
            event_type=AUDIT_CLARIFICATION_ANSWERED,
            actor=await actor_for(connection, worker_id),
            authority="NONE",
            case_id=case_id,
            before={"clarification": str(clarification.id), "answered": False},
            after={"clarification": str(clarification.id), "answered": True},
            provenance={"raw_answer": raw_text, "question": clarification.question},
            correlation_id=correlation_id,
            occurred_at=now,
        ) as write:
            await write.execute(
                insert(CaseReport).values(
                    id=command_id,
                    case_id=case_id,
                    kind=ReportKind.CLARIFICATION_ANSWER.value,
                    ordinal=await _next_ordinal(connection, case_id),
                    reported_by=worker_id,
                    raw_text=raw_text,
                    observed_at=seen,
                    recorded_at=now,
                    request_hash=fingerprint,
                )
            )
            await write.execute(
                update(ExceptionClarification)
                .where(
                    ExceptionClarification.id == clarification.id,
                    ExceptionClarification.answered_at.is_(None),
                )
                .values(answer_report_id=command_id, answer_text=raw_text, answered_at=now)
            )
            await enqueue_step(
                connection,
                case_id=case_id,
                step_key=begin_step_key(command_id),
                kind=STEP_BEGIN_INTERPRETATION,
            )
            await append_event(
                connection,
                event_type=EVENT_CLARIFICATION_ANSWERED,
                correlation_id=write.correlation_id,
                occurred_at=now,
                case_id=case_id,
                entity_refs=[{"kind": "clarification", "id": str(clarification.id)}],
                payload={"answered_by": worker_id},
            )

    logger.info("intake.clarification.answered", case_id=str(case_id), worker=worker_id)
    return IntakeResult(
        case_id=case_id, statement_id=command_id, state=CASE_CLARIFYING, created=True
    )


# ---------------------------------------------------------------------- correcting a fact


async def correct_physical_fact(
    database: RuntimeDatabase,
    *,
    case_id: UUID,
    command_id: UUID,
    worker_id: str,
    raw_text: str,
    observed_at: datetime | None = None,
    correlation_id: UUID | None = None,
) -> IntakeResult:
    """Record a later claim about a delivery this case already settled.

    A correction is a new attestation, never an undo. This function only stores it and queues
    the interpretation; what happens to the ledger -- a compensating movement, and a fresh
    fact citing the one it supersedes -- happens in the worker, where the old fact stays
    exactly where it is.
    """
    fingerprint = request_hash(case=str(case_id), worker=worker_id, text=raw_text)

    async with database.begin() as connection:
        existing = await _existing(connection, command_id, fingerprint)
        if existing is not None:
            return IntakeResult(
                case_id=existing.case_id,
                statement_id=command_id,
                state=existing.state,
                created=False,
            )

    async with database.begin() as connection:
        await require_worker(connection, worker_id)
        case = await lock_case(connection, case_id)
        await require_permitted(connection, case_id=case_id, worker_id=worker_id)
        bound = await connection.scalar(select(Case.exception_id).where(Case.id == case_id))
        if bound is None:
            raise NothingToCorrectError(f"case {case_id} has attested no physical fact to correct")

        now = await database_now(connection)
        seen = observed_at or now
        unit_of_work = UnitOfWork(connection)
        async with unit_of_work.governed(
            event_type=AUDIT_CORRECTION_REPORTED,
            actor=await actor_for(connection, worker_id),
            authority="NONE",
            case_id=case_id,
            after={"exception_id": str(bound), "case_state": case.state},
            provenance={"raw_correction": raw_text, "observed_at": seen.isoformat()},
            correlation_id=correlation_id,
            occurred_at=now,
        ) as write:
            await write.execute(
                insert(CaseReport).values(
                    id=command_id,
                    case_id=case_id,
                    kind=ReportKind.CORRECTION.value,
                    ordinal=await _next_ordinal(connection, case_id),
                    reported_by=worker_id,
                    raw_text=raw_text,
                    observed_at=seen,
                    recorded_at=now,
                    request_hash=fingerprint,
                )
            )
            await enqueue_step(
                connection,
                case_id=case_id,
                step_key=begin_step_key(command_id),
                kind=STEP_BEGIN_INTERPRETATION,
            )
            await append_event(
                connection,
                event_type=EVENT_CORRECTION_REPORTED,
                correlation_id=write.correlation_id,
                occurred_at=now,
                case_id=case_id,
                entity_refs=[{"kind": "exception", "id": str(bound)}],
                payload={"reported_by": worker_id},
            )

    logger.info("intake.correction.reported", case_id=str(case_id), worker=worker_id)
    return IntakeResult(case_id=case_id, statement_id=command_id, state=case.state, created=True)


# ----------------------------------------------------------------------------------- shared


@dataclass(frozen=True, slots=True)
class _Existing:
    case_id: UUID
    state: str


async def _existing(
    connection: AsyncConnection, command_id: UUID, fingerprint: str
) -> _Existing | None:
    """Has this exact command already been accepted? Answered from the row it wrote.

    A stored statement whose hash differs is not this command being retried; it is a different
    request claiming an identity that is taken, and the caller is told so rather than having
    one of the two silently win.
    """
    row = (
        await connection.execute(
            select(CaseReport.case_id, CaseReport.request_hash, Case.state)
            .join(Case, Case.id == CaseReport.case_id)
            .where(CaseReport.id == command_id)
        )
    ).one_or_none()
    if row is None:
        return None
    if row.request_hash != fingerprint:
        raise IntakeConflictError(
            f"command {command_id} was already accepted carrying a different request"
        )
    return _Existing(case_id=row.case_id, state=row.state)


async def observed_at_for(database: RuntimeDatabase, *, command_id: UUID) -> datetime | None:
    """When this command's statement said the kitchen looked like that, if it is already stored.

    For a caller with no natural clock of its own -- an HTTP handler, an MCP tool -- "when did
    this happen" is the moment the words arrived, and it is the *server's* to decide: a caller
    that could set it could backdate a physical claim. But a redelivery of one command is the
    same statement, so it happened when that statement said it happened, and stamping a fresh
    ``now()`` on the retry would change the request hash and turn an idempotent redelivery into
    a conflict.

    So this answers the narrow question a redelivery needs: has this exact command already been
    stored, and if so, when did it say it was observed. It decides nothing and writes nothing.
    """
    async with database.connect() as connection:
        stored: datetime | None = await connection.scalar(
            select(CaseReport.observed_at).where(CaseReport.id == command_id)
        )
    return stored


async def require_worker(connection: AsyncConnection, worker_id: str) -> None:
    exists = await connection.scalar(select(Worker.id).where(Worker.id == worker_id))
    if exists is None:
        raise UnknownWorkerError(f"no worker {worker_id!r}")


async def actor_for(connection: AsyncConnection, worker_id: str) -> Actor:
    """A staff member's audit identity, taken from their role rather than assumed.

    The distinction matters downstream: an owner binding a case by hand and a baker attesting
    what they saw are different authorities, and the ledger has separate vocabulary for both.
    """
    role = await connection.scalar(select(Worker.role).where(Worker.id == worker_id))
    return Actor(kind="OWNER" if role == OWNER_ROLE else "WORKER", id=worker_id)


async def require_permitted(connection: AsyncConnection, *, case_id: UUID, worker_id: str) -> None:
    """Who may speak on a case: the worker who opened it, or an owner.

    Narrow on purpose. A physical attestation is only worth anything if the person making it
    was in a position to see the thing, and "somebody else's case" is not that position. An
    owner is included because escalation is theirs to resolve.
    """
    opened_by = await connection.scalar(select(Case.opened_by).where(Case.id == case_id))
    if opened_by == worker_id:
        return
    role = await connection.scalar(select(Worker.role).where(Worker.id == worker_id))
    if role == OWNER_ROLE:
        return
    raise NotPermittedError(f"worker {worker_id!r} did not open case {case_id} and is not an owner")


OBSERVER_ROLE = "observer"
"""A principal that may be shown a case. It appears in :func:`require_readable` and nowhere else."""


async def require_readable(connection: AsyncConnection, *, case_id: UUID, worker_id: str) -> None:
    """Who may be *shown* a case: whoever may speak on it, or an observer.

    A second, wider question than :func:`require_permitted`, and deliberately a separate
    function rather than a flag on that one. Every write in this system gates on
    ``require_permitted``, which has no branch for an observer and is not changed by this being
    here -- so the read widening cannot reach a write even by mistake, and a write route added
    later with no observer check of its own still refuses one. A parameter would have made the
    two answers one call site apart.

    It is additive: everyone this admits who was admitted before is admitted for the same
    reason, by the same function, and the only new admission is a role the database did not have
    a week ago. Nothing that could speak stops being able to.
    """
    try:
        await require_permitted(connection, case_id=case_id, worker_id=worker_id)
    except NotPermittedError:
        role = await connection.scalar(select(Worker.role).where(Worker.id == worker_id))
        if role != OBSERVER_ROLE:
            raise
    return


async def _next_ordinal(connection: AsyncConnection, case_id: UUID) -> int:
    value = await connection.scalar(
        select(func.coalesce(func.max(CaseReport.ordinal), 0)).where(CaseReport.case_id == case_id)
    )
    return int(value or 0) + 1


def new_command_id() -> UUID:
    """A fresh command identity, for a caller that has no natural one of its own."""
    return uuid4()
