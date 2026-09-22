"""The customer channel: what it delivers, what it refuses, and what it never says.

No database and no network. Every test here drives the adapter against a scripted Bot API, so
the thing under test is the only thing being tested: how one provider's answers become the
three words the outbox understands, and what a bot token is allowed to touch on the way.

The properties this module exists to hold are not "the HTTP call is shaped right". They are:

* **the frozen wording survives the transport** -- byte for byte, with no markup mode that
  could reinterpret it, and refused rather than truncated when it will not fit;
* **a deterministic refusal is terminal** -- an unusable chat id, a blocked bot or a bad token
  costs one call and escalates the promise, instead of five calls and ten minutes of silence;
* **an uncertain answer is retryable, and the duplicate that may follow is one proposal** --
  the same key, the same words and the same link, which is the at-least-once guarantee the
  outbox states rather than an exactly-once one nobody can provide;
* **the credential reaches nothing but the request line** -- not a log, not an error recorded
  on a row, not a ``repr`` in a traceback;
* **the customer's chat id reaches nothing but the request line and the row** -- not the log
  line this adapter writes, which on the deployed host goes to CloudWatch through compose's
  ``awslogs`` driver, and not the ``provider_ref`` as anything but a channel kind once it is
  read back out.

What is deliberately absent is any test of an inbound path, because there is no inbound path:
a customer answers through the signed link on the surface that already existed, and this
adapter cannot read a reply, a webhook or an update.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest

from promisepatch import worker
from promisepatch.config import CustomerChannelProvider, Settings
from promisepatch.domain.adapters import FakeEffectAdapter, RoutedEffectAdapter
from promisepatch.domain.messaging import CONSENT_INSTRUCTION
from promisepatch.domain.model import (
    EFFECT_MESSAGE_SEND,
    EFFECT_ORDER_AMEND,
    DeliveryOutcome,
    DeliveryStatus,
)
from promisepatch.integrations.telegram import (
    API_ORIGIN,
    MAX_TEXT_CHARACTERS,
    REDACTED,
    TRANSPORT_LOGGERS,
    TelegramAdapter,
    build_customer_channel,
    compose,
)

TOKEN = "7654321:PLACEHOLDER-not-a-real-bot-token"
"""Deliberately not the shape of a Bot API credential.

A realistic-looking one would be caught by the secret scanner CI runs over every commit, and
the correct response to that would be to change this constant rather than to allowlist a
pattern -- an allowlist wide enough to admit a fake token is wide enough to admit a real one.
Nothing here depends on the shape: what is under test is where the value is allowed to travel.
"""
CHAT = "1002"
KEY = "approval-message:5f0c7f3e"
LINK = "https://bakery.example/?approve=v1.cGF5bG9hZA.c2lnbmF0dXJl"

TEXT = (
    "Hello Lena. Your Raspberry Lemon Layer for order ORD-1002 is affected. "
    f"We can make it with lemon curd instead (option A). {CONSENT_INSTRUCTION}"
)


def payload(**overrides: Any) -> dict[str, Any]:
    """One approval message as :func:`promisepatch.domain.approvals` really writes it."""
    body: dict[str, Any] = {
        "track_id": "3f2a0e2c-0000-4000-8000-000000000001",
        "request_id": "3f2a0e2c-0000-4000-8000-000000000002",
        "promise_id": "P-1002",
        "order_id": "ORD-1002",
        "option_code": "A",
        "channel_kind": "telegram",
        "channel_address": CHAT,
        "approval_url": LINK,
        "text": TEXT,
    }
    body.update(overrides)
    return body


class Telegram:
    """A scripted Bot API. Records every request, answers from a queue, never dedupes.

    Never deduping is the honest part. A fake that collapsed two ``sendMessage`` calls under
    one key would be modelling a provider that does not exist, and the duplicate this adapter
    can produce would stop being visible in the one place it is meant to be visible.
    """

    def __init__(self, *answers: httpx2.Response | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[httpx2.Request] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else ok(990 + len(self.requests))
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def bodies(self) -> list[dict[str, Any]]:
        import json

        return [json.loads(request.content) for request in self.requests]


def ok(message_id: int = 991) -> httpx2.Response:
    return httpx2.Response(
        200, json={"ok": True, "result": {"message_id": message_id, "date": 1, "text": "sent"}}
    )


def refusal(status: int, description: str) -> httpx2.Response:
    return httpx2.Response(
        status, json={"ok": False, "error_code": status, "description": description}
    )


def adapter_for(telegram: Telegram) -> TelegramAdapter:
    return TelegramAdapter(
        bot_token=TOKEN,
        timeout=1.0,
        client=httpx2.AsyncClient(transport=httpx2.MockTransport(telegram.handle)),
    )


@pytest.fixture
def scripted() -> Iterator[Telegram]:
    yield Telegram()


async def deliver(
    telegram: Telegram, *, kind: str = EFFECT_MESSAGE_SEND, key: str = KEY, **overrides: Any
) -> DeliveryOutcome:
    adapter = adapter_for(telegram)
    try:
        return await adapter.deliver(kind=kind, payload=payload(**overrides), idempotency_key=key)
    finally:
        await adapter.aclose()


# ------------------------------------------------------------------------------- the happy path


async def test_a_message_and_its_link_reach_the_chat_the_request_named(
    scripted: Telegram,
) -> None:
    outcome = await deliver(scripted)

    assert outcome.status is DeliveryStatus.DELIVERED
    assert outcome.provider_ref == f"telegram:{CHAT}:991"
    assert outcome.error is None

    body = scripted.bodies[0]
    assert body["chat_id"] == CHAT
    assert body["text"] == f"{TEXT}\n\n{LINK}"
    assert str(scripted.requests[0].url).startswith(f"{API_ORIGIN}/bot")


async def test_the_frozen_wording_is_sent_as_text_and_not_as_markup(
    scripted: Telegram,
) -> None:
    """§13.6's sentence is reproduced exactly, and no parse mode may reinterpret it.

    A recipe name with an underscore or an asterisk in it is a recipe name. Sent as Markdown,
    Telegram would swallow the character and change the words a customer reads -- which is the
    one thing a transport may not do to a message whose wording is frozen.
    """
    await deliver(scripted, text=f"Almond_Pear tart *today*. {CONSENT_INSTRUCTION}")

    body = scripted.bodies[0]
    assert "parse_mode" not in body
    assert body["text"].startswith("Almond_Pear tart *today*.")
    assert CONSENT_INSTRUCTION in body["text"]


async def test_the_link_preview_is_disabled_so_nobody_else_opens_the_link(
    scripted: Telegram,
) -> None:
    """A possession link is for the person it was sent to, and a crawler is not that person."""
    await deliver(scripted)
    assert scripted.bodies[0]["link_preview_options"] == {"is_disabled": True}


async def test_a_deployment_that_mints_no_link_sends_the_words_unchanged(
    scripted: Telegram,
) -> None:
    """The two literal answers are the whole protocol; the link is a convenience beside them."""
    await deliver(scripted, approval_url=None)
    assert scripted.bodies[0]["text"] == TEXT


def test_compose_appends_the_link_beside_the_words_and_never_inside_them() -> None:
    assert compose(text="words", approval_url="https://x/?approve=t") == (
        "words\n\nhttps://x/?approve=t"
    )
    assert compose(text="words", approval_url=None) == "words"
    assert compose(text="words", approval_url="") == "words"


# --------------------------------------------------------------------- destinations it refuses


async def test_an_effect_that_is_not_a_customer_message_is_refused_unsent(
    scripted: Telegram,
) -> None:
    """An adapter that guessed at an unfamiliar kind would report a success nobody performed."""
    outcome = await deliver(scripted, kind=EFFECT_ORDER_AMEND)

    assert outcome.status is DeliveryStatus.TERMINAL
    assert "ORDER_AMEND" in str(outcome.error)
    assert scripted.requests == []


@pytest.mark.parametrize("kind", ["console", "whatsapp", "", None])
async def test_a_message_for_another_channel_is_never_sent_to_telegram(
    scripted: Telegram, kind: str | None
) -> None:
    """The stored channel kind decides. Otherwise one customer's chat id is another's number."""
    outcome = await deliver(scripted, channel_kind=kind)

    assert outcome.status is DeliveryStatus.TERMINAL
    assert scripted.requests == []


@pytest.mark.parametrize(
    "address",
    ["", "   ", "@lena", "abc", "10 02", "1002;drop", "+21612345678", "1" * 21, None, 1002],
)
async def test_an_address_that_is_not_a_chat_id_is_refused_before_the_call(
    scripted: Telegram, address: Any
) -> None:
    """Deterministic, so terminal: it will not become a chat id on the fourth attempt.

    ``@lena`` is refused although the Bot API would accept it. A username is reassignable, so a
    message addressed to one can arrive at whoever holds the name today rather than at the
    customer the approval request was created for.
    """
    outcome = await deliver(scripted, channel_address=address)

    assert outcome.status is DeliveryStatus.TERMINAL
    assert "chat id" in str(outcome.error)
    assert scripted.requests == []


@pytest.mark.parametrize("address", ["1002", "-1001234567890"])
async def test_a_group_chat_id_is_a_chat_id(scripted: Telegram, address: str) -> None:
    outcome = await deliver(scripted, channel_address=address)
    assert outcome.status is DeliveryStatus.DELIVERED


async def test_an_effect_with_no_words_in_it_sends_nothing(scripted: Telegram) -> None:
    outcome = await deliver(scripted, text="   ")
    assert outcome.status is DeliveryStatus.TERMINAL
    assert scripted.requests == []


async def test_a_message_too_long_for_telegram_is_refused_rather_than_shortened(
    scripted: Telegram,
) -> None:
    """Truncating would cut the instruction off the end of a request for consent."""
    outcome = await deliver(scripted, text="x" * MAX_TEXT_CHARACTERS)

    assert outcome.status is DeliveryStatus.TERMINAL
    assert "refused rather than shortened" in str(outcome.error)
    assert scripted.requests == []


# ------------------------------------------------------------------- what the provider answers


@pytest.mark.parametrize(
    ("status", "description"),
    [
        (400, "Bad Request: chat not found"),
        (401, "Unauthorized"),
        (403, "Forbidden: bot was blocked by the user"),
        (404, "Not Found"),
    ],
)
async def test_a_deterministic_refusal_stops_at_one_attempt(status: int, description: str) -> None:
    """Five attempts at an answer that cannot change is ten minutes of nobody being told."""
    telegram = Telegram(refusal(status, description))
    outcome = await deliver(telegram)

    assert outcome.status is DeliveryStatus.TERMINAL
    assert description in str(outcome.error)
    assert len(telegram.requests) == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_an_answer_that_may_change_is_retryable(status: int) -> None:
    telegram = Telegram(refusal(status, "Too Many Requests: retry after 30"))
    outcome = await deliver(telegram)

    assert outcome.status is DeliveryStatus.RETRYABLE
    assert str(status) in str(outcome.error)


@pytest.mark.parametrize(
    "error",
    [
        httpx2.ReadTimeout("the answer never arrived"),
        httpx2.ConnectError("no route to api.telegram.org"),
        httpx2.RemoteProtocolError("the server hung up"),
    ],
)
async def test_a_transport_failure_is_uncertain_rather_than_failed(
    error: Exception,
) -> None:
    """Telegram may well have sent it. The retry is the honest response, and it may duplicate."""
    telegram = Telegram(error)
    outcome = await deliver(telegram)

    assert outcome.status is DeliveryStatus.RETRYABLE
    assert type(error).__name__ in str(outcome.error)


async def test_an_acceptance_this_build_cannot_read_is_terminal() -> None:
    """A completed round trip whose answer is unreadable will read the same way next time.

    Terminal rather than retryable, deliberately: the promise goes to the owner instead of into
    a ladder that could put a third copy of one message on a customer's phone.
    """
    telegram = Telegram(httpx2.Response(200, json={"ok": True, "result": {}}))
    outcome = await deliver(telegram)

    assert outcome.status is DeliveryStatus.TERMINAL
    assert "no message id" in str(outcome.error)


async def test_a_delivered_message_reports_no_authoritative_result() -> None:
    """Telegram is a transport, not a system of record the recovery must later agree with.

    ``result`` carries what a provider *did* for a provider that is a system of record, and a
    recovery is required to verify that before it may claim to be finished. A transport that
    filled it in would be inviting a verification of nothing.
    """
    telegram = Telegram(ok(17))
    outcome = await deliver(telegram)

    assert outcome.status is DeliveryStatus.DELIVERED
    assert outcome.result is None
    assert outcome.provider_ref is not None


# ------------------------------------------------------------- the duplicate, stated honestly


async def test_two_attempts_under_one_key_send_one_proposal_twice() -> None:
    """The Bot API has no idempotency key, so the second call is a second message. Say so.

    This is the documented at-least-once case, and what makes it survivable is in the
    assertions: the two calls are byte-identical. Same chat, same frozen words, same signed
    link -- so what a customer may receive twice is one proposal, opening one approval request,
    answerable once. It is never a second question and never a second authority.

    ``docs/`` and :mod:`promisepatch.domain.outbox` both state the rest: the key is stable
    across a crash in the uncertain window, and a provider without key support records two
    where one honouring keys would record one.
    """
    telegram = Telegram(ok(31), ok(32))
    adapter = adapter_for(telegram)
    try:
        first = await adapter.deliver(
            kind=EFFECT_MESSAGE_SEND, payload=payload(), idempotency_key=KEY
        )
        second = await adapter.deliver(
            kind=EFFECT_MESSAGE_SEND, payload=payload(), idempotency_key=KEY
        )
    finally:
        await adapter.aclose()

    assert first.status is second.status is DeliveryStatus.DELIVERED
    assert len(telegram.requests) == 2
    assert telegram.bodies[0] == telegram.bodies[1]
    assert first.provider_ref != second.provider_ref


async def test_a_retry_after_an_uncertain_answer_repeats_the_identical_call() -> None:
    """The shape a crash in the uncertain window produces: timeout, then the same call again."""
    telegram = Telegram(httpx2.ReadTimeout("lost after sending"), ok(44))
    adapter = adapter_for(telegram)
    try:
        first = await adapter.deliver(
            kind=EFFECT_MESSAGE_SEND, payload=payload(), idempotency_key=KEY
        )
        second = await adapter.deliver(
            kind=EFFECT_MESSAGE_SEND, payload=payload(), idempotency_key=KEY
        )
    finally:
        await adapter.aclose()

    assert first.status is DeliveryStatus.RETRYABLE
    assert second.status is DeliveryStatus.DELIVERED
    assert telegram.bodies[0] == telegram.bodies[1]


# ---------------------------------------------------------------------------- the credential


async def test_the_bot_token_reaches_the_request_line_and_nothing_else(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Everywhere a secret could end up, checked in one place, including the row.

    ``last_error`` on the outbox row is written from ``outcome.error``, and an outbox row is
    read by every evidence surface there is -- so a token in an error string is a token
    published. Transport failures are therefore recorded by exception *type*: an httpx error's
    own message can carry the URL it failed on, and that URL is the credential.
    """
    telegram = Telegram(
        refusal(400, "Bad Request: chat not found"),
        httpx2.ConnectError(f"failed connecting to {API_ORIGIN}/bot{TOKEN}/sendMessage"),
    )
    adapter = adapter_for(telegram)
    with caplog.at_level("DEBUG"):
        try:
            refused = await adapter.deliver(
                kind=EFFECT_MESSAGE_SEND, payload=payload(), idempotency_key=KEY
            )
            unreachable = await adapter.deliver(
                kind=EFFECT_MESSAGE_SEND, payload=payload(), idempotency_key=KEY
            )
        finally:
            await adapter.aclose()

    assert TOKEN not in str(refused.error)
    assert TOKEN not in str(unreachable.error)
    assert TOKEN not in repr(adapter)
    assert TOKEN not in caplog.text
    # And the one place it does belong: the request this adapter actually made.
    assert TOKEN in str(telegram.requests[0].url)
    # Redacted, not silenced. The client's own request line is still there for an operator to
    # read -- which is the difference between hiding a credential and hiding an outage.
    assert "sendMessage" in caplog.text
    assert REDACTED in caplog.text


async def test_a_provider_that_echoed_the_token_back_would_not_get_it_into_a_row() -> None:
    """Telegram does not do this. The guarantee is that it would not matter if it did."""
    telegram = Telegram(refusal(400, f"Bad Request: bad token {TOKEN}"))
    outcome = await deliver(telegram)

    assert outcome.status is DeliveryStatus.TERMINAL
    assert TOKEN not in str(outcome.error)
    assert "***" in str(outcome.error)


async def test_neither_the_words_nor_the_link_are_logged(
    caplog: pytest.LogCaptureFixture, scripted: Telegram
) -> None:
    """A log line carrying the link would hand an approval to whoever reads the logs."""
    with caplog.at_level("DEBUG"):
        await deliver(scripted)

    assert LINK not in caplog.text
    assert CONSENT_INSTRUCTION not in caplog.text


async def test_the_chat_id_is_not_logged_in_any_field(
    capsys: pytest.CaptureFixture[str], scripted: Telegram
) -> None:
    """The leak this adapter shipped with, asserted over the line as it is really rendered.

    ``worker.telegram.sent`` carried ``chat_id`` as its own field and carried it again inside
    ``provider_ref``, and the deployed compose ships that line to a CloudWatch log group
    through the ``awslogs`` driver. So a real person's Telegram identifier sat in a log group --
    the one piece of care ``channel_binding`` takes everywhere else and this line did not.

    Captured from stdout rather than through ``caplog``, because the renderer is what a log
    group receives and a test reading the stdlib record would be asserting about a string
    nobody ships. It is asserted over the whole line rather than a named field, so a future
    field carrying the address under another name fails here too.
    """
    outcome = await deliver(scripted)
    written = capsys.readouterr().out

    assert outcome.status is DeliveryStatus.DELIVERED
    assert "worker.telegram.sent" in written
    assert CHAT not in written
    assert "chat_id" not in written
    assert "telegram:***" in written
    # The correlating identifier survives, because it names nobody and is what an operator
    # joins a delivery to its outbox row with.
    assert KEY in written


async def test_the_delivered_reference_still_carries_the_address_for_the_row() -> None:
    """Redaction is a boundary rule, not a storage rule, and this is the half that stores.

    The outbox row keeps the whole reference: it is the provider's own receipt, it is what a
    redelivery is reasoned about against, and the ledger is where a reader who is entitled to
    ask *which* chat was reached finds the answer. What must not carry it is the log line
    above and the projection an operator screen and an HTTP response are built from.
    """
    telegram = Telegram(ok(4242))
    outcome = await deliver(telegram)

    assert outcome.provider_ref == f"telegram:{CHAT}:4242"


async def test_the_redaction_is_installed_while_the_adapter_is_open_and_not_after() -> None:
    """A filter left behind on a shared logger is a leak of a different kind.

    It holds the credential of an adapter nobody is using any more, and every closed adapter
    would add another one to the same logger for the life of the process.
    """
    installed = TelegramAdapter(bot_token=TOKEN, timeout=1.0)
    assert all(_redactions(name) == 1 for name in TRANSPORT_LOGGERS)

    await installed.aclose()
    assert all(_redactions(name) == 0 for name in TRANSPORT_LOGGERS)


def _redactions(name: str) -> int:
    return sum(
        getattr(one, "name", "") == "promisepatch.telegram.redaction"
        for one in logging.getLogger(name).filters
    )


# -------------------------------------------------------------------------------- selection


def test_the_fake_channel_is_what_an_unconfigured_deployment_gets() -> None:
    """CI, every test and the local stack: no credential, no network, no message to anybody."""
    assert Settings().customer_channel_provider is CustomerChannelProvider.FAKE
    assert build_customer_channel(Settings()) is None


def test_selecting_telegram_without_a_token_refuses_to_start() -> None:
    """The alternative is worse than a crash.

    A deployment that fell back here would believe it was contacting customers while delivering
    to an in-memory provider: approval requests marked sent, tracks waiting, deadlines running,
    and nobody ever asked.
    """
    settings = Settings(
        customer_channel_provider=CustomerChannelProvider.TELEGRAM, telegram_bot_token=None
    )
    with pytest.raises(RuntimeError, match="PP_TELEGRAM_BOT_TOKEN"):
        build_customer_channel(settings)


def test_selecting_telegram_with_a_token_builds_the_adapter() -> None:
    settings = Settings(
        customer_channel_provider=CustomerChannelProvider.TELEGRAM,
        telegram_bot_token=TOKEN,
        telegram_timeout_seconds=4.5,
    )
    built = build_customer_channel(settings)

    assert isinstance(built, TelegramAdapter)
    assert built.timeout == 4.5
    assert TOKEN not in repr(built)


def test_an_empty_token_is_not_a_token() -> None:
    with pytest.raises(ValueError, match="empty bot token"):
        TelegramAdapter(bot_token="   ", timeout=1.0)


def test_the_token_does_not_survive_a_settings_repr() -> None:
    assert TOKEN not in repr(Settings(telegram_bot_token=TOKEN))


# --------------------------------------------------------------------------- what a worker gets

UNCONNECTED = "postgresql+asyncpg://promisepatch_app:never-used@127.0.0.1:1/promisepatch"
"""A well-formed runtime URL nothing in this module connects to.

``RuntimeDatabase.from_settings`` builds an engine and opens no connection, so a worker can be
composed and disposed here without a database -- which is the point: what is under test is the
wiring decision, and a decision that needed Postgres to observe would be one nobody could
check on the machine that makes it.
"""


async def test_a_worker_selected_for_telegram_without_a_token_fails_before_anything_else() -> None:
    """And it fails naming the right variable, which is the whole of the assertion.

    These settings are missing a database URL as well. If the channel were built later -- after
    the engine, or lazily on the first message -- the error a deployer saw would be about
    ``PP_DATABASE_URL``, or would not arrive until a case had already queued an approval. It
    arrives first, and it names the thing that is actually wrong.
    """
    settings = Settings(
        customer_channel_provider=CustomerChannelProvider.TELEGRAM,
        telegram_bot_token=None,
        database_url=None,
    )
    with pytest.raises(RuntimeError, match="PP_TELEGRAM_BOT_TOKEN"):
        async with worker.built(settings):
            pass  # pragma: no cover - the context manager never opens


async def test_a_configured_worker_routes_customer_messages_to_telegram_and_nothing_else() -> None:
    """One table, built where the process is composed. Everything unrouted stays on the fake."""
    settings = Settings(
        customer_channel_provider=CustomerChannelProvider.TELEGRAM,
        telegram_bot_token=TOKEN,
        database_url=UNCONNECTED,
    )
    async with worker.built(settings) as running:
        adapter = running.adapter
        assert isinstance(adapter, RoutedEffectAdapter)
        assert isinstance(adapter.routes[EFFECT_MESSAGE_SEND], TelegramAdapter)
        assert EFFECT_ORDER_AMEND not in adapter.routes
        assert isinstance(adapter.default, FakeEffectAdapter)


async def test_an_unconfigured_worker_sends_a_customer_message_nowhere_real() -> None:
    """The default everywhere: CI, the local stack, and any deployment that said nothing."""
    settings = Settings(database_url=UNCONNECTED)
    async with worker.built(settings) as running:
        assert isinstance(running.adapter, FakeEffectAdapter)
