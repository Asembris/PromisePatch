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
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from starlette.requests import Request

from promisepatch.api.auth import cookies, passwords, sessions
from promisepatch.api.auth.rate_limit import FixedWindowLimiter, login_limiter
from promisepatch.api.dependencies import (
    ConnectionDep,
    CsrfPrincipalDep,
    PrincipalDep,
    SettingsDep,
    now,
)
from promisepatch.api.errors import ApiError
from promisepatch.api.schemas.auth import LoginRequest, WorkerIdentity, WorkerResponse
from promisepatch.config import Settings
from promisepatch.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_limiter: FixedWindowLimiter = login_limiter()
"""Process-wide login limiter. Proportional to one API process for one bakery."""

INVALID_CREDENTIALS = ApiError(
    status_code=401,
    code="INVALID_CREDENTIALS",
    message="the username or password is incorrect",
)
"""One rejection, reused, so the two paths cannot drift into distinguishable answers."""


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_origin(request: Request, settings: Settings) -> None:
    """Refuse a login posted from an origin this deployment does not serve.

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
        )
    )
