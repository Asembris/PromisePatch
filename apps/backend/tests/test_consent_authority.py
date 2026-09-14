"""What may and may not become a customer's answer, stated once, in one place.

The consent rules are proved in detail elsewhere -- the parser without a database in
``test_consent_parser``, the protocol against one in ``test_customer_approval``. This module is
deliberately a second reading of the same guarantees, arranged as the invariant rather than as
the scenario, because the invariant is the thing that has to survive changes to the machinery
underneath it.

It is written to be provider-agnostic on purpose. Every test here drives a real worker carrying
a real semantic provider object, and asserts an outcome that owes nothing to what that provider
said, could not say, or was never asked. A reading of the customer's words is not among the
inputs to any assertion below, so the file reads identically whether one is taken or not.

Four things are pinned:

* **Only the two words decide.** A literal ``YES`` approves, a literal ``NO`` declines, both
  through :class:`~promise_graph.model.ParserKind` ``LITERAL``, and an agreeable English
  sentence does neither, however friendly it is.
* **Who, and when, are checked before what.** A reply from another number and a reply after the
  window closed are refused without the parser being reached at all.
* **A conversation cannot be replayed into a second answer.** One delivery redelivered decides
  once; a contradicting word after a decision changes nothing.
* **A worker's yes is not a customer's yes.** Different people, different parsers, different
  tables, and confirming a plan writes no approval decision anywhere.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from _intake_support import RASPBERRY_ONLY, TOMAS_CHANNEL, Intake
from _intake_support import physical as physical

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import ApprovalRequestState, ParserKind
from promisepatch.domain import approvals, cases
from promisepatch.graph.channel import split_channel
from promisepatch.semantic import FakeSemanticProvider, SemanticJob

pytestmark = pytest.mark.integration

B = ho.PROMISE_B

NON_LITERAL = "Strawberries work"
"""The canonical agreeable sentence. It is about strawberries; it is not a signature."""

ANOTHER_NUMBER = "tg:9999"
"""The same transport, a different person. Refused on identity alone, and on nothing else."""


# ------------------------------------------------------------------------------------ driving


async def waiting_case(intake: Intake) -> UUID:
    """The canonical case driven to a durable wait on promise B's customer."""
    opened = await intake.report()
    await intake.drain()
    await intake.answer(opened.case_id, RASPBERRY_ONLY)
    await intake.drain()
    await intake.confirm(opened.case_id)
    await intake.drain(limit=40)
    return opened.case_id


async def the_request(intake: Intake) -> Any:
    requests = await intake.requests()
    assert len(requests) == 1
    return requests[0]


async def audit_types(intake: Intake, case_id: UUID) -> list[str]:
    return [row.type for row in await intake.audits(case_id)]


def reply_readings(provider: FakeSemanticProvider) -> int:
    """How many times this provider was asked to read a customer's words."""
    return len([call for call in provider.calls if call.job is SemanticJob.CLASSIFY_REPLY_INTENT])


async def answer(intake: Intake, request: Any, text: str, **kwargs: Any) -> FakeSemanticProvider:
    """Deliver one reply and run a worker of our own until the protocol has finished with it."""
    provider = FakeSemanticProvider()
    await intake.deliver_reply(request.id, text, **kwargs)
    await intake.drain(worker=intake.worker(semantic=provider), limit=30)
    return provider


# ================================================================== only the two words decide


async def test_a_literal_yes_is_an_approval_read_by_the_literal_parser(physical: Intake) -> None:
    """The whole of what authorises a change: one word, read by a parser with no model in it."""
    await waiting_case(physical)
    request = await the_request(physical)

    provider = await answer(physical, request, "YES")

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVE"
    assert decisions[0].parser == ParserKind.LITERAL.value
    assert decisions[0].request_id == request.id
    assert reply_readings(provider) == 0


async def test_a_literal_no_is_a_decline_read_by_the_same_parser(physical: Intake) -> None:
    """A decline is literal too, because it escalates. An apparent no is not a no."""
    await waiting_case(physical)
    request = await the_request(physical)

    provider = await answer(physical, request, "NO")

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "DECLINE"
    assert decisions[0].parser == ParserKind.LITERAL.value
    assert reply_readings(provider) == 0


@pytest.mark.parametrize("said", [" Yes. ", "yes", "NO!", " no "])
async def test_the_two_words_survive_punctuation_and_case(physical: Intake, said: str) -> None:
    """Normalisation is the parser's whole latitude, and it is the same for both words."""
    await waiting_case(physical)
    request = await the_request(physical)

    provider = await answer(physical, request, said)

    assert len(await physical.decisions()) == 1
    assert reply_readings(provider) == 0


async def test_an_agreeable_sentence_gains_no_authority(physical: Intake) -> None:
    """The centre of the whole authority model. Nothing here is a decision of any kind."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await answer(physical, request, NON_LITERAL)

    assert await physical.decisions() == []
    after = await the_request(physical)
    assert after.decided is False
    assert after.state == ApprovalRequestState.CONFIRMATION_PENDING.value
    assert (await physical.track(case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert (await physical.case(case_id)).state == cases.CASE_WAITING


async def test_an_agreeable_sentence_is_kept_word_for_word(physical: Intake) -> None:
    """Stored as data. What the customer wrote is evidence, and never an instruction."""
    await waiting_case(physical)
    request = await the_request(physical)

    await answer(physical, request, NON_LITERAL)

    replies = await physical.replies()
    assert len(replies) == 1
    assert replies[0].raw_text == NON_LITERAL
    assert replies[0].request_id == request.id


async def test_an_agreeable_sentence_earns_exactly_one_further_question(
    physical: Intake,
) -> None:
    """One prompt, then the protocol stops asking. A second unreadable reply goes to a person."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await answer(physical, request, NON_LITERAL)
    await answer(physical, request, "sounds good to me")

    assert await physical.decisions() == []
    prefix = f"pp:confirm:{request.id}:"
    prompts = [row for row in await physical.effects() if row.idempotency_key.startswith(prefix)]
    assert len(prompts) == 1
    assert (await physical.track(case_id, B)).state == cases.TRACK_ESCALATED


# ============================================================== who, and when, before what


async def test_a_yes_from_another_number_is_refused_on_identity(physical: Intake) -> None:
    """The sender is checked before the words are, and no other path can substitute for it."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    provider = await answer(physical, request, "YES", sender=ANOTHER_NUMBER)

    assert await physical.decisions() == []
    after = await the_request(physical)
    assert after.decided is False
    assert after.state == ApprovalRequestState.SENT.value
    assert approvals.AUDIT_UNAUTHORIZED_APPROVAL in await audit_types(physical, case_id)
    assert reply_readings(provider) == 0


async def test_a_yes_after_the_window_closed_does_not_reopen_it(physical: Intake) -> None:
    """A closed window stays closed. Expiry is not something a later answer can undo."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    await physical.close_window(request.id)

    provider = await answer(physical, request, "YES")

    assert await physical.decisions() == []
    after = await the_request(physical)
    assert after.decided is False
    assert (await physical.track(case_id, B)).state == cases.TRACK_ESCALATED
    assert reply_readings(provider) == 0


# =============================================================== one conversation, one answer


async def test_a_redelivered_reply_decides_once(physical: Intake) -> None:
    """The transport may deliver the same message twice. The ledger holds one of it."""
    await waiting_case(physical)
    request = await the_request(physical)
    delivery = await physical.deliver_reply(request.id, "YES", event_id="replayed")

    await physical.deliver_reply(request.id, "YES", event_id=delivery)
    await physical.drain(limit=25)

    assert len(await physical.decisions()) == 1
    assert len(await physical.replies()) == 1


async def test_a_contradicting_word_after_a_decision_changes_nothing(physical: Intake) -> None:
    """Append-only and unique per request: the first literal answer is the answer for ever."""
    await waiting_case(physical)
    request = await the_request(physical)

    await answer(physical, request, "YES")
    await answer(physical, request, "NO")

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVE"


# ===================================================== a worker's yes is not a customer's yes


async def test_confirming_a_plan_writes_no_customer_decision(physical: Intake) -> None:
    """Two different people, and only one of them can approve a change to their own order."""
    opened = await physical.report()
    await physical.drain()
    await physical.answer(opened.case_id, RASPBERRY_ONLY)
    await physical.drain()

    await physical.confirm(opened.case_id)

    assert await physical.decisions() == []
    assert await physical.requests() == []


def test_the_two_yeses_are_read_by_two_different_parsers() -> None:
    """Structural, so the distinction cannot be lost to a refactor that unified them.

    The worker's plain yes is the orchestrator's, on its own side of the transport, and it is
    stricter than the domain's. Neither module holds the other's reader.
    """
    from promisepatch.domain import consent
    from promisepatch.orchestrator import policy

    assert consent.read_literal("YES") is not None
    assert consent.read_literal("sure") is None
    assert not hasattr(policy, "read_literal")


def test_the_refused_sender_differs_from_the_customer_only_in_who_it_is() -> None:
    """Grounds the refusal above: same channel kind, same shape, a different person.

    Worth stating, because a sender rejected for being malformed would prove nothing about
    identity. These two are told apart by the address and by nothing else.
    """
    assert TOMAS_CHANNEL != ANOTHER_NUMBER
    assert split_channel(TOMAS_CHANNEL)[0] == split_channel(ANOTHER_NUMBER)[0]
