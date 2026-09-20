"""The product's own durable worker, run inside the harness process for arms B and C.

**Why this exists.** Arm C is PromisePatch with revalidation check 5 dropped, removed by
rebinding ``promisepatch.domain.revalidation.revalidate`` at the benchmark boundary. The
rebinding happens in the harness process; on every topology this benchmark has run on, the
evaluator that decides ran in the ``worker`` container. ``diagnostics.ablation`` is empty on all
seventeen ablation captures across two scored runs: **arm C has been arm B by construction**,
which is unmeasurable rather than unmeasured. See ``docs/sur1-v3-forensic-audit.md`` §5 and
[ADR-0020](../../../docs/adr/0020-a-scored-benchmark-hosts-the-product-s-own-worker.md).

**What this is not.** It is not a second worker, not a benchmark mode of the product, and not a
reimplementation of the loop. :func:`promisepatch.worker.built` wires the worker and
:meth:`promisepatch.worker.Worker.run_forever` drives it -- the same claim, lease and fence
protocol, the same effect adapters, the same semantic provider resolution, reached through the
same settings any deployment reads. Nothing under ``apps/`` or ``packages/`` knows this module
exists, and the frozen contract's *no deployed process can reach the wrapper* stays literally
true: for the length of a scored run there is no deployed worker.

**What it deliberately does not wire.** The deployment's ``_DemoCaseKeeper``, which lives in the
``worker`` entrypoint's :func:`~promisepatch.worker.run` rather than in the worker, and which
opened a case inside every installed world on all 27 attempts of the third scored run. A hosted
worker cannot do that because it never calls it.

**Both arms, or neither.** Arms B and C hold one ``PromisePatchArm`` and therefore one world and
one worker control. There is no parameter by which they could reach different workers, which is
what keeps the topology change arm-blind between them.

**Quiescence is a read, not a sleep.** The loop's own ``when_idle`` hook -- the production hook
the deployment uses for its demo keeper -- marks a cycle that found nothing to do, and a mark is
only taken when no semantic preparation is outstanding beside the loop. :meth:`await_quiescence`
waits for two fresh marks, so a caller that returns from it is not guessing that the work
finished.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from scripts.sur1.bindings import REAL, Probe
from scripts.sur1.bindings.lifecycle import (
    ABSENT,
    RUNNING,
    STOPPED,
    ComposeWorkerControl,
)
from scripts.sur1.bindings.receivers import DatabaseReader
from scripts.sur1.bindings.setup import PreparationError

DURABLE_EVALUATOR_MODULE: Final = "promisepatch.domain.revalidation"
"""The module whose ``revalidate`` binding the durable step resolves, and arm C rebinds."""

REVALIDATION_CHECK_EVENT: Final = "REVALIDATION_CHECK"
"""The product's own governed audit row, one per check, written inside the deciding transaction.

``promisepatch.domain.revalidation._record_checks`` writes it with the check's index and name in
``provenance`` and the worker identity in both ``actor_id`` and ``provenance.worker``. It is the
product's append-only ledger rather than the harness's log, which is what makes it evidence that
arm C was ablated and arm B was not.
"""

START_TIMEOUT: Final = 30.0
STOP_TIMEOUT: Final = 60.0
QUIESCENCE_TIMEOUT: Final = 120.0
"""Ceilings, in seconds, on waits that are otherwise driven by a real signal.

Each one exists so a wedged worker ends one attempt rather than hanging a run. Reaching one is
a refusal with a name, never a silent continue.
"""

QUIESCENT_MARKS: Final = 2
"""Idle cycles with nothing deferred, after the caller started waiting, before work is settled.

One would be enough if a cycle and an enqueue could not interleave. Two costs an idle interval
and removes the interleaving.
"""


class HostedWorkerError(RuntimeError):
    """The hosted worker could not be put where a measurement needs it."""


class HarnessCompetitionError(HostedWorkerError):
    """A second worker could execute the work this measurement attributes to one arm."""


@dataclass(frozen=True, slots=True)
class RevalidationWitness:
    """One ``REVALIDATION_CHECK`` row, as the ablation proof reads it back."""

    check: int
    name: str
    worker: str

    @property
    def ablated(self) -> bool:
        """Whether this row is arm C's mark rather than the evaluator's own check name."""
        from scripts.sur1.ablation import ABLATED_MARK

        return self.name == ABLATED_MARK

    def as_payload(self) -> dict[str, Any]:
        return {"check": self.check, "name": self.name, "worker": self.worker}


@dataclass(slots=True)
class _Loop:
    """One life of the hosted worker: a thread, an event loop, and what it reported."""

    thread: threading.Thread | None = None
    loop: asyncio.AbstractEventLoop | None = None
    stop: asyncio.Event | None = None
    """Created on the worker's own loop, because that is the only loop allowed to set it."""

    identity: str = ""
    started: threading.Event = field(default_factory=threading.Event)
    failure: BaseException | None = None
    idle_marks: int = 0
    """Incremented from the worker thread, read from the harness thread.

    A monotonically increasing integer written by exactly one thread and read by exactly one
    other. No lock: a reader that sees a stale value waits one more interval, which is the
    conservative direction, and there is no value it could read that never existed.
    """


@dataclass(slots=True)
class HostedWorkerControl:
    """The durable worker, hosted here, controlled by the seam a container worker used.

    Satisfies :class:`~scripts.sur1.bindings.lifecycle.WorkerControl`, so the installation
    lifecycle, the preflight and the run manifest reach it exactly as they reached
    :class:`~scripts.sur1.bindings.lifecycle.ComposeWorkerControl`. Nothing above this object
    learns that the topology changed; what changes is the answer to
    :meth:`evaluates_in_process`.
    """

    database: DatabaseReader
    compose: ComposeWorkerControl | None = None
    """The container worker, held only so it can be proved to be down. Never started by this.

    A second worker would claim benchmark steps and execute them **without** arm C's wrapper,
    and the ablation would silently cover a fraction of an attempt that no artefact could
    recover. So the competing worker is checked rather than assumed absent.
    """

    binding_kind: str = REAL
    start_timeout: float = START_TIMEOUT
    stop_timeout: float = STOP_TIMEOUT
    quiescence_timeout: float = QUIESCENCE_TIMEOUT

    _life: _Loop | None = field(default=None, init=False, repr=False)
    _evaluator_module: Any = field(default=None, init=False, repr=False)
    _lives: int = field(default=0, init=False, repr=False)

    # ------------------------------------------------------------------ WorkerControl

    def identity(self) -> dict[str, Any]:
        return {
            "control": "hosted",
            "process": "harness",
            "worker_identity": self.worker_identity(),
            "lives": self._lives,
        }

    def state(self) -> str:
        """``running`` while a hosted loop is alive, ``stopped`` otherwise. Never ``absent``.

        A hosted worker is never *absent*: this process can always start one. ``ABSENT`` is
        reserved for a control that has no worker to command, which is what
        :class:`~scripts.sur1.bindings.lifecycle.UncontrolledWorker` reports.
        """
        life = self._life
        if life is None or life.thread is None or not life.thread.is_alive():
            return STOPPED
        return RUNNING

    def quiesce(self) -> str:
        """Stop the loop and wait for the process to have stopped, not for a command to return.

        Exiting :func:`promisepatch.worker.built` is the point rather than a tidy-up: it awaits
        every deferred preparation, closes the order-system client and disposes the database
        engine. A pool still holding connections would sit in the way of the ``TRUNCATE`` the
        fixture load is about to issue, which is the deadlock this whole lifecycle exists to
        remove.
        """
        life = self._life
        if life is None or life.thread is None:
            self._life = None
            return f"hosted-worker:{STOPPED}"
        loop, stop = life.loop, life.stop
        if loop is not None and stop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop.set)
        life.thread.join(timeout=self.stop_timeout)
        if life.thread.is_alive():
            raise PreparationError(
                "the hosted worker did not stop within "
                f"{self.stop_timeout:.0f}s; installing a world now would race its connections "
                "for the tables the fixture load empties"
            )
        self._life = None
        if life.failure is not None:
            raise PreparationError(
                f"the hosted worker stopped on {type(life.failure).__name__}: {life.failure}"
            )
        return f"hosted-worker:{STOPPED}"

    def resume(self) -> str:
        """Start a fresh hosted worker, and refuse if a container worker could compete with it.

        Fresh rather than resumed: :meth:`quiesce` left the previous life's database engine
        disposed, and a worker is stateless by design -- everything it was doing is a row and
        every claim it held has expired or was completed before the loop returned. A new
        identity per life is the product's own behaviour on every restart.
        """
        self.require_no_competing_worker()
        if self.state() == RUNNING:
            return f"hosted-worker:{RUNNING}"

        life = _Loop()
        life.thread = threading.Thread(
            target=self._serve,
            args=(life,),
            name=f"sur1-hosted-worker-{self._lives + 1}",
            daemon=True,
        )
        self._life = life
        self._lives += 1
        life.thread.start()
        if not life.started.wait(timeout=self.start_timeout):
            raise PreparationError(
                f"the hosted worker did not report started within {self.start_timeout:.0f}s; "
                "arms that work through PromisePatch would be driven at a system whose durable "
                "work never runs"
            )
        if life.failure is not None:
            raise PreparationError(
                f"the hosted worker could not start: {type(life.failure).__name__}: {life.failure}"
            )
        return f"hosted-worker:{RUNNING}"

    def probe(self) -> Probe:
        """Can this control run a worker here at all, and is the container one out of the way?"""
        try:
            self.require_no_competing_worker()
        except HarnessCompetitionError as competing:
            return Probe("WORKER", False, str(competing))
        except Exception as failure:
            return Probe("WORKER", False, f"{type(failure).__name__}: {failure}")
        try:
            import promisepatch.worker as product_worker
        except Exception as failure:
            return Probe(
                "WORKER",
                False,
                f"the product's worker could not be imported here: "
                f"{type(failure).__name__}: {failure}",
            )
        if not hasattr(product_worker, "built"):
            return Probe("WORKER", False, "promisepatch.worker publishes no built() wiring")
        return Probe(
            "WORKER",
            True,
            f"the product's own worker runs in this process and is {self.state()}",
        )

    def runtime_identity(self) -> Mapping[str, Any]:
        """What **this** process is configured to do, computed by the product's own module.

        Not a copy of the container's answer and not a description the harness maintains: the
        same :func:`promisepatch.runtime_identity.runtime_identity` the ``pp runtime-identity``
        command prints, given the settings this hosted worker was built from. A run that
        validated a stopped container while another process performed the semantics is exactly
        what this replaces.
        """
        try:
            from promisepatch.config import LlmProvider, get_settings
            from promisepatch.runtime_identity import runtime_identity
        except Exception:
            return {}
        settings = get_settings()
        resolves = _credential_resolves() if settings.llm_provider is LlmProvider.BEDROCK else None
        published = dict(runtime_identity(settings, credential_resolves=resolves))
        published["process"] = "hosted-worker"
        return published

    def evaluates_in_process(self) -> bool:
        """Whether arm C's rebinding reaches the process that decides revalidation.

        Proved twice rather than returned as a constant.

        **The name is reachable.** The wrapper is installed over
        ``promisepatch.domain.revalidation.revalidate`` and the binding the durable step resolves
        is read back; it has to be the wrapper's own module. That is the same operation arm C
        performs, taken here as a question instead of as an effect, and it is restored on the
        way out.

        **The worker is here.** A hosted loop must have been built in this process against the
        same module object the wrapper rebinds. A control that has never started a worker cannot
        claim the evaluator runs in this one.
        """
        import importlib

        from scripts.sur1 import ablation as wrapper

        if self._evaluator_module is None:
            return False
        if importlib.import_module(DURABLE_EVALUATOR_MODULE) is not self._evaluator_module:
            return False
        try:
            with wrapper.ablation():
                installed = wrapper.installed_evaluator()
        except Exception:
            return False
        return getattr(installed, "__module__", "") == wrapper.__name__

    # ------------------------------------------------------------------ sole executor

    def require_no_competing_worker(self) -> None:
        """Refuse while a container worker could claim a step this measurement depends on."""
        if self.compose is None:
            return
        try:
            state = self.compose.state()
        except Exception as failure:
            raise HarnessCompetitionError(
                "whether the containerised worker is running could not be established "
                f"({type(failure).__name__}: {failure}); a second worker would execute "
                "benchmark work without arm C's wrapper"
            ) from failure
        if state == RUNNING:
            raise HarnessCompetitionError(
                f"the {self.compose.service!r} container is running; it would claim benchmark "
                "steps and execute them without arm C's wrapper, so part of every ablated "
                "attempt would silently be arm B. Stop it before a scored run"
            )

    def competing_worker_state(self) -> str:
        """What the container worker is, recorded so a restart during a run is detectable."""
        if self.compose is None:
            return ABSENT
        try:
            return self.compose.state()
        except Exception:
            return "unknown"

    def worker_identity(self) -> str:
        """The lease owner the hosted worker writes onto everything it claims, or empty."""
        life = self._life
        return "" if life is None else life.identity

    def executed_only_by_the_hosted_worker(self, since: datetime) -> tuple[str, ...]:
        """Every worker identity other than this one that did governed work since ``since``.

        Read out of the product's own append-only audit ledger, which records the actor of every
        governed write. An empty tuple is the sole-executor proof; anything in it is a second
        process that executed part of an attempt, and the attempt is not a reading of either arm.
        """
        mine = self.worker_identity()
        rows = self.database.rows(
            "WORKER",
            "SELECT DISTINCT actor_id FROM audit_events "
            f"WHERE actor_kind = 'SYSTEM' AND occurred_at >= '{_stamp(since)}'::timestamptz",
        )
        return tuple(
            sorted(str(row[0]) for row in rows if row[0] is not None and str(row[0]) != mine)
        )

    def revalidation_witnesses(self, since: datetime) -> tuple[RevalidationWitness, ...]:
        """The product's own record of which checks ran, in order, since ``since``.

        This is the treatment evidence. Arm B's check 5 row carries the evaluator's own name;
        arm C's carries the ablation mark, because the wrapper replaced the check in the tuple
        the ledger is written from. Neither arm can produce the other's rows without the wrapper
        having reached the deciding process, which is the whole question ADR-0020 answers.
        """
        rows = self.database.rows(
            "WORKER",
            "SELECT provenance ->> 'check', provenance ->> 'name', provenance ->> 'worker' "
            "FROM audit_events "
            f"WHERE type = '{REVALIDATION_CHECK_EVENT}' "
            f"AND occurred_at >= '{_stamp(since)}'::timestamptz ORDER BY seq",
        )
        witnesses = []
        for check, name, worker in rows:
            try:
                index = int(str(check))
            except (TypeError, ValueError):
                continue
            witnesses.append(
                RevalidationWitness(check=index, name=str(name or ""), worker=str(worker or ""))
            )
        return tuple(witnesses)

    # ------------------------------------------------------------------ quiescence

    def await_quiescence(self, timeout: float | None = None) -> str:
        """Wait until the hosted worker has nothing outstanding, or say that it never did.

        Called while arm C's wrapper is still installed, which is the point: a wrapper taken out
        while the worker was mid-attempt would ablate a prefix of the work and the capture would
        not say so. Arms B and C both wait, identically, so the wait cannot become a difference
        between them.

        Returns a sentence for the record rather than raising on a timeout. An attempt whose
        durable work never settled is a reading about that attempt -- the receivers are still
        read, and what is there is what the arm achieved -- and ending the run over it would
        lose eight other scenarios.
        """
        ceiling = self.quiescence_timeout if timeout is None else timeout
        life = self._life
        if life is None or life.thread is None:
            return "quiescent: no hosted worker is running"
        start = life.idle_marks
        deadline = time.monotonic() + ceiling
        while time.monotonic() < deadline:
            if not life.thread.is_alive():
                return "quiescent: the hosted worker stopped"
            if life.idle_marks - start >= QUIESCENT_MARKS:
                return f"quiescent after {life.idle_marks - start} idle cycles"
            time.sleep(0.05)
        return f"not quiescent within {ceiling:.0f}s; the receivers are read as the world stands"

    # ------------------------------------------------------------------ the thread

    def _serve(self, life: _Loop) -> None:
        """One hosted life, start to finish, on its own event loop in its own thread."""
        try:
            asyncio.run(self._run(life))
        except BaseException as failure:  # recorded, never swallowed; quiesce re-raises it
            life.failure = failure
        finally:
            life.started.set()

    async def _run(self, life: _Loop) -> None:
        """Build the product's worker exactly as its entrypoint does, and run its loop."""
        import importlib

        from promisepatch.config import get_settings
        from promisepatch.worker import built

        life.loop = asyncio.get_running_loop()
        life.stop = asyncio.Event()
        # Imported rather than looked up in ``sys.modules``. The worker reaches the evaluator
        # lazily, through a handler, so at the moment a life starts the module may not have been
        # imported by anything -- and a lookup that found nothing left the control unable to say
        # the wrapper reaches the deciding name while a worker was running in this very process.
        # Found by starting one; no unit test could have, because no unit test starts a worker.
        self._evaluator_module = importlib.import_module(DURABLE_EVALUATOR_MODULE)

        async def mark_idle() -> None:
            """The loop's own idle hook, used to observe quiescence and to do nothing else.

            A mark is taken only when nothing is deferred beside the loop, because an idle cycle
            with an outstanding semantic preparation is not a settled attempt.
            """
            if worker.deferred == 0:
                life.idle_marks += 1

        async with built(get_settings()) as worker:
            life.identity = worker.identity.value
            life.started.set()
            await worker.run_forever(life.stop, when_idle=mark_idle)


def _stamp(moment: datetime) -> str:
    """One instant as SQL sees it. ISO-8601, which PostgreSQL parses without a format string."""
    return moment.isoformat()


def _credential_resolves() -> bool:
    """Whether the AWS SDK can resolve an identity in this process. A boolean, never a value.

    The same question ``pp runtime-identity`` asks inside a container, asked here because here
    is where the semantic job would run. It makes no Bedrock call: a process that answered this
    by invoking a model would spend money to report its own configuration.
    """
    try:
        import boto3

        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


__all__ = [
    "DURABLE_EVALUATOR_MODULE",
    "QUIESCENT_MARKS",
    "REVALIDATION_CHECK_EVENT",
    "HarnessCompetitionError",
    "HostedWorkerControl",
    "HostedWorkerError",
    "RevalidationWitness",
]
