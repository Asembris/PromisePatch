"""The consent protocol's pure half: the literal parser, the message, the reply normaliser.

No database, no worker, no fixture. Everything here is a value in and a value out, which is the
point rather than a convenience: the rule that decides whether a customer agreed to a change to
their order must be readable, testable and explainable without any infrastructure at all.

The parser's job is mostly refusal, so most of this file is refusals. `Strawberries work` is the
canonical one, and it is asserted alongside every other way a person might sound like they are
agreeing without having said the word.
"""

from __future__ import annotations

import json

import pytest

from promise_graph.model import ApprovalDecisionKind
from promisepatch.domain import consent, handlers, messaging

NON_LITERAL = "Strawberries work"
"""The sentence from the frozen spec that must never become consent."""


# --------------------------------------------------------------------------- the literal parser


@pytest.mark.parametrize("said", ["YES", "yes", "Yes", " yes ", "\tYES\n", "Yes.", "(yes)", "yes!"])
def test_a_literal_yes_approves(said: str) -> None:
    """Trim, casefold, unwrap the punctuation a person puts around a word. Nothing else."""
    assert consent.read_literal(said) is ApprovalDecisionKind.APPROVE


@pytest.mark.parametrize("said", ["NO", "no", "No", " no ", "no.", "NO!", "'no'"])
def test_a_literal_no_declines(said: str) -> None:
    assert consent.read_literal(said) is ApprovalDecisionKind.DECLINE


@pytest.mark.parametrize(
    "said",
    [
        NON_LITERAL,
        "strawberries work",
        "YES PLEASE",
        "yes please",
        "yes, please do",
        "NO THANKS",
        "no thanks",
        "okay",
        "OK",
        "sure",
        "that sounds fine",
        "fine by me",
        "go ahead",
        "yeah",
        "yep",
        "nope",
        "y",
        "n",
        "yes or no",
        "I already said yes",
        "no no no",
        "si",
        "oui",
        "",
        "   ",
        "\n",
    ],
)
def test_anything_else_decides_nothing(said: str) -> None:
    """Exact match, never substring. A sentence containing a token is not that token.

    Every string here is something a real customer might plausibly send, and not one of them is
    a signature. The later semantic slice may read them as apparent intent and ask the customer
    to confirm in the two words that count; none of them may ever authorise a change by itself.
    """
    assert consent.read_literal(said) is None


def test_normalisation_touches_only_the_ends() -> None:
    """Nothing inside the string is rewritten, so a phrase can never be collapsed into a token."""
    assert consent.normalize("  YES.  ") == "yes"
    assert consent.normalize("yes please") == "yes please"
    assert consent.normalize("no, thank you") == "no, thank you"


def test_the_parser_is_a_function_of_its_argument_alone() -> None:
    """Called twice with one string, it answers the same thing. There is nothing else in it."""
    assert consent.read_literal("YES") == consent.read_literal("yes")
    assert consent.read_literal(NON_LITERAL) == consent.read_literal(NON_LITERAL)


# ------------------------------------------------------------------------------- the message


def _message(**overrides: object) -> messaging.ApprovalMessage:
    values: dict[str, object] = {
        "customer_name": "A Customer",
        "order_reference": "EXT-X",
        "option_code": "OPT-ABC123",
        "from_product": "One Cake (v1)",
        "to_product": "Another Cake (v2)",
        "affected_resource": "Raspberries",
        "substitute_resource": "Strawberries",
        # The deployed shape. Every real message this product has sent carried a signed link,
        # and the form without one is exercised by name below rather than by default, so a
        # test that forgets to say which deployment it means gets the one that exists.
        "link_available": True,
    }
    values.update(overrides)
    return messaging.ApprovalMessage(**values)  # type: ignore[arg-type]


def test_the_message_carries_the_frozen_answering_instruction_verbatim() -> None:
    """ADR-0021's sentence, word for word, and the option code beside it.

    The second clause is §13.6's own and is unchanged. The first is the amendment: it names
    the link, because the link is the only thing that opens the consent protocol.
    """
    text = messaging.build_approval_request(_message())

    assert messaging.CONSENT_INSTRUCTION in text
    assert "Open the secure link below to approve or decline this change." in text
    assert "If you decline, the bakery will follow up." in text
    assert "OPT-ABC123" in text


def test_no_message_ever_tells_a_customer_to_reply() -> None:
    """The regression this change exists for, asserted as an absence rather than a rewrite.

    A real customer typed a literal ``YES`` into the bot's own chat on 2026-09-22 because the
    message told them to, and it reached nothing: no inbound reply, no decision, and not one
    ``getUpdates`` call in the deployment's whole history. There is no inbound path and there
    is deliberately not going to be one, so no message may ask for a reply on the channel.
    """
    for text in (
        messaging.build_approval_request(_message()),
        messaging.build_approval_request(_message(link_available=False)),
        messaging.build_confirmation_prompt(_message()),
        messaging.build_confirmation_prompt(_message(link_available=False)),
        messaging.build_supersede_notice(_message()),
    ):
        lowered = text.lower()
        for forbidden in ("reply", "respond", "text back", "send yes", "answer yes"):
            assert forbidden not in lowered


def test_only_the_link_is_offered_as_a_way_to_answer() -> None:
    """The message points at exactly one door, and it is the signed one.

    ``build_approval_request`` never renders the URL -- the transport appends it beside the
    words -- so what is asserted here is that the words name that line and offer no second way.
    """
    text = messaging.build_approval_request(_message())

    assert "secure link below" in text
    assert "http" not in text
    for other_door in ("@", "call us", "phone", "email"):
        assert other_door not in text.lower()


def test_a_deployment_that_mints_no_link_asks_for_nothing_at_all() -> None:
    """With no link there is no surface to answer on, so the message stops being a question.

    Both of its claims hold by construction: nothing is amended without consent, and an
    unanswered request reaches its deadline and puts the promise on its owner's desk.
    """
    text = messaging.build_approval_request(_message(link_available=False))

    assert messaging.CONSENT_WITHOUT_LINK_INSTRUCTION in text
    assert messaging.CONSENT_INSTRUCTION not in text
    assert "secure link" not in text
    assert "nothing about your order changes because of it" in text
    assert "OPT-ABC123" in text


def test_the_message_names_the_exact_change() -> None:
    """§16.7: the substitute is named, not alluded to."""
    text = messaging.build_approval_request(_message())

    assert "Another Cake (v2)" in text
    assert "One Cake (v1)" in text
    assert "Strawberries" in text
    assert "Raspberries" in text
    assert "A Customer" in text
    assert "EXT-X" in text


def test_the_message_never_reassures_and_never_promises_the_original() -> None:
    """PromisePatch has no allergen knowledge, and declining does not un-spoil anything."""
    lowered = messaging.build_approval_request(_message()).lower()

    for forbidden in ("safe", "fine", "guarantee", "no problem", "don't worry"):
        assert forbidden not in lowered


def test_a_message_missing_its_detail_still_carries_its_instruction() -> None:
    """Detail degrades; the instruction and the reference never do."""
    text = messaging.build_approval_request(
        _message(from_product=None, to_product=None, affected_resource=None)
    )

    assert messaging.CONSENT_INSTRUCTION in text
    assert "OPT-ABC123" in text


def test_the_confirmation_prompt_points_at_the_link_in_both_deployments() -> None:
    """The prompt a non-literal reply earns names the same door the request named.

    Two sets of instructions in one conversation would be worse than the one wrong set this
    change removes, so the prompt and the request are composed against a single reading of the
    same setting.
    """
    with_link = messaging.build_confirmation_prompt(_message())
    without = messaging.build_confirmation_prompt(_message(link_available=False))

    assert messaging.CONFIRMATION_INSTRUCTION in with_link
    assert "secure link in our earlier message" in with_link
    assert messaging.CONFIRMATION_WITHOUT_LINK_INSTRUCTION in without
    assert messaging.CONFIRMATION_INSTRUCTION not in without
    assert "OPT-ABC123" in with_link
    assert "OPT-ABC123" in without


def test_the_supersede_notice_says_the_order_changed_and_asks_for_nothing() -> None:
    """§14.4's one message: it tells, it does not ask, and it claims no write was made."""
    text = messaging.build_supersede_notice(_message())

    assert messaging.SUPERSEDE_NOTICE in text
    assert messaging.SUPERSEDE_FOLLOW_UP in text
    assert "A Customer" in text
    assert "EXT-X" in text
    assert "OPT-ABC123" in text
    assert messaging.CONSENT_INSTRUCTION not in text
    assert messaging.CONFIRMATION_INSTRUCTION not in text
    assert "YES" not in text
    assert "NO" not in text


def test_the_supersede_notice_never_promises_the_original_and_never_reassures() -> None:
    """The same two rules the ask is held to: no restoration promised, nothing reassured."""
    lowered = messaging.build_supersede_notice(_message()).lower()

    for forbidden in ("safe", "fine", "guarantee", "no problem", "don't worry", "as ordered"):
        assert forbidden not in lowered


def test_the_supersede_guard_refuses_a_notice_that_invites_a_reply() -> None:
    """A notice carrying a reply instruction would be a question nobody could act on."""
    good = messaging.build_supersede_notice(_message())
    assert messaging.carries_supersede_literals(good, option_code="OPT-ABC123") is True
    assert messaging.carries_supersede_literals(good, option_code="OPT-OTHER") is False
    assert messaging.carries_supersede_literals("nothing here", option_code="OPT-ABC123") is False
    # Every form of both instructions, not merely the one this deployment sends. A guard that
    # knew only the link spelling would stop catching the other the moment it existed.
    for instruction in (*messaging.CONSENT_INSTRUCTIONS, *messaging.CONFIRMATION_INSTRUCTIONS):
        assert (
            messaging.carries_supersede_literals(
                good + chr(10) + instruction, option_code="OPT-ABC123"
            )
            is False
        )


def test_the_pre_send_guard_refuses_a_message_missing_either_literal() -> None:
    """The check exists before the drafter it will one day check."""
    assert (
        messaging.carries_required_literals(
            "nothing here", option_code="OPT-ABC123", link_available=True
        )
        is False
    )
    assert (
        messaging.carries_required_literals(
            messaging.CONSENT_INSTRUCTION, option_code="OPT-ABC123", link_available=True
        )
        is False
    )
    assert (
        messaging.carries_required_literals(
            f"{messaging.CONSENT_INSTRUCTION} OPT-ABC123",
            option_code="OPT-ABC123",
            link_available=True,
        )
        is True
    )


def test_the_pre_send_guard_refuses_the_instruction_the_deployment_did_not_owe() -> None:
    """A message promising a link nobody will attach must not pass, and nor must its opposite.

    This is why ``link_available`` is required rather than defaulted on the guard: the check is
    worth having only if it is told which sentence was owed.
    """
    with_link = messaging.build_approval_request(_message())
    without = messaging.build_approval_request(_message(link_available=False))

    assert (
        messaging.carries_required_literals(
            with_link, option_code="OPT-ABC123", link_available=False
        )
        is False
    )
    assert (
        messaging.carries_required_literals(without, option_code="OPT-ABC123", link_available=True)
        is False
    )


# ------------------------------------------------------------------------- the reply normaliser


def _body(**overrides: object) -> str:
    values: dict[str, object] = {
        "request_id": "6a1d2b7c-0000-4000-8000-000000000001",
        "sender": "tg:1002",
        "text": NON_LITERAL,
        "provider_message_id": "update-42",
    }
    values.update(overrides)
    return json.dumps({key: value for key, value in values.items() if value is not None})


def test_a_customer_reply_is_normalised_without_being_read() -> None:
    """Material out, no verdict: which case it belongs to and what it means come later."""
    outcome = handlers.normalize_inbound(handlers.CUSTOMER_REPLY_SOURCE, _body())

    assert outcome.state == "PROCESSED"
    assert outcome.case_id is None
    assert outcome.normalized is not None
    assert outcome.normalized["sender"] == "tg:1002"
    assert outcome.normalized["text"] == NON_LITERAL
    assert outcome.normalized["provider_message_id"] == "update-42"


def test_the_reply_text_survives_normalisation_untouched() -> None:
    """Not trimmed, not lowered, not interpreted. The stored words stay the customer's."""
    outcome = handlers.normalize_inbound(handlers.CUSTOMER_REPLY_SOURCE, _body(text="  YES  "))

    assert outcome.normalized is not None
    assert outcome.normalized["text"] == "  YES  "


@pytest.mark.parametrize("missing", ["request_id", "sender", "text", "provider_message_id"])
def test_a_reply_missing_a_required_field_fails_rather_than_guesses(missing: str) -> None:
    """A message id fallback would silently discard every reply after the first."""
    outcome = handlers.normalize_inbound(handlers.CUSTOMER_REPLY_SOURCE, _body(**{missing: None}))

    assert outcome.state == "FAILED"
    assert outcome.error is not None
    assert missing in outcome.error


def test_an_unreadable_reply_body_is_terminal_rather_than_retried_forever() -> None:
    outcome = handlers.normalize_inbound(handlers.CUSTOMER_REPLY_SOURCE, "{not json")

    assert outcome.state == "FAILED"
    assert outcome.case_id is None
