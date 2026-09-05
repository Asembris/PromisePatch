"""Inbound records: stored before anything is decided, processed from the row.

Two rules, and everything else follows from them.

**Store first, decide later.** An arriving event is written to ``inbox_events`` and the sender
is answered. Whatever we then do with it is done by reading the stored row, never the live
request, so processing is replayable, survives a crash, and cannot depend on a connection that
has since closed.

**The database deduplicates, not the application.** ``(source, provider_event_id)`` is unique,
so a provider that retries a delivery it was unsure about produces a conflict and a no-op
rather than a second piece of work. There is no "have we seen this before" query to forget,
and no window between checking and inserting.

Processing is one transaction per record: read a ``RECEIVED`` row under ``FOR UPDATE SKIP
LOCKED``, hand its stored material to a pure normaliser, write the verdict, create at most one
deterministic successor, append the event, commit. A worker killed in the middle of that rolls
back to ``RECEIVED``, which is retriable, rather than to a half-consumed state that is not.

**Nothing is decided here.** Processing an inbound record works out which case, if any, the
record is about, and creates the step that will decide what to do with it under its own lock and
its own audit. A customer's reply in particular is only *bound* here; whether the sender was
entitled to send it, whether the request is still open and whether the words mean anything are
questions for the transition that could act on the answers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.clock import database_now
from promisepatch.db.events import append_event
from promisepatch.db.models import InboxEvent
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.domain import crash, handlers
from promisepatch.domain.model import EVENT_INBOX_FAILED, EVENT_INBOX_PROCESSED
from promisepatch.observability import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessedInbound:
    """What became of one stored record."""

    inbox_id: UUID
    source: str
    state: str
    step_key: str | None
    seq: int


async def ingest(
    connection: AsyncConnection,
    *,
    source: str,
    provider_event_id: str,
    body: str | None,
    headers: Mapping[str, Any] | None = None,
    received_at: Any = None,
) -> UUID | None:
    """Store one inbound record, or recognise it as a delivery we already have.

    Returns the new row's id, or ``None`` when this exact ``(source, provider_event_id)`` was
    already stored. ``None`` is a success: the sender should be told the event was accepted,
    because it was -- the first time.
    """
    now = received_at or await database_now(connection)
    statement = (
        pg_insert(InboxEvent)
        .values(
            id=uuid4(),
            source=source,
            provider_event_id=provider_event_id,
            raw_headers=dict(headers) if headers is not None else None,
            raw_body=body,
            received_at=now,
            state="RECEIVED",
        )
        .on_conflict_do_nothing(index_elements=[InboxEvent.source, InboxEvent.provider_event_id])
        .returning(InboxEvent.id)
    )
    return (await connection.execute(statement)).scalar_one_or_none()


async def process_one(database: RuntimeDatabase, *, worker: str) -> ProcessedInbound | None:
    """Process at most one stored record, in a transaction of its own.

    Ungoverned: reading an inbound message and writing down what we made of it changes nothing
    a customer was promised. The successor step it may create is what will eventually make such
    a change, under its own audited transition.
    """
    async with database.begin() as connection:
        now = await database_now(connection)
        row = (
            await connection.execute(
                select(InboxEvent.id, InboxEvent.source, InboxEvent.raw_body)
                .where(InboxEvent.state == "RECEIVED")
                .order_by(InboxEvent.received_at, InboxEvent.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).one_or_none()
        if row is None:
            return None

        outcome = handlers.normalize_inbound(row.source, row.raw_body)
        if row.source == handlers.CUSTOMER_REPLY_SOURCE and outcome.state == "PROCESSED":
            # Normalisation is pure and cannot ask which case a reply belongs to, so the one
            # question that needs a row is asked here, in the same transaction. Deferred import
            # because the consent protocol enqueues steps this module's successors execute.
            from promisepatch.domain.approvals import bind_customer_reply

            outcome = await bind_customer_reply(connection, outcome)
        crash.at(crash.DURING_INBOX_PROCESSING)

        step_key: str | None = None
        if outcome.state == "PROCESSED" and outcome.case_id and outcome.step_kind:
            from promisepatch.domain.steps import enqueue_step

            step_key = handlers.inbox_step_key(row.id)
            await enqueue_step(
                connection,
                case_id=outcome.case_id,
                step_key=step_key,
                kind=outcome.step_kind,
            )

        await connection.execute(
            update(InboxEvent)
            .where(InboxEvent.id == row.id, InboxEvent.state == "RECEIVED")
            .values(
                state=outcome.state,
                normalized=dict(outcome.normalized) if outcome.normalized else None,
                processed_at=now,
                error=outcome.error,
            )
        )

        seq = await append_event(
            connection,
            event_type=(EVENT_INBOX_FAILED if outcome.state == "FAILED" else EVENT_INBOX_PROCESSED),
            correlation_id=uuid4(),
            occurred_at=now,
            case_id=outcome.case_id,
            entity_refs=[{"kind": "inbox_event", "id": str(row.id)}],
            payload={
                "source": row.source,
                "state": outcome.state,
                "step_key": step_key,
                "error": outcome.error,
            },
        )

    logger.info(
        "worker.inbox.processed",
        inbox_id=str(row.id),
        source=row.source,
        state=outcome.state,
        step_key=step_key,
        worker=worker,
    )
    return ProcessedInbound(
        inbox_id=row.id, source=row.source, state=outcome.state, step_key=step_key, seq=seq
    )
