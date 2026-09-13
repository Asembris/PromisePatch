"""Authentication behaviour, against the real database and the seeded demo logins.

The properties asserted here are the ones an attacker would probe: whether a failed login
tells you which usernames exist, whether a session survives being revoked, whether a cookie
can be forged, and whether a mutation can be triggered from another site.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from conftest import run_off_loop
from fastapi import HTTPException
from httpx2 import Response as HttpResponse
from sqlalchemy import delete, insert, select
from starlette.responses import Response
from starlette.testclient import TestClient

from promisepatch.api.auth import cookies, passwords, sessions
from promisepatch.api.auth.rate_limit import DEMO_SESSION_LIMIT, FixedWindowLimiter
from promisepatch.api.dependencies import role_guard
from promisepatch.api.routers import auth as auth_router
from promisepatch.config import Environment, Settings
from promisepatch.db import RuntimeDatabase
from promisepatch.db.models import Session
from promisepatch.db.models import Worker as WorkerRow
from promisepatch.db.types import WORKER_ROLES
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.domain import intake
from promisepatch.fixtures import demo as demo_fixtures
from promisepatch.main import create_app

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
        "may_report": True,
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


def test_me_tells_a_baker_the_domain_would_take_their_word(api: TestClient) -> None:
    """The screen asks the server whether to offer "report what happened", never a role table."""
    login(api, BAKER, password_for("baker"))

    assert api.get("/api/auth/me").json()["worker"]["may_report"] is True


def test_me_tells_an_observer_the_domain_would_not(demo: TestClient) -> None:
    demo.post("/api/auth/demo-session")

    assert demo.get("/api/auth/me").json()["worker"]["may_report"] is False


def test_the_field_is_the_rule_the_write_itself_enforces() -> None:
    """One rule, asked twice. A surface cannot be told yes where a write would hear no."""
    assert intake.may_attest("baker") is True
    assert intake.may_attest("owner") is True
    assert intake.may_attest(intake.OBSERVER_ROLE) is False


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


# ------------------------------------------------------------------ the scoped demo session


OBSERVER = "judge"
"""The seeded observer. Named here so a rename of the fixture fails a test rather than a demo."""


def demo_app(settings: Settings, *, enabled: bool = True) -> TestClient:
    """The real application, with the demo endpoint turned on or off by configuration alone."""
    auth_router._limiter.reset()
    auth_router._demo_limiter.reset()
    return TestClient(create_app(settings.model_copy(update={"demo_session_enabled": enabled})))


@pytest.fixture
def demo(runtime_settings: Settings, demo_state: object) -> Iterator[TestClient]:
    with demo_app(runtime_settings) as client:
        yield client


def test_the_role_a_demo_session_names_is_one_the_database_admits() -> None:
    """The endpoint names a role; the schema decides which roles exist. They must agree."""
    assert auth_router.OBSERVER_ROLE in WORKER_ROLES


def test_the_demo_endpoint_is_absent_unless_a_deployment_turns_it_on(
    runtime_settings: Settings, demo_state: object
) -> None:
    """Off by default, and off means gone: no session, no cookie, no distinguishable refusal."""
    with demo_app(runtime_settings, enabled=False) as client:
        response = client.post("/api/auth/demo-session")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert cookies.SESSION_COOKIE not in response.cookies


def test_a_demo_session_is_issued_to_the_seeded_observer(demo: TestClient) -> None:
    """No credentials in, an observer out. Nothing about the caller chose which one."""
    response = demo.post("/api/auth/demo-session")

    assert response.status_code == 200
    assert response.json()["worker"] == {
        "id": OBSERVER,
        "username": OBSERVER,
        "display_name": "Observer",
        "role": "observer",
        "may_report": False,
    }
    assert demo.get("/api/auth/me").json()["worker"]["role"] == "observer"


def test_a_body_naming_a_worker_changes_nothing(demo: TestClient) -> None:
    """There is no request model at all, so there is no field a caller could aim at one."""
    response = demo.post(
        "/api/auth/demo-session",
        json={"worker_id": BAKER, "username": OWNER, "role": "owner", "actor": OWNER},
    )

    assert response.status_code == 200
    assert response.json()["worker"]["id"] == OBSERVER


def test_the_observer_cannot_be_reached_by_signing_in(demo: TestClient) -> None:
    """Its stored hash is not a hash, so no password is the password. Same answer as any other."""
    attempts = ("judge", "observer", "password", demo_fixtures.UNUSABLE_PASSWORD_HASH)
    for attempt in attempts:
        response = login(demo, OBSERVER, attempt)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_a_demo_session_from_an_unlisted_origin_is_refused(demo: TestClient) -> None:
    """The same ``Origin`` allowlist login is checked against, checked here for the same reason."""
    response = demo.post(
        "/api/auth/demo-session", headers={"Origin": "https://not-this-deployment.example"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    assert cookies.SESSION_COOKIE not in response.cookies


def test_a_client_asking_for_too_many_demo_sessions_is_refused(demo: TestClient) -> None:
    """Bounded per client, by a limiter of its own rather than by sign-in's budget."""
    for _ in range(DEMO_SESSION_LIMIT):
        assert demo.post("/api/auth/demo-session").status_code == 200

    refused = demo.post("/api/auth/demo-session")

    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"


def test_the_demo_limiter_does_not_spend_the_sign_in_budget(demo: TestClient) -> None:
    """Two limiters, so exhausting one leaves the other exactly where it was."""
    for _ in range(DEMO_SESSION_LIMIT + 1):
        demo.post("/api/auth/demo-session")

    assert login(demo, BAKER, password_for("baker")).status_code == 200


def test_a_demo_session_expires_in_an_hour_rather_than_a_shift(demo: TestClient) -> None:
    """The bound is on the row the server wrote, not on a cookie a browser was asked to keep."""
    assert demo.post("/api/auth/demo-session").status_code == 200
    session_id = cookies.unsign(
        demo.cookies[cookies.SESSION_COOKIE], Settings().require_session_secret()
    )

    async def stored() -> tuple[datetime, datetime]:
        database = RuntimeDatabase.from_settings(Settings())
        try:
            async with database.connect() as connection:
                row = (
                    await connection.execute(
                        select(Session.created_at, Session.expires_at).where(
                            Session.id == session_id
                        )
                    )
                ).one()
            return row.created_at, row.expires_at
        finally:
            await database.dispose()

    created_at, expires_at = run_off_loop(stored)

    assert expires_at - created_at == sessions.OBSERVER_SESSION_TTL
    assert timedelta(minutes=60) == sessions.OBSERVER_SESSION_TTL
    assert sessions.OBSERVER_SESSION_TTL < sessions.SESSION_TTL


async def test_a_demo_session_past_its_hour_is_rejected(database: RuntimeDatabase) -> None:
    """Expiry is compared where it is enforced, so a clock the client holds cannot revive one."""
    now = datetime.now(UTC)
    async with database.begin() as connection:
        issued = await sessions.create(
            connection, worker_id=OBSERVER, now=now, ttl=sessions.OBSERVER_SESSION_TTL
        )
        an_hour_later = now + sessions.OBSERVER_SESSION_TTL + timedelta(seconds=1)

        assert await sessions.resolve(connection, session_id=issued.session_id, now=now)
        assert (
            await sessions.resolve(connection, session_id=issued.session_id, now=an_hour_later)
            is None
        )


def test_a_revoked_demo_session_stops_working_on_the_next_request(demo: TestClient) -> None:
    """It is an ordinary session row, so the ordinary kill switch ends it."""
    assert demo.post("/api/auth/demo-session").status_code == 200
    assert demo.get("/api/auth/me").status_code == 200
    session_id = cookies.unsign(
        demo.cookies[cookies.SESSION_COOKIE], Settings().require_session_secret()
    )
    assert session_id is not None

    async def kill() -> None:
        database = RuntimeDatabase.from_settings(Settings())
        try:
            async with database.begin() as connection:
                await sessions.revoke(connection, session_id=session_id, now=datetime.now(UTC))
        finally:
            await database.dispose()

    run_off_loop(kill)

    assert demo.get("/api/auth/me").status_code == 401


def test_turning_the_flag_off_ends_the_endpoint_without_a_code_change(
    runtime_settings: Settings, demo_state: object
) -> None:
    """The documented kill switch: one setting, and the door is not there on the next start."""
    with demo_app(runtime_settings, enabled=True) as on:
        assert on.post("/api/auth/demo-session").status_code == 200

    with demo_app(runtime_settings, enabled=False) as off:
        assert off.post("/api/auth/demo-session").status_code == 404


def test_a_deployment_with_no_observer_seeded_issues_nothing(
    runtime_settings: Settings, demo_state: object
) -> None:
    """Fails closed rather than inventing a principal nobody seeded."""
    with demo_app(runtime_settings) as client:
        removed = run_off_loop(lambda: _set_observer_present(False))
        try:
            response = client.post("/api/auth/demo-session")
        finally:
            if removed:
                run_off_loop(lambda: _set_observer_present(True))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEMO_SESSION_UNAVAILABLE"
    assert cookies.SESSION_COOKIE not in response.cookies


async def _set_observer_present(present: bool) -> bool:
    """Add or remove the seeded observer, under the audit the write boundary requires."""
    database = RuntimeDatabase.from_settings(Settings())
    try:
        async with database.begin() as connection:
            existing = await connection.scalar(select(WorkerRow.id).where(WorkerRow.id == OBSERVER))
            if bool(existing) == present:
                return False
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="AUTH_TEST_SETUP",
                actor=Actor(kind="SYSTEM", id="auth-tests"),
                authority="NONE",
            ) as write:
                await write.execute(
                    insert(WorkerRow).values(
                        id=OBSERVER,
                        username=OBSERVER,
                        display_name="Observer",
                        role="observer",
                        password_hash=demo_fixtures.UNUSABLE_PASSWORD_HASH,
                        created_at=datetime.now(UTC),
                    )
                    if present
                    else delete(WorkerRow).where(WorkerRow.id == OBSERVER)
                )
        return True
    finally:
        await database.dispose()


def test_the_sign_in_options_say_nothing_about_anybody(demo: TestClient) -> None:
    """One boolean about this deployment. No username, no principal, no session required."""
    response = demo.get("/api/auth/options")

    assert response.status_code == 200
    assert response.json() == {"demo_session": True}


def test_the_sign_in_options_are_readable_without_a_session(
    runtime_settings: Settings, demo_state: object
) -> None:
    """Read by the screen that has no session by definition, so it cannot require one."""
    with demo_app(runtime_settings, enabled=False) as client:
        response = client.get("/api/auth/options")

    assert response.status_code == 200
    assert response.json() == {"demo_session": False}


def test_advertising_the_demo_session_does_not_issue_one(demo: TestClient) -> None:
    """Saying a door exists is not opening it: the read sets no cookie and names no worker."""
    response = demo.get("/api/auth/options")

    assert cookies.SESSION_COOKIE not in response.cookies
    assert demo.get("/api/auth/me").status_code == 401
