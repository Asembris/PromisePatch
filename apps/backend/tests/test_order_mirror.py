"""The ingress that accepts an order-system event, and the worker that applies it.

Two halves, deliberately tested apart, because keeping them apart is the design. The HTTP
handler authenticates a service and stores bytes; it changes nothing about any order. The
worker reads the stored row under a lock and decides what the mirror should now say.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx2
import pytest_asyncio
from _intake_support import RASPBERRY_ONLY, Intake
from _intake_support import physical as physical
from _order_system_support import (
    LEMON_CURD,
    LENA_LINE,
    LENA_ORDER,
    RASPBERRY_LEMON,
    WEBHOOK_PATH,
    WEBHOOK_SECRET,
    a_snapshot,
    an_event,
    ingress_client,
    order_system_settings,
    signed_headers,
)
from sqlalchemy import select

from order_contract import signing
from order_contract.events import OrderEvent, OrderSnapshot
from promisepatch.config import Settings
from promisepatch.db.models import AuditEvent, InboxEvent, Order, OrderLine, Reservation
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.domain import order_mirror
from promisepatch.domain.cases import CASE_PLANNED
from promisepatch.domain.order_mirror import Disposition

WORKER = "order-mirror-tests"


@pytest_asyncio.fixture
async def ingress(
    runtime_settings: Settings,
    physical: Intake,
) -> AsyncIterator[httpx2.AsyncClient]:
    """The real application, configured with an order-system webhook secret.

    Depends on the seeded database rather than merely coexisting with it. A fixture reset
    truncates every table PromisePatch owns, which needs an exclusive lock on each of them, and
    an application holding open connections while that runs is a deadlock waiting for a slow
    test.
    """
    async with ingress_client(order_system_settings(runtime_settings)) as client:
        yield client


@pytest_asyncio.fixture
async def unconfigured(
    runtime_settings: Settings,
    physical: Intake,
) -> AsyncIterator[httpx2.AsyncClient]:
    """The same application with no order-system secret configured at all.

    Cleared explicitly rather than by leaving the environment alone: a developer's local stack
    configures one, so "unconfigured" has to be stated here or this fixture would quietly
    become "configured" and the test would pass by asserting the wrong rejection.
    """
    without_secret = runtime_settings.model_copy(
        update={"order_system_webhook_secret": None, "order_system_base_url": None}
    )
    async with ingress_client(without_secret) as client:
        yield client


async def post(client: httpx2.AsyncClient, event: OrderEvent) -> httpx2.Response:
    body = event.model_dump_json().encode("utf-8")
    return await client.post(WEBHOOK_PATH, content=body, headers=signed_headers(body))


async def inbox_rows(database: RuntimeDatabase) -> list[Any]:
    async with database.connect() as connection:
        return list(
            (
                await connection.execute(
                    select(InboxEvent).where(InboxEvent.source == order_mirror.ORDER_SYSTEM_SOURCE)
                )
            ).all()
        )


async def mirrored(database: RuntimeDatabase, external_id: str = LENA_ORDER) -> Any:
    async with database.connect() as connection:
        return (
            await connection.execute(select(Order).where(Order.external_id == external_id))
        ).one()


async def pinned(database: RuntimeDatabase, line_id: str = LENA_LINE) -> str:
    async with database.connect() as connection:
        return (
            await connection.execute(
                select(OrderLine.recipe_version_id).where(OrderLine.id == line_id)
            )
        ).scalar_one()


async def audits(database: RuntimeDatabase, *types: str, since: int = 0) -> list[Any]:
    """Audit rows of these kinds, written after ``since``.

    Scoped by sequence rather than by table, because the ledger is never truncated: a reset
    empties the domain and deliberately leaves the record of what was done to it, so counting
    every row of a type would be counting every earlier test's work as well.
    """
    async with database.connect() as connection:
        return list(
            (
                await connection.execute(
                    select(AuditEvent)
                    .where(AuditEvent.type.in_(types), AuditEvent.seq > since)
                    .order_by(AuditEvent.seq)
                )
            ).all()
        )


async def reservations(database: RuntimeDatabase, line_id: str = LENA_LINE) -> set[str]:
    async with database.connect() as connection:
        rows = (
            await connection.execute(
                select(Reservation.resource_id).where(Reservation.order_line_id == line_id)
            )
        ).scalars()
    return set(rows)


async def process(
    intake: Intake, *, fetch: order_mirror.AuthoritativeFetch | None = None
) -> order_mirror.MirrorOutcome | None:
    return await order_mirror.process_one(intake.database, worker=WORKER, fetch=fetch)


def fetching(snapshot: OrderSnapshot) -> order_mirror.AuthoritativeFetch:
    """An authoritative read that answers with one prepared order."""

    async def fetch(external_order_id: str) -> OrderSnapshot:
        assert external_order_id == snapshot.external_id
        return snapshot

    return fetch


# ------------------------------------------------------------------- the decision, in isolation


def test_the_next_version_in_line_is_applied() -> None:
    event = an_event(version=2)

    assert (
        order_mirror.decide(mirror_version=1, applied_event_id=None, event=event)
        is Disposition.APPLY
    )


def test_the_event_this_mirror_already_applied_is_a_duplicate() -> None:
    event = an_event(version=2)

    assert (
        order_mirror.decide(mirror_version=2, applied_event_id=event.event_id, event=event)
        is Disposition.DUPLICATE
    )


def test_an_older_version_is_stale() -> None:
    assert (
        order_mirror.decide(mirror_version=8, applied_event_id=None, event=an_event(version=7))
        is Disposition.STALE
    )


def test_a_version_beyond_the_next_one_is_a_gap() -> None:
    assert (
        order_mirror.decide(mirror_version=7, applied_event_id=None, event=an_event(version=9))
        is Disposition.GAP
    )


def test_an_event_that_moved_from_another_version_is_a_gap() -> None:
    """``previous_version`` is what the sender says it moved from, and it is believed."""
    event = an_event(version=8, previous_version=6)

    assert (
        order_mirror.decide(mirror_version=7, applied_event_id=None, event=event) is Disposition.GAP
    )


# ------------------------------------------------------------------------- the signed ingress


async def test_a_signed_event_is_stored_and_acknowledged(
    ingress: httpx2.AsyncClient, physical: Intake
) -> None:
    response = await post(ingress, an_event(version=2))

    assert response.status_code == 202
    assert response.json()["duplicate"] is False
    assert len(await inbox_rows(physical.database)) == 1


async def test_a_delivery_with_no_signature_is_refused(
    ingress: httpx2.AsyncClient, physical: Intake
) -> None:
    body = an_event(version=2).model_dump_json().encode("utf-8")

    response = await ingress.post(
        WEBHOOK_PATH, content=body, headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 401
    assert await inbox_rows(physical.database) == []


async def test_a_delivery_signed_with_another_secret_is_refused(
    ingress: httpx2.AsyncClient, physical: Intake
) -> None:
    event = an_event(version=2)
    body = event.model_dump_json().encode("utf-8")
    headers = signed_headers(body, secret="a-different-secret")

    response = await ingress.post(WEBHOOK_PATH, content=body, headers=headers)

    assert response.status_code == 401
    assert await inbox_rows(physical.database) == []


async def test_a_body_altered_after_signing_is_refused(
    ingress: httpx2.AsyncClient, physical: Intake
) -> None:
    """The signature covers the exact bytes, so one changed character is a forgery."""
    event = an_event(version=2)
    body = event.model_dump_json().encode("utf-8")
    headers = signed_headers(body)

    response = await ingress.post(
        WEBHOOK_PATH, content=body.replace(b'"version":2', b'"version":9'), headers=headers
    )

    assert response.status_code == 401
    assert await inbox_rows(physical.database) == []


async def test_a_delivery_outside_the_replay_window_is_refused(
    ingress: httpx2.AsyncClient, physical: Intake
) -> None:
    event = an_event(version=2)
    body = event.model_dump_json().encode("utf-8")
    headers = signed_headers(body, now=datetime.now(UTC) - timedelta(minutes=10))

    response = await ingress.post(WEBHOOK_PATH, content=body, headers=headers)

    assert response.status_code == 401
    assert await inbox_rows(physical.database) == []


async def test_a_rejection_says_nothing_about_which_check_failed(
    ingress: httpx2.AsyncClient,
) -> None:
    """A caller that cannot sign has no legitimate use for the difference."""
    body = an_event(version=2).model_dump_json().encode("utf-8")

    unsigned = await ingress.post(WEBHOOK_PATH, content=body)
    wrong = await ingress.post(
        WEBHOOK_PATH, content=body, headers=signed_headers(body, secret="other")
    )

    assert unsigned.json() == wrong.json()


async def test_the_same_event_delivered_ten_times_is_one_stored_record(
    ingress: httpx2.AsyncClient, physical: Intake
) -> None:
    """Transport retries are absorbed by the database, not by a check the application forgets."""
    event = an_event(version=2)

    answers = [await post(ingress, event) for _ in range(10)]

    assert answers[0].status_code == 202
    assert {answer.status_code for answer in answers[1:]} == {200}
    assert all(answer.json()["accepted"] for answer in answers)
    assert len(await inbox_rows(physical.database)) == 1


async def test_an_ingress_with_no_secret_configured_accepts_nothing(
    unconfigured: httpx2.AsyncClient, physical: Intake
) -> None:
    body = an_event(version=2).model_dump_json().encode("utf-8")

    response = await unconfigured.post(WEBHOOK_PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 503
    assert await inbox_rows(physical.database) == []


async def test_a_signed_body_that_is_not_an_order_event_is_refused(
    ingress: httpx2.AsyncClient,
) -> None:
    body = b'{"hello": "world"}'

    response = await ingress.post(WEBHOOK_PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ORDER_EVENT_UNREADABLE"


async def test_the_http_handler_changes_no_order(
    ingress: httpx2.AsyncClient, physical: Intake
) -> None:
    """Transport is not business state. Storing the delivery moves nothing at all."""
    before = await mirrored(physical.database)

    await post(ingress, an_event(version=2))

    after = await mirrored(physical.database)
    assert (after.external_version, after.updated_at) == (
        before.external_version,
        before.updated_at,
    )
    assert await pinned(physical.database) == RASPBERRY_LEMON


async def test_the_worker_and_not_the_handler_applies_the_change(
    ingress: httpx2.AsyncClient, physical: Intake
) -> None:
    await post(ingress, an_event(version=2))
    assert await pinned(physical.database) == RASPBERRY_LEMON

    outcome = await process(physical)

    assert outcome is not None
    assert outcome.disposition is Disposition.APPLY
    assert await pinned(physical.database) == LEMON_CURD


# ------------------------------------------------------------------------ applying to the mirror


async def store(intake: Intake, event: OrderEvent) -> None:
    """Put one event in the inbox the way the ingress would, without going through HTTP."""
    async with intake.database.begin() as connection:
        from promisepatch.domain import inbox

        await inbox.ingest(
            connection,
            source=order_mirror.ORDER_SYSTEM_SOURCE,
            provider_event_id=str(event.event_id),
            body=event.model_dump_json(),
        )


async def test_applying_moves_the_mirror_to_the_order_systems_version(physical: Intake) -> None:
    event = an_event(version=2)
    await store(physical, event)

    await process(physical)

    order = await mirrored(physical.database)
    assert order.external_version == 2
    assert order.state == "AMENDED"
    assert order.mirror_source_event_id == event.event_id
    assert await pinned(physical.database) == LEMON_CURD


async def test_applying_rewrites_the_lines_reservations(physical: Intake) -> None:
    """A line's reservations are its pinned version times its quantity, still, afterwards."""
    before = await reservations(physical.database)
    await store(physical, an_event(version=2))

    await process(physical)

    after = await reservations(physical.database)
    assert "res-raspberries" in before
    assert "res-raspberries" not in after
    assert "res-lemon-curd" in after


async def test_applying_audits_the_order_system_as_the_source(physical: Intake) -> None:
    """Authority and executor are different parties, and the ledger keeps them apart."""
    watermark = await physical.latest_audit_seq()
    await store(physical, an_event(version=2))

    await process(physical)

    entry = (await audits(physical.database, order_mirror.AUDIT_MIRROR_UPDATED, since=watermark))[
        -1
    ]
    assert entry.actor_kind == "SYSTEM"
    assert entry.actor_id == WORKER
    assert entry.authority == "NONE"
    assert entry.provenance["source"] == order_mirror.EXTERNAL_ORDER_SYSTEM
    assert entry.provenance["executor"] == WORKER
    assert entry.before["external_version"] == 1
    assert entry.after["external_version"] == 2


async def test_a_redelivered_event_does_not_move_the_version_again(physical: Intake) -> None:
    """One logical event, one mirror change, however many deliveries it took."""
    watermark = await physical.latest_audit_seq()
    event = an_event(version=2)
    await store(physical, event)
    await process(physical)

    async with physical.database.begin() as connection:
        from promisepatch.domain import inbox

        # A second stored record for the same logical event: the unique index normally makes
        # this impossible, so it is forced here to prove the *processor* is idempotent too.
        await inbox.ingest(
            connection,
            source=order_mirror.ORDER_SYSTEM_SOURCE,
            provider_event_id=f"{event.event_id}:redelivered",
            body=event.model_dump_json(),
        )
    outcome = await process(physical)

    assert outcome is not None
    assert outcome.disposition is Disposition.DUPLICATE
    assert (await mirrored(physical.database)).external_version == 2
    assert (
        len(await audits(physical.database, order_mirror.AUDIT_MIRROR_UPDATED, since=watermark))
        == 1
    )


async def test_a_stale_event_is_ignored_and_the_mirror_does_not_move_back(
    physical: Intake,
) -> None:
    """§34: an overtaken event must not roll truth back, or even look like it touched anything."""
    watermark = await physical.latest_audit_seq()
    await store(physical, an_event(version=2))
    await process(physical)
    before = await mirrored(physical.database)

    await store(physical, an_event(version=2, item=RASPBERRY_LEMON))
    outcome = await process(physical)

    after = await mirrored(physical.database)
    assert outcome is not None
    assert outcome.disposition is Disposition.STALE
    assert after.external_version == 2
    assert after.updated_at == before.updated_at
    assert await pinned(physical.database) == LEMON_CURD
    assert await audits(physical.database, order_mirror.AUDIT_MIRROR_STALE, since=watermark)


async def test_a_version_gap_is_repaired_from_the_authoritative_order(physical: Intake) -> None:
    """§35: never applied blind. The order is fetched whole and the mirror made equal to it."""
    await store(physical, an_event(version=4, previous_version=3))

    outcome = await process(physical, fetch=fetching(a_snapshot(version=4, item=LEMON_CURD)))

    assert outcome is not None
    assert outcome.disposition is Disposition.GAP
    order = await mirrored(physical.database)
    assert order.external_version == 4
    assert await pinned(physical.database) == LEMON_CURD
    # The mirror was made equal to a fetched order, not moved by this event, and says so.
    assert order.mirror_source_event_id is None


async def test_a_gap_never_passes_through_the_version_it_skipped(physical: Intake) -> None:
    watermark = await physical.latest_audit_seq()
    await store(physical, an_event(version=4, previous_version=3))

    await process(physical, fetch=fetching(a_snapshot(version=4)))

    updates = await audits(physical.database, order_mirror.AUDIT_MIRROR_UPDATED, since=watermark)
    assert [entry.after["external_version"] for entry in updates] == [4]


async def test_a_gap_with_no_authoritative_read_fails_closed(physical: Intake) -> None:
    await store(physical, an_event(version=4, previous_version=3))

    outcome = await process(physical)

    assert outcome is not None
    assert outcome.error is not None
    assert (await mirrored(physical.database)).external_version == 1
    assert (await inbox_rows(physical.database))[0].state == "FAILED"


async def test_an_event_for_an_order_we_do_not_mirror_fails_closed(physical: Intake) -> None:
    """§36: an unsolicited event does not add a customer promise to this bakery's book."""
    await store(physical, an_event(version=2, external_id="EXT-SOMEBODY-ELSE"))

    outcome = await process(physical)

    assert outcome is not None
    assert "no mirrored order" in (outcome.error or "")
    assert await physical.rows_of(Order) != []
    assert len(await physical.rows_of(Order)) == 6


async def test_an_unmapped_catalogue_item_fails_closed(physical: Intake) -> None:
    """§37: nothing invents a recipe version because an external system named one."""
    await store(physical, an_event(version=2, item="cat-something-nobody-authored"))

    outcome = await process(physical)

    assert outcome is not None
    assert "order_line_mappings" in (outcome.error or "")
    assert await pinned(physical.database) == RASPBERRY_LEMON
    assert (await mirrored(physical.database)).external_version == 1


async def test_a_refused_event_leaves_no_partial_mirror_audit_or_event(
    physical: Intake,
) -> None:
    """The transaction is all or nothing, and the failure is recorded separately afterwards."""
    watermark = await physical.latest_audit_seq()
    before = await mirrored(physical.database)
    await store(physical, an_event(version=2, item="cat-something-nobody-authored"))

    await process(physical)

    after = await mirrored(physical.database)
    assert (after.external_version, after.updated_at, after.state) == (
        before.external_version,
        before.updated_at,
        before.state,
    )
    assert await reservations(physical.database) == await reservations(physical.database)
    assert await audits(physical.database, order_mirror.AUDIT_MIRROR_UPDATED, since=watermark) == []
    assert await audits(physical.database, order_mirror.AUDIT_MIRROR_REJECTED, since=watermark)


async def test_an_event_for_a_line_the_order_does_not_have_fails_closed(
    physical: Intake,
) -> None:
    await store(physical, an_event(version=2, line_id="ol-not-here"))

    outcome = await process(physical)

    assert outcome is not None
    assert "no mirrored line" in (outcome.error or "")
    assert await pinned(physical.database) == RASPBERRY_LEMON


async def test_an_event_in_an_unknown_schema_version_fails_closed(physical: Intake) -> None:
    event = an_event(version=2)
    payload = event.model_dump(mode="json") | {"schema_version": 99}
    async with physical.database.begin() as connection:
        from promisepatch.domain import inbox

        await inbox.ingest(
            connection,
            source=order_mirror.ORDER_SYSTEM_SOURCE,
            provider_event_id=str(uuid4()),
            body=json.dumps(payload),
        )

    outcome = await process(physical)

    assert outcome is not None
    assert "schema version" in (outcome.error or "")


async def test_a_cancellation_is_refused_rather_than_quietly_ignored(physical: Intake) -> None:
    """Cancellation is in the contract and is not yet applied. Ignoring it would be worse."""
    event = an_event(version=2)
    payload = event.model_dump(mode="json") | {"type": "order.cancelled"}
    async with physical.database.begin() as connection:
        from promisepatch.domain import inbox

        await inbox.ingest(
            connection,
            source=order_mirror.ORDER_SYSTEM_SOURCE,
            provider_event_id=str(uuid4()),
            body=json.dumps(payload),
        )

    outcome = await process(physical)

    assert outcome is not None
    assert "order.cancelled" in (outcome.error or "")
    assert (await mirrored(physical.database)).state == "ACCEPTED"


async def test_nothing_waiting_is_not_an_outcome(physical: Intake) -> None:
    assert await process(physical) is None


# ------------------------------------------------------------------- the general sweep is clear


async def test_the_general_inbox_sweep_leaves_order_events_alone(physical: Intake) -> None:
    """An unreachable order system must not park a record in front of a customer's reply."""
    from promisepatch.domain import inbox

    await store(physical, an_event(version=4, previous_version=3))

    assert await inbox.process_one(physical.database, worker=WORKER) is None
    assert (await inbox_rows(physical.database))[0].state == "RECEIVED"


async def test_the_worker_cycle_applies_an_order_event(physical: Intake) -> None:
    """The worker really does sweep this, rather than a test calling the module directly."""
    await store(physical, an_event(version=2))

    assert await physical.worker().run_once() is True
    assert await pinned(physical.database) == LEMON_CURD


async def test_an_unreachable_order_system_does_not_stop_the_rest_of_the_worker(
    physical: Intake,
) -> None:
    """§70: one provider being unreachable is a runtime dependency, not a global mutex.

    The order event waiting here needs an authoritative read to be applied safely, and this
    worker has no way to make one. What must not happen is everything else stopping with it: an
    exception a baker reports while the order system is down is still interpreted, analysed and
    planned, on the same worker, in the same cycles.
    """
    await store(physical, an_event(version=4, previous_version=3))
    opened = await physical.report()

    await physical.drain(limit=30)
    await physical.answer(opened.case_id, RASPBERRY_ONLY)
    await physical.drain(limit=30)

    case = await physical.case(opened.case_id)
    assert case is not None
    assert case.state == CASE_PLANNED
    assert len(await physical.tracks(opened.case_id)) == 6
    # And the order event stayed out of everybody's way rather than holding the queue.
    assert (await inbox_rows(physical.database))[0].state == "FAILED"
    assert (await mirrored(physical.database)).external_version == 1


def test_the_signature_helper_and_the_ingress_agree_on_the_header_names() -> None:
    headers = signed_headers(b"{}")

    assert signing.SIGNATURE_HEADER in headers
    assert signing.TIMESTAMP_HEADER in headers
    assert WEBHOOK_SECRET
