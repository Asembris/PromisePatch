"""The production consent ingress, as a door the world can hold.

A stipulated customer reply has two honest destinations and they answer different questions.
The harness's own channel record answers *what did the customer do* -- it is ``E2`` evidence,
it is read by the scorer, and every attempt gets it identically. This module answers *did
PromisePatch receive it*, which is a question about a running system and is answered only where
that system actually asked something.

**Why it exists.** Without it a reply reaches a Python list and nothing else: no approval
request is bound, no sender is compared against the channel the request was sent to, no deadline
is checked against the database's clock, the literal parser never runs and no consent decision
is written. An attempt driven that way waits for a customer who was never asked -- and because
the baseline has no consent protocol and needs the reply only to *exist*, the same missing door
leaves the baseline whole and stops the other two recovering anything needing a yes. That is a
confound rather than a limitation, and closing it is what this module is for.

**It is a transport and holds no authority.** It finds the link PromisePatch put in the message
it sent, presses one of the two buttons that link opens, and records which door it used.
Whether that answer authorises anything is settled afterwards, under the case lock, by the
protocol that already existed. Nothing here writes an approval decision, names a sender, states
a clock or carries free text: the endpoint has no field for any of them, the channel comes out
of the link's own signature and the two permitted values are composed on the server from the
literal parser's own tokens.

**It never invents a question.** A link exists only where PromisePatch asked, and where it did
not ask there is nothing to press -- so the door reports that it stayed shut rather than
minting a link for itself, which would prove possession of nothing. The reply is still on the
channel record either way, which is what keeps the observable customer event the same
everywhere.

**It is blind to who is driving.** The door is offered every declared reply, by one world that
serves every attempt. What differs is whether a signed link was found, and that is a fact about
what the driven system did, read from that system's own outbox. Nothing here may consult who is
driving, what the expected answer is, or any reading the scorer will take; the preflight's
``event_blinding`` check reads this file's syntax and refuses a run if it ever does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final, Protocol
from urllib.parse import parse_qs, urlsplit

from scripts.sur1.bindings import REAL, Probe
from scripts.sur1.bindings.receivers import (
    DatabaseReader,
    ReceiverUnreadableError,
    channel_identity,
)

APPROVE: Final = "APPROVE"
DECLINE: Final = "DECLINE"
ANSWER_FOR_TEXT: Final = {"YES": APPROVE, "NO": DECLINE}
"""Which button a stipulated literal reply presses.

From the two literal words the consent parser reads to the two values the customer endpoint's
schema permits, and total in neither direction on purpose. A reply that is not one of those two
words has no button on that page: the customer approval surface offers a choice and not a text
field, so there is no honest way to put a sentence through it. Such a reply stays on the channel
record, uninterpreted, exactly as it would if no link had been sent.
"""

LINK_PARAMETER: Final = "approve"
"""The query parameter the customer page dispatches on, and where the token is in the URL."""

MESSAGE_SEND: Final = "MESSAGE_SEND"
"""The outbox kind that carries a customer message. Read, never written."""

NO_REQUEST: Final = "no approval request was opened for this channel, so no link was sent"
NO_BUTTON: Final = "the customer approval page offers two buttons and this reply is neither"

SHUT: Final = "shut"
OPENED: Final = "customer-approval-link"

PROBE_TOKEN: Final = "preflight-token-that-cannot-verify"
"""What the readiness probe presents. Deliberately unsignable, so the probe answers nothing."""


class ConsentDoorError(RuntimeError):
    """The door was due to be pressed and could not be. Never softened into a silent skip.

    A reply that should have reached the product and did not is the confound this module exists
    to close, so it fails the arming closed rather than being recorded as a reply nobody got.
    """


class ConsentDoor(Protocol):
    """Somewhere a declared reply may additionally be delivered, beyond the channel record."""

    binding_kind: str

    def identity(self) -> dict[str, Any]: ...

    def probe(self) -> Probe: ...

    def begin(self) -> None: ...

    def offer(self, *, channel: str, order: str, text: str) -> dict[str, Any]: ...


@dataclass(slots=True)
class SignedLinkDoor:
    """The customer's own door: the signed possession link PromisePatch put in its own message.

    Holds no authority and decides nothing. Every offer produces a receipt saying which door was
    used and why, so a capture states it rather than leaving it to be assumed.
    """

    api_base_url: str
    database: DatabaseReader
    timeout_seconds: float = 15.0
    receipts: list[dict[str, Any]] = field(default_factory=list)
    binding_kind: str = REAL

    def identity(self) -> dict[str, Any]:
        return {
            "door": OPENED,
            "ingress": f"{self.api_base_url}/api/customer/approval/{{token}}",
            "when_unasked": NO_REQUEST,
        }

    def probe(self) -> Probe:
        """One unauthenticated ``GET`` at a token that cannot verify. Reads, never writes.

        A process holding no link secret signs nothing and therefore verifies nothing: it answers
        ``503`` to every token, mints no link into any message, and would leave every reply with
        no door to go through. A process that verifies answers ``404`` -- it read the link and
        refused it -- and that is the only answer this accepts. Asking with a token that cannot
        verify is what keeps the probe a read: there is no request behind it to answer.
        """
        import httpx2

        url = f"{self.api_base_url}/api/customer/approval/{PROBE_TOKEN}"
        try:
            answer = httpx2.get(url, timeout=self.timeout_seconds)
        except Exception as failure:
            return Probe(
                "CONSENT",
                False,
                f"the customer approval surface at {self.api_base_url} was unreachable: "
                f"{type(failure).__name__}: {failure}",
            )
        if answer.status_code == 503:
            return Probe(
                "CONSENT",
                False,
                f"{self.api_base_url} mints no customer approval links, so no message carries "
                "one and no reply could be delivered through the link it would have carried",
            )
        if answer.status_code != 404:
            return Probe(
                "CONSENT",
                False,
                f"{self.api_base_url} answered {answer.status_code} to a token that cannot "
                "verify; a surface verifying links answers 404",
            )
        return Probe("CONSENT", True, f"{self.api_base_url} verifies customer approval links")

    def begin(self) -> None:
        """Between attempts. Receipts from a previous attempt would describe another world.

        Nothing else is reset here, because there is nothing else to reset: the links this door
        reads live in ``outbox_messages``, which the fixture load empties before every attempt,
        so a link an earlier attempt was sent cannot survive into this one.
        """
        self.receipts.clear()

    # -- the offer ------------------------------------------------------------------------------

    def offer(self, *, channel: str, order: str, text: str) -> dict[str, Any]:
        """Deliver this reply to the product too, if the product asked for it on this channel.

        Returns the receipt either way. A shut door is an ordinary outcome and not a failure:
        it is what a world looks like when nothing asked the customer anything.
        """
        answer = ANSWER_FOR_TEXT.get(text.strip().upper())
        if answer is None:
            return self._shut(order=order, channel=channel, reason=NO_BUTTON)
        token = self._link_for(channel)
        if token is None:
            return self._shut(order=order, channel=channel, reason=NO_REQUEST)
        return self._press(token=token, channel=channel, order=order, answer=answer)

    def _shut(self, *, order: str, channel: str, reason: str) -> dict[str, Any]:
        receipt = {"door": SHUT, "order": order, "channel": channel, "reason": reason}
        self.receipts.append(receipt)
        return receipt

    def _link_for(self, channel: str) -> str | None:
        """The signed link PromisePatch sent to this channel, if it sent one.

        Read out of the outbox payload, which is the only place a link is. Nothing stores one and
        no surface hands one out, so this reads the message rather than minting a second link.

        The comparison is on the channel identity the arming and the fixture speak, not the bare
        address the row stores. Read the other way round this matches nothing, every reply
        quietly takes the channel record alone, and the confound is back with no sign of it.
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
            if channel_identity(body) != channel:
                continue
            url = body.get("approval_url")
            if not url:
                continue
            found = parse_qs(urlsplit(str(url)).query).get(LINK_PARAMETER)
            if found:
                return str(found[0])
        return None

    def _press(self, *, token: str, channel: str, order: str, answer: str) -> dict[str, Any]:
        """Post one answer to the customer approval endpoint, and nothing else.

        No sender, no channel, no timestamp and no free text travel in the body: the endpoint has
        no field for any of them, the channel comes out of the signature and the clock comes out
        of the database. ``202`` is the answer this press stored and ``200`` is the answer an
        earlier press already had -- a redelivered provider message is one decision seen twice,
        and the endpoint's derived record id is what makes that true rather than a branch here.
        """
        import httpx2

        try:
            reply = httpx2.post(
                f"{self.api_base_url}/api/customer/approval/{token}",
                json={"answer": answer},
                timeout=self.timeout_seconds,
            )
        except Exception as failure:
            raise ConsentDoorError(
                f"the customer approval surface was unreachable: {type(failure).__name__}: "
                f"{failure}"
            ) from failure
        if reply.status_code not in (200, 202):
            raise ConsentDoorError(
                f"the customer approval surface answered {reply.status_code} to {order}'s reply"
            )
        receipt = {
            "door": OPENED,
            "order": order,
            "channel": channel,
            "answer": answer,
            "status_code": reply.status_code,
            "stored": reply.status_code == 202,
        }
        self.receipts.append(receipt)
        return receipt


__all__ = [
    "ANSWER_FOR_TEXT",
    "APPROVE",
    "DECLINE",
    "LINK_PARAMETER",
    "MESSAGE_SEND",
    "NO_BUTTON",
    "NO_REQUEST",
    "OPENED",
    "SHUT",
    "ConsentDoor",
    "ConsentDoorError",
    "SignedLinkDoor",
]
