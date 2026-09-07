"""Where a destructive test is allowed to point, decided before it can connect.

The backend suite truncates. ``reset_demo_state`` empties every table PromisePatch owns, the
intake fixtures delete the workflow tables outright, and the round-trip suite reloads the
fixture at several anchors in one session. That is correct against a disposable local database
and catastrophic against any other, so the question "which database is this?" has to be
answered before a connection exists rather than after a statement has run.

**Why the existing opt-in is not enough.** ``PP_ALLOW_FIXTURE_RESET`` says that *a* reset is
permitted; it says nothing about *where*. It is deliberately a setting rather than a hostname
check, because ``pp reset-demo-state`` is an operator action against a demo deployment and a
process genuinely cannot work out from its own hostname whether it is the demo one. That
reasoning is sound for the operator command and wrong for the test suite: a suite has no
legitimate remote target at all. So the flag keeps its production meaning and this module adds
the second, narrower condition that only tests are held to.

**The guard hands back the URL.** Nothing here returns a boolean for a caller to remember to
check. A test module cannot build an engine without a connection string, and the only place it
gets one is :func:`migration_database_url` or :func:`runtime_database_url` -- so the check is
not a step that precedes the destructive work, it is the thing the destructive work is made
out of. ``test_database_safety`` asserts against the source of the suite that no destructive
module reaches around it.

**Unknown fails closed.** A URL with a host nobody recognised, no host at all, or one that does
not parse is refused. The allowlist is the four addresses this repository actually serves a
test database on and nothing else: no cloud provider, no ``*.supabase.com``, and no blanket
private-range rule, because "it is a private address" is not the same claim as "it is this
machine's throwaway container".
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from promisepatch.config import Settings

LOCAL_TEST_HOSTS: Final[frozenset[str]] = frozenset(
    {
        # The host tooling's address for the published container port, and the form
        # `docker/env/host.env` is generated with.
        "127.0.0.1",
        # The same machine by name, which is what CI's disposable PostgreSQL and a locally
        # installed one are both reached as.
        "localhost",
        # The loopback address again, for a host resolving it over IPv6.
        "::1",
        # The compose service name. Inside the stack's own network `migrate` and `seed` reach
        # the database this way, so a test run from inside a container is a supported path.
        "postgres",
    }
)
"""Every host a PromisePatch test may destroy data on. Deliberately short, deliberately literal."""

MIGRATION_URL_VARIABLE: Final = "PP_MIGRATION_DATABASE_URL"
RUNTIME_URL_VARIABLE: Final = "PP_DATABASE_URL"


class UnsafeTestDatabaseError(RuntimeError):
    """Raised when the suite's configured database is not one it may write to.

    A hard error rather than a skip. A skip would be safe and silent, and silence is how a
    developer ends up believing the integration suite ran when it did not.
    """


def local_test_database_url(url: str, *, variable: str) -> str:
    """Return ``url`` unchanged if it names a local test database; refuse otherwise.

    The host is parsed structurally with SQLAlchemy's own URL parser rather than matched as a
    substring: ``"localhost" in url`` is satisfied by
    ``postgresql://user@localhost.attacker.example/db`` and by a password that happens to
    contain the word, and neither is this machine.

    The message names the variable and the host. It never contains ``url``, which carries a
    password -- the same rule the runtime connection already follows.
    """
    try:
        host = make_url(url).host
    except ArgumentError as error:
        raise UnsafeTestDatabaseError(
            f"{variable} is not a database URL this suite can parse, so it cannot be shown to "
            f"be local; refusing to run destructive tests against it."
        ) from error

    if not host:
        raise UnsafeTestDatabaseError(
            f"{variable} names no host, so it cannot be shown to be a local test database; "
            f"refusing to run destructive tests against it."
        )

    if host.lower() not in LOCAL_TEST_HOSTS:
        raise UnsafeTestDatabaseError(
            f"{variable} points at {host!r}, which is not a local test database. The backend "
            f"suite truncates every table PromisePatch owns, so it runs only against "
            f"{sorted(LOCAL_TEST_HOSTS)}. PP_ALLOW_FIXTURE_RESET does not authorise this: it "
            f"says a reset is permitted, not that this is the database to permit it on. Point "
            f"the suite at the local stack with "
            f"`uv run python scripts/with_local_env.py -- uv run pytest apps/backend`."
        )

    return url


def migration_database_url(settings: Settings) -> str:
    """The administrative connection the suite may migrate and truncate through."""
    return local_test_database_url(
        settings.require_migration_database_url(), variable=MIGRATION_URL_VARIABLE
    )


def runtime_database_url(settings: Settings) -> str:
    """The least-privileged connection the suite serves requests over."""
    return local_test_database_url(settings.require_database_url(), variable=RUNTIME_URL_VARIABLE)
