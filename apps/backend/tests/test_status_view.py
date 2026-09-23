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

from promisepatch.domain.analysis import (
    ApprovalStatus,
    CaseStatus,
    ClarificationOptionStatus,
    EffectStatus,
    PendingClarification,
    TrackStatus,
)
from promisepatch.domain.explanations import FactId, closed_phrase
from promisepatch.domain.status_view import (
    CASE_HEADLINES,
    ActionOwner,
    Authority,
    CaseHeadline,
    PromiseState,
    owner_label,
    project,
    render,
    render_clarification_receipt,
    render_confirmation,
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


def case(
    state: str,
    *tracks: TrackStatus,
    attention: bool = False,
    plan: str = "a" * 64,
    question: PendingClarification | None = None,
) -> CaseStatus:
    return CaseStatus(
        case_id=UUID("11111111-1111-4111-8111-111111111111"),
        state=state,
        needs_owner_attention=attention,
        exception_id=uuid4(),
        category="DELIVERY_NOT_RECEIVED",
        tracks=tracks,
        plan_id=plan,
        clarification=question,
    )


def pending(question: str = "Whole delivery, or only the raspberries?") -> PendingClarification:
    return PendingClarification(
        clarification_id=UUID("33333333-3333-4333-8333-333333333333"),
        ordinal=1,
        slot="SCOPE",
        question=question,
        options=(
            ClarificationOptionStatus(code="WHOLE_DELIVERY", label="the whole delivery"),
            ClarificationOptionStatus(code="LINE-RASP", label="only the raspberries"),
        ),
    )


# ------------------------------------------------------------- a token, and the words for it


def test_a_stored_reason_token_travels_beside_the_sentence_for_it() -> None:
    """Both, because the drawer quotes the token and the bands read the sentence."""
    view = project(case("PLANNED", track(state="PENDING", reason="NOSUB_CONSTRAINT")))

    promise = view.threatened[0]
    assert promise.reason == "NOSUB_CONSTRAINT"
    assert promise.reason_phrase == "the order carries a no-substitution constraint"


def test_the_reason_sentence_is_the_explanation_layer_s_own_wording() -> None:
    """Read from the one table that owns it, so a surface cannot hold a second dictionary."""
    view = project(case("PLANNED", track(state="PENDING", reason="PREAPPROVAL_COVERS")))

    assert view.threatened[0].reason_phrase == closed_phrase(
        FactId.IMPACT_REASON, "PREAPPROVAL_COVERS"
    )


def test_a_reason_token_with_no_published_phrase_is_left_without_one() -> None:
    """Understating: a caller falls back to the token rather than to a sentence somebody made up."""
    view = project(case("PLANNED", track(state="PENDING", reason="SOMETHING_NEW")))

    assert view.threatened[0].reason == "SOMETHING_NEW"
    assert view.threatened[0].reason_phrase is None


def test_a_promise_with_no_recorded_reason_has_neither_token_nor_sentence() -> None:
    view = project(case("PLANNED", track(state="PENDING", reason=None)))

    assert view.threatened[0].reason == ""
    assert view.threatened[0].reason_phrase is None


def test_the_exception_category_travels_beside_the_sentence_for_it() -> None:
    status = case("PLANNED", track(state="PENDING"))
    named = CaseStatus(
        case_id=status.case_id,
        state=status.state,
        needs_owner_attention=status.needs_owner_attention,
        exception_id=status.exception_id,
        category="SUPPLY_NOT_RECEIVED",
        tracks=status.tracks,
        plan_id=status.plan_id,
        clarification=status.clarification,
    )

    view = project(named)

    assert view.exception_category == "SUPPLY_NOT_RECEIVED"
    assert view.exception_phrase == "a supplier delivery did not arrive"


def test_a_case_with_no_category_claims_no_sentence_about_one() -> None:
    status = case("UNDERSTANDING")
    uncategorised = CaseStatus(
        case_id=status.case_id,
        state=status.state,
        needs_owner_attention=status.needs_owner_attention,
        exception_id=status.exception_id,
        category=None,
        tracks=(),
        plan_id=status.plan_id,
        clarification=None,
    )

    view = project(uncategorised)

    assert view.exception_category is None
    assert view.exception_phrase is None


def test_the_spoken_status_says_the_reason_rather_than_the_engine_s_token() -> None:
    """What is read aloud is language. ``NOSUB_CONSTRAINT`` is evidence, and stays evidence.

    This is a deliberate change to what the status tool speaks. It previously read the stored
    token out, which asked a baker to know the engine's enum in order to understand their own
    kitchen. The token has not moved: it is still on the projection and still in the drawer that
    quotes it -- only the sentence changed.
    """
    view = project(case("PLANNED", track(state="PENDING", reason="NOSUB_CONSTRAINT")))

    spoken = render(view)

    assert "the order carries a no-substitution constraint" in spoken
    assert "NOSUB_CONSTRAINT" not in spoken


def test_an_untouched_promise_is_explained_in_words_too() -> None:
    """The untouched band carries the product's central claim and is read out with the rest."""
    view = project(
        case(
            "PLANNED",
            track(state="PENDING", reason="NOSUB_CONSTRAINT"),
            track(state="UNAFFECTED", reason="NOT_REACHABLE"),
        )
    )

    spoken = render(view)

    phrase = closed_phrase(FactId.IMPACT_REASON, "NOT_REACHABLE")
    assert phrase is not None
    assert "NOT_REACHABLE" not in spoken
    assert phrase in spoken


def test_a_reason_with_no_published_phrase_is_still_spoken_as_its_token() -> None:
    """The fallback is the token, never a sentence this module made up for an unknown reason."""
    view = project(case("PLANNED", track(state="PENDING", reason="SOMETHING_NEW")))

    assert "SOMETHING_NEW" in render(view)


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


# ---------------------------------------------------- the answer, carried past what followed


def test_a_promise_nobody_was_asked_about_carries_no_consent() -> None:
    """No request, no sentence. An automatic promise must not read as one somebody agreed to."""
    automatic = track(state="PENDING", classification="AUTO_RECOVERABLE", approval=None)
    assert project(case("PLANNED", automatic)).threatened[0].consent is None


def test_a_message_still_in_flight_says_nobody_has_been_asked() -> None:
    """The same gate the word "asked" passes. A queued message has reached nobody."""
    queued = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(provider_ref=None),
    )
    assert project(case("WAITING", queued)).threatened[0].consent is None


def test_a_delivered_question_with_no_answer_says_so_in_the_published_words() -> None:
    asked = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(state="SENT"),
    )
    promise = project(case("WAITING", asked)).threatened[0]
    assert promise.state is PromiseState.REQUESTED
    assert promise.consent == closed_phrase(FactId.APPROVAL_STATE, "SENT")


@pytest.mark.parametrize(
    ("decision", "expected"),
    [("APPROVE", "the customer said yes"), ("DECLINE", "the customer said no")],
)
def test_a_literal_decision_is_stated_in_the_product_s_own_two_words(
    decision: str, expected: str
) -> None:
    decided = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(state="ANSWERED", decision=decision),
    )
    assert project(case("WAITING", decided)).threatened[0].consent == expected


def test_a_yes_survives_a_change_that_was_then_carried_out() -> None:
    """The promise reads "changed"; the record still says a person agreed to it."""
    recovered = track(
        state="RECOVERED",
        classification="APPROVAL_REQUIRED",
        approval=approval(state="ANSWERED", decision="APPROVE"),
    )
    promise = project(case("RESOLVED", recovered)).threatened[0]
    assert promise.state is PromiseState.RECOVERED
    assert promise.consent == "the customer said yes"


def test_a_yes_whose_change_could_not_be_carried_out_is_not_hidden_by_the_escalation() -> None:
    """The one case this field exists for.

    Revalidation refused, or the amendment failed, *after* a customer said yes. The promise is
    the owner's and says so -- and a worker picking it up is told the customer already agreed,
    which the escalation itself deliberately never says.
    """
    refused = track(
        state="ESCALATED",
        classification="APPROVAL_REQUIRED",
        approval=approval(state="ANSWERED", decision="APPROVE"),
    )
    promise = project(case("RESOLVED", refused)).threatened[0]
    assert promise.state is PromiseState.ESCALATED
    assert promise.phrase == "needs you"
    assert promise.consent == "the customer said yes"


def test_a_closed_window_states_the_closure_and_claims_no_answer() -> None:
    expired = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(state="EXPIRED"),
    )
    promise = project(case("WAITING", expired)).threatened[0]
    assert promise.consent == closed_phrase(FactId.APPROVAL_STATE, "EXPIRED")
    assert "said" not in (promise.consent or "")


def test_a_withdrawn_request_says_why_it_was_withdrawn() -> None:
    superseded = track(
        state="PENDING",
        classification="APPROVAL_REQUIRED",
        approval=approval(state="SUPERSEDED"),
    )
    promise = project(case("PLANNED", superseded)).threatened[0]
    assert promise.consent == closed_phrase(FactId.APPROVAL_STATE, "SUPERSEDED")


def test_a_decision_outranks_a_timer_that_fired_after_it() -> None:
    """A customer who answered answered. The request state moving on does not unsay it."""
    late = track(
        state="ESCALATED",
        classification="APPROVAL_REQUIRED",
        approval=approval(state="EXPIRED", decision="APPROVE"),
    )
    assert project(case("WAITING", late)).threatened[0].consent == "the customer said yes"


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


def test_a_case_that_left_promises_alone_counts_no_effects_on_them() -> None:
    """The product's central published number, and it is counted rather than asserted."""
    view = project(
        case(
            "PLANNED",
            track(state="PENDING", classification="BLOCKED", customer="Okafor"),
            track(state="UNAFFECTED", classification="UNAFFECTED", customer="Lena"),
            track(state="UNAFFECTED", classification="UNAFFECTED", customer="Ahmed"),
        )
    )

    assert len(view.untouched) == 2
    assert view.untouched_effect_count == 0


def test_an_effect_on_an_untouched_promise_would_be_counted_and_not_hidden() -> None:
    """The zero is only worth publishing if the same field could come back non-zero.

    A workflow that raised an outbound effect against a promise nothing reached would be
    breaking the selectivity guarantee, and the screen that claims the guarantee has to be the
    place it shows. So the count is over the effect rows of the untouched tracks, and a
    constant would pass every other test in this file.
    """
    reached = track(state="UNAFFECTED", classification="UNAFFECTED", customer="Lena")
    leaked = TrackStatus(
        **{
            **{field: getattr(reached, field) for field in reached.__slots__},
            "effects": (
                EffectStatus(
                    kind="ORDER_AMEND",
                    state="DELIVERED",
                    idempotency_key="pp:amend:leak",
                    provider_ref="amd-1",
                    attempts=1,
                    result=None,
                    delivered_at=None,
                    last_error=None,
                ),
            ),
        }
    )

    view = project(case("PLANNED", leaked))

    assert len(view.untouched) == 1
    assert view.untouched_effect_count == 1


def test_the_case_states_its_own_universe_rather_than_leaving_it_to_be_added_up() -> None:
    """The denominator of "0 of 6" is counted by the projection, over every promise it placed."""
    view = project(
        case(
            "PLANNED",
            track(state="PENDING", classification="AUTO_RECOVERABLE", customer="Priya"),
            track(state="PENDING", classification="BLOCKED", customer="Okafor"),
            track(state="UNAFFECTED", classification="UNAFFECTED", customer="Lena"),
        )
    )

    assert view.promise_count == 3
    assert view.promise_count == len(view.threatened) + len(view.untouched)


def test_a_case_that_has_looked_at_nothing_counts_no_promises() -> None:
    """Fail closed on the denominator too: an unassessed case claims no universe at all."""
    assert project(case("CLARIFYING", question=pending())).promise_count == 0


def test_the_untouched_band_is_present_even_when_it_is_empty() -> None:
    """The claim is made either way. A missing line reads as an omission, not as a zero."""
    view = project(case("PLANNED", track(state="PENDING", classification="BLOCKED")))
    assert "No promise in this case was left alone." in render(view)


def test_a_case_that_has_assessed_nothing_makes_no_claim_about_untouched_promises() -> None:
    """A case still asking a question has not left anything alone; it has not looked yet.

    The band carries the product's central claim, and a claim made before there is anything to
    claim is the wrong kind of confident. While the scope is still a question, the honest
    thing to say about untouched promises is nothing.
    """
    spoken = render(project(case("CLARIFYING", question=pending())))
    assert "left alone" not in spoken


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


# ------------------------------------------------------------------ the question, as a question


def test_an_open_question_is_read_out_with_the_answers_it_will_accept() -> None:
    """Band 1: an unresolved ambiguity appears as a question, never as a result.

    A surface told only "waiting for your answer" has to reconstruct what was asked, and the
    only material it has is the original sentence -- which is exactly the invention the
    clarification protocol exists to avoid.
    """
    view = project(case("CLARIFYING", question=pending()))
    assert view.question is not None
    assert view.question.question == "Whole delivery, or only the raspberries?"
    assert [option.code for option in view.question.options] == ["WHOLE_DELIVERY", "LINE-RASP"]
    spoken = render(view)
    assert "Whole delivery, or only the raspberries?" in spoken
    assert "only the raspberries" in spoken


def test_a_case_with_nothing_open_asks_nothing() -> None:
    view = project(case("PLANNED", track(state="PENDING", classification="AUTO_RECOVERABLE")))
    assert view.question is None
    assert "?" not in render(view)


# --------------------------------------------------------------- the plan, only while offered


def test_a_planned_case_offers_the_identity_of_the_plan_it_is_showing() -> None:
    view = project(case("PLANNED", track(state="PENDING", classification="AUTO_RECOVERABLE")))
    assert view.plan_id == "a" * 64
    assert view.awaiting_confirmation is True


@pytest.mark.parametrize(
    "state", ["RECEIVED", "INTERPRETING", "CLARIFYING", "ANALYZED", "EXECUTING", "RESOLVED"]
)
def test_a_case_that_is_not_offering_a_plan_offers_no_identity(state: str) -> None:
    """Nothing to confirm, so nothing to quote.

    A case already executing still *has* tracks and would still compute an identity, and
    handing one over would invite a confirmation of something nobody is being asked about.
    The domain would refuse it -- and the conversation would have been wrong out loud first.
    """
    view = project(case(state, track(state="PENDING", classification="AUTO_RECOVERABLE")))
    assert view.plan_id is None
    assert view.awaiting_confirmation is False


# ----------------------------------------------------------- what a yes is allowed to sound like


def test_confirming_reports_permission_and_refuses_to_report_completion() -> None:
    """The counts are authorisations. Nothing in this sentence may sound like an outcome."""
    spoken = render_confirmation(
        applying=1, awaiting_approval=1, escalated=1, already_confirmed=False
    )
    assert "covered by a standing preference" in spoken
    assert "still have to ask the customer" in spoken
    assert "need the owner" in spoken
    assert "Nothing has been changed yet" in spoken
    for forbidden in ("changed the order", "recovered", "sent", "asked Tomas", "done"):
        assert forbidden not in spoken


def test_a_confirmation_with_nothing_to_carry_out_says_so() -> None:
    spoken = render_confirmation(
        applying=0, awaiting_approval=0, escalated=0, already_confirmed=False
    )
    assert "no order is being changed" in spoken


def test_a_redelivered_confirmation_does_not_claim_a_second_one_happened() -> None:
    spoken = render_confirmation(
        applying=2, awaiting_approval=0, escalated=0, already_confirmed=True
    )
    assert "already confirmed" in spoken
    assert "not done it twice" in spoken


def test_one_order_is_said_in_the_singular() -> None:
    spoken = render_confirmation(
        applying=1, awaiting_approval=0, escalated=0, already_confirmed=False
    )
    assert "1 order covered by a standing preference" in spoken
    assert "orders" not in spoken


def test_an_answer_receipt_promises_nothing_at_all() -> None:
    spoken = render_clarification_receipt()
    assert "Nothing has changed yet" in spoken
    for forbidden in ("planned", "recovered", "confirmed", "changed the"):
        assert forbidden not in spoken


# ------------------------------------------------- a deadline, in words rather than in ISO-8601


def test_a_spoken_deadline_is_not_read_out_as_a_machine_timestamp() -> None:
    """The spoken status is the only carrier of a customer's clock, and it is read aloud.

    ``isoformat`` puts microseconds and a UTC offset into a sentence a worker hears. The zone
    is named rather than dropped, because a clock time with no clock named makes the reader
    guess which one it is.
    """
    waiting = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(provider_ref="tg-42"),
        deadline=NOW,
    )
    spoken = render(project(case("WAITING", waiting)))
    assert "by 2026-03-04 07:00 (UTC)" in spoken
    assert NOW.isoformat() not in spoken
    assert "T07:00" not in spoken


def test_a_deadline_keeps_its_machine_form_in_the_field_built_for_it() -> None:
    """The sentence is for people; the field stays ISO-8601 so a surface can render its own."""
    waiting = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(provider_ref="tg-42"),
        deadline=NOW,
    )
    promise = project(case("WAITING", waiting)).threatened[0]
    assert promise.deadline_at == NOW.isoformat()
    assert promise.deadline_phrase == "2026-03-04 07:00 (UTC)"


def test_a_next_action_does_not_restate_the_deadline_beside_it() -> None:
    """Two readings of one instant on adjacent lines, and the sentence carried the machine's."""
    waiting = track(
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        approval=approval(provider_ref="tg-42"),
        deadline=NOW,
    )
    promise = project(case("WAITING", waiting)).threatened[0]
    assert promise.next_action == "Nothing. The customer has been asked and has not answered."
    assert "2026" not in promise.next_action


def test_a_promise_with_no_deadline_claims_no_moment_at_all() -> None:
    escalated = track(state="BLOCKED", classification="ESCALATE", reason="NOSUB_CONSTRAINT")
    promise = project(case("PLANNED", escalated)).threatened[0]
    assert promise.deadline_at is None
    assert promise.deadline_phrase is None
    assert "by " not in render(project(case("PLANNED", escalated)))


def test_a_reader_who_may_not_act_is_not_told_the_move_is_theirs() -> None:
    """The judge's session reads a planned case. "You" there offers a move it does not have."""
    planned = track(state="PENDING", classification="AUTO_RECOVERABLE")
    action = project(case("PLANNED", planned)).next_action

    assert action.owner is ActionOwner.YOU
    assert owner_label(action.owner, reader_may_act=True) == "You" == action.owner_label
    assert owner_label(action.owner, reader_may_act=False) == "The worker"


@pytest.mark.parametrize("owner", [item for item in ActionOwner if item is not ActionOwner.YOU])
def test_every_other_owner_is_named_the_same_whoever_reads_it(owner: ActionOwner) -> None:
    """Only the pronoun is relative to the reader. "The owner" is the owner to everybody."""
    assert owner_label(owner, reader_may_act=False) == owner_label(owner, reader_may_act=True)
