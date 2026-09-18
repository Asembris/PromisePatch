"""What unrelated ready work waits while one case is held open on a slow model call.

This is the regression form of the G8 head-of-line measurement -- see
`docs/g8-head-of-line-measurement.md` and `docs/g8-head-of-line-disposition.md`. That harness
needed nine runs, three arms and a fixture reset to publish a number nobody could argue with.
This file needs none of that, because it is not publishing a number: it asserts the one property
the number was about, cheaply enough to run on every change.

**The gate is not invented here.** ``H <= 1000.0 ms`` is section 8 of the predeclaration, taken
from ``worker.IDLE_INTERVAL`` -- the worker's own word for how long ready work may reasonably
sit -- and fixed before that harness existed. This file imports the constant rather than
restating the number, so the two can never drift apart.

**No model is called and no clock is real except the database's.** The provider is the ordinary
fake with an ``asyncio.sleep`` in front of it, injected through the constructor field the product
already exposes, and every instant that reaches an assertion is a column the product wrote:
``case_steps.created_at`` and ``case_steps.started_at``. Nothing is timed by the test.

**The loop's idle sampling is turned down, and the gate is not.** A worker that has just gone
idle looks again after ``IDLE_INTERVAL``, so ready work arriving one millisecond into that sleep
waits most of the gate before anything is even claimed -- which would make a 1000 ms assertion a
coin toss about *when* the test happened to write a row. ``idle_interval`` is therefore set small
on the worker under test, which leaves head-of-line coupling as the only thing the measured wait
can be made of. The delay injected in front of the model is five seconds, five times the gate, so
the two outcomes are nowhere near each other: coupled, the wait is seconds; uncoupled, it is
milliseconds.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final
from uuid import UUID

import pytest
from _intake_support import UNREADABLE, Intake
from _intake_support import physical as physical
from _semantic_support import COLOUR_COMPLAINT, CREAM_TURNED, PARTIAL_DELIVERY, THE_BERRIES
from _workflow_support import Workflow
from sqlalchemy import select

from promisepatch.db.models import CaseStep
from promisepatch.domain import steps
from promisepatch.domain.model import StepKind
from promisepatch.domain.observation import STEP_INTERPRET_SEMANTICALLY
from promisepatch.semantic import FakeSemanticProvider
from promisepatch.semantic.jobs import JobSpec
from promisepatch.semantic.provider import Attempt
from promisepatch.worker import IDLE_INTERVAL, Worker

pytestmark = pytest.mark.integration

GATE_MS: Final = IDLE_INTERVAL * 1000.0
"""Section 8's threshold, imported rather than restated. 1000.0 ms at the time of writing."""

DELAY_SECONDS: Final = 5.0
"""Five times the gate, and well inside ``steps.LEASE_DURATION``."""

SAMPLING_INTERVAL: Final = 0.05
"""What the worker under test uses instead of ``IDLE_INTERVAL``. See the module docstring."""

SETTLE_BOUND: Final = 30.0
"""Any wait this file polls for is bounded, so a regression fails rather than hangs."""

POLL_SECONDS: Final = 0.02

READABLE: Final = "the deck oven is down"
"""An unrelated sentence the deterministic lexicon resolves outright, so no model is asked."""


class DelayingProvider(FakeSemanticProvider):
    """The unmodified fake, held open for a stated number of seconds.

    ``entered`` is set on the way in, which is what lets a test create unrelated work at the one
    instant that makes the question meaningful: after the slow call has started. ``peak`` is how
    many of these were ever open at once, which is the only place a bound on concurrency can
    honestly be read: the worker's own counter would be the code under test marking its own work.
    """

    def __init__(self, delay_seconds: float, *, label: str = "responsiveness-harness") -> None:
        super().__init__()
        self.name = label
        self.delay_seconds = delay_seconds
        self.entered = asyncio.Event()
        self.open = 0
        self.peak = 0

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        self.entered.set()
        self.open += 1
        self.peak = max(self.peak, self.open)
        try:
            await asyncio.sleep(self.delay_seconds)
            return await super().invoke(spec, content, correction=correction)
        finally:
            self.open -= 1


class RaisingProvider(FakeSemanticProvider):
    """A provider whose failure is not one the semantic boundary has a category for.

    A provider that is merely unreachable is already an outcome ``semantic_intake.prepare``
    records and the transition reads. What this one produces is the other thing: an exception
    nobody planned for, in the one place that used to be inside the worker's only loop.
    """

    name = "responsiveness-raiser"

    def __init__(self) -> None:
        super().__init__()
        self.calls_made = 0

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        self.calls_made += 1
        raise RuntimeError("the preparation broke in a way nothing expected")


async def _first_step(intake: Intake, case_id: UUID) -> Any:
    async with intake.database.begin() as connection:
        return (
            await connection.execute(
                select(CaseStep)
                .where(CaseStep.case_id == case_id)
                .order_by(CaseStep.created_at, CaseStep.id)
                .limit(1)
            )
        ).first()


async def _semantic_step(intake: Intake, case_id: UUID) -> Any:
    async with intake.database.begin() as connection:
        return (
            await connection.execute(
                select(CaseStep).where(
                    CaseStep.case_id == case_id,
                    CaseStep.kind == STEP_INTERPRET_SEMANTICALLY,
                )
            )
        ).first()


async def _row(intake: Intake, step_id: UUID) -> Any:
    async with intake.database.begin() as connection:
        return (await connection.execute(select(CaseStep).where(CaseStep.id == step_id))).one()


async def _started(intake: Intake, step_id: UUID) -> Any:
    """Poll until the database says this step was started, and return the row that says so."""

    async def poll() -> Any:
        while True:
            row = await _row(intake, step_id)
            if row.started_at is not None:
                return row
            await asyncio.sleep(POLL_SECONDS)

    return await asyncio.wait_for(poll(), SETTLE_BOUND)


def _wait_ms(row: Any) -> float:
    """How long this step sat between being created and being started, by the database's clock."""
    return float((row.started_at - row.created_at).total_seconds()) * 1000.0


async def _stage_slow_case(intake: Intake, worker: Worker) -> UUID:
    """Open the case whose sentence needs a model, and stop with its step pending, unclaimed.

    Two cycles is the whole of intake up to that point: one to begin interpretation, one to
    resolve it deterministically and fail, which is what enqueues the semantic step. A third
    cycle would claim it, and the delay belongs inside the measured window rather than before it.
    """
    opened = await intake.report(UNREADABLE)
    await intake.drain(worker=worker, limit=2)
    staged = await _semantic_step(intake, opened.case_id)
    assert staged is not None and staged.state == "PENDING"
    return opened.case_id


async def test_unrelated_ready_work_does_not_wait_behind_a_slow_semantic_preparation(
    physical: Intake, request: pytest.FixtureRequest
) -> None:
    """The head-of-line property, as one assertion against the gate the roadmap fixed.

    Case A is held open in the model call. Case B is created *after* that call has started, so it
    is unrelated ready work arriving while the slow one is outstanding. What is asserted is the
    wait the product itself recorded for B's first step, against section 8's threshold.
    """
    provider = DelayingProvider(DELAY_SECONDS)
    worker = physical.worker(semantic=provider)
    worker.idle_interval = SAMPLING_INTERVAL
    slow_case = await _stage_slow_case(physical, worker)

    stop = asyncio.Event()
    loop = asyncio.create_task(worker.run_forever(stop))
    try:
        await asyncio.wait_for(provider.entered.wait(), SETTLE_BOUND)
        unrelated = await physical.report(READABLE)
        first = await _first_step(physical, unrelated.case_id)
        assert first is not None
        started = await _started(physical, first.id)
    finally:
        stop.set()
        await loop

    wait_ms = _wait_ms(started)
    # Recorded rather than printed, so a run can be asked what the wait actually was instead of
    # only whether it cleared the gate. ``user_properties`` directly rather than through the
    # ``record_property`` fixture, which warns under this repository's junit family.
    request.node.user_properties.append(("unrelated_wait_ms", round(wait_ms, 1)))
    request.node.user_properties.append(("gate_ms", GATE_MS))
    assert wait_ms <= GATE_MS, (
        f"unrelated ready work waited {wait_ms:.1f} ms behind a {DELAY_SECONDS * 1000:.0f} ms "
        f"semantic call; section 8's gate is {GATE_MS:.1f} ms"
    )
    assert (await _semantic_step(physical, slow_case)).state == "DONE"


async def test_a_stopped_worker_has_finished_what_it_deferred(physical: Intake) -> None:
    """Stopping the loop is not abandoning the work beside it.

    A worker that returned from ``run_forever`` with a model call still outstanding would be
    telling its caller a case was done with while the task that finishes it was still running --
    and the caller's next act, in ``worker.built``, is to close the database that task is using.
    """
    provider = DelayingProvider(1.0)
    worker = physical.worker(semantic=provider)
    worker.idle_interval = SAMPLING_INTERVAL
    slow_case = await _stage_slow_case(physical, worker)

    stop = asyncio.Event()
    loop = asyncio.create_task(worker.run_forever(stop))
    await asyncio.wait_for(provider.entered.wait(), SETTLE_BOUND)
    stop.set()
    await asyncio.wait_for(loop, SETTLE_BOUND)

    assert worker.deferred == 0
    assert worker.deferred_failures == []
    step = await _semantic_step(physical, slow_case)
    assert step.state == "DONE"
    assert step.done_at is not None


SLOW_SENTENCES: Final[tuple[str, ...]] = (
    UNREADABLE,
    CREAM_TURNED,
    PARTIAL_DELIVERY,
    THE_BERRIES,
    COLOUR_COMPLAINT,
)
"""Five sentences the deterministic lexicon cannot conclude on, so five cases need a model."""


async def _settled(intake: Intake, case_ids: list[UUID]) -> None:
    """Poll until every one of these cases has a semantic step that reached an outcome."""

    async def poll() -> None:
        while True:
            rows = [await _semantic_step(intake, case_id) for case_id in case_ids]
            if all(row is not None and row.state == "DONE" for row in rows):
                return
            await asyncio.sleep(POLL_SECONDS)

    await asyncio.wait_for(poll(), SETTLE_BOUND)


async def test_several_slow_cases_progress_together_and_none_of_them_twice(
    physical: Intake,
) -> None:
    """Concurrency is bounded, is really concurrent, and buys nothing at the cost of a repeat.

    Five cases all need a model and the worker is allowed two preparations at once. What the
    provider counted is the bound holding from the outside; what the step rows say is that the
    bound bought no duplication -- one call and one attempt each, which is what a claim, a lease
    and a fence are for and which concurrency is the classic way to lose.
    """
    provider = DelayingProvider(0.4)
    worker = physical.worker(semantic=provider)
    worker.idle_interval = SAMPLING_INTERVAL
    worker.deferred_limit = 2
    cases = [(await physical.report(sentence)).case_id for sentence in SLOW_SENTENCES]

    stop = asyncio.Event()
    loop = asyncio.create_task(worker.run_forever(stop))
    try:
        await _settled(physical, cases)
    finally:
        stop.set()
        await asyncio.wait_for(loop, SETTLE_BOUND)

    assert provider.peak == worker.deferred_limit, (
        f"the provider saw a peak of {provider.peak} calls at once against a limit of "
        f"{worker.deferred_limit}"
    )
    assert len(provider.calls) == len(SLOW_SENTENCES)
    for case_id in cases:
        step = await _semantic_step(physical, case_id)
        assert step.attempts == 1
        assert step.state == "DONE"


async def test_a_preparation_that_outlives_its_lease_still_commits_nothing(
    physical: Intake,
) -> None:
    """The fence is unchanged by the deferral, which is the whole claim being made about it.

    The slow worker's claim is aged out while its call is open and another worker takes the step
    over and finishes it. When the first one wakes holding an answer, the row it would write to
    no longer carries its attempt number -- so the reading on the step is the second worker's,
    and the answer the first one paid for is simply dropped.
    """
    slow = DelayingProvider(2.0, label="the-worker-that-stalled")
    stalling = physical.worker(identity="stalled", semantic=slow)
    stalling.idle_interval = SAMPLING_INTERVAL
    case_id = await _stage_slow_case(physical, stalling)

    stop = asyncio.Event()
    loop = asyncio.create_task(stalling.run_forever(stop))
    try:
        await asyncio.wait_for(slow.entered.wait(), SETTLE_BOUND)
        step = await _semantic_step(physical, case_id)
        await physical.expire_lease(step.id)

        quick = DelayingProvider(0.0, label="the-worker-that-took-over")
        await physical.drain_intake(
            case_id, worker=physical.worker(identity="took-over", semantic=quick)
        )
        assert len(quick.calls) == 1
    finally:
        stop.set()
        await asyncio.wait_for(loop, SETTLE_BOUND)

    assert len(slow.calls) == 1
    assert stalling.deferred_failures == []
    settled = await _semantic_step(physical, case_id)
    assert settled.attempts == 2
    assert settled.result["semantic"]["provider"] == "the-worker-that-took-over"


async def test_a_preparation_that_raises_does_not_stall_unrelated_work(
    physical: Intake,
) -> None:
    """A broken preparation costs its own case an attempt and costs everybody else nothing.

    This is the one failure mode the deferral introduces and it is the reason the task swallows:
    before, an exception here left the loop, and a loop that stops is every unrelated case
    stopping with it. Now the unrelated case finishes, the failure is on the record, and the
    broken step is left to the lease and the ladder that already handle a worker that vanished.
    """
    provider = RaisingProvider()
    worker = physical.worker(semantic=provider)
    worker.idle_interval = SAMPLING_INTERVAL
    broken = await _stage_slow_case(physical, worker)

    stop = asyncio.Event()
    loop = asyncio.create_task(worker.run_forever(stop))
    try:
        unrelated = await physical.report(READABLE)
        first = await _first_step(physical, unrelated.case_id)
        await _started(physical, first.id)
        assert not loop.done(), "the loop stopped because one preparation raised"
    finally:
        stop.set()
        await asyncio.wait_for(loop, SETTLE_BOUND)

    assert provider.calls_made == 1
    assert [type(error) for error in worker.deferred_failures] == [RuntimeError]
    assert worker.deferred == 0
    step = await _semantic_step(physical, broken)
    assert step.state == "IN_FLIGHT"
    assert step.attempts == 1


# ------------------------------------------------- the claim-time exclusions, on their own


async def test_a_claim_sweep_leaves_an_excluded_case_alone(workflow: Workflow) -> None:
    """A sweep told to skip a case takes the next row instead, and the skip is not durable."""
    held = await workflow.create_case()
    other = await workflow.create_case()
    await workflow.add_step(held, step_key="noop:1", kind=StepKind.NOOP)
    await workflow.add_step(other, step_key="noop:1", kind=StepKind.NOOP)

    claimed = await steps.claim_step(workflow.database, worker="w", exclude_cases=(held,))
    assert claimed is not None and claimed.case_id == other

    # Nothing was written to the skipped row: the very next sweep, with nothing excluded, finds
    # it exactly where it was.
    again = await steps.claim_step(workflow.database, worker="w")
    assert again is not None and again.case_id == held
    assert again.attempts == 1


async def test_a_claim_sweep_leaves_an_excluded_kind_alone(workflow: Workflow) -> None:
    """A sweep with no capacity for slow work overtakes it rather than queueing behind it."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="semantic:1", kind=STEP_INTERPRET_SEMANTICALLY)
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)

    claimed = await steps.claim_step(
        workflow.database, worker="w", exclude_kinds=(STEP_INTERPRET_SEMANTICALLY,)
    )
    assert claimed is not None and claimed.step_key == "noop:1"

    again = await steps.claim_step(workflow.database, worker="w")
    assert again is not None and again.step_key == "semantic:1"
