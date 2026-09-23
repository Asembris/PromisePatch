"""The interlock that decides which database the suite may destroy data on.

These tests need no database of their own. That is the point: the property under test is that
a refusal happens *before* a connection is opened, so proving it must not require one.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from _database_safety import (
    LOCAL_TEST_HOSTS,
    UnsafeTestDatabaseError,
    local_test_database_url,
    migration_database_url,
    runtime_database_url,
)

from promisepatch.config import Settings

TESTS = Path(__file__).resolve().parent
REPOSITORY = TESTS.parents[2]

HOSTED = (
    "postgresql+asyncpg://postgres.pwhkabc:s3cr3t-p4ssw0rd"
    "@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
)
LOOPBACK = "postgresql+asyncpg://postgres:pw@127.0.0.1:55432/promisepatch"
LOCALHOST = "postgresql+asyncpg://postgres:pw@localhost:5432/promisepatch"
IPV6_LOOPBACK = "postgresql+asyncpg://postgres:pw@[::1]:5432/promisepatch"
COMPOSE_SERVICE = "postgresql+asyncpg://postgres:pw@postgres:5432/promisepatch"


def hosted_settings() -> Settings:
    """A developer's ``.env`` exactly as it goes wrong: hosted, and opted into resets."""
    return Settings(
        migration_database_url=HOSTED,
        database_url=HOSTED,
        allow_fixture_reset=True,
        demo_worker_password="irrelevant",
        demo_owner_password="irrelevant",
    )


# --------------------------------------------------------------------- what is accepted


@pytest.mark.parametrize(
    "url",
    [
        pytest.param(LOOPBACK, id="127.0.0.1"),
        pytest.param(LOCALHOST, id="localhost"),
        pytest.param(IPV6_LOOPBACK, id="::1"),
        pytest.param(COMPOSE_SERVICE, id="compose-service"),
    ],
)
def test_a_local_test_database_is_accepted_and_handed_back_unchanged(url: str) -> None:
    """The four addresses this repository actually serves a test database on.

    Returned rather than merely approved: the caller builds its engine from what comes back,
    which is what stops the check being a step somebody can forget.
    """
    assert local_test_database_url(url, variable="PP_MIGRATION_DATABASE_URL") == url


def test_the_allowlist_is_only_the_hosts_this_repository_serves() -> None:
    """Written down so that widening it is an edit somebody has to justify."""
    assert frozenset({"127.0.0.1", "localhost", "::1", "postgres"}) == LOCAL_TEST_HOSTS


# --------------------------------------------------------------------- what is refused


def test_a_hosted_database_is_refused_even_though_resets_are_enabled() -> None:
    """The whole reason this module exists.

    ``PP_ALLOW_FIXTURE_RESET=true`` and a hosted URL can coexist in one ``.env``, and the flag
    says a reset is permitted rather than that this is the database to permit it on.
    """
    settings = hosted_settings()
    assert settings.allow_fixture_reset is True

    with pytest.raises(UnsafeTestDatabaseError, match=re.escape("pooler.supabase.com")):
        migration_database_url(settings)
    with pytest.raises(UnsafeTestDatabaseError, match=re.escape("pooler.supabase.com")):
        runtime_database_url(settings)


def test_the_refusal_says_the_reset_flag_did_not_authorise_it() -> None:
    """A developer who set the flag deserves to be told why it was not enough."""
    with pytest.raises(UnsafeTestDatabaseError) as refused:
        migration_database_url(hosted_settings())
    assert "PP_ALLOW_FIXTURE_RESET does not authorise this" in str(refused.value)


@pytest.mark.parametrize(
    "url",
    [
        pytest.param(
            "postgresql+asyncpg://u:pw@promisepatch.abc123.eu-west-1.rds.amazonaws.com/db",
            id="aws-rds",
        ),
        pytest.param("postgresql+asyncpg://u:pw@10.0.0.7:5432/promisepatch", id="rfc1918-10"),
        pytest.param("postgresql+asyncpg://u:pw@192.168.1.20:5432/promisepatch", id="rfc1918-192"),
        pytest.param("postgresql+asyncpg://u:pw@db.internal:5432/promisepatch", id="unknown-name"),
    ],
)
def test_an_unrecognised_host_fails_closed(url: str) -> None:
    """Unknown is refused, not investigated.

    A private address is not the same claim as "this machine's throwaway container", so no
    RFC1918 range is waved through for convenience.
    """
    with pytest.raises(UnsafeTestDatabaseError):
        local_test_database_url(url, variable="PP_MIGRATION_DATABASE_URL")


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("postgresql+asyncpg://u:pw@localhost.attacker.example/db", id="suffix"),
        pytest.param("postgresql+asyncpg://u:pw@notlocalhost/db", id="prefix"),
        pytest.param("postgresql+asyncpg://u:localhost@db.example.com/db", id="in-the-password"),
    ],
)
def test_a_host_that_merely_contains_a_local_name_is_refused(url: str) -> None:
    """Why the check parses the URL instead of asking whether ``"localhost" in url``.

    Every one of these satisfies a substring test and none of them is this machine.
    """
    with pytest.raises(UnsafeTestDatabaseError):
        local_test_database_url(url, variable="PP_MIGRATION_DATABASE_URL")


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("postgresql+asyncpg:///promisepatch", id="no-host"),
        pytest.param("not a database url at all", id="unparseable"),
        pytest.param("", id="empty"),
    ],
)
def test_a_url_that_cannot_be_shown_to_be_local_fails_closed(url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        local_test_database_url(url, variable="PP_MIGRATION_DATABASE_URL")


def test_a_refusal_names_the_variable_and_never_the_password() -> None:
    """The refusal is going into a CI log; the URL it refused carries a credential."""
    with pytest.raises(UnsafeTestDatabaseError) as refused:
        migration_database_url(hosted_settings())
    message = str(refused.value)
    assert "PP_MIGRATION_DATABASE_URL" in message
    assert "s3cr3t-p4ssw0rd" not in message
    assert HOSTED not in message


# --------------------------------------------------- refusal happens before any database work


def test_no_engine_is_built_when_the_target_is_not_local() -> None:
    """The ordering property, demonstrated in the shape every call site uses.

    ``build_engine(migration_database_url(settings), ...)`` evaluates its argument first, so a
    refusal raises before the engine exists -- and with no engine there is no connection, and
    with no connection there is no ``TRUNCATE``.
    """
    built: list[str] = []

    def build_engine(url: str, **_: Any) -> None:
        built.append(url)

    with pytest.raises(UnsafeTestDatabaseError):
        build_engine(migration_database_url(hosted_settings()), pool_size=1)

    assert built == []


def test_the_destructive_reset_is_never_reached_for_a_hosted_target() -> None:
    """The same ordering stated against the destructive function itself.

    ``seed`` below is the shape both ``demo_state`` and the intake ``_seed`` have: resolve a
    URL, then reset through it. The spy records a call it must never receive.
    """
    calls: list[str] = []

    def reset_demo_state(*_: Any, **__: Any) -> None:
        calls.append("reset")

    def seed(settings: Settings) -> None:
        url = migration_database_url(settings)
        reset_demo_state(url)

    with pytest.raises(UnsafeTestDatabaseError):
        seed(hosted_settings())

    assert calls == []


# ------------------------------------------------------- the suite cannot reach around it


def destructive_test_modules() -> list[Path]:
    """Every module in the backend suite that can empty a table.

    Both names, because a truncation is reachable through two functions now. ``pp
    restore-demo-world`` sequences the reset behind three more steps and resolves its own
    migration connection from the settings it is handed, so a module that drives it is exactly
    as destructive as one that calls the reset directly -- and would be invisible to a scan
    that only knew the older name.
    """
    calls_reset = re.compile(r"(?:reset_demo_state|restore_demo_world)\s*\(")
    found = [
        path
        for path in sorted(TESTS.glob("*.py"))
        if path.name != Path(__file__).name and calls_reset.search(path.read_text(encoding="utf-8"))
    ]
    assert found, "no destructive test modules found; this scan is checking nothing"
    return found


@pytest.mark.parametrize("module", destructive_test_modules(), ids=lambda path: path.name)
def test_no_destructive_module_resolves_a_database_url_around_the_guard(module: Path) -> None:
    """A module that can truncate may not ask ``Settings`` for a connection string itself.

    This is what makes the interlock structural rather than a convention. The two accessors
    are the only way to turn settings into a URL, so a destructive module that calls neither
    can only have got its URL from ``_database_safety`` or from a fixture that did.
    """
    source = module.read_text(encoding="utf-8")
    reached_around = re.findall(r"\.require_(?:migration_)?database_url\(\)", source)
    assert reached_around == [], (
        f"{module.name} resolves a database URL directly; use _database_safety instead"
    )


def test_the_local_stack_template_points_the_suite_at_a_local_database() -> None:
    """The launcher's own template, checked rather than assumed.

    ``scripts/with_local_env.py`` runs the suite against ``docker/env/host.env``, which is
    generated from this template. If the template ever named something remote, every test
    above would still pass and the suite would still be pointed somewhere it must not be.
    """
    template = (REPOSITORY / "docker" / "env" / "host.env.example").read_text(encoding="utf-8")
    urls = re.findall(r"^PP_(?:MIGRATION_)?DATABASE_URL=(.+)$", template, re.MULTILINE)
    assert len(urls) == 2, urls
    for url in urls:
        # The template carries an unsubstituted port placeholder; the host is what matters.
        assert local_test_database_url(
            url.replace("__POSTGRES_PUBLISHED_PORT__", "55432"),
            variable="PP_MIGRATION_DATABASE_URL",
        )
