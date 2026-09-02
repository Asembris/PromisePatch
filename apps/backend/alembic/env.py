"""Alembic environment.

Three things here are deliberate:

* **The URL comes from settings, never from ``alembic.ini``.** A connection string is a
  credential; keeping it in the environment is what makes the migration config committable.
* **The connection is async**, because the whole backend speaks asyncpg and a second sync
  driver would be a second set of type and pooling behaviours to reason about.
* **The schema is created before the version table is placed in it.** Alembic writes its
  version row into ``promisepatch``, which cannot happen until that schema exists, so the
  bootstrap statement runs first and is idempotent.
"""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from logging.config import fileConfig
from typing import Literal

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection

from promisepatch.config import Settings
from promisepatch.db.base import SCHEMA, metadata
from promisepatch.db.session import build_engine

# Importing the registry is what populates the metadata Alembic compares against.
import promisepatch.db.models  # noqa: F401  isort:skip

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata

# Mirrors alembic's own filter signature without importing from its private autogenerate API.
NameFilterType = Literal[
    "schema",
    "table",
    "column",
    "index",
    "unique_constraint",
    "foreign_key_constraint",
    "check_constraint",
]
ParentNames = MutableMapping[
    Literal["schema_name", "table_name", "schema_qualified_table_name"], str | None
]


def _database_url() -> str:
    return Settings().require_migration_database_url()


def _include_name(
    name: str | None,
    type_: NameFilterType,
    parent_names: ParentNames,
) -> bool:
    """Restrict reflection to our own schema.

    ``include_schemas`` without this filter would compare every schema in the database. On a
    managed host that means the provider's own schemas are reflected, found absent from our
    metadata, and proposed for deletion. PromisePatch owns exactly one schema and must never
    generate an operation against anything else.
    """
    if type_ == "schema":
        return name == SCHEMA
    return True


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    schema = getattr(obj, "schema", None)
    return schema in (None, SCHEMA)


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=_include_name,
        include_object=_include_object,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=False,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a database connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA,
        include_schemas=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    connection.commit()
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = build_engine(_database_url(), pool_size=1)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
