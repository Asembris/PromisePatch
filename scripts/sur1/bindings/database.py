"""Which database a scored run installs its world into, and reads its evidence out of.

There is one answer and this module is where it is computed. It exists because there used to be
two: the receivers resolved theirs from ``SUR1_DATABASE_URL`` and the governed fixture load went
and found its own, inside the write itself, from ``promisepatch.config.get_settings()`` -- which
falls back to the repository's ``.env``. A run started without the local environment loaded named
a hosted database in one and the local one in the other, and every reading it produced would have
been about a world that was never installed. See ``docs/sur1-corrected-scored-run-refusal.md``.

**One target, two credentials, and that is not a contradiction.** The fixture load is a
``TRUNCATE`` across forty-two tables inside one governed transaction, so it connects as the
migration role; the receivers only read, so they connect as the least-privileged application
role. Two roles on one database are the same database and two databases behind one role are not,
which is why what is compared here is the *identity* of the server and the database on it --
host, port, database name, and the backend the driver speaks -- and never a credential.

**Nothing here opens a connection.** Every function in this module parses strings and reads
settings. That is what lets :func:`~scripts.sur1.preflight.database_identity` refuse a mismatched
run *before* authorisation, before a run directory exists and before anything is dialled --
rather than at the first write, which is where the refusal used to land.

**A fault is carried, never raised, at resolution time.** :func:`installer_target` is called while
the bindings are being assembled, and that assembly reaches nothing and refuses nothing: the
preflight is what says whether a run could be taken. So a migration URL that is not configured at
all comes back as an :class:`InstallerTarget` carrying the reason, and the preflight reports it
like any other failed question.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urlsplit

POSTGRES_BACKENDS: Final = frozenset({"postgres", "postgresql"})
"""The backends this product speaks. Anything else is refused rather than compared."""

CANONICAL_BACKEND: Final = "postgresql"
"""What ``postgres`` and ``postgresql`` are both normalised to, so two spellings agree."""

DEFAULT_PORT: Final = 5432
"""PostgreSQL's own default, applied when a URL omits the port.

``...@127.0.0.1/promisepatch`` and ``...@127.0.0.1:5432/promisepatch`` are the same server, and a
comparison that called them different would refuse a correct run.
"""

INSTALLER_SOURCE: Final = "promisepatch settings (PP_MIGRATION_DATABASE_URL)"
"""Where the installer's connection comes from, named so a capture can say it.

Deliberately *not* a ``SUR1_`` variable of its own. An override here would be a way to make
:func:`~scripts.sur1.preflight.database_identity` agree while every other product setting the
fixture load reads -- the demo staff passwords it seeds, the reset permission it checks -- still
came from a different file. The one supported way to point this harness at the local stack is to
load the local environment, which moves all of them together.
"""

RECEIVER_SOURCE: Final = "SUR1_DATABASE_URL"
"""Where the receivers' connection comes from. The scored configuration, and nothing else."""


class DatabaseIdentityError(RuntimeError):
    """A connection string does not name a database this harness can recognise."""


@dataclass(frozen=True, slots=True)
class DatabaseIdentity:
    """One server and one database on it. Never a role, never a password.

    ``driver`` is the DBAPI the URL names -- ``asyncpg`` for the fixture load, nothing at all for
    the receivers, which hand a bare ``postgresql://`` DSN to ``asyncpg`` directly. It is recorded
    because a capture reading *which driver* is useful, and it is excluded from equality because
    the two ends legitimately differ: what has to match is the backend, which is compared.
    """

    backend: str
    host: str
    port: int
    database: str
    driver: str = field(default="", compare=False)

    def __str__(self) -> str:
        return f"{self.backend}://{self.host}:{self.port}/{self.database}"

    def describes(self) -> dict[str, object]:
        """A payload a committed capture may carry. Holds no credential by construction."""
        return {
            "backend": self.backend,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "driver": self.driver,
        }


def identity_of(url: str, *, what: str = "a database URL") -> DatabaseIdentity:
    """The server and database one connection string names, or a refusal saying why not.

    Malformed and unrecognised both refuse. A URL this function could not read is not a URL whose
    target can be compared with another, and *unknown* is the one answer a gate may not treat as
    agreement.
    """
    if not url or not url.strip():
        raise DatabaseIdentityError(f"{what} is not configured")
    try:
        parsed = urlsplit(url.strip())
    except ValueError as failure:
        raise DatabaseIdentityError(f"{what} could not be parsed: {failure}") from failure
    scheme = parsed.scheme.lower()
    if not scheme:
        raise DatabaseIdentityError(f"{what} names no scheme, so it names no database")
    backend, _, driver = scheme.partition("+")
    if backend not in POSTGRES_BACKENDS:
        raise DatabaseIdentityError(
            f"{what} names the {backend!r} backend; this harness speaks "
            f"{sorted(POSTGRES_BACKENDS)} and will not guess at another"
        )
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as failure:
        raise DatabaseIdentityError(f"{what} names no readable port: {failure}") from failure
    if not host:
        raise DatabaseIdentityError(f"{what} names no host")
    database = parsed.path.lstrip("/")
    if not database or "/" in database:
        raise DatabaseIdentityError(f"{what} names no single database ({parsed.path!r})")
    return DatabaseIdentity(
        backend=CANONICAL_BACKEND,
        host=host.lower(),
        port=port or DEFAULT_PORT,
        database=database,
        driver=driver,
    )


@dataclass(frozen=True, slots=True)
class InstallerTarget:
    """The connection the governed fixture load will use, resolved once and handed down.

    Handed to :class:`~scripts.sur1.bindings.setup.WorldHandles` and from there to the installer,
    so the write itself resolves nothing. That is the whole correction: the value the preflight
    checked is by construction the value the load uses, rather than a second lookup taken minutes
    later against whatever the working directory happened to hold.
    """

    url: str = ""
    source: str = INSTALLER_SOURCE
    fault: str = ""
    """Why nothing could be resolved, when nothing could. Carried rather than raised."""

    def identity(self) -> DatabaseIdentity:
        if self.fault:
            raise DatabaseIdentityError(self.fault)
        return identity_of(self.url, what="the fixture load's database URL")


def installer_target() -> InstallerTarget:
    """Resolve the fixture load's connection, here and nowhere else.

    It is the product's own migration setting because the load is the owner's transaction and no
    other credential can take it. What makes that safe is not the credential but the gate: the
    identity it resolves to is compared with the scored target before a run is authorised, so a
    settings file naming somewhere else refuses the run rather than writing to it.
    """
    try:
        from promisepatch.config import get_settings

        url = get_settings().require_migration_database_url()
    except Exception as failure:
        return InstallerTarget(fault=f"{type(failure).__name__}: {failure}")
    return InstallerTarget(url=url)


def receiver_identity(url: str) -> DatabaseIdentity:
    """The database the receivers read, from the scored configuration's own variable."""
    return identity_of(url, what=f"the receivers' database URL ({RECEIVER_SOURCE})")


def disagreement(installer: DatabaseIdentity, receiver: DatabaseIdentity) -> str:
    """The sentence naming a split target, or empty when both name one database.

    The sentence says what each end would have done, because the failure it describes is not
    *a setting is wrong* but *the readings would have been about a world that was never
    installed*, and only the second explains why this refuses rather than warns.
    """
    if installer == receiver:
        return ""
    return (
        f"the fixture load would install into {installer} and the receivers would read "
        f"{receiver}; a world installed into one database and read out of another produces "
        "readings about a world that was never installed. Load the local environment "
        "(scripts/with_local_env.py) so both name the same database."
    )


__all__ = [
    "CANONICAL_BACKEND",
    "DEFAULT_PORT",
    "INSTALLER_SOURCE",
    "POSTGRES_BACKENDS",
    "RECEIVER_SOURCE",
    "DatabaseIdentity",
    "DatabaseIdentityError",
    "InstallerTarget",
    "disagreement",
    "identity_of",
    "installer_target",
    "receiver_identity",
]
