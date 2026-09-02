"""Record-level guarantees: immutability, aware time, decimal quantities, mandatory provenance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from promise_graph.model import (
    REJECTION_PRECEDENCE,
    SETTLED_STATES,
    SEVERITY_ORDER,
    Classification,
    CommitmentLine,
    ConstraintKind,
    CustomerConstraint,
    ExceptionCategory,
    Order,
    OrderLine,
    PhysicalException,
    ReceivedState,
    RejectionReason,
    Resource,
    ResourceKind,
    RuleId,
)

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)


def line(**overrides: object) -> CommitmentLine:
    payload: dict[str, object] = {
        "id": "cl-1",
        "commitment_id": "com-1",
        "resource_id": "res-1",
        "quantity": Decimal("4.0"),
    }
    payload.update(overrides)
    return CommitmentLine(**payload)


def test_records_are_frozen() -> None:
    resource = Resource(id="res-1", kind=ResourceKind.INGREDIENT, name="raspberries")
    with pytest.raises(ValidationError):
        resource.name = "strawberries"  # type: ignore[misc]


def test_records_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Resource(id="res-1", kind=ResourceKind.INGREDIENT, name="x", colour="red")  # type: ignore[call-arg]


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CustomerConstraint(
            id="cn-1",
            order_id="ord-1",
            kind=ConstraintKind.NO_SUBSTITUTION,
            recorded_by="jo",
            recorded_at=datetime(2026, 3, 4, 7, 0),  # noqa: DTZ001 - deliberately naive
        )


def test_timestamps_are_normalised_to_utc() -> None:
    offset = datetime(2026, 3, 4, 9, 0, tzinfo=UTC).astimezone(timezone(timedelta(hours=2)))
    constraint = CustomerConstraint(
        id="cn-1",
        order_id="ord-1",
        kind=ConstraintKind.NO_SUBSTITUTION,
        recorded_by="jo",
        recorded_at=offset,
    )
    assert constraint.recorded_at.tzinfo is UTC
    assert constraint.recorded_at == datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


def test_float_quantities_are_rejected() -> None:
    with pytest.raises(ValidationError):
        line(quantity=4.0)


def test_quantities_normalise_to_a_fixed_scale() -> None:
    assert line(quantity=Decimal("2.0")).quantity == line(quantity=Decimal("2.00")).quantity
    assert line(quantity="2").quantity == Decimal("2.000")
    assert line(quantity=2).quantity == Decimal("2.000")


def test_negative_quantities_are_rejected() -> None:
    with pytest.raises(ValidationError):
        line(quantity=Decimal("-1"))


def test_booleans_are_not_quantities() -> None:
    with pytest.raises(ValidationError):
        line(quantity=True)


def test_unknown_quantity_is_representable() -> None:
    assert line(quantity=None).quantity is None


def test_short_lines_must_carry_a_received_quantity() -> None:
    with pytest.raises(ValidationError):
        line(received_state=ReceivedState.SHORT, settled_at=NOW)
    settled = line(received_state=ReceivedState.SHORT, received_qty=Decimal("1.5"), settled_at=NOW)
    assert settled.is_settled


def test_received_quantity_is_only_for_short_lines() -> None:
    with pytest.raises(ValidationError):
        line(received_state=ReceivedState.RECEIVED, received_qty=Decimal("1.0"), settled_at=NOW)


def test_expected_lines_are_not_settled() -> None:
    with pytest.raises(ValidationError):
        line(settled_at=NOW)
    assert not line().is_settled


def test_settled_states_are_exactly_the_non_expected_ones() -> None:
    assert set(ReceivedState) - {ReceivedState.EXPECTED} == SETTLED_STATES


def test_constraint_provenance_is_mandatory() -> None:
    with pytest.raises(ValidationError):
        CustomerConstraint(
            id="cn-1",
            order_id="ord-1",
            kind=ConstraintKind.NO_SUBSTITUTION,
            recorded_by="   ",
            recorded_at=NOW,
        )


def test_preapproval_requires_both_resources() -> None:
    with pytest.raises(ValidationError):
        CustomerConstraint(
            id="cn-1",
            order_id="ord-1",
            kind=ConstraintKind.PREAPPROVED_ALTERNATIVE,
            resource_id="res-1",
            recorded_by="jo",
            recorded_at=NOW,
        )


def test_exclusion_requires_a_resource_and_no_substitute() -> None:
    with pytest.raises(ValidationError):
        CustomerConstraint(
            id="cn-1",
            order_id="ord-1",
            kind=ConstraintKind.EXCLUDE_RESOURCE,
            recorded_by="jo",
            recorded_at=NOW,
        )
    with pytest.raises(ValidationError):
        CustomerConstraint(
            id="cn-1",
            order_id="ord-1",
            kind=ConstraintKind.EXCLUDE_RESOURCE,
            resource_id="res-1",
            substitute_resource_id="res-2",
            recorded_by="jo",
            recorded_at=NOW,
        )


def test_plain_constraints_carry_no_resources() -> None:
    with pytest.raises(ValidationError):
        CustomerConstraint(
            id="cn-1",
            order_id="ord-1",
            kind=ConstraintKind.ASK_BEFORE_VISIBLE_CHANGE,
            resource_id="res-1",
            recorded_by="jo",
            recorded_at=NOW,
        )


def test_order_lines_must_belong_to_their_order() -> None:
    with pytest.raises(ValidationError):
        Order(
            id="ord-1",
            external_id="EXT-1",
            external_version=1,
            customer_id="cus-1",
            due_at=NOW,
            state="ACCEPTED",
            lines=(OrderLine(id="ol-1", order_id="ord-2", recipe_version_id="rv-1", quantity=1),),
        )


def test_order_line_ids_are_unique() -> None:
    with pytest.raises(ValidationError):
        Order(
            id="ord-1",
            external_id="EXT-1",
            external_version=1,
            customer_id="cus-1",
            due_at=NOW,
            state="ACCEPTED",
            lines=(
                OrderLine(id="ol-1", order_id="ord-1", recipe_version_id="rv-1", quantity=1),
                OrderLine(id="ol-1", order_id="ord-1", recipe_version_id="rv-2", quantity=1),
            ),
        )


def test_order_line_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        OrderLine(id="ol-1", order_id="ord-1", recipe_version_id="rv-1", quantity=0)


def test_supply_exceptions_must_bind_a_commitment() -> None:
    with pytest.raises(ValidationError):
        PhysicalException(
            id="exc-1",
            category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
            reported_by="maya",
            reported_at=NOW,
        )
    with pytest.raises(ValidationError):
        PhysicalException(
            id="exc-1",
            category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
            commitment_id="com-1",
            resource_id="res-1",
            reported_by="maya",
            reported_at=NOW,
        )


def test_stock_exceptions_must_bind_a_resource_only() -> None:
    with pytest.raises(ValidationError):
        PhysicalException(
            id="exc-1",
            category=ExceptionCategory.STOCK_UNUSABLE,
            reported_by="maya",
            reported_at=NOW,
        )
    with pytest.raises(ValidationError):
        PhysicalException(
            id="exc-1",
            category=ExceptionCategory.STOCK_UNUSABLE,
            resource_id="res-1",
            commitment_id="com-1",
            reported_by="maya",
            reported_at=NOW,
        )


def test_equipment_exceptions_must_bind_equipment_only() -> None:
    with pytest.raises(ValidationError):
        PhysicalException(
            id="exc-1",
            category=ExceptionCategory.EQUIPMENT_UNAVAILABLE,
            reported_by="maya",
            reported_at=NOW,
        )
    with pytest.raises(ValidationError):
        PhysicalException(
            id="exc-1",
            category=ExceptionCategory.EQUIPMENT_UNAVAILABLE,
            resource_id="res-oven",
            commitment_id="com-1",
            reported_by="maya",
            reported_at=NOW,
        )


def test_severity_order_is_total_and_ascending() -> None:
    assert set(SEVERITY_ORDER) == set(Classification)
    assert sorted(SEVERITY_ORDER, key=lambda item: SEVERITY_ORDER[item]) == [
        Classification.UNAFFECTED,
        Classification.AUTO_RECOVERABLE,
        Classification.APPROVAL_REQUIRED,
        Classification.BLOCKED,
    ]


def test_the_frozen_rule_set_has_exactly_twelve_ids() -> None:
    assert len(RuleId) == 12


def test_rejection_precedence_covers_every_reason_once() -> None:
    assert set(REJECTION_PRECEDENCE) == set(RejectionReason)
    assert len(REJECTION_PRECEDENCE) == len(RejectionReason)
