"""Installing a world beside a running worker, without the two racing for the same tables.

``reset_demo_state`` empties forty-two tables in one transaction. ``TRUNCATE`` takes an
``ACCESS EXCLUSIVE`` lock on each of them, one at a time, in the order the statement lists;
the ``worker`` container's cycle takes ``ACCESS SHARE`` on several of them, in an order of its
own. The two orders cross, and PostgreSQL resolves it the only way it can::

    Process 131199 waits for AccessExclusiveLock on relation 16412; blocked by process 93662.
    Process 93662 waits for AccessShareLock on relation 16989; blocked by process 131199.

That is the deadlock that cost ``ABLATION`` ``C06`` in the first scored run
(``docs/sur1-first-scored-run-defect.md`` §2.3). It is not a flake to be retried: it is two
processes that must not be writing at the same time, and the fix is to make sure they are not.

**The lifecycle, and the reason for each step.**

1. **Quiesce.** The worker is stopped and the stop is *verified* before anything is written. A
   stopped container has no backend, and a lock nobody holds cannot be waited on -- so the race
   is removed rather than made less likely.
2. **Install.** The caller does whatever installing a world means; this module does not know.
3. **Verify.** The product's own ``fixture_state`` row is read back and has to name the world
   that was just installed. An install that half-happened is refused here rather than measured.
4. **Resume.** The worker comes back, and coming back is verified too. Arms B and C work
   through the product, and the product's durable work is the worker's -- an attempt driven at
   a stopped worker would measure a system with no engine.

**Nothing waits on a guess.** Stopping and starting are synchronous operations that report
what happened, the compose service carries a healthcheck so ``up --wait`` blocks on a real
signal, and every step ends with a *read* of the state it was supposed to produce. There is no
sleep here and nothing is attempted twice.

**A failed install still resumes the worker.** Leaving it down would make one bad attempt into
a broken run: the next scenario would be driven at a system whose durable work never runs, and
the numbers would look like findings. The original failure is what is raised; a resume that
also failed is named beside it rather than replacing it.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol, TypeVar

from scripts.sur1.bindings import REAL, Probe
from scripts.sur1.bindings.receivers import DatabaseReader, ReceiverUnreadableError
from scripts.sur1.bindings.setup import PreparationError

ROOT: Final = Path(__file__).resolve().parents[3]

RUNNING: Final = "running"
STOPPED: Final = "stopped"
ABSENT: Final = "absent"
"""The three answers a worker's state can be. ``ABSENT`` is *no such service*, not *stopped*."""

FIXTURE_PREFIX: Final = "hollow-oak+sur1-"
"""What the governed fixture load calls a world it installed for one scenario.

The same string :func:`~scripts.sur1.bindings.realisation._load` builds. Restated here rather
than imported because this module verifies the *result* and importing the installer to check
its own work would make the two agree by construction.
"""

T = TypeVar("T")


class WorkerControl(Protocol):
    """Whatever can put the durable worker down and bring it back, and say which it is."""

    @property
    def binding_kind(self) -> str:
        """Read-only, so an implementation may be frozen. A control is configuration, not state.

        Declared as a property rather than as an attribute -- which is how
        :class:`~scripts.sur1.bindings.consentdoor.ConsentDoor` declares the same member -- so
        that a frozen dataclass satisfies it. A mutable attribute satisfies it too, so nothing
        that already exists is excluded.
        """

    def state(self) -> str: ...

    def quiesce(self) -> str: ...

    def resume(self) -> str: ...

    def probe(self) -> Probe: ...


@dataclass(frozen=True, slots=True)
class ComposeWorkerControl:
    """The local stack's worker, controlled through compose and verified by reading it back.

    ``docker compose stop`` and ``docker compose up --wait`` are both synchronous: the first
    returns when the container has stopped, the second when the service's healthcheck passes.
    Neither is trusted on its own -- each is followed by :meth:`state`, because the fact that
    matters is what the service *is*, not what a command said it did.
    """

    project: str = "promisepatch"
    service: str = "worker"
    root: Path = ROOT
    timeout: float = 180.0
    binding_kind: str = REAL

    def identity(self) -> dict[str, Any]:
        return {"control": "compose", "project": self.project, "service": self.service}

    def state(self) -> str:
        """What compose says this service is, right now.

        ``--format json`` rather than parsing the table, and ``--all`` so a stopped container
        is reported as stopped instead of vanishing from the listing -- which is the single
        distinction this whole module turns on.
        """
        completed = self._compose("ps", "--all", "--format", "json", self.service)
        rows = _rows(completed.stdout)
        if not rows:
            return ABSENT
        state = str(rows[-1].get("State", "")).lower()
        return RUNNING if state == RUNNING else STOPPED

    def quiesce(self) -> str:
        """Stop the worker, and refuse to carry on unless it is actually stopped."""
        if self.state() == ABSENT:
            raise PreparationError(
                f"compose knows no {self.service!r} service in project {self.project!r}, so "
                "the durable worker cannot be put down before a fixture load; an install run "
                "beside a live worker deadlocks on the TRUNCATE"
            )
        self._compose("stop", self.service)
        state = self.state()
        if state == RUNNING:
            raise PreparationError(
                f"the {self.service!r} container is still running after being asked to stop; "
                "installing a world now would race it for the tables the fixture load empties"
            )
        return f"worker:{STOPPED}"

    def resume(self) -> str:
        """Bring the worker back and wait on its healthcheck, not on a clock."""
        self._compose("up", "--detach", "--wait", "--no-recreate", self.service)
        state = self.state()
        if state != RUNNING:
            raise PreparationError(
                f"the {self.service!r} container is {state} after being asked to start; arms "
                "that work through PromisePatch would be driven at a system whose durable work "
                "never runs"
            )
        return f"worker:{RUNNING}"

    def probe(self) -> Probe:
        """Can this control observe the worker at all? Asked by the preflight, writes nothing."""
        try:
            state = self.state()
        except Exception as failure:
            return Probe("WORKER", False, f"{type(failure).__name__}: {failure}")
        if state == ABSENT:
            return Probe(
                "WORKER",
                False,
                f"compose knows no {self.service!r} service in project {self.project!r}",
            )
        return Probe("WORKER", True, f"{self.service} is {state} and can be stopped and started")

    def _compose(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["docker", "compose", "--project-name", self.project, *arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise PreparationError(
                f"docker compose {' '.join(arguments)} exited {completed.returncode}: "
                f"{completed.stderr.strip()[:400]}"
            )
        return completed


def _rows(stdout: str) -> list[dict[str, Any]]:
    """Compose's service listing, whichever of its two JSON shapes this version emits.

    Older releases print one array; newer ones print one object per line. Both are read rather
    than one being assumed, because guessing wrong reports a running worker as absent -- and
    this module's whole job is telling those two apart.
    """
    text = stdout.strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip().startswith("{")]
    if isinstance(loaded, dict):
        return [loaded]
    return [row for row in loaded if isinstance(row, dict)]


@dataclass(frozen=True, slots=True)
class InstallationLifecycle:
    """Quiesce, install, verify, resume -- in that order, every time, for every attempt.

    Holds the control and the database rather than the installer: what an install *is* belongs
    to :mod:`~scripts.sur1.bindings.realisation`, and a lifecycle that knew would be a second
    place the install could change.
    """

    worker: WorkerControl
    database: DatabaseReader

    def around(self, scenario_id: str, install: Callable[[], T]) -> T:
        """Run one install with the worker down, and hand the worker back afterwards."""
        self.worker.quiesce()
        try:
            installed = install()
            self.verify(scenario_id)
        except BaseException as failure:
            self._resume_beside(failure)
            raise
        self.worker.resume()
        return installed

    def verify(self, scenario_id: str) -> str:
        """Read the product's own statement of which world is loaded, and require this one.

        ``fixture_state`` is written inside the governed fixture load's own transaction, so a
        row naming this scenario is the load's own evidence that it committed. A load that was
        refused -- by a governance trigger, by a privilege, by a deadlock -- leaves the previous
        row, and this is where that is caught instead of being measured.
        """
        expected = f"{FIXTURE_PREFIX}{scenario_id}"
        try:
            rows = self.database.rows(
                "WORLD", "SELECT fixture_name, fixture_digest FROM fixture_state"
            )
        except ReceiverUnreadableError as failure:
            raise PreparationError(
                f"{scenario_id}'s installed world could not be read back: {failure.detail}"
            ) from failure
        if not rows:
            raise PreparationError(
                f"{scenario_id}'s world was installed and the database holds no fixture_state "
                "row; nothing says which world an arm would be driven at"
            )
        name = str(rows[-1][0])
        if name != expected:
            raise PreparationError(
                f"{scenario_id}'s world was installed and fixture_state names {name!r} rather "
                f"than {expected!r}; the world an arm would act on is not the one prepared"
            )
        return f"verified:{name}"

    def _resume_beside(self, failure: BaseException) -> None:
        """Hand the worker back after a failed install, without hiding why it failed."""
        try:
            self.worker.resume()
        except Exception as second:
            failure.add_note(f"the worker could not be restarted afterwards: {second}")


@dataclass(frozen=True, slots=True)
class UncontrolledWorker:
    """A stand-in for a run that does not control a worker, and says so when asked.

    Unit tests and anything driven with no live stack get this. It is **not** real, which is
    how :func:`~scripts.sur1.preflight.worker_lifecycle` refuses it for a scored run -- the same
    way a stand-in model and a stand-in consent door are refused, by declared kind rather than
    by shape.
    """

    binding_kind: str = "stand-in"

    def state(self) -> str:
        return ABSENT

    def quiesce(self) -> str:
        return "worker:uncontrolled"

    def resume(self) -> str:
        return "worker:uncontrolled"

    def probe(self) -> Probe:
        return Probe("WORKER", False, "this run controls no durable worker")


__all__ = [
    "ABSENT",
    "FIXTURE_PREFIX",
    "RUNNING",
    "STOPPED",
    "ComposeWorkerControl",
    "InstallationLifecycle",
    "UncontrolledWorker",
    "WorkerControl",
]
