"""Backend test fixtures.

This directory is deliberately not a package: the engine suite already owns the top-level
``tests`` package name, and two packages with the same name under one pytest run resolve to
whichever lands on ``sys.path`` first. Files here are imported by path instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from starlette.testclient import TestClient

from promisepatch.api.routers import auth as login_router
from promisepatch.config import Environment, Settings
from promisepatch.db import RuntimeDatabase, build_engine
from promisepatch.db.uow import Actor
from promisepatch.fixtures import demo
from promisepatch.fixtures.reset import reset_demo_state
from promisepatch.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Explicit settings, never inherited from the developer's environment."""
    return Settings(env=Environment.LOCAL, log_level="info", cors_origins="http://localhost:5173")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def database_url() -> str:
    """The administrative connection the schema tests run against.

    Schema verification is schema work, so it uses the migration connection. Anything that
    exercises the application uses ``app_database_url`` instead, which is the credential a
    request would really arrive on.
    """
    settings = Settings()
    if settings.migration_database_url is None:
        pytest.skip(
            "PP_MIGRATION_DATABASE_URL is not set; the schema integration tests need a database"
        )
    return settings.require_migration_database_url()


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    created = build_engine(database_url, pool_size=1)
    try:
        yield created
    finally:
        await created.dispose()


@pytest_asyncio.fixture
async def conn(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection whose transaction is always rolled back.

    Nothing these tests write survives them, which is what makes it safe to point the suite at
    a real database. Each test provokes at most one violation: a failed statement aborts its
    transaction, so a second assertion in the same one could not run.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest.fixture(scope="session")
def app_database_url() -> str:
    """The connection the application itself uses, exactly as configured.

    Read from ``PP_DATABASE_URL`` rather than derived, because the thing under test is the
    credential the running API would actually present. A derived URL would prove the role can
    do what we expect and say nothing about whether the deployment points at that role.
    """
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("PP_DATABASE_URL is not set; the runtime-connection tests need it")
    return settings.require_database_url()


@pytest_asyncio.fixture
async def app_engine(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    created = build_engine(app_database_url, pool_size=1)
    try:
        yield created
    finally:
        await created.dispose()


@pytest_asyncio.fixture
async def app_conn(app_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A rolled-back transaction held by ``promisepatch_app``, not by the migration role.

    What the application may do is a question about privileges as well as triggers, and only a
    connection that actually holds those privileges can answer it.
    """
    async with app_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest_asyncio.fixture
async def database(app_database_url: str) -> AsyncIterator[RuntimeDatabase]:
    """The application's own database handle, disposed with the test that asked for it."""
    settings = Settings()
    created = RuntimeDatabase.from_settings(settings)
    try:
        yield created
    finally:
        await created.dispose()


# --------------------------------------------------------------- a database with the demo in it


DEMO_ANCHOR = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
"""A fixed anchor, so every offset in the fixture lands on the same instant on every run.

The wall clock would make the seeded graph -- and its digest -- different each time, which is
exactly the property that would stop the round-trip and ordering assertions from meaning
anything.
"""


@dataclass(frozen=True, slots=True)
class DemoState:
    """What the seeded database contains, for tests that assert against known rows."""

    anchor: datetime
    digest: str


@pytest.fixture(scope="session")
def demo_state() -> DemoState:
    """Load the demo fixture once per test session, through the privileged operator path.

    Synchronous on purpose: it drives its own event loop, so it does not have to agree with
    pytest-asyncio's per-function loop scope and can stay session-scoped -- one reset for the
    whole suite rather than one per test over a pooled connection.

    The reset runs as the migration role because that is the only identity that may truncate.
    The runtime role deliberately cannot, which is why there is no HTTP reset endpoint.
    """
    settings = Settings()
    if settings.migration_database_url is None:
        pytest.skip("PP_MIGRATION_DATABASE_URL is not set; the demo-state tests need a database")
    if settings.demo_worker_password is None or settings.demo_owner_password is None:
        pytest.skip("PP_DEMO_WORKER_PASSWORD / PP_DEMO_OWNER_PASSWORD are not set")
    if not settings.allow_fixture_reset:
        pytest.skip("PP_ALLOW_FIXTURE_RESET is not true; refusing to reset this database")

    async def seed() -> DemoState:
        engine = build_engine(settings.require_migration_database_url(), pool_size=1)
        try:
            async with engine.begin() as connection:
                outcome = await reset_demo_state(
                    connection,
                    anchor=DEMO_ANCHOR,
                    now=DEMO_ANCHOR,
                    passwords={
                        demo.BAKER_ROLE: settings.require_demo_worker_password(),
                        demo.OWNER_ROLE: settings.require_demo_owner_password(),
                    },
                    actor=Actor(kind="SYSTEM", id="backend-test-suite"),
                )
            return DemoState(anchor=outcome.anchor, digest=outcome.digest)
        finally:
            await engine.dispose()

    return asyncio.run(seed())


@pytest.fixture
def runtime_settings() -> Settings:
    """Settings as the running API would read them, skipping if the runtime path is unset."""
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("PP_DATABASE_URL is not set; the API integration tests need it")
    if settings.session_secret is None:
        pytest.skip("PP_SESSION_SECRET is not set; the API integration tests need it")
    return settings


@pytest.fixture
def api(runtime_settings: Settings, demo_state: DemoState) -> Iterator[TestClient]:
    """A client for the real application: runtime connection, seeded database, no fakes."""
    login_router._limiter.reset()
    with TestClient(create_app(runtime_settings)) as test_client:
        yield test_client
