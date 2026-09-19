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

**E1 is read from a copy of the simulator's own store, taken on demand.** Rule ``B2`` attributes
an amendment by the ``idempotency_key`` on the order system's own event, and that field lives in
the committed event body rather than in the ``/admin/events`` projection -- which is why
:class:`~scripts.sur1.bindings.receivers.OrderSystemReceiver` reads the store directly. Under
``docker-compose.yml`` that store is inside a named volume with no host path, so there is nothing
for ``SUR1_ORDER_SYSTEM_STORE`` to name. :class:`ContainerOrderReceiver` copies the file out with
``docker cp`` immediately before each read. It is the simulator's own committed record either
way; only the route to it differs, and it is read-only in both directions.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

from scripts.sur1.bindings import Probe
from scripts.sur1.bindings.receivers import (
    ChannelLedger,
    DatabaseReader,
    OrderSystemReceiver,
    ReceiverUnreadableError,
    channel_identity,
)
from scripts.sur1.bindings.worldsink import LedgerWriter
from scripts.sur1.evidence import INBOUND, ChannelMessage

APPROVE: Final = "APPROVE"
DECLINE: Final = "DECLINE"
ANSWER_FOR_TEXT: Final = {"YES": APPROVE, "NO": DECLINE}
"""Which button a stipulated literal reply presses.

The mapping is from the two literal words the consent parser reads to the two values the
customer endpoint's schema permits, and it is total in neither direction on purpose: a reply
that is not one of those two words has no button on that page, and the rehearsal refuses rather
than inventing a way to say it.
"""

LINK_PARAMETER: Final = "approve"
"""The query parameter the customer page dispatches on, and where the token is in the URL."""

MESSAGE_SEND: Final = "MESSAGE_SEND"
"""The outbox kind that carries a customer message. Read, never written."""


class RehearsalIngressError(RuntimeError):
    """The rehearsal could not deliver a stipulated reply through any honest door."""


# ---------------------------------------------------------------------------- E1, from a volume


@dataclass(slots=True)
class ContainerOrderReceiver(OrderSystemReceiver):
    """``E1``, read from a copy of the order simulator's own committed store.

    The copy is taken immediately before every read, so the rows read are the rows the simulator
    had committed at that moment. It is never written to, and the container's own file is never
    written to either: ``docker cp`` out of a container is a read.
    """

    container: str = ""
    container_path: str = "/data/order-simulator.sqlite3"

    # ``@dataclass(slots=True)`` builds a replacement class, so a zero-argument ``super()`` in a
    # method here closes over the pre-slots class and raises. The base is named explicitly for
    # that reason and for no other; the calls below are ordinary inherited ones.

    def identity(self) -> dict[str, Any]:
        return {
            "receiver": "E1",
            "base_url": self.base_url,
            "store": None if self.store_path is None else str(self.store_path),
            "copied_from": f"{self.container}:{self.container_path}",
        }

    def refresh(self) -> None:
        """Copy the simulator's committed store out of its volume, or say it is unreadable."""
        if self.store_path is None:
            raise ReceiverUnreadableError("E1", "no host path was given for the copied store")
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            ["docker", "cp", f"{self.container}:{self.container_path}", str(self.store_path)],
            capture_output=True,
            text=True,
            check=False,
            env={"MSYS_NO_PATHCONV": "1"},
        )
        if completed.returncode != 0:
            raise ReceiverUnreadableError(
                "E1", f"the simulator's store could not be copied: {completed.stderr.strip()[:200]}"
            )

    def probe(self) -> Probe:
        try:
            self.refresh()
        except ReceiverUnreadableError as failure:
            return Probe("E1", False, failure.detail)
        return OrderSystemReceiver.probe(self)

    def read(self, *, since: datetime) -> tuple[Any, ...]:
        self.refresh()
        return OrderSystemReceiver.read(self, since=since)


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
        token = self._link_for(channel)
        if token is not None:
            return self._press(token=token, channel=channel, order=order, text=text)
        return self._record(message_id=message_id, channel=channel, order=order, text=text)

    def move_stock(self, *, resource: str, delta: Decimal, source_id: str, order: str) -> str:
        """The same append-only posting :class:`LiveWorldSink` makes, unchanged."""
        return self.ledger.post(
            resource_id=resource,
            delta=delta,
            source_id=source_id,
            recorded_at=datetime.now(UTC),
        )

    # -- the ingress ---------------------------------------------------------------------------

    def _link_for(self, channel: str) -> str | None:
        """The signed link PromisePatch sent to this channel, if it sent one.

        Read out of the outbox payload, which is the only place a link is. Nothing stores one,
        no surface hands one out, and this reads the message rather than minting a second link,
        because a link this harness signed for itself would prove possession of nothing.
        """
        try:
            rows = self.database.rows(
                "E2",
                "SELECT payload FROM outbox_messages"
                f" WHERE kind = '{MESSAGE_SEND}' ORDER BY created_at DESC",
            )
        except ReceiverUnreadableError:
            return None
        for (payload,) in rows:
            body = payload if isinstance(payload, dict) else json.loads(payload)
            # The identity the arming and the fixture speak, not the bare address the row
            # stores. Read the other way round, this matched nothing and every reply quietly
            # took the fallback door -- which is a reply PromisePatch never receives.
            if channel_identity(body) != channel:
                continue
            url = body.get("approval_url")
            if not url:
                continue
            found = parse_qs(urlsplit(str(url)).query).get(LINK_PARAMETER)
            if found:
                return str(found[0])
        return None

    def _press(self, *, token: str, channel: str, order: str, text: str) -> str:
        """Post one answer to the customer approval endpoint, and nothing else.

        No sender field, no channel field, no timestamp and no free text: the endpoint has none,
        the channel comes out of the signature and the clock comes out of the database.
        """
        import httpx2

        literal = text.strip().upper()
        answer = ANSWER_FOR_TEXT.get(literal)
        if answer is None:
            raise RehearsalIngressError(
                f"{text!r} is neither of the two words the customer page can send; a rehearsal "
                "reply that is not a literal decision has no button and is not invented one"
            )
        try:
            reply = httpx2.post(
                f"{self.api_base_url}/api/customer/approval/{token}",
                json={"answer": answer},
                timeout=self.timeout_seconds,
            )
        except Exception as failure:
            raise RehearsalIngressError(
                f"the customer approval surface was unreachable: {type(failure).__name__}: "
                f"{failure}"
            ) from failure
        if reply.status_code not in (200, 202):
            raise RehearsalIngressError(
                f"the customer approval surface answered {reply.status_code} to {order}'s reply"
            )
        receipt = {
            "door": "customer-approval-link",
            "order": order,
            "channel": channel,
            "answer": answer,
            "status_code": reply.status_code,
            "stored": reply.status_code == 202,
        }
        self.receipts.append(receipt)
        return f"reply:{order}:{answer}:via-signed-link:{reply.status_code}"

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


def scratch_store(root: Path) -> Path:
    """Where the copied simulator store lives. Outside the repository, never committed."""
    return root / "order-simulator.sqlite3"


__all__ = [
    "ANSWER_FOR_TEXT",
    "APPROVE",
    "DECLINE",
    "ContainerOrderReceiver",
    "CustomerLinkSink",
    "RehearsalIngressError",
    "scratch_store",
]
