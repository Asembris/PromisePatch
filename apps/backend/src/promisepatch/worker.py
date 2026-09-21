"""The ``worker`` entrypoint: a stateless loop over durable work.

**Stateless** is the whole design, not a description of the implementation. The worker holds no
queue, no schedule, no in-memory list of what it was doing. Every piece of outstanding work is a
row -- a step, a timer, an inbound record, an outbound message -- and everything the process
knows is a lease it can lose. So "restart the worker" is `docker compose restart worker`, and
what happens next is that leases expire and another process picks the work up. There is nothing
to drain, nothing to hand over, and nothing to reconstruct on boot.

**Several workers are safe, and none of them coordinate.** There is no leader, no partitioning
and no lock server. Correctness comes from the database: ``FOR UPDATE SKIP LOCKED`` means two
sweeps take different rows, the lease-and-fence protocol means a slow worker cannot overwrite a
fast one, and uniqueness means a duplicate is refused rather than duplicated. This process
starts one cycle at a time because that is the simplest thing that works, not because anything
depends on it.

**One thing does not run inside the cycle, and that is the point.** A semantic step spends most
of its life waiting for somebody else's service to answer, and a cycle that waited with it was
measured holding every unrelated case up for exactly as long -- see
``docs/g8-head-of-line-measurement.md``, where the delay propagated one for one across a
five-fold range. So the model call and the transition it feeds are handed to a task beside the
loop, up to :data:`DEFERRED_SEMANTIC_LIMIT` of them, and the loop goes back to claiming. It is a
deferral and not a second worker: the claim, the lease, the fence and the execution transaction
are the same ones, taken in the same order, by the same identity. What changed is which task
waits for the provider, and nothing else.

**A hard kill is a supported outcome.** ``SIGTERM`` and ``SIGINT`` stop the loop between
cycles, which is tidier; ``SIGKILL`` mid-transaction leaves a rolled-back transaction and an
expiring lease, which is recoverable. The difference between the two is how quickly the work
resumes, never whether it can.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from promisepatch import provisioning
from promisepatch.config import Settings
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.db.uow import Actor
from promisepatch.domain import (
    inbox,
    order_mirror,
    outbox,
    semantic_intake,
    steps,
    timers,
)
from promisepatch.domain.adapters import FakeEffectAdapter, RoutedEffectAdapter
from promisepatch.domain.identity import WorkerIdentity
from promisepatch.domain.model import EFFECT_MESSAGE_SEND, EFFECT_ORDER_AMEND
from promisepatch.domain.observation import STEP_INTERPRET_SEMANTICALLY
from promisepatch.domain.order_mirror import AuthoritativeFetch
from promisepatch.domain.outbox import EffectAdapter
from promisepatch.domain.physical import bakery_day
from promisepatch.integrations import build_customer_channel, build_semantic_provider
from promisepatch.integrations.order_system import OrderSystemAdapter, OrderSystemClient
from promisepatch.observability import configure_logging, get_logger
from promisepatch.semantic import FakeSemanticProvider, SemanticProvider

type IdleHook = Callable[[], Awaitable[None]]
"""Work the loop offers a cycle that found nothing to do. Never a second task."""

logger = get_logger(__name__)

IDLE_INTERVAL: Final = 1.0
"""Seconds to wait after a cycle that found nothing to do.

Short enough that a step enqueued by an API request is picked up promptly, long enough that an
idle worker is not a continuous load on the database. A constant rather than a setting: nothing
has asked to vary it, and a variable nobody sets is a promise the code does not keep.
"""

DEFERRED_SEMANTIC_LIMIT: Final = 4
"""How many semantic preparations one process may have outstanding beside its loop.

A bound rather than a pool, and a small one. Each outstanding preparation is a provider call and
three short transactions, so four of them plus the cycle itself stay well inside the connection
pool and cannot become the reason a database runs out of handles. When they are all taken the
loop simply stops claiming semantic steps -- it does not queue them, does not fall back to
waiting for one, and does not start a fifth. The rows are left exactly where they were, which is
the only place a worker's memory is allowed to be.
"""

SEMANTIC_KINDS: Final[tuple[str, ...]] = (STEP_INTERPRET_SEMANTICALLY,)
"""The step kinds whose execution waits on a model, and which a full worker therefore skips."""

DEFERRED: Final = "DEFERRED"
"""What a cycle reports when it handed a step to a task beside itself rather than running it.

Not a :class:`~promisepatch.domain.model.StepResult`: no step reached an outcome, and calling
this one would be the loop claiming a result it has not got.
"""

INITIAL_BACKOFF: Final = 1.0
MAX_BACKOFF: Final = 30.0
"""Retreat when the database is unreachable, and keep retreating.

A worker that hammered a database that had just gone away would be part of the outage. It
backs off to half a minute and stays there, because the recovery it is waiting for is somebody
else's and will take as long as it takes.
"""


@dataclass
class Worker:
    """One process's loop. Owns an identity, a database handle and an adapter -- nothing else."""

    database: RuntimeDatabase
    adapter: EffectAdapter
    identity: WorkerIdentity = field(default_factory=WorkerIdentity.create)
    idle_interval: float = IDLE_INTERVAL
    semantic: SemanticProvider = field(default_factory=FakeSemanticProvider)
    """Where a sentence the deterministic lexicon cannot read is sent to be read.

    Injected, and the fake by default, so a worker started by a test, by CI or by
    ``docker compose up`` reaches no network and needs no credential. The fake's unscripted
    answer binds nothing, which means a deployment that forgot to configure a provider
    escalates visibly to a person instead of proceeding on invented understanding.
    """
    fetch_order: AuthoritativeFetch | None = None
    """How to read an order whole from the system that owns it, when there is one.

    Injected rather than constructed, because the module that applies an external change to the
    mirror may not open a socket: it decides what the mirror should say, and the worker supplies
    the one call that has to leave the process -- made, like every other provider call, with no
    transaction held.
    """
    deferred_limit: int = DEFERRED_SEMANTIC_LIMIT
    """How many semantic preparations this worker may have outstanding. See the constant."""

    _deferred: dict[UUID, asyncio.Task[None]] = field(default_factory=dict, init=False, repr=False)
    """The preparations running beside the loop, by case, so a case appears at most once.

    Keyed by case rather than by step because what it is used for is a claim-time exclusion: a
    cycle must not take a second step of a case this process is already working on, or the two
    would reach :func:`~promisepatch.domain.cases.lock_case` in an order nobody chose.
    """

    deferred_failures: list[BaseException] = field(default_factory=list, init=False, repr=False)
    """Everything a deferred preparation raised and the loop therefore never saw.

    Kept because swallowing it silently and swallowing it are different things. Nothing reads
    this to make a decision -- the step's own lease and retry ladder do that -- but a test can
    assert a failure happened, and an operator reading the log finds the same exception there.
    """

    @property
    def actor(self) -> Actor:
        """Every governed write this worker makes is attributed to this process by name."""
        return Actor(kind="SYSTEM", id=self.identity.value)

    @property
    def deferred(self) -> int:
        """How many semantic preparations are outstanding beside the loop right now."""
        return len(self._deferred)

    async def run_once(self) -> bool:
        """One pass over every kind of work, start to finish. ``True`` if anything was done.

        **Nothing it starts outlives it.** This is the form every caller outside the loop uses --
        provisioning, the operator commands, the tests that arm a crash point between two halves
        of a step -- and all of them are written against a cycle that has finished what it
        claimed by the time it returns. So the semantic call is made here, in this task, exactly
        where it has always been made. :meth:`run_forever` is the only caller that defers it.
        """
        return await self._cycle(defer=False)

    async def _cycle(self, *, defer: bool) -> bool:
        """One pass over every kind of work. ``defer`` says whether slow work may run beside it.

        The order is deliberate. Timers first, because a fired deadline becomes a step this same
        cycle can execute; then steps, because executing one is what enqueues effects; then
        dispatch and ingestion, which are the edges of the system. A cycle therefore carries a
        deadline all the way to an outbound attempt rather than taking four cycles to do it.

        The order system's own events are swept last and separately. Separately because applying
        one can need an authoritative read over the network, which the general inbox sweep must
        not hold a transaction across; last because an event that arrives while this cycle is
        running is picked up by the next one anyway, and the ordering it does need -- amendment
        first, echo afterwards -- is decided by durable state rather than by sweep order.
        """
        fired = await timers.fire_due_timer(self.database, worker=self.identity.value)
        stepped = await self._execute_one_step(defer=defer)
        dispatched = await outbox.dispatch_one(
            self.database, self.adapter, worker=self.identity.value, actor=self.actor
        )
        ingested = await inbox.process_one(self.database, worker=self.identity.value)
        mirrored = await order_mirror.process_one(
            self.database, worker=self.identity.value, fetch=self.fetch_order
        )
        return any(item is not None for item in (fired, stepped, dispatched, ingested, mirrored))

    async def _execute_one_step(self, *, defer: bool) -> str | None:
        claim = await steps.claim_step(
            self.database,
            worker=self.identity.value,
            # Never a second step of a case a preparation of this process is already holding,
            # and never a semantic step there is no capacity to prepare. Both are recomputed
            # here on every sweep and neither leaves the process, so a row passed over now is
            # ordinary claimable work to the next sweep and to every other worker meanwhile.
            exclude_cases=tuple(self._deferred),
            exclude_kinds=(
                () if not defer or self.deferred < self.deferred_limit else SEMANTIC_KINDS
            ),
        )
        if claim is None:
            return None
        if claim.kind == STEP_INTERPRET_SEMANTICALLY:
            if defer:
                self._defer(claim)
                return DEFERRED
            await self._prepare(claim)
        return await self._execute(claim)

    async def _prepare(self, claim: steps.StepClaim) -> None:
        """Ask the model, with a lease held and no transaction open.

        The one provider call in the step path, and it is made here rather than inside the
        execution transaction. Between the claim and the execution is the only moment when this
        process holds a lease on the work and no database transaction at all, which is exactly
        what a call to somebody else's service needs. What it leaves behind is a row; what
        decides anything is :meth:`_execute`, which takes the locks and re-reads what it is
        deciding about.

        A worker's sentence, and nothing else. Per ADR-0008 a customer's reply is never sent to
        a model: the two words that can answer are read by a parser, and the one question an
        unreadable reply earns is built from the request it is bound to.
        """
        await semantic_intake.prepare(self.database, self.semantic, claim=claim)

    async def _execute(self, claim: steps.StepClaim) -> str:
        result = await steps.execute_step(self.database, claim=claim, actor=self.actor)
        logger.info(
            "worker.step.executed",
            step_id=str(claim.step_id),
            step_key=claim.step_key,
            kind=claim.kind,
            attempt=claim.attempts,
            result=result.value,
        )
        return result.value

    def _defer(self, claim: steps.StepClaim) -> None:
        """Hand one claimed semantic step to a task beside the loop, and return immediately.

        The claim goes with it whole. The task prepares and executes under the very lease and
        fencing token this cycle wrote, so nothing about who may commit what has changed --
        a preparation that outlives its lease still fails the fence and writes nothing, exactly
        as it would have from inside the cycle.
        """
        task = asyncio.create_task(
            self._prepare_then_execute(claim), name=f"semantic:{claim.step_key}"
        )
        self._deferred[claim.case_id] = task
        logger.info(
            "worker.step.deferred",
            step_id=str(claim.step_id),
            step_key=claim.step_key,
            attempt=claim.attempts,
            outstanding=len(self._deferred),
        )

    async def _prepare_then_execute(self, claim: steps.StepClaim) -> None:
        """What the loop would have done with this step, done beside it instead.

        **Nothing escapes into the loop.** A deferred task has no cycle to abort and no caller to
        raise into, and a bug here must not be allowed to stop every unrelated case as well --
        that is the exact coupling this whole arrangement exists to remove. So the failure is
        recorded and logged, and the step is left to the machinery that already handles a worker
        that stopped in this window: the lease expires, another sweep reclaims the row as the
        next attempt, and the retry ladder ends in a terminal escalation like any other. Nothing
        is written by a task that failed here, because nothing it had written was authority.
        """
        try:
            await self._prepare(claim)
            await self._execute(claim)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # see the docstring: nothing may escape here
            self.deferred_failures.append(error)
            logger.exception(
                "worker.step.deferred_failed",
                step_id=str(claim.step_id),
                step_key=claim.step_key,
                attempt=claim.attempts,
            )
        finally:
            # In the task's own frame rather than a done callback, so that a caller which has
            # just awaited these tasks sees an empty set rather than one the loop has not been
            # round to clear yet.
            self._deferred.pop(claim.case_id, None)

    async def settle(self) -> None:
        """Wait for every preparation this worker deferred. Nothing outlives the worker.

        Called on the way out of :meth:`run_forever`, including when it is leaving because of an
        error. A process that returned here with a model call still outstanding would be telling
        its caller that a case's work was over while the task that finishes it was still running
        -- and the caller's next act is usually to close the database that task is using.
        """
        outstanding = tuple(self._deferred.values())
        if outstanding:
            await asyncio.gather(*outstanding, return_exceptions=True)

    async def run_forever(self, stop: asyncio.Event, *, when_idle: IdleHook | None = None) -> None:
        """Cycle until ``stop`` is set, backing off when the database is unreachable.

        Only :class:`~sqlalchemy.exc.SQLAlchemyError` and ``OSError`` are treated as transient.
        Anything else is a bug in a transition, and a loop that swallowed those would keep
        running while getting the same thing wrong every second.

        ``when_idle`` is awaited on a cycle that found nothing to do, before the wait. Awaited
        from this task rather than from one beside it, so whatever it does cannot run a cycle
        concurrently with this loop -- there is only ever one cycle in flight, which is the
        property every lease and every claim in the step path is written against. Deferred
        semantic preparations run beside the loop and do not weaken that: each one carries a
        claim this cycle already made, and no cycle can claim a case one of them holds.

        Everything deferred is awaited on the way out, including the way out through an error,
        so a stopped worker has stopped.
        """
        backoff = INITIAL_BACKOFF
        logger.info("worker.start", worker=self.identity.value)
        try:
            while not stop.is_set():
                try:
                    busy = await self._cycle(defer=True)
                except (SQLAlchemyError, OSError) as error:
                    logger.warning(
                        "worker.database_unavailable",
                        worker=self.identity.value,
                        backoff_seconds=backoff,
                        error=str(error),
                    )
                    await _wait(stop, backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                    continue

                backoff = INITIAL_BACKOFF
                if not busy:
                    if when_idle is not None:
                        await when_idle()
                    await _wait(stop, self.idle_interval)
        finally:
            await self.settle()
            logger.info("worker.stop", worker=self.identity.value)


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    """Sleep, but wake immediately if asked to stop. Never a bare sleep in a signalled loop."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        return


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """Ask the loop to finish its cycle, on either of the two signals a container sends.

    ``add_signal_handler`` is the correct mechanism and is unavailable on Windows, where the
    fallback is the standard-library handler. A developer running the worker locally on Windows
    should be able to stop it with Ctrl+C and see the same tidy shutdown a container gets.
    """
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signal_number, stop.set)
        except (NotImplementedError, AttributeError, ValueError):
            signal.signal(signal_number, lambda *_: stop.set())


@asynccontextmanager
async def built(settings: Settings, adapter: EffectAdapter | None = None) -> AsyncIterator[Worker]:
    """A worker wired from settings, and the order-system client it owns, closed on the way out.

    Which provider each kind of effect reaches is a deployment question, answered once here and
    nowhere else. With an order system configured, amendments go to it and the mirror is
    reconciled against what it says; with a customer channel configured, a message goes to a
    real device. Without either, the fake provider proves the outbox's own guarantees and makes
    no claim about anybody's order or anybody's phone. The recovery saga is identical in every
    case: it reads what the row says the provider did, and does not know which one answered.

    **The customer channel is built first, before anything this function would have to close.**
    A deployment that selected a real transport and configured no credential fails here, on the
    way up, with the variable's name -- rather than starting, marking approval requests sent,
    and leaving tracks waiting on answers nobody was ever asked for.

    Extracted from :func:`run` so that anything else needing worker cycles -- today, ``pp
    ensure-demo-case`` -- drives *this* wiring rather than a second copy of it that could
    quietly reach a different provider.
    """
    customer_channel = build_customer_channel(settings)
    database = RuntimeDatabase.from_settings(settings)
    client = (
        OrderSystemClient(
            base_url=settings.require_order_system_base_url(),
            timeout=settings.order_system_timeout_seconds,
        )
        if settings.order_system_configured
        else None
    )
    if adapter is None:
        routes: dict[str, EffectAdapter] = {}
        if client is not None:
            routes[EFFECT_ORDER_AMEND] = OrderSystemAdapter(client)
        if customer_channel is not None:
            routes[EFFECT_MESSAGE_SEND] = customer_channel
        adapter = (
            RoutedEffectAdapter(routes=routes, default=FakeEffectAdapter())
            if routes
            else FakeEffectAdapter()
        )
    try:
        yield Worker(
            database=database,
            adapter=adapter,
            # One place reads `PP_LLM_PROVIDER`, and it is not here: the worker asks for whatever
            # this deployment configured and cannot behave differently depending on the answer.
            semantic=build_semantic_provider(settings),
            fetch_order=None if client is None else client.fetch_order,
        )
    finally:
        if client is not None:
            await client.aclose()
        if customer_channel is not None:
            await customer_channel.aclose()
        await database.dispose()


async def run(settings: Settings, adapter: EffectAdapter | None = None) -> None:
    """Build a worker from settings and run it until it is asked to stop.

    The connection is ``PP_DATABASE_URL`` -- ``promisepatch_app``, the same least-privileged
    role the API uses. A worker holds no migration credential and can no more disable a trigger
    or rewrite a ledger than a request handler can.
    """
    configure_logging(settings)
    stop = asyncio.Event()
    _install_signal_handlers(stop)

    async with built(settings, adapter) as worker:
        keeper = _DemoCaseKeeper(worker, settings)
        await keeper.check()
        await worker.run_forever(stop, when_idle=keeper.check_if_the_day_turned)


@dataclass(slots=True)
class _DemoCaseKeeper:
    """Keeps a deployment that offers the judge entry pointed at a case worth landing on.

    Here rather than in a compose service because the deployed composition has 44 bytes of
    headroom against its SSM cap, and here rather than in the seed because the seed is the
    destructive path. It runs before the loop so the case is there by the time anything can look
    at it, **and once more on the first idle cycle of each new bakery day**, which is the half
    that makes this more than a boot-time convenience: a seed is good for the rest of its own
    bakery day and no longer, and a host that is never restarted would otherwise serve the
    bootstrap day's world for ever.

    The day is the gate, not a timer, for two reasons. It is the same notion of *today* the
    interpreter narrows the canonical report against, so the check happens exactly when the
    thing it checks for can have changed; and it is free, because reading the clock costs
    nothing and the database is not touched at all on the other ninety-nine per cent of idle
    cycles.
    """

    worker: Worker
    settings: Settings
    checked_day: datetime | None = None

    async def check_if_the_day_turned(self) -> None:
        if self.checked_day == bakery_day(datetime.now(UTC))[0]:
            return
        await self.check()

    async def check(self) -> None:
        """**Nothing it can do may stop the worker starting, or keep it from cycling.**

        A provisioning failure costs a judge a case to read, which the screen already has a
        truthful sentence for; a worker that failed to start costs the deployment every case
        anybody opens afterwards. So the exception handler is deliberately as broad as the
        difference between those two outcomes, and the day is marked as checked either way --
        a failure that repeated every idle cycle would be the worse of the two failures again.
        """
        self.checked_day = bakery_day(datetime.now(UTC))[0]
        try:
            outcome = await provisioning.ensure_demo_case(
                self.worker.database, cycles=self.worker, settings=self.settings
            )
        except Exception:
            logger.exception("worker.demo_case.failed")
            return
        logger.info(
            "worker.demo_case",
            action=outcome.action.value,
            case_id=None if outcome.case_id is None else str(outcome.case_id),
            state=outcome.state,
            detail=outcome.detail,
            rolled=outcome.rolled,
        )
