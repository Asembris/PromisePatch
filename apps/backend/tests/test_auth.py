"""Authentication behaviour, against the real database and the seeded demo logins.

The properties asserted here are the ones an attacker would probe: whether a failed login
tells you which usernames exist, whether a session survives being revoked, whether a cookie
can be forged, and whether a mutation can be triggered from another site.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx2 import Response as HttpResponse
from sqlalchemy import insert, select
from starlette.responses import Response
from starlette.testclient import TestClient

from promisepatch.api.auth import cookies, passwords, sessions
from promisepatch.api.auth.rate_limit import FixedWindowLimiter
from promisepatch.api.dependencies import role_guard
from promisepatch.api.routers import auth as auth_router
from promisepatch.config import Environment, Settings
from promisepatch.db import RuntimeDatabase
from promisepatch.db.models import Session

BAKER = "maya"
OWNER = "jo"

pytestmark = pytest.mark.integration


def password_for(role: str) -> str:
    settings = Settings()
    if role == "baker":
        return settings.require_demo_worker_password()
    return settings.require_demo_owner_password()


def login(api: TestClient, username: str, password: str) -> HttpResponse:
    return api.post("/api/auth/login", json={"username": username, "password": password})


def csrf(api: TestClient) -> dict[str, str]:
    return {cookies.CSRF_HEADER: api.cookies[cookies.CSRF_COOKIE]}


def principal(role: str) -> sessions.Principal:
    return sessions.Principal(
        worker_id=BAKER if role == "baker" else OWNER,
        username=BAKER if role == "baker" else OWNER,
        display_name="Maya" if role == "baker" else "Jo",
        role=role,
        session_id=uuid4(),
        csrf_token="a-token",
    )


# --------------------------------------------------------------------------------- logging in


def test_the_baker_can_sign_in(api: TestClient) -> None:
    response = login(api, BAKER, password_for("baker"))

    assert response.status_code == 200
    assert response.json()["worker"] == {
        "id": BAKER,
        "username": BAKER,
        "display_name": "Maya",
        "role": "baker",
    }


def test_the_owner_can_sign_in(api: TestClient) -> None:
    response = login(api, OWNER, password_for("owner"))

    assert response.status_code == 200
    assert response.json()["worker"]["role"] == "owner"


def test_a_login_response_carries_no_secret(api: TestClient) -> None:
    """Not the hash, not the session id, not the CSRF token: only safe identity."""
    body = login(api, BAKER, password_for("baker")).text

    assert "password_hash" not in body
    assert "$argon2" not in body
    assert api.cookies[cookies.CSRF_COOKIE] not in body
    assert api.cookies[cookies.SESSION_COOKIE] not in body


def test_an_unknown_user_and_a_wrong_password_are_indistinguishable(api: TestClient) -> None:
    """The single most useful thing a login endpoint can refuse to tell an attacker."""
    unknown = login(api, "nobody-here", "whatever-they-typed")
    wrong = login(api, BAKER, "not-the-right-password")

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert unknown.json() == {
        "error": {
            "code": "INVALID_CREDENTIALS",
            "message": "the username or password is incorrect",
        }
    }
    assert cookies.SESSION_COOKIE not in unknown.cookies
    assert cookies.SESSION_COOKIE not in wrong.cookies


def test_an_unknown_user_still_costs_a_verification() -> None:
    """The timing side of the same property, asserted at the function that provides it."""
    assert passwords.verify_unknown_user("anything") is False
    assert passwords.DUMMY_HASH.startswith("$argon2")


def test_a_login_from_an_unserved_origin_is_refused(api: TestClient) -> None:
    """Login carries no CSRF token, so the origin is what stands in for one."""
    response = api.post(
        "/api/auth/login",
        json={"username": BAKER, "password": password_for("baker")},
        headers={"Origin": "http://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"


def test_a_login_from_the_configured_origin_is_allowed(
    api: TestClient, runtime_settings: Settings
) -> None:
    """The allowlist is configuration, so the origin under test is read rather than assumed.

    A literal here would assert nothing about the allowlist and everything about one
    deployment's default: it passes because the default happens to be that string, and fails
    the moment a stack serves the frontend from any other port.
    """
    response = api.post(
        "/api/auth/login",
        json={"username": BAKER, "password": password_for("baker")},
        headers={"Origin": runtime_settings.cors_origin_list[0]},
    )

    assert response.status_code == 200


def test_a_malformed_login_body_is_reported_without_internals(api: TestClient) -> None:
    response = api.post("/api/auth/login", json={"username": BAKER})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "password" not in response.text


# ------------------------------------------------------------------------------------- cookies


def test_the_session_cookie_is_http_only_and_same_site_lax(api: TestClient) -> None:
    response = login(api, BAKER, password_for("baker"))

    header = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{cookies.SESSION_COOKIE}=")
    )
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Path=/" in header
    # Local development is plain HTTP on loopback; a Secure-only cookie would never arrive.
    assert "Secure" not in header


def test_the_csrf_cookie_is_readable_by_the_client(api: TestClient) -> None:
    """The client must echo it in a header, so this one cookie is deliberately not HttpOnly."""
    response = login(api, BAKER, password_for("baker"))

    header = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{cookies.CSRF_COOKIE}=")
    )
    assert "HttpOnly" not in header
    assert "SameSite=lax" in header


def test_cookies_are_secure_outside_local_mode() -> None:
    """Asserted at the function that sets the flags, so it needs no deployed database."""
    response = Response()
    cookies.set_session_cookies(
        response,
        cookie_value="abc.def",
        csrf_token="token",
        max_age=60,
        settings=Settings(env=Environment.AWS),
    )

    headers = response.headers.getlist("set-cookie")
    assert len(headers) == 2
    for header in headers:
        assert "Secure" in header


def test_a_forged_session_cookie_is_rejected(api: TestClient) -> None:
    """An unsigned id never reaches the database: the MAC fails first."""
    api.cookies.set(cookies.SESSION_COOKIE, f"{uuid4()}.forged-signature")

    response = api.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_the_signature_is_bound_to_the_secret() -> None:
    session_id = uuid4()
    signed = cookies.sign(session_id, "the-real-secret")

    assert cookies.unsign(signed, "the-real-secret") == session_id
    assert cookies.unsign(signed, "a-different-secret") is None
    assert cookies.unsign("not-even-shaped-like-a-cookie", "the-real-secret") is None
    assert cookies.unsign(f"not-a-uuid.{signed.partition('.')[2]}", "the-real-secret") is None


# ---------------------------------------------------------------------------------- the session


def test_me_returns_the_signed_in_worker(api: TestClient) -> None:
    login(api, OWNER, password_for("owner"))

    response = api.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["worker"]["username"] == OWNER


def test_me_without_a_session_is_unauthenticated(api: TestClient) -> None:
    response = api.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "UNAUTHENTICATED", "message": "a valid session is required"}
    }


def test_logout_revokes_the_session_row(api: TestClient) -> None:
    """Replaying the cookie after logout proves the row, not the cookie, is doing the work."""
    login(api, BAKER, password_for("baker"))
    cookie = api.cookies[cookies.SESSION_COOKIE]
    headers = csrf(api)

    assert api.post("/api/auth/logout", headers=headers).status_code == 204

    api.cookies.set(cookies.SESSION_COOKIE, cookie)
    assert api.get("/api/auth/me").status_code == 401


def test_logout_clears_both_cookies(api: TestClient) -> None:
    login(api, BAKER, password_for("baker"))

    response = api.post("/api/auth/logout", headers=csrf(api))

    cleared = " ".join(response.headers.get_list("set-cookie"))
    assert cookies.SESSION_COOKIE in cleared
    assert cookies.CSRF_COOKIE in cleared


async def test_an_expired_session_is_rejected(database: RuntimeDatabase) -> None:
    """Expiry is compared in the query that loads the session, not by trusting the client."""
    session_id = uuid4()
    now = datetime.now(UTC)
    expired = now - timedelta(hours=1)
    async with database.begin() as connection:
        await connection.execute(
            insert(Session).values(
                id=session_id,
                worker_id=BAKER,
                csrf_token="irrelevant",
                created_at=expired - sessions.SESSION_TTL,
                expires_at=expired,
                revoked_at=None,
            )
        )
        resolved = await sessions.resolve(connection, session_id=session_id, now=now)

    assert resolved is None


async def test_a_revoked_session_is_rejected(database: RuntimeDatabase) -> None:
    now = datetime.now(UTC)
    async with database.begin() as connection:
        issued = await sessions.create(connection, worker_id=BAKER, now=now)
        assert await sessions.resolve(connection, session_id=issued.session_id, now=now)

        await sessions.revoke(connection, session_id=issued.session_id, now=now)
        assert await sessions.resolve(connection, session_id=issued.session_id, now=now) is None


async def test_revoking_twice_keeps_the_first_revocation(database: RuntimeDatabase) -> None:
    """Idempotent, so a repeated logout cannot rewrite when the session actually ended."""
    now = datetime.now(UTC)
    later = now + timedelta(minutes=5)
    async with database.begin() as connection:
        issued = await sessions.create(connection, worker_id=BAKER, now=now)
        await sessions.revoke(connection, session_id=issued.session_id, now=now)
        await sessions.revoke(connection, session_id=issued.session_id, now=later)

        revoked_at = await connection.scalar(
            select(Session.revoked_at).where(Session.id == issued.session_id)
        )

    assert revoked_at == now


async def test_a_session_is_issued_entirely_server_side(database: RuntimeDatabase) -> None:
    """The client chooses neither the id, nor the expiry, nor the CSRF token."""
    now = datetime.now(UTC)
    async with database.begin() as connection:
        issued = await sessions.create(connection, worker_id=BAKER, now=now)

    assert issued.expires_at == now + sessions.SESSION_TTL
    assert len(issued.csrf_token) >= 32


# ---------------------------------------------------------------------------------------- CSRF


def test_a_mutation_without_a_csrf_token_is_refused(api: TestClient) -> None:
    login(api, BAKER, password_for("baker"))

    response = api.post("/api/auth/logout")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"
    # The refused mutation had no effect: the session is still usable.
    assert api.get("/api/auth/me").status_code == 200


def test_a_mutation_with_a_token_the_caller_chose_is_refused(api: TestClient) -> None:
    """The header is compared against the session row, so writing the cookie is not enough."""
    login(api, BAKER, password_for("baker"))
    forged = "a-token-the-attacker-chose"
    api.cookies.set(cookies.CSRF_COOKIE, forged)

    response = api.post("/api/auth/logout", headers={cookies.CSRF_HEADER: forged})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"


def test_csrf_is_not_required_for_a_read(api: TestClient) -> None:
    """A GET that changes nothing has no cross-origin effect to protect against."""
    login(api, BAKER, password_for("baker"))

    assert api.get("/api/auth/me").status_code == 200


def test_an_unauthenticated_mutation_is_unauthenticated_not_forbidden(api: TestClient) -> None:
    """Order matters: who are you is answered before prove this was intentional."""
    response = api.post("/api/auth/logout")

    assert response.status_code == 401


# --------------------------------------------------------------------------------------- roles


async def test_role_enforcement_admits_only_the_named_roles() -> None:
    """Two roles, checked explicitly. Asserted at the guard, which is where the rule lives."""
    owner_only = role_guard("owner")
    owner = principal("owner")

    assert await owner_only(owner) is owner
    with pytest.raises(HTTPException) as raised:
        await owner_only(principal("baker"))

    assert raised.value.status_code == 403


async def test_a_guard_naming_both_roles_admits_both() -> None:
    either = role_guard("baker", "owner")

    assert await either(principal("baker"))
    assert await either(principal("owner"))


def test_the_seeded_roles_are_the_two_the_architecture_names(api: TestClient) -> None:
    assert login(api, BAKER, password_for("baker")).json()["worker"]["role"] == "baker"
    api.cookies.clear()
    assert login(api, OWNER, password_for("owner")).json()["worker"]["role"] == "owner"


# ------------------------------------------------------------------------------- rate limiting


def test_repeated_attempts_are_limited_within_the_window() -> None:
    limiter = FixedWindowLimiter(limit=3, window=timedelta(minutes=1))
    start = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)

    assert [limiter.allow("caller", start) for _ in range(4)] == [True, True, True, False]
    assert limiter.allow("caller", start + timedelta(minutes=2))


def test_a_successful_login_clears_the_count() -> None:
    limiter = FixedWindowLimiter(limit=2, window=timedelta(minutes=1))
    start = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)

    limiter.allow("caller", start)
    limiter.forget("caller")

    assert limiter.allow("caller", start)
    assert limiter.allow("caller", start)


def test_one_caller_s_attempts_do_not_limit_another() -> None:
    limiter = FixedWindowLimiter(limit=1, window=timedelta(minutes=1))
    start = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)

    assert limiter.allow("first", start)
    assert not limiter.allow("first", start)
    assert limiter.allow("second", start)


def test_the_login_endpoint_refuses_a_flood(api: TestClient) -> None:
    for _ in range(auth_router._limiter.limit):
        login(api, BAKER, "wrong")

    response = login(api, BAKER, password_for("baker"))

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
