"""Point the seeded demo customer at one real Telegram chat, and nothing else at anything.

The shipped fixture gives every customer a made-up destination -- ``tg:1001`` through
``tg:1006`` -- because a committed dataset must not carry a real person's identifier. That is
right, and it is also the last thing standing between this repository and the claim
``docs/customer-message-transport.md`` says it cannot yet make: *nothing proves a real chat id
reaches the adapter*. The preflight is told a destination by an operator; no approval request
has ever carried one.

This closes exactly that gap and nothing wider. It is a fixture edit, not a customer editor,
and the list of what it refuses is the design:

* **One customer, derived rather than named.** The row it may touch is the customer who owns
  :data:`~promise_graph.examples.hollow_oak.ORDER_B` -- the seeded case's one
  ``APPROVAL_REQUIRED`` band, the single promise in the demo whose recovery waits on a person.
  Reading the id off the fixture rather than typing it here means a dataset that renamed that
  customer moves this with it, and that no second customer can be reached by changing an
  argument, because there is no argument to change.
* **One world.** ``fixture_state`` must say this database holds the demo fixture by name, and
  nothing else will do. A *variant* of the demo world -- a stated graph installed under its own
  fixture name, which :func:`promisepatch.fixtures.reset.reset_demo_state` takes an argument
  for -- is refused by the same check, as is a database that has never been seeded at all. "Is
  this the disposable demo database" is not something a process can infer from its own
  hostname, and guessing wrong writes a stranger's chat id into somebody else's row.
* **One prior state.** The row must carry either the fixture's own committed destination or,
  already, exactly the destination being bound. A row holding some *other* address is a state
  this command did not create and cannot reason about -- perhaps a second operator bound a
  second phone -- so it is refused rather than overwritten. ``pp reset-demo-state`` puts the
  fixture value back, and that is the way round to it.
* **One destination, and only one Telegram itself confirmed.** :class:`VerifiedDestination`
  cannot be built from an operator's typing: it carries the id ``getChat`` echoed back, which
  is :meth:`~promisepatch.integrations.telegram.TelegramPreflight.locate`'s rendering of an
  integer the Bot API returned. A username never reaches this module, because a username is
  never what comes back.

**It cannot send.** There is no transport here and no message to put in one. This package may
not import :mod:`promisepatch.integrations` at all -- the layering contract in
``pyproject.toml`` puts integrations above fixtures -- so an adapter is not merely absent, it
is unreachable. The verification happens in the CLI, before a transaction is open, and what
crosses into this module is its result.

**The destination never enters a ledger.** The audit row says that the demo customer's
Telegram address was replaced and by whom; it does not say what it was replaced with. A chat id
identifies a real person, ``audit_events`` is the table G8 exports curated evidence out of, and
a digest would be theatre rather than protection -- a ten-digit number has ten billion
candidates, which is a second of work. The fixture's own committed addresses *are* recorded,
because those are public data sitting in a file in this repository. The real one lives in the
``customers`` row it was written to, which is the only place it is any use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.examples import hollow_oak
from promisepatch.db.events import append_event
from promisepatch.db.models import Customer, FixtureState
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.fixtures import demo
from promisepatch.fixtures.reset import AUDIT_EVENT_TYPE, FIXTURE_STATE_ID, LOCK_KEY
from promisepatch.graph.channel import split_channel
from promisepatch.observability import get_logger

logger = get_logger(__name__)

CHANNEL_KIND: Final = "telegram"
"""The one kind a binding may write, stated in the vocabulary the schema's CHECK is built from.

Deliberately not taken from :mod:`promisepatch.integrations.telegram`, which this package may
not import. It is the same word, and ``test_channel_binding`` asserts the two agree rather than
trusting that they do.
"""

DOMAIN_EVENT_TYPE: Final = "fixture.demo_customer_channel_bound"
"""One customer's approval destination moved. Nothing else about the world changed."""

OPERATION: Final = "bind-demo-customer"
"""Distinguishes this row from a reload or a roll in the shared ``FIXTURE_LOAD`` vocabulary.

The same audit event type as both, for the reason :data:`promisepatch.fixtures.reanchor.OPERATION`
gives: all three are the demo fixture being put where an operator wants it, all three are
authorised by nothing but that wish, and an operator reading the ledger for *what happened to
the demo world* should find them under one name.
"""

REDACTED: Final = "<redacted>"
"""What the ledger records in place of a destination that belongs to a real person."""

_ADVISORY_LOCK = text("SELECT pg_advisory_xact_lock(:key)")
"""The reset's own lock, so a binding and an operator's reload can never interleave."""


class BindingRefusedError(RuntimeError):
    """A binding that will not be attempted, for a reason an operator can act on."""


class WorldNotTheDemoError(BindingRefusedError):
    """This database does not hold the demo fixture, so it has no demo customer to bind."""


class DemoCustomerMissingError(BindingRefusedError):
    """The demo fixture's canonical customer is not in this database."""


class UnexpectedBindingStateError(BindingRefusedError):
    """The row carries a destination this command did not write and will not overwrite."""


class Bound(StrEnum):
    """What a binding did, in one word an operator and a test can both read."""

    BOUND = "bound"
    ALREADY_BOUND = "already-bound"


@dataclass(frozen=True, slots=True)
class VerifiedDestination:
    """A chat the Bot API has just confirmed this bot may speak to. The only thing a bind takes.

    Built from a ``getChat`` answer rather than from an argument, which is what makes "verified
    before mutation" a property of the type rather than of the order somebody wrote two calls
    in. ``chat_id`` is
    :func:`promisepatch.integrations.telegram._chat_identity`'s rendering of an integer the API
    returned -- so a username, which is what an operator might have typed and what this module
    must never store, cannot be one of these.

    ``bot_id`` and ``bot_username`` are carried for the audit row: which bot was proved able to
    reach the destination is the part of this that is safe to write down.
    """

    chat_id: str
    chat_type: str
    bot_id: int
    bot_username: str

    def __post_init__(self) -> None:
        # Not a second copy of the Bot API's address grammar -- that lives in
        # `promisepatch.integrations.telegram.CHAT_ID` and is applied twice before anything
        # reaches here. This is the type invariant: a destination that is not the decimal
        # rendering of an integer did not come from a `getChat` answer, whatever built it.
        if str(_as_int(self.chat_id)) != self.chat_id:
            raise UnexpectedBindingStateError(
                "a verified destination is a numeric Telegram chat id as the Bot API returned it"
            )
        if not self.chat_type.strip():
            raise UnexpectedBindingStateError("a verified destination carries the kind of chat")
        if not self.bot_username.strip():
            raise UnexpectedBindingStateError("a verified destination names the bot that reached")


@dataclass(frozen=True, slots=True)
class BindingOutcome:
    """What happened, in terms an operator reading a log and a test can both check.

    There is no address on it, for the reason there is none in the ledger. A caller that needs
    to know which destination is bound reads the ``customers`` row.
    """

    action: Bound
    customer_id: str
    channel_kind: str
    chat_type: str
    bot_username: str
    audit_seq: int | None
    domain_event_seq: int | None

    @property
    def changed(self) -> bool:
        return self.action is Bound.BOUND


def canonical_demo_customer_id() -> str:
    """The one customer a binding may touch, read off the fixture rather than typed.

    The owner of :data:`~promise_graph.examples.hollow_oak.ORDER_B`: the seeded case's single
    ``APPROVAL_REQUIRED`` band, and therefore the only promise in the demo whose recovery is
    waiting on a person to answer on a phone. ``docs/seeded-demo-case.md`` asserts that band
    against this same order.
    """
    return hollow_oak.hollow_oak(hollow_oak.ANCHOR).orders[hollow_oak.ORDER_B].customer_id


def fixture_addresses() -> frozenset[str]:
    """Every destination the committed fixture ships, which are the ones safe to write down.

    Derived from the dataset for the reason every other value in this package is: a list here
    would be a second copy of six strings that live in a file in this repository, and a second
    copy eventually disagrees with the first.
    """
    return frozenset(
        split_channel(customer.approval_channel)[1]
        for customer in hollow_oak.hollow_oak(hollow_oak.ANCHOR).customers.values()
    )


async def bind_demo_customer_channel(
    connection: AsyncConnection,
    *,
    destination: VerifiedDestination,
    now: datetime,
    actor: Actor,
) -> BindingOutcome:
    """Bind the canonical demo customer to ``destination``, or refuse and change nothing.

    The caller owns the transaction, exactly as a reset's and a roll's do, so the decision to
    commit belongs to whoever asked for it. Every refusal below is raised before the governed
    block opens, so a refused binding leaves no audit row claiming an attempt that was never
    made -- and any failure after it rolls the audit row back with the write it authorised,
    because they are one transaction and share one fate.

    Rebinding to the identical destination is a no-op that writes nothing at all: no ``UPDATE``,
    no audit row, no event. That is the truthful record. A command run twice did not change the
    world twice, and a ledger that said it had would be the wrong kind of careful.
    """
    await connection.execute(_ADVISORY_LOCK, {"key": LOCK_KEY})

    await _require_demo_world(connection)
    customer_id = canonical_demo_customer_id()
    current = await _locked_customer(connection, customer_id)
    _require_bindable(current, destination)

    if current.kind == CHANNEL_KIND and current.address == destination.chat_id:
        logger.info(
            "demo customer channel already bound",
            customer_id=customer_id,
            channel_kind=CHANNEL_KIND,
            bot_username=destination.bot_username,
        )
        return BindingOutcome(
            action=Bound.ALREADY_BOUND,
            customer_id=customer_id,
            channel_kind=current.kind,
            chat_type=destination.chat_type,
            bot_username=destination.bot_username,
            audit_seq=None,
            domain_event_seq=None,
        )

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_EVENT_TYPE,
        actor=actor,
        # No policy and no consent permitted this, and no customer approved it: an operator
        # pointed the demo at a phone they hold. Recording that honestly is better than
        # dressing it up as an authority it does not have -- and binding a destination is not
        # consent, which arrives later, literally, on the customer's own surface.
        authority="NONE",
        before={
            "operation": OPERATION,
            "customer": customer_id,
            "channel_kind": current.kind,
            "address": _writable(current.address),
        },
        after={
            "operation": OPERATION,
            "fixture": demo.FIXTURE_NAME,
            "customer": customer_id,
            "channel_kind": CHANNEL_KIND,
            "address": REDACTED,
            "chat_type": destination.chat_type,
            "bot_id": destination.bot_id,
            "bot_username": destination.bot_username,
        },
        occurred_at=now,
    ) as write:
        result = await write.execute(
            update(Customer)
            .where(Customer.id == customer_id)
            .values(
                approval_channel_kind=CHANNEL_KIND,
                approval_channel_address=destination.chat_id,
            )
        )
        if int(result.rowcount or 0) != 1:
            # Unreachable through the read above, which held the row. Raised rather than
            # trusted, because the whole point of this module is that exactly one row moves:
            # raising here rolls back the audit event along with whatever did.
            raise UnexpectedBindingStateError(
                f"binding matched {result.rowcount} customer rows; exactly one was expected"
            )

        # Last, and after every row lock this transaction needs: appending an event takes the
        # spine's ordering lock and holds it to commit, so nothing may queue behind it here.
        domain_event_seq = await append_event(
            write.connection,
            event_type=DOMAIN_EVENT_TYPE,
            correlation_id=write.correlation_id,
            occurred_at=now,
            entity_refs=({"kind": "customer", "id": customer_id},),
            payload={
                "operation": OPERATION,
                "fixture": demo.FIXTURE_NAME,
                "customer": customer_id,
                "channel_kind": CHANNEL_KIND,
                "address": REDACTED,
            },
        )

        logger.info(
            "demo customer channel bound",
            customer_id=customer_id,
            channel_kind=CHANNEL_KIND,
            bot_username=destination.bot_username,
            audit_seq=write.audit_seq,
        )
        return BindingOutcome(
            action=Bound.BOUND,
            customer_id=customer_id,
            channel_kind=CHANNEL_KIND,
            chat_type=destination.chat_type,
            bot_username=destination.bot_username,
            audit_seq=write.audit_seq,
            domain_event_seq=int(domain_event_seq),
        )


@dataclass(frozen=True, slots=True)
class _CurrentChannel:
    """The two columns a binding reads, and the row it read them under lock from."""

    kind: str
    address: str


async def _require_demo_world(connection: AsyncConnection) -> None:
    """Refuse every database that is not holding the demo fixture, by its recorded name."""
    loaded = await connection.scalar(
        select(FixtureState.fixture_name).where(FixtureState.id == FIXTURE_STATE_ID)
    )
    if loaded is None:
        raise WorldNotTheDemoError(
            "this database holds no fixture, so it has no demo customer to bind; "
            "seed it with `pp reset-demo-state` first."
        )
    if loaded != demo.FIXTURE_NAME:
        raise WorldNotTheDemoError(
            f"this database holds the {loaded!r} fixture rather than {demo.FIXTURE_NAME!r}; "
            "only the demo world has a demo customer, and nothing else will be written to."
        )


async def _locked_customer(connection: AsyncConnection, customer_id: str) -> _CurrentChannel:
    """The canonical customer's channel, with the row held until this transaction ends."""
    row = (
        (
            await connection.execute(
                select(Customer.approval_channel_kind, Customer.approval_channel_address)
                .where(Customer.id == customer_id)
                .with_for_update()
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise DemoCustomerMissingError(
            f"the demo fixture's customer {customer_id!r} is not in this database; "
            "seed it with `pp reset-demo-state` first."
        )
    return _CurrentChannel(
        kind=row["approval_channel_kind"], address=row["approval_channel_address"]
    )


def _require_bindable(current: _CurrentChannel, destination: VerifiedDestination) -> None:
    """Refuse a row this command did not put in the state it is in.

    Two states are bindable and no third is: the fixture's own committed destination, and the
    destination being bound. Anything else was written by somebody else -- a second operator, a
    second phone, a hand-edited row -- and overwriting it would be this command deciding on
    their behalf that their binding did not matter. The refusal names no address, because the
    address it would name is the one that is not ours to print.
    """
    if current.kind == CHANNEL_KIND and current.address == destination.chat_id:
        return
    if current.kind == CHANNEL_KIND and current.address in fixture_addresses():
        return
    raise UnexpectedBindingStateError(
        f"the demo customer is already bound to a {current.kind!r} destination this command "
        "did not write; `pp reset-demo-state` restores the fixture's own, and a binding will "
        "not overwrite somebody else's."
    )


def _writable(address: str) -> str:
    """The address itself when the fixture ships it, and :data:`REDACTED` when a person holds it.

    ``tg:1002`` is in a committed file and is nobody's phone; writing it into the ledger tells
    an operator reading the history exactly what the binding replaced. A real chat id is a real
    person's identifier and is never written anywhere but the row it addresses.
    """
    return address if address in fixture_addresses() else REDACTED


def _as_int(value: str) -> int:
    """``int(value)`` with a refusal in this module's vocabulary rather than a ``ValueError``."""
    try:
        return int(value)
    except ValueError:
        raise UnexpectedBindingStateError(
            "a verified destination is a numeric Telegram chat id as the Bot API returned it"
        ) from None
