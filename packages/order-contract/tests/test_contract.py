"""The contract's own guarantees: what it refuses, and what a signature actually covers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from order_contract import amendments, events, signing

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
SECRET = "a-local-test-secret"


def a_snapshot(*, version: int = 1, item: str = "cat-one") -> events.OrderSnapshot:
    return events.OrderSnapshot(
        external_id="EXT-D",
        version=version,
        state="ACCEPTED",
        customer=events.CustomerRef(
            external_id="cus-lena",
            name="Lena Fischer",
            approval_channel=events.ChannelRef(kind="telegram", address="1004"),
        ),
        due_at=NOW,
        lines=(events.OrderLineRef(external_line_id="ol-d", external_item_id=item, quantity=1),),
    )


def an_event(**overrides: object) -> events.OrderEvent:
    fields: dict[str, object] = {
        "event_id": uuid4(),
        "type": events.EVENT_ORDER_UPDATED,
        "occurred_at": NOW,
        "previous_version": 1,
        "changed_line_ids": ("ol-d",),
        "order": a_snapshot(version=2),
    }
    fields.update(overrides)
    return events.OrderEvent(**fields)


# --------------------------------------------------------------------------- the envelope


def test_an_event_carries_the_whole_authoritative_order() -> None:
    """A snapshot rather than a diff, so a receiver can apply it without the earlier ones."""
    event = an_event()

    assert event.schema_version == events.SCHEMA_VERSION
    assert event.order.version == 2
    assert event.previous_version == 1
    assert event.order.lines[0].external_item_id == "cat-one"


def test_a_previous_version_at_or_above_the_new_one_is_refused() -> None:
    with pytest.raises(ValidationError, match="previous_version"):
        an_event(previous_version=2)


def test_a_changed_line_the_order_does_not_have_is_refused() -> None:
    """A change naming a line nobody can see would be an instruction with no referent."""
    with pytest.raises(ValidationError, match="changed_line_ids"):
        an_event(changed_line_ids=("ol-absent",))


def test_two_lines_with_one_identity_are_refused() -> None:
    line = events.OrderLineRef(external_line_id="ol-d", external_item_id="cat-one", quantity=1)
    with pytest.raises(ValidationError, match="duplicate"):
        events.OrderSnapshot(
            external_id="EXT-D",
            version=1,
            state="ACCEPTED",
            customer=a_snapshot().customer,
            due_at=NOW,
            lines=(line, line),
        )


def test_an_undeclared_field_is_refused_rather_than_dropped() -> None:
    """A sender adding a field is a contract change, not something to silently ignore."""
    payload = an_event().model_dump(mode="json")
    payload["urgency"] = "high"

    with pytest.raises(ValidationError, match="urgency"):
        events.OrderEvent.model_validate(payload)


def test_an_event_round_trips_through_json_unchanged() -> None:
    event = an_event()

    assert events.OrderEvent.model_validate_json(event.model_dump_json()) == event


def test_a_non_positive_quantity_is_refused() -> None:
    with pytest.raises(ValidationError):
        events.OrderLineRef(external_line_id="ol-d", external_item_id="cat-one", quantity=0)


# -------------------------------------------------------------------------- the amendment


def an_amendment(**overrides: object) -> amendments.AmendmentRequest:
    fields: dict[str, object] = {
        "external_order_id": "EXT-A",
        "expected_version": 1,
        "external_line_id": "ol-a",
        "from_item_id": "cat-one",
        "to_item_id": "cat-two",
        "correlation": amendments.AmendmentCorrelation(
            case_id=uuid4(), track_id=uuid4(), option_id=uuid4()
        ),
    }
    fields.update(overrides)
    return amendments.AmendmentRequest(**fields)


def test_an_amendment_states_the_version_it_was_planned_against() -> None:
    assert an_amendment().expected_version == 1


def test_an_amendment_without_an_expected_version_cannot_be_built() -> None:
    """Optimistic concurrency is not optional: an amendment with no precondition is a clobber."""
    with pytest.raises(ValidationError, match="expected_version"):
        amendments.AmendmentRequest.model_validate(
            an_amendment().model_dump(mode="json") | {"expected_version": 0}
        )


def test_every_deterministic_refusal_has_a_named_code() -> None:
    """A refusal a caller cannot branch on would have to be retried to be understood."""
    assert amendments.ERROR_VERSION_CONFLICT in amendments.DETERMINISTIC_REFUSALS
    assert amendments.ERROR_IDEMPOTENCY_CONFLICT in amendments.DETERMINISTIC_REFUSALS
    assert len(amendments.DETERMINISTIC_REFUSALS) == 8


# --------------------------------------------------------------------------- the signature


def test_a_signature_verifies_against_the_bytes_it_was_made_over() -> None:
    body = an_event().model_dump_json().encode("utf-8")
    headers = signing.headers_for(secret=SECRET, body=body, now=NOW)

    signing.verify(
        secret=SECRET,
        body=body,
        timestamp=headers[signing.TIMESTAMP_HEADER],
        signature=headers[signing.SIGNATURE_HEADER],
        now=NOW,
    )


def test_a_body_altered_after_signing_is_refused() -> None:
    body = b'{"amount": 1}'
    headers = signing.headers_for(secret=SECRET, body=body, now=NOW)

    with pytest.raises(signing.SignatureError, match="does not match"):
        signing.verify(
            secret=SECRET,
            body=b'{"amount": 9}',
            timestamp=headers[signing.TIMESTAMP_HEADER],
            signature=headers[signing.SIGNATURE_HEADER],
            now=NOW,
        )


def test_another_secret_produces_another_signature() -> None:
    body = b"{}"
    headers = signing.headers_for(secret="one-secret", body=body, now=NOW)

    with pytest.raises(signing.SignatureError, match="does not match"):
        signing.verify(
            secret="another-secret",
            body=body,
            timestamp=headers[signing.TIMESTAMP_HEADER],
            signature=headers[signing.SIGNATURE_HEADER],
            now=NOW,
        )


def test_missing_headers_are_refused() -> None:
    with pytest.raises(signing.SignatureError, match="missing"):
        signing.verify(secret=SECRET, body=b"{}", timestamp=None, signature=None, now=NOW)


def test_a_signature_outside_the_window_is_refused() -> None:
    """A recorded delivery must not stay replayable for ever."""
    body = b"{}"
    headers = signing.headers_for(secret=SECRET, body=body, now=NOW)

    with pytest.raises(signing.SignatureError, match="replay window"):
        signing.verify(
            secret=SECRET,
            body=body,
            timestamp=headers[signing.TIMESTAMP_HEADER],
            signature=headers[signing.SIGNATURE_HEADER],
            now=NOW + timedelta(minutes=6),
        )


def test_a_signature_from_the_near_future_is_accepted() -> None:
    """Clocks drift in both directions; only one of them being tolerated would be arbitrary."""
    body = b"{}"
    headers = signing.headers_for(secret=SECRET, body=body, now=NOW + timedelta(minutes=1))

    signing.verify(
        secret=SECRET,
        body=body,
        timestamp=headers[signing.TIMESTAMP_HEADER],
        signature=headers[signing.SIGNATURE_HEADER],
        now=NOW,
    )


def test_an_unreadable_timestamp_is_refused() -> None:
    with pytest.raises(signing.SignatureError, match="unreadable"):
        signing.verify(
            secret=SECRET, body=b"{}", timestamp="yesterday", signature="ab" * 32, now=NOW
        )


def test_an_oversized_body_is_refused_before_the_secret_is_touched() -> None:
    body = b"x" * (signing.MAX_BODY_BYTES + 1)

    with pytest.raises(signing.SignatureError, match="limit"):
        signing.verify(secret=SECRET, body=body, timestamp="1", signature="ab" * 32, now=NOW)


def test_the_timestamp_is_covered_by_the_signature() -> None:
    """Re-stamping a captured body must not produce a delivery that verifies."""
    body = b"{}"
    headers = signing.headers_for(secret=SECRET, body=body, now=NOW)
    restamped = signing.timestamp_of(NOW + timedelta(minutes=1))

    with pytest.raises(signing.SignatureError, match="does not match"):
        signing.verify(
            secret=SECRET,
            body=body,
            timestamp=restamped,
            signature=headers[signing.SIGNATURE_HEADER],
            now=NOW,
        )
