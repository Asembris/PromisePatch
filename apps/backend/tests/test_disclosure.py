"""What a customer's channel address may reach, and the boundaries it is stopped at.

Two halves, and the second is the one that matters. The first tests the pure reduction in
:mod:`promisepatch.domain.disclosure` -- a string in, a string out, no infrastructure. The
second asserts the property the module exists for, which is not "the function works" but
**nothing renders an address**: the projection an operator terminal and an HTTP response are
both built from, and the log line the deployed worker writes to CloudWatch.

The distinction under test throughout is between storing and disclosing. The outbox row, the
approval request row, the decision row and the audit ledger all keep the real address, because
addressing a message, matching a reply to the channel it was owed to (§14.3 check 8) and saying
afterwards what those two values were all need it. None of that is a reason for it to appear in
a log group, on a terminal or on a page anybody holding a case id can open -- and before this
module it appeared in all three.
"""

from __future__ import annotations

import pytest

from promisepatch.db.types import CHANNEL_KINDS
from promisepatch.domain import disclosure
from promisepatch.graph.channel import PREFIX_BY_KIND

CHAT = "1234567890"
"""A chat id of the shape a real one has: ten decimal digits, which is why nothing here hashes.

The space is about ten billion, so a truncated digest of one is a digest a commodity GPU walks
through in seconds. That is the whole argument for masking rather than fingerprinting, and it
is recorded here beside the value it is an argument about.
"""


# ------------------------------------------------------------------- the reduction itself


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (f"telegram:{CHAT}:42", "telegram:***"),
        (f"tg:{CHAT}", "tg:***"),
        (f"whatsapp:{CHAT}:7", "whatsapp:***"),
        (f"wa:{CHAT}", "wa:***"),
        ("console:demo-customer", "console:***"),
    ],
)
def test_an_address_is_reduced_to_its_channel_kind(value: str, expected: str) -> None:
    """Both vocabularies, and everything after the prefix goes -- not merely the next field.

    A channel address is arbitrary text that may itself contain a separator, so a rule that
    kept the final segment would leak the tail of any address long enough to have one. The
    Telegram message id is lost with it, which is the price: it identifies nothing an operator
    can act on without access to the chat, and access to the chat is what this prevents.
    """
    assert disclosure.redact_channel(value) == expected
    assert CHAT not in str(disclosure.redact_channel(value))


@pytest.mark.parametrize(
    "value",
    [
        "fake-abc123def456",
        "amd-e735e9398046",
        "link:69c047c7-0000-4000-8000-000000000001",
        "OPT-4D3FFD",
        "ACCEPTED or AMENDED @ v1",
        "now <= 2026-09-22T21:47:06.452592Z",
        "SCHEDULED and start 2026-09-22T22:47:06.452592Z",
        "",
    ],
)
def test_a_value_that_names_no_person_is_returned_unchanged(value: str) -> None:
    """The prefix list is closed on purpose: this is not a general scrubber.

    One that masked anything shaped like ``<word>:<rest>`` would quietly eat the identifiers
    the evidence surface is built out of -- an order amendment's reference, a timestamp, the
    expected half of eight of the ten checks.
    """
    assert disclosure.redact_channel(value) == value


def test_no_reference_and_a_withheld_one_stay_different_facts() -> None:
    """``None`` passes through, so a message that never went reads differently from one whose
    receipt is being withheld."""
    assert disclosure.redact_channel(None) is None


def test_the_prefix_list_covers_both_vocabularies_that_exist() -> None:
    """The one duplication in the module, checked rather than trusted.

    :mod:`promisepatch.domain.disclosure` declares its prefixes instead of importing them,
    because the import contracts forbid :mod:`promisepatch.integrations` both
    :mod:`promisepatch.db` and :mod:`promisepatch.graph` -- and a helper the adapter could not
    call would not cover the log line it was written for. This is what keeps the copy honest:
    a channel kind added to the schema without being added here fails right here.
    """
    assert set(PREFIX_BY_KIND.values()) <= disclosure.CHANNEL_PREFIXES
    assert set(CHANNEL_KINDS) <= disclosure.CHANNEL_PREFIXES


# --------------------------------------------------------------- check 8's pair of addresses


def test_a_passing_comparison_masks_both_halves() -> None:
    """Check 8's right-hand side is the sender *and* the chain it was followed back to.

    So the two sides are never equal as text even when the addresses are, which is exactly why
    :func:`~promisepatch.domain.disclosure.redact_comparison` is told the verdict instead of
    inferring it by comparing the strings.
    """
    expected, actual = disclosure.redact_comparison(
        f"tg:{CHAT}", f"tg:{CHAT} via tg:{CHAT}", passed=True
    )

    assert (expected, actual) == ("tg:***", "tg:***")
    assert CHAT not in expected
    assert CHAT not in actual


def test_a_failing_comparison_reports_difference_and_neither_address() -> None:
    """An operator reading an ``UNAUTHORIZED`` refusal learns what check 8 concluded.

    Which is that the addresses differed -- and not what either of them was. Two identical
    masks beside the word FAIL would be no leak and no information; this is the same non-leak
    with the finding kept.
    """
    other = "9876543210"
    expected, actual = disclosure.redact_comparison(
        f"tg:{CHAT}", f"tg:{other} via tg:{other}", passed=False
    )

    assert expected == "tg:***"
    assert actual == "tg:*** (a different address)"
    assert CHAT not in actual
    assert other not in actual


def test_a_check_that_failed_because_nobody_answered_is_not_called_a_different_address() -> None:
    """Check 8 fails two ways, and telling them apart is the reader's whole question.

    Nobody answered, or somebody else did. A right-hand side carrying no address at all is the
    first, and a reader told "a different address" would be told something untrue.
    """
    expected, actual = disclosure.redact_comparison(f"tg:{CHAT}", "none", passed=False)

    assert expected == "tg:***"
    assert actual == "none"


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("ACCEPTED or AMENDED @ v1", "ACCEPTED @ v1"),
        ("rv-raspberry-rose-2", "rv-raspberry-rose-2"),
        (">= 2.200", "3.200"),
        ("LITERAL", "LITERAL"),
    ],
)
def test_the_other_nine_checks_pass_through_untouched(expected: str, actual: str) -> None:
    """Nine of the ten compare no address, and none of them is reworded on the way out."""
    assert disclosure.redact_comparison(expected, actual, passed=True) == (expected, actual)
