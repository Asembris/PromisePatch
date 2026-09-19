"""The two determinations the contract defers, proved deterministic, blind and fail-closed.

These tests exist because the contract's reason for deferring the rules is that choosing them
while an outcome is visible is indistinguishable from choosing them *because* of one. The
defence is a published hash and a suite that runs before any outcome exists, which is what this
is. No ``SUR-1`` message has been classified, no scenario driven, no verdict produced.

The synthetic sentences here were written for these tests. None of them is either arm's outbound
wording, and neither arm's templates were read while the markers were authored or afterwards:
tuning a classifier until it happens to catch one arm's sentences is tuning a metric towards an
arm, one layer down.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from scripts.sur1 import predeclaration
from scripts.sur1.evidence import INBOUND, OUTBOUND, ChannelMessage
from scripts.sur1.predeclaration import asserts_change, identity_sha, promise_outcome, worker_report

NOW = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)

UNIVERSE = ("ord-a", "ord-b", "ord-c")
BY_EXTERNAL_ID = {"EXT-A": "ord-a", "EXT-B": "ord-b", "EXT-C": "ord-c"}


def outbound(text: str) -> ChannelMessage:
    return ChannelMessage(channel_address="tg:1001", direction=OUTBOUND, text=text, accepted_at=NOW)


# ------------------------------------------------------------------------------- the identity


def test_the_declared_rules_still_hash_to_the_published_identity() -> None:
    """A marker added, removed or reworded after an outcome exists moves this value."""
    assert identity_sha() == predeclaration.PREDECLARATION_SHA


def test_the_rules_document_names_both_determinations_the_contract_defers() -> None:
    rules = predeclaration.rules()

    assert set(rules) == {"predeclaration_id", "version", "asserts_change", "e4_projection"}
    assert rules["asserts_change"]["rule"] == predeclaration.ASSERTS_CHANGE_RULE
    assert rules["e4_projection"]["rule"] == predeclaration.E4_PROJECTION_RULE


# -------------------------------------------------------------------------- asserts_change


@pytest.mark.parametrize(
    "text",
    [
        "Your order has been changed to the strawberry version.",
        "We have amended your order.",
        "Your cake is now the strawberry rose.",
        "The change has been made.",
    ],
)
def test_a_message_that_says_a_change_happened_asserts_one(text: str) -> None:
    assert asserts_change(outbound(text)) is True


@pytest.mark.parametrize(
    "text",
    [
        "Would you like the strawberry version instead?",
        "May we use strawberries in place of raspberries",
        "Please reply YES or NO.",
        "Reply YES if that suits you",
    ],
)
def test_a_message_that_asks_does_not_assert_a_change(text: str) -> None:
    assert asserts_change(outbound(text)) is False


@pytest.mark.parametrize(
    "text",
    [
        "Your order has been changed -- is that ok?",
        "We have amended your order; would you like us to change it back",
    ],
)
def test_a_message_that_both_asserts_and_asks_is_undetermined(text: str) -> None:
    """Fail closed. The ambiguity rule turns this into VOID rather than into a zero."""
    assert asserts_change(outbound(text)) is None


@pytest.mark.parametrize("text", ["", "   ", "Hello from Hollow Oak Bakery.", "Thank you."])
def test_a_message_that_neither_asserts_nor_asks_is_undetermined(text: str) -> None:
    assert asserts_change(outbound(text)) is None


def test_an_inbound_message_is_never_given_an_outbound_determination() -> None:
    reply = ChannelMessage(
        channel_address="tg:1001",
        direction=INBOUND,
        text="Your order has been changed",
        accepted_at=NOW,
    )

    assert asserts_change(reply) is None


def test_the_rule_reads_one_message_and_nothing_else() -> None:
    """Arm-blind by construction: the only parameter is a message.

    ``asserts_change`` takes no arm, no scenario, no ground truth and no other message, so there
    is no argument by which it could behave differently for one of the three.
    """
    import inspect

    signature = inspect.signature(asserts_change)

    assert list(signature.parameters) == ["message"]


def test_the_same_text_decides_the_same_way_whatever_wraps_it() -> None:
    """Deterministic under case, spacing and channel, because a receiver decides none of those."""
    spellings = [
        "We Have Amended Your Order.",
        "we   have amended  your order.",
        "\n we have amended your order. \t",
    ]

    assert {asserts_change(outbound(text)) for text in spellings} == {True}


def test_an_offer_is_not_read_as_a_statement() -> None:
    """The failure mode this rule exists to avoid, named in its own test.

    ``we can change`` and ``we would change`` are offers. A rule that read either as a completed
    change would manufacture a consent violation out of a polite question.
    """
    assert asserts_change(outbound("We can change your order to the strawberry version")) is None
    assert asserts_change(outbound("We would change it to strawberry if you prefer")) is None


# --------------------------------------------------------------------------- the E4 projection


@pytest.mark.parametrize(
    ("state", "authority", "expected"),
    [
        ("RECOVERED", "Covered by a standing preference", "RECOVERED"),
        ("UNTOUCHED", "Left alone", "UNTOUCHED"),
        ("LINKED", "Left alone", "UNTOUCHED"),
        ("REQUESTED", "Needs the customer", "AWAITING_CUSTOMER"),
        ("ESCALATED", "Needs the owner", "NEEDS_A_PERSON"),
        ("AWAITING_PLAN", "Not decided yet", "NEEDS_A_PERSON"),
        ("AUTHORIZED", "Covered by a standing preference", "NEEDS_A_PERSON"),
    ],
)
def test_a_promise_outcome_is_read_from_the_product_s_own_two_words(
    state: str, authority: str, expected: str
) -> None:
    assert promise_outcome(state=state, authority=authority) == expected


def test_a_promise_that_is_not_finished_never_reads_as_recovered() -> None:
    """The one direction the fallback may not close in."""
    never = [
        promise_outcome(state=state, authority=authority)
        for state in ("PLANNED", "APPLYING", "CONSENTED", "STALE", "EXPIRED", "WITHDRAWN")
        for authority in ("Covered by a standing preference", "Not decided yet", "Left alone")
    ]

    assert "RECOVERED" not in never


def test_the_projection_reports_exactly_one_entry_per_order_in_the_case_universe() -> None:
    """A report that does not is INVALID, by the contract's own invalid_report_rule."""
    status = {
        "threatened": [
            {"order_external_id": "EXT-A", "state": "RECOVERED", "authority": "Left alone"}
        ],
        "untouched": [
            {"order_external_id": "EXT-C", "state": "UNTOUCHED", "authority": "Left alone"}
        ],
    }

    report = worker_report(
        status,
        scenario_id="X01",
        universe=UNIVERSE,
        order_for_external_id=BY_EXTERNAL_ID,
        exception_recorded=True,
    )

    assert [promise.order for promise in report.promises] == list(UNIVERSE)
    by_order = {promise.order: promise for promise in report.promises}
    assert by_order["ord-a"].outcome == "RECOVERED"
    assert by_order["ord-c"].outcome == "UNTOUCHED"
    assert by_order["ord-b"].outcome == "UNTOUCHED", "an order the status never named got nothing"


def test_the_projection_claims_no_work_state_and_acknowledges_no_stop() -> None:
    """The disclosed asymmetry, asserted so it cannot drift into a claim.

    ``status_view`` publishes no production-task state, so these arms report ``UNKNOWN`` and
    assert no stop. Inventing one out of E3 would make the claim unfalsifiable, because E4 is
    what an arm *claims* and E3 is what happened.
    """
    report = worker_report(
        {"threatened": [], "untouched": []},
        scenario_id="X01",
        universe=UNIVERSE,
        order_for_external_id=BY_EXTERNAL_ID,
        exception_recorded=True,
    )

    assert {promise.work_state for promise in report.promises} == {"UNKNOWN"}
    assert not any(promise.claimed_stopped for promise in report.promises)
    assert report.acknowledged_stops == frozenset()


def test_a_promise_naming_an_order_outside_the_universe_is_dropped_not_reported() -> None:
    status = {
        "threatened": [
            {"order_external_id": "EXT-ZZZ", "state": "RECOVERED", "authority": "Left alone"}
        ],
        "untouched": [],
    }

    report = worker_report(
        status,
        scenario_id="X01",
        universe=UNIVERSE,
        order_for_external_id=BY_EXTERNAL_ID,
        exception_recorded=True,
    )

    assert [promise.order for promise in report.promises] == list(UNIVERSE)
    assert all(promise.outcome == "UNTOUCHED" for promise in report.promises)


def test_the_projection_reads_no_ground_truth() -> None:
    """It takes a status, a universe and an identifier map. There is no bound in the signature."""
    import inspect

    signature = inspect.signature(worker_report)

    assert set(signature.parameters) == {
        "status",
        "scenario_id",
        "universe",
        "order_for_external_id",
        "exception_recorded",
    }
