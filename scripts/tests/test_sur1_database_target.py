"""One database target, proved by pointing the two ends apart and watching the run refuse.

``20260920T1100Z-scored-corrected`` passed all seventeen preflight checks and then failed all 27
of its attempts in preparation, because the governed fixture load resolved its own connection
from the repository's ``.env`` -- a hosted Supabase instance -- while the receivers read the local
database named by ``SUR1_DATABASE_URL``. The guard inside the write refused before anything was
dialled, which is why nothing was spent and the hosted database was never opened. But a refusal at
the write is not a gate: by then the authorisation had been minted and the run directory existed.

This module proves the correction in both halves. The fixture load no longer resolves a database
at all -- it is handed one -- and :func:`~scripts.sur1.preflight.database_identity` compares the
two before a scored run is authorised. Nothing here opens a connection, drives an arm, calls a
model or reaches AWS; the one test that would have is the one that asserts a socket is never
created.

The two published scored runs are pinned at the bottom, byte for byte. This correction sits
beside both and replaces neither.
"""

from __future__ import annotations

import hashlib
import socket
from pathlib import Path
from typing import Any

import pytest
from scripts.sur1.bindings.database import (
    CANONICAL_BACKEND,
    DEFAULT_PORT,
    DatabaseIdentity,
    DatabaseIdentityError,
    InstallerTarget,
    disagreement,
    identity_of,
    installer_target,
    receiver_identity,
)
from scripts.sur1.bindings.setup import PreparationError, WorldHandles
from scripts.sur1.preflight import REQUIRED_CHECKS, database_identity

HOSTED = (
    "postgresql+asyncpg://postgres.abc:secret@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
)
"""The shape of the URL the repository's ``.env`` actually held when the second run was taken.

A literal rather than a read of ``.env``, because this file must assert the same thing on a
machine whose ``.env`` points somewhere else entirely -- including on CI, where there is none.
The credential in it is invented.
"""

LOCAL_RECEIVER = "postgresql://promisepatch_app:secret@127.0.0.1:55432/promisepatch"
LOCAL_INSTALLER = "postgresql+asyncpg://promisepatch:secret@127.0.0.1:55432/promisepatch"
"""The two ends of a correct local run: one database, two roles, two drivers."""


# ------------------------------------------------------------------ what a URL is read as


def test_a_connection_string_is_read_as_a_server_and_a_database_and_never_a_credential() -> None:
    identity = identity_of(LOCAL_INSTALLER)

    assert identity == DatabaseIdentity(
        backend=CANONICAL_BACKEND, host="127.0.0.1", port=55432, database="promisepatch"
    )
    rendered = f"{identity}{identity.describes()}"
    assert "secret" not in rendered
    assert "promisepatch:" not in rendered


def test_two_roles_and_two_drivers_at_one_database_are_one_database() -> None:
    """The case a naive comparison would refuse, and refusing it would refuse every real run.

    The fixture load is the owner's ``TRUNCATE`` through SQLAlchemy and asyncpg; the receivers
    hand a bare DSN to asyncpg directly. Different credential, different driver, same database.
    """
    assert identity_of(LOCAL_INSTALLER) == identity_of(LOCAL_RECEIVER)
    assert identity_of(LOCAL_INSTALLER).driver == "asyncpg"
    assert identity_of(LOCAL_RECEIVER).driver == ""
    assert disagreement(identity_of(LOCAL_INSTALLER), identity_of(LOCAL_RECEIVER)) == ""


def test_an_omitted_port_is_postgresql_s_own_default_rather_than_a_difference() -> None:
    assert identity_of("postgresql://host.example/promisepatch").port == DEFAULT_PORT
    assert identity_of("postgresql://host.example/promisepatch") == identity_of(
        f"postgresql://host.example:{DEFAULT_PORT}/promisepatch"
    )


def test_a_hosted_database_and_the_local_one_are_not_the_same_database() -> None:
    said = disagreement(identity_of(HOSTED), identity_of(LOCAL_RECEIVER))

    assert "aws-1-eu-west-1.pooler.supabase.com:5432/postgres" in said
    assert "127.0.0.1:55432/promisepatch" in said
    assert "world that was never installed" in said
    assert "secret" not in said


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "promisepatch",
        "mysql://user@127.0.0.1:3306/promisepatch",
        "postgresql://127.0.0.1:55432",
        "postgresql://:55432/promisepatch",
        "postgresql://127.0.0.1:not-a-port/promisepatch",
    ],
)
def test_a_url_that_cannot_be_read_is_refused_rather_than_treated_as_agreement(url: str) -> None:
    """*Unknown* is the one answer a gate may not read as a match."""
    with pytest.raises(DatabaseIdentityError):
        identity_of(url)


# ------------------------------------------------------------- the gate, before authorisation


class _World:
    """A world that names its two databases and reaches neither. No probe, no connection."""

    def __init__(self, *, receiver: str, installer: InstallerTarget | None) -> None:
        self.database = _Reader(receiver)
        self.installer = installer


class _Reader:
    def __init__(self, url: str) -> None:
        self.url = url


def _config(url: str = LOCAL_RECEIVER) -> Any:
    from scripts.sur1.bindings.config import BindingConfig

    return BindingConfig.from_environment({"SUR1_DATABASE_URL": url})


def test_the_split_target_that_lost_the_second_scored_run_is_now_a_failed_check() -> None:
    """The exact configuration of ``20260920T1100Z-scored-corrected``, asked before the run."""
    refused = database_identity(
        world=_World(receiver=LOCAL_RECEIVER, installer=InstallerTarget(url=HOSTED)),
        config=_config(),
    )

    assert not refused.passed
    assert "aws-1-eu-west-1.pooler.supabase.com:5432/postgres" in refused.detail
    assert "127.0.0.1:55432/promisepatch" in refused.detail


def test_one_database_behind_two_roles_passes_and_says_where_the_load_resolved_it() -> None:
    allowed = database_identity(
        world=_World(receiver=LOCAL_RECEIVER, installer=InstallerTarget(url=LOCAL_INSTALLER)),
        config=_config(),
    )

    assert allowed.passed, allowed.detail
    assert "127.0.0.1:55432/promisepatch" in allowed.detail
    assert "PP_MIGRATION_DATABASE_URL" in allowed.detail


def test_a_world_whose_receivers_read_elsewhere_than_the_run_was_configured_for_is_refused() -> (
    None
):
    """The third reading. Two ends agreeing proves nothing if the third names somewhere else."""
    refused = database_identity(
        world=_World(receiver=HOSTED, installer=InstallerTarget(url=HOSTED)),
        config=_config(LOCAL_RECEIVER),
    )

    assert not refused.passed
    assert "configured for" in refused.detail


def test_a_world_carrying_no_installer_target_may_not_be_driven() -> None:
    refused = database_identity(
        world=_World(receiver=LOCAL_RECEIVER, installer=None), config=_config()
    )

    assert not refused.passed
    assert "no installer target" in refused.detail


def test_a_load_that_could_not_resolve_a_database_at_all_is_reported_not_raised() -> None:
    """``build`` reaches nothing and refuses nothing; the preflight is what says no."""
    refused = database_identity(
        world=_World(
            receiver=LOCAL_RECEIVER,
            installer=InstallerTarget(fault="RuntimeError: PP_MIGRATION_DATABASE_URL is not set"),
        ),
        config=_config(),
    )

    assert not refused.passed
    assert "PP_MIGRATION_DATABASE_URL" in refused.detail


def test_the_comparison_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """The property that lets this refuse *before* anything is dialled, asserted rather than read.

    Every constructor and connector on the socket module is replaced with one that fails the
    test. A check that resolved its answer by connecting would be a check that had already
    touched the database it exists to refuse.
    """

    def forbidden(*arguments: object, **keywords: object) -> None:
        raise AssertionError("the database identity check opened a connection")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)

    refused = database_identity(
        world=_World(receiver=LOCAL_RECEIVER, installer=InstallerTarget(url=HOSTED)),
        config=_config(),
    )
    allowed = database_identity(
        world=_World(receiver=LOCAL_RECEIVER, installer=InstallerTarget(url=LOCAL_INSTALLER)),
        config=_config(),
    )

    assert not refused.passed
    assert allowed.passed


def test_the_gate_is_one_of_the_questions_a_scored_authorisation_is_refused_without() -> None:
    assert "database_identity" in REQUIRED_CHECKS
    assert REQUIRED_CHECKS.index("database_identity") < REQUIRED_CHECKS.index("output_directory")


# --------------------------------------------------------------- the load resolves nothing


def test_the_fixture_load_no_longer_resolves_a_database_of_its_own() -> None:
    """Structural, because a comment saying so is not a control.

    ``require_migration_database_url`` is the call that used to decide, inside the write, which
    database a canonical world was installed into. It appears nowhere on this path now: the
    target is a parameter, and there is no second place a load could look one up.
    """
    import ast
    import inspect

    from scripts.sur1.bindings import realisation

    source = Path("scripts/sur1/bindings/realisation.py").read_text(encoding="utf-8")
    called = {
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "require_migration_database_url" not in called
    assert "require_database_url" not in called
    assert "target" in inspect.signature(realisation._write).parameters


def test_a_load_handed_no_database_refuses_instead_of_finding_one() -> None:
    import asyncio

    from scripts.sur1.bindings import realisation

    with pytest.raises(PreparationError, match="no database target was handed"):
        asyncio.run(realisation._write(object(), fixture_name="unit", anchor=None, target=None))


def test_a_load_whose_target_disagrees_with_the_receivers_refuses_before_it_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The load's own last refusal, kept beside the preflight's rather than replaced by it.

    A development path that never went through a preflight still reaches this, and a destructive
    write with one guard is a destructive write with one guard.

    *Refuses before it connects* is asserted rather than read off the source order: the engine
    factory this load would connect through is replaced with one that fails the test, as is every
    way the standard library resolves or dials a host. ``socket.socket`` itself is left alone
    because ``asyncio.run`` builds its own self-pipe out of one before any of this code runs, and
    a sabotage that caught the event loop would prove nothing about the database.
    """
    import asyncio

    from scripts.sur1.bindings import realisation

    from promisepatch.db import session as db_session

    def forbidden(*arguments: object, **keywords: object) -> None:
        raise AssertionError("the fixture load opened a connection to a database it refused")

    monkeypatch.setattr(db_session, "build_engine", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)

    with pytest.raises(PreparationError, match="world that was never installed"):
        asyncio.run(
            realisation._write(
                object(),
                fixture_name="unit",
                anchor=None,
                target=InstallerTarget(url=HOSTED),
                expected_database=LOCAL_RECEIVER,
            )
        )


def test_the_destructive_write_guard_is_still_in_front_of_the_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment that never opted into fixture resets is still refused one.

    The correction moved *which* database the load writes to; it did not move *whether* the load
    is allowed to write at all. ``PP_ALLOW_FIXTURE_RESET`` is the product's own statement by
    whoever configured the deployment, and a run whose target and receivers agree perfectly still
    does not get to truncate a database that never opted in. This is the guard that makes a
    hosted or otherwise non-local target fail safe rather than fail agreeably.
    """
    import asyncio

    from scripts.sur1.bindings import realisation

    import promisepatch.config as product_config
    from promisepatch.db import session as db_session
    from promisepatch.fixtures.reset import FixtureResetNotAllowedError

    class Closed:
        allow_fixture_reset = False

    def forbidden(*arguments: object, **keywords: object) -> None:
        raise AssertionError("a refused fixture load still opened an engine")

    monkeypatch.setattr(product_config, "get_settings", Closed)
    monkeypatch.setattr(db_session, "build_engine", forbidden)

    with pytest.raises(FixtureResetNotAllowedError, match="PP_ALLOW_FIXTURE_RESET"):
        asyncio.run(
            realisation._write(
                object(),
                fixture_name="unit",
                anchor=None,
                target=InstallerTarget(url=HOSTED),
                expected_database=HOSTED,
            )
        )


def test_the_installer_is_built_from_the_target_the_handles_carry() -> None:
    """``realise`` hands the load the run's database rather than letting it choose one."""
    from scripts.sur1.bindings.realisation import LiveInstaller

    target = InstallerTarget(url=LOCAL_INSTALLER)
    handles = WorldHandles(
        order_system_base_url="http://order-system.invalid",
        database=_Reader(LOCAL_RECEIVER),  # type: ignore[arg-type]
        installer=target,
    )
    built = LiveInstaller(target=handles.installer, expected_database=handles.database.url)

    assert built.target is target
    assert built.expected_database == LOCAL_RECEIVER


def test_an_unresolvable_product_setting_comes_back_as_a_fault_rather_than_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assembly reaches nothing and refuses nothing. A missing setting is reported, not raised."""
    import promisepatch.config as product_config

    def unset() -> Any:
        raise RuntimeError("PP_MIGRATION_DATABASE_URL is not configured")

    monkeypatch.setattr(product_config, "get_settings", unset)

    resolved = installer_target()

    assert resolved.fault
    assert "PP_MIGRATION_DATABASE_URL" in resolved.fault
    with pytest.raises(DatabaseIdentityError):
        resolved.identity()


def test_the_receivers_database_is_named_by_the_scored_variable_in_every_refusal() -> None:
    with pytest.raises(DatabaseIdentityError, match="SUR1_DATABASE_URL"):
        receiver_identity("")


# ------------------------------------------------- neither published run moved, and no digest did

PRESERVED_RUNS = {
    "20260919T2020Z-scored": (
        57,
        "d599d644c6869fe527a32cfe240fe9a20433ed4a07679b02fbb597fecdc746ed",
    ),
    "20260920T1100Z-scored-corrected": (
        57,
        "e2a46c35b53902c817b9602999bb84f3df82cd3c7b425cb813551e7817364bca",
    ),
}
"""Both scored runs, hashed the way the freeze hashes a module set: path, then bytes, sorted.

If one of these fails, something edited a published run. The right response is to restore it and
never to update the constant. The second run is pinned here for the first time; the first was
already pinned in ``test_sur1_harness_correction`` and is pinned again beside it deliberately,
because the claim this correction has to make is about *both*.
"""


@pytest.mark.parametrize("run_id", sorted(PRESERVED_RUNS))
def test_a_published_scored_run_is_byte_identical_to_what_was_taken(run_id: str) -> None:
    expected_files, expected_digest = PRESERVED_RUNS[run_id]
    root = Path("docs/benchmarks/runs") / run_id

    assert root.is_dir(), f"{run_id} is missing from the tree"
    files = sorted(path for path in root.rglob("*") if path.is_file())
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.relative_to(root).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes().replace(b"\r\n", b"\n"))
        hasher.update(b"\0")

    assert len(files) == expected_files
    assert hasher.hexdigest() == expected_digest


def test_the_second_scored_run_still_says_it_reached_no_model() -> None:
    """Read out of the artefact rather than out of a document about it."""
    import json
    from collections import Counter

    root = Path("docs/benchmarks/runs/20260920T1100Z-scored-corrected")
    verdicts = Counter(
        json.loads(path.read_text(encoding="utf-8"))["outcome"]
        for path in sorted((root / "verdicts").glob("*.json"))
    )

    assert sum(verdicts.values()) == 27
    assert verdicts["HARNESS_FAILURE"] == 27


def test_this_correction_moved_no_frozen_benchmark_identity() -> None:
    """The manifest, the prompt, the scorer, the predeclaration and the program set all hold.

    ``implementation_sha`` legitimately moves -- the modules that decide where a world is
    installed are part of what it hashes, and two of them changed -- and it is re-frozen in the
    published declaration rather than exempted, so ``differences()`` is still empty.
    """
    from scripts.sur1 import predeclaration
    from scripts.sur1.bindings.declaration import differences, published
    from scripts.sur1.frozen import Contract

    identity = Contract.load().identity
    declaration = published()

    assert identity.manifest_sha == (
        "5718340fbd19aa8ba1aedc2327c07a934e22b773271e996f13f0e8d87e70e84c"
    )
    assert identity.baseline_prompt_sha == (
        "772ba46025620a1aea4742fac3971c5906ec3252036d07725434e0a89ce47cb1"
    )
    assert identity.scorer_version == "1.0.0"
    assert predeclaration.PREDECLARATION_SHA == (
        "c53d267a0874d2e91456fdfacc23c86ebfc411f938cbe060ce958cb41d1e1927"
    )
    assert declaration["program_set_sha"] == (
        "88db566c13ef7a9865141583e5d918d43ff1b612b3311393c12af627ab1de649"
    )
    assert differences() == ()


def test_every_world_digest_is_the_one_that_was_published() -> None:
    """The nine worlds are unchanged: this correction moved where they go, never what they are."""
    from scripts.sur1.bindings.declaration import published
    from scripts.sur1.bindings.programs import programs
    from scripts.sur1.bindings.worldsnapshot import digests

    declared = published()["programs"]
    recomputed = digests(programs())

    assert sorted(declared) == sorted(recomputed)
    for scenario_id, digest in sorted(recomputed.items()):
        assert declared[scenario_id]["world_digest"] == digest
