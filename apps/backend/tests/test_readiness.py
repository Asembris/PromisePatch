"""Liveness and readiness.

The distinction is the point of these tests. ``/healthz`` must answer without a database, so
an unrelated outage cannot get a healthy task restarted. ``/readyz`` must refuse when the
things the process genuinely needs are not there -- and must say which one, without quoting a
credential or a driver message on an endpoint that requires no authentication.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete
from starlette.testclient import TestClient

from promisepatch import __version__
from promisepatch.api.routers.health import migration_readiness, read_fixture
from promisepatch.config import Settings
from promisepatch.db import HEAD_REVISION, RuntimeDatabase
from promisepatch.db.boundary import RUNTIME_ROLE
from promisepatch.db.models import FixtureState
from promisepatch.main import create_app

UNREACHABLE_URL = "postgresql+asyncpg://promisepatch_app:hunter2@no-such-host.invalid:5432/postgres"


def app_with(**overrides: object) -> TestClient:
    """A client for an application configured exactly as named.

    Constructed rather than copied: ``model_copy`` skips validation, so a URL passed that way
    stays a plain string and never becomes the :class:`~pydantic.SecretStr` the code expects.
    """
    return TestClient(create_app(Settings(**overrides)))  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------ liveness


def test_healthz_answers_without_a_database() -> None:
    """Configured with no database at all, which is the whole point of the endpoint."""
    with app_with(database_url=None) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "api"
    assert body["version"] == __version__


def test_healthz_needs_no_session(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


# ----------------------------------------------------------------------------------- readiness


def test_readyz_is_not_ready_without_a_database() -> None:
    """No connection configured is a real deployment mistake, and it reports as one."""
    with app_with(database_url=None) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["database"] == {
        "configured": False,
        "reachable": False,
        "current_user": None,
        "expected_user": RUNTIME_ROLE,
        "detail": "PP_DATABASE_URL is not configured",
    }
    assert body["migrations"]["at_head"] is False
    assert body["fixture"]["readable"] is False


def test_readyz_needs_no_session(client: TestClient) -> None:
    """A probe that required a login could not tell a load balancer anything useful."""
    assert client.get("/readyz").status_code in {200, 503}


def test_an_unreachable_database_is_not_ready_and_leaks_nothing() -> None:
    """Pointed at a host that does not exist, so the driver's own error is the thing at risk.

    A connection failure commonly quotes the host, the login and sometimes the whole DSN. The
    body must carry one fixed sentence instead, on an endpoint anyone can call.
    """
    with app_with(database_url=UNREACHABLE_URL) as broken:
        response = broken.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["database"]["configured"] is True
    assert body["database"]["reachable"] is False
    assert body["database"]["detail"] == (
        "the database could not be reached over the runtime connection"
    )
    assert "hunter2" not in response.text
    assert "no-such-host" not in response.text
    assert "Traceback" not in response.text
    assert "asyncpg" not in response.text


@pytest.mark.integration
def test_readyz_is_ready_on_the_runtime_connection_at_head(api: TestClient) -> None:
    response = api.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == {
        "configured": True,
        "reachable": True,
        "current_user": RUNTIME_ROLE,
        "expected_user": RUNTIME_ROLE,
        "detail": None,
    }
    assert body["migrations"] == {
        "at_head": True,
        "expected_revision": HEAD_REVISION,
        "actual_revision": HEAD_REVISION,
        "detail": None,
    }


@pytest.mark.integration
def test_readyz_reports_the_loaded_fixture(api: TestClient) -> None:
    """The fixture is evidence, not a gate: it is reported and readiness still passes."""
    body = api.get("/readyz").json()

    assert body["fixture"]["readable"] is True
    assert body["fixture"]["present"] is True
    assert body["fixture"]["fixture_name"] == "hollow-oak"
    assert body["fixture"]["digest"]
    assert body["status"] == "ready"


@pytest.mark.integration
def test_a_revision_mismatch_is_not_ready(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Code ahead of migrations is the failure readiness exists to catch."""
    monkeypatch.setattr(
        "promisepatch.api.routers.health.HEAD_REVISION", "9999_a_migration_that_never_ran"
    )

    response = api.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["migrations"]["at_head"] is False
    assert body["migrations"]["expected_revision"] == "9999_a_migration_that_never_ran"
    assert body["migrations"]["actual_revision"] == HEAD_REVISION
    assert body["database"]["reachable"] is True


@pytest.mark.integration
async def test_an_absent_fixture_reads_as_absent_not_as_a_failure(
    database: RuntimeDatabase, demo_state: object
) -> None:
    """A migrated database nobody has seeded yet is a healthy state, not a broken one.

    Exercised against a genuinely empty table -- the row is deleted inside a transaction that
    is then rolled back, so the real query answers the real absent case without disturbing the
    demo the rest of the suite reads.
    """
    async with database.engine.connect() as connection:
        transaction = await connection.begin()
        try:
            seeded = await read_fixture(connection)
            await connection.execute(delete(FixtureState))
            absent = await read_fixture(connection)
        finally:
            await transaction.rollback()

    assert seeded.present is True
    assert seeded.fixture_name == "hollow-oak"
    assert seeded.digest

    assert absent.readable is True
    assert absent.present is False
    assert absent.fixture_name is None
    assert absent.anchor_at is None
    assert absent.digest is None
    assert absent.detail == "no fixture is loaded"


def test_readiness_does_not_depend_on_a_fixture_being_present() -> None:
    """The verdict is a function of the database and the schema, and of nothing else.

    Stated as a property of the readiness rule rather than of one response: an absent fixture
    contributes nothing to the decision, so a fresh deployment reports ready.
    """
    assert migration_readiness(HEAD_REVISION).at_head
    assert not migration_readiness("0001_baseline").at_head
    assert not migration_readiness(None).at_head
