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

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from _database_safety import migration_database_url
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy import update as sa_update

from promise_graph.classification import analyze as engine_analyze
from promise_graph.examples import hollow_oak
from promise_graph.model import ExceptionCategory
from promise_graph.model import PhysicalException as EnginePhysicalException
from promise_graph.snapshot import GraphSnapshot, reservations_for_line
from promisepatch.config import Settings
from promisepatch.db import RuntimeDatabase, build_engine
from promisepatch.db import events as ledger
from promisepatch.db.base import SCHEMA, metadata
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    Case,
    CaseReport,
    CaseStep,
    CommitmentLine,
    DomainEvent,
    ExceptionClarification,
    ExceptionFact,
    FixtureState,
    InboundReply,
    InventoryLedgerEntry,
    Order,
    OrderConstraint,
    OrderLine,
    OutboxMessage,
    PhysicalException,
    ProductionTask,
    Promise,
    RecipeVersion,
    RecoveryOption,
    Reservation,
    Timer,
    Track,
    TrackPath,
    TrackWatch,
)
from promisepatch.db.models import Worker as WorkerRow
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.domain import analysis, approvals, crash, handlers, intake, recovery
from promisepatch.domain import inbox as inbox_ledger
from promisepatch.domain.adapters import FakeEffectAdapter
from promisepatch.domain.identity import WorkerIdentity
from promisepatch.domain.observation import INTAKE_STEP_KINDS
from promisepatch.domain.outbox import EffectAdapter
from promisepatch.fixtures import demo
from promisepatch.fixtures.projection import TableRows
from promisepatch.fixtures.reset import reset_demo_state
from promisepatch.semantic import FakeSemanticProvider, SemanticProvider
from promisepatch.worker import Worker

BAKER = hollow_oak.BAKER
OWNER = hollow_oak.AUTHOR
RASPBERRY_LINE = hollow_oak.VP_TODAY_RASPBERRY
STRAWBERRY_LINE = hollow_oak.VP_TODAY_STRAWBERRY
STRAWBERRIES = hollow_oak.STRAWBERRIES
RASPBERRIES = hollow_oak.RASPBERRIES


def _channel_for(promise_id: str) -> str:
    """The approval channel behind one promise, read out of the fixture rather than restated.

    A literal here would be a second copy of the customer's identity, and the day the fixture
    moved a chat id the tests would keep passing against a customer who no longer exists.
    """
    graph = hollow_oak.hollow_oak()
    order = graph.orders[graph.promises[promise_id].order_id]
    return graph.customers[order.customer_id].approval_channel


TOMAS_CHANNEL = _channel_for(hollow_oak.PROMISE_B)
"""The only identity whose reply can authorise the change to promise B."""

CANONICAL_REPORT = "today's raspberry delivery didn't arrive"
RASPBERRY_ONLY = "just raspberries - the strawberries came"
WHOLE_DELIVERY = "the whole delivery didn't arrive"
CORRECTION = "Correction - the strawberries were missing too."
UNREADABLE = "the delivery situation is weird"

WORKFLOW_TABLES: tuple[str, ...] = ("case_steps", "timers", "outbox_messages", "inbox_events")

ORDER_BOOK: tuple[Any, ...] = (
    Order,
    OrderLine,
    Reservation,
    ProductionTask,
    RecipeVersion,
    Promise,
)
"""The tables analysis and planning must never write. Read before, compared after."""


def bakery_anchor(settings: Settings) -> datetime:
    """An anchor that keeps the fixture's working day ahead of the clock, at any hour.

    The dataset is day-shaped: a delivery an hour in, ovens running through the afternoon, and
    the next delivery the following morning. Two things have to stay true of it whatever time
    the suite runs, and a fixed "seven this morning" only kept the first.

    * **Today's delivery has to be today.** The interpreter resolves "today's raspberry
      delivery" against the bakery's calendar day (:func:`~promisepatch.domain.physical.
      bakery_day`), so that delivery must fall inside the day and the next one must fall
      outside it -- otherwise the canonical sentence is genuinely ambiguous and the reading
      stops to ask which delivery was meant.
    * **The day's work has to still be ahead.** Equipment propagation intersects an outage with
      ``[now, outage_until]``, so a suite running at nine in the evening against a fixture whose
      ovens finished at nine finds nothing affected -- correctly. Every test about what an
      outage reaches would then pass by describing an empty kitchen, which is the worst way for
      one to pass.

    Anchoring two hours behind the clock satisfies both: the delivery was due an hour ago and
    did not arrive, and every production task is still in front of the kitchen. The floor an
    hour past midnight is what stops the *next* delivery, twenty-three hours out, from landing
    back inside today and turning one raspberry commitment into two.
    """
    zone = ZoneInfo(settings.bakery_tz)
    now = datetime.now(UTC)
    day_start = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(now - timedelta(hours=2), (day_start + timedelta(hours=1)).astimezone(UTC))


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

    def worker(
        self,
        *,
        identity: str | None = None,
        adapter: EffectAdapter | None = None,
        fetch: Any = None,
        semantic: SemanticProvider | None = None,
    ) -> Worker:
        """A worker process of its own, so two of them can be made to contend deliberately.

        The adapter is injectable because the provider's memory is where half of the
        crash-safety assertions live: how many transport calls it saw, and how many logical
        effects those became. ``fetch`` is the authoritative order read, present only for a
        deployment that has an order system to ask. ``semantic`` is where a sentence the
        deterministic lexicon cannot read is sent; unscripted, it binds nothing, so a test that
        does not mention a model gets a worker whose model understands nothing.
        """
        return Worker(
            database=self.database,
            adapter=adapter or FakeEffectAdapter(),
            identity=WorkerIdentity(identity) if identity else WorkerIdentity.create(),
            semantic=semantic or FakeSemanticProvider(),
            fetch_order=fetch,
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

    async def drain_until_decided(self, *, limit: int = 30, worker: Worker | None = None) -> None:
        """Run cycles until a customer decision exists, and stop on that boundary.

        The instant after consent is recorded and before anything has been revalidated is a real
        moment in the workflow, and several guarantees are about exactly it: an approval is
        authority, not application. A plain drain runs straight past it, so this stops there.
        """
        runner = worker or self.worker()
        for _ in range(limit):
            if await self.decisions():
                return
            if not await runner.run_once():
                return

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

    async def plan_id(self, case_id: UUID) -> str:
        """The identity of the plan this case offers now, read the way a surface would read it.

        Through :func:`analysis.read_case_status` on purpose: it is the value a worker would
        have been shown, so a test that confirms with it is confirming the plan somebody read
        rather than one it computed for itself out of the rows it is about to assert on.
        """
        status = await analysis.read_case_status(self.database, case_id=case_id)
        return status.plan_id

    async def confirm(
        self,
        case_id: UUID,
        *,
        worker_id: str = BAKER,
        command_id: UUID | None = None,
        plan_id: str | None = None,
    ) -> recovery.ConfirmationResult:
        """A worker's yes, through the same reusable command the CLI and the MCP tool call.

        ``plan_id`` defaults to the plan the case is currently offering, which is what a
        worker confirming what they just read would quote. A test about staleness passes a
        different one deliberately.
        """
        return await recovery.confirm_plan(
            self.database,
            case_id=case_id,
            command_id=command_id or uuid4(),
            worker_id=worker_id,
            plan_id=plan_id if plan_id is not None else await self.plan_id(case_id),
        )

    @asynccontextmanager
    async def another_baker(self, worker_id: str = "sam") -> AsyncIterator[str]:
        """A second baker, for the length of one test, and then gone again.

        ``workers`` is shared demo state that other suites assert the exact shape of, so this
        puts the table back the way it found it rather than leaving the row for whichever
        fixture reset happens to notice next. A test that dirties state other tests read is a
        test that fails somebody else's assertion in a later run, from a different file.
        """
        async with self.another_worker(worker_id, role="baker") as present:
            yield present

    @asynccontextmanager
    async def another_worker(self, worker_id: str, *, role: str) -> AsyncIterator[str]:
        """One more principal of any declared role, for the length of one test.

        The role is a parameter because "who may speak on a case" is a question about roles, and
        a helper that could only make bakers could only ask a third of it.
        """
        await self._set_worker(worker_id, role=role, present=True)
        try:
            yield worker_id
        finally:
            await self._set_worker(worker_id, role=role, present=False)

    async def reopen_as(self, case_id: UUID, worker_id: str) -> None:
        """Rewrite who opened a case, to construct a state the domain should not be able to reach.

        Only a test may do this, and only for the narrow purpose of asserting that a defence
        holds even when the condition it defends against has somehow come about anyway. Nothing
        in production writes ``opened_by`` after a case exists.
        """
        async with self.database.begin() as connection:
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="INTAKE_TEST_SETUP",
                actor=Actor(kind="SYSTEM", id="intake-tests"),
                authority="NONE",
                case_id=case_id,
            ) as write:
                await write.execute(
                    sa_update(Case).where(Case.id == case_id).values(opened_by=worker_id)
                )

    async def _set_worker(self, worker_id: str, *, role: str, present: bool) -> None:
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
                        role=role,
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

    async def latest_audit_seq(self) -> int:
        async with self.database.connect() as connection:
            value = await connection.scalar(select(func.coalesce(func.max(AuditEvent.seq), 0)))
        return int(value or 0)

    async def latest_event_seq(self) -> int:
        async with self.database.connect() as connection:
            return await ledger.latest_seq(connection)

    async def events_after(self, seq: int) -> list[Any]:
        async with self.database.connect() as connection:
            return list(await ledger.read_after(connection, after_seq=seq, limit=500))

    # ---------------------------------------------------------------------------- nudging

    async def make_work_due(self) -> None:
        """Bring every backed-off step and effect forward to now.

        A retry ladder is a real wait measured against the database clock, and a test that slept
        through one would be slow and, worse, timing-dependent. What the tests here are about is
        what happens *when* the retry runs, so the delay is removed rather than waited out.
        """
        async with self.database.begin() as connection:
            await connection.execute(
                sa_update(CaseStep)
                .where(CaseStep.state == "RETRYING")
                .values(next_attempt_at=text("now()"))
            )
            await connection.execute(
                sa_update(OutboxMessage)
                .where(OutboxMessage.state == "PENDING")
                .values(next_attempt_at=text("now()"))
            )

    async def expire_lease(self, step_id: UUID) -> None:
        """Age a claim out without waiting for it: leases are compared against the DB clock."""
        async with self.database.begin() as connection:
            await connection.execute(
                sa_update(CaseStep)
                .where(CaseStep.id == step_id)
                .values(lease_expires_at=text("now() - interval '1 second'"))
            )

    async def rows_of(self, model: Any) -> list[Any]:
        """Every row of one table, for count and emptiness assertions."""
        async with self.database.connect() as connection:
            return list((await connection.execute(select(model))).all())

    # ------------------------------------------------------------------- analysis reads

    async def tracks(self, case_id: UUID) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(Track).where(Track.case_id == case_id).order_by(Track.promise_id)
                    )
                ).all()
            )

    async def track(self, case_id: UUID, promise_id: str) -> Any:
        async with self.database.connect() as connection:
            return (
                await connection.execute(
                    select(Track).where(Track.case_id == case_id, Track.promise_id == promise_id)
                )
            ).one_or_none()

    async def options(self, track_id: UUID) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(RecoveryOption)
                        .where(RecoveryOption.track_id == track_id)
                        .order_by(RecoveryOption.id)
                    )
                ).all()
            )

    async def paths(self, track_id: UUID) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(TrackPath)
                        .where(TrackPath.track_id == track_id)
                        .order_by(TrackPath.ordinal)
                    )
                ).all()
            )

    async def watch(self, track_id: UUID) -> list[tuple[str, str]]:
        async with self.database.connect() as connection:
            rows = (
                await connection.execute(
                    select(TrackWatch.entity_type, TrackWatch.entity_id).where(
                        TrackWatch.track_id == track_id
                    )
                )
            ).all()
        return sorted((row.entity_type, row.entity_id) for row in rows)

    async def effects(self) -> list[Any]:
        """Every outbound effect in the database, oldest first."""
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(OutboxMessage).order_by(OutboxMessage.created_at, OutboxMessage.id)
                    )
                ).all()
            )

    async def effects_for(self, track_id: UUID) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(OutboxMessage)
                        .where(OutboxMessage.payload["track_id"].astext == str(track_id))
                        .order_by(OutboxMessage.created_at)
                    )
                ).all()
            )

    async def tasks(self) -> dict[str, tuple[str, Any]]:
        """Every production task's state and holder, for the writes a blocked track performs."""
        async with self.database.connect() as connection:
            rows = (await connection.execute(select(ProductionTask))).all()
        return {row.id: (row.state, row.held_by_case_id) for row in rows}

    # ------------------------------------------------------------------ consent protocol

    async def requests(self) -> list[Any]:
        """Every approval request in the database, oldest first."""
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(ApprovalRequest).order_by(ApprovalRequest.sent_at)
                    )
                ).all()
            )

    async def request_for(self, track_id: UUID) -> Any:
        async with self.database.connect() as connection:
            return (
                await connection.execute(
                    select(ApprovalRequest).where(ApprovalRequest.track_id == track_id)
                )
            ).one_or_none()

    async def decisions(self) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(ApprovalDecision).order_by(ApprovalDecision.received_at)
                    )
                ).all()
            )

    async def replies(self) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(InboundReply).order_by(InboundReply.received_at)
                    )
                ).all()
            )

    async def timers(self) -> list[Any]:
        async with self.database.connect() as connection:
            return list((await connection.execute(select(Timer).order_by(Timer.due_at))).all())

    async def deliver_reply(
        self,
        request_id: UUID,
        text_said: str,
        *,
        sender: str = TOMAS_CHANNEL,
        event_id: str | None = None,
    ) -> str:
        """Put one customer reply on the transport, exactly as the fake channel would.

        Nothing is decided here and nothing may be: this writes the raw material to
        ``inbox_events`` and returns the provider's id for it. A test that wanted a decision has
        to run the worker, which is the only path a reply can take to become one.
        """
        delivery = event_id or f"msg-{uuid4()}"
        async with self.database.begin() as connection:
            await inbox_ledger.ingest(
                connection,
                source=handlers.CUSTOMER_REPLY_SOURCE,
                provider_event_id=delivery,
                body=json.dumps(
                    {
                        "request_id": str(request_id),
                        "sender": sender,
                        "text": text_said,
                        "provider_message_id": delivery,
                    }
                ),
            )
        return delivery

    async def close_window(self, request_id: UUID) -> None:
        """Move an approval deadline into the past, and its timer with it.

        Deterministic where sleeping is not: the deadline is compared against the *database's*
        clock, so moving the row backwards is exactly equivalent to the window having closed.
        """
        async with self.database.begin() as connection:
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="APPROVAL_TEST_SETUP",
                actor=Actor(kind="SYSTEM", id="approval-tests"),
                authority="NONE",
            ) as write:
                # ``sent_at`` moves with it: the table's own ``deadline > sent_at`` check is
                # the record that no request was ever sent into a closed window, and a helper
                # that could violate it would be rewriting history rather than advancing time.
                await write.execute(
                    sa_update(ApprovalRequest)
                    .where(ApprovalRequest.id == request_id)
                    .values(
                        sent_at=text("now() - interval '2 seconds'"),
                        deadline=text("now() - interval '1 second'"),
                    )
                )
            await connection.execute(
                sa_update(Timer)
                .where(Timer.subject_id == str(request_id), Timer.fired_at.is_(None))
                .values(due_at=text("now() - interval '1 second'"))
            )

    async def close_planning_window(self, track_id: UUID) -> None:
        """Move a track's planned approval window into the past, before anything is asked."""
        async with self.database.begin() as connection:
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="APPROVAL_TEST_SETUP",
                actor=Actor(kind="SYSTEM", id="approval-tests"),
                authority="NONE",
            ) as write:
                await write.execute(
                    sa_update(Track)
                    .where(Track.id == track_id)
                    .values(deadline_at=text("now() - interval '1 second'"))
                )

    async def expire_effect_lease(self, effect_id: UUID) -> None:
        """Age an outbox claim out without waiting: leases compare against the DB clock."""
        await self._age_effect(effect_id, "lease_expires_at")

    async def make_effect_due(self, effect_id: UUID) -> None:
        await self._age_effect(effect_id, "next_attempt_at")

    async def _age_effect(self, effect_id: UUID, column: str) -> None:
        async with self.database.begin() as connection:
            await connection.execute(
                sa_update(OutboxMessage)
                .where(OutboxMessage.id == effect_id)
                .values(**{column: text("now() - interval '1 second'")})
            )

    async def snapshot(self) -> GraphSnapshot:
        """The same whole-graph read the analysis worker makes, for direct engine comparison."""
        async with self.database.connect() as connection:
            return await analysis.fresh_snapshot(connection)

    async def engine_analysis(
        self, case_id: UUID, *, now: datetime | None = None
    ) -> tuple[GraphSnapshot, Any]:
        """Run ``promise_graph`` directly against the persisted graph and the case's exception.

        The comparison the equivalence tests make is only worth anything if this side of it
        reads no backend answer: the snapshot, the exception and the classification all come
        from the engine's own code path, and only the raw rows are shared.
        """
        row = await self.exception(case_id)
        assert row is not None
        graph = await self.snapshot()
        exception = EnginePhysicalException(
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
        return graph, engine_analyze(graph, exception, now or datetime.now(UTC))

    # ------------------------------------------------------------- order-system stand-ins

    async def order_book(self) -> dict[str, list[tuple[Any, ...]]]:
        """Every row of the tables a plan must not touch, as comparable tuples."""
        captured: dict[str, list[tuple[Any, ...]]] = {}
        async with self.database.connect() as connection:
            for model in ORDER_BOOK:
                table = model.__table__
                rows = (await connection.execute(select(table).order_by(*table.primary_key))).all()
                captured[table.name] = [tuple(row) for row in rows]
        return captured

    async def repin_order_line(
        self, line_id: str, version_id: str, *, bump_order: bool = True
    ) -> None:
        """Re-pin one line to another authored version, the way the order system will.

        Reservations are recomputed through the engine's own derivation rather than written by
        hand, so the mutated database still satisfies invariant 11.4.3: a line's reservations
        are its pinned version times its quantity.

        ``bump_order`` is on by default because a real order-system amendment moves the order's
        version with it. A revalidation test that wants to prove the *pinned version* check on
        its own turns it off, so the lower-numbered order check cannot claim the failure first
        and leave the interesting one untested.
        """
        graph = await self.snapshot()
        order_line = graph.order_lines[line_id]
        version = graph.versions[version_id]
        derived = reservations_for_line(
            order_line.model_copy(update={"recipe_version_id": version_id}),
            version,
            graph.resources,
        )
        async with self.database.begin() as connection:
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="ORDER_SYSTEM_TEST_MUTATION",
                actor=Actor(kind="SYSTEM", id="order-system-stand-in"),
                authority="NONE",
            ) as write:
                await write.execute(
                    sa_update(OrderLine)
                    .where(OrderLine.id == line_id)
                    .values(recipe_version_id=version_id)
                )
                await write.execute(delete(Reservation).where(Reservation.order_line_id == line_id))
                for reservation in derived:
                    await write.execute(
                        insert(Reservation).values(
                            id=reservation.id,
                            order_line_id=reservation.order_line_id,
                            resource_id=reservation.resource_id,
                            quantity=reservation.quantity,
                            source_recipe_version_id=reservation.source_recipe_version_id,
                        )
                    )
                if bump_order:
                    await write.execute(
                        sa_update(Order)
                        .where(Order.id == order_line.order_id)
                        .values(
                            external_version=Order.external_version + 1,
                            state="AMENDED",
                            updated_at=datetime.now(UTC),
                        )
                    )

    async def fixture_anchor(self) -> datetime:
        """The instant this database's fixture was loaded at, read from the fixture's own row.

        Anything that wants to extend the seeded graph has to build its addition at the same
        anchor the rest of it was built at, and the anchor is a per-run value rather than a
        constant. Recomputing it would be a second guess at something the database already
        knows.
        """
        async with self.database.connect() as connection:
            return (await connection.execute(select(FixtureState.anchor_at))).scalar_one()

    async def author(self, tables: Sequence[TableRows]) -> None:
        """Add authored rows to the graph, the way an owner authoring a variant beforehand does.

        A governed write like every other fixture mutation, so a recipe version that exists
        because a person authored it carries provenance. This is emphatically not a runtime
        creation: nothing in PromisePatch ever derives or synthesises a version, and the whole
        recovery model rests on every one of them having been authored in advance. This helper
        *is* that advance.
        """
        async with self.database.begin() as connection:
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="AUTHORING_TEST_SETUP",
                actor=Actor(kind="SYSTEM", id="authoring-tests"),
                authority="NONE",
            ) as write:
                for table_rows in tables:
                    if not table_rows.rows:
                        continue
                    table = metadata.tables[f"{SCHEMA}.{table_rows.table}"]
                    await write.execute(
                        insert(table).values([dict(row) for row in table_rows.rows])
                    )

    async def set_constraint_kind(self, constraint_id: str, kind: str) -> None:
        """Rewrite one snapshotted order constraint, the way an owner amending an order would.

        A governed write like any other, so the mutated row still carries its provenance and the
        constraint hash still describes something a human recorded.
        """
        await self._governed(
            sa_update(OrderConstraint)
            .where(OrderConstraint.id == constraint_id)
            .values(kind=kind, recorded_at=datetime.now(UTC))
        )

    async def consume_stock(self, resource_id: str, quantity: str) -> None:
        """Post a negative physical movement, as a correcting attestation would.

        The ledger is append-only and this is a row on it, which is the only way a quantity ever
        changes: nothing edits ``on_hand`` because there is no such column.
        """
        await self._governed(
            insert(InventoryLedgerEntry).values(
                resource_id=resource_id,
                delta=Decimal(quantity),
                source_kind="CORRECTION",
                source_id=f"test-consumption-{uuid4()}",
                recorded_at=datetime.now(UTC),
            )
        )

    async def set_task_state(self, line_id: str, state: str) -> None:
        """Move one production task on, the way the kitchen starting work would."""
        await self._governed(
            sa_update(ProductionTask)
            .where(ProductionTask.order_line_id == line_id)
            .values(state=state)
        )

    async def bring_task_start_forward(self, line_id: str) -> None:
        """Put a task's scheduled start in the past, against the database's own clock."""
        await self._governed(
            sa_update(ProductionTask)
            .where(ProductionTask.order_line_id == line_id)
            .values(scheduled_start=text("now() - interval '1 minute'"))
        )

    async def hold_task_for(self, line_id: str, case_id: UUID) -> None:
        """Put a task on hold in the name of one case, the way a blocked promise does (§13.5)."""
        await self._governed(
            sa_update(ProductionTask)
            .where(ProductionTask.order_line_id == line_id)
            .values(state="HELD", held_by_case_id=case_id)
        )

    async def task_of_line(self, line_id: str) -> Any:
        async with self.database.connect() as connection:
            return (
                await connection.execute(
                    select(ProductionTask).where(ProductionTask.order_line_id == line_id)
                )
            ).one_or_none()

    async def constraints_of(self, order_id: str) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(OrderConstraint)
                        .where(OrderConstraint.order_id == order_id)
                        .order_by(OrderConstraint.id)
                    )
                ).all()
            )

    # ------------------------------------------------- deliberately corrupted consent records

    async def rewrite_decision_sender(self, request_id: UUID, sender: str) -> None:
        """Try to rewrite the sender a persisted decision claims. Nothing may do this.

        Attempted through the *migration* role, which is as much authority as exists anywhere in
        the deployment, so what refuses it is the append-only trigger rather than a grant. The
        caller is expected to catch the refusal: that is the assertion.
        """
        await self._privileged(
            sa_update(ApprovalDecision)
            .where(ApprovalDecision.request_id == request_id)
            .values(sender_identity=sender)
        )

    async def corrupt_reply_sender(self, request_id: UUID, sender: str) -> None:
        """Rewrite the stored reply behind a decision, leaving the decision's own copy intact.

        ``inbound_replies`` is not an append-only ledger -- a later slice attaches a model's
        non-authoritative reading to it -- so this is genuinely reachable, and revalidation has
        to survive a provenance chain that no longer joins up.
        """
        await self._privileged(
            sa_update(InboundReply)
            .where(InboundReply.request_id == request_id)
            .values(sender_identity=sender)
        )

    async def move_customer_channel(self, request_id: UUID, channel: str) -> None:
        """Point a request's approval channel somewhere else, as an amended order would.

        The realistic shape of a check 8 failure: the decision is exactly as the customer left
        it, and the channel the order says to trust has moved out from under it.
        """
        await self._governed(
            sa_update(ApprovalRequest)
            .where(ApprovalRequest.id == request_id)
            .values(customer_channel=channel)
        )

    async def supersede_request(self, request_id: UUID) -> None:
        """Mark a request superseded without re-planning, so check 10 can be provoked alone."""
        await self._governed(
            sa_update(ApprovalRequest)
            .where(ApprovalRequest.id == request_id)
            .values(state="SUPERSEDED")
        )

    async def rebind_chosen_option(self, track_id: UUID, option_id: UUID) -> None:
        """Point a track at a different option than the one its customer was asked about."""
        await self._governed(
            sa_update(Track)
            .where(Track.id == track_id)
            .values(chosen_option_id=option_id, version=Track.version + 1)
        )

    async def reopen_for_revalidation(
        self, case_id: UUID, step_key: str, *, track_id: UUID | None = None
    ) -> None:
        """Put a case back at the revalidation boundary and make its checklist runnable again.

        Not something the engine does. It is how a test reaches a check that a lower-numbered
        one would otherwise claim first -- ``track_id`` also winds the track back to waiting, so
        the checklist gets past check 1 and has to answer for itself.
        """
        await self._governed(sa_update(Case).where(Case.id == case_id).values(state="REVALIDATING"))
        if track_id is not None:
            await self._governed(
                sa_update(Track)
                .where(Track.id == track_id)
                .values(state="WAITING_FOR_CUSTOMER", version=Track.version + 1)
            )
        step = await self.step_named(case_id, step_key)
        assert step is not None
        await self.requeue(step.id)

    async def _governed(self, statement: Any) -> None:
        """One fixture write through the runtime connection, audited like everything else."""
        async with self.database.begin() as connection:
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="REVALIDATION_TEST_SETUP",
                actor=Actor(kind="SYSTEM", id="revalidation-tests"),
                authority="NONE",
            ) as write:
                await write.execute(statement)

    async def _privileged(self, statement: Any) -> None:
        """The same, through the migration role, for a table the application may only append to.

        Still audited: the boundary being reached past is the privilege grant, not the ledger.
        """
        settings = Settings()
        engine = build_engine(migration_database_url(settings), pool_size=1)
        try:
            async with engine.begin() as connection:
                unit_of_work = UnitOfWork(connection)
                async with unit_of_work.governed(
                    event_type="REVALIDATION_TEST_SETUP",
                    actor=Actor(kind="SYSTEM", id="revalidation-tests"),
                    authority="NONE",
                ) as write:
                    await write.execute(statement)
        finally:
            await engine.dispose()

    async def bump_order_version(self, order_id: str) -> None:
        """One fingerprint input moved, and nothing else."""
        async with self.database.begin() as connection:
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="ORDER_SYSTEM_TEST_MUTATION",
                actor=Actor(kind="SYSTEM", id="order-system-stand-in"),
                authority="NONE",
            ) as write:
                await write.execute(
                    sa_update(Order)
                    .where(Order.id == order_id)
                    .values(
                        external_version=Order.external_version + 1,
                        updated_at=datetime.now(UTC),
                    )
                )

    # ------------------------------------------------------------------- step scheduling

    async def defer(self, step_id: UUID) -> None:
        """Push one step out of reach so a later one can be made to run first.

        Deterministic ordering without sleeping: a ``PENDING`` step whose ``next_attempt_at``
        lies in the future is not claimable, so the sweep takes the next row instead.
        """
        async with self.database.begin() as connection:
            await connection.execute(
                sa_update(CaseStep)
                .where(CaseStep.id == step_id)
                .values(next_attempt_at=text("now() + interval '1 hour'"))
            )

    async def defer_approvals(self, case_id: UUID) -> None:
        """Push a case's approval work out of reach, leaving only its recovery work runnable.

        A confirmation enqueues the amendment and the ask in one transaction, so both rows carry
        the same ``created_at`` and the claim order falls through to their ids -- which are
        random. That is correct for the engine, whose two pieces of work are independent, and
        useless for a test about one of them: whichever it meant to drive would be decided by a
        UUID. Deferring the other makes the subject of such a test the thing it names.
        """
        await self._shift_approvals(case_id, "now() + interval '1 hour'")

    async def release_approvals(self, case_id: UUID) -> None:
        """Bring deferred approval work back, to run after the recovery rather than beside it."""
        await self._shift_approvals(case_id, None)

    async def _shift_approvals(self, case_id: UUID, when: str | None) -> None:
        async with self.database.begin() as connection:
            await connection.execute(
                sa_update(CaseStep)
                .where(
                    CaseStep.case_id == case_id,
                    CaseStep.kind.in_(sorted(approvals.APPROVAL_STEP_KINDS)),
                )
                .values(next_attempt_at=None if when is None else text(when))
            )

    async def requeue(self, step_id: UUID) -> None:
        """Put a settled step back in the queue, so it genuinely runs a second time.

        Not something the engine does: it is how a test provokes the replay that a crash between
        two transactions would otherwise have to produce, and asks whether running the same
        piece of work twice writes the same rows twice.
        """
        async with self.database.begin() as connection:
            await connection.execute(
                sa_update(CaseStep)
                .where(CaseStep.id == step_id)
                .values(
                    state="PENDING",
                    attempts=0,
                    done_at=None,
                    next_attempt_at=None,
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )

    async def release(self, step_id: UUID) -> None:
        async with self.database.begin() as connection:
            await connection.execute(
                sa_update(CaseStep).where(CaseStep.id == step_id).values(next_attempt_at=None)
            )

    async def step_named(self, case_id: UUID, step_key: str) -> Any:
        async with self.database.connect() as connection:
            return (
                await connection.execute(
                    select(CaseStep).where(
                        CaseStep.case_id == case_id, CaseStep.step_key == step_key
                    )
                )
            ).one_or_none()

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
    engine = build_engine(migration_database_url(settings), pool_size=1)
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
