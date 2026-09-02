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


def build_engine(url: str, *, echo: bool = False, pool_size: int = 5) -> AsyncEngine:
    """Build an async engine that behaves correctly behind a connection pooler."""
    return create_async_engine(
        url,
        echo=echo,
        future=True,
        pool_size=pool_size,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={
            "timeout": DEFAULT_CONNECT_TIMEOUT,
            "prepared_statement_cache_size": 0,
        },
    )
