"""What every request is given, and what every request must prove.

Four things are resolved here, in this order, because each depends on the one before: the
settings, the runtime database, the principal behind the session cookie, and -- for a mutation
-- the CSRF token bound to that session.

The CSRF design is session-backed double-submit. The token is generated when the session is
created and stored on the session row; the client reads it from a non-``HttpOnly`` cookie and
echoes it in ``X-CSRF-Token``; the server compares the header against **the row**, not against
the cookie. Comparing header to cookie alone would be satisfied by anyone who can write a
cookie; comparing against the row means the token has to have come from a real login.

Reads are exempt, which is correct rather than convenient: CSRF protects against a
cross-origin *effect*, and a GET that changes nothing has none. The endpoints in this slice
are all reads apart from login and logout.
"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.requests import Request

from promisepatch.api.auth.cookies import CSRF_HEADER, SESSION_COOKIE, unsign
from promisepatch.api.auth.sessions import Principal, resolve
from promisepatch.api.errors import ApiError
from promisepatch.config import Settings
from promisepatch.db import RuntimeDatabase


def now() -> datetime:
    """The wall clock, read at exactly one place in the request path.

    The engine never calls a clock; the application must, and doing it here keeps "when is
    now" a single answer for the whole of one request rather than a series of slightly
    different ones.
    """
    return datetime.now(UTC)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_database(request: Request) -> RuntimeDatabase:
    """The runtime engine, or an honest 503 if this process has none configured."""
    database: RuntimeDatabase | None = request.app.state.database
    if database is None:
        raise ApiError(
            status_code=503,
            code="DATABASE_UNAVAILABLE",
            message="this process has no database connection configured",
        )
    return database


async def get_connection(
    database: Annotated[RuntimeDatabase, Depends(get_database)],
) -> AsyncIterator[AsyncConnection]:
    """One transaction per request, committed on success and rolled back on any exception."""
    async with database.begin() as connection:
        yield connection


SettingsDep = Annotated[Settings, Depends(get_settings)]
DatabaseDep = Annotated[RuntimeDatabase, Depends(get_database)]
ConnectionDep = Annotated[AsyncConnection, Depends(get_connection)]


async def optional_principal(
    request: Request,
    settings: SettingsDep,
    connection: ConnectionDep,
) -> Principal | None:
    """The caller, if the cookie names a live session. ``None`` is a normal answer."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    session_id = unsign(cookie, settings.require_session_secret())
    if session_id is None:
        return None
    return await resolve(connection, session_id=session_id, now=now())


async def require_principal(
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Principal:
    """The caller, or 401. Absent, forged, expired and revoked are one answer on purpose."""
    if principal is None:
        raise ApiError(
            status_code=401,
            code="UNAUTHENTICATED",
            message="a valid session is required",
        )
    return principal


PrincipalDep = Annotated[Principal, Depends(require_principal)]


async def require_csrf(request: Request, principal: PrincipalDep) -> Principal:
    """Refuse a mutation whose CSRF token does not match the caller's session row."""
    presented = request.headers.get(CSRF_HEADER, "")
    if not presented or not hmac.compare_digest(presented, principal.csrf_token):
        raise ApiError(
            status_code=403,
            code="CSRF_TOKEN_INVALID",
            message=f"a matching {CSRF_HEADER} header is required for this request",
        )
    return principal


CsrfPrincipalDep = Annotated[Principal, Depends(require_csrf)]


def role_guard(*roles: str) -> Callable[[Principal], Awaitable[Principal]]:
    """The check itself: admit these roles, refuse the rest.

    Separated from :func:`require_role` so it can be exercised directly. A guard that can only
    be reached through a mounted route is a guard whose behaviour is asserted indirectly.
    """

    async def guard(principal: PrincipalDep) -> Principal:
        if not principal.has_role(*roles):
            raise ApiError(
                status_code=403,
                code="FORBIDDEN",
                message="this action requires a different role",
            )
        return principal

    return guard


def require_role(*roles: str) -> Principal:
    """A dependency admitting only the named roles.

    Two roles exist and the check is explicit at each route rather than inferred from a path
    prefix: a route that quietly became owner-only, or quietly stopped being, is the kind of
    change that should be visible in the route's own signature.
    """
    # The declared return type is what the *parameter* receives, which is the FastAPI idiom:
    # the marker object is replaced by the resolved dependency before the route body runs.
    return cast(Principal, Depends(role_guard(*roles)))
