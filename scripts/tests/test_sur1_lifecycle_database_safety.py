"""Where the lifecycle regression is allowed to point, asserted rather than intended.

``test_sur1_world_lifecycle_postgres`` is the one module in this directory that destroys
things. It issues ``DROP DATABASE``, runs Alembic to head, and loads the demo world through
``reset_demo_state`` -- correct against a disposable local container and catastrophic anywhere
else. It took its target verbatim from ``PP_MIGRATION_DATABASE_URL`` and proved nothing about
it. This file is the proof that it no longer can.

**How that variable came to name a hosted database.** ``deepeval`` is installed as a ``pytest11``
plugin, so every pytest session imports it, and importing it calls ``load_dotenv()``. The
repository's root ``.env`` is copied into ``os.environ`` before the first test runs -- so under
pytest, and only under pytest, a developer's hosted connection string was the one the fixture
read. Nothing in this repository asked for that and nothing in this repository can rely on it not
happening again, which is the whole argument for checking the target rather than the provenance.

**Two protections were assumed and neither held.** ``PP_ALLOW_FIXTURE_RESET`` says that *a*
reset is permitted and says nothing about where. The autouse guard in ``conftest`` refuses any
socket that leaves this machine -- but it was function-scoped, and pytest builds a module-scoped
fixture before the first function-scoped one, so ``migrated_world`` dropped a database before
the guard existed. It is also an in-process monkeypatch on ``socket``, and the Alembic upgrade
runs in a child process it cannot reach at any scope. The guard is now installed at session
scope too, which closes the first of those and not the second.

**So the proof is positive and structural, not a blacklist and not an ordering.** Every
connection string the module opens something on comes back from
:func:`_database_safety.local_test_database_url`, which hands back a URL naming one of four
known-local hosts and raises for everything else -- unknown, unparseable and hostless included.
A test below walks the module's own syntax tree and requires that of every call site that can
open a connection, so the interlock cannot be reached around by a later edit rather than merely
being followed by the current one.

Nothing here needs a database, a credential or a network: every refusal is proved with
``asyncpg.connect`` replaced by a recorder that is then asserted to be empty.
"""

from __future__ import annotations

import ast
import asyncio
import re
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, cast

import pytest
from _database_safety import (
    LOCAL_TEST_HOSTS,
    MIGRATION_URL_VARIABLE,
    RUNTIME_URL_VARIABLE,
    UnsafeTestDatabaseError,
    local_test_database_url,
)
from scripts.tests import conftest
from scripts.tests import test_sur1_world_lifecycle_postgres as lifecycle

REPOSITORY = Path(__file__).resolve().parents[2]

MODULE_SOURCE = Path(lifecycle.__file__).read_text(encoding="utf-8")

HOSTED = "postgresql+asyncpg://user:secret@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
"""A hosted target shaped exactly like the one this machine's ``.env`` names.

Written out rather than read from ``.env`` so the test says the same thing on a machine whose
``.env`` is local, and so the file's real credential never reaches a test report.
"""

LOCAL = "postgresql+asyncpg://postgres:secret@127.0.0.1:48432/promisepatch"
"""The disposable container this repository publishes, in the spelling ``host.env`` uses."""


# --------------------------------------------------------------- an approved target is accepted


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://postgres:secret@127.0.0.1:48432/promisepatch",
        "postgresql+asyncpg://postgres:secret@localhost:5432/promisepatch",
        "postgresql+asyncpg://postgres:secret@[::1]:55432/promisepatch",
        "postgresql+asyncpg://postgres:secret@postgres:5432/promisepatch",
    ],
)
def test_a_local_test_database_is_accepted_and_handed_back_unchanged(url: str) -> None:
    """The positive half. A guard that refused everything would also pass every refusal test."""
    assert local_test_database_url(url, variable=MIGRATION_URL_VARIABLE) == url


def test_the_approved_hosts_are_the_four_this_repository_serves_a_test_database_on() -> None:
    """Named, so widening the allowlist is a decision somebody has to make on purpose."""
    assert frozenset({"127.0.0.1", "localhost", "::1", "postgres"}) == LOCAL_TEST_HOSTS


def test_the_configured_target_is_read_and_checked_in_one_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_configured`` is the module's only door from the environment onto a connection string."""
    monkeypatch.setenv(MIGRATION_URL_VARIABLE, LOCAL)

    assert lifecycle._configured(MIGRATION_URL_VARIABLE) == LOCAL


def test_the_configured_target_refuses_a_hosted_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same door, with the value this machine's ``.env`` really carries."""
    monkeypatch.setenv(MIGRATION_URL_VARIABLE, HOSTED)

    with pytest.raises(UnsafeTestDatabaseError) as refusal:
        lifecycle._configured(MIGRATION_URL_VARIABLE)

    assert "pooler.supabase.com" in str(refusal.value)
    assert "secret" not in str(refusal.value), "a refusal never carries the password"


# ------------------------------------------------- and nothing else reaches a connection at all


@pytest.fixture
def recorded_connections(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Every ``asyncpg.connect`` this test made, which is the number the refusals assert on.

    Replaced with a recorder rather than left alone: if the guard ever stopped refusing, a real
    ``connect`` would be the accident itself, and a test that proved the absence of a connection
    by relying on the connection failing would prove nothing on a machine where it succeeded.
    """
    import asyncpg

    attempts: list[object] = []

    async def record(*args: Any, **kwargs: Any) -> Any:
        attempts.append(kwargs.get("dsn", args))
        raise AssertionError("a connection was opened; the guard did not refuse first")

    monkeypatch.setattr(asyncpg, "connect", record)
    return attempts


@pytest.mark.parametrize(
    ("url", "because"),
    [
        (HOSTED, "a hosted database on a cloud provider"),
        ("postgresql+asyncpg://user:secret@10.0.3.7:5432/promisepatch", "a private address"),
        (
            "postgresql+asyncpg://user:secret@localhost.attacker.example:5432/db",
            "a host that merely contains a local name",
        ),
        ("postgresql+asyncpg:///promisepatch", "a URL naming no host"),
        ("not a url at all", "a value that is not a connection string"),
        ("", "nothing configured"),
    ],
)
def test_an_unapproved_target_is_refused_before_a_connection_exists(
    url: str, because: str, recorded_connections: list[object]
) -> None:
    """The whole safety claim, at the only site in the module that dials a socket itself.

    ``_administer`` is what issues ``DROP DATABASE``. Each of these is refused by it, and the
    recorder is empty afterwards -- so the refusal is not something that happens after a
    connection, it is something that happens instead of one.
    """
    with pytest.raises(UnsafeTestDatabaseError):
        asyncio.run(_drop(url))

    assert recorded_connections == [], because


async def _drop(url: str) -> None:
    """The real statement the fixture runs, against whatever was handed in."""
    await lifecycle._administer(f'DROP DATABASE IF EXISTS "{lifecycle.SCRATCH_DATABASE}"', url=url)


def test_an_approved_target_reaches_the_connection_the_refusals_never_do(
    recorded_connections: list[object],
) -> None:
    """The negative control for the tests above: the guard is what refuses, not the recorder.

    A local URL gets past the check and reaches ``asyncpg.connect``, where the recorder raises
    its own error. If this passed with an empty recorder, every refusal above would be
    consistent with a module that had simply stopped working.
    """
    with pytest.raises(AssertionError, match="the guard did not refuse first"):
        asyncio.run(_drop(LOCAL))

    assert len(recorded_connections) == 1


# ---------------------------------------------------- the module-scoped fixture is covered too


def _fixture_body() -> Generator[tuple[str, str], None, None]:
    """``migrated_world``'s own generator, driven directly rather than through pytest.

    ``pytest.fixture`` hands back a definition object wrapping the function; the function is
    what holds the refusal, and driving it here is how a module-scoped setup can be tested at
    all -- pytest would otherwise build it once, before the first test, and there would be
    nothing left to observe.
    """
    definition: Any = lifecycle.migrated_world
    body = cast("Callable[[], Generator[tuple[str, str], None, None]]", definition.__wrapped__)
    return body()


@pytest.fixture
def refuse_every_destructive_step(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The three destructive things ``migrated_world`` does, replaced by recorders.

    Recording rather than allowing: what this proves is that the fixture refuses *before* the
    first of them, and a recorder that ran is the failure.
    """
    reached: list[str] = []

    async def administer(statement: str, *, url: str) -> None:
        reached.append(f"administer: {statement}")

    def run(arguments: list[str], **kwargs: Any) -> None:
        reached.append(f"subprocess: {' '.join(arguments[1:])}")

    async def load(url: str) -> None:
        reached.append("reset_demo_state")

    monkeypatch.setattr(lifecycle, "_administer", administer)
    monkeypatch.setattr(lifecycle, "_run", run)
    monkeypatch.setattr(lifecycle, "_load_world", load)
    return reached


def test_the_module_scoped_fixture_refuses_before_its_first_destructive_statement(
    monkeypatch: pytest.MonkeyPatch, refuse_every_destructive_step: list[str]
) -> None:
    """``migrated_world`` itself, driven with the environment that caused this defect.

    This is the case that matters. The fixture is module-scoped, so pytest builds it before any
    function-scoped protection is in place; the refusal therefore has to be inside it, and this
    drives its own body to show that it is.
    """
    monkeypatch.setenv(MIGRATION_URL_VARIABLE, HOSTED)
    monkeypatch.setenv(RUNTIME_URL_VARIABLE, HOSTED)

    with pytest.raises(UnsafeTestDatabaseError):
        next(_fixture_body())

    assert refuse_every_destructive_step == [], "nothing destructive may precede the refusal"


def test_an_unconfigured_environment_skips_rather_than_refusing(
    monkeypatch: pytest.MonkeyPatch, refuse_every_destructive_step: list[str]
) -> None:
    """No database configured is not a safety failure, and stays the ordinary skip it was.

    Caught as ``pytest.skip.Exception`` rather than as ``Exception``: a skip is an
    ``OutcomeException`` and derives from ``BaseException``, so a plain ``pytest.raises`` lets
    it through and this test skips itself while appearing to have made an assertion.
    """
    monkeypatch.delenv(MIGRATION_URL_VARIABLE, raising=False)
    monkeypatch.delenv(RUNTIME_URL_VARIABLE, raising=False)

    with pytest.raises(pytest.skip.Exception) as outcome:
        next(_fixture_body())

    assert MIGRATION_URL_VARIABLE in str(outcome.value)
    assert refuse_every_destructive_step == []


def test_a_local_environment_is_allowed_through_to_the_destructive_steps(
    monkeypatch: pytest.MonkeyPatch, refuse_every_destructive_step: list[str]
) -> None:
    """The positive half of the fixture's own check: a configured local stack still runs.

    Without this, a guard that refused every environment would satisfy every test above while
    quietly making the regression unrunnable -- which is the failure mode this module was
    written to close in the first place.
    """
    monkeypatch.setenv(MIGRATION_URL_VARIABLE, LOCAL)
    monkeypatch.setenv(RUNTIME_URL_VARIABLE, LOCAL)
    monkeypatch.setenv("PP_DEMO_WORKER_PASSWORD", "unused")
    monkeypatch.setenv("PP_DEMO_OWNER_PASSWORD", "unused")

    fixture = _fixture_body()
    migration, runtime = next(fixture)

    assert migration.endswith(f"/{lifecycle.SCRATCH_DATABASE}")
    assert runtime.endswith(f"/{lifecycle.SCRATCH_DATABASE}")
    assert refuse_every_destructive_step[:3] == [
        f'administer: DROP DATABASE IF EXISTS "{lifecycle.SCRATCH_DATABASE}"',
        f'administer: CREATE DATABASE "{lifecycle.SCRATCH_DATABASE}"',
        f"subprocess: -m alembic -c {REPOSITORY / 'apps' / 'backend' / 'alembic.ini'} upgrade head",
    ]
    assert "reset_demo_state" in refuse_every_destructive_step
    fixture.close()


def test_the_scratch_database_is_never_the_shared_local_one() -> None:
    """The name that is dropped, which must not be the database the demo world lives in."""
    assert lifecycle.SCRATCH_DATABASE == "sur1_lifecycle_regression"
    assert lifecycle.SCRATCH_DATABASE != "promisepatch"


# ------------------------------------------------- why the socket guard could not have done it


def test_the_socket_guard_now_covers_the_scope_the_module_fixture_is_built_at() -> None:
    """The scope mismatch that made this defect possible, held as a fact rather than a memory.

    pytest instantiates fixtures highest-scope-first, so a module-scoped fixture's setup runs
    before any function-scoped autouse fixture. ``migrated_world`` is module-scoped, which is
    why the socket guard was not installed when it dropped a database. It is now installed at
    session scope as well, and both scopes are read off the fixtures themselves here.

    This is the net, not the protection. The Alembic upgrade runs in a child process that no
    in-process patch on ``socket`` reaches at any scope, so what actually makes this module safe
    is the URL check above -- and if somebody later deletes that check believing the widened
    guard made it redundant, the tests above fail and this docstring says why.
    """
    per_test = conftest.refuse_off_machine_connections._fixture_function_marker
    per_session = conftest.refuse_off_machine_connections_outside_a_test._fixture_function_marker
    world = lifecycle.migrated_world._fixture_function_marker

    assert per_test.autouse is True
    assert per_test.scope == "function"
    assert per_session.autouse is True
    assert per_session.scope == "session"
    assert world.scope == "module"
    assert "subprocess" in MODULE_SOURCE, "the child process no socket patch can reach"


# ------------------------------------------------------ the module cannot reach around it later


CONNECTION_SITES = frozenset({"asyncpg.connect", "build_engine", "DatabaseReader"})
"""Every call in the lifecycle module that can result in an open connection."""

GUARD = "local_test_database_url"


def _dotted(expression: ast.expr) -> str:
    """The dotted spelling of an expression, as written in the source."""
    parts: list[str] = []
    current = expression
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _callee(node: ast.Call) -> str:
    """The dotted spelling of what a call calls."""
    return _dotted(node.func)


def _functions_of(source: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def connecting_functions() -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every function in the lifecycle module that can open a connection."""
    found = [
        function
        for function in _functions_of(MODULE_SOURCE)
        if any(
            _callee(call) in CONNECTION_SITES
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
        )
    ]
    assert found, "no connection sites found; this scan is checking nothing"
    return found


@pytest.mark.parametrize(
    "function", connecting_functions(), ids=lambda function: str(function.name)
)
def test_every_connection_site_proves_its_target_local_first(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> None:
    """Structural, not conventional: the guard is what the connection is made out of.

    A function that can open a connection must also call the allowlist. This is the assertion
    that survives a later edit -- somebody adding a fifth reader, or moving the fixture's work
    into a helper, has to pass through the check or fail this test.
    """
    guarded = [
        call
        for call in ast.walk(function)
        if isinstance(call, ast.Call) and _callee(call).endswith(GUARD)
    ]

    assert guarded, (
        f"{function.name} opens a connection without calling {GUARD}; every target this "
        f"module reaches has to be shown to be local first"
    )


def _names_a_database_url(key: ast.expr) -> bool:
    """Whether an ``os.environ`` key is one of the two connection strings."""
    if isinstance(key, ast.Constant):
        return isinstance(key.value, str) and "DATABASE_URL" in key.value
    return isinstance(key, ast.Name) and key.id.endswith("_URL_VARIABLE")


def _environment_reads(node: ast.AST) -> list[ast.AST]:
    """Every ``os.environ[...]`` and ``os.environ.get(...)`` naming a database URL."""
    found: list[ast.AST] = []
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Subscript)
            and _dotted(child.value) == "os.environ"
            and _names_a_database_url(child.slice)
        ):
            found.append(child)
        if (
            isinstance(child, ast.Call)
            and _callee(child) == "os.environ.get"
            and child.args
            and _names_a_database_url(child.args[0])
        ):
            found.append(child)
    return found


def test_no_unchecked_database_url_is_ever_bound_to_a_name() -> None:
    """The defect itself, refused structurally rather than remembered.

    What went wrong was one statement: ``migration = os.environ.get(...)``, and then a ``DROP``
    against whatever that held. So the rule is that a database URL taken out of the environment
    may be *tested* for presence and may be handed straight to the guard, but may never be bound
    to a name -- because a name is what the rest of a function goes on to use.
    """
    reads = _environment_reads(ast.parse(MODULE_SOURCE))
    assert reads, "no environment reads found; this scan is checking nothing"

    bound = [
        target.id
        for node in ast.walk(ast.parse(MODULE_SOURCE))
        if isinstance(node, ast.Assign) and _environment_reads(node.value)
        for target in node.targets
        if isinstance(target, ast.Name)
    ]

    assert bound == [], (
        f"{bound} holds a database URL that was never shown to be local; read it through "
        f"_configured, which refuses a target this suite may not destroy"
    )


# ------------------------------------------------------------------- and CI still has a target


def _workflow_database_urls(workflow: Path) -> list[str]:
    """The connection strings a workflow writes into its own environment, shell-resolved.

    The jobs build one ``address`` and interpolate it, so the literal line is not a URL. The
    substitutions here are exactly the two the shell would make, and a password becomes a
    placeholder because what is being checked is the host.
    """
    text = workflow.read_text(encoding="utf-8")
    address = re.search(r'^\s*address="([^"]+)"', text, re.MULTILINE)
    resolved: list[str] = []
    for url in re.findall(r"PP_(?:MIGRATION_)?DATABASE_URL=(postgresql[^\"']+)", text):
        value = re.sub(r"\$(?:superuser_password|app_password)", "placeholder", url)
        if address is not None:
            value = value.replace("$address", address.group(1))
        resolved.append(value)
    return resolved


@pytest.mark.parametrize("workflow", ["pr.yml", "effect-sets.yml"])
def test_ci_points_its_postgres_at_a_target_this_guard_accepts(workflow: str) -> None:
    """The guard must not break the only automated run that has a database.

    CI starts a disposable ``postgres:16-alpine`` and publishes it on ``127.0.0.1:5432``, which
    is on the allowlist. Asserted from the workflow's own text rather than assumed, so a change
    that moved CI onto a managed database would fail here rather than at a ``DROP``.
    """
    urls = _workflow_database_urls(REPOSITORY / ".github" / "workflows" / workflow)

    assert len(urls) == 2, urls
    for url in urls:
        assert local_test_database_url(url, variable=MIGRATION_URL_VARIABLE) == url


def test_the_launcher_only_ever_repoints_a_loopback_address() -> None:
    """``scripts/with_local_env.py`` is the supported way in, and it cannot move a remote one.

    The launcher rewrites the port in the URLs it loads so the suite reaches the port compose
    actually published. That rewrite is loopback-only by construction, so a ``host.env`` naming
    something else comes through untouched rather than quietly repointed -- and then meets the
    guard above. ``host.env.example`` itself is checked in ``apps/backend/tests``.
    """
    import sys

    # The launcher imports its sibling by bare name, as a script does, so the directory has to
    # be importable before the module is. Done here rather than at module scope so that
    # importing this file changes nothing for any other test in the directory.
    sys.path.insert(0, str(REPOSITORY / "scripts"))
    from scripts.with_local_env import repoint

    hosted = {MIGRATION_URL_VARIABLE: HOSTED}
    local = {MIGRATION_URL_VARIABLE: LOCAL}

    assert repoint(hosted, "48432") == hosted
    assert repoint(local, "48432")[MIGRATION_URL_VARIABLE] == LOCAL
    assert ":55432/" in repoint(local, "55432")[MIGRATION_URL_VARIABLE]
