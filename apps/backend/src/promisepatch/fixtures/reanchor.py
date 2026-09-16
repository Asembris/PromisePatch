"""Move a seeded demo world forward to today, without replacing a single row.

``docs/demo-fixture-anchoring.md`` established the defect this closes. Every instant in the
shipped fixture is an offset from the anchor a seed chose, and a seed is taken once per
instance; so the world's *today* is the bootstrap day for ever, and a case opened on any later
day resolves *today's raspberry delivery* to a delivery no promise is waiting on and falls
silently to four blocked bands. The decay is in the durable rows, not in the rule that wrote
them, which is why no change to :func:`promisepatch.fixtures.demo.resolve_demo_anchor` can
repair it.

**A roll is a shift, never a reload.** ``reset_demo_state`` empties every demo-owned table and
writes the fixture again: it is the right operation for an operator who wants a known state
back, and the wrong one for a process that runs by itself, because it takes the cases, the
sessions and the order mirror's version numbers with it. What this does instead is add one
duration to every instant the fixture owns. Nothing is truncated, no id moves, no session is
signed out, and every non-instant edit -- an external order change that crossed as a webhook,
say -- survives untouched, because a column holding a quantity is never written here at all.

**The duration is measured, not remembered.** It is the difference between where today's Valley
Produce delivery *is* in the durable rows and where a seed taken now would put it, read back
through the fixture's own offset. So a world that has already been rolled, or seeded by an
operator at an anchor nobody recorded, lands in the same place as one that has not, and
``fixture_state`` is bookkeeping rather than the thing correctness depends on.

**Which columns move is derived from the projection, not listed here.** A list would be a second
copy of the schema and would go stale the first time a table gained a time. :func:`shiftable`
projects the fixture and asks which columns really hold a ``datetime``, which is the same
question the seed answers when it writes them.

**Two instants deliberately do not move**, and both are append-only by
:data:`promisepatch.db.boundary.APPEND_ONLY_TABLES` -- an ``UPDATE`` on them fails as immutable
whatever authorises it. ``recipe_versions.authored_at`` is when somebody wrote a recipe down and
``inventory_ledger.recorded_at`` is when a posting was made; both are history, neither is read
against the clock to decide a band, and leaving them where they are is more truthful than
pretending the recipes were authored this morning. ``fixture_state.fixture_digest`` is therefore
left alone as well: it is the digest of the load this world descends from, and overwriting it
with the digest of a fresh seed would claim those two columns had moved when they had not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.examples import hollow_oak
from promisepatch.db.base import SCHEMA
from promisepatch.db.boundary import APPEND_ONLY_TABLES
from promisepatch.db.events import append_event
from promisepatch.db.models import FixtureState, SupplierCommitment
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.fixtures import demo
from promisepatch.fixtures.projection import project, project_staff
from promisepatch.fixtures.reset import AUDIT_EVENT_TYPE, FIXTURE_STATE_ID, LOCK_KEY
from promisepatch.observability import get_logger

logger = get_logger(__name__)

DOMAIN_EVENT_TYPE: Final = "fixture.reanchored"
"""The graph was not replaced -- it was moved. Saying ``fixture.reset`` here would be a lie."""

OPERATION: Final = "reanchor"
"""Distinguishes this row from a reload in the shared ``FIXTURE_LOAD`` audit vocabulary.

The same audit event type on purpose: both are the demo fixture being put where an operator or
this process wants it, both are authorised by nothing but that wish, and an operator reading the
ledger for *what happened to the demo world* should find both under one name.
"""

_ADVISORY_LOCK = text("SELECT pg_advisory_xact_lock(:key)")
"""The reset's own lock, so a roll and an operator's reload can never interleave."""

_DIGEST_PLACEHOLDER: Final = ""
"""Stands in for a password hash while columns are being *discovered* rather than written.

``project_staff`` needs a hash per worker to build a row. Nothing here writes one, and the only
use of the row is to ask which of its columns hold a time.
"""


@dataclass(frozen=True, slots=True)
class ReanchorOutcome:
    """What a roll moved, in terms an operator reading a log and a test can both check."""

    shifted_by: timedelta
    from_anchor: datetime
    to_anchor: datetime
    rows_moved: int

    @property
    def moved(self) -> bool:
        return self.shifted_by != timedelta(0)


def shiftable() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Every fixture-owned column that holds an instant and can be written after the fact.

    Derived by projecting the fixture and looking at the values, so a table that gains a time
    is carried by this without anybody remembering to add it, and an append-only table is
    excluded by the same boundary constant the database's own trigger is built from.
    """
    anchor = hollow_oak.ANCHOR
    tables = (
        *project(demo.build_snapshot(anchor), mirrored_at=anchor),
        project_staff(
            demo.SEEDED_WORKERS,
            password_hashes={seed.worker_id: _DIGEST_PLACEHOLDER for seed in demo.SEEDED_WORKERS},
            created_at=anchor,
        ),
    )
    found = []
    for table in tables:
        if table.table in APPEND_ONLY_TABLES:
            continue
        columns = sorted(
            {
                column
                for row in table.rows
                for column, value in row.items()
                if isinstance(value, datetime)
            }
        )
        if columns:
            found.append((table.table, tuple(columns)))
    return tuple(found)


async def measure_drift(connection: AsyncConnection, *, anchor: datetime) -> timedelta:
    """How far the durable world is from where a seed taken at ``anchor`` would put it.

    Read off today's Valley Produce delivery, because that one commitment is what the canonical
    report narrows on and therefore what decides whether the demo tells its story at all. The
    offset comes from the fixture rather than from a number typed here, for this package's
    standing reason.
    """
    due_at = await connection.scalar(
        select(SupplierCommitment.due_at).where(SupplierCommitment.id == hollow_oak.VP_TODAY)
    )
    if due_at is None:
        raise WorldNotSeededError("no Valley Produce delivery is loaded; there is nothing to move")
    wanted = anchor + (
        hollow_oak.hollow_oak(hollow_oak.ANCHOR).commitments[hollow_oak.VP_TODAY].due_at
        - hollow_oak.ANCHOR
    )
    return wanted - due_at


class WorldNotSeededError(RuntimeError):
    """The database holds no demo world, so there is nothing to move and nothing to guess at."""


async def reanchor_world(
    connection: AsyncConnection, *, anchor: datetime, now: datetime, actor: Actor
) -> ReanchorOutcome:
    """Move every fixture-owned instant so the world reads as though it were seeded at ``anchor``.

    The caller owns the transaction and the decision to commit it, exactly as a reset's does.
    """
    await connection.execute(_ADVISORY_LOCK, {"key": LOCK_KEY})

    drift = await measure_drift(connection, anchor=anchor)
    from_anchor = anchor - drift
    if drift == timedelta(0):
        return ReanchorOutcome(drift, from_anchor, anchor, rows_moved=0)

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_EVENT_TYPE,
        actor=actor,
        # No policy and no consent permitted this, and nobody approved it: the deployment moved
        # its own demo world so the story it tells is still today's. Recording that honestly is
        # better than dressing it up as an authority it does not have.
        authority="NONE",
        before={"anchor": from_anchor.isoformat()},
        after={
            "operation": OPERATION,
            "fixture": demo.FIXTURE_NAME,
            "anchor": anchor.isoformat(),
            "shifted_by_seconds": drift.total_seconds(),
        },
        occurred_at=now,
    ) as write:
        moved = 0
        for table, columns in shiftable():
            # Every column of a table in one statement, which is a correctness requirement and
            # not a tidiness one: ``production_tasks`` carries a CHECK that its scheduled start
            # precedes its scheduled end, and moving one of the pair and then the other leaves a
            # row that breaks it in between. A single SET moves them together and is never seen
            # half-applied.
            assignment = ", ".join(
                f'"{column}" = "{column}" + CAST(:drift AS interval)' for column in columns
            )
            result = await write.execute(
                text(f'UPDATE {SCHEMA}."{table}" SET {assignment}').bindparams(drift=drift)
            )
            moved += int(result.rowcount or 0)

        await write.execute(
            update(FixtureState)
            .where(FixtureState.id == FIXTURE_STATE_ID)
            .values(anchor_at=anchor, loaded_at=now)
        )
        await append_event(
            write.connection,
            event_type=DOMAIN_EVENT_TYPE,
            correlation_id=write.correlation_id,
            occurred_at=now,
            payload={
                "fixture": demo.FIXTURE_NAME,
                "from_anchor": from_anchor.isoformat(),
                "to_anchor": anchor.isoformat(),
                "shifted_by_seconds": drift.total_seconds(),
            },
        )

    logger.info(
        "fixture.reanchored",
        from_anchor=from_anchor.isoformat(),
        to_anchor=anchor.isoformat(),
        shifted_by_seconds=drift.total_seconds(),
        rows_moved=moved,
    )
    return ReanchorOutcome(drift, from_anchor, anchor, rows_moved=moved)
