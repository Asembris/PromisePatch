"""The connection the API serves requests over, and the privilege it does not hold.

Two questions are asked here and they are not the same. *Who are we* is answered by the
server, because a URL states an intention and a pooler may rewrite it. *What may we do* is
answered by provoking the refusals, because a privilege matrix is a claim about behaviour and
behaviour is what a test should read.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.config import Settings
from promisepatch.db import RuntimeDatabase
from promisepatch.db.boundary import RUNTIME_ROLE
from promisepatch.db.runtime import RuntimeRoleError, login_role
from promisepatch.db.session import POOLER_SAFE_CONNECT_ARGS

INSUFFICIENT_PRIVILEGE = "42501"


def sqlstate(error: DBAPIError) -> str:
    return str(getattr(error.orig, "sqlstate", ""))


# ------------------------------------------------------------------- configuration, no server


def test_the_login_role_ignores_a_pooler_tenant_suffix() -> None:
    """A pooled endpoint appends the project reference; the role is what precedes it."""
    pooled = "postgresql+asyncpg://promisepatch_app.abcdefghij:pw@pooler.example:5432/postgres"
    direct = "postgresql+asyncpg://promisepatch_app:pw@db.example:5432/postgres"
    assert login_role(pooled) == RUNTIME_ROLE
    assert login_role(direct) == RUNTIME_ROLE


def test_an_administrative_url_is_refused_as_the_runtime_connection() -> None:
    """Pointing the API at the owner would silently retire the whole write boundary."""
    settings = Settings(
        database_url="postgresql+asyncpg://postgres.abcdefghij:pw@pooler.example:5432/postgres"
    )
    with pytest.raises(RuntimeRoleError, match=RUNTIME_ROLE):
        RuntimeDatabase.from_settings(settings)


def test_a_missing_runtime_url_names_the_variable_to_set() -> None:
    with pytest.raises(RuntimeError, match="PP_DATABASE_URL"):
        Settings(database_url=None).require_database_url()


def test_the_runtime_url_does_not_leak_through_a_repr() -> None:
    """A connection string is a credential, and a repr is one traceback away from a log."""
    secret = "postgresql+asyncpg://promisepatch_app:hunter2@pooler.example:5432/postgres"
    settings = Settings(database_url=secret)
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings.database_url)


def test_a_runtime_error_names_the_variable_and_never_the_url() -> None:
    url = "postgresql+asyncpg://postgres.abcdefghij:hunter2@pooler.example:5432/postgres"
    with pytest.raises(RuntimeRoleError) as raised:
        RuntimeDatabase.from_settings(Settings(database_url=url))
    message = str(raised.value)
    assert "PP_DATABASE_URL" in message
    assert "hunter2" not in message
    assert "pooler.example" not in message


def test_the_runtime_engine_is_pooler_safe() -> None:
    """A cached prepared statement is bound to a server connection a pooler may swap."""
    assert POOLER_SAFE_CONNECT_ARGS["prepared_statement_cache_size"] == 0

    settings = Settings(
        database_url="postgresql+asyncpg://promisepatch_app:pw@pooler.example:5432/postgres"
    )
    database = RuntimeDatabase.from_settings(settings)
    assert database.engine.dialect.name == "postgresql"
    assert database.engine.url.username == RUNTIME_ROLE


# --------------------------------------------------------------------------------- the server


@pytest.mark.integration
async def test_the_runtime_connection_authenticates_as_the_runtime_role(
    database: RuntimeDatabase,
) -> None:
    """The whole least-privilege argument rests on this one fact being true in production."""
    async with database.connect() as connection:
        assert await database.current_user(connection) == RUNTIME_ROLE


@pytest.mark.integration
async def test_the_runtime_connection_is_not_the_migration_connection() -> None:
    """Two credentials, two identities. A deployment that collapsed them would pass every
    other test in this file and hold no boundary at all."""
    settings = Settings()
    if settings.migration_database_url is None:
        pytest.skip("PP_MIGRATION_DATABASE_URL is not set")
    assert settings.require_database_url() != settings.require_migration_database_url()
    assert login_role(settings.require_migration_database_url()) != RUNTIME_ROLE


@pytest.mark.integration
async def test_the_runtime_connection_can_read_the_schema_revision(
    database: RuntimeDatabase,
) -> None:
    async with database.connect() as connection:
        revision = await connection.scalar(
            text("select version_num from promisepatch.alembic_version")
        )
    assert revision


@pytest.mark.integration
async def test_the_runtime_connection_cannot_rewrite_an_append_only_ledger(
    app_conn: AsyncConnection,
) -> None:
    with pytest.raises(DBAPIError) as raised:
        await app_conn.exec_driver_sql("update promisepatch.inventory_ledger set delta = 0")
    assert sqlstate(raised.value) == INSUFFICIENT_PRIVILEGE


@pytest.mark.integration
async def test_the_runtime_connection_cannot_perform_migration_level_operations(
    app_conn: AsyncConnection,
) -> None:
    """Schema change, trigger control and truncation are all out of reach."""
    for statement in (
        "create table promisepatch.smuggled (id int)",
        "drop table promisepatch.promises",
        "alter table promisepatch.promises disable trigger trg_10_governed_write",
        "truncate promisepatch.promises",
    ):
        savepoint = await app_conn.begin_nested()
        with pytest.raises(DBAPIError) as raised:
            await app_conn.exec_driver_sql(statement)
        await savepoint.rollback()
        assert sqlstate(raised.value) == INSUFFICIENT_PRIVILEGE, statement


@pytest.mark.integration
async def test_the_runtime_role_cannot_widen_its_own_privileges(
    app_conn: AsyncConnection,
) -> None:
    """A self-grant is not an error in PostgreSQL -- it is a warning and a no-op.

    Asserted by effect rather than by exception for exactly that reason: a test that expected
    a refusal here would pass while proving nothing, because the statement always "succeeds".
    What matters is that the privilege afterwards is the one the migration granted.
    """
    await app_conn.exec_driver_sql("grant truncate on promisepatch.promises to promisepatch_app")
    widened = await app_conn.scalar(
        text("select has_table_privilege(:role, 'promisepatch.promises', 'TRUNCATE')"),
        {"role": RUNTIME_ROLE},
    )
    assert not widened


@pytest.mark.integration
async def test_the_runtime_connection_cannot_write_a_governed_table_unaudited(
    app_conn: AsyncConnection,
) -> None:
    with pytest.raises(DBAPIError) as raised:
        await app_conn.exec_driver_sql(
            "insert into promisepatch.resources (id, kind, name, unit)"
            " values ('smuggled', 'INGREDIENT', 'smuggled', 'kg')"
        )
    assert sqlstate(raised.value) == INSUFFICIENT_PRIVILEGE


@pytest.mark.integration
async def test_disposal_is_idempotent(database: RuntimeDatabase) -> None:
    """Shutdown may run twice under a reloader; the second one must not be an error."""
    await database.dispose()
    await database.dispose()
