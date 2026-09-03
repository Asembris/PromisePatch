"""``pp reset-demo-state``: put the database back to a known graph, and say so in the ledger.

A demo reset is the most destructive operation this system has, so it is built out of the same
parts as every other consequential write rather than around them.

* **It is audited, not exempt.** The whole reset happens inside one
  :meth:`~promisepatch.db.uow.UnitOfWork.governed` block, so the ``FIXTURE_LOAD`` audit event
  is written first and the database's own trigger is what permits the truncations and inserts.
  There is no privileged path; the reset is authorised exactly the way a recovery amendment is.
* **It never empties the ledgers of record.** ``audit_events`` and ``domain_events`` are outside
  the reset set and are refused truncation by trigger regardless. The history of what was done
  survives every reset, which is what makes "reset" a demo convenience rather than a way to
  make evidence disappear.
* **It is one transaction, serialised against itself.** A PostgreSQL advisory transaction lock
  is taken first, so two operators pressing the button at once produce one reset and one wait,
  not two interleaved half-loads.
* **It waits for readers, and yields to them.** Truncation takes an exclusive lock on every
  table it empties, so a reset issued while a graph load is open joins the lock queue behind
  it. That is the right way round -- answering a question about a customer promise outranks
  emptying the database -- but it does mean a reset can be cancelled by a server statement
  timeout instead of waiting indefinitely. Nothing is half-applied when that happens: the
  whole reset is one transaction, so a cancelled one leaves the previous state exactly as it
  was, and the operator runs it again.

**Idempotency is a claim about domain state, not about row counts everywhere.** Running the
reset twice at the same anchor leaves identical domain state and an identical digest; the audit
and event ledgers legitimately grow by one entry each time, because two resets did happen and
the record of them is exactly what must not be rewritten.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import uuid4

from argon2 import PasswordHasher
from sqlalchemy import Table, insert, text
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.config import Settings
from promisepatch.db.base import SCHEMA, metadata
from promisepatch.db.boundary import resettable_tables
from promisepatch.db.models import DomainEvent, FixtureState
from promisepatch.db.uow import Actor, GovernedWrite, UnitOfWork
from promisepatch.fixtures import demo
from promisepatch.fixtures.projection import TableRows, digest, project, project_staff

AUDIT_EVENT_TYPE: Final = "FIXTURE_LOAD"
"""The audit event that authorises a fixture load, named by the architecture."""

DOMAIN_EVENT_TYPE: Final = "fixture.reset"
"""The one event the spine needs: the graph was replaced wholesale at this sequence.

Nothing narrower would be true. ``entity_refs`` is empty on purpose -- it exists so a watcher
can recompute the tracks that were watching a touched entity, and after a reset there are no
tracks and no watches left to recompute.
"""

LOCK_NAME: Final = "promisepatch.fixture_reset"
LOCK_KEY: Final = int.from_bytes(
    hashlib.sha256(LOCK_NAME.encode("utf-8")).digest()[:8], "big", signed=True
)
"""Advisory lock key, derived from the operation's name so it cannot collide by accident."""

FIXTURE_STATE_ID: Final = 1
"""``fixture_state`` holds one row, and the schema has a ``CHECK`` saying so."""

_ADVISORY_LOCK = text("SELECT pg_advisory_xact_lock(:key)")


class FixtureResetNotAllowedError(RuntimeError):
    """Raised when a reset is attempted in a deployment that has not opted into one."""


@dataclass(frozen=True, slots=True)
class ResetOutcome:
    """What a reset did, in terms an operator and a test can both check."""

    fixture_name: str
    anchor: datetime
    loaded_at: datetime
    digest: str
    audit_seq: int
    domain_event_seq: int
    row_counts: Mapping[str, int]

    @property
    def rows_written(self) -> int:
        return sum(self.row_counts.values())


def ensure_reset_allowed(settings: Settings) -> None:
    """Refuse a reset unless this deployment has explicitly opted into fixture resets.

    The guard is a setting rather than an environment check because "is this the demo database"
    is not something a process can work out from its own hostname, and guessing wrong deletes
    the wrong data.
    """
    if not settings.allow_fixture_reset:
        raise FixtureResetNotAllowedError(
            "fixture resets are disabled; set PP_ALLOW_FIXTURE_RESET=true to enable one."
        )


async def reset_demo_state(
    connection: AsyncConnection,
    *,
    anchor: datetime,
    now: datetime,
    passwords: Mapping[str, str],
    actor: Actor,
) -> ResetOutcome:
    """Replace all demo-owned state with the fixture at ``anchor``, in one audited transaction.

    ``passwords`` is keyed by staff role. The caller owns the transaction, because a reset is a
    write like any other and the decision to commit it belongs to whoever asked for it.
    """
    await connection.execute(_ADVISORY_LOCK, {"key": LOCK_KEY})

    snapshot = demo.build_snapshot(anchor)
    hasher = PasswordHasher()
    hashes = {seed.worker_id: hasher.hash(passwords[seed.role]) for seed in demo.STAFF}

    # Every fixture-derived instant is measured from the anchor, including the two columns the
    # engine has no counterpart for. Using the wall clock for them would make the digest of an
    # otherwise identical reset different every time, which is precisely the property that
    # would make idempotency unprovable.
    tables = (
        *project(snapshot, mirrored_at=anchor),
        project_staff(demo.STAFF, password_hashes=hashes, created_at=anchor),
    )
    fixture_digest = digest(fixture_name=demo.FIXTURE_NAME, anchor=anchor, tables=tables)

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_EVENT_TYPE,
        actor=actor,
        # No policy and no consent permitted this: an operator asked for a known state back.
        # Recording that honestly is better than dressing it up as something it was not.
        authority="NONE",
        after={
            "fixture": demo.FIXTURE_NAME,
            "anchor": anchor.isoformat(),
            "digest": fixture_digest,
        },
        occurred_at=now,
    ) as write:
        await write.execute(text(_truncate_statement()))
        for table_rows in tables:
            await _insert(write, table_rows)

        await write.execute(
            insert(FixtureState).values(
                id=FIXTURE_STATE_ID,
                anchor_at=anchor,
                loaded_at=now,
                fixture_name=demo.FIXTURE_NAME,
                fixture_digest=fixture_digest,
            )
        )
        domain_event_seq = (
            await write.execute(
                insert(DomainEvent)
                .values(
                    event_id=uuid4(),
                    type=DOMAIN_EVENT_TYPE,
                    case_id=None,
                    entity_refs=[],
                    payload={
                        "fixture": demo.FIXTURE_NAME,
                        "anchor": anchor.isoformat(),
                        "digest": fixture_digest,
                    },
                    correlation_id=write.correlation_id,
                    occurred_at=now,
                )
                .returning(DomainEvent.seq)
            )
        ).scalar_one()

        return ResetOutcome(
            fixture_name=demo.FIXTURE_NAME,
            anchor=anchor,
            loaded_at=now,
            digest=fixture_digest,
            audit_seq=write.audit_seq,
            domain_event_seq=int(domain_event_seq),
            row_counts={table.table: len(table.rows) for table in tables},
        )


def _truncate_statement() -> str:
    """Empty every demo-owned table in one statement, restarting their identity sequences.

    One statement rather than a delete per table, for two reasons that both matter. Foreign
    keys are satisfied by construction, because every referenced table is emptied in the same
    breath, so no deletion order has to be maintained alongside the insertion one. And the
    ledger tables here are append-only: they refuse a ``DELETE`` outright, so truncation is not
    a shortcut but the only way to reset one at all.

    ``RESTART IDENTITY`` is what makes the reloaded inventory ledger carry the same sequence
    numbers the engine's own copy does, so a fingerprint taken over stock is reproducible.
    """
    tables = ", ".join(f'{SCHEMA}."{table}"' for table in sorted(resettable_tables()))
    return f"TRUNCATE TABLE {tables} RESTART IDENTITY"


def _table(name: str) -> Table:
    return metadata.tables[f"{SCHEMA}.{name}"]


async def _insert(write: GovernedWrite, table_rows: TableRows) -> None:
    """Insert one table's rows as a single multi-row statement, preserving their order.

    Order is not cosmetic here: ``inventory_ledger`` draws its sequence numbers as the rows are
    written, so the order they are written in *is* the ledger's order.
    """
    if not table_rows.rows:
        return
    statement = insert(_table(table_rows.table)).values([dict(row) for row in table_rows.rows])
    await write.execute(statement)
