"""Login, logout, and who am I.

Three properties of ``login`` are worth stating because they are easy to lose in a refactor:

* **Unknown username and wrong password are one outcome.** Same status, same body, same code,
  and comparable time -- an unknown user is verified against a dummy Argon2 hash. A login
  endpoint that distinguishes them is a user directory with extra steps.
* **The session is issued server-side.** The client chooses nothing: not the id, not the
  expiry, not the CSRF token.
* **Login is the one mutation without a CSRF token, and is not therefore unprotected.** A
  token has to be bound to a session, and there is no session yet. What stands in for it is
  the credential itself, ``SameSite=Lax`` (so a cross-site POST carries no cookie at all), and
  an ``Origin`` check against the configured allowlist when the browser sends one.

``demo-session`` is the fourth endpoint and is not a login. It **issues** rather than
authenticates: there are no credentials to present, none are published anywhere, and no field of
the request names anybody -- the server chooses the principal, the expiry and the CSRF token, as
it does for a login. What the session it mints is *worth* is decided entirely elsewhere: it
names the seeded observer, and :func:`promisepatch.domain.intake.require_permitted` -- which
every write in this system gates on -- has no branch for one. The endpoint therefore cannot be
widened into a write by anything done here, which is why it is safe for it to ask for nothing.

Four bounds sit on it regardless, because "cannot do damage" is not a reason to leave a door
open: it is served only where :attr:`~promisepatch.config.Settings.demo_session_enabled` says
so, it is ``Origin``-checked exactly as login is, it is rate-limited per client by its own
limiter, and the session expires in an hour rather than a shift.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Response
from starlette.requests import Request

from promisepatch.api.auth import cookies, passwords, sessions
from promisepatch.api.auth.rate_limit import (
    FixedWindowLimiter,
    demo_session_limiter,
    login_limiter,
)
from promisepatch.api.dependencies import (
    ConnectionDep,
    CsrfPrincipalDep,
    PrincipalDep,
    SettingsDep,
    now,
)
from promisepatch.api.errors import ApiError
from promisepatch.api.schemas.auth import (
    LoginRequest,
    SignInOptions,
    WorkerIdentity,
    WorkerResponse,
)
from promisepatch.config import Settings
from promisepatch.domain import intake
from promisepatch.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_limiter: FixedWindowLimiter = login_limiter()
"""Process-wide login limiter. Proportional to one API process for one bakery."""

_demo_limiter: FixedWindowLimiter = demo_session_limiter()
"""A limiter of its own, so a burst of demo sessions cannot spend a real worker's
sign-in budget, and a script hammering either one cannot lock the other out."""

OBSERVER_ROLE: Final = "observer"
"""The role a demo session names.

Restated here rather than imported from the fixture module, so which principal this endpoint
issues for is a property of the API rather than of whichever dataset a deployment seeded.
A test asserts the database's own vocabulary still admits it.
"""

DEMO_SESSION_DISABLED = ApiError(
    status_code=404,
    code="NOT_FOUND",
    message="this deployment does not serve demo sessions",
)
"""A deployment that has not opted in has no such endpoint, and says so as one.

``404`` rather than ``403``: there is nothing here to be forbidden from. A distinct code
would tell an unauthenticated caller which deployments have the feature turned off, which
is a fact about a deployment they have no business learning from a refusal."""

DEMO_SESSION_UNAVAILABLE = ApiError(
    status_code=503,
    code="DEMO_SESSION_UNAVAILABLE",
    message="this deployment has no single observer for a demo session to name",
)
"""Turned on, but there is not exactly one observer seeded.

Fail closed on both sides of that. None means the migration ran and the fixture did not,
and inventing a principal would be creating an identity nobody seeded. More than one means
conflicting state about which principal a session names, and this system picks nothing when
the state conflicts -- even where every candidate is equally powerless."""

INVALID_CREDENTIALS = ApiError(
    status_code=401,
    code="INVALID_CREDENTIALS",
    message="the username or password is incorrect",
)
"""One rejection, reused, so the two paths cannot drift into distinguishable answers."""


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_origin(request: Request, settings: Settings) -> None:
    """Refuse a session request posted from an origin this deployment does not serve.

    Only checked when the header is present: a browser always sends it on a cross-site POST,
    and a command-line client legitimately sends none.
    """
    origin = request.headers.get("Origin")
    if origin and origin not in settings.cors_origin_list:
        raise ApiError(
            status_code=403,
            code="ORIGIN_NOT_ALLOWED",
            message="this origin may not sign in to this deployment",
        )


@router.get("/options", response_model=SignInOptions, summary="What ways in this deployment has")
async def options(settings: SettingsDep) -> SignInOptions:
    """Say which ways in exist, so the sign-in screen draws the ones that do.

    Unauthenticated, because the sign-in screen has no session by definition, and it discloses
    nothing about anybody: one boolean about this deployment's own configuration. The demo
    session is an advertised way in rather than a hidden one -- a judge is meant to find it by
    looking at the page -- so saying whether it is served costs nothing and stops a screen
    drawing a control that would be dead.

    It grants nothing either way. ``true`` here still issues no session; that needs the endpoint
    below, with its own flag check, its own ``Origin`` check and its own limiter.
    """
    return SignInOptions(demo_session=settings.demo_session_enabled)


@router.post("/login", response_model=WorkerResponse, summary="Sign in")
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    settings: SettingsDep,
    connection: ConnectionDep,
) -> WorkerResponse:
    _check_origin(request, settings)
    at = now()
    if not _limiter.allow(_client_key(request), at):
        raise ApiError(
            status_code=429,
            code="TOO_MANY_ATTEMPTS",
            message="too many sign-in attempts; wait a moment and try again",
        )

    worker = await sessions.find_worker(connection, body.username)
    if worker is None:
        # Deliberate work on a username that does not exist. See auth.passwords.
        passwords.verify_unknown_user(body.password)
        logger.info("auth.login_rejected", username_known=False)
        raise INVALID_CREDENTIALS
    if not passwords.verify(worker["password_hash"], body.password):
        logger.info("auth.login_rejected", username_known=True, worker_id=worker["id"])
        raise INVALID_CREDENTIALS

    issued = await sessions.create(connection, worker_id=worker["id"], now=at)
    _limiter.forget(_client_key(request))
    cookies.set_session_cookies(
        response,
        cookie_value=cookies.sign(issued.session_id, settings.require_session_secret()),
        csrf_token=issued.csrf_token,
        max_age=int(sessions.SESSION_TTL.total_seconds()),
        settings=settings,
    )
    logger.info("auth.login", worker_id=worker["id"], role=worker["role"])
    return WorkerResponse(
        worker=WorkerIdentity(
            id=worker["id"],
            username=worker["username"],
            display_name=worker["display_name"],
            role=worker["role"],
            may_report=intake.may_attest(worker["role"]),
        )
    )


@router.post(
    "/demo-session",
    response_model=WorkerResponse,
    summary="Open a scoped, read-only observer session",
)
async def demo_session(
    request: Request,
    response: Response,
    settings: SettingsDep,
    connection: ConnectionDep,
) -> WorkerResponse:
    """Issue a session for the seeded observer. It takes nothing in and publishes nothing.

    There is no request model, which is the strongest available form of "no caller may name an
    actor": a body naming a worker is not rejected by a validator, it is read by nothing at all.
    The principal is the one row this deployment seeded with the observer role, the expiry is an
    hour decided here, and the CSRF token is minted here -- the same three server-side decisions
    a login makes, with the credential check removed because there is no credential, and nothing
    for one to buy.

    What comes back is the ordinary ``WorkerResponse`` carrying ``role: "observer"``. The screen
    is told what it is holding rather than left to work it out, and the domain refuses every
    write regardless of what the screen does with the answer.
    """
    if not settings.demo_session_enabled:
        raise DEMO_SESSION_DISABLED
    _check_origin(request, settings)
    at = now()
    if not _demo_limiter.allow(_client_key(request), at):
        raise ApiError(
            status_code=429,
            code="TOO_MANY_ATTEMPTS",
            message="too many demo sessions from this client; wait a moment and try again",
        )

    observer = await sessions.find_sole_worker_with_role(connection, OBSERVER_ROLE)
    if observer is None:
        logger.error("auth.demo_session_unavailable")
        raise DEMO_SESSION_UNAVAILABLE

    issued = await sessions.create(
        connection,
        worker_id=observer["id"],
        now=at,
        ttl=sessions.OBSERVER_SESSION_TTL,
    )
    cookies.set_session_cookies(
        response,
        cookie_value=cookies.sign(issued.session_id, settings.require_session_secret()),
        csrf_token=issued.csrf_token,
        max_age=int(sessions.OBSERVER_SESSION_TTL.total_seconds()),
        settings=settings,
    )
    logger.info("auth.demo_session", worker_id=observer["id"], role=observer["role"])
    return WorkerResponse(
        worker=WorkerIdentity(
            id=observer["id"],
            username=observer["username"],
            display_name=observer["display_name"],
            role=observer["role"],
            may_report=intake.may_attest(observer["role"]),
        )
    )


@router.post("/logout", status_code=204, summary="Sign out")
async def logout(
    response: Response,
    principal: CsrfPrincipalDep,
    settings: SettingsDep,
    connection: ConnectionDep,
) -> Response:
    """Revoke the session row, then clear the cookies.

    In that order, and both: clearing a cookie asks a browser to forget a session, revoking
    the row means it no longer matters whether it did.
    """
    await sessions.revoke(connection, session_id=principal.session_id, now=now())
    cookies.clear_session_cookies(response, settings=settings)
    logger.info("auth.logout", worker_id=principal.worker_id)
    response.status_code = 204
    return response


@router.get("/me", response_model=WorkerResponse, summary="The signed-in worker")
async def me(principal: PrincipalDep) -> WorkerResponse:
    return WorkerResponse(
        worker=WorkerIdentity(
            id=principal.worker_id,
            username=principal.username,
            display_name=principal.display_name,
            role=principal.role,
            may_report=intake.may_attest(principal.role),
        )
    )
