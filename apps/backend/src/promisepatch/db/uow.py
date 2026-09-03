"""The only way to write a governed table.

``UnitOfWork.governed`` writes the audit event first, registers it in a transaction-local
setting, and hands back a handle to write through. The database then refuses any governed
write whose transaction has not done exactly that, so "every consequential change is audited"
is a property of PostgreSQL rather than a rule reviewers have to keep noticing.

The ordering is what makes it crash-safe. Audit row and domain write share one transaction and
one fate: there is no window in which a change is applied but unexplained, or explained but not
applied. The marker is set with ``is_local``, so it dies with the transaction that set it, and
it is cleared again when the block ends — an authorisation is spent on the write it was taken
out for, not on whatever the transaction does next.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, Executable, insert, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.boundary import AUDIT_MARKER
from promisepatch.db.models import AuditEvent
from promisepatch.db.types import ACTOR_KINDS, AUTHORITIES

_SET_MARKER = text(f"SELECT set_config('{AUDIT_MARKER}', :marker, true)")
_CLEAR_MARKER = text(f"SELECT set_config('{AUDIT_MARKER}', '', true)")


@dataclass(frozen=True, slots=True)
class Actor:
    """Who caused a write. Every governed write names one; none is anonymous."""

    kind: str
    id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ACTOR_KINDS:
            raise ValueError(f"unknown actor kind {self.kind!r}; expected one of {ACTOR_KINDS}")


@dataclass(frozen=True, slots=True)
class GovernedWrite:
    """An open authorisation: the connection to write through, and the event that permits it."""

    connection: AsyncConnection
    audit_seq: int
    audit_id: UUID
    correlation_id: UUID

    async def execute(self, statement: Executable) -> CursorResult[Any]:
        """Run one statement under this authorisation."""
        return await self.connection.execute(statement)


@dataclass(frozen=True, slots=True)
class UnitOfWork:
    """A transaction, and the audited write boundary over it.

    The connection is supplied rather than created: the caller owns the transaction, because a
    governed write is almost never the only thing in it — the state transition, the domain
    events and the outbox row it causes must commit or fail with it.
    """

    connection: AsyncConnection

    @asynccontextmanager
    async def governed(
        self,
        *,
        event_type: str,
        actor: Actor,
        authority: str,
        rule_id: str | None = None,
        case_id: UUID | None = None,
        track_id: UUID | None = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | None = None,
        correlation_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> AsyncIterator[GovernedWrite]:
        """Authorise the writes performed inside the block, and audit them first.

        ``authority`` says what permitted the change: a policy, a customer constraint, an
        explicit human approval, or nothing at all. ``NONE`` is a real answer — a physical fact
        a worker attested is authoritative without anyone approving it — and is recorded as
        such rather than dressed up as policy.
        """
        if authority not in AUTHORITIES:
            raise ValueError(f"unknown authority {authority!r}; expected one of {AUTHORITIES}")

        audit_id = uuid4()
        correlation = correlation_id or uuid4()
        values: dict[str, Any] = {
            "id": audit_id,
            "type": event_type,
            "actor_kind": actor.kind,
            "actor_id": actor.id,
            "authority": authority,
            "rule_id": rule_id,
            "case_id": case_id,
            "track_id": track_id,
            "before": None if before is None else dict(before),
            "after": None if after is None else dict(after),
            "provenance": dict(provenance or {}),
            "correlation_id": correlation,
        }
        if occurred_at is not None:
            values["occurred_at"] = occurred_at

        # ``xid`` is left to its server default: the transaction id has to be the database's own
        # answer, or the binding the trigger checks would be one the caller could write for it.
        statement = insert(AuditEvent).values(**values).returning(AuditEvent.seq)
        seq = (await self.connection.execute(statement)).scalar_one()

        await self.connection.execute(_SET_MARKER, {"marker": str(seq)})
        try:
            yield GovernedWrite(
                connection=self.connection,
                audit_seq=seq,
                audit_id=audit_id,
                correlation_id=correlation,
            )
        finally:
            # Best effort by design: a failed statement leaves the transaction aborted, and the
            # marker dies with it either way. Clearing matters for the case where the caller
            # recovers and carries on — the next write must take out its own authorisation.
            with suppress(SQLAlchemyError):
                await self.connection.execute(_CLEAR_MARKER)
