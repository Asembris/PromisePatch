"""Two systems, one boundary, and the business consequence of crossing it.

Everything here runs the real External Order System simulator beside the real PromisePatch
application. The order changes in the order system's own database, through the order system's
own HTTP surface; PromisePatch learns about it through a signed webhook it verifies, an inbox
row it stores, and a worker that applies it. No PromisePatch helper touches an order.

The last test in this module is the one the whole slice exists for. Before the external
mutation, Lena's promise is ``BLOCKED`` -- there is no authored variant that could rescue a
Raspberry Lemon Layer without raspberries. An operator changes her order somewhere else
entirely, and afterwards a *fresh* exception, analysed from scratch, finds her promise
``UNAFFECTED``. Nothing in PromisePatch knows who Lena is. The only thing that changed is what
the order system says she ordered.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest_asyncio
from _intake_support import RASPBERRY_ONLY, Intake
from _intake_support import physical as physical
from _order_system_support import (
    LEMON_CURD,
    LENA_LINE,
    LENA_ORDER,
    RASPBERRY_LEMON,
    Boundary,
    boundary,
)

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import Classification
from promisepatch.config import Settings
from promisepatch.domain import order_mirror
from promisepatch.graph.channel import join_channel

A, B, C, D, E, F = (
    ho.PROMISE_A,
    ho.PROMISE_B,
    ho.PROMISE_C,
    ho.PROMISE_D,
    ho.PROMISE_E,
    ho.PROMISE_F,
)

WORKER = "order-boundary-tests"


@pytest_asyncio.fixture
async def wired(
    physical: Intake,
    runtime_settings: Settings,
    tmp_path: Path,
) -> AsyncIterator[Boundary]:
    """Both systems, running, with their own storage and the wire between them."""
    async with boundary(
        physical.database,
        settings=runtime_settings,
        sqlite_path=tmp_path / "order-simulator.sqlite3",
    ) as running:
        yield running


async def mirror_cycle(wired: Boundary, *, limit: int = 6) -> None:
    """Deliver whatever the order system has queued, and let the worker apply it."""
    await wired.deliver_webhooks()
    for _ in range(limit):
        if (
            await order_mirror.process_one(
                wired.database, worker=WORKER, fetch=wired.client.fetch_order
            )
            is None
        ):
            return


async def classifications(intake: Intake, case_id: Any) -> dict[str, str]:
    return {track.promise_id: track.classification for track in await intake.tracks(case_id)}


async def analysed(intake: Intake) -> Any:
    """One whole exception, from the spoken report to a plan, driven by the real worker."""
    opened = await intake.report()
    await intake.drain()
    await intake.answer(opened.case_id, RASPBERRY_ONLY)
    await intake.drain()
    return opened.case_id


# --------------------------------------------------------------------------- seed parity


def test_both_systems_were_seeded_from_the_same_demo_contract(wired: Boundary) -> None:
    """The order system's book and PromisePatch's mirror describe the same six orders.

    A parity assertion rather than a shared fixture: the two applications author their demo data
    separately, because one of them reading the other's would make the boundary a fiction. What
    keeps them in step is this test failing the moment either side is edited alone.
    """
    from order_simulator import seed

    graph = ho.hollow_oak()
    external = {order.external_id: order for order in wired.simulator.list_orders()}

    assert len(external) == len(graph.orders) == 6
    for order in graph.orders.values():
        theirs = external[order.external_id]
        customer = graph.customers[order.customer_id]
        line = order.lines[0]
        assert theirs.version == seed.INITIAL_VERSION == order.external_version
        assert theirs.customer.external_id == customer.id
        assert theirs.customer.name == customer.name
        # Through the codec that owns this translation, not a string built by hand: the two
        # systems agree on a channel only if PromisePatch's own reader turns the order
        # system's (kind, address) into the string the engine holds.
        assert (
            join_channel(
                theirs.customer.approval_channel.kind, theirs.customer.approval_channel.address
            )
            == customer.approval_channel
        )
        assert theirs.lines[0].external_line_id == line.id
        assert theirs.lines[0].external_item_id == line.recipe_version_id
        assert theirs.lines[0].quantity == line.quantity


def test_the_order_systems_catalogue_is_only_what_the_bakery_authored(
    wired: Boundary,
) -> None:
    """Nothing at runtime creates a variant, and the order system cannot name one that is not."""
    graph = ho.hollow_oak()

    named = {item.external_item_id for item in wired.simulator.catalogue()}

    assert named <= set(graph.versions)


# ------------------------------------------------------------------- the boundary is real


async def test_the_mirror_does_not_move_until_the_event_is_processed(
    wired: Boundary, physical: Intake
) -> None:
    """§42: the two systems really do not share storage, and this is the proof.

    Three observations, in order: the order system has changed, PromisePatch has not, and then
    -- only once the event has crossed and been applied -- it has. If a single table were shared,
    the middle observation would be impossible.
    """
    await wired.operator_changes(item=LEMON_CURD)

    assert wired.external_order().lines[0].external_item_id == LEMON_CURD
    assert wired.external_order().version == 2
    assert await wired.mirrored_version_of(LENA_LINE) == RASPBERRY_LEMON
    assert (await wired.mirrored_order()).external_version == 1

    await wired.deliver_webhooks()
    assert await wired.mirrored_version_of(LENA_LINE) == RASPBERRY_LEMON

    await mirror_cycle(wired)
    assert await wired.mirrored_version_of(LENA_LINE) == LEMON_CURD
    assert (await wired.mirrored_order()).external_version == 2


async def test_an_operator_mutation_crosses_as_one_signed_authenticated_event(
    wired: Boundary,
) -> None:
    await wired.operator_changes(item=LEMON_CURD)

    delivered = await wired.deliver_webhooks()

    rows = await wired.inbox_rows()
    assert delivered == 1
    assert len(rows) == 1
    assert rows[0].source == order_mirror.ORDER_SYSTEM_SOURCE
    assert wired.simulator.undelivered_count() == 0


async def test_a_redelivered_webhook_is_one_inbox_row_and_one_mirror_change(
    wired: Boundary,
) -> None:
    """§33: transport retries must not become watched-state changes."""
    mutation = await wired.operator_changes(item=LEMON_CURD)
    watermark = await _audit_watermark(wired)

    for _ in range(5):
        wired.simulator.record_delivery_failure(
            _last_event_id(wired), error="pretending the answer was lost", retry_at=_now()
        )
        await wired.deliver_webhooks()
    await mirror_cycle(wired)

    assert mutation.version == 2
    assert len(await wired.inbox_rows()) == 1
    assert (await wired.mirrored_order()).external_version == 2
    updates = [
        entry
        for entry in await wired.audits_of(order_mirror.AUDIT_MIRROR_UPDATED)
        if entry.seq > watermark
    ]
    assert len(updates) == 1


async def test_the_authoritative_fetch_answers_with_the_order_systems_own_state(
    wired: Boundary,
) -> None:
    await wired.operator_changes(item=LEMON_CURD)

    fetched = await wired.client.fetch_order(LENA_ORDER)

    assert fetched.version == 2
    assert fetched.lines[0].external_item_id == LEMON_CURD


# ------------------------------------------------------------------------------- Proof A


async def test_an_external_order_change_changes_what_analysis_concludes(
    wired: Boundary, physical: Intake
) -> None:
    """Proof A. The mutation happens outside PromisePatch, and the conclusion follows it.

    The two analyses are of two separate cases, each opened by a worker speaking the same
    sentence and each classified from a graph read fresh at the time. Between them, one thing
    happens: an operator changes an order in another application. There is no branch anywhere in
    PromisePatch that mentions this customer, this order or this variant -- the classification
    moves because the persisted order line moved, and for no other reason.
    """
    before = await classifications(physical, await analysed(physical))

    assert before[D] == Classification.BLOCKED.value

    await wired.operator_changes(item=LEMON_CURD)
    await mirror_cycle(wired)
    assert await wired.mirrored_version_of(LENA_LINE) == LEMON_CURD

    after = await classifications(physical, await analysed(physical))

    assert after[D] == Classification.UNAFFECTED.value


async def test_the_external_change_moves_that_one_promise_and_no_other(
    wired: Boundary, physical: Intake
) -> None:
    """§54: the selectivity half of Proof A, which is the half a demo can fake.

    Changing one customer's order must change exactly one customer's answer. A system that
    re-derived everything from scratch and happened to get four of the six right would pass the
    test above and fail this one.
    """
    before = await classifications(physical, await analysed(physical))

    await wired.operator_changes(item=LEMON_CURD)
    await mirror_cycle(wired)
    after = await classifications(physical, await analysed(physical))

    assert before == {
        A: Classification.AUTO_RECOVERABLE.value,
        B: Classification.APPROVAL_REQUIRED.value,
        C: Classification.BLOCKED.value,
        D: Classification.BLOCKED.value,
        E: Classification.UNAFFECTED.value,
        F: Classification.UNAFFECTED.value,
    }
    assert after == {
        A: Classification.AUTO_RECOVERABLE.value,
        B: Classification.APPROVAL_REQUIRED.value,
        C: Classification.BLOCKED.value,
        D: Classification.UNAFFECTED.value,
        E: Classification.UNAFFECTED.value,
        F: Classification.UNAFFECTED.value,
    }
    assert {promise for promise in before if before[promise] != after[promise]} == {D}


async def test_the_demo_order_is_the_external_mutation_then_the_exception(
    wired: Boundary, physical: Intake
) -> None:
    """§53: the order the video tells it in, with nothing analysed beforehand.

    The mutation lands in an idle system, and the exception that follows is the first thing
    anybody analyses. That is what makes the demo legible: there is no earlier answer for the
    new one to be a correction of.
    """
    await wired.operator_changes(item=LEMON_CURD)
    await mirror_cycle(wired)

    case_id = await analysed(physical)

    assert await classifications(physical, case_id) == {
        A: Classification.AUTO_RECOVERABLE.value,
        B: Classification.APPROVAL_REQUIRED.value,
        C: Classification.BLOCKED.value,
        D: Classification.UNAFFECTED.value,
        E: Classification.UNAFFECTED.value,
        F: Classification.UNAFFECTED.value,
    }


async def test_the_reverse_mutation_puts_the_promise_back(
    wired: Boundary, physical: Intake
) -> None:
    """The other direction, so the proof cannot be a one-way coincidence."""
    await wired.operator_changes(item=LEMON_CURD)
    await mirror_cycle(wired)
    forwards = await classifications(physical, await analysed(physical))

    await wired.operator_changes(item=RASPBERRY_LEMON)
    await mirror_cycle(wired)
    backwards = await classifications(physical, await analysed(physical))

    assert forwards[D] == Classification.UNAFFECTED.value
    assert backwards[D] == Classification.BLOCKED.value
    assert (await wired.mirrored_order()).external_version == 3


# ------------------------------------------------------------------------------- helpers


def _last_event_id(wired: Boundary) -> UUID:
    return wired.simulator.latest_deliveries()[0].event_id


def _now() -> datetime:
    return datetime.now(UTC)


async def _audit_watermark(wired: Boundary) -> int:
    from sqlalchemy import func, select

    from promisepatch.db.models import AuditEvent

    async with wired.database.connect() as connection:
        return int(await connection.scalar(select(func.coalesce(func.max(AuditEvent.seq), 0))) or 0)
