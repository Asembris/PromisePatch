"""``pp channel check``: what an operator may learn, and what the command cannot do.

No database, no AWS and no socket. Every test here drives the real preflight against a scripted
Bot API, so the structural checks, the error mapping and the token redaction under test are the
production ones and only the transport is fake.

The properties this module exists to hold are not "the HTTP call is shaped right". They are:

* **it cannot reach a customer** -- there is no ``sendMessage`` in the command, no text to put
  in one, and no ``getUpdates``, webhook or parser that could read a reply back;
* **``200`` is not the question** -- an answer that is not a bot, or not readable, is a refusal
  rather than a report, because a preflight that trusted a status code would pass on both;
* **the credential reaches nothing an operator can see** -- not the terminal, not a diagnostic,
  and not the URL it was called on, since the Bot API takes its token in the request path and
  that URL therefore *is* the secret;
* **a working credential is not a switched-on transport** -- the report says which it is, so a
  green check is never read as "this deployment is contacting customers".
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from typer.testing import CliRunner

from promisepatch import cli
from promisepatch.cli import app, channel_app
from promisepatch.config import Settings, get_settings
from promisepatch.integrations.telegram import (
    TelegramAdapter,
    TelegramPreflight,
    build_customer_channel,
)

runner = CliRunner()

TOKEN = "7654321:PLACEHOLDER-not-a-real-bot-token"
"""Deliberately not the shape of a Bot API credential.

For the reason ``test_telegram_channel`` gives: a realistic-looking one would be caught by the
secret scanner CI runs over every commit, and an allowlist wide enough to admit a fake token is
wide enough to admit a real one. Nothing here depends on the shape.
"""

BOT_ID = 7654321
BOT_NAME = "promisepatch_demo_bot"
CHAT = "1002"


class ScriptedBotApi:
    """A Bot API that records every request and answers from a queue. It cannot send."""

    def __init__(self, *answers: httpx2.Response | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[httpx2.Request] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else bot_ok()
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def methods(self) -> list[str]:
        """Which Bot API methods were called, in order, read off the paths they were called on."""
        return [request.url.path.rsplit("/", 1)[-1] for request in self.requests]


def bot_ok(username: str = BOT_NAME, bot_id: int = BOT_ID) -> httpx2.Response:
    return httpx2.Response(
        200, json={"ok": True, "result": {"id": bot_id, "is_bot": True, "username": username}}
    )


def chat_ok(chat_id: int = 1002, chat_type: str = "private") -> httpx2.Response:
    return httpx2.Response(200, json={"ok": True, "result": {"id": chat_id, "type": chat_type}})


def refusal(status: int, description: str) -> httpx2.Response:
    return httpx2.Response(status, json={"ok": False, "description": description})


def scripted(monkeypatch: pytest.MonkeyPatch, api: ScriptedBotApi) -> None:
    """Hand the command the real preflight, wired to a transport that never leaves the process.

    The factory is replaced, never the preflight itself: every structural check, every error
    mapping and the redaction filter are the production ones, and only the socket is scripted.
    """

    class Scripted(TelegramPreflight):
        @classmethod
        def from_settings(cls, settings: Settings) -> Scripted:
            return cls(
                bot_token=settings.require_telegram_bot_token(),
                timeout=1.0,
                client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)),
            )

    monkeypatch.setattr(cli, "TelegramPreflight", Scripted)


@pytest.fixture
def credentialled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A credential in the environment, with the fake provider still selected.

    Both halves matter. A preflight is what an operator runs *before* switching the transport
    on, so it has to work while ``PP_CUSTOMER_CHANNEL_PROVIDER`` is still its default.
    """
    monkeypatch.setenv("PP_TELEGRAM_BOT_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ------------------------------------------------------------------------------------ the shape


def test_channel_check_is_a_subcommand() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "channel" in result.stdout


def test_there_is_no_channel_command_that_sends_anything() -> None:
    """No command in the group may deliver. A send from a terminal is a message nobody owed.

    The group holds a preflight and a binding, and the property is the same for both: neither
    has a ``sendMessage``, neither has any text to put in one, and the module they are written
    in reaches the adapter's send path through nothing at all. Asserted over the whole group
    rather than over one name, so a third command inherits the rule instead of escaping it.
    """
    assert runner.invoke(app, ["channel", "--help"]).exit_code == 0
    assert {command.name for command in channel_app.registered_commands} == {
        "check",
        "bind-demo-customer",
    }
    imported = list(vars(cli).values())
    assert not any(value is TelegramAdapter for value in imported)
    assert not any(value is build_customer_channel for value in imported)


# ------------------------------------------------------------------------------ the credential


def test_a_check_without_a_token_names_the_variable_and_calls_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one thing an operator who has not made a bot yet needs told, and no traceback."""
    monkeypatch.delenv("PP_TELEGRAM_BOT_TOKEN", raising=False)
    api = ScriptedBotApi()
    scripted(monkeypatch, api)
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["channel", "check"])

        assert result.exit_code == 1
        assert "PP_TELEGRAM_BOT_TOKEN" in result.output
        assert api.requests == []
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------------------- getMe


def test_a_reachable_bot_is_reported_by_name(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    api = ScriptedBotApi(bot_ok())
    scripted(monkeypatch, api)

    result = runner.invoke(app, ["channel", "check"])

    assert result.exit_code == 0, result.output
    assert f"@{BOT_NAME}" in result.stdout
    assert str(BOT_ID) in result.stdout
    assert "not checked" in result.stdout
    assert api.methods == ["getMe"]


def test_a_working_credential_is_not_reported_as_a_switched_on_transport(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """The fake provider stays the default, and a green check must not imply otherwise."""
    scripted(monkeypatch, ScriptedBotApi(bot_ok()))

    result = runner.invoke(app, ["channel", "check"])

    assert result.exit_code == 0, result.output
    assert "provider: fake" in result.stdout


def test_an_answer_that_is_not_a_bot_is_refused_rather_than_reported(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """``200`` is not the question. A preflight that trusted the status code would pass here."""
    scripted(
        monkeypatch,
        ScriptedBotApi(httpx2.Response(200, json={"ok": True, "result": {"id": BOT_ID}})),
    )

    result = runner.invoke(app, ["channel", "check"])

    assert result.exit_code == 1
    assert "does not describe a bot" in result.output


def test_an_ok_false_answer_is_a_refusal_whatever_the_status_code(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    scripted(monkeypatch, ScriptedBotApi(httpx2.Response(200, json={"ok": False})))

    result = runner.invoke(app, ["channel", "check"])

    assert result.exit_code == 1
    assert "did not answer ok" in result.output


def test_a_telegram_refusal_is_reported_in_telegrams_own_words(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """A wrong token is ``401 Unauthorized``, and an operator needs to read exactly that."""
    scripted(monkeypatch, ScriptedBotApi(refusal(401, "Unauthorized")))

    result = runner.invoke(app, ["channel", "check"])

    assert result.exit_code == 1
    assert "Unauthorized" in result.output
    assert "getMe" in result.output


def test_an_unreadable_answer_is_refused_rather_than_guessed_at(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """A proxy's HTML error page is a ``200`` that means nothing about the bot."""
    scripted(monkeypatch, ScriptedBotApi(httpx2.Response(200, content=b"<html>nope</html>")))

    result = runner.invoke(app, ["channel", "check"])

    assert result.exit_code == 1
    assert "cannot read" in result.output


def test_a_transport_failure_is_reported_by_exception_type_and_never_by_message(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """An httpx error's own text carries the URL it failed on -- and that URL is the token."""
    leaky = httpx2.ConnectTimeout(f"timed out on https://api.telegram.org/bot{TOKEN}/getMe")
    scripted(monkeypatch, ScriptedBotApi(leaky))

    result = runner.invoke(app, ["channel", "check"])

    assert result.exit_code == 1
    assert "ConnectTimeout" in result.output
    assert TOKEN not in result.output
    assert "timed out on" not in result.output


# -------------------------------------------------------------------------------------- getChat


def test_a_named_chat_is_proved_reachable_with_a_second_read(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    api = ScriptedBotApi(bot_ok(), chat_ok())
    scripted(monkeypatch, api)

    result = runner.invoke(app, ["channel", "check", "--chat-id", CHAT])

    assert result.exit_code == 0, result.output
    assert "private (id not echoed)" in result.stdout
    assert api.methods == ["getMe", "getChat"]


def test_the_chat_id_is_not_echoed_back_to_the_terminal(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """The operator typed it, so echoing it tells them nothing and costs a disclosure.

    This command is run inside the deployed container over ``ssm:StartSession``, and what it
    prints lands in a session transcript and a scrollback buffer that the person on the other
    end of the chat is not party to. ``bind-demo-customer`` beside it has always refused to
    echo the id; this one did, and now both answer the question that was actually asked --
    whether the bot can reach that chat -- without naming whose chat it is.
    """
    scripted(monkeypatch, ScriptedBotApi(bot_ok(), chat_ok()))

    result = runner.invoke(app, ["channel", "check", "--chat-id", CHAT])

    assert result.exit_code == 0, result.output
    assert CHAT not in result.stdout
    assert "reachable; no message was sent" in result.stdout


def test_a_chat_the_bot_has_never_met_is_reported_as_unreachable(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """The rehearsed setup step ADR-0006 names: the customer has not pressed Start yet."""
    scripted(monkeypatch, ScriptedBotApi(bot_ok(), refusal(400, "chat not found")))

    result = runner.invoke(app, ["channel", "check", "--chat-id", CHAT])

    assert result.exit_code == 1
    assert "chat not found" in result.output


def test_an_address_that_is_not_a_chat_id_costs_no_call(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """``@username`` is reassignable, so confirming one confirms nothing about a customer."""
    api = ScriptedBotApi()
    scripted(monkeypatch, api)

    result = runner.invoke(app, ["channel", "check", "--chat-id", f"@{BOT_NAME}"])

    assert result.exit_code == 1
    assert "not a Telegram chat id" in result.output
    assert api.requests == []


def test_a_chat_id_travels_in_a_body_and_not_in_a_url(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """A query string is logged by every intermediary between here and Telegram."""
    api = ScriptedBotApi(bot_ok(), chat_ok())
    scripted(monkeypatch, api)

    runner.invoke(app, ["channel", "check", "--chat-id", CHAT])

    get_chat = api.requests[1]
    assert get_chat.url.query == b""
    assert CHAT in get_chat.content.decode()


# ----------------------------------------------------------------------------- what it may not do


def test_a_check_asks_telegram_for_nothing_but_the_two_reads(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """No ``sendMessage``, and no ``getUpdates``: it cannot deliver and it cannot read a reply."""
    api = ScriptedBotApi(bot_ok(), chat_ok())
    scripted(monkeypatch, api)

    runner.invoke(app, ["channel", "check", "--chat-id", CHAT])

    assert api.methods == ["getMe", "getChat"]
    assert not {"sendMessage", "getUpdates", "setWebhook"} & set(api.methods)


def test_a_check_prints_neither_the_token_nor_the_url_it_called(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """The Bot API takes its credential in the path, so the request URL *is* the secret."""
    api = ScriptedBotApi(bot_ok(), chat_ok())
    scripted(monkeypatch, api)

    result = runner.invoke(app, ["channel", "check", "--chat-id", CHAT])

    assert result.exit_code == 0, result.output
    assert TOKEN not in result.output
    assert "/bot" not in result.output
    assert str(api.requests[0].url) not in result.output


def test_a_provider_that_echoed_the_token_back_would_not_get_it_onto_the_terminal(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """Telegram does not do this. "It would not matter if it did" is the stronger guarantee."""
    scripted(monkeypatch, ScriptedBotApi(refusal(401, f"bad token {TOKEN}")))

    result = runner.invoke(app, ["channel", "check"])

    assert result.exit_code == 1
    assert TOKEN not in result.output
    assert "***" in result.output


def test_a_check_opens_no_database_and_asks_for_no_aws_credential(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """It reads settings and calls one provider. Anything else it touched would be a surprise."""
    import boto3

    monkeypatch.setattr(cli, "build_engine", _refuse_to_open)
    monkeypatch.setattr(cli, "RuntimeDatabase", _refuse_to_open)
    monkeypatch.setattr(boto3, "Session", _refuse_to_open)
    scripted(monkeypatch, ScriptedBotApi(bot_ok(), chat_ok()))

    result = runner.invoke(app, ["channel", "check", "--chat-id", CHAT])

    assert result.exit_code == 0, result.output


def test_the_redaction_filter_is_removed_when_the_check_is_over(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """A filter left behind would outlive the credential it was hiding."""
    import logging

    from promisepatch.integrations.telegram import TRANSPORT_LOGGERS

    before = {name: list(logging.getLogger(name).filters) for name in TRANSPORT_LOGGERS}
    scripted(monkeypatch, ScriptedBotApi(bot_ok()))

    runner.invoke(app, ["channel", "check"])

    for name in TRANSPORT_LOGGERS:
        assert logging.getLogger(name).filters == before[name]


def _refuse_to_open(*arguments: Any, **keywords: Any) -> Any:
    raise AssertionError("pp channel check reached a database or an AWS credential")
