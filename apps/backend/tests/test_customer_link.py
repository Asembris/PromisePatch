"""The possession link's pure half: what a signature binds, and what it refuses to bind.

No database, no worker, no HTTP. A link is a value in and a value out, and that is deliberate
rather than convenient: the thing that decides which question a stranger may open must be
readable and explainable without any infrastructure at all.

The file is mostly refusals, because the guarantee is mostly a refusal. A link opens exactly one
request on exactly one channel, and every way of editing it into another one has to fail. What
it may *not* do is prove who opened it, and the last section asserts the shape of that honesty
rather than trusting the docstring to carry it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from promisepatch.domain import customer_link

SECRET = "a-local-signing-secret"
OTHER_SECRET = "a-different-deployments-secret"
CHANNEL = "telegram:770001"
"""A channel address that contains the separator a naive encoding would have used."""


@pytest.fixture
def request_id() -> UUID:
    return uuid4()


# ------------------------------------------------------------------------------- what it binds


def test_a_minted_link_reads_back_as_what_it_was_minted_for(request_id: UUID) -> None:
    token = customer_link.mint(secret=SECRET, request_id=request_id, channel=CHANNEL)

    possession = customer_link.verify(secret=SECRET, token=token)

    assert possession.request_id == request_id
    assert possession.channel == CHANNEL


def test_minting_is_deterministic_so_a_resend_is_one_door(request_id: UUID) -> None:
    """A message composed twice carries the same link, not a second way in to the same question."""
    first = customer_link.mint(secret=SECRET, request_id=request_id, channel=CHANNEL)
    second = customer_link.mint(secret=SECRET, request_id=request_id, channel=CHANNEL)

    assert first == second


def test_a_link_is_url_safe(request_id: UUID) -> None:
    """It travels in an address bar, so it may hold nothing that has to be escaped there."""
    token = customer_link.mint(secret=SECRET, request_id=request_id, channel=CHANNEL)

    assert set(token) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def test_a_channel_holding_the_field_separator_is_still_read_back_exactly() -> None:
    """The one encoding bug that would matter, asserted rather than reasoned about.

    A colon is a character real channel addresses contain. If the payload were joined on one,
    two different (request, channel) pairs could pack into identical bytes -- and an ambiguity
    inside signed material is a forgery nobody has found yet.
    """
    awkward = "telegram:1:2:3"
    token = customer_link.mint(secret=SECRET, request_id=uuid4(), channel=awkward)

    assert customer_link.verify(secret=SECRET, token=token).channel == awkward


def test_two_requests_on_one_channel_do_not_share_a_link() -> None:
    a, b = uuid4(), uuid4()

    assert customer_link.mint(secret=SECRET, request_id=a, channel=CHANNEL) != customer_link.mint(
        secret=SECRET, request_id=b, channel=CHANNEL
    )


def test_two_channels_on_one_request_do_not_share_a_link(request_id: UUID) -> None:
    """The reason the channel is signed at all: a link is a door for one customer's channel."""
    mine = customer_link.mint(secret=SECRET, request_id=request_id, channel=CHANNEL)
    theirs = customer_link.mint(secret=SECRET, request_id=request_id, channel="telegram:770002")

    assert mine != theirs


# ---------------------------------------------------------------------------- what it refuses


def test_a_link_signed_by_another_deployment_opens_nothing(request_id: UUID) -> None:
    token = customer_link.mint(secret=OTHER_SECRET, request_id=request_id, channel=CHANNEL)

    with pytest.raises(customer_link.LinkError):
        customer_link.verify(secret=SECRET, token=token)


def test_a_tampered_signature_opens_nothing(request_id: UUID) -> None:
    token = customer_link.mint(secret=SECRET, request_id=request_id, channel=CHANNEL)
    version, payload, signature = token.split(".")
    flipped = signature[:-1] + ("A" if signature[-1] != "A" else "B")

    with pytest.raises(customer_link.LinkError):
        customer_link.verify(secret=SECRET, token=".".join((version, payload, flipped)))


def test_an_edited_payload_opens_nothing(request_id: UUID) -> None:
    """The attack the signature exists for: keep the signature, name a different request."""
    mine = customer_link.mint(secret=SECRET, request_id=request_id, channel=CHANNEL)
    theirs = customer_link.mint(secret=SECRET, request_id=uuid4(), channel=CHANNEL)
    _, their_payload, _ = theirs.split(".")
    version, _, my_signature = mine.split(".")

    with pytest.raises(customer_link.LinkError):
        customer_link.verify(secret=SECRET, token=".".join((version, their_payload, my_signature)))


@pytest.mark.parametrize(
    "token",
    ["", "not-a-token", "v1.onepart", "v1.two.parts.and.more", "..", "v1..", "v9.abc.def"],
)
def test_a_malformed_link_opens_nothing(token: str) -> None:
    with pytest.raises(customer_link.LinkError):
        customer_link.verify(secret=SECRET, token=token)


def test_a_link_claiming_another_format_is_refused_rather_than_guessed(request_id: UUID) -> None:
    """Relabelling a token must not reinterpret it: the version is inside the signature too."""
    token = customer_link.mint(secret=SECRET, request_id=request_id, channel=CHANNEL)
    _, payload, signature = token.split(".")

    with pytest.raises(customer_link.LinkError):
        customer_link.verify(secret=SECRET, token=".".join(("v2", payload, signature)))


def test_an_oversized_link_is_refused_before_it_is_decoded() -> None:
    """Hashing unbounded input is work an unauthenticated caller must not be able to demand."""
    with pytest.raises(customer_link.LinkError):
        customer_link.verify(secret=SECRET, token="v1." + "a" * customer_link.MAX_TOKEN_CHARACTERS)


def test_a_link_cannot_be_minted_for_no_channel(request_id: UUID) -> None:
    with pytest.raises(customer_link.LinkError):
        customer_link.mint(secret=SECRET, request_id=request_id, channel="")


# ------------------------------------------------------------------------------ what it is not


def test_a_verified_link_carries_no_identity(request_id: UUID) -> None:
    """Possession is what a link proves, so possession is all its result is allowed to hold.

    Asserted on the fields rather than left to the docstring: a ``customer`` attribute appearing
    here is the first step towards something downstream reading it as proof that a named person
    pressed a button, which no link can establish.
    """
    token = customer_link.mint(secret=SECRET, request_id=request_id, channel=CHANNEL)

    possession = customer_link.verify(secret=SECRET, token=token)

    assert set(possession.__slots__) == {"request_id", "channel"}


def test_the_link_module_names_no_parser_no_clock_and_no_table() -> None:
    """The structural half of "a link opens a page and decides nothing".

    Made over the syntax tree with every docstring removed, rather than over the text, for the
    reason the same assertion in ``test_customer_intent`` is: prose is where this module
    explains what it refuses to do, and a grep would either trip on the explanation or be
    weakened until it stopped meaning anything.

    A link that could reach the parser would be one import away from possession of a URL
    becoming consent. A link that could read a clock would be a second deadline kept where the
    customer's browser holds it.
    """
    tree = ast.parse(Path(customer_link.__file__).read_text(encoding="utf-8"))
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }

    named: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            named.add(node.id)
        elif isinstance(node, ast.Attribute):
            named.add(node.attr)
        elif isinstance(node, ast.alias):
            named.update(part for part in (node.name, node.asname) if part)
        elif isinstance(node, ast.ImportFrom) and node.module:
            named.add(node.module)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node not in docstrings
        ):
            named.add(node.value)

    forbidden = {
        "ApprovalDecision",
        "ApprovalDecisionKind",
        "ApprovalRequest",
        "approval_decisions",
        "approval_requests",
        "consent",
        "datetime",
        "now",
        "promisepatch.db",
        "promisepatch.domain.approvals",
        "promisepatch.domain.consent",
        "read_literal",
        "sqlalchemy",
        "time",
    }

    assert named & forbidden == set()


def test_a_url_carries_the_token_in_the_parameter_the_bundle_reads() -> None:
    request_id = uuid4()
    url = customer_link.url_for(
        base_url="https://bakery.example/", secret=SECRET, request_id=request_id, channel=CHANNEL
    )
    token = url.partition(f"?{customer_link.PARAM}=")[2]

    assert url.startswith("https://bakery.example/?")
    assert customer_link.verify(secret=SECRET, token=token).request_id == request_id
