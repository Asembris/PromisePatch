"""The database round trip: does a stored promise graph still decide the same things?

This is the acceptance gate for persistence. The engine's own suite proves the Hollow Oak
fixture yields A auto / B approval / C blocked / D-E-F untouched; these tests prove that a copy
of that fixture which has been through PostgreSQL — projected into twenty tables, truncated,
reloaded, and read back through the loader — yields *the same answers for the same cited
reasons*. A round trip that changed one classification, one rule id or one ledger sequence
number would make every downstream proof about a stored graph rather than about the engine.

Unlike the schema tests, these commit. A reset is convergent by construction, so leaving the
demo fixture loaded is the correct end state rather than a side effect to clean up.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import Classification, ReasonDetail, Record, RuleId
from promise_graph.snapshot import GraphSnapshot
from promisepatch.db import build_engine
from promisepatch.db.base import SCHEMA, Base
from promisepatch.db.models import (
    AuditEvent,
    CommitmentLine,
    DomainEvent,
    FixtureState,
    Promise,
    Reservation,
    Resource,
    Worker,
)
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.fixtures import demo
from promisepatch.fixtures.reset import (
    AUDIT_EVENT_TYPE,
    DOMAIN_EVENT_TYPE,
    LOCK_KEY,
    ResetOutcome,
    reset_demo_state,
)
from promisepatch.graph.loader import READ_TABLES, load_snapshot, snapshot_session
from tests.fixtures import classifications, settle_and_analyze

pytestmark = pytest.mark.integration

OPERATOR = Actor(kind="SYSTEM", id="fixture-round-trip-tests")

LOCK_NOT_AVAILABLE = "55P03"
"""SQLSTATE for a lock a ``NOWAIT`` request could not have."""


def sqlstate(error: DBAPIError) -> str:
    """The code the database itself reported, not the sentence the driver wrapped it in."""
    return str(getattr(error.orig, "sqlstate", ""))


DEMO_PASSWORDS = {
    demo.BAKER_ROLE: "round-trip-baker-passphrase",
    demo.OWNER_ROLE: "round-trip-owner-passphrase",
}
"""Throwaway values supplied by the test, not read from the environment.

Passing the passwords in rather than reading settings is what keeps this gate runnable on any
database: the reset's contract is "seed these logins", and where an operator gets them from is
the CLI's problem, tested separately.
"""

ANCHORS = [
    datetime(2026, 3, 4, 7, 0, tzinfo=UTC),
    datetime(2026, 7, 19, 22, 45, tzinfo=UTC),
    datetime(2027, 1, 1, 0, 0, tzinfo=UTC),
]

A, B, C, D, E, F = (
    ho.PROMISE_A,
    ho.PROMISE_B,
    ho.PROMISE_C,
    ho.PROMISE_D,
    ho.PROMISE_E,
    ho.PROMISE_F,
)


@pytest_asyncio.fixture
async def graph_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """More than one connection, because a torn-read test needs two at once."""
    engine = build_engine(database_url, pool_size=4)
    try:
        yield engine
    finally:
        await engine.dispose()


async def reset_at(
    engine: AsyncEngine, anchor: datetime, *, now: datetime | None = None
) -> ResetOutcome:
    async with engine.begin() as connection:
        return await reset_demo_state(
            connection,
            anchor=anchor,
            now=now or datetime.now(UTC),
            passwords=DEMO_PASSWORDS,
            actor=OPERATOR,
        )


async def load(engine: AsyncEngine) -> GraphSnapshot:
    async with snapshot_session(engine) as session:
        return await load_snapshot(session)


def same_graph(loaded: GraphSnapshot, expected: GraphSnapshot) -> bool:
    """Equal in every stored fact.

    ``as_of`` is compared separately and deliberately. It is not a fact about the graph: it is
    the position on the event spine the graph was read at, and that spine is append-only across
    resets by design. Folding it into this comparison would mean asserting that history had
    been deleted, which is the one thing a reset must never do.
    """
    return loaded.replace(as_of=expected.as_of) == expected


# ------------------------------------------------------------------ 1. it comes back the same


@pytest.mark.parametrize("anchor", ANCHORS)
async def test_the_persisted_fixture_loads_back_equal_to_the_pure_one(
    graph_engine: AsyncEngine, anchor: datetime
) -> None:
    """Every record, id, decimal and timestamp survives twenty tables and a reload."""
    await reset_at(graph_engine, anchor)
    assert same_graph(await load(graph_engine), demo.build_snapshot(anchor))


async def test_the_snapshot_is_stamped_with_the_event_it_was_read_after(
    graph_engine: AsyncEngine,
) -> None:
    """``as_of`` is the spine position, so a reader can say how current its view was."""
    outcome = await reset_at(graph_engine, ANCHORS[0])
    loaded = await load(graph_engine)
    assert loaded.as_of == outcome.domain_event_seq

    async with graph_engine.connect() as connection:
        highest = (await connection.execute(select(func.max(DomainEvent.seq)))).scalar_one()
    assert loaded.as_of == highest


async def test_unknown_quantities_come_back_unknown(graph_engine: AsyncEngine) -> None:
    """A null quantity must reload as ``None``; reloading it as zero would fail open."""
    await reset_at(graph_engine, ANCHORS[0])
    async with (
        graph_engine.begin() as connection,
        UnitOfWork(connection).governed(
            event_type="TEST_UNKNOWN_QUANTITY", actor=OPERATOR, authority="NONE"
        ) as write,
    ):
        await write.execute(
            update(CommitmentLine)
            .where(CommitmentLine.id == ho.VP_TODAY_RASPBERRY)
            .values(quantity=None)
        )

    loaded = await load(graph_engine)
    assert loaded.commitment_lines[ho.VP_TODAY_RASPBERRY].quantity is None


# ------------------------------------------------------------------ 2. the ledger's order


@pytest.mark.parametrize("anchor", ANCHORS[:2])
async def test_the_ledger_keeps_its_sequence_through_reset_and_load(
    graph_engine: AsyncEngine, anchor: datetime
) -> None:
    """Stock figures are keyed by ledger sequence, so the sequence has to be reproducible."""
    expected = demo.build_snapshot(anchor)
    await reset_at(graph_engine, anchor)
    first = await load(graph_engine)

    assert [(entry.seq, entry.resource_id) for entry in first.ledger] == [
        (entry.seq, entry.resource_id) for entry in expected.ledger
    ]

    await reset_at(graph_engine, anchor)
    second = await load(graph_engine)
    assert second.ledger == first.ledger


async def test_the_ledger_sequence_restarts_from_one(graph_engine: AsyncEngine) -> None:
    """``RESTART IDENTITY`` is what stops a reloaded ledger drifting further each reset."""
    await reset_at(graph_engine, ANCHORS[0])
    await reset_at(graph_engine, ANCHORS[0])
    loaded = await load(graph_engine)
    assert [entry.seq for entry in loaded.ledger] == list(range(1, len(loaded.ledger) + 1))


# ------------------------------------------------------------------ 3-6. the same decisions


@pytest.mark.parametrize("anchor", ANCHORS)
async def test_the_canonical_result_is_unchanged_by_persistence(
    graph_engine: AsyncEngine, anchor: datetime
) -> None:
    """The demo's headline outcome, computed from rows that went through PostgreSQL."""
    await reset_at(graph_engine, anchor)
    stored = ho.with_lena_mutation(await load(graph_engine))
    analysis = settle_and_analyze(stored, ho.raspberry_only(anchor), anchor)
    assert classifications(analysis) == {
        A: Classification.AUTO_RECOVERABLE,
        B: Classification.APPROVAL_REQUIRED,
        C: Classification.BLOCKED,
        D: Classification.UNAFFECTED,
        E: Classification.UNAFFECTED,
        F: Classification.UNAFFECTED,
    }


@pytest.mark.parametrize("anchor", ANCHORS)
async def test_every_cited_rule_and_constraint_matches_the_pure_engine(
    graph_engine: AsyncEngine, anchor: datetime
) -> None:
    """A right answer for a different reason would still break the evidence screen."""
    await reset_at(graph_engine, anchor)
    stored = ho.with_lena_mutation(await load(graph_engine))
    pure = ho.with_lena_mutation(demo.build_snapshot(anchor))
    exception = ho.raspberry_only(anchor)

    from_database = settle_and_analyze(stored, exception, anchor)
    from_memory = settle_and_analyze(pure, exception, anchor)

    assert from_database.classifications == from_memory.classifications
    assert from_database.classifications[A].rule_id is RuleId.R_PREAPPROVED
    assert from_database.classifications[A].cited_constraint_ids == (ho.CONSTRAINT_A_PREAPPROVED,)
    assert from_database.classifications[B].rule_id is RuleId.R_VISIBLE_ASK
    assert from_database.classifications[B].cited_constraint_ids == (ho.CONSTRAINT_B_ASK,)
    assert from_database.classifications[C].rule_id is RuleId.R_NOSUB
    assert from_database.classifications[C].reason_detail is ReasonDetail.NOSUB_CONSTRAINT
    assert from_database.classifications[C].cited_constraint_ids == (ho.CONSTRAINT_C_NOSUB,)
    for promise_id in (D, E, F):
        assert from_database.classifications[promise_id].rule_id is RuleId.R_UNREACH


@pytest.mark.parametrize("anchor", ANCHORS)
async def test_d_is_persisted_before_the_mutation_and_is_blocked(
    graph_engine: AsyncEngine, anchor: datetime
) -> None:
    """The stored order still points at Raspberry Lemon Layer v2, which has no variant."""
    await reset_at(graph_engine, anchor)
    stored = await load(graph_engine)
    assert stored.order_lines[ho.LINE_D].recipe_version_id == ho.RLL_V2

    result = settle_and_analyze(stored, ho.raspberry_only(anchor), anchor).classifications[D]
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_NOSUB
    assert result.reason_detail is ReasonDetail.NO_PREAUTHORED_VARIANT


@pytest.mark.parametrize("anchor", ANCHORS)
async def test_whole_delivery_blocks_a_and_b_on_substitute_stock(
    graph_engine: AsyncEngine, anchor: datetime
) -> None:
    """The wider scope is a different answer from the same stored graph."""
    await reset_at(graph_engine, anchor)
    stored = ho.with_lena_mutation(await load(graph_engine))
    analysis = settle_and_analyze(stored, ho.whole_delivery(anchor), anchor)

    assert classifications(analysis) == {
        A: Classification.BLOCKED,
        B: Classification.BLOCKED,
        C: Classification.BLOCKED,
        D: Classification.UNAFFECTED,
        E: Classification.UNAFFECTED,
        F: Classification.UNAFFECTED,
    }
    assert analysis.classifications[A].rule_id is RuleId.R_SUBSTOCK
    assert analysis.classifications[B].rule_id is RuleId.R_SUBSTOCK


# ------------------------------------------------------------------ 7. no torn reads


async def test_a_truncation_cannot_start_while_a_load_is_open(
    graph_engine: AsyncEngine,
) -> None:
    """A reset cannot empty a table out from under a read in progress.

    This is the hazard repeatable read does not cover. ``TRUNCATE`` is not MVCC-safe: a reader
    holding an older snapshot sees a truncated table as **empty**, not as it was -- and a graph
    with no promises in it is one the engine would call entirely unaffected, which is the worst
    possible way to be wrong, because nothing raises. The loader's up-front share lock on its
    read set is what closes it, and the proof is that the exclusive lock a truncation needs
    cannot be taken while a load's transaction is open.

    Probed with ``NOWAIT`` rather than by racing a real reset. A real reset would sit in the
    lock queue until the reader let go, which is the correct behaviour but makes the assertion
    depend on how long the read takes and on the server's statement timeout; asking for the
    lock and being refused states the same fact in one round trip.
    """
    await reset_at(graph_engine, ANCHORS[0])
    exclusive = text(f'LOCK TABLE {SCHEMA}."resources" IN ACCESS EXCLUSIVE MODE NOWAIT')

    async with snapshot_session(graph_engine) as session:
        loaded = await load_snapshot(session)
        async with graph_engine.connect() as contender:
            await contender.begin()
            with pytest.raises(DBAPIError) as refused:
                await contender.execute(exclusive)
            await contender.rollback()

    assert sqlstate(refused.value) == LOCK_NOT_AVAILABLE
    assert same_graph(loaded, demo.build_snapshot(ANCHORS[0]))

    # And the moment the reader lets go, the reset is free to proceed.
    async with graph_engine.connect() as contender:
        await contender.begin()
        await contender.execute(exclusive)
        await contender.rollback()


async def test_a_load_is_repeatable_across_a_concurrent_commit(
    graph_engine: AsyncEngine,
) -> None:
    """Two reads in one transaction see one graph, however much commits between them.

    Under READ COMMITTED the loader's twenty selects would straddle a commit and assemble half
    of one graph and half of another -- a shape that never existed, which the engine would then
    classify with a straight face.
    """
    await reset_at(graph_engine, ANCHORS[0])
    renamed = "renamed by a concurrent writer"

    async with snapshot_session(graph_engine) as session:
        before = await load_snapshot(session)

        async with (
            graph_engine.begin() as connection,
            UnitOfWork(connection).governed(
                event_type="TEST_CONCURRENT_WRITE", actor=OPERATOR, authority="NONE"
            ) as write,
        ):
            await write.execute(update(Resource).values(name=renamed))

        after = await load_snapshot(session)

    assert same_graph(after, before)
    assert all(resource.name != renamed for resource in after.resources.values())

    fresh = await load(graph_engine)
    assert all(resource.name == renamed for resource in fresh.resources.values())


async def test_the_loader_locks_exactly_the_tables_it_reads(graph_engine: AsyncEngine) -> None:
    """An undeclared table is the hole a concurrent reset would empty underneath the read."""
    await reset_at(graph_engine, ANCHORS[0])
    async with snapshot_session(graph_engine) as session:
        await load_snapshot(session)
        locked = {
            row["relname"]
            for row in (
                await session.execute(
                    text(
                        "SELECT c.relname FROM pg_locks l"
                        " JOIN pg_class c ON c.oid = l.relation"
                        " JOIN pg_namespace n ON n.oid = c.relnamespace"
                        " WHERE l.pid = pg_backend_pid() AND n.nspname = :schema"
                        "   AND c.relkind = 'r'"
                    ),
                    {"schema": SCHEMA},
                )
            ).mappings()
        }
    assert locked == set(READ_TABLES)


async def test_a_snapshot_session_refuses_to_write(graph_engine: AsyncEngine) -> None:
    """``READ ONLY`` says what the transaction is for, and the server holds it to it."""
    async with snapshot_session(graph_engine) as session:
        with pytest.raises(DBAPIError):
            await session.execute(update(Resource).values(name="not through here"))


# ------------------------------------------------------------------ 8. no ORM leakage


async def test_no_orm_object_reaches_the_engine(graph_engine: AsyncEngine) -> None:
    """The engine is pure. An ORM instance would smuggle a session and a lazy loader into it."""
    await reset_at(graph_engine, ANCHORS[0])
    loaded = await load(graph_engine)

    seen = 0
    for value in _walk(loaded):
        seen += 1
        assert not isinstance(value, Base)
        assert not hasattr(value, "_sa_instance_state")
        assert type(value).__module__.split(".")[0] in {
            "promise_graph",
            "builtins",
            "datetime",
            "decimal",
            "enum",
        }
    assert seen > 100


def _walk(value: Any) -> Iterable[Any]:
    """Every record and scalar reachable from a snapshot."""
    if isinstance(value, Record):
        yield value
        for item in value.__dict__.values():
            yield from _walk(item)
    elif is_dataclass(value) and not isinstance(value, type):
        yield value
        for field in fields(value):
            if field.compare:
                yield from _walk(getattr(value, field.name))
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(key)
            yield from _walk(item)
    elif isinstance(value, tuple | list):
        for item in value:
            yield from _walk(item)
    else:
        yield value


# ------------------------------------------------------------------ 9. idempotency


async def test_two_resets_at_one_anchor_leave_one_state(graph_engine: AsyncEngine) -> None:
    """Idempotent means the same domain state and the same digest, not the same ledger."""
    anchor = ANCHORS[1]
    first = await reset_at(graph_engine, anchor)
    after_first = await load(graph_engine)
    second = await reset_at(graph_engine, anchor)
    after_second = await load(graph_engine)

    assert first.digest == second.digest
    assert same_graph(after_second, after_first)
    assert second.domain_event_seq > first.domain_event_seq


async def test_a_reset_converges_from_dirty_and_partial_state(graph_engine: AsyncEngine) -> None:
    """Whatever the demo was left in, the next reset produces the same graph."""
    anchor = ANCHORS[0]
    clean = await reset_at(graph_engine, anchor)
    expected = await load(graph_engine)

    async with (
        graph_engine.begin() as connection,
        UnitOfWork(connection).governed(
            event_type="TEST_DIRTY_STATE", actor=OPERATOR, authority="NONE"
        ) as write,
    ):
        await write.execute(update(Resource).values(name="scribbled over"))
        await write.execute(delete(Reservation))
        await write.execute(delete(Promise))

    dirty = await load(graph_engine)
    assert not same_graph(dirty, expected)

    again = await reset_at(graph_engine, anchor)
    assert again.digest == clean.digest
    assert same_graph(await load(graph_engine), expected)


async def test_a_different_anchor_produces_a_different_state(graph_engine: AsyncEngine) -> None:
    first = await reset_at(graph_engine, ANCHORS[0])
    second = await reset_at(graph_engine, ANCHORS[1])
    assert first.digest != second.digest
    assert same_graph(await load(graph_engine), demo.build_snapshot(ANCHORS[1]))


async def test_the_loaded_fixture_state_names_what_is_loaded(graph_engine: AsyncEngine) -> None:
    outcome = await reset_at(graph_engine, ANCHORS[0])
    async with graph_engine.connect() as connection:
        rows = (await connection.execute(select(FixtureState))).mappings().all()

    assert len(rows) == 1
    assert rows[0]["fixture_name"] == demo.FIXTURE_NAME
    assert rows[0]["anchor_at"] == ANCHORS[0]
    assert rows[0]["fixture_digest"] == outcome.digest


async def test_the_demo_logins_are_seeded_with_verifiable_hashes(
    graph_engine: AsyncEngine,
) -> None:
    """A hash that does not verify is a demo nobody can log into."""
    await reset_at(graph_engine, ANCHORS[0])
    async with graph_engine.connect() as connection:
        workers = (await connection.execute(select(Worker))).mappings().all()

    by_id = {row["id"]: row for row in workers}
    assert set(by_id) == {seed.worker_id for seed in demo.STAFF}

    hasher = PasswordHasher()
    for seed in demo.STAFF:
        row = by_id[seed.worker_id]
        assert row["role"] == seed.role
        assert row["password_hash"] != DEMO_PASSWORDS[seed.role]
        assert hasher.verify(row["password_hash"], DEMO_PASSWORDS[seed.role])
        with pytest.raises(VerifyMismatchError):
            hasher.verify(row["password_hash"], "not the configured password")


# ------------------------------------------------------------------ 10. history survives


async def test_a_reset_is_audited_and_announced(graph_engine: AsyncEngine) -> None:
    """One audit event authorises it, one domain event puts it on the spine."""
    outcome = await reset_at(graph_engine, ANCHORS[0])
    async with graph_engine.connect() as connection:
        audit = (
            (
                await connection.execute(
                    select(AuditEvent).where(AuditEvent.seq == outcome.audit_seq)
                )
            )
            .mappings()
            .one()
        )
        event = (
            (
                await connection.execute(
                    select(DomainEvent).where(DomainEvent.seq == outcome.domain_event_seq)
                )
            )
            .mappings()
            .one()
        )

    assert audit["type"] == AUDIT_EVENT_TYPE
    assert audit["authority"] == "NONE"
    assert audit["actor_id"] == OPERATOR.id
    assert audit["after"]["digest"] == outcome.digest
    assert event["type"] == DOMAIN_EVENT_TYPE
    assert event["correlation_id"] == audit["correlation_id"]
    assert event["entity_refs"] == []


async def test_a_reset_never_empties_the_append_only_history(graph_engine: AsyncEngine) -> None:
    """The record of what was done outlives every state it describes."""
    await reset_at(graph_engine, ANCHORS[0])
    async with graph_engine.connect() as connection:
        before_audit = (
            await connection.execute(select(func.count()).select_from(AuditEvent.__table__))
        ).scalar_one()
        before_events = (
            await connection.execute(select(func.count()).select_from(DomainEvent.__table__))
        ).scalar_one()
        earliest_audit = (await connection.execute(select(func.min(AuditEvent.seq)))).scalar_one()

    await reset_at(graph_engine, ANCHORS[0])

    async with graph_engine.connect() as connection:
        after_audit = (
            await connection.execute(select(func.count()).select_from(AuditEvent.__table__))
        ).scalar_one()
        after_events = (
            await connection.execute(select(func.count()).select_from(DomainEvent.__table__))
        ).scalar_one()
        survivor = (
            await connection.execute(
                select(func.count())
                .select_from(AuditEvent.__table__)
                .where(AuditEvent.seq == earliest_audit)
            )
        ).scalar_one()

    assert after_audit == before_audit + 1
    assert after_events == before_events + 1
    assert survivor == 1


async def test_the_reset_key_serialises_two_resets(graph_engine: AsyncEngine) -> None:
    """Two operators pressing the button at once produce one reset and one wait.

    Asserted on the lock itself rather than by racing two resets: a race that happened to pass
    would prove nothing, whereas the key being unavailable to a second transaction while a
    first holds it is exactly the property the reset relies on.
    """
    async with graph_engine.connect() as holder:
        await holder.begin()
        await holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
        async with graph_engine.connect() as contender:
            await contender.begin()
            taken = (
                await contender.execute(
                    text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_KEY}
                )
            ).scalar_one()
            await contender.rollback()
        assert taken is False
        await holder.rollback()


async def test_the_reset_lock_dies_with_its_transaction(graph_engine: AsyncEngine) -> None:
    """A transaction-scoped lock cannot be left behind by a crash mid-reset."""
    await reset_at(graph_engine, ANCHORS[0])
    async with graph_engine.connect() as connection:
        await connection.begin()
        taken = (
            await connection.execute(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_KEY}
            )
        ).scalar_one()
        await connection.rollback()
    assert taken is True


async def test_the_demo_is_left_loaded_at_a_usable_anchor(graph_engine: AsyncEngine) -> None:
    """This suite commits, so it finishes by putting the demo somewhere sensible.

    Every fixture deadline is an offset from the anchor, so anchoring on now keeps them in the
    future -- which is the state an operator opening the app straight after a test run wants.
    """
    anchor = datetime.now(UTC).replace(microsecond=0)
    outcome = await reset_at(graph_engine, anchor)
    loaded = await load(graph_engine)

    assert same_graph(loaded, demo.build_snapshot(anchor))
    assert outcome.rows_written > 0
    assert min(promise.due_at for promise in loaded.promises.values()) > anchor + timedelta(hours=1)
