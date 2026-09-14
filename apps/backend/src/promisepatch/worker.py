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

**A hard kill is a supported outcome.** ``SIGTERM`` and ``SIGINT`` stop the loop between
cycles, which is tidier; ``SIGKILL`` mid-transaction leaves a rolled-back transaction and an
expiring lease, which is recoverable. The difference between the two is how quickly the work
resumes, never whether it can.
"""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy.exc import SQLAlchemyError

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
from promisepatch.domain.model import EFFECT_ORDER_AMEND
from promisepatch.domain.observation import STEP_INTERPRET_SEMANTICALLY
from promisepatch.domain.order_mirror import AuthoritativeFetch
from promisepatch.domain.outbox import EffectAdapter
from promisepatch.integrations import build_semantic_provider
from promisepatch.integrations.order_system import OrderSystemAdapter, OrderSystemClient
from promisepatch.observability import configure_logging, get_logger
from promisepatch.semantic import FakeSemanticProvider, SemanticProvider

logger = get_logger(__name__)

IDLE_INTERVAL: Final = 1.0
"""Seconds to wait after a cycle that found nothing to do.

Short enough that a step enqueued by an API request is picked up promptly, long enough that an
idle worker is not a continuous load on the database. A constant rather than a setting: nothing
has asked to vary it, and a variable nobody sets is a promise the code does not keep.
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

    @property
    def actor(self) -> Actor:
        """Every governed write this worker makes is attributed to this process by name."""
        return Actor(kind="SYSTEM", id=self.identity.value)

    async def run_once(self) -> bool:
        """One pass over every kind of work. ``True`` if anything at all was done.

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
        stepped = await self._execute_one_step()
        dispatched = await outbox.dispatch_one(
            self.database, self.adapter, worker=self.identity.value, actor=self.actor
        )
        ingested = await inbox.process_one(self.database, worker=self.identity.value)
        mirrored = await order_mirror.process_one(
            self.database, worker=self.identity.value, fetch=self.fetch_order
        )
        return any(item is not None for item in (fired, stepped, dispatched, ingested, mirrored))

    async def _execute_one_step(self) -> str | None:
        claim = await steps.claim_step(self.database, worker=self.identity.value)
        if claim is None:
            return None
        if claim.kind == STEP_INTERPRET_SEMANTICALLY:
            # The one provider call in the step path, and it is made here rather than inside
            # the execution transaction. Between the claim and the execution is the only moment
            # in the cycle when this process holds a lease on the work and no database
            # transaction at all, which is exactly what a call to somebody else's service
            # needs. What it leaves behind is a row; what decides anything is the transaction
            # below, which takes the locks and re-reads what it is deciding about.
            #
            # A worker's sentence, and nothing else. Per ADR-0008 a customer's reply is never
            # sent to a model: the two words that can answer are read by a parser, and the one
            # question an unreadable reply earns is built from the request it is bound to.
            await semantic_intake.prepare(self.database, self.semantic, claim=claim)
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

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Cycle until ``stop`` is set, backing off when the database is unreachable.

        Only :class:`~sqlalchemy.exc.SQLAlchemyError` and ``OSError`` are treated as transient.
        Anything else is a bug in a transition, and a loop that swallowed those would keep
        running while getting the same thing wrong every second.
        """
        backoff = INITIAL_BACKOFF
        logger.info("worker.start", worker=self.identity.value)
        try:
            while not stop.is_set():
                try:
                    busy = await self.run_once()
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
                    await _wait(stop, self.idle_interval)
        finally:
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


async def run(settings: Settings, adapter: EffectAdapter | None = None) -> None:
    """Build a worker from settings and run it until it is asked to stop.

    The connection is ``PP_DATABASE_URL`` -- ``promisepatch_app``, the same least-privileged
    role the API uses. A worker holds no migration credential and can no more disable a trigger
    or rewrite a ledger than a request handler can.

    Which provider each kind of effect reaches is a deployment question, answered once here and
    nowhere else. With an order system configured, amendments go to it and the mirror is
    reconciled against what it says; without one, the fake provider proves the outbox's own
    guarantees and makes no claim about anybody's order. Everything else -- today, only the
    customer message, whose real channel is a later slice -- goes to the fake provider either
    way. The recovery saga is identical in every case: it reads what the row says the provider
    did, and does not know which one answered.
    """
    configure_logging(settings)
    database = RuntimeDatabase.from_settings(settings)
    stop = asyncio.Event()
    _install_signal_handlers(stop)

    client = (
        OrderSystemClient(
            base_url=settings.require_order_system_base_url(),
            timeout=settings.order_system_timeout_seconds,
        )
        if settings.order_system_configured
        else None
    )
    if adapter is None:
        adapter = (
            RoutedEffectAdapter(
                routes={EFFECT_ORDER_AMEND: OrderSystemAdapter(client)},
                default=FakeEffectAdapter(),
            )
            if client is not None
            else FakeEffectAdapter()
        )

    worker = Worker(
        database=database,
        adapter=adapter,
        # One place reads `PP_LLM_PROVIDER`, and it is not here: the worker asks for whatever
        # this deployment configured and cannot behave differently depending on the answer.
        semantic=build_semantic_provider(settings),
        fetch_order=None if client is None else client.fetch_order,
    )
    try:
        await worker.run_forever(stop)
    finally:
        if client is not None:
            await client.aclose()
        await database.dispose()
