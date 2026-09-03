"""Server-side sessions: the rows that decide who is logged in.

A session is a row, not a token. That is the whole design, and it buys the two properties a
signed self-contained token cannot give without extra machinery:

* **Logout genuinely revokes.** ``revoked_at`` is set, and the very next request re-reads the
  row and is refused. Nothing depends on the browser having discarded a cookie.
* **Expiry is checked where it is enforced.** ``expires_at`` is compared in the query that
  loads the session, so an expired session cannot be resurrected by a clock the client
  controls.

Sessions are ungoverned by design (``db.boundary``): creating one is not a change to a
customer promise, and requiring an audit event to record that somebody logged in would audit
an arrival nobody has decided anything about yet.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.models import Session, Worker

SESSION_TTL: Final = timedelta(hours=12)
"""How long a login lasts.

Long enough to cover a bakery shift without a re-login mid-demo, short enough that an
unattended browser is not a standing key. A constant rather than a setting: nothing has asked
to vary it, and an unused environment variable is a promise the code does not keep.
"""

CSRF_TOKEN_BYTES: Final = 32


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is making this request, resolved from the session row and the worker it names.

    Carries no password hash and no cookie value. What a handler is allowed to see about the
    caller is exactly this, which is why the type exists rather than passing the row around.
    """

    worker_id: str
    username: str
    display_name: str
    role: str
    session_id: UUID
    csrf_token: str

    def has_role(self, *roles: str) -> bool:
        return self.role in roles


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A freshly created session, and the values the response needs to carry."""

    session_id: UUID
    csrf_token: str
    expires_at: datetime


async def find_worker(connection: AsyncConnection, username: str) -> dict[str, str] | None:
    """The stored worker for a username, including the hash the password is checked against."""
    table = Worker.__table__
    result = await connection.execute(
        select(
            table.c.id, table.c.username, table.c.display_name, table.c.role, table.c.password_hash
        ).where(table.c.username == username)
    )
    row = result.mappings().one_or_none()
    return None if row is None else dict(row)


async def create(connection: AsyncConnection, *, worker_id: str, now: datetime) -> IssuedSession:
    """Open a session for a worker, with its expiry and CSRF token decided server-side."""
    session_id = uuid4()
    csrf_token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
    expires_at = now + SESSION_TTL
    await connection.execute(
        insert(Session).values(
            id=session_id,
            worker_id=worker_id,
            csrf_token=csrf_token,
            created_at=now,
            expires_at=expires_at,
            revoked_at=None,
        )
    )
    return IssuedSession(session_id=session_id, csrf_token=csrf_token, expires_at=expires_at)


async def resolve(
    connection: AsyncConnection, *, session_id: UUID, now: datetime
) -> Principal | None:
    """The principal a session id names, or ``None`` if it names nothing usable.

    Revoked and expired are both ``None`` rather than distinct answers: a caller has no
    legitimate use for the difference, and telling them apart would say that a session id was
    real once.
    """
    sessions = Session.__table__
    workers = Worker.__table__
    result = await connection.execute(
        select(
            sessions.c.id,
            sessions.c.csrf_token,
            workers.c.id.label("worker_id"),
            workers.c.username,
            workers.c.display_name,
            workers.c.role,
        )
        .join(workers, workers.c.id == sessions.c.worker_id)
        .where(
            sessions.c.id == session_id,
            sessions.c.revoked_at.is_(None),
            sessions.c.expires_at > now,
        )
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    return Principal(
        worker_id=row["worker_id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        session_id=row["id"],
        csrf_token=row["csrf_token"],
    )


async def revoke(connection: AsyncConnection, *, session_id: UUID, now: datetime) -> None:
    """Revoke a session. Idempotent: revoking a revoked session leaves the first time stamped."""
    await connection.execute(
        update(Session)
        .where(Session.id == session_id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )
