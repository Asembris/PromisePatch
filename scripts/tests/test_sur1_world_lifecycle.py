"""The worker/``TRUNCATE`` race, removed structurally rather than retried around.

``ABLATION`` ``C06`` of the first scored run died of a PostgreSQL deadlock: the fixture load
was emptying forty-two tables while the ``worker`` container was reading several of them, and
the two took their locks in crossing orders. See ``docs/sur1-first-scored-run-defect.md`` §2.3.

The correction is a lifecycle -- quiesce, install, verify, resume -- and these are its proofs:
the worker is down for the whole install, it comes back afterwards, a world that did not land
is refused instead of measured, a failed install still hands the worker back, and two attempts
in a row each start from the same clean state.

**Nothing here runs ``docker``, opens a database or drives an arm.** The worker control and the
database reader are stand-ins that record what they were asked to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from scripts.sur1.bindings import Probe


@dataclass(slots=True)
class WorldWith:
    """Only what the lifecycle check reaches. It is not a world and drives nothing."""

    orders: Any = None
    worker: Any = None


# ---------------------------------------- the worker cannot race a world into the same tables


@dataclass(slots=True)
class ScriptedWorker:
    """A worker control that records the order it was asked to do things in."""

    log: list[str] = field(default_factory=list)
    running: bool = True
    refuse_resume: bool = False
    binding_kind: str = "real"

    def state(self) -> str:
        from scripts.sur1.bindings.lifecycle import RUNNING, STOPPED

        return RUNNING if self.running else STOPPED

    def quiesce(self) -> str:
        self.running = False
        self.log.append("quiesce")
        return "worker:stopped"

    def resume(self) -> str:
        from scripts.sur1.bindings.setup import PreparationError

        if self.refuse_resume:
            raise PreparationError("the worker would not start")
        self.running = True
        self.log.append("resume")
        return "worker:running"

    def probe(self) -> Probe:
        return Probe("WORKER", True, "worker can be stopped and started")


@dataclass(slots=True)
class ReadsFixtureState:
    """A database reader that answers one query: which world the product says is loaded."""

    fixture_name: str | None
    url: str = "postgresql://reader@127.0.0.1:55432/promisepatch"
    seen: list[str] = field(default_factory=list)

    def rows(self, source: str, statement: str) -> list[tuple[Any, ...]]:
        self.seen.append(statement)
        if self.fixture_name is None:
            return []
        return [(self.fixture_name, "a-digest")]


def lifecycle(worker: Any, database: Any) -> Any:
    from scripts.sur1.bindings.lifecycle import InstallationLifecycle

    return InstallationLifecycle(worker=worker, database=database)


def test_the_worker_is_down_for_the_whole_install_and_back_up_afterwards() -> None:
    """The deadlock, removed structurally: there is no worker to race while the world lands."""
    worker = ScriptedWorker()
    database = ReadsFixtureState(fixture_name="hollow-oak+sur1-C06")
    observed: list[bool] = []

    def install() -> str:
        observed.append(worker.running)
        worker.log.append("install")
        return "installed"

    assert lifecycle(worker, database).around("C06", install) == "installed"

    assert observed == [False], "a world was installed while the worker was still running"
    assert worker.log == ["quiesce", "install", "resume"]
    assert worker.running is True


def test_a_world_that_did_not_land_is_refused_rather_than_measured() -> None:
    """``fixture_state`` still names the previous world, so the install did not commit."""
    from scripts.sur1.bindings.setup import PreparationError

    worker = ScriptedWorker()
    database = ReadsFixtureState(fixture_name="hollow-oak")

    with pytest.raises(PreparationError, match=r"hollow-oak\+sur1-C06"):
        lifecycle(worker, database).around("C06", lambda: "installed")

    assert worker.log == ["quiesce", "resume"]


def test_a_database_with_no_fixture_row_is_refused() -> None:
    from scripts.sur1.bindings.setup import PreparationError

    worker = ScriptedWorker()

    with pytest.raises(PreparationError, match="no fixture_state row"):
        lifecycle(worker, ReadsFixtureState(fixture_name=None)).around("C06", lambda: "x")


def test_a_failed_install_still_hands_the_worker_back() -> None:
    """One bad attempt must not leave every later attempt driven at a stopped engine."""
    worker = ScriptedWorker()
    database = ReadsFixtureState(fixture_name="hollow-oak+sur1-C06")

    def install() -> str:
        raise RuntimeError("the order system refused a reset")

    with pytest.raises(RuntimeError, match="refused a reset"):
        lifecycle(worker, database).around("C06", install)

    assert worker.log == ["quiesce", "resume"]
    assert worker.running is True


def test_a_worker_that_will_not_come_back_is_named_beside_the_original_failure() -> None:
    """Neither fact is hidden by the other: the install failed, and so did the recovery."""
    worker = ScriptedWorker(refuse_resume=True)
    database = ReadsFixtureState(fixture_name="hollow-oak+sur1-C06")

    def install() -> str:
        raise RuntimeError("the order system refused a reset")

    with pytest.raises(RuntimeError) as raised:
        lifecycle(worker, database).around("C06", install)

    assert "would not start" in " ".join(getattr(raised.value, "__notes__", []))


def test_a_retry_installs_into_a_world_the_previous_attempt_did_not_leave_behind() -> None:
    """Two attempts in a row each quiesce, install and resume: no state crosses between them."""
    worker = ScriptedWorker()
    database = ReadsFixtureState(fixture_name="hollow-oak+sur1-C06")
    cycle = lifecycle(worker, database)

    cycle.around("C06", lambda: "first")
    cycle.around("C06", lambda: "second")

    assert worker.log == ["quiesce", "resume", "quiesce", "resume"]


def test_a_run_that_cannot_control_its_worker_is_refused() -> None:
    """A scored run may not install a world beside a worker it only pretends to control."""
    from scripts.sur1.bindings.lifecycle import UncontrolledWorker
    from scripts.sur1.preflight import worker_lifecycle

    refused = worker_lifecycle(world=WorldWith(worker=UncontrolledWorker()))

    assert not refused.passed

    allowed = worker_lifecycle(world=WorldWith(worker=ScriptedWorker()))
    assert allowed.passed, allowed.detail


def test_a_world_with_no_worker_control_at_all_is_refused() -> None:
    from scripts.sur1.preflight import worker_lifecycle

    refused = worker_lifecycle(world=WorldWith(worker=None))

    assert not refused.passed
    assert "deadlock" in refused.detail


def test_a_run_binds_the_real_worker_control() -> None:
    """The default is a stand-in; a run has to replace it, and this is where that is asserted."""
    import inspect

    from scripts.sur1 import run as run_module

    source = inspect.getsource(run_module.build)

    assert "ComposeWorkerControl()" in source


def test_the_compose_worker_can_be_waited_on() -> None:
    """``up --wait`` needs a healthcheck to wait for; without one, resume is a guess."""
    import yaml

    document = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    worker = document["services"]["worker"]

    assert "healthcheck" in worker, "the worker has no signal `docker compose up --wait` can use"
    assert worker["healthcheck"]["test"][0] == "CMD"


# ------------------------------------- handing the worker back must not re-seed the database


@dataclass(slots=True)
class RecordedCompose:
    """Stands in for ``docker compose``, recording every argv and answering ``ps`` as running."""

    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: list[str], **_: Any) -> Any:
        import subprocess

        self.calls.append(list(argv))
        stdout = '{"Service": "worker", "State": "running"}' if "ps" in argv else ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    def argv_for(self, verb: str) -> list[str]:
        return next(argv for argv in self.calls if verb in argv)


def test_resuming_the_worker_does_not_rerun_the_services_it_depends_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--no-deps``, without which handing the worker back destroys the installed world.

    The worker declares ``depends_on: seed``, and compose satisfies that by *re-running* seed --
    which is ``pp reset-demo-state``. Observed live on 2026-09-20: a sentinel written into
    ``fixture_state`` was replaced by ``hollow-oak`` by the resume alone, after the install had
    landed and ``verify`` had passed. Every attempt would have been driven at the canonical demo
    fixture rather than at its scenario's world.
    """
    import subprocess

    from scripts.sur1.bindings import lifecycle

    compose = RecordedCompose()
    monkeypatch.setattr(subprocess, "run", compose)

    assert lifecycle.ComposeWorkerControl().resume() == "worker:running"

    argv = compose.argv_for("up")
    assert "--no-deps" in argv, f"resume would re-run the worker's dependencies: {argv}"
    assert "--wait" in argv, "resume must still block on the worker's own healthcheck"


def test_the_service_a_resume_must_not_rerun_is_the_one_that_resets_the_database() -> None:
    """Why ``--no-deps`` is load-bearing, read from compose rather than asserted in prose."""
    import yaml

    document = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    depends = document["services"]["worker"]["depends_on"]
    assert "seed" in depends, "this test is about a dependency the worker no longer declares"
    assert document["services"]["seed"]["command"] == ["pp", "reset-demo-state"]
