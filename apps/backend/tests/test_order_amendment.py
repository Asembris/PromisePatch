"""Pushing a recovery amendment at the order system, and finishing only once it echoes back.

Every test here runs the real order system. The amendment is a real HTTP request it parses and
applies to its own database; the echo is a real signed event PromisePatch verifies, stores and
applies to its mirror. What is asserted is the thing that distinguishes an integration from a
claim about one: how many times the *order* actually moved, and whether PromisePatch would ever
say a recovery was complete without having seen it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from _intake_support import RASPBERRY_ONLY, TOMAS_CHANNEL, Intake
from _intake_support import physical as physical
from _order_system_support import (
    Boundary,
    boundary,
    losing,
)
from sqlalchemy import select

from order_contract.amendments import AmendmentRequest
from promise_graph.examples import hollow_oak as ho
from promisepatch.config import Settings
from promisepatch.db.models import OutboxMessage
from promisepatch.domain import crash, order_mirror, outbox, recovery, steps
from promisepatch.domain.model import DeliveryOutcome, DeliveryStatus
from promisepatch.integrations.order_system import build_request
from promisepatch.worker import Worker

A, B = ho.PROMISE_A, ho.PROMISE_B
ORDER_A, ORDER_B = "EXT-A", "EXT-B"
WORKER = "order-amendment-tests"


@pytest_asyncio.fixture
async def wired(
    physical: Intake,
    runtime_settings: Settings,
    tmp_path: Path,
) -> AsyncIterator[Boundary]:
    async with boundary(
        physical.database,
        settings=runtime_settings,
        sqlite_path=tmp_path / "order-simulator.sqlite3",
    ) as running:
        yield running


@pytest_asyncio.fixture
async def uncertain(
    physical: Intake,
    runtime_settings: Settings,
    tmp_path: Path,
) -> AsyncIterator[Boundary]:
    """The same pair, with the first amendment's answer lost after it was applied."""
    async with boundary(
        physical.database,
        settings=runtime_settings,
        sqlite_path=tmp_path / "order-simulator.sqlite3",
        transport=losing(1),
    ) as running:
        yield running


# ------------------------------------------------------------------------------- driving


def worker_for(intake: Intake, wired: Boundary) -> Worker:
    return intake.worker(adapter=wired.adapter, fetch=wired.client.fetch_order)


async def planned(intake: Intake) -> UUID:
    opened = await intake.report()
    await intake.drain()
    await intake.answer(opened.case_id, RASPBERRY_ONLY)
    await intake.drain()
    return opened.case_id


async def confirmed(intake: Intake, wired: Boundary) -> UUID:
    """A worker's yes, and everything it releases, up to the amendment leaving."""
    case_id = await planned(intake)
    await intake.confirm(case_id)
    await intake.drain(worker=worker_for(intake, wired), limit=40)
    return case_id


async def settle(intake: Intake, wired: Boundary, *, rounds: int = 4) -> None:
    """Carry the echo across and let the workflow finish, without waiting out a retry ladder."""
    for _ in range(rounds):
        await wired.deliver_webhooks()
        await intake.make_work_due()
        await intake.drain(worker=worker_for(intake, wired), limit=40)


async def run_steps(intake: Intake, *, limit: int = 30) -> None:
    """Execute steps and nothing else, so a test can decide when the sending happens.

    A whole worker cycle claims a step *and* dispatches an effect, and which of a case's two
    ready steps it happens to claim first is not fixed. Tests about the order of the two
    hand-offs therefore drive the sweeps themselves rather than asserting about a cycle whose
    internal order they do not control.
    """
    runner = intake.worker()
    for _ in range(limit):
        claim = await steps.claim_step(intake.database, worker=runner.identity.value)
        if claim is None:
            return
        await steps.execute_step(intake.database, claim=claim, actor=runner.actor)


async def dispatch_all(intake: Intake, wired: Boundary, *, limit: int = 10) -> None:
    """Send whatever the outbox has ready, with no step execution in between."""
    runner = intake.worker(adapter=wired.adapter)
    for _ in range(limit):
        if (
            await outbox.dispatch_one(
                intake.database, wired.adapter, worker=runner.identity.value, actor=runner.actor
            )
            is None
        ):
            return


async def track_of(intake: Intake, case_id: UUID, promise_id: str) -> Any:
    row = await intake.track(case_id, promise_id)
    assert row is not None
    return row


async def amendment_effect(intake: Intake, track_id: UUID) -> Any:
    rows = [
        row for row in await intake.effects_for(track_id) if row.kind == recovery.EFFECT_ORDER_AMEND
    ]
    assert len(rows) == 1, rows
    return rows[0]


# ----------------------------------------------------------------- what is actually sent


def test_the_request_is_built_from_the_persisted_plan_and_nothing_else() -> None:
    """Serialisation, not selection. Every value is copied off the outbox row."""
    case_id, track_id, option_id = UUID(int=1), UUID(int=2), UUID(int=3)
    payload = {
        "case_id": str(case_id),
        "track_id": str(track_id),
        "option_id": str(option_id),
        "order_external_id": ORDER_A,
        "order_external_version": 4,
        "order_line_id": "ol-a",
        "from_version_id": "rv-raspberry-almond-3",
        "to_version_id": "rv-raspberry-almond-4",
    }

    request = build_request(payload, reference="pp:amend:key")

    assert request == AmendmentRequest(
        external_order_id=ORDER_A,
        expected_version=4,
        external_line_id="ol-a",
        from_item_id="rv-raspberry-almond-3",
        to_item_id="rv-raspberry-almond-4",
        note=request.note,
        correlation=request.correlation,
    )
    assert request.correlation.case_id == case_id
    assert request.correlation.track_id == track_id
    assert request.correlation.option_id == option_id
    assert "pp:amend:key" in request.note


async def test_the_amendment_carries_the_option_planning_chose(
    wired: Boundary, physical: Intake
) -> None:
    case_id = await confirmed(physical, wired)
    track = await track_of(physical, case_id, A)

    effect = await amendment_effect(physical, track.id)
    option = next(
        row for row in await physical.options(track.id) if row.id == track.chosen_option_id
    )
    external = wired.external_order(ORDER_A)

    assert effect.payload["option_id"] == str(option.id)
    assert effect.payload["to_version_id"] == option.to_version_id
    assert effect.payload["order_external_version"] == 1
    assert external.lines[0].external_item_id == option.to_version_id
    assert external.version == 2


async def test_the_provider_result_is_persisted_with_the_acknowledgement(
    wired: Boundary, physical: Intake
) -> None:
    """A reference says it was accepted; the result says what was accepted."""
    case_id = await confirmed(physical, wired)
    track = await track_of(physical, case_id, A)

    effect = await amendment_effect(physical, track.id)

    assert effect.state == "DELIVERED"
    assert effect.provider_ref
    assert effect.result["external_version"] == 2
    assert effect.result["previous_version"] == 1
    assert effect.result["item_id"] == effect.payload["to_version_id"]


async def test_the_amendment_is_sent_with_no_database_transaction_held(
    wired: Boundary, physical: Intake
) -> None:
    """§22: a provider call inside a transaction would hold a connection for a round trip.

    Measured rather than reviewed: the adapter records how many connections the application's
    own pool had checked out at the moment it was called, and the answer has to be none.
    """
    observed: list[int] = []
    inner = wired.adapter

    class Probe:
        async def deliver(self, **call: Any) -> DeliveryOutcome:
            pool = physical.database.engine.pool
            observed.append(int(pool.checkedout()))  # type: ignore[attr-defined]
            return await inner.deliver(**call)

    case_id = await planned(physical)
    await physical.confirm(case_id)
    await physical.drain(
        worker=physical.worker(adapter=Probe(), fetch=wired.client.fetch_order), limit=40
    )

    assert observed
    assert set(observed) == {0}


# ------------------------------------------------------- recovered means observed


async def test_a_track_does_not_recover_on_an_acknowledgement_alone(
    wired: Boundary, physical: Intake
) -> None:
    """§29: the order system has accepted it, and PromisePatch has not yet seen the result."""
    case_id = await confirmed(physical, wired)
    track = await track_of(physical, case_id, A)

    effect = await amendment_effect(physical, track.id)

    assert effect.state == "DELIVERED"
    assert wired.external_order(ORDER_A).version == 2
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_APPLYING
    assert await wired.mirrored_version_of("ol-a") == "rv-raspberry-almond-3"


async def test_the_echo_completes_the_recovery(wired: Boundary, physical: Intake) -> None:
    """§64: the whole canonical A path, against a real provider and its real event."""
    case_id = await confirmed(physical, wired)

    await settle(physical, wired)

    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED
    assert await wired.mirrored_version_of("ol-a") == "rv-raspberry-almond-4"
    assert (await wired.mirrored_order(ORDER_A)).external_version == 2
    assert wired.simulator.event_count(ORDER_A) == 1


async def test_the_recovery_finishes_exactly_once(wired: Boundary, physical: Intake) -> None:
    case_id = await confirmed(physical, wired)
    await settle(physical, wired)

    await settle(physical, wired)

    track = await track_of(physical, case_id, A)
    completions = [
        row
        for row in await physical.audits(case_id)
        if row.type == recovery.AUDIT_RECOVERY_COMPLETED
    ]
    assert track.state == recovery.TRACK_RECOVERED
    assert len(completions) == 1
    assert wired.simulator.event_count(ORDER_A) == 1


async def test_an_echo_that_arrives_before_the_acknowledgement_also_converges(
    uncertain: Boundary, physical: Intake
) -> None:
    """§28 and §41: the order applied it, the answer was lost, the event arrived first.

    The dispatcher's first attempt reaches the order system and never learns what happened. The
    echo of that very change is delivered and applied to the mirror while the effect is still
    ``PENDING``. The retry then presents the same key, the order system replays its stored
    answer rather than acting twice, and the recovery finishes -- against a mirror that was
    already correct before the acknowledgement existed.
    """
    case_id = await planned(physical)
    await physical.confirm(case_id)
    await run_steps(physical)
    track = await track_of(physical, case_id, A)

    # One round of sending, and the answer to the amendment is lost on the way back.
    await dispatch_all(physical, uncertain)
    assert (await amendment_effect(physical, track.id)).state == "PENDING"
    assert uncertain.external_order(ORDER_A).version == 2

    # The echo of that very change, arriving while the acknowledgement does not yet exist.
    await uncertain.deliver_webhooks()
    await order_mirror.process_one(
        physical.database, worker=WORKER, fetch=uncertain.client.fetch_order
    )
    assert await uncertain.mirrored_version_of("ol-a") == "rv-raspberry-almond-4"
    assert (await amendment_effect(physical, track.id)).state == "PENDING"
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_APPLYING

    await settle(physical, uncertain)

    effect = await amendment_effect(physical, track.id)
    assert effect.state == "DELIVERED"
    assert effect.attempts == 2
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED
    assert uncertain.simulator.event_count(ORDER_A) == 1
    assert len(uncertain.simulator.commands()) == 1


async def test_an_uncertain_answer_never_becomes_a_second_order_change(
    uncertain: Boundary, physical: Intake
) -> None:
    """§26: one logical external mutation, two transport calls, one stored command."""
    await confirmed(physical, uncertain)
    await settle(physical, uncertain)

    assert uncertain.simulator.event_count(ORDER_A) == 1
    assert uncertain.external_order(ORDER_A).version == 2
    assert len(uncertain.simulator.commands()) == 1


# ---------------------------------------------------------- optimistic concurrency


async def test_an_amendment_planned_against_an_overtaken_version_is_refused(
    wired: Boundary, physical: Intake
) -> None:
    """§25 and §66: an old plan may not overwrite a newer external truth.

    The order moves in the order system after PromisePatch planned against it and *before*
    PromisePatch has heard about it -- so the plan still looks current here and the amendment
    goes out expecting the version it was made against. The order system refuses. What must not
    happen is the recovery reporting success, or the customer's newer order being overwritten.
    """
    case_id = await planned(physical)
    await physical.confirm(case_id)
    await wired.operator_changes(order=ORDER_A, item="rv-raspberry-charlotte-1")

    await physical.drain(worker=worker_for(physical, wired), limit=40)

    track = await track_of(physical, case_id, A)
    effect = await amendment_effect(physical, track.id)
    assert effect.state == "FAILED"
    assert "VERSION_CONFLICT" in (effect.last_error or "")
    assert track.state != recovery.TRACK_RECOVERED
    assert wired.external_order(ORDER_A).lines[0].external_item_id == "rv-raspberry-charlotte-1"
    assert wired.simulator.event_count(ORDER_A) == 1


async def test_a_refused_amendment_escalates_instead_of_claiming_success(
    wired: Boundary, physical: Intake
) -> None:
    case_id = await planned(physical)
    await physical.confirm(case_id)
    await wired.operator_changes(order=ORDER_A, item="rv-raspberry-charlotte-1")

    await physical.drain(worker=worker_for(physical, wired), limit=40)
    await settle(physical, wired)

    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_ESCALATED


async def test_an_effect_kind_the_adapter_does_not_understand_is_refused(
    wired: Boundary,
) -> None:
    """An adapter that accepted an unfamiliar effect would report a success nobody performed."""
    outcome = await wired.order_system_adapter.deliver(
        kind="SOMETHING_ELSE", payload={}, idempotency_key="pp:whatever"
    )

    assert outcome.status is DeliveryStatus.TERMINAL


# ------------------------------------------------------------------------- crash safety


async def test_a_death_after_the_order_system_applied_it_recovers_under_the_same_key(
    wired: Boundary, physical: Intake
) -> None:
    """§69: the uncertain window, with a real provider on the other side of it.

    The process dies between the order system applying the amendment and PromisePatch recording
    that it did. The lease expires, the same key goes out again, and the order system answers
    from its idempotency ledger rather than acting twice.
    """
    case_id = await planned(physical)
    await physical.confirm(case_id)
    await run_steps(physical)

    def die_once_the_order_has_moved() -> None:
        """Kill the process at the exact instant the window opens, and not before.

        The boundary is reached by every accepted effect, and this case sends two. Arming it
        unconditionally would kill the worker on whichever happened to go first, which is not
        the moment this test is about: the one that matters is after the *order system* has
        applied an amendment and before PromisePatch has recorded that it did.
        """
        if wired.simulator.event_count(ORDER_A) == 1:
            raise crash.WorkerDied(crash.AFTER_EXTERNAL_SUCCESS)

    with (
        crash.arm(crash.AFTER_EXTERNAL_SUCCESS, die_once_the_order_has_moved),
        pytest.raises(crash.WorkerDied),
    ):
        await dispatch_all(physical, wired)

    assert wired.external_order(ORDER_A).version == 2
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_APPLYING

    stranded = next(
        row for row in await physical.effects() if row.kind == recovery.EFFECT_ORDER_AMEND
    )
    await physical.expire_effect_lease(stranded.id)
    await settle(physical, wired)

    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED
    assert wired.simulator.event_count(ORDER_A) == 1


async def test_a_death_before_the_finalisation_commits_finalises_exactly_once(
    wired: Boundary, physical: Intake
) -> None:
    """The mirror is already right; the transition that says so never committed.

    A fresh worker re-runs the step, and the recovery completes once -- not twice, because the
    first attempt wrote nothing at all.
    """
    case_id = await confirmed(physical, wired)
    await wired.deliver_webhooks()
    await physical.make_work_due()

    with crash.arm(crash.BEFORE_TRANSITION_COMMIT):
        for _ in range(10):
            try:
                if not await worker_for(physical, wired).run_once():
                    break
            except crash.WorkerDied:
                break

    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_APPLYING

    await settle(physical, wired)

    completions = [
        row
        for row in await physical.audits(case_id)
        if row.type == recovery.AUDIT_RECOVERY_COMPLETED
    ]
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED
    assert len(completions) == 1


async def test_an_ingested_event_survives_a_worker_that_never_processed_it(
    wired: Boundary, physical: Intake
) -> None:
    """§40: the inbox is durable, so a restart is all the recovery a delivery needs."""
    await wired.operator_changes(order=ORDER_A, item="rv-raspberry-almond-4")
    await wired.deliver_webhooks()

    rows = await wired.inbox_rows()
    assert [row.state for row in rows] == ["RECEIVED"]

    await order_mirror.process_one(physical.database, worker=WORKER, fetch=wired.client.fetch_order)

    assert await wired.mirrored_version_of("ol-a") == "rv-raspberry-almond-4"


# ---------------------------------------------------------------- the approved path


async def test_an_approved_change_uses_the_same_external_path(
    wired: Boundary, physical: Intake
) -> None:
    """§65: B recovers through the customer's own yes and the same order system as A.

    There is deliberately no second mechanism here. The consent protocol decides *whether* the
    amendment may be sent; what sends it, what the order system does with it and what has to be
    observed before the track may be called recovered are identical to A's.
    """
    case_id = await confirmed(physical, wired)
    await settle(physical, wired)
    track_b = await track_of(physical, case_id, B)
    assert track_b.state == "WAITING_FOR_CUSTOMER"

    requests = await physical.requests()
    assert len(requests) == 1
    await physical.deliver_reply(requests[0].id, "YES", sender=TOMAS_CHANNEL)
    await settle(physical, wired, rounds=6)

    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_RECOVERED
    assert await wired.mirrored_version_of("ol-b") == "rv-raspberry-rose-3"
    assert wired.external_order(ORDER_B).lines[0].external_item_id == "rv-raspberry-rose-3"
    assert wired.simulator.event_count(ORDER_B) == 1


async def test_the_order_system_records_who_amended_the_order_and_why(
    wired: Boundary, physical: Intake
) -> None:
    """The note an operator reads in the order system afterwards, from the order system's rows."""
    await confirmed(physical, wired)

    line = wired.external_order(ORDER_A).lines[0]

    assert "Amended by PromisePatch" in line.note
    assert "pp:amend:" in line.note


async def test_nothing_amends_an_order_that_no_plan_chose(
    wired: Boundary, physical: Intake
) -> None:
    """Selectivity, at the boundary: only the orders a plan reached are touched at all."""
    await confirmed(physical, wired)
    await settle(physical, wired)

    changed = {order.external_id for order in wired.simulator.list_orders() if order.version > 1}

    assert changed == {ORDER_A}


async def test_every_amendment_the_outbox_holds_reached_one_order(
    wired: Boundary, physical: Intake
) -> None:
    """One effect, one command in the order system's ledger, one event. No arithmetic drift."""
    await confirmed(physical, wired)
    await settle(physical, wired)

    async with physical.database.connect() as connection:
        amendments = (
            await connection.execute(
                select(OutboxMessage).where(
                    OutboxMessage.kind == recovery.EFFECT_ORDER_AMEND,
                    OutboxMessage.state == "DELIVERED",
                )
            )
        ).all()

    assert len(amendments) == len(wired.simulator.commands()) == 1
