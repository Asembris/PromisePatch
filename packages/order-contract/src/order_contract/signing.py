"""Service-to-service authentication for an order-system webhook.

A webhook is an unauthenticated HTTP request until something proves who sent it, and browser
session authentication cannot do that job: the sender is a server, it holds no cookie, and a
cookie it did hold would make a cross-site request forgery out of every delivery. So the sender
signs, and the receiver verifies.

**The signature covers the timestamp and the exact bytes of the body.** Not the parsed object,
not a re-serialised copy of it: an attacker who can alter one byte of the payload must produce
a signature over the altered bytes, and only the shared secret can do that. The receiver
therefore has to verify before it parses, which is also the right order for a second reason --
parsing untrusted input is work an unauthenticated caller should not be able to make us do.

**The timestamp is inside the signature and is checked against a window.** Without it a
recorded delivery could be replayed for ever, because the signature of an unchanging body never
expires. Five minutes is the architecture's number and is generous enough for a retry ladder.

The window is *not* a substitute for duplicate handling: a legitimate redelivery inside the
window verifies exactly as the first one did, and the receiver's own uniqueness on the event id
is what makes it a no-op.
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Final

SIGNATURE_HEADER: Final = "X-Order-Signature"
TIMESTAMP_HEADER: Final = "X-Order-Timestamp"
"""Two headers rather than one packed value, so a malformed one is a readable error."""

DEFAULT_TOLERANCE: Final = timedelta(minutes=5)
"""How far apart the sender's and the receiver's clocks may be. The architecture's window."""

MAX_BODY_BYTES: Final = 256 * 1024
"""The largest signed body a receiver will read at all.

Checked before the signature, because computing an HMAC over an unbounded body is exactly the
work an unauthenticated caller must not be able to demand.
"""


class SignatureError(ValueError):
    """A delivery that did not prove who sent it. One class, several reasons, no detail leaked.

    ``reason`` is for the receiver's own log. What goes back to the caller is a bare rejection:
    telling an unauthenticated sender *why* their signature failed is telling them how to make
    the next one succeed.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def timestamp_of(moment: datetime) -> str:
    """The wire form of an instant: whole seconds since the epoch, as text."""
    return str(int(moment.timestamp()))


def signature_for(*, secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over ``timestamp . body``, hex encoded.

    The separator is what stops two different (timestamp, body) pairs from concatenating to the
    same bytes -- without it, a timestamp ending in a digit that the body begins with would be
    ambiguous, and an ambiguity inside a signature is a forgery waiting to be found.
    """
    message = timestamp.encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, sha256).hexdigest()


def verify(
    *,
    secret: str,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    now: datetime | None = None,
    tolerance: timedelta = DEFAULT_TOLERANCE,
) -> None:
    """Accept the delivery, or raise :class:`SignatureError`. Nothing is returned on success.

    The order of the checks is deliberate: size, then presence, then the window, then the
    comparison. Every one of them is cheaper than the one after it, and the expensive one is
    the only one that touches the secret.
    """
    if len(body) > MAX_BODY_BYTES:
        raise SignatureError("body is larger than the signed-payload limit")
    if not timestamp or not signature:
        raise SignatureError("the signature headers are missing")

    try:
        sent_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise SignatureError(f"unreadable timestamp: {error}") from error

    moment = now or datetime.now(UTC)
    if abs(moment - sent_at) > tolerance:
        raise SignatureError("the timestamp is outside the replay window")

    expected = signature_for(secret=secret, timestamp=timestamp, body=body)
    # Constant time: a comparison that returned early would leak the correct prefix one
    # request at a time, which is enough to reconstruct a whole signature.
    if not hmac.compare_digest(expected, signature):
        raise SignatureError("the signature does not match the body")


def headers_for(*, secret: str, body: bytes, now: datetime | None = None) -> dict[str, str]:
    """The two headers a sender attaches. The secret never leaves this call."""
    stamp = timestamp_of(now or datetime.now(UTC))
    return {
        TIMESTAMP_HEADER: stamp,
        SIGNATURE_HEADER: signature_for(secret=secret, timestamp=stamp, body=body),
    }


__all__ = [
    "DEFAULT_TOLERANCE",
    "MAX_BODY_BYTES",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "SignatureError",
    "headers_for",
    "signature_for",
    "timestamp_of",
    "verify",
]
