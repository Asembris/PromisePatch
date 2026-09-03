"""Backend test fixtures.

This directory is deliberately not a package: the engine suite already owns the top-level
``tests`` package name, and two packages with the same name under one pytest run resolve to
whichever lands on ``sys.path`` first. Files here are imported by path instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from starlette.testclient import TestClient

from promisepatch.config import Environment, Settings
from promisepatch.db import build_engine
from promisepatch.db.boundary import RUNTIME_ROLE
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

    Schema verification is schema work, so it uses the migration connection. When the
    least-privileged application role exists, the runtime tests will use that one instead and
    this fixture stays where it belongs: proving the shape, not exercising the app.
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


def runtime_url(admin_url: str, password: str) -> str:
    """The runtime role's connection, derived from the administrative one.

    Same host, same database, a different login: the least-privileged role is not a second
    deployment target, it is a second identity on the same one, so it needs a password rather
    than a URI of its own. A connection pooler qualifies the user with the project reference
    (``postgres.abcdef``); the tenant part is kept and only the role name is replaced.
    """
    url = make_url(admin_url)
    tenant = (url.username or "").partition(".")[2]
    login = f"{RUNTIME_ROLE}.{tenant}" if tenant else RUNTIME_ROLE
    return url.set(username=login, password=password).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def app_database_url(database_url: str) -> str:
    """The connection the application itself would use, if it were running."""
    settings = Settings()
    if settings.db_app_password is None:
        pytest.skip("PP_DB_APP_PASSWORD is not set; the runtime-role tests need it")
    return runtime_url(database_url, settings.require_db_app_password())


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
