"""``pp restore-demo-world``: the proven destructive demo repair, sequenced once and guarded.

``docs/demo-fixture-anchoring.md`` wrote the repair down as four operator steps, and
``docs/deployed-customer-channel.md`` section 10 records it being taken on the deployed host --
reseed, reset the External Order System, provision the canonical case, bind the demo customer.
It worked, and the two things that made it dangerous were not the individual steps:

* **the order is load-bearing and lives only in a document.** The reset truncates ``customers``,
  so a binding taken before it is silently erased; ``docs/deployed-customer-channel.md`` section
  9.5 records that as the ordering fact, and an operator who remembers three of the four steps
  gets a demo that reaches nobody.
* **the External Order System keeps its own store.** A PromisePatch reset does not reach it, so
  skipping step 2 leaves an order book carrying every amendment the destroyed cases made,
  against a mirror that has just been rebuilt at version 1. Run 1 of the voice measurement was
  spoiled by exactly that.

This module is that sequence, once, with the preconditions asked of rows before anything is
destroyed. **It is demo and rehearsal tooling.** It is not a general reset: there is no argument
that names a fixture, a customer, a case or a table, and every refusal below exists because the
thing it refuses is a state this sequence did not create and cannot reason about.

**What it is not, stated as plainly as what it is.**

* It **never authorises anything**. It confirms no plan, creates no approval request and no
  approval decision, records no consent, and sends no customer message. The case it leaves
  behind is ``PLANNED``: the point at which a person has yet to say yes.
* It **weakens no existing guard**. ``promisepatch.provisioning``'s ``_what_would_be_lost`` and
  the world roll are untouched and unreachable from here -- a world this has just reseeded tells
  the story by construction, so provisioning finds nothing to roll.
* It **preserves the ledgers of record**. The truncation is
  :func:`promisepatch.fixtures.reset.reset_demo_state`'s, whose set is ``resettable_tables()`` --
  every table minus ``audit_events`` and ``domain_events`` -- and both are refused truncation by
  trigger regardless. The census below reads them before and after so a caller can say they grew.
* It **touches no volume and no infrastructure**. Nothing here runs Docker, and the order book is
  reset through the simulator's own HTTP admin route rather than by removing its volume --
  ``docker compose down -v`` would take ``caddy-data`` and the Let's Encrypt certificate with it.
* It **moves no clock by hand**. The anchor is
  :func:`promisepatch.fixtures.demo.resolve_demo_anchor` applied to ``now``, which is what an
  operator omitting ``--anchor`` already gets.
* It **prints no identifier that belongs to a person**. A preserved chat id is held in memory for
  the length of one call, is re-applied through the existing binding command's own service, and
  has a ``__repr__`` that redacts it so a traceback cannot publish it either. See ADR-0021.

**The binding is preserved by carrying it, not by storing it.** The address is read out of the
``customers`` row before the truncate and written back after provisioning through
:func:`promisepatch.fixtures.channel_binding.bind_demo_customer_channel` -- the one binding
mechanism there is. Nothing is persisted anywhere new, no file is written, and a run that cannot
re-verify the destination refuses **before** anything is destroyed rather than leaving a world
that reaches nobody.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

import httpx2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.examples import hollow_oak
from promisepatch import provisioning
from promisepatch.config import Settings
from promisepatch.db import RuntimeDatabase, build_engine
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    Case,
    Customer,
    DomainEvent,
    FixtureState,
    InboundReply,
    OutboxMessage,
    PlanApproval,
)
from promisepatch.db.uow import Actor
from promisepatch.domain.model import TERMINAL_CASE_STATES
from promisepatch.fixtures import channel_binding, demo
from promisepatch.fixtures.reset import (
    FIXTURE_STATE_ID,
    ResetOutcome,
    ensure_reset_allowed,
    reset_demo_state,
)
from promisepatch.graph.channel import split_channel
from promisepatch.observability import get_logger

logger = get_logger(__name__)

CONFIRMATION: Final = "destroy-and-restore"
"""The word an operator has to type. A flag alone is too easy to reach for by habit.

Deliberately a value rather than a boolean: ``--confirm`` with nothing after it is one keystroke
away from ``--dry-run``, and the thing on the other side of this is a ``TRUNCATE`` that takes
every case on the deployment with it.
"""

ACTOR: Final = Actor(kind="SYSTEM", id="pp restore-demo-world")
"""Who the audit rows name. An operator asked for a known world back; nothing else authorised it."""

UNSETTLED_OUTBOX_STATES: Final = ("PENDING", "IN_FLIGHT")
"""An effect that has not finished leaving. Truncating under one is the failure this refuses.

A ``DELIVERED`` or ``FAILED`` row is history: the effect has happened, the ledgers record it, and
the repair exists precisely for a world that has been used. A ``PENDING`` or ``IN_FLIGHT`` row is
work a dispatcher is about to do or is doing right now, and the world it would act against is
about to stop existing.
"""

ORDER_RESET_PATH: Final = "/admin/reset"
ORDER_HEALTH_PATH: Final = "/healthz"
"""The simulator's own routes. Read first, so an unreachable order system refuses nothing lost."""


class RestoreRefusedError(RuntimeError):
    """A restore that will not be attempted, for a reason an operator can act on.

    Every subclass is raised **before** the first destructive statement, which is what makes
    "fail closed" a property of the sequence rather than of the order somebody wrote it in.
    """


class NotConfirmedError(RestoreRefusedError):
    """The destructive confirmation was absent or did not match."""


class WorldNotRestorableError(RestoreRefusedError):
    """This database is not a canonical demo world, so there is no canonical world to restore."""


class EffectsInFlightError(RestoreRefusedError):
    """An effect is queued or leaving. Nothing may be truncated under it."""


class OrderSystemUnreachableError(RestoreRefusedError):
    """The External Order System could not be reached, so step 2 could not be relied on."""


class BindingNotRestorableError(RestoreRefusedError):
    """A destination is bound and could not be re-verified, so the reset was not taken."""


class Restored(StrEnum):
    """What a run did, in one word an operator and a test can both read."""

    RESTORED = "restored"

    INSPECTED = "inspected"
    """``--dry-run``: every precondition asked, nothing written."""


class BindingAction(StrEnum):
    """What happened to the demo customer's destination across the restore."""

    NONE_HELD = "none-held"
    """The row carried the committed fixture's own placeholder. There was nothing to preserve."""

    RESTORED = "restored"
    """A bound destination was carried across the truncate and written back."""


@dataclass(frozen=True, slots=True, repr=False)
class PreservedBinding:
    """One customer's real destination, held in memory for the length of one restore.

    ``repr`` is overridden rather than inherited, and that is defensive rather than decorative:
    an unhandled exception anywhere between the read and the rebind would otherwise print the
    address into a terminal, a log and -- on the deployed host -- a Session Manager transcript.
    ADR-0021 is why that matters more than it looks.
    """

    kind: str
    address: str

    def __repr__(self) -> str:
        return f"PreservedBinding(kind={self.kind!r}, address=<redacted>)"


@dataclass(frozen=True, slots=True)
class Census:
    """What the database holds, in the counts a before/after proof is made of.

    No address, no chat id, no token and no link: the two channel facts here are *how many*
    customers there are and *whether* the canonical one is bound to something other than the
    committed placeholder.
    """

    fixture_name: str | None
    anchor_at: datetime | None
    customers: int
    cases: int
    live_cases: int
    outbox_total: int
    outbox_unsettled: int
    approval_requests: int
    approval_decisions: int
    plan_approvals: int
    inbound_replies: int
    audit_events: int
    domain_events: int
    demo_customer_bound: bool


@dataclass(frozen=True, slots=True)
class RestoreOutcome:
    """What a restore did, in terms an operator reading a log and a test can both check."""

    action: Restored
    before: Census
    after: Census | None
    anchor: datetime | None
    digest: str | None
    rows_written: int
    orders_reset: int
    provisioned: provisioning.ProvisionOutcome | None
    binding: BindingAction

    @property
    def ledgers_only_grew(self) -> bool:
        """Both ledgers of record came out at least as long as they went in.

        The claim the reset's own docstring makes, checked against rows rather than trusted.
        """
        if self.after is None:
            return True
        return (
            self.after.audit_events >= self.before.audit_events
            and self.after.domain_events >= self.before.domain_events
        )


DestinationVerifier = Callable[[str], Awaitable[channel_binding.VerifiedDestination]]
"""Ask the provider to confirm one address, and answer with what it echoed back.

Injected rather than imported, for the reason :class:`promisepatch.provisioning.Cycles` is: this
module sits below :mod:`promisepatch.integrations` in the layering contract, so it *cannot* reach
a Bot API client, and the one that verifies is the CLI's own -- the same two calls
``pp channel bind-demo-customer`` makes, in the process that would send.
"""


def fixture_channels() -> Mapping[str, tuple[str, str]]:
    """Every customer the committed fixture ships, with the channel it ships them with.

    Read off the dataset rather than listed, for this package's standing reason: a list here
    would be a second copy of six rows that live in a file in this repository, and a second copy
    eventually disagrees with the first.
    """
    graph = hollow_oak.hollow_oak(hollow_oak.ANCHOR)
    return {
        customer.id: split_channel(customer.approval_channel)
        for customer in graph.customers.values()
    }


async def take_census(connection: AsyncConnection) -> Census:
    """Count what is here. Reads only, and nothing that identifies a person."""
    state = (
        (
            await connection.execute(
                select(FixtureState.fixture_name, FixtureState.anchor_at).where(
                    FixtureState.id == FIXTURE_STATE_ID
                )
            )
        )
        .mappings()
        .first()
    )
    return Census(
        fixture_name=None if state is None else str(state["fixture_name"]),
        anchor_at=None if state is None else state["anchor_at"],
        customers=await _count(connection, Customer),
        cases=await _count(connection, Case),
        live_cases=await _count(connection, Case, Case.state.not_in(sorted(TERMINAL_CASE_STATES))),
        outbox_total=await _count(connection, OutboxMessage),
        outbox_unsettled=await _count(
            connection, OutboxMessage, OutboxMessage.state.in_(UNSETTLED_OUTBOX_STATES)
        ),
        approval_requests=await _count(connection, ApprovalRequest),
        approval_decisions=await _count(connection, ApprovalDecision),
        plan_approvals=await _count(connection, PlanApproval),
        inbound_replies=await _count(connection, InboundReply),
        audit_events=await _count(connection, AuditEvent),
        domain_events=await _count(connection, DomainEvent),
        demo_customer_bound=await _demo_customer_bound(connection),
    )


async def restore_demo_world(
    database: RuntimeDatabase,
    *,
    cycles: provisioning.Cycles,
    settings: Settings,
    confirmation: str = "",
    verify: DestinationVerifier | None = None,
    order_client: httpx2.AsyncClient | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> RestoreOutcome:
    """Put the canonical demo world back, in the order that was proved on the deployed host.

    Everything that can refuse, refuses first. By the time the first ``TRUNCATE`` runs, the
    fixture has been named, the customer topology has been checked row by row, no effect is in
    flight, the External Order System has answered a probe, and any bound destination has already
    been re-verified -- so the failure modes left are the ones no amount of reading can foresee.

    A second run is **outcome-idempotent**: it destroys the world this one left, reseeds at a
    fresh anchor and provisions the same canonical partition again. It is not a no-op, and it is
    not corrupting either -- the case it removes is the case it opened.
    """
    moment = now or datetime.now(UTC)
    if not dry_run and confirmation != CONFIRMATION:
        raise NotConfirmedError(
            "this destroys every case, effect and session on this deployment; pass "
            f"--confirm {CONFIRMATION} to say so."
        )
    ensure_reset_allowed(settings)
    if not settings.demo_session_enabled:
        raise WorldNotRestorableError(
            "this deployment does not serve the judge entry, so provisioning would open no case "
            "and a restore would leave an empty list; set PP_DEMO_SESSION_ENABLED=true."
        )
    base_url = settings.require_order_system_base_url()

    async with database.connect() as connection:
        before = await take_census(connection)
        _require_demo_world(before)
        preserved = await _preserved_binding(connection)
    _require_nothing_in_flight(before)
    await _require_order_system(
        base_url, timeout=settings.order_system_timeout_seconds, client=order_client
    )
    destination = await _reverified(preserved, verify=verify)

    if dry_run:
        return RestoreOutcome(
            action=Restored.INSPECTED,
            before=before,
            after=None,
            anchor=None,
            digest=None,
            rows_written=0,
            orders_reset=0,
            provisioned=None,
            binding=BindingAction.NONE_HELD if destination is None else BindingAction.RESTORED,
        )

    # 1. The operational world, reloaded at an anchor the fixture can be driven from.
    anchor = demo.resolve_demo_anchor(moment, settings.bakery_tz)
    reset = await _reseed(settings, anchor=anchor, now=moment)

    # 2. The External Order System, which keeps its own store and is not reached by step 1.
    orders = await _reset_order_book(
        base_url, timeout=settings.order_system_timeout_seconds, client=order_client
    )

    # 3. The canonical case, through provisioning's own path. Nothing is written directly.
    provisioned = await provisioning.ensure_demo_case(database, cycles=cycles, settings=settings)

    # 4. The destination, written back through the one command that may write one.
    binding = BindingAction.NONE_HELD
    if destination is not None:
        async with database.begin() as connection:
            await channel_binding.bind_demo_customer_channel(
                connection, destination=destination, now=datetime.now(UTC), actor=ACTOR
            )
        binding = BindingAction.RESTORED

    async with database.connect() as connection:
        after = await take_census(connection)

    logger.info(
        "demo_restore.completed",
        anchor=anchor.isoformat(),
        rows_written=reset.rows_written,
        orders_reset=orders,
        provisioning=provisioned.action.value,
        case_state=provisioned.state,
        binding=binding.value,
        cases_destroyed=before.cases,
    )
    return RestoreOutcome(
        action=Restored.RESTORED,
        before=before,
        after=after,
        anchor=anchor,
        digest=reset.digest,
        rows_written=reset.rows_written,
        orders_reset=orders,
        provisioned=provisioned,
        binding=binding,
    )


# ------------------------------------------------------------------- what is refused, and why


def _require_demo_world(census: Census) -> None:
    """Refuse a database that is not holding the canonical demo fixture, by its recorded name.

    The same check :mod:`promisepatch.fixtures.channel_binding` makes and for the same reason: a
    stated variant of the demo world installed under its own fixture name is not the demo world,
    and "is this the disposable demo database" is not something a process can infer from its own
    hostname.
    """
    if census.fixture_name is None:
        raise WorldNotRestorableError(
            "this database holds no fixture, so there is no demo world to restore; "
            "seed it with `pp reset-demo-state` first."
        )
    if census.fixture_name != demo.FIXTURE_NAME:
        raise WorldNotRestorableError(
            f"this database holds the {census.fixture_name!r} fixture rather than "
            f"{demo.FIXTURE_NAME!r}; only the demo world is restored by this command."
        )


def _require_nothing_in_flight(census: Census) -> None:
    """Refuse while an effect is queued or leaving."""
    if census.outbox_unsettled:
        raise EffectsInFlightError(
            f"{census.outbox_unsettled} operational effect(s) are PENDING or IN_FLIGHT; nothing "
            "may be truncated under work a dispatcher is about to do. Stop the worker, let the "
            "outbox settle, and run this again."
        )


async def _preserved_binding(connection: AsyncConnection) -> PreservedBinding | None:
    """The demo customer's real destination, or ``None`` -- refusing any other topology.

    Every customer is compared against the committed fixture. Five of the six must carry exactly
    the channel the dataset ships them with; the canonical one may carry that or one other
    address of the same kind, which is what a binding looks like and the only difference this
    command knows how to put back. Anything else -- a missing customer, an extra one, a moved
    kind, a second customer somebody pointed at a phone -- is a world this did not create, and
    restoring it would be this command deciding on somebody else's behalf what their edit meant.
    """
    rows = (
        (
            await connection.execute(
                select(
                    Customer.id,
                    Customer.approval_channel_kind,
                    Customer.approval_channel_address,
                ).order_by(Customer.id)
            )
        )
        .mappings()
        .all()
    )
    expected = fixture_channels()
    found = {str(row["id"]) for row in rows}
    if found != set(expected):
        raise WorldNotRestorableError(
            "the customer set is not the demo fixture's: "
            f"{len(found - set(expected))} unexpected and {len(set(expected) - found)} missing."
        )

    canonical = channel_binding.canonical_demo_customer_id()
    preserved: PreservedBinding | None = None
    for row in rows:
        customer_id = str(row["id"])
        kind, address = str(row["approval_channel_kind"]), str(row["approval_channel_address"])
        wanted_kind, wanted_address = expected[customer_id]
        if kind != wanted_kind:
            raise WorldNotRestorableError(
                f"customer {customer_id!r} carries a {kind!r} channel where the fixture ships "
                f"{wanted_kind!r}; this command restores the fixture's own topology only."
            )
        if address == wanted_address:
            continue
        if customer_id != canonical:
            raise WorldNotRestorableError(
                f"customer {customer_id!r} carries a destination this command did not write; "
                "only the demo fixture's approval customer may be bound, and a binding on any "
                "other row is somebody else's."
            )
        preserved = PreservedBinding(kind=kind, address=address)
    return preserved


async def _reverified(
    preserved: PreservedBinding | None, *, verify: DestinationVerifier | None
) -> channel_binding.VerifiedDestination | None:
    """Confirm a preserved destination before anything is destroyed, or refuse having destroyed
    nothing.

    Re-verification rather than trust, for the reason
    :class:`promisepatch.fixtures.channel_binding.VerifiedDestination` exists at all: the value
    that reaches the rebind has to be one the provider echoed back, not one this process read out
    of a column and believed. Running it *first* is what makes the refusal free -- a restore that
    reseeded and then discovered it could not put the destination back would have produced a demo
    world that reaches nobody, which is the exact failure section 9.5 records.

    No refusal here carries the address, or the provider's own message about it, which may.
    """
    if preserved is None:
        return None
    if preserved.kind != channel_binding.CHANNEL_KIND:
        raise BindingNotRestorableError(
            f"the demo customer is bound to a {preserved.kind!r} destination, and only "
            f"{channel_binding.CHANNEL_KIND!r} bindings can be re-verified; nothing was reset."
        )
    if verify is None:
        raise BindingNotRestorableError(
            "the demo customer holds a bound destination and no channel verifier is available "
            "here, so it could not be carried across a reset; nothing was reset. Run this where "
            "the channel preflight can reach the provider."
        )
    try:
        destination = await verify(preserved.address)
    except Exception as error:
        raise BindingNotRestorableError(
            f"the bound destination could not be re-verified ({type(error).__name__}); "
            "nothing was reset."
        ) from error
    if destination.chat_id != preserved.address:
        raise BindingNotRestorableError(
            "the provider answered about a different chat than the bound one; nothing was reset."
        )
    return destination


async def _require_order_system(
    base_url: str, *, timeout: float, client: httpx2.AsyncClient | None = None
) -> None:
    """Read the simulator's liveness before anything is destroyed.

    Step 2 is not optional and cannot be deferred: an order book still carrying the destroyed
    cases' amendments, against a mirror rebuilt at version 1, is the state that spoiled run 1 of
    the voice measurement. So an order system that cannot be reached refuses the whole sequence
    here, where refusing costs nothing.
    """
    try:
        async with _http(client, timeout=timeout) as http:
            response = await http.get(f"{base_url}{ORDER_HEALTH_PATH}")
    except httpx2.HTTPError as error:
        raise OrderSystemUnreachableError(
            f"the external order system could not be reached ({type(error).__name__}); its "
            "order book cannot be reset, so nothing was reset here either."
        ) from error
    if response.status_code != 200:
        raise OrderSystemUnreachableError(
            f"the external order system answered {response.status_code} to a liveness read; "
            "nothing was reset."
        )


# ------------------------------------------------------------------------------ the four steps


async def _reseed(settings: Settings, *, anchor: datetime, now: datetime) -> ResetOutcome:
    """Step 1, through the reset's own service: one connection, one audited transaction.

    The migration role, because truncation is the one thing the runtime role deliberately cannot
    do. No reset logic is reproduced here -- what this adds is the engine and the two demo
    passwords, which is wiring rather than behaviour.
    """
    passwords = {
        demo.BAKER_ROLE: settings.require_demo_worker_password(),
        demo.OWNER_ROLE: settings.require_demo_owner_password(),
    }
    engine = build_engine(settings.require_migration_database_url(), pool_size=1)
    try:
        async with engine.begin() as connection:
            return await reset_demo_state(
                connection, anchor=anchor, now=now, passwords=passwords, actor=ACTOR
            )
    finally:
        await engine.dispose()


async def _reset_order_book(
    base_url: str, *, timeout: float, client: httpx2.AsyncClient | None = None
) -> int:
    """Step 2: the External Order System's own admin route, and never a volume.

    ``docker compose down -v`` would empty the order system's store and take ``caddy-data`` --
    the Let's Encrypt certificate and account key -- with it, forcing a re-issue against Let's
    Encrypt's rate limits for a demo that is about to be watched.
    """
    try:
        async with _http(client, timeout=timeout) as http:
            response = await http.post(f"{base_url}{ORDER_RESET_PATH}")
    except httpx2.HTTPError as error:
        raise OrderSystemUnreachableError(
            f"the external order system could not be reset ({type(error).__name__}); "
            "PromisePatch has been reseeded, so run this again once it is reachable."
        ) from error
    if response.status_code != 200:
        raise OrderSystemUnreachableError(
            f"the external order system answered {response.status_code} to a reset; "
            "PromisePatch has been reseeded, so run this again."
        )
    body: Any = response.json()
    return int(body.get("orders", 0)) if isinstance(body, dict) else 0


@asynccontextmanager
async def _http(
    client: httpx2.AsyncClient | None, *, timeout: float
) -> AsyncIterator[httpx2.AsyncClient]:
    """The caller's HTTP client, or one owned for the length of a single call.

    The seam exists for the same reason ``cycles`` and ``verify`` do, and for one more: the
    backend suite runs the real External Order System as a second ASGI application in its own
    process, so a test that could not hand this module that client would have to be skipped
    wherever no simulator is listening on a socket -- which is every CI job. A caller's client
    is used and left open; an owned one is closed however the call ends.
    """
    if client is not None:
        yield client
        return
    async with httpx2.AsyncClient(timeout=timeout) as owned:
        yield owned


# ------------------------------------------------------------------------------------- reading


async def _count(connection: AsyncConnection, model: Any, *where: Any) -> int:
    statement = select(func.count()).select_from(model)
    for clause in where:
        statement = statement.where(clause)
    return int(await connection.scalar(statement) or 0)


async def _demo_customer_bound(connection: AsyncConnection) -> bool:
    """Whether the canonical customer holds something other than the committed placeholder.

    A boolean, never a value, for the reason ``pp channel bind-demo-customer`` prints the kind of
    chat and not the chat.
    """
    address = await connection.scalar(
        select(Customer.approval_channel_address).where(
            Customer.id == channel_binding.canonical_demo_customer_id()
        )
    )
    return address is not None and str(address) not in channel_binding.fixture_addresses()
