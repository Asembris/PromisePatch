"""The scored path's customer-consent ingress, proved on synthetic fixtures and no SUR-1 world.

Nothing here prepares a ``SUR-1`` scenario, drives an arm, calls a model, reaches AWS or opens a
run directory. The outbox payloads are hand-written in the shape the product writes, the channel
addresses are invented, and the one test that talks to a running API asks it about a token that
cannot verify -- which answers nothing and writes nothing.

**What is proved here and what is proved elsewhere.** The consent *protocol* -- the sender read
from the link's signature, the request and channel comparison, the deadline against the
database's clock, the literal parser, one decision per link, a forged or expired or superseded
link failing closed -- is proved against the real router, the real domain and the real database
in ``apps/backend/tests/test_customer_approval_link.py``, which this work did not change. What
was missing, and what this file adds, is the *join*: that a stipulated benchmark reply reaches
that endpoint at all, that it reaches no other address, that it carries nothing the endpoint
has no field for, and that the channel record still holds the same observable event either way.

The two compose into an authority path because the door's only reach into PromisePatch is one
URL, which :func:`test_the_door_reaches_one_address_and_writes_to_no_store` reads out of the
syntax rather than taking on trust.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from scripts.sur1.bindings.consentdoor import (
    NO_BUTTON,
    NO_REQUEST,
    OPENED,
    PROBE_TOKEN,
    SHUT,
    ConsentDoorError,
    SignedLinkDoor,
)
from scripts.sur1.bindings.receivers import ChannelLedger, ReceiverUnreadableError
from scripts.sur1.bindings.worldsink import LedgerWriter, LiveWorldSink, SinkUnavailableError

REPO = Path(__file__).resolve().parents[2]
DOOR_SOURCE = REPO / "scripts" / "sur1" / "bindings" / "consentdoor.py"

BASE = "http://127.0.0.1:48000"
CHANNEL = "tg:5551"
OTHER_CHANNEL = "tg:5552"
TOKEN = "a-signed-possession-token"
ORDER = "syn-order-1"
MESSAGE_ID = "provider-message-1"


def payload(*, address: str = "5551", token: str | None = TOKEN) -> dict[str, Any]:
    """One outbound row in the shape ``outbox_messages`` stores, and nothing SUR-1 declares."""
    url = None if token is None else f"{BASE}/customer/approve?approve={token}"
    return {
        "channel_kind": "telegram",
        "channel_address": address,
        "text": "we can offer a strawberry version; reply YES or NO",
        "approval_url": url,
    }


@dataclass(slots=True)
class Rows:
    """A database reader that answers with stated rows and reaches nothing."""

    payloads: tuple[dict[str, Any], ...] = ()
    unreadable: bool = False
    url: str = "postgresql://reader@127.0.0.1:55432/synthetic"
    statements: list[str] = field(default_factory=list)

    def rows(self, source: str, statement: str) -> list[tuple[object, ...]]:
        self.statements.append(statement)
        if self.unreadable:
            raise ReceiverUnreadableError(source, "the synthetic reader was asked to refuse")
        return [(json.dumps(body),) for body in self.payloads]


@dataclass(slots=True)
class Press:
    """One recorded HTTP call. Records and never dispatches: nothing here reaches a network."""

    url: str
    kwargs: dict[str, Any]


@dataclass(slots=True)
class Surface:
    """A stand-in customer surface that answers a stated status and remembers what it was sent."""

    statuses: list[int] = field(default_factory=lambda: [202])
    presses: list[Press] = field(default_factory=list)
    gets: list[Press] = field(default_factory=list)
    explode: bool = False

    def post(self, url: str, **kwargs: Any) -> Any:
        if self.explode:
            raise OSError("the synthetic surface refused the connection")
        self.presses.append(Press(url, kwargs))
        return _Answer(self.statuses[min(len(self.presses) - 1, len(self.statuses) - 1)])

    def get(self, url: str, **kwargs: Any) -> Any:
        if self.explode:
            raise OSError("the synthetic surface refused the connection")
        self.gets.append(Press(url, kwargs))
        return _Answer(self.statuses[0])


@dataclass(slots=True)
class _Answer:
    status_code: int


@pytest.fixture
def surface(monkeypatch: pytest.MonkeyPatch) -> Surface:
    """The customer approval surface, replaced at the one module the door calls it through."""
    import httpx2

    made = Surface()
    monkeypatch.setattr(httpx2, "post", made.post)
    monkeypatch.setattr(httpx2, "get", made.get)
    return made


def door(*payloads: dict[str, Any], unreadable: bool = False) -> SignedLinkDoor:
    return SignedLinkDoor(
        api_base_url=BASE,
        database=Rows(payloads=payloads, unreadable=unreadable),  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------- the door presses the link


def test_the_reply_goes_through_the_signed_link_the_product_actually_sent(
    surface: Surface,
) -> None:
    """The one place a link exists is the message PromisePatch queued, and this reads it there."""
    receipt = door(payload()).offer(channel=CHANNEL, order=ORDER, text="YES")

    assert [press.url for press in surface.presses] == [f"{BASE}/api/customer/approval/{TOKEN}"]
    assert receipt["door"] == OPENED
    assert receipt["answer"] == "APPROVE"
    assert receipt["status_code"] == 202
    assert receipt["stored"] is True


def test_the_press_carries_only_the_answer_and_nothing_the_endpoint_has_no_field_for(
    surface: Surface,
) -> None:
    """No sender, no channel, no clock, no free text. The channel comes out of the signature."""
    door(payload()).offer(channel=CHANNEL, order=ORDER, text="YES")

    body = surface.presses[0].kwargs["json"]
    assert body == {"answer": "APPROVE"}
    sent = json.dumps(surface.presses[0].kwargs)
    for forbidden in ("sender", "channel", "received_at", "now", "tg:5551"):
        assert forbidden not in sent, f"the door sent {forbidden} to the customer endpoint"


def test_a_literal_no_presses_the_decline_button(surface: Surface) -> None:
    """The two words the parser reads map to the two values the schema permits, and no others."""
    receipt = door(payload()).offer(channel=CHANNEL, order=ORDER, text="NO")

    assert surface.presses[0].kwargs["json"] == {"answer": "DECLINE"}
    assert receipt["answer"] == "DECLINE"


# --------------------------------------------------------------- the door stays shut, honestly


def test_a_channel_nobody_asked_leaves_the_door_shut(surface: Surface) -> None:
    """The baseline's own case: nothing of it opened a request, so there is no link to press."""
    receipt = door(payload(address="5552")).offer(channel=CHANNEL, order=ORDER, text="YES")

    assert receipt == {
        "door": SHUT,
        "order": ORDER,
        "channel": CHANNEL,
        "reason": NO_REQUEST,
    }
    assert surface.presses == [], "a reply nobody asked for reached the customer endpoint"


def test_a_message_that_carried_no_link_leaves_the_door_shut(surface: Surface) -> None:
    """An ordinary customer message is not an approval request and opens nothing."""
    receipt = door(payload(token=None)).offer(channel=CHANNEL, order=ORDER, text="YES")

    assert receipt["reason"] == NO_REQUEST
    assert surface.presses == []


def test_free_text_has_no_button_and_is_never_invented_into_one(surface: Surface) -> None:
    """The customer page offers a choice, not a text field, so a sentence has nowhere to go.

    Deliberately not an error and deliberately not an approval. The reply is real, it is on the
    channel record where the scorer reads it, and the one thing that must not happen is a
    sentence being turned into a decision by this harness -- which is the whole reason the
    product has a literal parser in the first place.
    """
    receipt = door(payload()).offer(channel=CHANNEL, order=ORDER, text="Strawberries work.")

    assert receipt["door"] == SHUT
    assert receipt["reason"] == NO_BUTTON
    assert surface.presses == []


def test_an_unreadable_outbox_leaves_the_door_shut_rather_than_guessing(surface: Surface) -> None:
    receipt = door(payload(), unreadable=True).offer(channel=CHANNEL, order=ORDER, text="YES")

    assert receipt["reason"] == NO_REQUEST
    assert surface.presses == []


# ----------------------------------------------------------------------------- replay and stale


def test_a_redelivered_message_presses_one_link_and_is_stored_once(surface: Surface) -> None:
    """``C07``'s shape, on a synthetic order: one message identity delivered twice.

    The door does not remember and does not branch. Both presses are made, both name the same
    derived record, and the endpoint answers ``202`` to the one it stored and ``200`` to the one
    it already had. Exactly-once is the database's unique index, not this object's memory.
    """
    surface.statuses = [202, 200]
    opened = door(payload())

    first = opened.offer(channel=CHANNEL, order=ORDER, text="YES")
    second = opened.offer(channel=CHANNEL, order=ORDER, text="YES")

    assert [press.url for press in surface.presses] == [
        f"{BASE}/api/customer/approval/{TOKEN}",
        f"{BASE}/api/customer/approval/{TOKEN}",
    ]
    assert first["stored"] is True
    assert second["stored"] is False, "a redelivery was reported as a second stored decision"


def test_a_refused_link_fails_the_event_closed_rather_than_passing_quietly(
    surface: Surface,
) -> None:
    """A forged, expired or unknown link answers 404, and that is never softened into a skip."""
    surface.statuses = [404]

    with pytest.raises(ConsentDoorError, match="404"):
        door(payload()).offer(channel=CHANNEL, order=ORDER, text="YES")


def test_an_unreachable_surface_fails_the_event_closed(surface: Surface) -> None:
    surface.explode = True

    with pytest.raises(ConsentDoorError, match="unreachable"):
        door(payload()).offer(channel=CHANNEL, order=ORDER, text="YES")


def test_receipts_do_not_survive_into_the_next_attempt() -> None:
    """An attempt reporting the previous attempt's doors would describe another world."""
    opened = door(payload(token=None))
    opened.offer(channel=CHANNEL, order=ORDER, text="YES")
    assert opened.receipts

    opened.begin()

    assert opened.receipts == []


def test_no_link_from_a_previous_attempt_can_survive_into_this_one() -> None:
    """Fresh request state per attempt, as a property of the reset rather than of the door.

    The door reads links out of ``outbox_messages`` and requests out of ``approval_requests``.
    Both are emptied by the governed fixture load every ``prepare`` runs, so there is no stale
    link to find -- which is why the door does not need a time filter, and why a filter would be
    worse: a clock skew between this process and PostgreSQL would silently drop a real link.
    """
    from promisepatch.db.boundary import resettable_tables

    emptied = resettable_tables()
    for table in ("outbox_messages", "approval_requests", "inbound_replies", "inbox_events"):
        assert table in emptied, f"{table} survives a fixture reset, so an attempt is not fresh"


# ------------------------------------------------------------------------------ E2 equivalence


def sink(*, door_bound: SignedLinkDoor | None) -> tuple[LiveWorldSink, ChannelLedger]:
    ledger = ChannelLedger()
    return (
        LiveWorldSink(
            channel=ledger,
            ledger=LedgerWriter(url="postgresql://stub/stub"),
            door=door_bound,
        ),
        ledger,
    )


def observable(ledger: ChannelLedger) -> list[tuple[str, str, str, str | None]]:
    return [
        (message.channel_address, message.direction, message.text, message.provider_event_id)
        for message in ledger.messages
    ]


def test_the_channel_record_holds_the_same_reply_whether_or_not_a_door_opened(
    surface: Surface,
) -> None:
    """``E2`` equivalence, which is the whole reason the record is written unconditionally.

    One arm has a consent protocol and a door opens for it; another has neither. The customer
    event the scorer reads -- same address, same words, same provider identity, same direction --
    is identical, and the difference is confined to whether a running system was also told.
    """
    with_door, opened_ledger = sink(door_bound=door(payload()))
    without_door, plain_ledger = sink(door_bound=None)

    for made in (with_door, without_door):
        made.deliver_reply(
            message_id=MESSAGE_ID,
            channel=CHANNEL,
            order=ORDER,
            text="YES",
            delivery=1,
            deliveries=1,
        )

    assert observable(opened_ledger) == observable(plain_ledger)
    assert observable(plain_ledger) == [(CHANNEL, "INBOUND", "YES", MESSAGE_ID)]
    assert len(surface.presses) == 1, "only the arm that asked reached the customer endpoint"


def test_a_sink_with_no_door_calls_no_approval_endpoint(surface: Surface) -> None:
    """The baseline's semantics stated directly: the record, and nothing else."""
    made, ledger = sink(door_bound=None)

    made.deliver_reply(
        message_id=MESSAGE_ID,
        channel=CHANNEL,
        order=ORDER,
        text="YES",
        delivery=1,
        deliveries=1,
    )

    assert observable(ledger) == [(CHANNEL, "INBOUND", "YES", MESSAGE_ID)]
    assert surface.presses == []
    assert surface.gets == []


def test_the_record_is_written_before_the_door_is_offered(surface: Surface) -> None:
    """A door that refuses still leaves the customer event on the record it belongs on."""
    surface.explode = True
    made, ledger = sink(door_bound=door(payload()))

    with pytest.raises(SinkUnavailableError, match="unreachable"):
        made.deliver_reply(
            message_id=MESSAGE_ID,
            channel=CHANNEL,
            order=ORDER,
            text="YES",
            delivery=1,
            deliveries=1,
        )

    assert observable(ledger) == [(CHANNEL, "INBOUND", "YES", MESSAGE_ID)]


# --------------------------------------------------------------------------- structural proofs


def test_the_door_reaches_one_address_and_writes_to_no_store() -> None:
    """The join that makes the composition sound: one URL out, and no store written.

    The consent protocol's own guarantees are proved against the real router and the real
    database elsewhere. They cover this path only if this path reaches that endpoint and nothing
    else -- so the reach is read out of the syntax rather than assumed, and the absence of any
    write means no decision can be inserted behind the protocol's back.
    """
    source = DOOR_SOURCE.read_text(encoding="utf-8")

    assert source.count("httpx2.post(") == 1
    assert source.count("httpx2.get(") == 1
    assert "/api/customer/approval/" in source
    for writing in ("INSERT", "UPDATE", "DELETE", "approval_decisions", "inbound_replies"):
        assert writing not in source, f"the door names {writing}, which would bypass the protocol"

    reads = [line.strip() for line in source.splitlines() if "SELECT" in line]
    assert len(reads) == 1, f"the door makes {len(reads)} queries; it is allowed exactly one"
    assert reads[0].startswith('"SELECT payload FROM outbox_messages"'), reads[0]


def test_the_readiness_probe_reads_and_never_writes(surface: Surface) -> None:
    """A preflight that answered a real request to find out whether it could would be a write."""
    surface.statuses = [404]

    answer = door().probe()

    assert answer.reachable
    assert surface.presses == []
    assert [press.url for press in surface.gets] == [f"{BASE}/api/customer/approval/{PROBE_TOKEN}"]


def test_a_surface_that_mints_no_links_is_reported_unready(surface: Surface) -> None:
    """503 is a deployment that signs nothing, so no message would carry a link at all."""
    surface.statuses = [503]

    answer = door().probe()

    assert not answer.reachable
    assert "mints no customer approval links" in answer.detail


def test_an_unreachable_surface_is_reported_unready(surface: Surface) -> None:
    surface.explode = True

    answer = door().probe()

    assert not answer.reachable
    assert "unreachable" in answer.detail


def test_the_ingress_can_name_no_answer_no_arm_and_no_reading() -> None:
    """The structural guard the goal asks for, served by the check the preflight already runs.

    ``consentdoor`` is listed in ``EVENT_MODULES``, so :func:`event_blinding` walks it: it may
    not name ``ground_truth``, ``the_point``, an expected report, an ablation target, an arm
    field or an arm, and it may not import the scorer. Asserting the module is *in the list* is
    the half that a new file could otherwise quietly miss.
    """
    from scripts.sur1.preflight import EVENT_MODULES, event_blinding

    assert "consentdoor" in EVENT_MODULES
    assert event_blinding().passed, event_blinding().detail


def test_the_implementation_freeze_covers_the_door() -> None:
    """A change to what a reply reaches must move a hash, or the freeze is not a freeze."""
    from scripts.sur1.bindings import consentdoor as door_module
    from scripts.sur1.bindings import declaration

    assert door_module in declaration.IMPLEMENTATION_MODULES
    assert declaration.differences() == (), declaration.differences()


# ------------------------------------------------------------------------------- the preflight


def test_a_world_with_no_consent_door_is_refused() -> None:
    """The refusal that stops a run reintroducing the confound by simply not binding a door."""
    from scripts.sur1.preflight import consent_ingress

    @dataclass
    class Doorless:
        consent_door: None = None

    refused = consent_ingress(world=Doorless())

    assert not refused.passed
    assert "never reach PromisePatch" in refused.detail


def test_a_stand_in_door_cannot_carry_a_scored_run() -> None:
    from scripts.sur1.preflight import consent_ingress

    @dataclass
    class Double:
        binding_kind: str = "double"

        def probe(self) -> Any:
            raise AssertionError("a stand-in door was probed instead of refused")

    @dataclass
    class World:
        consent_door: Double = field(default_factory=Double)

    refused = consent_ingress(world=World())

    assert not refused.passed
    assert "stand-in" in refused.detail


def test_a_world_whose_surface_verifies_links_is_permitted(surface: Surface) -> None:
    from scripts.sur1.preflight import consent_ingress

    surface.statuses = [404]

    @dataclass
    class World:
        consent_door: SignedLinkDoor

    permitted = consent_ingress(world=World(consent_door=door()))

    assert permitted.passed
    assert "verifies customer approval links" in permitted.detail
