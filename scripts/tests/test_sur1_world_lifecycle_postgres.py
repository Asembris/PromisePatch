"""The installation fingerprint, executed against a real migrated PostgreSQL schema.

``DR01`` died at its first install because :meth:`InstallationLifecycle.fingerprint` asked
``commitment_lines`` for a ``state`` column. The table has ``received_state``; the neighbouring
``production_tasks`` query is the one that has ``state``, which is how the mistake reads as a
transposition. See ``docs/sur1-dr01-hosted-worker-rehearsal.md`` §4.

**Nothing caught it because nothing had ever executed the statement.**
``test_sur1_world_lifecycle.py`` answers the lifecycle from a dictionary keyed on substrings,
and ``preflight.world_integrity`` drove the lifecycle against dictionaries too. A stand-in that
cannot fail on a real column name was the gap -- not the typo.

So this module opens a database. It builds a **disposable one of its own**, migrates it with the
product's own Alembic revisions, loads the demo world through the product's own governed reset,
and drives the real lifecycle at it. The shared local database is never written to: a test that
contaminated the demo fixture would be the same class of accident the lifecycle exists to refuse.

Marked ``integration`` and skipped without ``PP_MIGRATION_DATABASE_URL``, like every other suite
in this repository that needs a database. Roughly eight seconds: create, migrate, seed, drive,
drop.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts.sur1.bindings import Probe

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]

SCRATCH_DATABASE = "sur1_lifecycle_regression"
"""A database this module owns outright. Dropped and recreated around every run."""

SCENARIO = "C01"
"""The scenario name the installed world is loaded under, so ``verify`` has a row to accept.

No world *program* is built, run or read here: this is the fixture name a governed install
writes into ``fixture_state``, which is the only part of a scenario the lifecycle looks at.
"""

RASPBERRIES = "cl-vp-today-raspberries"
"""The line the third scored run's contamination attested ``NOT_RECEIVED`` before any arm acted.

Mutating exactly this line after ``resume`` is what makes the detection proof below the same
event the lifecycle was written for, rather than an arbitrary row change.
"""


# ------------------------------------------------------------------ a database this module owns


def _dsn(url: str) -> str:
    """``postgresql+asyncpg://`` is a SQLAlchemy spelling; asyncpg wants the scheme alone."""
    scheme, separator, rest = url.partition("://")
    return f"{scheme.split('+')[0]}{separator}{rest}"


def _named(url: str, database: str) -> str:
    return f"{url.rsplit('/', 1)[0]}/{database}"


async def _administer(statement: str, *, url: str) -> None:
    import asyncpg

    connection = await asyncpg.connect(dsn=_dsn(_named(url, "postgres")), timeout=10)
    try:
        await connection.execute(statement)
    finally:
        await connection.close()


def _run(arguments: list[str], *, environment: dict[str, str], cwd: Path) -> None:
    finished = subprocess.run(
        arguments, cwd=str(cwd), env=environment, capture_output=True, text=True
    )
    if finished.returncode != 0:
        raise AssertionError(
            f"{' '.join(arguments[1:])} failed ({finished.returncode})\n"
            f"{finished.stdout[-2000:]}\n{finished.stderr[-2000:]}"
        )


async def _load_world(url: str) -> None:
    """Install the demo world under the name a ``SUR-1`` install writes, through the product.

    ``reset_demo_state`` is the governed load the harness's own installer calls, and
    ``fixture_name`` is the one argument that installer sets: the lifecycle's ``verify`` reads
    that row back and requires it to name this scenario. Calling the product's writer rather
    than inserting rows is what makes the tables below hold what a real install leaves.
    """
    from scripts.sur1.bindings.lifecycle import FIXTURE_PREFIX

    from promisepatch.db import build_engine
    from promisepatch.db.uow import Actor
    from promisepatch.fixtures import demo
    from promisepatch.fixtures.reset import reset_demo_state

    timezone = os.environ.get("PP_BAKERY_TZ", "Africa/Tunis")
    anchor = demo.resolve_demo_anchor(datetime.now(UTC), timezone)
    engine = build_engine(url, pool_size=1)
    try:
        async with engine.begin() as connection:
            await reset_demo_state(
                connection,
                anchor=anchor,
                now=datetime.now(UTC),
                passwords={
                    demo.BAKER_ROLE: os.environ["PP_DEMO_WORKER_PASSWORD"],
                    demo.OWNER_ROLE: os.environ["PP_DEMO_OWNER_PASSWORD"],
                },
                actor=Actor(kind="SYSTEM", id="sur1-lifecycle-regression"),
                fixture_name=f"{FIXTURE_PREFIX}{SCENARIO}",
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def migrated_world() -> Iterator[tuple[str, str]]:
    """A freshly migrated database holding the demo world, and the two URLs that reach it.

    The schema comes from Alembic rather than from ``metadata.create_all``: the defect this
    module exists to catch is a statement disagreeing with the *migrated* schema, and building
    the tables from the same declarations the statement would be compared against would make the
    two agree by construction.
    """
    migration = os.environ.get("PP_MIGRATION_DATABASE_URL")
    runtime = os.environ.get("PP_DATABASE_URL")
    if not migration or not runtime:
        pytest.skip(
            "PP_MIGRATION_DATABASE_URL and PP_DATABASE_URL are not set; this suite needs a "
            "database. Run it through scripts/with_local_env.py."
        )

    asyncio.run(_administer(f'DROP DATABASE IF EXISTS "{SCRATCH_DATABASE}"', url=migration))
    asyncio.run(_administer(f'CREATE DATABASE "{SCRATCH_DATABASE}"', url=migration))
    environment = dict(
        os.environ,
        PP_MIGRATION_DATABASE_URL=_named(migration, SCRATCH_DATABASE),
        PP_DATABASE_URL=_named(runtime, SCRATCH_DATABASE),
        PP_ALLOW_FIXTURE_RESET="true",
    )
    try:
        _run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(ROOT / "apps" / "backend" / "alembic.ini"),
                "upgrade",
                "head",
            ],
            environment=environment,
            cwd=ROOT / "apps" / "backend",
        )
        asyncio.run(_load_world(environment["PP_MIGRATION_DATABASE_URL"]))
        yield (
            environment["PP_MIGRATION_DATABASE_URL"],
            environment["PP_DATABASE_URL"],
        )
    finally:
        asyncio.run(_administer(f'DROP DATABASE IF EXISTS "{SCRATCH_DATABASE}"', url=migration))


@pytest.fixture
def reader(migrated_world: tuple[str, str]) -> Any:
    """The receivers' own reader on the runtime role, exactly as a run reads a world."""
    from scripts.sur1.bindings.receivers import DatabaseReader

    return DatabaseReader(url=migrated_world[1])


# ------------------------------------------------------------ the worker controls it is handed


@dataclass(slots=True)
class QuietWorker:
    """A worker control that writes nothing. The database is the only real thing it meets."""

    log: list[str] = field(default_factory=list)
    binding_kind: str = "stand-in"

    def state(self) -> str:
        from scripts.sur1.bindings.lifecycle import RUNNING

        return RUNNING

    def quiesce(self) -> str:
        self.log.append("quiesce")
        return "worker:stopped"

    def resume(self) -> str:
        self.log.append("resume")
        return "worker:running"

    def probe(self) -> Probe:
        return Probe("WORKER", True, "nothing is controlled and nothing is written")


@dataclass(slots=True)
class AttestsOnResume(QuietWorker):
    """A worker whose return attests today's raspberry line, through the product's own writer.

    Not a stand-in for the contamination: it *is* the contamination, committed to the same
    database the fingerprint reads, so what refuses the attempt is a row that really moved.
    """

    migration_url: str = ""

    def resume(self) -> str:
        # Named rather than ``super()``: ``slots=True`` rebuilds the class, so the zero-argument
        # form's ``__class__`` cell points at a class this instance is not one of.
        asyncio.run(self._attest())
        return QuietWorker.resume(self)

    async def _attest(self) -> None:
        from sqlalchemy import text

        from promisepatch.db import build_engine
        from promisepatch.db.uow import Actor, UnitOfWork

        engine = build_engine(self.migration_url, pool_size=1)
        try:
            async with (
                engine.begin() as connection,
                UnitOfWork(connection).governed(
                    event_type="SUR1_LIFECYCLE_REGRESSION",
                    actor=Actor(kind="SYSTEM", id="regression"),
                    authority="NONE",
                    after={"line": RASPBERRIES},
                    occurred_at=datetime.now(UTC),
                ) as write,
            ):
                await write.execute(
                    text(
                        "UPDATE promisepatch.commitment_lines SET"
                        " received_state = 'NOT_RECEIVED', settled_at = now(),"
                        " attested_by = 'regression' WHERE id = :line"
                    ).bindparams(line=RASPBERRIES)
                )
        finally:
            await engine.dispose()


def lifecycle(worker: Any, database: Any) -> Any:
    from scripts.sur1.bindings.lifecycle import InstallationLifecycle

    return InstallationLifecycle(worker=worker, database=database)


def _install(database: Any) -> str:
    """Stand in for the fixture load alone. ``reset-demo-state`` already installed the world."""
    database.rows("WORLD", "SELECT 1")
    return "installed"


# ----------------------------------------------------------------------- the fingerprint reads


def test_the_fingerprint_reads_a_real_installed_world(reader: Any) -> None:
    """Every statement the fingerprint issues, executed against the migrated schema.

    This is the whole regression. Under the defect, ``fingerprint`` raised
    ``UndefinedColumnError: column "state" does not exist`` here, and every scored attempt would
    have died at its first install.
    """
    from scripts.sur1.bindings.lifecycle import FIXTURE_PREFIX, QUIET_TABLES

    fingerprint = lifecycle(QuietWorker(), reader).fingerprint()

    assert [name for name, _ in fingerprint["fixture_state"]] == [f"{FIXTURE_PREFIX}{SCENARIO}"]
    assert sorted(fingerprint["counts"]) == sorted(QUIET_TABLES)
    assert all(isinstance(count, int) for count in fingerprint["counts"].values())


def test_the_commitment_lines_of_a_real_world_are_read_with_their_states(reader: Any) -> None:
    """Not that a query ran: that the column carrying a line's settlement came back."""
    lines = dict(lifecycle(QuietWorker(), reader).fingerprint()["commitment_lines"])

    assert RASPBERRIES in lines
    assert set(lines.values()) == {"EXPECTED"}, "a freshly loaded world has settled nothing"


def test_the_production_tasks_of_a_real_world_are_read_with_their_states(reader: Any) -> None:
    """The neighbouring query, whose column really is ``state``, proved against the same schema."""
    tasks = lifecycle(QuietWorker(), reader).fingerprint()["production_tasks"]

    assert tasks, "the demo world schedules work and the fingerprint has to see it"
    assert {state for _, state, _ in tasks} <= {"SCHEDULED", "STARTED", "DONE", "HELD"}
    assert {holder for _, _, holder in tasks} == {""}, "no case holds a task in a fresh world"


def test_the_quiet_tables_of_a_real_world_are_counted(reader: Any) -> None:
    """A count is the fingerprint's evidence that no case's own work has started here."""
    from scripts.sur1.bindings.lifecycle import QUIET_TABLES

    counts = lifecycle(QuietWorker(), reader).fingerprint()["counts"]

    assert counts == dict.fromkeys(QUIET_TABLES, 0)


# ------------------------------------------------------------ and what it is read twice to find


def test_a_real_write_after_the_worker_returns_refuses_the_attempt(
    migrated_world: tuple[str, str], reader: Any
) -> None:
    """The v3 contamination, committed for real and caught by the second read.

    ``around`` fingerprints the installed world, hands the worker back, and fingerprints again.
    The worker here attests today's raspberry line on its way up -- which is what the product's
    own start-up provisioning did on all 27 attempts of the third scored run -- and the
    comparison has to refuse the attempt rather than let it be measured.
    """
    from scripts.sur1.bindings.setup import PreparationError

    worker = AttestsOnResume(migration_url=migrated_world[0])

    with pytest.raises(PreparationError, match="nobody declared") as refusal:
        lifecycle(worker, reader).around(SCENARIO, lambda: _install(reader))

    assert "commitment_lines moved" in str(refusal.value)
    assert worker.log == ["quiesce", "resume"]

    after = dict(lifecycle(QuietWorker(), reader).fingerprint()["commitment_lines"])
    assert after[RASPBERRIES] == "NOT_RECEIVED", "the refusal is about a row that really moved"


# ------------------------------------------------------------------ the negative control for it


def test_the_column_dr01_asked_for_does_not_exist_and_is_refused(reader: Any) -> None:
    """Proof that the tests above have the power to fail, and had it for exactly this defect.

    A suite that only ever runs the corrected statement cannot say whether it would have caught
    the wrong one. This runs ``DR01``'s statement through the same reader against the same
    schema and requires the database to refuse it, so a fingerprint that drifted back onto a
    column ``commitment_lines`` does not have could not pass this module quietly.
    """
    from scripts.sur1.bindings.receivers import ReceiverUnreadableError

    with pytest.raises(ReceiverUnreadableError) as refused:
        reader.rows("WORLD", "SELECT id, state FROM commitment_lines ORDER BY id")

    assert "UndefinedColumnError" in refused.value.detail
    assert reader.rows("WORLD", "SELECT id, received_state FROM commitment_lines ORDER BY id")


def test_the_migrated_schema_is_the_one_the_fingerprint_is_written_against(reader: Any) -> None:
    """Drift under the fingerprint, named as columns rather than inferred from a failure."""
    columns = {
        str(name)
        for (name,) in reader.rows(
            "WORLD",
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'promisepatch' AND table_name = 'commitment_lines'",
        )
    }

    assert "received_state" in columns
    assert "state" not in columns
