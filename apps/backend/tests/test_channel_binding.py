"""``pp channel bind-demo-customer``: the one row it may move, and everything it refuses.

The committed fixture gives every customer a made-up ``tg:100N`` destination, which is correct
and is also the last thing between this repository and a live customer message:
``docs/customer-message-transport.md`` records that *nothing proves a real chat id reaches the
adapter*. This is the operator action that closes it, and the properties under test are not
"the UPDATE is shaped right". They are:

* **nothing is written before Telegram has confirmed the destination** -- a malformed id, a
  missing credential and a ``getChat`` refusal each leave the database untouched, and the first
  two never open a socket at all;
* **exactly one customer can move** -- the row is derived from the fixture, there is no
  argument that could name another, and the other five are asserted unchanged;
* **a state this command did not write is never overwritten** -- a second operator's binding is
  refused rather than replaced, and a database that is not holding the demo fixture is refused
  before the customer is even looked for;
* **a repeat writes nothing at all** -- no ``UPDATE``, no audit row, no event, because a
  command run twice did not change the world twice;
* **the destination reaches no ledger, no log line and no terminal** -- it identifies a real
  person, and the only place it is any use is the row it addresses;
* **consent is untouched** -- a binding mints no approval request, no decision and no
  authority; it says where a later proposal would be sent, never that anybody agreed to one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection
from test_channel_check import BOT_ID, BOT_NAME, ScriptedBotApi, bot_ok, chat_ok, refusal, scripted
from typer.testing import CliRunner

from promisepatch import cli
from promisepatch.cli import app, channel_app
from promisepatch.config import get_settings
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    Customer,
    DomainEvent,
    FixtureState,
)
from promisepatch.db.uow import Actor
from promisepatch.fixtures import channel_binding
from promisepatch.fixtures.channel_binding import (
    BindingOutcome,
    Bound,
    DemoCustomerMissingError,
    UnexpectedBindingStateError,
    VerifiedDestination,
    WorldNotTheDemoError,
    bind_demo_customer_channel,
    canonical_demo_customer_id,
    fixture_addresses,
)
from promisepatch.fixtures.reset import FIXTURE_STATE_ID
from promisepatch.integrations import telegram

runner = CliRunner()

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
OPERATOR = Actor(kind="SYSTEM", id="channel-binding-tests")

CHAT = 7000000001
OTHER_CHAT = 7000000002
"""Synthetic destinations, shaped like a chat id and belonging to nobody.

A real one is never committed -- it identifies a person -- so these are what the scripted Bot
API answers with. Deliberately far from the fixture's own ``1001``-``1006``, so a test that
accidentally asserted against a fixture value would fail rather than pass.
"""


def destination(chat_id: int = CHAT, chat_type: str = "private") -> VerifiedDestination:
    """What a ``getChat`` answer becomes on its way to the binding."""
    return VerifiedDestination(
        chat_id=str(chat_id), chat_type=chat_type, bot_id=BOT_ID, bot_username=BOT_NAME
    )


@pytest.fixture
def credentialled(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A credential in the environment, with the fake provider still selected.

    Both halves matter here for the reason they matter to the preflight: binding a destination
    is something an operator does *before* switching the transport on, and a command that
    demanded the transport already be live could only confirm a decision already made.
    """
    monkeypatch.setenv("PP_TELEGRAM_BOT_TOKEN", "7654321:PLACEHOLDER-not-a-real-bot-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def never_binds(monkeypatch: pytest.MonkeyPatch) -> list[VerifiedDestination]:
    """Record every binding the command reaches, so "nothing was written" can be asserted.

    The database runner is replaced rather than the database, because the claim under test is
    that the command does not *get that far* -- a test that let it open a connection and then
    checked the rows would pass just as well against a command that verified nothing and found
    the row unchanged by luck.
    """
    reached: list[VerifiedDestination] = []

    async def record(settings: Any, verified: VerifiedDestination) -> BindingOutcome:
        reached.append(verified)
        return BindingOutcome(
            action=Bound.BOUND,
            customer_id=canonical_demo_customer_id(),
            channel_kind=channel_binding.CHANNEL_KIND,
            chat_type=verified.chat_type,
            bot_username=verified.bot_username,
            audit_seq=1,
            domain_event_seq=1,
        )

    monkeypatch.setattr(cli, "_run_bind_demo_customer", record)
    return reached


# ------------------------------------------------------------------------------------- the shape


def test_the_binding_names_the_same_channel_kind_as_the_adapter() -> None:
    """Two words that must be one word.

    The fixtures package may not import :mod:`promisepatch.integrations` -- the layering
    contract puts integrations above it -- so the kind is stated in both places. Stated twice
    and asserted equal is honest; stated twice and hoped equal is how a customer's message is
    delivered to a chat id that is really somebody's WhatsApp number.
    """
    assert channel_binding.CHANNEL_KIND == telegram.CHANNEL_KIND


def test_the_binding_is_a_channel_subcommand() -> None:
    assert {command.name for command in channel_app.registered_commands} == {
        "check",
        "bind-demo-customer",
    }


def test_the_canonical_customer_is_read_off_the_fixture_and_takes_no_argument() -> None:
    """There is no customer option, so there is no customer but the one the fixture names."""
    result = runner.invoke(app, ["channel", "bind-demo-customer", "--help"])

    assert result.exit_code == 0
    assert "--customer" not in result.output
    assert canonical_demo_customer_id() in {"cus-tomas"}


def test_a_verified_destination_cannot_be_built_from_a_username() -> None:
    """The type refuses what ADR-0006 refuses, whatever built it.

    Not a second copy of the Bot API's address grammar -- that lives in ``telegram.CHAT_ID`` and
    is applied before anything reaches here. This is the invariant that makes the type mean
    something: a value that is not the decimal rendering of an integer did not come back from a
    ``getChat``, and a username is reassignable.
    """
    with pytest.raises(UnexpectedBindingStateError):
        VerifiedDestination(
            chat_id="@promisepatch_demo_bot", chat_type="private", bot_id=BOT_ID, bot_username="b"
        )


# -------------------------------------------------------------- nothing moves before a check


def test_a_username_is_refused_before_telegram_is_called(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    api = ScriptedBotApi()
    scripted(monkeypatch, api)
    reached = never_binds(monkeypatch)

    result = runner.invoke(
        app, ["channel", "bind-demo-customer", "--chat-id", "@promisepatch_demo_bot"]
    )

    assert result.exit_code == 1
    assert api.requests == []
    assert reached == []


def test_a_binding_without_a_credential_names_the_variable_and_binds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PP_TELEGRAM_BOT_TOKEN", raising=False)
    api = ScriptedBotApi()
    scripted(monkeypatch, api)
    reached = never_binds(monkeypatch)
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["channel", "bind-demo-customer", "--chat-id", str(CHAT)])

        assert result.exit_code == 1
        assert "PP_TELEGRAM_BOT_TOKEN" in result.output
        assert api.requests == []
        assert reached == []
    finally:
        get_settings.cache_clear()


def test_a_destination_telegram_will_not_confirm_binds_nothing(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """What an operator sees before the customer has ever pressed Start on the bot."""
    api = ScriptedBotApi(bot_ok(), refusal(400, "Bad Request: chat not found"))
    scripted(monkeypatch, api)
    reached = never_binds(monkeypatch)

    result = runner.invoke(app, ["channel", "bind-demo-customer", "--chat-id", str(CHAT)])

    assert result.exit_code == 1
    assert api.methods == ["getMe", "getChat"]
    assert reached == []
    assert "not verified" in result.output


def test_a_credential_that_is_not_a_bot_binds_nothing(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """``200`` is not the question here either, and a refusal is not a binding."""
    api = ScriptedBotApi(refusal(401, "Unauthorized"))
    scripted(monkeypatch, api)
    reached = never_binds(monkeypatch)

    result = runner.invoke(app, ["channel", "bind-demo-customer", "--chat-id", str(CHAT)])

    assert result.exit_code == 1
    assert reached == []


def test_a_confirmed_destination_is_what_reaches_the_binding(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """The id stored is the one the Bot API echoed back, carrying the bot that proved it."""
    api = ScriptedBotApi(bot_ok(), chat_ok(chat_id=CHAT))
    scripted(monkeypatch, api)
    reached = never_binds(monkeypatch)

    result = runner.invoke(app, ["channel", "bind-demo-customer", "--chat-id", str(CHAT)])

    assert result.exit_code == 0, result.output
    assert api.methods == ["getMe", "getChat"]
    assert reached == [destination()]


# ------------------------------------------------------------------ what a terminal may learn


def test_the_report_never_echoes_the_destination(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """An operator who typed a chat id does not need it read back into their scrollback.

    ``pp channel check`` prints it, and that is the right call for a command whose whole answer
    is *about* the destination. A binding's answer is about a row, and a customer's identifier
    in a terminal is a customer's identifier in a buffer somebody later pastes.
    """
    api = ScriptedBotApi(bot_ok(), chat_ok(chat_id=CHAT))
    scripted(monkeypatch, api)
    never_binds(monkeypatch)

    result = runner.invoke(app, ["channel", "bind-demo-customer", "--chat-id", str(CHAT)])

    assert result.exit_code == 0, result.output
    assert str(CHAT) not in result.output
    assert "private" in result.output
    assert "no message was sent" in result.output


def test_the_report_never_echoes_the_credential(
    monkeypatch: pytest.MonkeyPatch, credentialled: None
) -> None:
    """The Bot API takes its token in the request path, so the URL called *is* the secret."""
    api = ScriptedBotApi(bot_ok(), chat_ok(chat_id=CHAT))
    scripted(monkeypatch, api)
    never_binds(monkeypatch)

    result = runner.invoke(app, ["channel", "bind-demo-customer", "--chat-id", str(CHAT)])

    assert "PLACEHOLDER-not-a-real-bot-token" not in result.output
    assert "api.telegram.org/bot" not in result.output


# ------------------------------------------------------------------------------- the one row


@pytest.mark.integration
async def test_only_the_canonical_demo_customer_moves(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    before = await _channels(app_conn)

    outcome = await bind_demo_customer_channel(
        app_conn, destination=destination(), now=NOW, actor=OPERATOR
    )

    after = await _channels(app_conn)
    moved = {key for key in after if after[key] != before.get(key)}
    assert moved == {outcome.customer_id}
    assert after[outcome.customer_id] == (channel_binding.CHANNEL_KIND, str(CHAT))
    assert outcome.action is Bound.BOUND


@pytest.mark.integration
async def test_the_bound_row_is_the_destination_the_engine_will_read_back(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    """Stored split, read back joined: what an approval request is addressed with."""
    await bind_demo_customer_channel(app_conn, destination=destination(), now=NOW, actor=OPERATOR)

    kind, address = (await _channels(app_conn))[canonical_demo_customer_id()]
    assert kind == telegram.CHANNEL_KIND
    assert telegram.CHAT_ID.match(address)
    assert address == str(CHAT)


@pytest.mark.integration
async def test_rebinding_the_same_destination_writes_nothing(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    """A command run twice did not change the world twice, and the ledger says so."""
    await bind_demo_customer_channel(app_conn, destination=destination(), now=NOW, actor=OPERATOR)
    audits = await _count(app_conn, AuditEvent)
    events = await _count(app_conn, DomainEvent)

    outcome = await bind_demo_customer_channel(
        app_conn, destination=destination(), now=NOW, actor=OPERATOR
    )

    assert outcome.action is Bound.ALREADY_BOUND
    assert outcome.audit_seq is None
    assert outcome.domain_event_seq is None
    assert await _count(app_conn, AuditEvent) == audits
    assert await _count(app_conn, DomainEvent) == events


@pytest.mark.integration
async def test_a_destination_this_command_did_not_write_is_refused(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    """A second operator's phone is not overwritten, and the refusal names no address."""
    await bind_demo_customer_channel(app_conn, destination=destination(), now=NOW, actor=OPERATOR)

    with pytest.raises(UnexpectedBindingStateError) as refused:
        await bind_demo_customer_channel(
            app_conn, destination=destination(OTHER_CHAT), now=NOW, actor=OPERATOR
        )

    assert str(CHAT) not in str(refused.value)
    assert str(OTHER_CHAT) not in str(refused.value)
    assert (await _channels(app_conn))[canonical_demo_customer_id()][1] == str(CHAT)


@pytest.mark.integration
async def test_a_world_that_is_not_the_demo_fixture_is_refused(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    """A ``SUR-1`` world records ``hollow-oak+sur1-<scenario>`` and has no demo customer."""
    before = await _channels(app_conn)
    await app_conn.execute(
        update(FixtureState)
        .where(FixtureState.id == FIXTURE_STATE_ID)
        .values(fixture_name="hollow-oak+sur1-C01")
    )

    with pytest.raises(WorldNotTheDemoError):
        await bind_demo_customer_channel(
            app_conn, destination=destination(), now=NOW, actor=OPERATOR
        )

    assert await _channels(app_conn) == before


@pytest.mark.integration
async def test_a_demo_customer_that_is_not_here_is_refused(
    app_conn: AsyncConnection, demo_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails closed on a world that names a customer this database does not hold."""
    monkeypatch.setattr(channel_binding, "canonical_demo_customer_id", lambda: "cus-nobody")
    before = await _channels(app_conn)

    with pytest.raises(DemoCustomerMissingError):
        await bind_demo_customer_channel(
            app_conn, destination=destination(), now=NOW, actor=OPERATOR
        )

    assert await _channels(app_conn) == before


@pytest.mark.integration
async def test_a_failure_after_the_audit_event_leaves_no_trace(
    app_conn: AsyncConnection, demo_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit row and domain write share one transaction and one fate.

    The event append is the last thing the binding does, so failing it is the only way to be
    *past* the audit row and the ``UPDATE`` and still fail. Both must go with it: an audit
    event explaining a change that did not happen is worse than no record at all.
    """

    async def explode(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("the spine refused")

    monkeypatch.setattr(channel_binding, "append_event", explode)
    before = await _channels(app_conn)
    audits = await _count(app_conn, AuditEvent)

    # The savepoint is released explicitly rather than by a context manager: `pytest.raises`
    # catches the failure, so an `async with` block would see a clean exit and *release* the
    # savepoint -- keeping the very write this test exists to prove is discarded.
    savepoint = await app_conn.begin_nested()
    with pytest.raises(RuntimeError, match="the spine refused"):
        await bind_demo_customer_channel(
            app_conn, destination=destination(), now=NOW, actor=OPERATOR
        )
    await savepoint.rollback()

    assert await _channels(app_conn) == before
    assert await _count(app_conn, AuditEvent) == audits


# --------------------------------------------------------------------------- what is recorded


@pytest.mark.integration
async def test_the_ledger_records_the_binding_and_never_the_destination(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    """A chat id identifies a real person, and ``audit_events`` is exported evidence.

    The fixture's own address is written down, because ``tg:1002`` sits in a committed file and
    is nobody's phone; what replaced it is not. No digest stands in for it either -- a ten-digit
    number has ten billion candidates, so a digest would be theatre rather than protection.
    """
    outcome = await bind_demo_customer_channel(
        app_conn, destination=destination(), now=NOW, actor=OPERATOR
    )

    row = (
        (
            await app_conn.execute(
                select(
                    AuditEvent.type, AuditEvent.authority, AuditEvent.before, AuditEvent.after
                ).where(AuditEvent.seq == outcome.audit_seq)
            )
        )
        .mappings()
        .one()
    )
    payload = (
        await app_conn.execute(
            select(DomainEvent.payload).where(DomainEvent.seq == outcome.domain_event_seq)
        )
    ).scalar_one()

    assert row["type"] == "FIXTURE_LOAD"
    assert row["authority"] == "NONE"
    assert row["before"]["address"] in fixture_addresses()
    assert row["after"]["address"] == channel_binding.REDACTED
    assert str(CHAT) not in str(row["before"]) + str(row["after"]) + str(payload)


@pytest.mark.integration
async def test_a_binding_creates_no_approval_and_no_consent(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    """Saying where a proposal would be sent is not proposing one, and never agreeing to one."""
    requests = await _count(app_conn, ApprovalRequest)
    decisions = await _count(app_conn, ApprovalDecision)

    await bind_demo_customer_channel(app_conn, destination=destination(), now=NOW, actor=OPERATOR)

    assert await _count(app_conn, ApprovalRequest) == requests
    assert await _count(app_conn, ApprovalDecision) == decisions


async def _channels(connection: AsyncConnection) -> dict[str, tuple[str, str]]:
    """Every customer's approval channel, so "exactly one moved" is a whole-table assertion."""
    rows = await connection.execute(
        select(Customer.id, Customer.approval_channel_kind, Customer.approval_channel_address)
    )
    return {row.id: (row.approval_channel_kind, row.approval_channel_address) for row in rows}


async def _count(connection: AsyncConnection, model: Any) -> int:
    return int(await connection.scalar(select(func.count()).select_from(model)) or 0)
