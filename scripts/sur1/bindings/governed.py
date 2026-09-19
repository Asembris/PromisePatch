"""The one way this harness writes a row PromisePatch governs, and why it has to be this way.

Two of the world's powers land in PromisePatch's own tables. A hold on a production task is an
``UPDATE`` on ``production_tasks`` and a stipulated stock movement is an ``INSERT`` into
``inventory_ledger``, and both of those tables are in
:data:`~promisepatch.db.boundary.GOVERNED_TABLES`: the database's ``assert_governed_write``
trigger refuses any statement against them that is not accompanied, *in the same transaction*,
by an ``audit_events`` row this transaction wrote.

Both writers used to issue a bare statement on a bare connection, which the trigger refuses
every single time. It was never noticed because neither had ever been performed against the
live database -- the realisation check leaves declared events ``armed_and_unfired`` and the
dress rehearsal fired none -- so the first execution of both was the first scored run, where
they cost three attempts. See ``docs/sur1-first-scored-run-defect.md`` §2.2 and the correction
record beside it.

**The fix is to write governed, not to make the database lenient.** Nothing here weakens a
trigger, grants a privilege or reaches around the boundary. It opens one transaction, asks the
product's *own* :meth:`~promisepatch.db.uow.UnitOfWork.governed` block to authorise it, and
performs the statement inside it. The row the harness writes is audited exactly the way a
product write is audited.

**The audit says the benchmark did it.** Every event type here begins :data:`AUDIT_PREFIX`
and the actor is :data:`WORLD_ACTOR`, so a reader of the ledger can never mistake a measurement
harness's world facility for a decision the product made. That distinction is the reason these
rows are worth auditing at all.

The product's helper is imported inside the call for the reason
:mod:`~scripts.sur1.bindings.realisation` gives: this module is reachable from the program set
and the preflight, and importing the application's database layer at module scope would make
reading a hash open a connection pool.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from scripts.sur1.bindings.receivers import SCHEMA

AUDIT_PREFIX: Final = "BENCHMARK_WORLD_"
"""What every audit event this harness writes is called, so none reads as a product decision."""

TASK_HELD: Final = f"{AUDIT_PREFIX}TASK_HELD"
TASK_RELEASED: Final = f"{AUDIT_PREFIX}TASK_RELEASED"
STOCK_MOVEMENT: Final = f"{AUDIT_PREFIX}STOCK_MOVEMENT"
"""The three world writes, each named in the ledger by what it actually did."""

WORLD_ACTOR: Final = "sur1 world facility"
"""Who the ledger says performed it. Never a worker, never an owner, never a customer."""

AUTHORITY: Final = "NONE"
"""What permitted it: nothing did.

The honest answer and the one the product already uses for a fixture load. A benchmark world
doing what a scenario stipulated it would do is not a policy decision, not a customer
constraint and not a human approval, and recording it as one would put a false authority in the
ledger of record.
"""


class GovernedWriteError(RuntimeError):
    """A world write could not be performed against PromisePatch's own tables."""


@dataclass(frozen=True, slots=True)
class GovernedWriter:
    """One audited statement at a time, over the product's own unit of work.

    Shaped like the two writers it serves: a URL, a schema, one statement, and a count of the
    rows it actually moved. It holds no connection between calls, because a connection held
    open beside a fixture load is the thing that deadlocks a ``TRUNCATE``.
    """

    url: str
    schema: str = SCHEMA

    def write(
        self,
        *,
        event_type: str,
        after: Mapping[str, Any],
        statement: str,
        parameters: Mapping[str, Any],
    ) -> int:
        """Perform one governed statement and report how many rows it moved.

        ``statement`` names its parameters in SQLAlchemy's ``:name`` form and is expected to
        ``RETURNING`` something, for the reason :class:`~scripts.sur1.bindings.setup.
        KitchenWriter` gives: the difference between performed and refused is the difference
        between one row and none, and a parsed status tag is a second thing to get wrong.
        """
        try:
            return asyncio.run(
                self._write(
                    event_type=event_type,
                    after=dict(after),
                    statement=statement,
                    parameters=dict(parameters),
                )
            )
        except GovernedWriteError:
            raise
        except Exception as failure:
            raise GovernedWriteError(f"{type(failure).__name__}: {failure}") from failure

    async def _write(
        self,
        *,
        event_type: str,
        after: Mapping[str, Any],
        statement: str,
        parameters: Mapping[str, Any],
    ) -> int:
        from sqlalchemy import text

        from promisepatch.db.session import build_engine
        from promisepatch.db.uow import Actor, UnitOfWork

        engine = build_engine(sqlalchemy_url(self.url), pool_size=1)
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'SET search_path TO "{self.schema}", public'))
                unit_of_work = UnitOfWork(connection)
                async with unit_of_work.governed(
                    event_type=event_type,
                    actor=Actor(kind="SYSTEM", id=WORLD_ACTOR),
                    authority=AUTHORITY,
                    after=dict(after),
                ):
                    moved = await connection.execute(text(statement), dict(parameters))
                    return len(moved.fetchall())
        finally:
            await engine.dispose()


def sqlalchemy_url(url: str) -> str:
    """The receivers' connection string, spelled the way the application's engine wants it.

    The receivers normalise ``postgresql+asyncpg`` *down* to a bare DSN because ``asyncpg``
    wants one; this normalises the same value *up*, because ``create_async_engine`` refuses a
    URL with no async driver on it. Two spellings of one database, and neither is a second
    database -- which is the property :func:`~scripts.sur1.bindings.realisation._same_database`
    exists to keep true.
    """
    scheme, separator, rest = url.partition("://")
    if not separator:
        return url
    base = scheme.split("+")[0]
    return f"{base}+asyncpg{separator}{rest}"


__all__ = [
    "AUDIT_PREFIX",
    "AUTHORITY",
    "STOCK_MOVEMENT",
    "TASK_HELD",
    "TASK_RELEASED",
    "WORLD_ACTOR",
    "GovernedWriteError",
    "GovernedWriter",
    "sqlalchemy_url",
]
