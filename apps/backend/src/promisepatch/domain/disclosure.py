"""What a customer's channel address may not reach, and the one shape it is reduced to.

Pure, like :mod:`promisepatch.domain.consent` and for the same reason: a string in, a string
out. No database, no clock, no settings, no network. It decides nothing and authorises nothing;
it is the last thing a value passes through before a person reads it.

**The distinction this module exists to hold.** A customer's Telegram chat id is load-bearing
*inside* the system and disclosing *outside* it. The outbox needs it to address a message, the
consent protocol needs it to compare a reply's sender against the channel a request was sent to
(§14.3 check 8), and the audit ledger needs it to say what those two values actually were. None
of that is a reason for it to appear in a log line, on an operator's terminal or in an HTTP
response -- and until now it appeared in all three.

So the rule is a boundary rule rather than a storage rule:

    in the database, in the audit ledger, on the wire to the provider  -> the real address
    in a log, on a terminal, in an API response, on a rendered page    -> this module's output

**Why the whole address goes, rather than a hash of it.** A Telegram chat id is a decimal
number of about ten digits, so the space is roughly ten billion -- which a commodity GPU walks
through in seconds. Publishing ``sha256(chat_id)`` would therefore publish the chat id to
anybody who cared, while looking careful. There is no keyed digest here either: a key that
reached every rendering boundary would be a second secret to hold, rotate and leak, bought for
an operator convenience that :data:`~promisepatch.domain.analysis.EffectStatus.idempotency_key`
already provides. The honest reduction is the one that keeps nothing.

**What survives, and why it is enough.** The channel *kind*, because knowing a message went to
Telegram rather than to a console discloses nobody. Everything an operator correlates by --
the request id, the track id, the idempotency key, the effect state, the attempt count -- is
unaffected, because none of it was ever the customer's address.

**Both spellings are covered.** The engine carries a channel as ``tg:<id>``
(:mod:`promisepatch.graph.channel`) and the Telegram adapter stamps a reference as
``telegram:<id>:<message>`` (:mod:`promisepatch.integrations.telegram`). Those two vocabularies
are declared here in one set rather than imported, because the import contracts forbid
:mod:`promisepatch.integrations` both :mod:`promisepatch.db` and :mod:`promisepatch.graph`, and
a redaction helper that could not be called from the adapter would be a redaction helper that
did not cover the log line this module was written for. ``test_disclosure.py`` asserts the set
against both sources, so the duplication is checked rather than trusted.
"""

from __future__ import annotations

from typing import Final

MASK: Final = "***"
"""What replaces an address. Deliberately the same token the Telegram adapter uses for a token,
so one grep over a log finds every place this build decided somebody may not read something."""

SEPARATOR: Final = ":"
"""The one character that divides a prefix from what follows it, in both spellings."""

DIFFERENT_ADDRESS: Final = " (a different address)"
"""What is appended to a masked value that failed the comparison it was the right-hand side of.

Check 8 compares the channel a reply arrived on against the channel the request was sent to,
and masking both sides of a *failed* comparison would print two identical strings beside the
word FAIL. That is not a leak, but it is unreadable, and an operator looking at an
``UNAUTHORIZED`` refusal is the person with the most legitimate need to understand it. So the
pair is redacted together and inequality is reported as a fact rather than as two values: the
reader learns that the addresses differed, which is the whole of what check 8 concluded, and
learns neither of them.
"""

CHANNEL_PREFIXES: Final = frozenset(
    {
        # promisepatch.graph.channel.PREFIX_BY_KIND -- the engine's spelling.
        "tg",
        "wa",
        "console",
        # promisepatch.db.types.CHANNEL_KINDS -- the adapter's spelling, used by a provider_ref.
        "telegram",
        "whatsapp",
    }
)
"""Every prefix that introduces a customer address, in either vocabulary.

``console`` is in both sets and appears once. ``link``, ``fake-`` and ``amd-`` are deliberately
absent: a link reply id, a fake provider's reference and an order amendment's reference name no
person, and redacting them would cost an operator a real identifier to buy nothing.
"""


def redact_channel(value: str | None) -> str | None:
    """A channel string or provider reference with the address taken out of it.

    ``None`` passes through as ``None``, because "no reference" and "a reference we will not
    show you" are different facts and an operator reading ``-`` for both could not tell a
    message that never went from one whose receipt is being withheld.

    Everything after the prefix goes, not merely the next field. A channel address is arbitrary
    text that may itself contain a separator, so a rule that kept the final segment would be a
    rule that leaked the tail of any address long enough to have one. The Telegram message id
    is lost with it, and that is the price: it identifies nothing an operator can act on without
    access to the chat, and access to the chat is what this function exists to not grant.

    A value with no known channel prefix is returned unchanged. That is deliberate and is the
    reason the prefix set above is a closed list: this function is not a general scrubber, and
    one that masked anything shaped like ``<word>:<rest>`` would quietly eat identifiers the
    evidence surface depends on.
    """
    if value is None:
        return None
    prefix, separator, rest = value.partition(SEPARATOR)
    if not separator or not rest or prefix not in CHANNEL_PREFIXES:
        return value
    return f"{prefix}{SEPARATOR}{MASK}"


def redact_comparison(expected: str, actual: str, *, passed: bool) -> tuple[str, str]:
    """Redact the two halves of one check's evidence, keeping only whether they matched.

    ``passed`` is the check's own verdict, computed by :mod:`promise_graph.revalidation` on the
    real values before either reached this module. It is taken as an argument rather than
    inferred by comparing the two strings, because check 8's right-hand side is not the address
    alone: it is the decision's sender *and* the reply chain it was followed back to, so a
    passing check's two sides are never equal as text even when the addresses are.

    A pair whose right-hand side carries no channel address is returned with only the left one
    masked. That is the ``no decision`` case, where check 8 fails because nobody answered rather
    than because somebody else did, and a reader who was told "a different address" would be
    told something untrue.

    A pair with no channel address on either side -- which is every check but the eighth -- is
    returned exactly as it came in.
    """
    redacted_expected = redact_channel(expected)
    redacted_actual = redact_channel(actual)
    if redacted_actual == actual:
        return str(redacted_expected), actual
    if passed:
        return str(redacted_expected), str(redacted_actual)
    return str(redacted_expected), f"{redacted_actual}{DIFFERENT_ADDRESS}"


__all__ = [
    "CHANNEL_PREFIXES",
    "DIFFERENT_ADDRESS",
    "MASK",
    "SEPARATOR",
    "redact_channel",
    "redact_comparison",
]
