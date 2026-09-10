"""What the product is allowed to say about a case, and when it is allowed to say it.

Pure tests over pure functions: no database, no engine, no transport. Each one names a durable
posture and asserts the phrase it may become, because the failure this module exists to prevent
is not a crash -- it is a sentence that was true five seconds later.

The negative assertions carry the weight. "Asked" must not appear while a message is still in
flight; "changed" must not appear before the order system's own state agrees; and a posture
nobody anticipated must land somewhere that understates rather than somewhere that lies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from promisepatch.domain.analysis import ApprovalStatus, CaseStatus, TrackStatus
from promisepatch.domain.status_view import (
    CASE_HEADLINES,
    Authority,
    CaseHeadline,
    PromiseState,
    project,
    render,
)

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)


def track(
    *,
    state: str,
    classification: str | None = None,
    customer: str = "Tomas",
    order: str = "HO-1001",
    reason: str | None = "raspberries did not arrive",
    approval: ApprovalStatus | None = None,
    deadline: datetime | None = None,
) -> TrackStatus:
    return TrackStatus(
        track_id=uuid4(),
        promise_id=f"promise-{customer.lower()}",
        order_external_id=order,
        order_external_version=1,
        mirrored_versions={},
        customer_name=customer,
        state=state,
        classification=classification,
        rule_id="R-UNREACH" if classification == "UNAFFECTED" else "R-SUB-OK",
        reason_detail=reason,
        priority=1,
        fingerprint=None,
        deadline_at=deadline,
        linked_track_id=None,
        paths=1,
        watched_entities=2,
        revalidation=None,
        options=(),
        approval=approval,
    )


def approval(
    *,
    state: str = "SENT",
    provider_ref: str | None = "tg-42",
    decision: str | None = None,
) -> ApprovalStatus:
    return ApprovalStatus(
        request_id=uuid4(),
        option_code="A",
        state=state,
        decided=decision is not None,
        sent_at=NOW,
        deadline=NOW,
        provider_ref=provider_ref,
        decision=decision,
        parser="LITERAL" if decision else None,
        replies=1 if decision else 0,
    )


def case(state: str, *tracks: TrackStatus, attention: bool = False) -> CaseStatus:
    return CaseStatus(
        case_id=UUID("11111111-1111-4111-8111-111111111111"),
        state=state,
        needs_owner_attention=attention,
        exception_id=uuid4(),
        category="DELIVERY_NOT_RECEIVED",
        tracks=tracks,
    )


# ------------------------------------------------------------------- planned is not completed


def test_an_automatic_track_before_confirmation_is_only_planned() -> None:
    """An ``AUTO_RECOVERABLE`` classification is a permission to act later, not an act.

    The most tempting untruth in the product: the plan is known, the substitution is allowed,
    and nothing whatever has been done. Until the worker confirms, "planned" is the whole
    sentence and the count of recovered orders is zero.
    """
    view = project(case("PLANNED", track(state="PENDING", classification="AUTO_RECOVERABLE")))
    assert view.threatened[0].state is PromiseState.PLANNED
    assert view.threatened[0].phrase == "planned - waiting for you"
    assert "changed" not in render(view)


def test_the_same_track_after_confirmation_is_authorized_and_still_not_recovered() -> None:
    view = project(case("EXECUTING", track(state="PENDING", classification="AUTO_RECOVERABLE")))
    assert view.threatened[0].state is PromiseState.AUTHORIZED
    assert view.threatened[0].authority is Authority.STANDING_PREFERENCE


def test_applying_is_not_recovered() -> None:
    view = project(case("EXECUTING", track(state="APPLYING", classification="AUTO_RECOVERABLE")))
    assert view.threatened[0].state is PromiseState.APPLYING
    assert view.threatened[0].phrase == "changing the order now"


def test_recovered_is_only_said_where_the_workflow_observed_the_order_system() -> None:
    """``RECOVERED`` is reachable only after reconciliation, so the phrase rides that posture."""
    view = project(case("RECONCILING", track(state="RECOVERED", classification="AUTO_RECOVERABLE")))
    assert view.threatened[0].state is PromiseState.RECOVERED
    assert view.threatened[0].phrase == "changed"


# --------------------------------------------------------------------------- asked means sent


def test_a_message_still_in_flight_is_not_an_ask() -> None:
    """No provider receipt, no "asked". A queued message has reached nobody."""
    waiting = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(provider_ref=None),
    )
    view = project(case("WAITING", waiting))
    assert view.threatened[0].state is PromiseState.PLANNED
    assert "asked" not in render(view)


def test_an_acknowledged_message_is_an_ask() -> None:
    waiting = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(provider_ref="tg-42"),
        deadline=NOW,
    )
    view = project(case("WAITING", waiting))
    assert view.threatened[0].state is PromiseState.REQUESTED
    assert view.threatened[0].authority is Authority.CUSTOMER
    assert "asked" in render(view)


@pytest.mark.parametrize(
    ("decision", "expected"),
    [("APPROVE", PromiseState.CONSENTED), ("DECLINE", PromiseState.DECLINED)],
)
def test_a_literal_decision_is_reported_as_the_customer_s_own(
    decision: str, expected: PromiseState
) -> None:
    decided = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(state="ANSWERED", decision=decision),
    )
    assert project(case("WAITING", decided)).threatened[0].state is expected


def test_a_closed_window_with_no_answer_is_expiry() -> None:
    expired = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(state="EXPIRED"),
    )
    assert project(case("WAITING", expired)).threatened[0].state is PromiseState.EXPIRED


# ------------------------------------------------------------------------ what was left alone


def test_an_unaffected_track_is_untouched_and_counted() -> None:
    view = project(
        case(
            "PLANNED",
            track(state="PENDING", classification="AUTO_RECOVERABLE", customer="Tomas"),
            track(
                state="UNAFFECTED",
                classification="UNAFFECTED",
                customer="Lena",
                order="HO-1002",
                reason="not reachable from the exception",
            ),
        )
    )
    assert [item.customer_name for item in view.untouched] == ["Lena"]
    assert view.untouched[0].authority is Authority.NONE
    assert "1 promise was left alone:" in render(view)


def test_the_untouched_band_is_present_even_when_it_is_empty() -> None:
    """The claim is made either way. A missing line reads as an omission, not as a zero."""
    view = project(case("PLANNED", track(state="PENDING", classification="BLOCKED")))
    assert "No promise in this case was left alone." in render(view)


def test_a_promise_another_case_is_recovering_is_not_called_untouched() -> None:
    """``LINKED`` has been left to somebody else, which is not the same as left alone.

    Folding it into the untouched count would inflate the product's central claim with a
    promise this case is genuinely entangled with.
    """
    view = project(case("PLANNED", track(state="LINKED", classification="AUTO_RECOVERABLE")))
    assert view.untouched == ()
    assert view.threatened[0].state is PromiseState.LINKED
    assert view.threatened[0].authority is Authority.NONE


# --------------------------------------------------------------------------- failing closed


def test_an_unrecognised_track_posture_understates_rather_than_lies() -> None:
    view = project(case("PLANNED", track(state="SOMETHING_NEW", classification="BLOCKED")))
    assert view.threatened[0].state is PromiseState.AWAITING_PLAN
    assert view.threatened[0].phrase == "not decided yet"


def test_a_pending_track_in_a_case_that_has_not_planned_yet_claims_nothing() -> None:
    view = project(case("ANALYZED", track(state="PENDING", classification="AUTO_RECOVERABLE")))
    assert view.threatened[0].state is PromiseState.AWAITING_PLAN


def test_every_durable_case_state_has_a_headline() -> None:
    """The schema's own list, so a new state is a failing test rather than a silent default."""
    durable = {
        "RECEIVED",
        "INTERPRETING",
        "CLARIFYING",
        "NEEDS_HUMAN_INTERPRETATION",
        "ANALYZED",
        "PLANNED",
        "EXECUTING",
        "WAITING",
        "REVALIDATING",
        "RECONCILING",
        "RESOLVED",
        "CANCELLED",
    }
    assert set(CASE_HEADLINES) == durable


def test_a_case_that_has_only_been_heard_says_nothing_has_changed() -> None:
    view = project(case("RECEIVED"))
    assert view.headline is CaseHeadline.UNDERSTANDING
    assert "Nothing has changed yet." in render(view)


# ------------------------------------------------------------------------------- rendering


def test_the_rendering_groups_by_authority_and_names_the_owner_s_share() -> None:
    view = project(
        case(
            "PLANNED",
            track(state="PENDING", classification="AUTO_RECOVERABLE", customer="Tomas"),
            track(
                state="PENDING",
                classification="APPROVAL_REQUIRED",
                customer="Ines",
                order="HO-1003",
            ),
            track(
                state="PENDING",
                classification="BLOCKED",
                customer="Marc",
                order="HO-1004",
                reason="no validated option",
            ),
        )
    )
    speech = render(view)
    assert "Covered by a standing preference:" in speech
    assert "Needs the customer:" in speech
    assert "Needs the owner:" in speech
    assert speech.index("Covered by") < speech.index("Needs the customer")
    assert "Marc (HO-1004)" in speech


def test_the_rendering_is_the_same_every_time() -> None:
    """Deterministic in the sense that matters: no clock, no provider, no ordering surprise."""
    subject = case(
        "PLANNED",
        track(state="PENDING", classification="AUTO_RECOVERABLE"),
        track(state="UNAFFECTED", classification="UNAFFECTED", customer="Lena", order="HO-1002"),
    )
    assert render(project(subject)) == render(project(subject))
