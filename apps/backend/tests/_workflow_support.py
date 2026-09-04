"""Test support for the durable workflow: a clean engine, and the reads every test makes.

A module rather than part of ``conftest`` because the fixture hands back an object whose methods
the tests call, and a type they cannot import is a type they cannot annotate. The backend test
directory is deliberately not a package -- the engine suite already owns the ``tests`` name --
so this is reachable instead through the ``pythonpath`` entry in ``pyproject.toml``, under a
name nothing else in the workspace uses.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import func, insert, select, text
from sqlalchemy import update as sa_update

from promisepatch.db import RuntimeDatabase
from promisepatch.db import events as ledger
from promisepatch.db.clock import database_now
from promisepatch.db.models import AuditEvent, Case, CaseStep, OutboxMessage
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.domain import crash
from promisepatch.domain.steps import enqueue_step

WORKFLOW_TABLES: tuple[str, ...] = ("case_steps", "timers", "outbox_messages", "inbox_events")
"""The engine's own bookkeeping, emptied between workflow tests.

All four are ungoverned, so the runtime role may clear them and a test does not have to take
out an audit event to get a clean slate. Emptying them matters more than it looks: a claim
sweep is global, so one test's leftover ``PENDING`` step would be picked up by the next test's
worker and make its assertions describe somebody else's work.

``cases``, ``audit_events`` and ``domain_events`` are deliberately left alone. The first is
governed, and the last two are ledgers of record that nothing may erase -- which is why every
assertion about them here is made relative to a sequence read at the start of the test.
"""

WORKFLOW_ACTOR = Actor(kind="SYSTEM", id="workflow-tests")


@dataclass(frozen=True, slots=True)
class Workflow:
    """A clean engine, a database handle, and the few reads every workflow test makes."""

    database: RuntimeDatabase

    async def create_case(self, *, state: str = "EXECUTING") -> UUID:
        """A case to hang steps off. Governed, like every other write to ``cases``."""
        case_id = uuid4()
        async with self.database.begin() as connection:
            now = await database_now(connection)
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="WORKFLOW_TEST_SETUP",
                actor=WORKFLOW_ACTOR,
                authority="NONE",
                case_id=case_id,
            ) as write:
                await write.execute(
                    insert(Case).values(
                        id=case_id,
                        state=state,
                        opened_by="workflow-tests",
                        opened_at=now,
                        updated_at=now,
                        version=1,
                    )
                )
        return case_id

    async def set_case_state(self, case_id: UUID, state: str) -> None:
        async with self.database.begin() as connection:
            now = await database_now(connection)
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="WORKFLOW_TEST_SETUP",
                actor=WORKFLOW_ACTOR,
                authority="NONE",
                case_id=case_id,
            ) as write:
                await write.execute(
                    sa_update(Case).where(Case.id == case_id).values(state=state, updated_at=now)
                )

    async def add_step(
        self,
        case_id: UUID,
        *,
        step_key: str,
        kind: str,
        next_attempt_at: datetime | None = None,
    ) -> UUID:
        async with self.database.begin() as connection:
            created = await enqueue_step(
                connection,
                case_id=case_id,
                step_key=step_key,
                kind=kind,
                next_attempt_at=next_attempt_at,
            )
        assert created is not None
        return created

    async def expire_lease(self, step_id: UUID) -> None:
        """Age a lease out without waiting for it.

        The lease is compared against the *database's* clock, so moving the expiry into the past
        is exactly equivalent to time passing -- and is deterministic, which sleeping is not.
        """
        await self._age(CaseStep, step_id, "lease_expires_at")

    async def expire_effect_lease(self, effect_id: UUID) -> None:
        await self._age(OutboxMessage, effect_id, "lease_expires_at")

    async def make_due(self, step_id: UUID) -> None:
        """Bring a scheduled retry forward to now, again without sleeping."""
        await self._age(CaseStep, step_id, "next_attempt_at")

    async def make_effect_due(self, effect_id: UUID) -> None:
        await self._age(OutboxMessage, effect_id, "next_attempt_at")

    async def _age(self, model: Any, identifier: Any, column: str) -> None:
        async with self.database.begin() as connection:
            await connection.execute(
                sa_update(model)
                .where(model.id == identifier)
                .values(**{column: text("now() - interval '1 second'")})
            )

    async def row(self, model: Any, identifier: Any) -> Any:
        async with self.database.connect() as connection:
            return (
                await connection.execute(select(model).where(model.id == identifier))
            ).one_or_none()

    async def rows(self, model: Any, **filters: Any) -> list[Any]:
        statement = select(model)
        for column, value in filters.items():
            statement = statement.where(getattr(model, column) == value)
        async with self.database.connect() as connection:
            return list((await connection.execute(statement)).all())

    async def case(self, case_id: UUID) -> Any:
        return await self.row(Case, case_id)

    async def latest_event_seq(self) -> int:
        async with self.database.connect() as connection:
            return await ledger.latest_seq(connection)

    async def events_since(self, seq: int) -> list[Any]:
        async with self.database.connect() as connection:
            return list(await ledger.read_after(connection, after_seq=seq, limit=500))

    async def latest_audit_seq(self) -> int:
        async with self.database.connect() as connection:
            value = await connection.scalar(select(func.coalesce(func.max(AuditEvent.seq), 0)))
        return int(value or 0)

    async def audits_since(self, seq: int, *, case_id: UUID | None = None) -> list[Any]:
        statement = select(AuditEvent).where(AuditEvent.seq > seq)
        if case_id is not None:
            statement = statement.where(AuditEvent.case_id == case_id)
        async with self.database.connect() as connection:
            return list((await connection.execute(statement.order_by(AuditEvent.seq))).all())


@pytest_asyncio.fixture
async def workflow(database: RuntimeDatabase) -> AsyncIterator[Workflow]:
    """An engine with no work outstanding, before the test and after it."""
    await _empty_workflow_tables(database)
    crash.clear()
    try:
        yield Workflow(database=database)
    finally:
        crash.clear()
        await _empty_workflow_tables(database)


async def _empty_workflow_tables(database: RuntimeDatabase) -> None:
    async with database.begin() as connection:
        for table in WORKFLOW_TABLES:
            await connection.execute(text(f'DELETE FROM promisepatch."{table}"'))
