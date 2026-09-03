"""The durable half of the live feed, against a real PostgreSQL.

The stream's ordering logic is proven deterministically elsewhere. What can only be proven
here is that the thing it reads behaves the way the design assumes: that a sequence number
survives a commit and never goes backwards, that a rolled-back event leaves neither a row nor
an announcement, that the announcement carries a sequence number and no business detail, and
that the least-privileged runtime role can subscribe to the channel across the session pooler
without being granted anything to do it.

Committed events are produced by ``reset_demo_state``, which is the only thing in the system
that writes ``domain_events`` today, and the demo passwords come from the environment for the
same reason the shared fixture uses them: a reset with different credentials would leave the
seeded logins in a state the rest of the suite does not expect.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from promisepatch.config import Settings
from promisepatch.db import build_engine
from promisepatch.db.boundary import (
    EVENT_CHANNEL,
    NOTIFY_EVENT_TRIGGER,
    RUNTIME_ROLE,
    runtime_privileges,
)
from promisepatch.db.events import latest_seq, read_after
from promisepatch.db.listen import asyncpg_dsn
from promisepatch.db.models import DomainEvent
from promisepatch.db.uow import Actor
from promisepatch.fixtures import demo
from promisepatch.fixtures.reset import DOMAIN_EVENT_TYPE, ResetOutcome, reset_demo_state

pytestmark = pytest.mark.integration

INSUFFICIENT_PRIVILEGE = "42501"

DELIVERY_TIMEOUT = 20.0
"""How long a notification is waited for before the test calls it undelivered.

Generous, because a real reset over a hosted database is doing real work. It is a failure
bound, not a synchronisation device: nothing here passes because a timer expired.
"""

FIXTURE_ANCHOR = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
"""The anchor the shared ``demo_state`` fixture guarantees.

Resetting to the same instant with the same passwords means these tests leave the database in
exactly the state every other test in the suite expects to find it in.
"""

ROW_TRIGGER, ON_INSERT = 1, 4
"""``pg_trigger.tgtype`` bits. ``AFTER`` is the absence of the ``BEFORE`` and ``INSTEAD`` bits."""


@pytest.fixture
def operator_settings() -> Settings:
    """The credentials that can produce a committed domain event, or a skip."""
    settings = Settings()
    if settings.migration_database_url is None:
        pytest.skip("PP_MIGRATION_DATABASE_URL is not set; these tests need a database")
    if settings.demo_worker_password is None or settings.demo_owner_password is None:
        pytest.skip("PP_DEMO_WORKER_PASSWORD / PP_DEMO_OWNER_PASSWORD are not set")
    return settings


@pytest_asyncio.fixture
async def operator_engine(operator_settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = build_engine(operator_settings.require_migration_database_url(), pool_size=1)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def notifications(app_database_url: str) -> AsyncIterator[asyncio.Queue[str]]:
    """A raw subscription held by ``promisepatch_app`` itself, over the configured endpoint.

    Deliberately the runtime credential and the runtime URL: the question is not whether
    PostgreSQL can deliver a notification, it is whether the login the API actually uses can
    receive one across the pooler it actually connects through.
    """
    connection = await asyncpg.connect(asyncpg_dsn(app_database_url), statement_cache_size=0)
    queue: asyncio.Queue[str] = asyncio.Queue()
    await connection.add_listener(
        EVENT_CHANNEL, lambda _c, _pid, _channel, payload: queue.put_nowait(payload)
    )
    try:
        yield queue
    finally:
        await connection.close()


async def append_one_event(engine: AsyncEngine, settings: Settings) -> ResetOutcome:
    """Commit exactly one domain event, through the only path that writes them today."""
    async with engine.begin() as connection:
        return await reset_demo_state(
            connection,
            anchor=FIXTURE_ANCHOR,
            now=datetime.now(UTC),
            passwords={
                demo.BAKER_ROLE: settings.require_demo_worker_password(),
                demo.OWNER_ROLE: settings.require_demo_owner_password(),
            },
            actor=Actor(kind="SYSTEM", id="domain-event-tests"),
        )


async def await_payload(queue: asyncio.Queue[str], expected: str) -> list[str]:
    """Collect payloads until ``expected`` arrives; return everything seen up to and with it."""
    seen: list[str] = []

    async def collect() -> None:
        while True:
            payload = await queue.get()
            seen.append(payload)
            if payload == expected:
                return

    await asyncio.wait_for(collect(), timeout=DELIVERY_TIMEOUT)
    return seen


# ----------------------------------------------------------------------------- the mechanism


async def test_the_spine_carries_an_after_insert_row_trigger(conn: AsyncConnection) -> None:
    """A trigger, not a convention: a future writer cannot append an event and forget to say so."""
    rows = (
        await conn.exec_driver_sql(
            "select t.tgname, t.tgtype from pg_trigger t"
            " join pg_class c on c.oid = t.tgrelid"
            " join pg_namespace n on n.oid = c.relnamespace"
            " where n.nspname = 'promisepatch' and c.relname = 'domain_events'"
            " and not t.tgisinternal"
        )
    ).all()
    installed = {name: int(tgtype) for name, tgtype in rows}
    assert installed[NOTIFY_EVENT_TRIGGER] == ROW_TRIGGER | ON_INSERT


async def test_listening_costs_the_runtime_role_no_extra_privilege(
    conn: AsyncConnection, notifications: asyncio.Queue[str]
) -> None:
    """The subscription in the fixture above is already open; nothing was granted for it.

    ``LISTEN`` needs no privilege in PostgreSQL, so the live feed cannot be a reason the
    application's reach ever widened. The grants on the spine are still exactly the two an
    append-only ledger gets.
    """
    # Asked of the database rather than read off the migration file: the grant that matters is
    # the one in force, not the one someone wrote down.
    check = text("select has_table_privilege(:role, 'promisepatch.domain_events', :privilege)")
    granted = {
        privilege
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        if await conn.scalar(check, {"role": RUNTIME_ROLE, "privilege": privilege})
    }
    assert granted == set(runtime_privileges("domain_events"))


# --------------------------------------------------------------------------- commit and only


async def test_a_committed_event_is_announced_with_its_sequence_number(
    operator_engine: AsyncEngine,
    operator_settings: Settings,
    notifications: asyncio.Queue[str],
) -> None:
    """The whole contract of the channel: it fires on commit, and it carries a cursor."""
    outcome = await append_one_event(operator_engine, operator_settings)

    seen = await await_payload(notifications, str(outcome.domain_event_seq))

    payload = seen[-1]
    assert payload.isascii() and payload.isdigit()
    assert int(payload) == outcome.domain_event_seq


async def test_a_rolled_back_event_leaves_no_row_and_is_never_announced(
    app_engine: AsyncEngine,
    operator_engine: AsyncEngine,
    operator_settings: Settings,
    notifications: asyncio.Queue[str],
) -> None:
    """Proven without waiting on a negative.

    A sequence number is drawn inside a transaction that is then rolled back, and a real event
    is committed afterwards. Notifications arrive in order, so waiting for the committed one
    and finding the abandoned one absent from everything that came before it is a proof rather
    than a hopeful pause.
    """
    async with app_engine.connect() as connection:
        transaction = await connection.begin()
        abandoned = (
            await connection.execute(
                insert(DomainEvent)
                .values(
                    event_id=uuid4(),
                    type="rolled.back",
                    correlation_id=uuid4(),
                )
                .returning(DomainEvent.seq)
            )
        ).scalar_one()
        await transaction.rollback()

    outcome = await append_one_event(operator_engine, operator_settings)
    seen = await await_payload(notifications, str(outcome.domain_event_seq))
    assert str(abandoned) not in seen

    async with app_engine.connect() as connection:
        survivor = await connection.scalar(
            select(DomainEvent.seq).where(DomainEvent.seq == abandoned)
        )
    assert survivor is None


# --------------------------------------------------------------------------------- the ledger


async def test_the_sequence_is_durable_and_monotonic(app_conn: AsyncConnection) -> None:
    """Every reset this suite has ever run is still on the spine, in the order it happened."""
    highest = await latest_seq(app_conn)
    assert highest > 0

    records = await read_after(app_conn, after_seq=0, limit=1000)
    sequences = [record.seq for record in records]
    assert sequences == sorted(set(sequences))
    assert records[-1].seq <= highest


async def test_a_read_returns_only_what_follows_the_cursor(app_conn: AsyncConnection) -> None:
    highest = await latest_seq(app_conn)
    records = await read_after(app_conn, after_seq=highest - 1, limit=10)
    assert [record.seq for record in records] == [highest]


async def test_a_read_is_bounded_by_the_limit_it_is_given(app_conn: AsyncConnection) -> None:
    """A subscriber that has been away cannot make one query materialise the whole ledger."""
    assert len(await read_after(app_conn, after_seq=0, limit=1)) <= 1
    with pytest.raises(ValueError, match="limit"):
        await read_after(app_conn, after_seq=0, limit=0)


async def test_the_reset_event_is_readable_as_the_type_it_was_written_as(
    app_conn: AsyncConnection,
) -> None:
    highest = await latest_seq(app_conn)
    records = await read_after(app_conn, after_seq=highest - 1, limit=1)
    assert records[0].type == DOMAIN_EVENT_TYPE
    assert records[0].occurred_at.tzinfo is not None


async def test_the_spine_is_still_append_only(app_conn: AsyncConnection) -> None:
    """The feed reads this table; nothing about that made it rewritable."""
    for statement in (
        "update promisepatch.domain_events set type = 'tampered'",
        "delete from promisepatch.domain_events",
    ):
        savepoint = await app_conn.begin_nested()
        with pytest.raises(DBAPIError) as raised:
            await app_conn.exec_driver_sql(statement)
        await savepoint.rollback()
        assert str(getattr(raised.value.orig, "sqlstate", "")) == INSUFFICIENT_PRIVILEGE
