"""The durable-workflow primitives, as the database actually holds them.

Everything here is a property a worker relies on and cannot check for itself at runtime: that a
claimed step must name its owner and an expiry, that two live timers for one subject are
impossible, that the attempt counter cannot go backwards, and that the event spine carries the
trigger which makes its sequence commit-ordered.

They are asserted against a real PostgreSQL rather than against the metadata, because the
metadata is what we asked for and the catalog is what we got.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Executable, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.boundary import (
    COMMIT_ORDER_FUNCTION,
    COMMIT_ORDER_TRIGGER,
    EVENT_ORDER_LOCK_KEY,
    EVENT_ORDER_LOCK_NAME,
    NOTIFY_EVENT_TRIGGER,
    advisory_lock_key,
)
from promisepatch.db.models import CaseStep, OutboxMessage, Timer

pytestmark = pytest.mark.integration

CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0005_durable_workflow_primitives.py"
)


def sqlstate(error: DBAPIError) -> str:
    return str(getattr(error.orig, "sqlstate", ""))


async def refused(conn: AsyncConnection, statement: Executable) -> DBAPIError:
    """Run a statement that must fail, inside a savepoint so the transaction survives it."""
    savepoint = await conn.begin_nested()
    try:
        await conn.execute(statement)
    except DBAPIError as error:
        await savepoint.rollback()
        return error
    await savepoint.rollback()
    raise AssertionError("the database accepted a statement it must refuse")


def a_step(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": uuid4(),
        "case_id": uuid4(),
        "step_key": f"schema:{uuid4().hex[:8]}",
        "kind": "NOOP",
        "state": "PENDING",
    }
    values.update(overrides)
    return values


def an_effect(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": uuid4(),
        "kind": "FAKE_EFFECT",
        "payload": {},
        "idempotency_key": f"pp:schema:{uuid4().hex}",
        "state": "PENDING",
    }
    values.update(overrides)
    return values


def a_timer(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": uuid4(),
        "kind": "WORKFLOW_WAKEUP",
        "subject_type": "CASE",
        "subject_id": str(uuid4()),
        "due_at": NOW,
    }
    values.update(overrides)
    return values


# ------------------------------------------------------------------- the ordering lock's key


def test_the_migration_states_the_key_the_runtime_derives() -> None:
    """The migration states a literal; the application derives one. They must be the same key.

    A migration records what was applied on a date and cannot import a constant that may move
    under it, so the integer is written out there. That makes this the only thing holding the
    two ends together, which is why it is a test rather than a comment.
    """
    source = MIGRATION.read_text(encoding="utf-8")
    assert f"EVENT_ORDER_LOCK_KEY = {EVENT_ORDER_LOCK_KEY}" in source
    assert advisory_lock_key(EVENT_ORDER_LOCK_NAME) == EVENT_ORDER_LOCK_KEY


async def test_the_installed_function_locks_the_key_the_runtime_expects(
    conn: AsyncConnection,
) -> None:
    """What the database will actually do, read back out of the database.

    The migration source says what was intended; ``pg_get_functiondef`` says what is installed,
    and a test that only read the file would still pass against a schema somebody had patched
    by hand. Every concurrency proof in the suite watches for *this* key.
    """
    definition = (
        await conn.execute(
            text("SELECT pg_get_functiondef(cast(:name AS regprocedure))"),
            {"name": f"promisepatch.{COMMIT_ORDER_FUNCTION}()"},
        )
    ).scalar_one()
    assert f"pg_advisory_xact_lock({EVENT_ORDER_LOCK_KEY})" in definition
    assert "nextval('promisepatch.domain_events_seq_seq')" in definition


# --------------------------------------------------------------------------- the spine's trigger

ROW_TRIGGER, ON_INSERT = 1, 4
BEFORE = 2
"""``pg_trigger.tgtype`` bits. ``AFTER`` is the absence of ``BEFORE``."""


async def test_the_spine_assigns_its_sequence_in_a_before_insert_row_trigger(
    conn: AsyncConnection,
) -> None:
    """``BEFORE INSERT ... FOR EACH ROW`` is the only point at which ``seq`` can still be set.

    A statement trigger could not reach ``NEW``, and an ``AFTER`` trigger would be looking at a
    value the row already has -- and that ``trg_20_notify_domain_event`` has already announced.
    """
    row = (
        await conn.exec_driver_sql(
            "select t.tgtype, t.tgenabled, p.proname"
            " from pg_trigger t"
            " join pg_class c on c.oid = t.tgrelid"
            " join pg_namespace n on n.oid = c.relnamespace"
            " join pg_proc p on p.oid = t.tgfoid"
            f" where n.nspname = 'promisepatch' and c.relname = 'domain_events'"
            f" and t.tgname = '{COMMIT_ORDER_TRIGGER}'"
        )
    ).one_or_none()
    assert row is not None, f"{COMMIT_ORDER_TRIGGER} is not installed on domain_events"
    tgtype, enabled, function = row
    mode = enabled.decode() if isinstance(enabled, bytes) else str(enabled)
    assert mode == "O"
    assert function == COMMIT_ORDER_FUNCTION
    assert int(tgtype) == ROW_TRIGGER | BEFORE | ON_INSERT


async def test_the_sequence_trigger_fires_before_the_notification(conn: AsyncConnection) -> None:
    """Name order decides it, and it decides which sequence number the wake-up carries."""
    assert COMMIT_ORDER_TRIGGER < NOTIFY_EVENT_TRIGGER


async def test_the_previous_trigger_inventory_is_intact(conn: AsyncConnection) -> None:
    """The spine gained one trigger. It must not have lost, or silently renamed, any other."""
    rows = (
        await conn.exec_driver_sql(
            "select t.tgname from pg_trigger t"
            " join pg_class c on c.oid = t.tgrelid"
            " join pg_namespace n on n.oid = c.relnamespace"
            " where n.nspname = 'promisepatch' and c.relname = 'domain_events'"
            " and not t.tgisinternal"
        )
    ).scalars()
    assert set(rows) == {
        "trg_00_append_only",
        "trg_01_no_truncate",
        COMMIT_ORDER_TRIGGER,
        NOTIFY_EVENT_TRIGGER,
    }


# ------------------------------------------------------------------------------- step leases


async def test_a_step_claiming_to_be_in_flight_must_name_an_owner_and_an_expiry(
    app_conn: AsyncConnection,
) -> None:
    """Otherwise a crash mid-claim would strand the step: nothing would say when to reclaim it."""
    error = await refused(app_conn, insert(CaseStep).values(**a_step(state="IN_FLIGHT")))
    assert sqlstate(error) == CHECK_VIOLATION
    assert "in_flight_lease" in str(error.orig)

    error = await refused(
        app_conn,
        insert(CaseStep).values(**a_step(state="IN_FLIGHT", lease_owner="worker-a")),
    )
    assert sqlstate(error) == CHECK_VIOLATION


async def test_a_leased_in_flight_step_is_accepted(app_conn: AsyncConnection) -> None:
    await app_conn.execute(
        insert(CaseStep).values(
            **a_step(
                state="IN_FLIGHT",
                lease_owner="worker-a",
                lease_expires_at=NOW + timedelta(seconds=60),
                attempts=1,
            )
        )
    )


async def test_a_step_that_is_not_in_flight_may_hold_no_lease(app_conn: AsyncConnection) -> None:
    """Releasing a lease is what a completion does; the constraint must not stand in its way."""
    await app_conn.execute(insert(CaseStep).values(**a_step(state="DONE", attempts=1)))


async def test_the_attempt_counter_cannot_go_negative(app_conn: AsyncConnection) -> None:
    """``attempts`` is the fencing token as well as the retry count; below zero it is neither."""
    error = await refused(app_conn, insert(CaseStep).values(**a_step(attempts=-1)))
    assert sqlstate(error) == CHECK_VIOLATION
    assert "attempts_non_negative" in str(error.orig)


async def test_a_step_key_is_unique_within_its_case(app_conn: AsyncConnection) -> None:
    """The whole of the "resume, do not re-run" story, expressed as an index."""
    case_id, step_key = uuid4(), "chain:0"
    await app_conn.execute(insert(CaseStep).values(**a_step(case_id=case_id, step_key=step_key)))
    error = await refused(
        app_conn, insert(CaseStep).values(**a_step(case_id=case_id, step_key=step_key))
    )
    assert sqlstate(error) == UNIQUE_VIOLATION


# ------------------------------------------------------------------------------ timer uniqueness


async def test_only_one_live_timer_exists_per_subject(app_conn: AsyncConnection) -> None:
    """Arming the same deadline twice must be a database no-op, not two wake-ups."""
    subject = str(uuid4())
    await app_conn.execute(insert(Timer).values(**a_timer(subject_id=subject)))
    error = await refused(app_conn, insert(Timer).values(**a_timer(subject_id=subject)))
    assert sqlstate(error) == UNIQUE_VIOLATION


async def test_a_fired_timer_stops_constraining_its_subject(app_conn: AsyncConnection) -> None:
    """The index is partial so the next round's deadline can be armed once this one has fired."""
    subject = str(uuid4())
    await app_conn.execute(insert(Timer).values(**a_timer(subject_id=subject, fired_at=NOW)))
    await app_conn.execute(insert(Timer).values(**a_timer(subject_id=subject, fired_at=NOW)))
    await app_conn.execute(insert(Timer).values(**a_timer(subject_id=subject)))


async def test_timers_for_different_subjects_do_not_collide(app_conn: AsyncConnection) -> None:
    await app_conn.execute(insert(Timer).values(**a_timer()))
    await app_conn.execute(insert(Timer).values(**a_timer()))


# ----------------------------------------------------------------------------- outbox leases


async def test_an_effect_claiming_to_be_in_flight_must_name_an_owner_and_an_expiry(
    app_conn: AsyncConnection,
) -> None:
    error = await refused(app_conn, insert(OutboxMessage).values(**an_effect(state="IN_FLIGHT")))
    assert sqlstate(error) == CHECK_VIOLATION
    assert "in_flight_lease" in str(error.orig)


async def test_an_effect_key_is_unique_across_the_whole_table(app_conn: AsyncConnection) -> None:
    """Two rows with one key would be two real-world effects for one decision."""
    key = f"pp:schema:{uuid4().hex}"
    await app_conn.execute(insert(OutboxMessage).values(**an_effect(idempotency_key=key)))
    with pytest.raises(IntegrityError):
        await app_conn.execute(insert(OutboxMessage).values(**an_effect(idempotency_key=key)))


# ---------------------------------------------------------------------------- reclaim indexes

EXPECTED_INDEXES = {
    ("case_steps", "ix_case_steps_lease_expires_at"),
    ("outbox_messages", "ix_outbox_messages_lease_expires_at"),
    ("timers", "ix_timers_live_subject"),
    ("timers", "ix_timers_due_unfired"),
}


async def test_every_sweep_the_worker_performs_has_an_index_behind_it(
    conn: AsyncConnection,
) -> None:
    """A worker polls these predicates continuously; each must be an index lookup, not a scan."""
    rows = (
        await conn.exec_driver_sql(
            "select tablename, indexname from pg_indexes where schemaname = 'promisepatch'"
        )
    ).all()
    installed = {(table, index) for table, index in rows}
    assert installed >= EXPECTED_INDEXES


async def test_the_reclaim_indexes_cover_only_rows_that_can_be_reclaimed(
    conn: AsyncConnection,
) -> None:
    """Partial on ``IN_FLIGHT``: the sweep never walks settled or unclaimed rows."""
    rows = (
        await conn.exec_driver_sql(
            "select indexname, indexdef from pg_indexes where schemaname = 'promisepatch'"
            " and indexname in ('ix_case_steps_lease_expires_at',"
            " 'ix_outbox_messages_lease_expires_at', 'ix_timers_live_subject')"
        )
    ).all()
    definitions = {str(name): str(definition) for name, definition in rows}
    assert "WHERE" in definitions["ix_case_steps_lease_expires_at"]
    assert "IN_FLIGHT" in definitions["ix_case_steps_lease_expires_at"]
    assert "IN_FLIGHT" in definitions["ix_outbox_messages_lease_expires_at"]
    assert "UNIQUE" in definitions["ix_timers_live_subject"]
    assert "fired_at IS NULL" in definitions["ix_timers_live_subject"]


# ------------------------------------------------------------------------ the columns exist

EXPECTED_COLUMNS = {
    "case_steps": {"lease_owner", "lease_expires_at", "created_at"},
    "outbox_messages": {
        "lease_owner",
        "lease_expires_at",
        "last_error",
        "delivered_at",
        "created_at",
    },
}


@pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS), ids=sorted(EXPECTED_COLUMNS))
async def test_the_lease_columns_landed(conn: AsyncConnection, table: str) -> None:
    rows = (
        await conn.execute(
            text(
                "select column_name from information_schema.columns"
                " where table_schema = 'promisepatch' and table_name = :table"
            ),
            {"table": table},
        )
    ).scalars()
    assert set(rows) >= EXPECTED_COLUMNS[table]


async def test_a_row_records_when_it_was_created_without_being_told(
    app_conn: AsyncConnection,
) -> None:
    """``created_at`` is the claim sweep's tiebreak, so it must never be the caller's to forget."""
    step_id = uuid4()
    await app_conn.execute(insert(CaseStep).values(**a_step(id=step_id)))
    created = (
        await app_conn.execute(select(CaseStep.created_at).where(CaseStep.id == step_id))
    ).scalar_one()
    assert created is not None
