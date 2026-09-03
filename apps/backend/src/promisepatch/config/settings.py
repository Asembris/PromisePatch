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

    database_url: SecretStr | None = None
    """The connection every request is served over: ``promisepatch_app``, and nothing more.

    Separate from :attr:`migration_database_url` on purpose rather than derived from it. The
    audited write boundary is only a control if the application cannot step over it, and an
    application holding the owner's credential could. Keeping the runtime connection a distinct
    variable means granting the API more privilege is an explicit act someone has to perform,
    not a side effect of how a URL was assembled.
    """

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

    session_secret: SecretStr | None = None
    """Key the ``pp_session`` cookie is signed with.

    Signing is what stops a browser handing us a session id it made up: the cookie carries an
    id and a MAC over it, and an id whose MAC does not verify is discarded before the database
    is asked about it. Rotating this value invalidates every outstanding cookie, which is the
    intended blunt instrument.
    """

    demo_worker_password: SecretStr | None = None
    """Password seeded for the demo baker login by ``pp reset-demo-state``."""

    demo_owner_password: SecretStr | None = None
    """Password seeded for the demo owner login by ``pp reset-demo-state``."""

    allow_fixture_reset: bool = False
    """Whether this deployment permits a fixture reset at all.

    Off by default, and deliberately not inferred from :attr:`env`. A reset deletes every
    domain row it owns; a process cannot work out from its own environment whether the database
    it is pointed at is the demo one, and guessing wrong destroys the wrong data. Turning this
    on is a statement by whoever configured the deployment, which is the only party that knows.
    """

    bakery_tz: str = "Africa/Tunis"
    """The bakery's local timezone.

    Read when an operator gives ``pp reset-demo-state`` a wall-clock anchor: "reset as if it is
    seven in the morning here" is the natural way to stage a demo, and it is a different instant
    depending on where "here" is. Every stored timestamp remains UTC.
    """

    @property
    def is_local(self) -> bool:
        return self.env is Environment.LOCAL

    def require_database_url(self) -> str:
        """The runtime connection string, or a precise failure naming what to configure."""
        if self.database_url is None:
            raise RuntimeError(
                "PP_DATABASE_URL is not configured; set it to a postgresql+asyncpg:// URI "
                "that logs in as promisepatch_app before serving requests."
            )
        return self.database_url.get_secret_value()

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

    def require_session_secret(self) -> str:
        """The cookie signing key, or a precise failure naming what to configure.

        There is deliberately no generated fallback. A key invented at boot would work
        perfectly on one process and silently log every user out of a second one, and a
        constant default would mean anyone holding this source could forge a session.
        """
        return _required(self.session_secret, "PP_SESSION_SECRET")

    def require_demo_worker_password(self) -> str:
        """The demo baker's password, or a precise failure naming what to configure."""
        return _required(self.demo_worker_password, "PP_DEMO_WORKER_PASSWORD")

    def require_demo_owner_password(self) -> str:
        """The demo owner's password, or a precise failure naming what to configure."""
        return _required(self.demo_owner_password, "PP_DEMO_OWNER_PASSWORD")

    @property
    def cors_origin_list(self) -> tuple[str, ...]:
        """``PP_CORS_ORIGINS`` as a comma-separated list.

        Deliberately a plain string on the model: pydantic-settings parses complex-typed
        fields as JSON, which would make the natural ``a,b`` form a startup error.
        """
        return tuple(origin.strip() for origin in self.cors_origins.split(",") if origin.strip())


def _required(value: SecretStr | None, name: str) -> str:
    """Unwrap a configured secret, or say exactly which variable is missing."""
    if value is None:
        raise RuntimeError(f"{name} is not configured; set it before seeding the demo logins.")
    return value.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Tests construct :class:`Settings` directly instead."""
    return Settings()
