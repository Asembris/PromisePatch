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
   a stopped worker would measure a system with no engine. It comes back **without its
   dependencies**: compose satisfies the worker's ``depends_on`` by re-running ``seed``, which
   is ``pp reset-demo-state``, and a resume that did that would undo steps 2 and 3 immediately
   after step 3 had confirmed them. See :meth:`ComposeWorkerControl.resume`.

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
from collections.abc import Callable, Mapping, Sequence
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

QUIET_TABLES: Final = (
    "cases",
    "exceptions",
    "exception_facts",
    "exception_clarifications",
    "approval_requests",
    "plan_approvals",
    "outbox_messages",
    "inbound_replies",
)
"""Tables an installed world leaves alone and only a case's own work writes into.

Counted rather than required empty. The fingerprint compares a count with the one the install
left behind, so a world program that legitimately wrote one of these is compared against itself;
what refuses is a row appearing while no arm is acting.
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

    def runtime_identity(self) -> Mapping[str, Any]:
        """What the worker process says it is configured to do, read out of that process.

        Not out of a compose file, not out of an environment this one happens to carry, and not
        out of a copy of its configuration the harness would have to keep. The three scored runs
        were driven at a worker holding no provider configuration at all, and nothing anywhere
        asked -- ``run.json`` recorded ``model_provider_configured`` from the *harness* process.
        See ``docs/sur1-v3-forensic-audit.md`` section 3.
        """

    def evaluates_in_process(self) -> bool:
        """Whether the process that decides revalidation is this one.

        Arm C removes revalidation check 5 by rebinding
        ``promisepatch.domain.revalidation.revalidate`` *in the harness process*. When the
        durable worker is a separate process, that rebinding reaches nothing and arm C is arm B
        by construction -- which is what all 17 ablation captures across two scored runs show,
        with an empty ablation log every time. See section 5 of the same record.
        """


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
        """Bring the worker back and wait on its healthcheck, not on a clock.

        ``--no-deps`` is load-bearing and is the whole reason this method is not one line
        shorter. The worker declares ``depends_on: seed: service_completed_successfully``, and
        compose satisfies that by **re-running** ``seed`` -- which is ``pp reset-demo-state``.
        Without the flag, handing the worker back destroys the world quiesce and install had
        just put in place and :meth:`InstallationLifecycle.verify` had just confirmed, and every
        attempt is driven at the canonical demo fixture instead of at the scenario's world. The
        dependency is not being bootstrapped here: the stack is already up and this is a service
        that was stopped seconds ago by :meth:`quiesce`.

        Nothing is weakened by skipping it. ``--wait`` still blocks on the worker's own
        healthcheck, that healthcheck is a real query against the database, and :meth:`state`
        reads the service back afterwards -- so a worker that could not come up is still caught
        here rather than assumed.
        """
        self._compose("up", "--detach", "--wait", "--no-deps", "--no-recreate", self.service)
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

    def runtime_identity(self) -> Mapping[str, Any]:
        """``pp runtime-identity``, run inside the worker container itself.

        ``exec`` rather than ``run``: the question is what *this* container is configured for,
        and a fresh one started from the same image would answer for a process that is not the
        one doing the work. ``-T`` because there is no terminal here.

        A container that cannot answer returns an empty mapping rather than raising, so the
        preflight reports "this worker publishes no identity" as the refusal it is instead of
        turning it into an exception somewhere up the stack.
        """
        return ComposeStack(project=self.project, root=self.root, timeout=self.timeout).identity(
            self.service
        )

    def evaluates_in_process(self) -> bool:
        """No: the durable worker is a container, and this harness is not inside it."""
        return False

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
class ComposeStack:
    """The other containers of the local stack, read and never started, stopped or changed.

    Two questions, both of which a scored run has to be able to answer about processes it does
    not control. **What is this service running and configured for**, asked of the service
    itself through ``pp runtime-identity`` rather than of a compose file, because a file says
    what a container was created with and a running process says what it holds. And **where is
    this service published**, asked of compose's own port map, because a harness that guessed
    the port reached nothing: ``docker/env/host.env`` named ``58100`` while this machine
    publishes ``48100``, and a host process would have pushed every governed amendment into
    a closed socket.

    Nothing here mutates. ``exec`` runs a read-only command in a container that is already up;
    ``port`` is a lookup. A service that is down, absent or cannot answer yields nothing, and
    the preflight turns that into a named refusal rather than an exception.
    """

    project: str = "promisepatch"
    root: Path = ROOT
    timeout: float = 60.0
    binding_kind: str = REAL

    def identity(self, service: str) -> Mapping[str, Any]:
        """What ``service`` says it is running and is configured to do, or nothing.

        Every failure is one answer -- *this service said nothing* -- because from a scored
        run's point of view a container that is down, a compose that refused and a machine with
        no ``docker`` on its path are the same fact: the stack cannot be shown to match. The
        preflight turns that into a named refusal, which is the only place it should become one.
        """
        try:
            completed = self._compose("exec", "-T", service, "pp", "runtime-identity")
        except Exception:
            return {}
        for line in reversed(completed.stdout.splitlines()):
            body = line.strip()
            if not body.startswith("{"):
                continue
            try:
                published = json.loads(body)
            except json.JSONDecodeError:
                continue
            if isinstance(published, dict):
                return published
        return {}

    def identities(self, services: Sequence[str]) -> dict[str, Mapping[str, Any]]:
        """One identity per named service, in order, including the ones that said nothing."""
        return {service: self.identity(service) for service in services}

    def published_port(self, service: str, container_port: int) -> str:
        """The host port ``service``'s ``container_port`` is published on, as compose knows it.

        Compose answers ``127.0.0.1:48100``; only the port is returned, because the host half
        is the loopback address the harness already only ever names. An unpublished service, an
        absent one and a compose that refused all return the empty string, which every caller
        reads as *this could not be established* rather than as a port.
        """
        try:
            completed = self._compose("port", service, str(container_port))
        except Exception:
            return ""
        answer = completed.stdout.strip().splitlines()
        if not answer:
            return ""
        _, _, port = answer[-1].strip().rpartition(":")
        return port if port.isdigit() else ""

    def probe(self) -> Probe:
        """Whether compose can be asked about this stack at all. Reads, and writes nothing."""
        try:
            self._compose("ps", "--all", "--format", "json")
        except Exception as failure:
            return Probe("STACK", False, f"{type(failure).__name__}: {failure}")
        return Probe("STACK", True, f"compose answers for project {self.project!r}")

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
        """Run one install with the worker down, and hand the worker back afterwards.

        **The world is read twice: once when the install says it is done, and once after the
        worker is back.** Verifying before ``resume`` and never again is what let all 27 attempts
        of the third scored run be driven at a contaminated world. The worker's own start-up
        provisioning opened a case inside the freshly installed world and attested today's
        raspberry line ``NOT_RECEIVED`` before any arm reported anything, and nothing re-read the
        world after that. See ``docs/sur1-v3-forensic-audit.md`` section 2.

        The second read is a comparison rather than a rule about what a world may contain. The
        fingerprint is taken of the world the install produced, whatever that is, and any
        difference after ``resume`` is an undeclared mutation that refuses the attempt. A rule
        naming which tables must be empty would have to know what every world program writes;
        this only has to know that nothing should be writing while no arm is acting.
        """
        self.worker.quiesce()
        try:
            installed = install()
            self.verify(scenario_id)
            installed_world = self.fingerprint()
        except BaseException as failure:
            self._resume_beside(failure)
            raise
        self.worker.resume()
        self.require_untouched(scenario_id, installed_world)
        return installed

    def fingerprint(self) -> dict[str, Any]:
        """Everything about the installed world an arm's reading depends on, as plain values.

        Counts for the tables only a case's own work writes into, and the ordered states of the
        two a world program legitimately writes. Small enough to read twice per attempt and
        specific enough that the contamination which lost the last run -- one case row, one
        exception row, one attested fact -- moves it.
        """
        counts = {
            table: int(self.database.rows("WORLD", f"SELECT count(*) FROM {table}")[0][0])
            for table in QUIET_TABLES
        }
        return {
            "fixture_state": [
                tuple(str(column) for column in row)
                for row in self.database.rows(
                    "WORLD", "SELECT fixture_name, fixture_digest FROM fixture_state"
                )
            ],
            "counts": counts,
            "commitment_lines": [
                (str(identifier), str(state))
                for identifier, state in self.database.rows(
                    "WORLD", "SELECT id, state FROM commitment_lines ORDER BY id"
                )
            ],
            "production_tasks": [
                (str(identifier), str(state), "" if holder is None else str(holder))
                for identifier, state, holder in self.database.rows(
                    "WORLD",
                    "SELECT id, state, held_by_case_id FROM production_tasks ORDER BY id",
                )
            ],
        }

    def require_untouched(self, scenario_id: str, installed: Mapping[str, Any]) -> None:
        """Refuse an attempt whose world changed between the install and the arm acting."""
        try:
            now = self.fingerprint()
        except ReceiverUnreadableError as failure:
            raise PreparationError(
                f"{scenario_id}'s world could not be re-read after the worker came back: "
                f"{failure.detail}"
            ) from failure
        differences = [
            f"{area} moved" for area, found in sorted(now.items()) if installed.get(area) != found
        ]
        if differences:
            raise PreparationError(
                f"{scenario_id}'s world was changed between the install and the arm acting by "
                "something that is not the install, so an attempt here would measure a world "
                "nobody declared: " + ", ".join(differences)
            )

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

    def runtime_identity(self) -> Mapping[str, Any]:
        return {}

    def evaluates_in_process(self) -> bool:
        return False


__all__ = [
    "ABSENT",
    "FIXTURE_PREFIX",
    "QUIET_TABLES",
    "RUNNING",
    "STOPPED",
    "ComposeStack",
    "ComposeWorkerControl",
    "InstallationLifecycle",
    "UncontrolledWorker",
    "WorkerControl",
]
