"""``pp restore-demo-world``: what it refuses, and what it refuses *before*.

The command exists because the four-step demo repair worked on the deployed host and lived only
in a document afterwards. The interesting properties are therefore not "the four calls happen".
They are:

* **every refusal is taken before the first destructive statement.** A world that is not the demo
  fixture, a customer topology this command did not create, an effect still in flight, an
  unreachable order system and a bound destination that cannot be re-verified each leave the
  database exactly as it was. A restore that truncated and *then* discovered it could not put the
  destination back would have produced a demo world that reaches nobody, which is the failure
  ``docs/deployed-customer-channel.md`` section 9.5 records.
* **the destructive confirmation is a value, not a flag.** ``--confirm`` alone is one keystroke
  from ``--dry-run``.
* **nothing that identifies a person can leave this module.** The preserved address is absent
  from every refusal message, from the outcome, from the census and from ``repr`` -- the last one
  because an unhandled exception would otherwise publish it into a terminal and a log.

The database-backed tests here run against real PostgreSQL inside a transaction that is rolled
back, and they move a real row through the governed write path rather than around it, because
``customers`` is a governed table and a test that could write to it ungoverned would be testing
something the application cannot do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.examples import hollow_oak
from promisepatch import demo_restore
from promisepatch.config import Environment, Settings
from promisepatch.db.models import Customer, OutboxMessage
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.demo_restore import (
    CONFIRMATION,
    BindingNotRestorableError,
    Census,
    EffectsInFlightError,
    NotConfirmedError,
    PreservedBinding,
    WorldNotRestorableError,
    restore_demo_world,
)
from promisepatch.fixtures import channel_binding, demo
from promisepatch.fixtures.channel_binding import VerifiedDestination
from promisepatch.fixtures.reset import AUDIT_EVENT_TYPE, FixtureResetNotAllowedError
from promisepatch.graph.channel import split_channel

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
OPERATOR = Actor(kind="SYSTEM", id="demo-restore-tests")

CHAT = "7000000001"
OTHER_CHAT = "7000000002"
"""Synthetic destinations shaped like a chat id and belonging to nobody.

Far from the fixture's own ``1001``-``1006`` on purpose, so a test that accidentally asserted
against a fixture value fails rather than passes. A real chat id is never committed.
"""


def settings(**overrides: Any) -> Settings:
    """Settings stated in full, never inherited from the developer's environment or ``.env``.

    Every field a refusal below turns on is named explicitly, because pytest loads the
    repository's ``.env`` and a default read from there would make these tests pass or fail for
    reasons that have nothing to do with the code.
    """
    values: dict[str, Any] = {
        "env": Environment.LOCAL,
        "allow_fixture_reset": False,
        "demo_session_enabled": False,
        "order_system_base_url": None,
    }
    return Settings(**{**values, **overrides})


def destination(chat_id: str = CHAT) -> VerifiedDestination:
    """What a provider's ``getChat`` answer becomes on its way to a binding."""
    return VerifiedDestination(
        chat_id=chat_id, chat_type="private", bot_id=1, bot_username="TestBot"
    )


def verifier(answer: VerifiedDestination) -> demo_restore.DestinationVerifier:
    async def verify(address: str) -> VerifiedDestination:
        return answer

    return verify


def census(**overrides: Any) -> Census:
    """A census with the demo fixture loaded and nothing outstanding, unless a test says so."""
    values: dict[str, Any] = {
        "fixture_name": demo.FIXTURE_NAME,
        "anchor_at": NOW,
        "customers": 6,
        "cases": 0,
        "live_cases": 0,
        "outbox_total": 0,
        "outbox_unsettled": 0,
        "approval_requests": 0,
        "approval_decisions": 0,
        "plan_approvals": 0,
        "inbound_replies": 0,
        "audit_events": 10,
        "domain_events": 12,
        "demo_customer_bound": False,
    }
    return Census(**{**values, **overrides})


async def govern(connection: AsyncConnection, statement: Any) -> None:
    """Run one statement the way the application would: audited first, permitted by the trigger.

    ``customers`` is in ``GOVERNED_TABLES``, so an ungoverned ``UPDATE`` is refused by the
    database itself. Arranging a topology this command must refuse therefore has to go through
    the same door every real write does.
    """
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_EVENT_TYPE,
        actor=OPERATOR,
        authority="NONE",
        after={"operation": "demo-restore-test-arrangement"},
        occurred_at=NOW,
    ) as write:
        await write.execute(statement)


# --------------------------------------------------------- the confirmation, and what precedes


async def test_a_restore_without_the_confirmation_word_refuses_before_anything_is_read() -> None:
    """``database`` is ``None``: if the check were not first, this would raise something else."""
    with pytest.raises(NotConfirmedError) as refusal:
        await restore_demo_world(
            cast(Any, None), cycles=cast(Any, None), settings=settings(), confirmation="yes"
        )

    assert CONFIRMATION in str(refusal.value)


@pytest.mark.parametrize("typed", ["", "true", "y", "confirm", CONFIRMATION.upper()])
async def test_the_confirmation_is_a_value_rather_than_a_flag(typed: str) -> None:
    """Nothing shorter is accepted, which is what a mistyped ``--dry-run`` would produce."""
    with pytest.raises(NotConfirmedError):
        await restore_demo_world(
            cast(Any, None), cycles=cast(Any, None), settings=settings(), confirmation=typed
        )


async def test_a_deployment_that_has_not_opted_into_resets_is_refused() -> None:
    """The existing opt-in still governs: this command is a reset with three more steps."""
    with pytest.raises(FixtureResetNotAllowedError):
        await restore_demo_world(
            cast(Any, None),
            cycles=cast(Any, None),
            settings=settings(),
            confirmation=CONFIRMATION,
        )


async def test_a_deployment_that_does_not_serve_the_judge_entry_is_refused() -> None:
    """Provisioning is gated on that setting, so a restore there would leave an empty list."""
    with pytest.raises(WorldNotRestorableError) as refusal:
        await restore_demo_world(
            cast(Any, None),
            cycles=cast(Any, None),
            settings=settings(allow_fixture_reset=True),
            confirmation=CONFIRMATION,
        )

    assert "PP_DEMO_SESSION_ENABLED" in str(refusal.value)


async def test_a_deployment_with_no_order_system_is_refused_before_it_is_truncated() -> None:
    """Step 2 is not optional: a reset that skipped it spoiled run 1 of the voice measurement."""
    with pytest.raises(RuntimeError) as refusal:
        await restore_demo_world(
            cast(Any, None),
            cycles=cast(Any, None),
            settings=settings(allow_fixture_reset=True, demo_session_enabled=True),
            confirmation=CONFIRMATION,
        )

    assert "PP_ORDER_SYSTEM_BASE_URL" in str(refusal.value)


# -------------------------------------------------------------------- the world, before a step


def test_a_database_holding_no_fixture_is_refused() -> None:
    with pytest.raises(WorldNotRestorableError) as refusal:
        demo_restore._require_demo_world(census(fixture_name=None, anchor_at=None))

    assert "reset-demo-state" in str(refusal.value)


def test_a_stated_variant_of_the_demo_world_is_refused_by_name() -> None:
    """A benchmark world is installed under its own fixture name, and is not the demo."""
    with pytest.raises(WorldNotRestorableError) as refusal:
        demo_restore._require_demo_world(census(fixture_name="sur1-c04"))

    assert "sur1-c04" in str(refusal.value)
    assert demo.FIXTURE_NAME in str(refusal.value)


def test_the_canonical_fixture_is_accepted() -> None:
    demo_restore._require_demo_world(census())


@pytest.mark.parametrize("unsettled", [1, 3])
def test_an_effect_still_leaving_refuses_the_whole_sequence(unsettled: int) -> None:
    with pytest.raises(EffectsInFlightError) as refusal:
        demo_restore._require_nothing_in_flight(census(outbox_unsettled=unsettled))

    assert "PENDING or IN_FLIGHT" in str(refusal.value)


def test_effects_that_have_already_settled_do_not_refuse() -> None:
    """The repair exists *for* a world that has been used; delivered rows are history."""
    demo_restore._require_nothing_in_flight(census(outbox_total=2, outbox_unsettled=0))


def test_the_unsettled_states_are_the_schema_s_own_non_terminal_ones() -> None:
    """A state added to the outbox vocabulary must be classified rather than silently ignored."""
    from promisepatch.db.types import OUTBOX_STATES

    assert set(demo_restore.UNSETTLED_OUTBOX_STATES) < set(OUTBOX_STATES)
    assert set(OUTBOX_STATES) - set(demo_restore.UNSETTLED_OUTBOX_STATES) == {
        "DELIVERED",
        "FAILED",
    }


# ------------------------------------------------------------------- the preserved destination


async def test_no_binding_means_nothing_to_carry_and_no_verifier_is_needed() -> None:
    assert await demo_restore._reverified(None, verify=None) is None


async def test_a_binding_with_no_verifier_available_refuses_rather_than_resetting() -> None:
    """The refusal is the point: a reset here would produce a demo that reaches nobody."""
    with pytest.raises(BindingNotRestorableError) as refusal:
        await demo_restore._reverified(PreservedBinding(kind="telegram", address=CHAT), verify=None)

    assert "nothing was reset" in str(refusal.value)
    assert CHAT not in str(refusal.value)


async def test_a_binding_on_a_kind_this_cannot_verify_refuses() -> None:
    with pytest.raises(BindingNotRestorableError) as refusal:
        await demo_restore._reverified(
            PreservedBinding(kind="whatsapp", address=CHAT), verify=verifier(destination())
        )

    assert CHAT not in str(refusal.value)


async def test_a_provider_answering_about_a_different_chat_refuses() -> None:
    """The same comparison ``pp channel bind-demo-customer`` makes, for the same reason."""
    with pytest.raises(BindingNotRestorableError) as refusal:
        await demo_restore._reverified(
            PreservedBinding(kind="telegram", address=CHAT),
            verify=verifier(destination(OTHER_CHAT)),
        )

    assert CHAT not in str(refusal.value)
    assert OTHER_CHAT not in str(refusal.value)


async def test_a_failing_verifier_never_leaks_the_address_it_was_asked_about() -> None:
    """A provider's own message may name the destination, so only its type is repeated."""

    async def explode(address: str) -> VerifiedDestination:
        raise RuntimeError(f"telegram refused chat {address}")

    with pytest.raises(BindingNotRestorableError) as refusal:
        await demo_restore._reverified(
            PreservedBinding(kind="telegram", address=CHAT), verify=explode
        )

    assert CHAT not in str(refusal.value)
    assert "RuntimeError" in str(refusal.value)


async def test_a_verified_binding_is_carried() -> None:
    carried = await demo_restore._reverified(
        PreservedBinding(kind="telegram", address=CHAT), verify=verifier(destination())
    )

    assert carried is not None
    assert carried.chat_id == CHAT


def test_a_preserved_binding_redacts_its_address_in_repr() -> None:
    """A traceback anywhere between the read and the rebind would otherwise publish it."""
    held = PreservedBinding(kind="telegram", address=CHAT)

    assert CHAT not in repr(held)
    assert "<redacted>" in repr(held)
    assert "telegram" in repr(held)


# ---------------------------------------------------------------------- the fixture, as shipped


def test_the_fixture_channels_are_read_off_the_dataset_and_not_restated() -> None:
    graph = hollow_oak.hollow_oak(hollow_oak.ANCHOR)

    channels = demo_restore.fixture_channels()

    assert set(channels) == set(graph.customers)
    assert channels == {
        customer.id: split_channel(customer.approval_channel)
        for customer in graph.customers.values()
    }


def test_every_shipped_customer_is_on_the_kind_the_binding_command_writes() -> None:
    """If this ever stops holding, the topology check below would refuse a fresh seed."""
    kinds = {kind for kind, _ in demo_restore.fixture_channels().values()}

    assert kinds == {channel_binding.CHANNEL_KIND}


def test_the_canonical_customer_is_the_one_whose_recovery_waits_on_a_person() -> None:
    assert channel_binding.canonical_demo_customer_id() in demo_restore.fixture_channels()


# --------------------------------------------------------- the topology, read from real rows


@pytest.mark.integration
async def test_a_freshly_seeded_world_holds_no_binding_to_preserve(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    """The committed fixture ships placeholders, so a fresh seed carries nothing across."""
    assert await demo_restore._preserved_binding(app_conn) is None


@pytest.mark.integration
async def test_a_bound_demo_customer_is_preserved_without_being_printed(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    await govern(
        app_conn,
        update(Customer)
        .where(Customer.id == channel_binding.canonical_demo_customer_id())
        .values(approval_channel_address=CHAT),
    )

    preserved = await demo_restore._preserved_binding(app_conn)

    assert preserved == PreservedBinding(kind=channel_binding.CHANNEL_KIND, address=CHAT)
    assert CHAT not in repr(preserved)


@pytest.mark.integration
async def test_a_second_customer_pointed_somewhere_is_refused(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    """Only the fixture's own approval customer may be bound; another row is somebody else's."""
    other = next(
        customer
        for customer in sorted(demo_restore.fixture_channels())
        if customer != channel_binding.canonical_demo_customer_id()
    )
    await govern(
        app_conn,
        update(Customer).where(Customer.id == other).values(approval_channel_address=CHAT),
    )

    with pytest.raises(WorldNotRestorableError) as refusal:
        await demo_restore._preserved_binding(app_conn)

    assert other in str(refusal.value)
    assert CHAT not in str(refusal.value)


@pytest.mark.integration
async def test_a_moved_channel_kind_is_refused(app_conn: AsyncConnection, demo_state: Any) -> None:
    await govern(
        app_conn,
        update(Customer)
        .where(Customer.id == channel_binding.canonical_demo_customer_id())
        .values(approval_channel_kind="console", approval_channel_address="console-1"),
    )

    with pytest.raises(WorldNotRestorableError) as refusal:
        await demo_restore._preserved_binding(app_conn)

    assert "console" in str(refusal.value)


@pytest.mark.integration
async def test_a_customer_set_that_is_not_the_fixtures_is_refused(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    """One extra row is enough: this restores the fixture's own topology and nothing wider."""
    await govern(
        app_conn,
        insert(Customer).values(
            id="cus-somebody-else",
            name="Somebody Else",
            approval_channel_kind=channel_binding.CHANNEL_KIND,
            approval_channel_address="9999",
        ),
    )

    with pytest.raises(WorldNotRestorableError) as refusal:
        await demo_restore._preserved_binding(app_conn)

    assert "customer set" in str(refusal.value)


@pytest.mark.integration
async def test_the_census_counts_without_naming_anybody(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    taken = await demo_restore.take_census(app_conn)

    assert taken.fixture_name == demo.FIXTURE_NAME
    assert taken.customers == len(demo_restore.fixture_channels())
    assert taken.demo_customer_bound is False
    assert taken.audit_events > 0
    assert CHAT not in repr(taken)


@pytest.mark.integration
async def test_the_census_reports_a_binding_as_a_boolean_and_never_as_a_value(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    await govern(
        app_conn,
        update(Customer)
        .where(Customer.id == channel_binding.canonical_demo_customer_id())
        .values(approval_channel_address=CHAT),
    )

    taken = await demo_restore.take_census(app_conn)

    assert taken.demo_customer_bound is True
    assert CHAT not in repr(taken)


@pytest.mark.integration
async def test_the_census_counts_unsettled_effects_apart_from_settled_ones(
    app_conn: AsyncConnection, demo_state: Any
) -> None:
    """The distinction the refusal rests on, read from the state column the schema checks."""
    total = int(
        (await app_conn.execute(select(func.count()).select_from(OutboxMessage))).scalar_one()
    )

    taken = await demo_restore.take_census(app_conn)

    assert taken.outbox_total == total
    assert taken.outbox_unsettled <= taken.outbox_total
