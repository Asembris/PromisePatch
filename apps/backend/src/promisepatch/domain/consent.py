"""The literal consent parser: the only thing in PromisePatch that can read a customer's yes.

Pure, tiny, and deliberately unhelpful. It takes the text of a reply and returns a decision or
nothing at all. It performs no database access, no network call, no model invocation and no
reading of intent, because everything it does *not* do is the point of it.

**Why so narrow.** §15's authority table gives customer consent exactly one deterministic
source: "**Only** the literal parser: literal YES / exact option code -> APPROVE; literal NO ->
DECLINE", and gives the model an explicitly non-authoritative role that "can never produce a
decision". A parser that grew a synonym list would be a second, undocumented consent protocol,
and every phrase it accepted would be a change to somebody's order that nobody agreed to in
words. "Strawberries work" is a sentence about strawberries; it is not a signature.

**Matching is exact, never substring.** ``"yes please"`` and ``"no thanks"`` produce no
decision, and so does every phrase that merely contains a token. A reply that is not exactly
one of the two words is not a decision; it is text, and it is stored as text.

Normalisation is the frozen one (§18.5): trim, casefold, and strip surrounding punctuation, so
``" Yes. "`` is the same answer as ``"YES"`` and nothing in the middle of the string is
touched. Anything else the customer wrote survives into the stored reply exactly as they wrote
it, for the later semantic slice to read as apparent intent -- which will still not be consent.

The option code that §13.6 also accepts is deliberately not implemented here yet: the message
this slice sends invites ``YES`` or ``NO`` and nothing else, and a parser that accepted a token
the customer was never asked for would be wider than the protocol it enforces. Narrower is the
safe direction; widening it is a change to the message and the parser together.
"""

from __future__ import annotations

from typing import Final

from promise_graph.model import ApprovalDecisionKind

APPROVE_TOKEN: Final = "yes"
DECLINE_TOKEN: Final = "no"
"""The two words that mean something. Casefolded, because that is the form compared."""

TRIM_CHARACTERS: Final = " \t\r\n.!?,;:'\"()[]"
"""Whitespace and the punctuation a person puts around a word, stripped from both ends only.

A fixed set rather than a Unicode category test, so what the parser accepts is readable here in
full and cannot change underneath us when a Python release reclassifies a character.
"""


def normalize(text: str) -> str:
    """The comparable form of a reply: trimmed, casefolded, unwrapped from its punctuation.

    Deterministic in its argument alone. Nothing about the request, the customer or the clock
    reaches it, so the same text always normalises to the same string.
    """
    return text.strip(TRIM_CHARACTERS).casefold().strip(TRIM_CHARACTERS)


def read_literal(text: str) -> ApprovalDecisionKind | None:
    """``APPROVE`` for a literal yes, ``DECLINE`` for a literal no, ``None`` for anything else.

    ``None`` is the ordinary answer for ordinary human writing, and it is not a failure: it
    means this reply is not a decision, so nothing is decided. The caller stores the text and
    leaves the request open.
    """
    normalized = normalize(text)
    if normalized == APPROVE_TOKEN:
        return ApprovalDecisionKind.APPROVE
    if normalized == DECLINE_TOKEN:
        return ApprovalDecisionKind.DECLINE
    return None


__all__ = [
    "APPROVE_TOKEN",
    "DECLINE_TOKEN",
    "TRIM_CHARACTERS",
    "normalize",
    "read_literal",
]
