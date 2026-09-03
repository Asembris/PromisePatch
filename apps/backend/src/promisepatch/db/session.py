"""Engine construction.

The only connection that exists today is the administrative one used for migrations and
schema tests. The runtime connection is a separate, least-privileged role and arrives with
the audited write boundary.

**Connection pooler note.** A managed Postgres endpoint is usually a PgBouncer in front of the
database. SQLAlchemy's asyncpg driver keeps its own prepared-statement cache, and a cached
statement handle is only valid for the server connection that created it — which a pooler is
free to swap underneath us. ``prepared_statement_cache_size=0`` trades a small amount of
throughput for correctness against any pooling mode, which is the right trade for a system
whose whole point is that state transitions are trustworthy.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

DEFAULT_CONNECT_TIMEOUT = 15

POOLER_SAFE_CONNECT_ARGS: dict[str, int] = {
    "timeout": DEFAULT_CONNECT_TIMEOUT,
    # Zero, not merely small: any cached statement handle can be invalidated by a pooler
    # swapping the server connection underneath it.
    "prepared_statement_cache_size": 0,
}
"""The driver arguments that make this engine correct behind a pooler, named so a test can
assert them. Reading them off a constructed engine would mean reaching into private pool
attributes, which is a worse guarantee than checking the input everything is built from."""


def build_engine(url: str, *, echo: bool = False, pool_size: int = 5) -> AsyncEngine:
    """Build an async engine that behaves correctly behind a connection pooler."""
    return create_async_engine(
        url,
        echo=echo,
        future=True,
        pool_size=pool_size,
        # No overflow: a least-privileged role has a connection budget, and a burst that
        # silently exceeded it would fail as a database outage rather than as backpressure.
        max_overflow=0,
        pool_pre_ping=True,
        connect_args=dict(POOLER_SAFE_CONNECT_ARGS),
    )
