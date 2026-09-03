"""The connection the running application serves requests over.

There are two ways into this database and they are not interchangeable. Migrations and schema
tests hold ``PP_MIGRATION_DATABASE_URL``: an owner that can create tables, install triggers and
grant privileges. Everything a request touches goes through ``PP_DATABASE_URL``, which is
``promisepatch_app`` -- a login that owns nothing, migrates nothing, cannot disable a trigger
and cannot rewrite an append-only ledger.

Keeping them apart is what makes the audited write boundary worth anything. A boundary the
application could step over by holding the owner's credential is a convention, not a control,
so this module refuses at construction to build a runtime engine out of anything but the
runtime role:

* :func:`login_role` reads the role out of the URL, tolerating the tenant suffix a connection
  pooler appends (``promisepatch_app.abcdef``);
* :meth:`RuntimeDatabase.from_settings` rejects any other role before a connection is opened,
  so pointing ``PP_DATABASE_URL`` at the migration credential is a startup failure rather than
  a quiet, total loss of least privilege;
* :meth:`RuntimeDatabase.current_user` asks the server who it thinks we are, which is the only
  answer that survives a pooler rewriting the login on the way through.

Nothing here logs a URL. The engine is built from a :class:`~pydantic.SecretStr` that is
unwrapped once, at the moment of construction, and the failures raised name the *variable* to
fix rather than the value it holds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from promisepatch.config import Settings
from promisepatch.db.boundary import RUNTIME_ROLE
from promisepatch.db.session import build_engine

CURRENT_USER = text("SELECT current_user")


class RuntimeRoleError(RuntimeError):
    """Raised when ``PP_DATABASE_URL`` does not name the least-privileged runtime role."""


def login_role(url: str) -> str:
    """The database role a connection string logs in as.

    A connection pooler multiplexes tenants over one endpoint and distinguishes them by
    appending a project reference to the login (``promisepatch_app.abcdef``), stripping it
    again before the server sees it. The role is therefore the part before the first dot,
    which is identical for a direct connection because there is no dot to find.
    """
    return (make_url(url).username or "").partition(".")[0]


@dataclass(frozen=True, slots=True)
class RuntimeDatabase:
    """The application's engine, and the lifecycle that owns it.

    Held on the application rather than created per request: an engine is a pool, and building
    one per request would open a connection per request, which is the thing a pool exists to
    stop. It is disposed explicitly on shutdown, so a reload leaves no sockets behind.
    """

    engine: AsyncEngine

    @classmethod
    def from_settings(cls, settings: Settings) -> RuntimeDatabase:
        """Build the runtime engine, refusing anything that is not the runtime role."""
        url = settings.require_database_url()
        role = login_role(url)
        if role != RUNTIME_ROLE:
            raise RuntimeRoleError(
                f"PP_DATABASE_URL logs in as {role!r}; the API must connect as "
                f"{RUNTIME_ROLE!r}. Administrative credentials belong to "
                "PP_MIGRATION_DATABASE_URL and are never used to serve a request."
            )
        return cls(engine=build_engine(url))

    async def dispose(self) -> None:
        """Close every pooled connection. Safe to call more than once."""
        await self.engine.dispose()

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[AsyncConnection]:
        """One transaction, committed if the block returns and rolled back if it raises."""
        async with self.engine.begin() as connection:
            yield connection

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        """A connection whose transaction is rolled back: for reads that must not write."""
        async with self.engine.connect() as connection:
            yield connection

    async def current_user(self, connection: AsyncConnection) -> str:
        """Who the *server* thinks is connected.

        The URL says what we asked for; this says what we got. On a pooled endpoint those can
        differ, and only the second one governs what the database will permit.
        """
        return str((await connection.execute(CURRENT_USER)).scalar_one())
