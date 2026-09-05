"""What this order system guarantees about its own state.

Every test here is about a claim PromisePatch is entitled to make on the other side of the
integration: that a version moves once per change, that a retry is not a second change, and
that an amendment planned against an old version is refused rather than applied.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from order_contract import amendments
from order_contract.events import EVENT_ORDER_UPDATED
from order_simulator import seed
from order_simulator.store import OrderStore, SimulatorError

LENA_ORDER = "EXT-D"
LENA_LINE = "ol-d"
RASPBERRY_LEMON = "rv-raspberry-lemon-2"
LEMON_CURD = "rv-lemon-curd-1"

NOW = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


def an_amendment(**overrides: object) -> amendments.AmendmentRequest:
    fields: dict[str, object] = {
        "external_order_id": LENA_ORDER,
        "expected_version": 1,
        "external_line_id": LENA_LINE,
        "from_item_id": RASPBERRY_LEMON,
        "to_item_id": LEMON_CURD,
        "correlation": amendments.AmendmentCorrelation(
            case_id=uuid4(), track_id=uuid4(), option_id=uuid4()
        ),
    }
    fields.update(overrides)
    return amendments.AmendmentRequest(**fields)


# ------------------------------------------------------------------------------------- seed


def test_the_seeded_order_book_is_the_demo_order_book(store: OrderStore) -> None:
    orders = store.list_orders()

    assert [order.external_id for order in orders] == [
        "EXT-A",
        "EXT-B",
        "EXT-C",
        "EXT-D",
        "EXT-E",
        "EXT-F",
    ]
    assert {order.version for order in orders} == {seed.INITIAL_VERSION}
    assert {order.state for order in orders} == {seed.ORDER_STATE_ACCEPTED}


def test_lena_starts_on_the_raspberry_lemon_variant(store: OrderStore) -> None:
    """The before-state of Proof A, in the system that owns it."""
    order = store.read_order(LENA_ORDER)

    assert order.customer.name == "Lena Fischer"
    assert order.lines[0].external_item_id == RASPBERRY_LEMON
    assert order.version == 1


def test_seeding_twice_does_not_change_the_order_book(store: OrderStore) -> None:
    """A restart re-runs initialisation; it must not re-seed over live state."""
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )
    store.initialize()

    assert store.read_order(LENA_ORDER).version == 2


def test_a_reset_puts_the_order_book_back(store: OrderStore) -> None:
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )
    store.reset()

    assert store.read_order(LENA_ORDER).lines[0].external_item_id == RASPBERRY_LEMON
    assert store.read_order(LENA_ORDER).version == 1
    assert store.event_count() == 0


# -------------------------------------------------------------------------- operator change


def test_an_operator_change_moves_the_version_exactly_once(store: OrderStore) -> None:
    mutation = store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD, now=NOW
    )

    assert mutation.result.previous_version == 1
    assert mutation.result.external_version == 2
    assert store.read_order(LENA_ORDER).version == 2
    assert store.read_order(LENA_ORDER).lines[0].external_item_id == LEMON_CURD


def test_a_change_commits_its_event_with_the_order(store: OrderStore) -> None:
    """The event is not a best-effort afterthought: it is in the same transaction."""
    mutation = store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD, now=NOW
    )

    assert store.event_count(LENA_ORDER) == 1
    assert mutation.event.type == EVENT_ORDER_UPDATED
    assert mutation.event.previous_version == 1
    assert mutation.event.order.version == 2
    assert mutation.event.changed_line_ids == (LENA_LINE,)
    assert mutation.event.order.lines[0].external_item_id == LEMON_CURD
    assert mutation.event.command is None


def test_a_change_queues_exactly_one_delivery(store: OrderStore) -> None:
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )

    assert store.undelivered_count() == 1
    assert [delivery.state for delivery in store.latest_deliveries()] == ["PENDING"]


def test_two_changes_produce_two_versions_and_two_events(store: OrderStore) -> None:
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=RASPBERRY_LEMON
    )

    assert store.read_order(LENA_ORDER).version == 3
    assert store.event_count(LENA_ORDER) == 2


def test_an_item_outside_the_catalogue_is_refused(store: OrderStore) -> None:
    """Nothing at runtime invents a product variant, here or on the other side."""
    with pytest.raises(SimulatorError) as refusal:
        store.operator_change(
            external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id="rv-invented"
        )

    assert refusal.value.code == amendments.ERROR_UNKNOWN_ITEM
    assert store.read_order(LENA_ORDER).version == 1


def test_an_unknown_order_is_refused(store: OrderStore) -> None:
    with pytest.raises(SimulatorError) as refusal:
        store.operator_change(
            external_order_id="EXT-NOWHERE", external_line_id=LENA_LINE, to_item_id=LEMON_CURD
        )

    assert refusal.value.code == amendments.ERROR_ORDER_NOT_FOUND


def test_an_unknown_line_is_refused(store: OrderStore) -> None:
    with pytest.raises(SimulatorError) as refusal:
        store.operator_change(
            external_order_id=LENA_ORDER, external_line_id="ol-nowhere", to_item_id=LEMON_CURD
        )

    assert refusal.value.code == amendments.ERROR_LINE_NOT_FOUND


# ------------------------------------------------------------------------------- amendments


def test_an_amendment_applies_and_names_its_command(store: OrderStore) -> None:
    mutation = store.amend(an_amendment(), idempotency_key="pp:amend:one", now=NOW)

    assert mutation.result.external_version == 2
    assert mutation.result.replayed is False
    assert mutation.event.command is not None
    assert mutation.event.command.idempotency_key == "pp:amend:one"
    assert mutation.event.command.provider_ref == mutation.result.provider_ref


def test_the_same_key_and_request_produce_one_mutation_and_the_same_answer(
    store: OrderStore,
) -> None:
    """The uncertain window, from the provider's side: one effect, two answers.

    The same request object, because that is what a redelivery presents: PromisePatch stores
    the payload on the outbox row and sends the row again, never a freshly built request.
    """
    request = an_amendment()
    first = store.amend(request, idempotency_key="pp:amend:one", now=NOW)
    second = store.amend(request, idempotency_key="pp:amend:one", now=NOW)

    assert second.result.provider_ref == first.result.provider_ref
    assert second.result.external_version == first.result.external_version
    assert second.result.replayed is True
    assert second.event.event_id == first.event.event_id
    assert store.read_order(LENA_ORDER).version == 2
    assert store.event_count(LENA_ORDER) == 1


def test_the_same_key_with_a_different_request_is_refused(store: OrderStore) -> None:
    """Two amendments claiming one identity: answering either would discard the other."""
    store.amend(an_amendment(), idempotency_key="pp:amend:one", now=NOW)

    with pytest.raises(SimulatorError) as refusal:
        store.amend(
            an_amendment(to_item_id=RASPBERRY_LEMON, expected_version=2),
            idempotency_key="pp:amend:one",
        )

    assert refusal.value.code == amendments.ERROR_IDEMPOTENCY_CONFLICT
    assert store.read_order(LENA_ORDER).version == 2


def test_an_amendment_planned_against_an_older_version_is_refused(store: OrderStore) -> None:
    """The whole of optimistic concurrency: an old plan may not overwrite newer truth."""
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )

    with pytest.raises(SimulatorError) as refusal:
        store.amend(an_amendment(expected_version=1), idempotency_key="pp:amend:stale")

    assert refusal.value.code == amendments.ERROR_VERSION_CONFLICT
    assert refusal.value.current_version == 2
    assert store.read_order(LENA_ORDER).lines[0].external_item_id == LEMON_CURD
    assert store.event_count(LENA_ORDER) == 1


def test_a_refused_amendment_leaves_no_idempotency_record(store: OrderStore) -> None:
    """A key is spent on a change that happened, never on one that was refused."""
    with pytest.raises(SimulatorError):
        store.amend(an_amendment(expected_version=9), idempotency_key="pp:amend:stale")

    assert store.commands() == []
    assert store.read_order(LENA_ORDER).version == 1


def test_an_amendment_whose_line_already_moved_is_refused(store: OrderStore) -> None:
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )

    with pytest.raises(SimulatorError) as refusal:
        store.amend(an_amendment(expected_version=2), idempotency_key="pp:amend:moved")

    assert refusal.value.code == amendments.ERROR_LINE_MOVED


def test_an_amendment_in_an_unsupported_schema_version_is_refused(store: OrderStore) -> None:
    request = an_amendment().model_copy(update={"schema_version": 99})

    with pytest.raises(SimulatorError) as refusal:
        store.amend(request, idempotency_key="pp:amend:future")

    assert refusal.value.code == amendments.ERROR_SCHEMA_VERSION


# --------------------------------------------------------------------------------- delivery


def test_a_claim_records_the_attempt_before_anything_is_sent(store: OrderStore) -> None:
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )

    claim = store.claim_delivery(now=NOW, lease=timedelta(seconds=60))

    assert claim is not None
    assert claim.attempts == 1
    assert [delivery.state for delivery in store.latest_deliveries()] == ["IN_FLIGHT"]


def test_a_retry_delivers_the_same_event_id(store: OrderStore) -> None:
    """One mutation, one event id, however many attempts it takes to hand it over."""
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )
    first = store.claim_delivery(now=NOW, lease=timedelta(seconds=60))
    assert first is not None
    store.record_delivery_failure(first.event_id, error="connection refused", retry_at=NOW)

    second = store.claim_delivery(now=NOW, lease=timedelta(seconds=60))

    assert second is not None
    assert second.event_id == first.event_id
    assert second.attempts == 2
    assert store.event_count(LENA_ORDER) == 1


def test_a_delivery_that_is_not_due_yet_is_not_claimed(store: OrderStore) -> None:
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )
    claim = store.claim_delivery(now=NOW, lease=timedelta(seconds=60))
    assert claim is not None
    store.record_delivery_failure(
        claim.event_id, error="connection refused", retry_at=NOW + timedelta(seconds=30)
    )

    assert store.claim_delivery(now=NOW, lease=timedelta(seconds=60)) is None
    assert store.claim_delivery(now=NOW + timedelta(seconds=31), lease=timedelta(seconds=60))


def test_an_event_committed_before_a_crash_is_still_waiting_after_a_restart(
    database_path: Path,
) -> None:
    """The durability claim: an order that changed cannot lose the news of it.

    The first store commits a mutation and dies mid-delivery -- no clean shutdown, no
    hand-over. A second store opens the same file and finds the event queued rather than lost
    or stranded in flight.
    """
    first = OrderStore(database_path)
    first.initialize()
    first.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )
    claim = first.claim_delivery(now=NOW, lease=timedelta(seconds=60))
    assert claim is not None

    restarted = OrderStore(database_path)
    restarted.initialize()

    assert restarted.read_order(LENA_ORDER).lines[0].external_item_id == LEMON_CURD
    assert restarted.undelivered_count() == 1
    resumed = restarted.claim_delivery(now=NOW, lease=timedelta(seconds=60))
    assert resumed is not None
    assert resumed.event_id == claim.event_id


def test_a_delivered_event_is_not_claimed_again(store: OrderStore) -> None:
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD
    )
    claim = store.claim_delivery(now=NOW, lease=timedelta(seconds=60))
    assert claim is not None
    store.record_delivered(claim.event_id, now=NOW)

    assert store.claim_delivery(now=NOW, lease=timedelta(seconds=60)) is None
    assert store.undelivered_count() == 0


def test_the_stored_event_body_is_what_gets_delivered(store: OrderStore) -> None:
    mutation = store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD, now=NOW
    )
    claim = store.claim_delivery(now=NOW, lease=timedelta(seconds=60))

    assert claim is not None
    assert claim.body == mutation.event.model_dump_json()
