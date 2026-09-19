"""The rehearsal's world: the real bindings, plus the two things a local rehearsal has to solve.

Everything here is the ``SUR-1`` binding it is named after, with one thing changed and the
change stated. Nothing in this module is a second world model, a second receiver or a second
protocol.

**The customer answers through the ingress production expects.**
:class:`~scripts.sur1.bindings.worldsink.LiveWorldSink` delivers a stipulated reply by appending
it to the harness's own channel record. That is honest *evidence* -- ``E2`` sees an inbound
message on the customer's channel -- and it is not *ingress*: PromisePatch never receives it, no
approval request is bound, no sender is compared against the channel the request was sent to, and
no consent decision exists. A benchmark arm driven that way would be scored on a consent that
never reached the consent protocol.

So :class:`CustomerLinkSink` delivers a reply the way a customer does. It reads the outbound
message PromisePatch actually queued for that channel, takes the signed possession link out of
its payload -- the one place a link exists, because nothing stores one and no surface hands one
out -- and posts the answer to ``POST /api/customer/approval/{token}``. The channel is inside the
signature and is checked against the request afterwards, so §14.3 check 8 stays a real check. The
two permitted values are composed on the server from the literal parser's own tokens. The
rehearsal supplies no sender, no channel, no clock and no free text, because that endpoint has no
field for any of them.

**The baseline has no request to answer, and that asymmetry is delivery, not authority.** Arm A
is not PromisePatch: nothing of it ever created an ``approval_request``, so there is no link to
hold and no ingress to reach. Its reply is recorded on the harness's own transport, exactly as
:class:`LiveWorldSink` does. The *observable customer event* is the same either way -- one
inbound message, on the same channel address, carrying the same two literal characters, at the
point in the sequence where the customer answered -- and that is what ``E2`` records and what the
scorer reads. What differs is the door the message came through, which is a fact about which
system was asked to carry it. The sink says which door it used in its receipt, so a capture says
so too rather than leaving it to be assumed.

**E1 is read from the order system's own endpoint.** Rule ``B2`` attributes an amendment by the
``idempotency_key`` on the order system's own event, and ``GET /admin/events`` now publishes each
event's committed body, so :class:`~scripts.sur1.bindings.receivers.OrderSystemReceiver` reads it
there. The rehearsal previously copied the simulator's SQLite store out of its named volume with
``docker cp`` before every read, because the projection carried none of the fields the rule
needed; that workaround is gone and ``ContainerOrderReceiver`` with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from scripts.sur1.bindings.consentdoor import (
    ANSWER_FOR_TEXT,
    APPROVE,
    DECLINE,
    NO_BUTTON,
    OPENED,
    ConsentDoorError,
    SignedLinkDoor,
)
from scripts.sur1.bindings.receivers import ChannelLedger, DatabaseReader
from scripts.sur1.bindings.worldsink import LedgerWriter
from scripts.sur1.evidence import INBOUND, ChannelMessage


class RehearsalIngressError(RuntimeError):
    """The rehearsal could not deliver a stipulated reply through any honest door."""


# ------------------------------------------------------------------- the customer's own door


@dataclass(slots=True)
class CustomerLinkSink:
    """The world delivering a stipulated customer reply, through the door a customer uses.

    Holds no authority and decides nothing. It finds the link PromisePatch put in the message it
    sent, presses one of the two buttons that link opens, and records which door it used. Whether
    that answer authorises anything is settled afterwards, under the case lock, by the protocol
    that already existed.
    """

    api_base_url: str
    database: DatabaseReader
    channel: ChannelLedger
    ledger: LedgerWriter
    timeout_seconds: float = 15.0
    receipts: list[dict[str, Any]] = field(default_factory=list)

    def identity(self) -> dict[str, Any]:
        return {
            "sink": "rehearsal",
            "ingress": f"{self.api_base_url}/api/customer/approval/{{token}}",
            "fallback": "the harness channel record, for an arm that opened no approval request",
        }

    # -- the two powers ------------------------------------------------------------------------

    def deliver_reply(
        self,
        *,
        message_id: str,
        channel: str,
        order: str,
        text: str,
        delivery: int,
        deliveries: int,
    ) -> str:
        """Answer on this channel: through the signed link if one was sent, else on the record.

        The order is not a preference. A link exists only where PromisePatch asked the question,
        and where it asked, answering anywhere else would be recording a decision the product
        never received.
        """
        if delivery < 1 or delivery > deliveries:
            raise RehearsalIngressError(
                f"delivery {delivery} of {message_id} is outside the {deliveries} declared"
            )
        try:
            receipt = self._door().offer(channel=channel, order=order, text=text)
        except ConsentDoorError as failure:
            raise RehearsalIngressError(str(failure)) from failure
        if receipt["door"] == OPENED:
            self.receipts.append(receipt)
            return f"reply:{order}:{receipt['answer']}:via-signed-link:{receipt['status_code']}"
        if receipt["reason"] == NO_BUTTON:
            raise RehearsalIngressError(
                f"{text!r} is neither of the two words the customer page can send; a rehearsal "
                "reply that is not a literal decision has no button and is not invented one"
            )
        return self._record(message_id=message_id, channel=channel, order=order, text=text)

    def _door(self) -> SignedLinkDoor:
        """The benchmark's own door, which this rehearsal uses rather than a second copy of it.

        The mechanism is shared and the *policy* is not, which is the whole difference between
        the two callers. A scored attempt records the reply on the channel and then offers it
        here, because ``E2`` must hold the same observable event whatever the door did. A
        rehearsal presses the link when there is one and records only when there is not, which
        is what it has always done and what its captures describe.
        """
        return SignedLinkDoor(
            api_base_url=self.api_base_url,
            database=self.database,
            timeout_seconds=self.timeout_seconds,
        )

    def move_stock(self, *, resource: str, delta: Decimal, source_id: str, order: str) -> str:
        """The same append-only posting :class:`LiveWorldSink` makes, unchanged."""
        return self.ledger.post(
            resource_id=resource,
            delta=delta,
            source_id=source_id,
            recorded_at=datetime.now(UTC),
        )

    def _record(self, *, message_id: str, channel: str, order: str, text: str) -> str:
        """The harness's own transport, for an arm that opened no approval request.

        Identical to what :class:`LiveWorldSink` does and for the same reason: arm A is not
        PromisePatch, has no outbox and asked no question PromisePatch recorded, so there is no
        link to hold. The observable customer event is the same inbound message on the same
        channel; only the door differs, and the receipt says which one it was.
        """
        self.channel.accept(
            ChannelMessage(
                channel_address=channel,
                direction=INBOUND,
                text=text,
                accepted_at=datetime.now(UTC),
                provider_event_id=message_id,
            )
        )
        receipt = {
            "door": "harness-channel-record",
            "order": order,
            "channel": channel,
            "reason": "no approval request was opened for this channel, so no link was sent",
        }
        self.receipts.append(receipt)
        return f"reply:{order}:recorded:on-the-harness-transport"


__all__ = [
    "ANSWER_FOR_TEXT",
    "APPROVE",
    "DECLINE",
    "CustomerLinkSink",
    "RehearsalIngressError",
]
