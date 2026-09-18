"""The signed possession link: what lets a customer reach one approval request, and no more.

Pure, like :mod:`promisepatch.domain.consent` and for the same reason. It takes a secret and a
pair of identifiers and returns a string; it verifies a string and returns the pair back. No
database, no clock, no network, no model. Everything it does *not* know about is the point of
it -- a module that could look a request up could decide something about one.

**What a link proves, exactly.** That whoever holds it was given it. That is possession, and it
is never identity: there is no account behind a bakery customer, no password, and nobody to
check a face against. A link that is forwarded is held by whoever it was forwarded to, and this
module cannot tell the difference -- so nothing in PromisePatch may treat opening one as proof
that a named person acted.

**What possession is therefore bounded to.** One request and one channel, both inside the
signature. A holder cannot edit the request id to answer somebody else's question, cannot edit
the channel to answer as somebody else, and cannot mint a link for a request they were never
sent. That is the whole of what signing buys, and it is bought precisely because possession is
weak: the weaker the proof, the narrower the thing it may open.

**The channel travels in the link and is checked against the request afterwards.** It would be
simpler to read the channel off the request row once the id is known, and it would be wrong:
the consent protocol's sender check (§14.3 check 8) compares the channel a reply *arrived on*
against the channel the request was *sent to*, and a transport that filled both sides of that
comparison from one row would turn a load-bearing check into a tautology. So the link carries
the channel it was minted for, the transport reports it as observed, and the existing check
stays a real one that a mismatched link fails.

**The link carries no expiry, deliberately.** The request's deadline is in the database, it is
compared against the database's clock under the request's own lock, and it is authoritative. An
expiry in the token would be a second, weaker deadline kept in a place the customer's browser
holds -- and two clocks disagreeing about whether consent was still possible is exactly the
ambiguity the consent protocol exists to not have. A link outlives its request and opens a page
that says so.

**Nothing here is authority.** Verifying a link produces two identifiers. Whether the request is
open, whether the window has closed, whether that channel is the right one, and what a literal
answer means are all decided elsewhere, against persisted rows, by code that already existed.
"""

from __future__ import annotations

import hmac
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from typing import Final
from uuid import UUID

VERSION: Final = "v1"
"""The one format this build mints and the only one it accepts.

Written into the signed material rather than only into the prefix, so a later version cannot be
produced by relabelling an old token: the signature covers which rules were meant to apply.
"""

SEPARATOR: Final = "."
"""What joins the three parts. Not a character base64url produces, so a split is unambiguous."""

FIELD_SEPARATOR: Final = "\x1f"
"""What joins the signed fields inside the payload.

A unit separator rather than a colon, because a channel address is arbitrary text and a colon
is a character it genuinely contains -- ``telegram:12345`` is a real channel. With a separator
the payload can hold, two different pairs could pack into the same bytes, and an ambiguity
inside signed material is a forgery somebody has not found yet.
"""

MAX_TOKEN_CHARACTERS: Final = 1024
"""The longest token this module will look at, checked before anything is decoded.

Decoding and hashing unbounded input is work an unauthenticated caller must not be able to
demand, and a real token is a small fraction of this.
"""


class LinkError(ValueError):
    """A link that did not prove it was minted here. One class, several reasons, none exported.

    ``reason`` is for our own log. What reaches the holder of a bad link is that the link does
    not open anything -- telling them *which* part failed is telling them how to fix it, and the
    only party who needs that is the one who wrote it themselves.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Possession:
    """What a valid link establishes: this request, reachable by whoever holds this channel.

    Named for what it is rather than for what it is convenient to call it. There is no
    ``customer`` field and no ``identity`` field, because neither is a thing this module knows,
    and a name that implied one would be the first step towards somewhere treating it as proof.
    """

    request_id: UUID
    channel: str


def mint(*, secret: str, request_id: UUID, channel: str) -> str:
    """Compose the link token for one request on one channel.

    Deterministic in its arguments alone: the same request and channel always produce the same
    token, so a message that is composed twice carries one link rather than two, and a resend
    cannot hand the customer a second door to the same question.
    """
    if not channel:
        raise LinkError("a link cannot be minted for an empty channel")
    payload = _encode(_material(request_id=request_id, channel=channel))
    return SEPARATOR.join((VERSION, payload, _signature(secret=secret, payload=payload)))


def verify(*, secret: str, token: str) -> Possession:
    """Read a token back, or raise :class:`LinkError`. Nothing is looked up and nothing decided.

    The order of the checks is cheapest first, and the one that touches the secret is last:
    length, shape, version, then the comparison. A caller that can make us hash before it has
    proved anything is a caller that can make us do work.
    """
    if not token or len(token) > MAX_TOKEN_CHARACTERS:
        raise LinkError("the link is empty or longer than a link can be")

    parts = token.split(SEPARATOR)
    if len(parts) != 3:
        raise LinkError("the link is not three parts")
    version, payload, signature = parts
    if version != VERSION:
        raise LinkError(f"the link claims format {version!r}, which this build does not mint")

    expected = _signature(secret=secret, payload=payload)
    # Constant time: a comparison that returned early would leak the correct prefix one request
    # at a time, which is enough to build a whole signature out of rejections.
    if not hmac.compare_digest(expected, signature):
        raise LinkError("the link is not signed by this deployment")

    return _decode(payload)


def url_for(*, base_url: str, secret: str, request_id: UUID, channel: str) -> str:
    """Where the customer's approval page for this request lives.

    A query parameter rather than a path segment, because the evidence surface is a single-page
    bundle whose other route is already ``?case=``, and because a token in a path is a token in
    more logs than a token in a query is not -- both are in the address, and neither is a
    secret that survives being pasted anywhere. What keeps it narrow is the signature, not
    where in the URL it sits.
    """
    token = mint(secret=secret, request_id=request_id, channel=channel)
    return f"{base_url.rstrip('/')}/?{PARAM}={token}"


PARAM: Final = "approve"
"""The query parameter the evidence bundle reads a token out of."""


# ------------------------------------------------------------------------------ the mechanics


def _material(*, request_id: UUID, channel: str) -> bytes:
    """The exact bytes that are signed: the version, the request, and the channel."""
    return FIELD_SEPARATOR.join((VERSION, str(request_id), channel)).encode("utf-8")


def _signature(*, secret: str, payload: str) -> str:
    """HMAC-SHA256 over the encoded payload, base64url without padding.

    Over the *encoded* payload rather than the decoded material, so verification never has to
    decode attacker-controlled bytes before it has established that they came from here.
    """
    digest = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), sha256).digest()
    return _b64(digest)


def _encode(material: bytes) -> str:
    return _b64(material)


def _decode(payload: str) -> Possession:
    """Read a payload whose signature has already held. Still validated, because bugs exist."""
    try:
        raw = urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise LinkError(f"the link's payload is unreadable: {error}") from error

    fields = raw.split(FIELD_SEPARATOR)
    if len(fields) != 3:
        raise LinkError("the link's payload does not hold three fields")
    version, raw_request, channel = fields
    if version != VERSION:
        raise LinkError("the link's signed version is not the one it claims")
    if not channel:
        raise LinkError("the link names no channel")
    try:
        return Possession(request_id=UUID(raw_request), channel=channel)
    except ValueError as error:
        raise LinkError(f"the link names no readable request: {error}") from error


def _b64(raw: bytes) -> str:
    """base64url with the padding stripped, so a token is one URL-safe word."""
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


__all__ = [
    "MAX_TOKEN_CHARACTERS",
    "PARAM",
    "VERSION",
    "LinkError",
    "Possession",
    "mint",
    "url_for",
    "verify",
]
