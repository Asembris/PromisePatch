"""Test support for physical exception intake: a database with today's deliveries in it.

The fixture is reloaded at **today's** anchor rather than at the suite's fixed one, and that is
load-bearing rather than incidental. "Today's raspberry delivery" is a claim about the bakery's
calendar day, so a dataset anchored in March cannot be answered by a suite running in September:
the interpreter would correctly find two open raspberry commitments and ask which one, and the
canonical path would never be reached. Anchoring on the bakery's own seven o'clock puts the
Valley Produce delivery at eight this morning and the next one at six tomorrow, which is the
shape the demo describes.

Reloading is safe for everything else: the round-trip suite already resets at several anchors,
and ``demo_state`` re-checks and reloads when it finds one it did not ask for.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy import update as sa_update

from promise_graph.examples import hollow_oak
from promisepatch.config import Settings
from promisepatch.db import RuntimeDatabase, build_engine
from promisepatch.db import events as ledger
from promisepatch.db.models import (
    AuditEvent,
    Case,
    CaseReport,
    CaseStep,
    CommitmentLine,
    DomainEvent,
    ExceptionClarification,
    ExceptionFact,
    InventoryLedgerEntry,
    PhysicalException,
)
from promisepatch.db.models import Worker as WorkerRow
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.domain import crash, intake
from promisepatch.domain.adapters import FakeEffectAdapter
from promisepatch.domain.identity import WorkerIdentity
from promisepatch.domain.observation import INTAKE_STEP_KINDS
from promisepatch.fixtures import demo
from promisepatch.fixtures.reset import reset_demo_state
from promisepatch.worker import Worker

BAKER = hollow_oak.BAKER
OWNER = hollow_oak.AUTHOR
RASPBERRY_LINE = hollow_oak.VP_TODAY_RASPBERRY
STRAWBERRY_LINE = hollow_oak.VP_TODAY_STRAWBERRY
STRAWBERRIES = hollow_oak.STRAWBERRIES
RASPBERRIES = hollow_oak.RASPBERRIES

CANONICAL_REPORT = "today's raspberry delivery didn't arrive"
RASPBERRY_ONLY = "just raspberries - the strawberries came"
WHOLE_DELIVERY = "the whole delivery didn't arrive"
CORRECTION = "Correction - the strawberries were missing too."
UNREADABLE = "the delivery situation is weird"

WORKFLOW_TABLES: tuple[str, ...] = ("case_steps", "timers", "outbox_messages", "inbox_events")


def bakery_anchor(settings: Settings) -> datetime:
    """Seven this morning, in the kitchen's timezone. Every fixture offset is measured from it."""
    zone = ZoneInfo(settings.bakery_tz)
    local = datetime.now(zone).replace(hour=7, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Intake:
    """A seeded database, a worker to drive it, and the reads every intake test makes."""

    database: RuntimeDatabase
    observed_at: datetime
    """One instant per test, so a redelivered command really does carry the same request.

    ``observed_at`` is part of what a report claims -- it says when the kitchen looked like
    this -- so it is part of the request hash. A helper that stamped a fresh ``now()`` on every
    call would make two deliveries of one command look like two different statements, which is
    the condition the conflict check exists to catch.
    """

    # ---------------------------------------------------------------------------- driving

    def worker(self, *, identity: str | None = None) -> Worker:
        """A worker process of its own, so two of them can be made to contend deliberately."""
        return Worker(
            database=self.database,
            adapter=FakeEffectAdapter(),
            identity=WorkerIdentity(identity) if identity else WorkerIdentity.create(),
        )

    async def drain(self, *, worker: Worker | None = None, limit: int = 16) -> None:
        """Run cycles until there is nothing outstanding, or the bound is reached."""
        runner = worker or self.worker()
        for _ in range(limit):
            if not await runner.run_once():
                return

    async def report(
        self,
        text_said: str = CANONICAL_REPORT,
        *,
        command_id: UUID | None = None,
        worker_id: str = BAKER,
        observed_at: datetime | None = None,
    ) -> intake.IntakeResult:
        return await intake.open_physical_exception(
            self.database,
            command_id=command_id or uuid4(),
            worker_id=worker_id,
            raw_text=text_said,
            observed_at=observed_at or self.observed_at,
        )

    async def answer(
        self,
        case_id: UUID,
        text_said: str,
        *,
        command_id: UUID | None = None,
        worker_id: str = BAKER,
    ) -> intake.IntakeResult:
        return await intake.answer_clarification(
            self.database,
            case_id=case_id,
            command_id=command_id or uuid4(),
            worker_id=worker_id,
            raw_text=text_said,
        )

    async def correct(
        self,
        case_id: UUID,
        text_said: str = CORRECTION,
        *,
        command_id: UUID | None = None,
        worker_id: str = BAKER,
    ) -> intake.IntakeResult:
        return await intake.correct_physical_fact(
            self.database,
            case_id=case_id,
            command_id=command_id or uuid4(),
            worker_id=worker_id,
            raw_text=text_said,
        )

    async def drain_intake(
        self, case_id: UUID, *, worker: Worker | None = None, limit: int = 16
    ) -> None:
        """Run cycles until this case's *intake* steps are settled, and stop there.

        A resolved intake enqueues impact analysis, so a plain drain carries the case all the
        way to ``PLANNED``. The assertions about what intake alone concluded need the boundary
        intake actually ends at, and steps are claimed oldest-first, so stopping as soon as no
        intake step is outstanding stops exactly there.
        """
        runner = worker or self.worker()
        for _ in range(limit):
            outstanding = await self.outstanding(case_id)
            if not any(step.kind in INTAKE_STEP_KINDS for step in outstanding):
                return
            if not await runner.run_once():
                return

    async def resolved_case(self) -> UUID:
        """The canonical path, driven to the point where both facts are attested."""
        opened = await self.report()
        await self.drain()
        await self.answer(opened.case_id, RASPBERRY_ONLY)
        await self.drain()
        return opened.case_id

    async def attested_case(self) -> UUID:
        """The same path, stopped the instant intake is done and before anything is analysed."""
        opened = await self.report()
        await self.drain_intake(opened.case_id)
        await self.answer(opened.case_id, RASPBERRY_ONLY)
        await self.drain_intake(opened.case_id)
        return opened.case_id

    @asynccontextmanager
    async def another_baker(self, worker_id: str = "sam") -> AsyncIterator[str]:
        """A second baker, for the length of one test, and then gone again.

        ``workers`` is shared demo state that other suites assert the exact shape of, so this
        puts the table back the way it found it rather than leaving the row for whichever
        fixture reset happens to notice next. A test that dirties state other tests read is a
        test that fails somebody else's assertion in a later run, from a different file.
        """
        await self._set_worker(worker_id, present=True)
        try:
            yield worker_id
        finally:
            await self._set_worker(worker_id, present=False)

    async def _set_worker(self, worker_id: str, *, present: bool) -> None:
        async with self.database.begin() as connection:
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="INTAKE_TEST_SETUP",
                actor=Actor(kind="SYSTEM", id="intake-tests"),
                authority="NONE",
            ) as write:
                statement = (
                    insert(WorkerRow).values(
                        id=worker_id,
                        username=worker_id,
                        display_name=worker_id.capitalize(),
                        role="baker",
                        password_hash="unusable",
                        created_at=datetime.now(UTC),
                    )
                    if present
                    else delete(WorkerRow).where(WorkerRow.id == worker_id)
                )
                await write.execute(statement)

    # ---------------------------------------------------------------------------- reading

    async def case(self, case_id: UUID) -> Any:
        async with self.database.connect() as connection:
            return (await connection.execute(select(Case).where(Case.id == case_id))).one_or_none()

    async def line(self, line_id: str) -> Any:
        async with self.database.connect() as connection:
            return (
                await connection.execute(select(CommitmentLine).where(CommitmentLine.id == line_id))
            ).one()

    async def reports(self, case_id: UUID) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(CaseReport)
                        .where(CaseReport.case_id == case_id)
                        .order_by(CaseReport.ordinal)
                    )
                ).all()
            )

    async def clarifications(self, case_id: UUID) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(ExceptionClarification)
                        .where(ExceptionClarification.case_id == case_id)
                        .order_by(ExceptionClarification.ordinal)
                    )
                ).all()
            )

    async def facts(self, case_id: UUID) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(ExceptionFact)
                        .join(Case, Case.exception_id == ExceptionFact.exception_id)
                        .where(Case.id == case_id)
                        .order_by(ExceptionFact.attested_at, ExceptionFact.target_id)
                    )
                ).all()
            )

    async def exception(self, case_id: UUID) -> Any:
        async with self.database.connect() as connection:
            return (
                await connection.execute(
                    select(PhysicalException)
                    .join(Case, Case.exception_id == PhysicalException.id)
                    .where(Case.id == case_id)
                )
            ).one_or_none()

    async def postings(self, resource_id: str) -> list[Any]:
        """Every physical movement of one resource that is not the fixture's opening balance."""
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(InventoryLedgerEntry)
                        .where(
                            InventoryLedgerEntry.resource_id == resource_id,
                            InventoryLedgerEntry.source_kind != "FIXTURE",
                        )
                        .order_by(InventoryLedgerEntry.seq)
                    )
                ).all()
            )

    async def on_hand(self, resource_id: str) -> Any:
        async with self.database.connect() as connection:
            return await connection.scalar(
                select(func.coalesce(func.sum(InventoryLedgerEntry.delta), 0)).where(
                    InventoryLedgerEntry.resource_id == resource_id
                )
            )

    async def steps(self, case_id: UUID) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(CaseStep)
                        .where(CaseStep.case_id == case_id)
                        .order_by(CaseStep.created_at, CaseStep.id)
                    )
                ).all()
            )

    async def events(self, case_id: UUID) -> list[str]:
        async with self.database.connect() as connection:
            rows = (
                await connection.execute(
                    select(DomainEvent.type)
                    .where(DomainEvent.case_id == case_id)
                    .order_by(DomainEvent.seq)
                )
            ).scalars()
        return list(rows)

    async def audits(self, case_id: UUID) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(AuditEvent)
                        .where(AuditEvent.case_id == case_id)
                        .order_by(AuditEvent.seq)
                    )
                ).all()
            )

    async def latest_event_seq(self) -> int:
        async with self.database.connect() as connection:
            return await ledger.latest_seq(connection)

    async def events_after(self, seq: int) -> list[Any]:
        async with self.database.connect() as connection:
            return list(await ledger.read_after(connection, after_seq=seq, limit=500))

    # ---------------------------------------------------------------------------- nudging

    async def expire_lease(self, step_id: UUID) -> None:
        """Age a claim out without waiting for it: leases are compared against the DB clock."""
        async with self.database.begin() as connection:
            await connection.execute(
                sa_update(CaseStep)
                .where(CaseStep.id == step_id)
                .values(lease_expires_at=text("now() - interval '1 second'"))
            )

    async def outstanding(self, case_id: UUID) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(CaseStep)
                        .where(
                            CaseStep.case_id == case_id,
                            CaseStep.state.in_(("PENDING", "RETRYING", "IN_FLIGHT")),
                        )
                        .order_by(CaseStep.created_at)
                    )
                ).all()
            )


async def _seed(settings: Settings) -> None:
    """Load the dataset at today's anchor, as the migration role, and clear the engine's work."""
    engine = build_engine(settings.require_migration_database_url(), pool_size=1)
    try:
        async with engine.begin() as connection:
            for table in WORKFLOW_TABLES:
                await connection.execute(text(f'DELETE FROM promisepatch."{table}"'))
            await reset_demo_state(
                connection,
                anchor=bakery_anchor(settings),
                now=datetime.now(UTC),
                passwords={
                    demo.BAKER_ROLE: settings.require_demo_worker_password(),
                    demo.OWNER_ROLE: settings.require_demo_owner_password(),
                },
                actor=Actor(kind="SYSTEM", id="intake-tests"),
            )
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def physical() -> AsyncIterator[Intake]:
    """A database holding today's Hollow Oak, with no case and no outstanding work.

    Reset per test rather than per session: these tests settle deliveries and post stock, and a
    test that inherited another's settled lines would be asserting about somebody else's
    kitchen.
    """
    settings = Settings()
    if settings.migration_database_url is None:
        pytest.skip("PP_MIGRATION_DATABASE_URL is not set; intake tests need a database")
    if settings.database_url is None:
        pytest.skip("PP_DATABASE_URL is not set; intake tests need the runtime connection")
    if settings.demo_worker_password is None or settings.demo_owner_password is None:
        pytest.skip("PP_DEMO_WORKER_PASSWORD / PP_DEMO_OWNER_PASSWORD are not set")
    if not settings.allow_fixture_reset:
        pytest.skip("PP_ALLOW_FIXTURE_RESET is not true; refusing to reset this database")

    await _seed(settings)
    crash.clear()
    database = RuntimeDatabase.from_settings(settings)
    try:
        yield Intake(database=database, observed_at=datetime.now(UTC))
    finally:
        crash.clear()
        await database.dispose()


def within(moment: datetime, *, of: datetime, seconds: int = 300) -> bool:
    return abs((moment - of).total_seconds()) <= seconds


def hours(count: int) -> timedelta:
    return timedelta(hours=count)
