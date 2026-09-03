"""Typed application settings, read from ``PP_``-prefixed environment variables.

Two rules keep this module honest as the system grows:

* **Only settings the code actually reads are declared.** A field here is a promise that
  something consumes it, and ``.env.example`` is asserted against this model in both
  directions, so a variable cannot drift into the example file or out of it unnoticed.
* **Nothing else reads the environment.** Modules take a :class:`Settings` instance; they do
  not reach for ``os.environ``. That is what makes the app configurable in tests without
  mutating global state.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Where this process is running. Controls exposure, not behaviour."""

    LOCAL = "local"
    AWS = "aws"


class Settings(BaseSettings):
    """The full configuration surface of the backend as it stands today."""

    model_config = SettingsConfigDict(
        env_prefix="PP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Environment = Environment.LOCAL
    log_level: str = "info"
    cors_origins: str = "http://localhost:5173"

    migration_database_url: SecretStr | None = None
    """Admin/DDL connection, used by Alembic and by schema tests. Never by request handlers.

    A :class:`~pydantic.SecretStr` so the credential cannot reach a log line, a traceback or a
    ``repr`` by accident. The runtime connection is a separate, least-privileged role, whose
    password is :attr:`db_app_password`.
    """

    db_app_password: SecretStr | None = None
    """Password for ``promisepatch_app``, the least-privileged runtime role.

    Read in exactly two places: the migration that creates the role, and the database tests
    that connect as it to prove what it cannot do. The role's connection string is derived from
    the administrative one -- same host, same database, different login -- so there is one
    credential here rather than a second URI to keep in step.
    """

    @property
    def is_local(self) -> bool:
        return self.env is Environment.LOCAL

    def require_migration_database_url(self) -> str:
        """The DDL connection string, or a precise failure naming what to configure."""
        if self.migration_database_url is None:
            raise RuntimeError(
                "PP_MIGRATION_DATABASE_URL is not configured; "
                "set it to a postgresql+asyncpg:// URI before running migrations."
            )
        return self.migration_database_url.get_secret_value()

    def require_db_app_password(self) -> str:
        """The runtime role's password, or a precise failure naming what to configure."""
        if self.db_app_password is None:
            raise RuntimeError(
                "PP_DB_APP_PASSWORD is not configured; "
                "set it before creating or connecting as the promisepatch_app role."
            )
        return self.db_app_password.get_secret_value()

    @property
    def cors_origin_list(self) -> tuple[str, ...]:
        """``PP_CORS_ORIGINS`` as a comma-separated list.

        Deliberately a plain string on the model: pydantic-settings parses complex-typed
        fields as JSON, which would make the natural ``a,b`` form a startup error.
        """
        return tuple(origin.strip() for origin in self.cors_origins.split(",") if origin.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Tests construct :class:`Settings` directly instead."""
    return Settings()
