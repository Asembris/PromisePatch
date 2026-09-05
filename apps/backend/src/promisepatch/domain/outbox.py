"""Outbound effects: enqueued with the decision, sent afterwards, acknowledged separately.

**The guarantee, stated plainly.** PromisePatch provides *at-least-once* dispatch under a
stable idempotency key. Exactly-once real-world effects are not something this or any other
outbox can deliver on its own: there is an irreducible window in which a provider has accepted
a call and the process dies before the acknowledgement commits, and the only honest response is
to send again under the identical key and let a provider that supports keys collapse the two.
Where a provider does not, the duplicate is real, and the attempt count on the row says so.

Three transactions, for three different reasons.

**Enqueue** happens inside the governed transition that decided on the effect, so the row and
the decision share a fate: no effect without its cause, and no cause that quietly failed to
schedule its effect. A duplicate idempotency key is a programming error, not a second effect --
it raises, and the surrounding transition rolls back rather than inventing a new key.

**Claim** is short and commits before anything is sent, so the row records that an attempt is
about to happen even if the process dies during it. That is what makes the uncertain window
recoverable rather than invisible.

**Delivery happens outside any transaction at all.** A provider call inside an open transaction
would hold a database connection, its locks and its snapshot for the length of a network round
trip, and a provider that hangs would become a database problem. The claim commits, the adapter
is called with nothing held, and the result is recorded in a third, fenced transaction.

Between the claim and the call sits exactly one question about what an effect *means*: may this
still be sent at all. It is asked because one effect genuinely expires -- an approval request may
not be delivered after the window in which the customer could have answered it has closed -- and
the answer is recorded as a terminal failure, so the row's own continuation decides what that
means. The dispatcher stays ignorant of everything else, which is what keeps it a dispatcher.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from sqlalchemy import insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.clock import database_now
from promisepatch.db.events import append_event
from promisepatch.db.models import OutboxMessage
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.domain import crash, retry
from promisepatch.domain.cases import apply_case_change, lock_case
from promisepatch.domain.model import (
    AUDIT_EFFECT_FAILED,
    EVENT_EFFECT_DELIVERED,
    EVENT_EFFECT_FAILED,
    CaseChange,
    DeliveryOutcome,
    DeliveryStatus,
)
from promisepatch.observability import get_logger

logger = get_logger(__name__)

LEASE_DURATION: Final = timedelta(seconds=60)
"""How long a dispatcher owns a message before another may retry it.

Longer than any adapter call should take, so a slow provider is not mistaken for a dead worker
and given a second, concurrent attempt.
"""


CONTINUATION: Final = "continuation"
DELIVERED: Final = "delivered"
FAILED: Final = "failed"
"""How an effect says what its answer should make runnable.

A payload may carry ``continuation`` naming a step to enqueue when the provider accepts the
call, another for when it finally refuses, or neither. The dispatcher stays ignorant of what
either step *means*: it enqueues a row in the same transaction that records the answer, and the
step runner decides the rest under its own lock and its own audit.

Storing the hand-off on the row rather than holding it in the dispatcher is what makes it
crash-safe. An in-memory callback would be lost with the process that was about to run it,
leaving a provider effect that is durable and a recovery that nobody will ever finish.
"""


class DuplicateEffectError(RuntimeError):
    """Two effects were enqueued under one idempotency key.

    A programming error rather than a race: the key is derived from server-side identifiers, so
    a collision means two different decisions believe they are the same one. Raised so the
    surrounding transition rolls back, because silently minting a fresh key would turn one
    intended effect into two real ones.
    """


class EffectLeaseLostError(RuntimeError):
    """Another dispatcher took this message over. Raised so nothing this one did commits."""


class EffectAdapter(Protocol):
    """A provider, reduced to the one call the dispatcher makes.

    The idempotency key is passed explicitly rather than derived, because it is the persistent
    one from the row: a redelivery must present the *same* key the first attempt did, and an
    adapter that generated its own would make every retry a new effect.
    """

    async def deliver(
        self, *, kind: str, payload: Mapping[str, Any], idempotency_key: str
    ) -> DeliveryOutcome: ...


@dataclass(frozen=True, slots=True)
class EffectClaim:
    """One dispatcher's right to attempt one message."""

    effect_id: UUID
    kind: str
    payload: Mapping[str, Any]
    idempotency_key: str
    attempts: int
    lease_owner: str
    case_id: UUID | None


# ------------------------------------------------------------------------------------ enqueue


async def enqueue_effect(
    connection: AsyncConnection,
    *,
    kind: str,
    payload: Mapping[str, Any],
    idempotency_key: str,
) -> UUID:
    """Record an intended effect in the transaction that decided on it."""
    effect_id = uuid4()
    try:
        await connection.execute(
            insert(OutboxMessage).values(
                id=effect_id,
                kind=kind,
                payload=dict(payload),
                idempotency_key=idempotency_key,
                state="PENDING",
                attempts=0,
            )
        )
    except IntegrityError as error:
        raise DuplicateEffectError(
            f"an effect with idempotency key {idempotency_key!r} is already enqueued"
        ) from error
    return effect_id


async def stamp_created_in_tx_seq(
    connection: AsyncConnection, *, effect_ids: Sequence[UUID], seq: int
) -> None:
    """Record which event this transaction's effects were created alongside.

    Run after the event append, and safe there: these rows were inserted by this very
    transaction, so it already holds their locks and waits for nobody. That is the difference
    between "take no new lock after appending" and "issue no statement after appending".
    """
    if not effect_ids:
        return
    await connection.execute(
        update(OutboxMessage)
        .where(OutboxMessage.id.in_(list(effect_ids)))
        .values(created_in_tx_seq=seq)
    )


# -------------------------------------------------------------------------------------- claim


async def claim_effect(
    database: RuntimeDatabase, *, worker: str, lease: timedelta = LEASE_DURATION
) -> EffectClaim | None:
    """Take one due message, and commit that before anything is sent."""
    async with database.begin() as connection:
        now = await database_now(connection)
        due = (OutboxMessage.state == "PENDING") & (
            OutboxMessage.next_attempt_at.is_(None) | (OutboxMessage.next_attempt_at <= now)
        )
        expired = (OutboxMessage.state == "IN_FLIGHT") & (OutboxMessage.lease_expires_at <= now)

        candidate = (
            await connection.execute(
                select(OutboxMessage.id)
                .where(or_(due, expired))
                .order_by(OutboxMessage.created_at, OutboxMessage.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if candidate is None:
            return None

        claimed = (
            await connection.execute(
                update(OutboxMessage)
                .where(OutboxMessage.id == candidate)
                .values(
                    state="IN_FLIGHT",
                    attempts=OutboxMessage.attempts + 1,
                    lease_owner=worker,
                    lease_expires_at=now + lease,
                    next_attempt_at=None,
                )
                .returning(
                    OutboxMessage.id,
                    OutboxMessage.kind,
                    OutboxMessage.payload,
                    OutboxMessage.idempotency_key,
                    OutboxMessage.attempts,
                )
            )
        ).one()

    crash.at(crash.AFTER_OUTBOX_CLAIM)
    payload = dict(claimed.payload or {})
    raw_case = payload.get("case_id")
    return EffectClaim(
        effect_id=claimed.id,
        kind=claimed.kind,
        payload=payload,
        idempotency_key=claimed.idempotency_key,
        attempts=claimed.attempts,
        lease_owner=worker,
        case_id=UUID(str(raw_case)) if raw_case else None,
    )


# ------------------------------------------------------------------------------------ record


async def record_delivery(
    database: RuntimeDatabase, *, claim: EffectClaim, outcome: DeliveryOutcome, actor: Actor
) -> DeliveryStatus:
    """Write down what the provider said, fenced against a dispatcher that lost its lease.

    Exhausting the retry ladder is treated as a terminal failure, because a message that has
    been refused five times is not going to be accepted on the sixth, and continuing to schedule
    attempts would hide a real problem behind a growing attempt count.
    """
    status = outcome.status
    if status is DeliveryStatus.RETRYABLE and retry.is_exhausted(claim.attempts):
        status = DeliveryStatus.TERMINAL

    if status is DeliveryStatus.DELIVERED:
        return await _record_delivered(database, claim=claim, outcome=outcome)
    if status is DeliveryStatus.RETRYABLE:
        return await _record_retry(database, claim=claim, outcome=outcome)
    return await _record_terminal(database, claim=claim, outcome=outcome, actor=actor)


async def _record_delivered(
    database: RuntimeDatabase, *, claim: EffectClaim, outcome: DeliveryOutcome
) -> DeliveryStatus:
    async with database.begin() as connection:
        now = await database_now(connection)
        await _settle(
            connection,
            claim=claim,
            state="DELIVERED",
            values={
                "provider_ref": outcome.provider_ref,
                # What the provider reported it did, if it is a system of record and reported
                # anything. Persisted with the acceptance rather than beside it: a process that
                # died in between would otherwise leave a delivered effect whose authoritative
                # result nobody could name afterwards.
                "result": None if outcome.result is None else dict(outcome.result),
                "delivered_at": now,
                "last_error": None,
            },
        )
        await _continue(connection, claim=claim, on=DELIVERED)
        await append_event(
            connection,
            event_type=EVENT_EFFECT_DELIVERED,
            correlation_id=uuid4(),
            occurred_at=now,
            case_id=claim.case_id,
            entity_refs=[{"kind": "outbox_message", "id": str(claim.effect_id)}],
            payload={
                "kind": claim.kind,
                "idempotency_key": claim.idempotency_key,
                "provider_ref": outcome.provider_ref,
                "attempts": claim.attempts,
            },
        )
    return DeliveryStatus.DELIVERED


async def _record_retry(
    database: RuntimeDatabase, *, claim: EffectClaim, outcome: DeliveryOutcome
) -> DeliveryStatus:
    """Back to ``PENDING`` with a time on it. The key is untouched, which is the whole point."""
    backoff = retry.backoff_after(claim.attempts)
    if backoff is None:  # pragma: no cover - exhaustion became TERMINAL in record_delivery
        raise RuntimeError("a retry was scheduled for an attempt the policy had exhausted")
    async with database.begin() as connection:
        now = await database_now(connection)
        await _settle(
            connection,
            claim=claim,
            state="PENDING",
            values={"next_attempt_at": now + backoff, "last_error": outcome.error},
        )
    return DeliveryStatus.RETRYABLE


async def _record_terminal(
    database: RuntimeDatabase, *, claim: EffectClaim, outcome: DeliveryOutcome, actor: Actor
) -> DeliveryStatus:
    """A failure that stops here, and puts the case on somebody's desk if it belongs to one.

    The case row is locked *before* the outbox row, which is the same order every step
    transition uses. Taking them the other way round would be the one pairing that could
    deadlock against a transition holding a case and enqueueing an effect.
    """
    async with database.begin() as connection:
        now = await database_now(connection)
        case = await lock_case(connection, claim.case_id) if claim.case_id else None

        if case is None:
            await _settle(
                connection,
                claim=claim,
                state="FAILED",
                values={"last_error": outcome.error},
            )
            await _continue(connection, claim=claim, on=FAILED)
            await _append_failure(connection, claim=claim, outcome=outcome, now=now)
            return DeliveryStatus.TERMINAL

        unit_of_work = UnitOfWork(connection)
        async with unit_of_work.governed(
            event_type=AUDIT_EFFECT_FAILED,
            actor=actor,
            authority="NONE",
            case_id=case.id,
            before={
                "case_version": case.version,
                "needs_owner_attention": case.needs_owner_attention,
            },
            after={"case_version": case.version + 1, "needs_owner_attention": True},
            provenance={
                "worker": claim.lease_owner,
                "idempotency_key": claim.idempotency_key,
                "attempts": claim.attempts,
            },
            occurred_at=now,
        ) as write:
            await apply_case_change(
                write, case=case, change=CaseChange(needs_owner_attention=True), now=now
            )
            await _settle(
                connection, claim=claim, state="FAILED", values={"last_error": outcome.error}
            )
            await _continue(connection, claim=claim, on=FAILED)
            await _append_failure(connection, claim=claim, outcome=outcome, now=now)
    return DeliveryStatus.TERMINAL


async def _append_failure(
    connection: AsyncConnection, *, claim: EffectClaim, outcome: DeliveryOutcome, now: datetime
) -> None:
    await append_event(
        connection,
        event_type=EVENT_EFFECT_FAILED,
        correlation_id=uuid4(),
        occurred_at=now,
        case_id=claim.case_id,
        entity_refs=[{"kind": "outbox_message", "id": str(claim.effect_id)}],
        payload={
            "kind": claim.kind,
            "idempotency_key": claim.idempotency_key,
            "attempts": claim.attempts,
            "error": outcome.error,
        },
    )


async def _still_worth_sending(
    database: RuntimeDatabase, claim: EffectClaim
) -> DeliveryOutcome | None:
    """Whether this claimed effect may be delivered at all, or must be refused unsent.

    The dispatcher's one concession to what an effect *means*, and it is narrow on purpose: the
    only question it asks is "may this still be sent", never "what should happen next". It exists
    because one effect really does expire -- an approval request may not be delivered after the
    window in which the customer could have answered it has closed (§13.6) -- and a generic
    outbox cannot know that on its own.

    Deferred import, because the consent protocol enqueues the effects this module delivers.
    Returns ``None`` for every effect that has no such rule, which is all of them but one.
    """
    from promisepatch.domain.approvals import refuse_if_window_closed

    return await refuse_if_window_closed(database, kind=claim.kind, payload=claim.payload)


async def _continue(connection: AsyncConnection, *, claim: EffectClaim, on: str) -> None:
    """Make the work this answer unblocks runnable, in the transaction that records the answer.

    Deferred import, because the step ledger enqueues the effects this module delivers and a
    module-level import in both directions would be a cycle.

    No case row is locked here and none is needed: this inserts a ``case_steps`` row and takes
    no lock a step transition would ever wait on, so it cannot close a cycle with one.
    """
    from promisepatch.domain.steps import enqueue_step

    continuation = claim.payload.get(CONTINUATION)
    if claim.case_id is None or not isinstance(continuation, Mapping):
        return
    successor = continuation.get(on)
    if not isinstance(successor, Mapping):
        return
    await enqueue_step(
        connection,
        case_id=claim.case_id,
        step_key=str(successor["step_key"]),
        kind=str(successor["kind"]),
    )


async def _settle(
    connection: AsyncConnection, *, claim: EffectClaim, state: str, values: Mapping[str, Any]
) -> None:
    """The fenced write. One row, or this dispatcher no longer owns the message."""
    statement = (
        update(OutboxMessage)
        .where(
            OutboxMessage.id == claim.effect_id,
            OutboxMessage.state == "IN_FLIGHT",
            OutboxMessage.lease_owner == claim.lease_owner,
            OutboxMessage.attempts == claim.attempts,
        )
        .values(state=state, lease_owner=None, lease_expires_at=None, **values)
    )
    if (await connection.execute(statement)).rowcount != 1:
        raise EffectLeaseLostError(
            f"effect {claim.effect_id} was reclaimed while attempt {claim.attempts} was in flight"
        )


# ---------------------------------------------------------------------------------- dispatch


async def dispatch_one(
    database: RuntimeDatabase, adapter: EffectAdapter, *, worker: str, actor: Actor
) -> DeliveryStatus | None:
    """Claim, send, record. ``None`` when there was nothing to send.

    The adapter call sits between two committed transactions and inside neither, which is the
    only arrangement in which a hanging provider costs latency rather than a held connection.
    """
    claim = await claim_effect(database, worker=worker)
    if claim is None:
        return None

    refusal = await _still_worth_sending(database, claim)
    if refusal is not None:
        # Never sent, and recorded as terminal so the row's own failure continuation runs. The
        # dispatcher is not deciding anything here: it asked whether this effect may still be
        # attempted at all, and something that knows the rules said no.
        return await record_delivery(database, claim=claim, outcome=refusal, actor=actor)

    outcome = await adapter.deliver(
        kind=claim.kind, payload=claim.payload, idempotency_key=claim.idempotency_key
    )
    if outcome.status is DeliveryStatus.DELIVERED:
        # The provider has already acted. A death here is the uncertain window, and it is
        # recoverable precisely because the claim committed: the lease expires, the message is
        # retried, and the same key goes out again.
        crash.at(crash.AFTER_EXTERNAL_SUCCESS)

    try:
        status = await record_delivery(database, claim=claim, outcome=outcome, actor=actor)
    except EffectLeaseLostError as lost:
        logger.info("worker.effect.fenced", effect_id=str(claim.effect_id), detail=str(lost))
        return None

    logger.info(
        "worker.effect.dispatched",
        effect_id=str(claim.effect_id),
        kind=claim.kind,
        attempt=claim.attempts,
        status=status.value,
    )
    return status
