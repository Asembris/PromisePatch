"""``pp restore-demo-world``, end to end: a used world in, the canonical story out.

The arrangement is the point. Every test below that restores does so from a world the *roll*
can never move again: a case was opened, a plan was confirmed, an approval was asked for and
effects were dispatched, so ``provisioning._what_would_be_lost`` answers ``REFUSED`` for ever --
which ``docs/demo-world-roll.md`` states as a permanent, monotone property and this suite does
not weaken. The destructive repair is the documented way out of exactly that state, and what is
asserted here is that it produces the canonical partition and mints no authority on the way.

The bands are read back through ``GET /api/cases/{id}`` as the observer session the judge entry
mints -- the screen, not the row -- for the reason ``test_demo_world_roll`` gives: the decay this
tooling exists to repair does not empty a case, it fills it with four blocked promises, which
looks like a working product right up until somebody asks what the system decided by itself.

The External Order System is the real simulator, its own ASGI application over its own SQLite
file, reached over the client seam ``restore_demo_world`` takes. That is what lets step 2 be
exercised rather than stubbed in a CI job where nothing is listening on a socket.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from _database_safety import migration_database_url, runtime_database_url
from _intake_support import Intake
from _intake_support import physical as physical
from _order_system_support import (
    PROMISEPATCH_ORIGIN,
    SIMULATOR_ORIGIN,
    WEBHOOK_PATH,
    WEBHOOK_SECRET,
)
from pydantic import SecretStr
from sqlalchemy import select, update
from test_demo_restore import CHAT, destination, govern, verifier
from typer.testing import CliRunner

from order_simulator.app import create_app as create_simulator
from order_simulator.config import Settings as SimulatorSettings
from promise_graph.examples import hollow_oak as ho
from promisepatch import cli as cli_module
from promisepatch import demo_restore
from promisepatch.api.routers import auth as login_router
from promisepatch.api.schemas.cases import CaseWorkspaceResponse
from promisepatch.cli import app as cli_app
from promisepatch.config import Settings
from promisepatch.db.models import Customer, FixtureState
from promisepatch.demo_restore import (
    CONFIRMATION,
    BindingAction,
    BindingNotRestorableError,
    Census,
    EffectsInFlightError,
    PreservedBinding,
    Restored,
    RestoreOutcome,
    WorldNotRestorableError,
)
from promisepatch.domain.adapters import FakeEffectAdapter
from promisepatch.domain.cases import CASE_PLANNED
from promisepatch.domain.model import DeliveryOutcome, DeliveryStatus
from promisepatch.domain.physical import bakery_day
from promisepatch.fixtures import channel_binding
from promisepatch.fixtures.reset import FIXTURE_STATE_ID
from promisepatch.main import create_app as create_promisepatch
from promisepatch.provisioning import Provisioned

runner = CliRunner()

CANONICAL_BANDS = {
    "AUTO_RECOVERABLE": (ho.PROMISE_A,),
    "APPROVAL_REQUIRED": (ho.PROMISE_B,),
    "BLOCKED": (ho.PROMISE_C, ho.PROMISE_D),
}
"""The heterogeneous-authority story, by classification. Untouched is asserted separately."""

CANONICAL_ORDERS = {
    ho.PROMISE_A: "EXT-A",
    ho.PROMISE_B: "EXT-B",
    ho.PROMISE_C: "EXT-C",
    ho.PROMISE_D: "EXT-D",
}
"""Which external order each band belongs to, because a band with the wrong order proves nothing."""


@pytest.fixture
def serving(runtime_settings: Settings) -> Settings:
    """A deployment that offers the judge entry, on connections the suite is allowed to destroy.

    Both URLs are resolved through ``_database_safety`` rather than read off ``Settings``. A
    restore truncates, and ``test_database_safety`` asserts that no module in this suite which
    can truncate resolves a connection string for itself.
    """
    return runtime_settings.model_copy(
        update={
            "demo_session_enabled": True,
            "migration_database_url": SecretStr(migration_database_url(runtime_settings)),
            "database_url": SecretStr(runtime_database_url(runtime_settings)),
        }
    )


@pytest.fixture
def restoring(serving: Settings) -> Settings:
    """The same deployment, pointed at the order system this test is running."""
    return serving.model_copy(update={"order_system_base_url": SIMULATOR_ORIGIN})


@asynccontextmanager
async def order_system(sqlite_path: Path) -> AsyncIterator[httpx2.AsyncClient]:
    """The real External Order System, in this process, over its own store.

    ``deliver=False`` because nothing here wants a webhook: a restore empties the order book and
    the mirror in the same breath, and a delivery attempt would only be an outbound call to an
    application that is not running.
    """
    settings = SimulatorSettings(
        database_path=sqlite_path,
        webhook_url=f"{PROMISEPATCH_ORIGIN}{WEBHOOK_PATH}",
        webhook_secret=SecretStr(WEBHOOK_SECRET),
        log_level="warning",
    )
    app = create_simulator(settings, deliver=False)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as client,
    ):
        yield client


@pytest_asyncio.fixture
async def orders(tmp_path: Path) -> AsyncIterator[httpx2.AsyncClient]:
    async with order_system(tmp_path / "orders.db") as client:
        yield client


async def a_used_world(physical: Intake) -> None:
    """A world nobody may roll again: a confirmed plan, an approval asked for, effects out.

    Driven through the ordinary path -- the canonical sentence, the canonical answer, a worker's
    yes on an authenticated channel, and worker cycles -- rather than by writing rows, because a
    hand-built arrangement would prove the restore works on states the product cannot reach.
    """
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    await physical.drain(limit=40)


async def restore(
    physical: Intake, settings: Settings, orders: httpx2.AsyncClient, **kwargs: Any
) -> RestoreOutcome:
    return await demo_restore.restore_demo_world(
        physical.database,
        cycles=physical.worker(),
        settings=settings,
        confirmation=CONFIRMATION,
        order_client=orders,
        **kwargs,
    )


@asynccontextmanager
async def judge(settings: Settings) -> AsyncIterator[httpx2.AsyncClient]:
    """One press of *Look around a real case*: an observer session, and nothing more.

    Minted after the restore, never before: a reset truncates ``sessions``, so a session taken
    earlier would be signed out by the very thing under test -- which is also what the fourth
    documented step tells an operator.
    """
    origin = settings.cors_origins.split(",")[0].strip()
    app = create_promisepatch(settings)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=origin) as client,
    ):
        login_router._limiter.reset()
        response = await client.post("/api/auth/demo-session", headers={"Origin": origin})
        assert response.status_code == 200, response.text
        client.headers["Origin"] = origin
        yield client


async def workspace(client: httpx2.AsyncClient, case_id: Any) -> CaseWorkspaceResponse:
    response = await client.get(f"/api/cases/{case_id}")
    assert response.status_code == 200, response.text
    return CaseWorkspaceResponse.model_validate(response.json())


def bands_of(view: CaseWorkspaceResponse) -> dict[str, tuple[str, ...]]:
    """Every threatened promise, grouped by the classification the screen drew it under."""
    grouped: dict[str, list[str]] = {}
    for band in view.authority_bands:
        for promise in band.promises:
            grouped.setdefault(str(promise.classification), []).append(promise.promise_id)
    return {key: tuple(sorted(value)) for key, value in sorted(grouped.items())}


def orders_of(view: CaseWorkspaceResponse) -> dict[str, str]:
    return {
        promise.promise_id: promise.order_external_id
        for band in view.authority_bands
        for promise in band.promises
    }


async def anchor_of(physical: Intake) -> datetime:
    return await physical.fixture_anchor()


async def bound_address(physical: Intake) -> str:
    """Read only inside an assertion, never printed: the value is the point of the test."""
    async with physical.database.connect() as connection:
        return str(
            await connection.scalar(
                select(Customer.approval_channel_address).where(
                    Customer.id == channel_binding.canonical_demo_customer_id()
                )
            )
        )


async def order_versions(orders: httpx2.AsyncClient) -> dict[str, int]:
    response = await orders.get(f"{SIMULATOR_ORIGIN}/orders")
    assert response.status_code == 200, response.text
    return {order["external_id"]: order["version"] for order in response.json()["orders"]}


# ----------------------------------------------------------- the world, rebuilt from a used one


@pytest.mark.integration
async def test_a_used_world_is_rebuilt_and_every_authority_counter_returns_to_zero(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    """The arrangement is a world the roll refuses for ever; the restore is the way out."""
    await a_used_world(physical)

    outcome = await restore(physical, restoring, orders)

    assert outcome.action is Restored.RESTORED
    before, after = outcome.before, outcome.after
    assert after is not None
    assert before.cases >= 1
    assert before.outbox_total > 0, "the arrangement dispatched no effect; it proves nothing"
    assert before.approval_requests == 1
    assert before.plan_approvals == 1

    assert after.cases == 1
    assert after.outbox_total == 0
    assert after.approval_requests == 0
    assert after.approval_decisions == 0
    assert after.plan_approvals == 0
    assert after.inbound_replies == 0


@pytest.mark.integration
async def test_the_restore_reaches_the_canonical_planned_case(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    await a_used_world(physical)

    outcome = await restore(physical, restoring, orders)

    assert outcome.provisioned is not None
    assert outcome.provisioned.action is Provisioned.OPENED
    assert outcome.provisioned.state == CASE_PLANNED
    assert outcome.provisioned.rolled is False, "a freshly seeded world has nothing to roll"
    assert outcome.binding is BindingAction.NONE_HELD


@pytest.mark.integration
async def test_the_rebuilt_case_tells_the_heterogeneous_authority_story(
    physical: Intake, restoring: Settings, serving: Settings, orders: httpx2.AsyncClient
) -> None:
    """Read from the judge's own screen: four bands, two untouched, zero effects."""
    await a_used_world(physical)

    outcome = await restore(physical, restoring, orders)
    assert outcome.provisioned is not None

    async with judge(serving) as client:
        view = await workspace(client, outcome.provisioned.case_id)

    assert bands_of(view) == CANONICAL_BANDS
    assert orders_of(view) == CANONICAL_ORDERS
    assert tuple(sorted(promise.promise_id for promise in view.untouched)) == (
        ho.PROMISE_E,
        ho.PROMISE_F,
    )
    assert {promise.order_external_id for promise in view.untouched} == {"EXT-E", "EXT-F"}
    assert view.untouched_count == 2
    assert view.untouched_effect_count == 0


@pytest.mark.integration
async def test_the_promise_that_waits_on_a_person_carries_exactly_one_option(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    """``pr-b`` is the whole reason a customer is ever asked.

    Two options would be a different product and none would be a blocked promise.
    """
    await a_used_world(physical)

    outcome = await restore(physical, restoring, orders)
    case_id = outcome.provisioned.case_id if outcome.provisioned else None
    assert case_id is not None
    track = await physical.track(case_id, ho.PROMISE_B)

    assert len(await physical.options(track.id)) == 1


@pytest.mark.integration
async def test_the_owner_blocked_promises_carry_no_option_at_all(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    await a_used_world(physical)

    outcome = await restore(physical, restoring, orders)
    case_id = outcome.provisioned.case_id if outcome.provisioned else None
    assert case_id is not None

    for promise_id in (ho.PROMISE_C, ho.PROMISE_D):
        track = await physical.track(case_id, promise_id)
        assert await physical.options(track.id) == []


@pytest.mark.integration
async def test_the_ledgers_of_record_only_grow_across_a_restore(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    """The reset truncates everything it owns; these two are outside its set and refuse it."""
    await a_used_world(physical)

    outcome = await restore(physical, restoring, orders)

    assert outcome.after is not None
    assert outcome.after.audit_events > outcome.before.audit_events
    assert outcome.after.domain_events > outcome.before.domain_events
    assert outcome.ledgers_only_grew


@pytest.mark.integration
async def test_the_restored_world_is_anchored_to_today(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    """Exactly one raspberry-bearing delivery in today's bakery day is the whole fixture claim."""
    await a_used_world(physical)

    outcome = await restore(physical, restoring, orders)

    assert outcome.anchor is not None
    assert outcome.after is not None
    assert outcome.after.anchor_at == outcome.anchor
    start, end = bakery_day(datetime.now(UTC))
    assert start <= outcome.anchor < end


@pytest.mark.integration
async def test_the_external_order_system_is_reset_beside_the_mirror(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    """Step 2, which a PromisePatch reset does not reach and an operator forgets.

    An order edited in the order system's own screen carries a version the freshly rebuilt
    mirror does not -- which is the state ``docs/demo-fixture-anchoring.md`` records spoiling
    run 1 of the voice measurement. The restore has to put that back too.
    """
    await a_used_world(physical)
    line = (await orders.get(f"{SIMULATOR_ORIGIN}/orders/EXT-D")).json()["lines"][0]
    edited = await orders.post(
        f"{SIMULATOR_ORIGIN}/ui/orders/EXT-D/lines/{line['external_line_id']}",
        data={"to_item_id": line["external_item_id"], "quantity": "7"},
        follow_redirects=False,
    )
    assert edited.status_code == 303, edited.text
    assert (await order_versions(orders))["EXT-D"] > 1

    outcome = await restore(physical, restoring, orders)

    versions = await order_versions(orders)
    assert outcome.orders_reset == len(versions)
    assert set(versions.values()) == {1}


@pytest.mark.integration
async def test_a_second_restore_rebuilds_the_same_partition_rather_than_corrupting_one(
    physical: Intake, restoring: Settings, serving: Settings, orders: httpx2.AsyncClient
) -> None:
    """Outcome-idempotent: the case it destroys the second time is the case it opened the first."""
    await a_used_world(physical)
    first = await restore(physical, restoring, orders)

    second = await restore(physical, restoring, orders)

    assert second.action is Restored.RESTORED
    assert second.before.cases == 1
    assert second.after is not None
    assert second.after.cases == 1
    assert second.provisioned is not None
    assert second.provisioned.state == CASE_PLANNED
    async with judge(serving) as client:
        assert bands_of(await workspace(client, second.provisioned.case_id)) == CANONICAL_BANDS
    assert first.after is not None
    assert second.after.audit_events > first.after.audit_events


# -------------------------------------------------------------------- what it refuses, live


@pytest.mark.integration
async def test_a_restore_refuses_while_an_effect_is_still_leaving(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    """A confirmed plan whose provider is down: the rows are queued and nothing has left.

    Arranged with a provider that answers ``RETRYABLE`` rather than by writing a state into a
    row, because ``PENDING`` with a time on it is exactly what the dispatcher's own retry
    ladder produces -- and it is the state in which a truncation would destroy the world an
    effect is about to be sent against.
    """
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    stalled = FakeEffectAdapter(
        fail_with=DeliveryOutcome(status=DeliveryStatus.RETRYABLE, error="the provider is down")
    )
    await physical.drain(worker=physical.worker(adapter=stalled), limit=40)
    assert stalled.attempts, "no effect was ever attempted; the arrangement proves nothing"
    assert stalled.effect_count == 0, "an effect was delivered; nothing is in flight"
    before = await anchor_of(physical)

    with pytest.raises(EffectsInFlightError):
        await restore(physical, restoring, orders)

    assert await anchor_of(physical) == before, "a refused restore moved the world"


@pytest.mark.integration
async def test_a_restore_refuses_a_world_that_is_not_the_demo_fixture(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    async with physical.database.begin() as connection:
        await connection.execute(
            update(FixtureState)
            .where(FixtureState.id == FIXTURE_STATE_ID)
            .values(fixture_name="hollow-oak+variant-01")
        )
    before = await anchor_of(physical)

    with pytest.raises(WorldNotRestorableError):
        await restore(physical, restoring, orders)

    assert await anchor_of(physical) == before


@pytest.mark.integration
async def test_a_binding_that_cannot_be_reverified_destroys_nothing(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    """The ordering fact, asserted: a reset would erase a destination it could not put back."""
    async with physical.database.begin() as connection:
        await govern(
            connection,
            update(Customer)
            .where(Customer.id == channel_binding.canonical_demo_customer_id())
            .values(approval_channel_address=CHAT),
        )
    before = await anchor_of(physical)

    with pytest.raises(BindingNotRestorableError):
        await restore(physical, restoring, orders, verify=None)

    assert await anchor_of(physical) == before
    assert await bound_address(physical) == CHAT


@pytest.mark.integration
async def test_a_verified_binding_is_carried_across_the_truncate(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    """The one thing the documented steps get wrong by hand: reseed, then bind, then propose."""
    async with physical.database.begin() as connection:
        await govern(
            connection,
            update(Customer)
            .where(Customer.id == channel_binding.canonical_demo_customer_id())
            .values(approval_channel_address=CHAT),
        )

    outcome = await restore(physical, restoring, orders, verify=verifier(destination()))

    assert outcome.binding is BindingAction.RESTORED
    assert outcome.after is not None
    assert outcome.after.demo_customer_bound is True
    assert await bound_address(physical) == CHAT
    assert outcome.after.outbox_total == 0, "restoring a destination sent something"


@pytest.mark.integration
async def test_restoring_a_destination_writes_no_approval_and_no_message(
    physical: Intake, restoring: Settings, orders: httpx2.AsyncClient
) -> None:
    """A binding says where a later proposal would be sent, never that anybody agreed to one."""
    async with physical.database.begin() as connection:
        await govern(
            connection,
            update(Customer)
            .where(Customer.id == channel_binding.canonical_demo_customer_id())
            .values(approval_channel_address=CHAT),
        )

    await restore(physical, restoring, orders, verify=verifier(destination()))

    assert await physical.requests() == []
    assert await physical.decisions() == []
    assert await physical.effects() == []


# --------------------------------------------------------------------------- the CLI surface


def test_restore_demo_world_is_a_subcommand() -> None:
    result = runner.invoke(cli_app, ["--help"])

    assert result.exit_code == 0
    assert "restore-demo-world" in result.stdout


def test_the_help_names_the_confirmation_value_an_operator_has_to_type() -> None:
    result = runner.invoke(cli_app, ["restore-demo-world", "--help"])

    assert result.exit_code == 0
    assert CONFIRMATION in result.stdout


@pytest.mark.parametrize(
    ("error", "code"),
    [
        pytest.param(demo_restore.NotConfirmedError("nope"), 1, id="not-confirmed"),
        pytest.param(demo_restore.WorldNotRestorableError("nope"), 2, id="not-the-demo"),
        pytest.param(demo_restore.EffectsInFlightError("nope"), 1, id="effects-in-flight"),
        pytest.param(demo_restore.OrderSystemUnreachableError("nope"), 1, id="no-order-system"),
        pytest.param(demo_restore.BindingNotRestorableError("nope"), 3, id="binding"),
    ],
)
def test_each_refusal_gets_its_own_exit_code(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: int
) -> None:
    """An operator scripting this needs to tell "not the demo" from "could not rebind"."""

    async def refuse(*_: Any, **__: Any) -> RestoreOutcome:
        raise error

    monkeypatch.setattr(cli_module, "_run_restore_demo_world", refuse)

    result = runner.invoke(cli_app, ["restore-demo-world", "--confirm", CONFIRMATION])

    assert result.exit_code == code


def test_the_outcome_carries_no_field_that_could_hold_an_address() -> None:
    """Structural rather than a string search: there is nowhere for one to be.

    ``PreservedBinding`` is the only type in the module that holds an address, it never reaches
    an outcome, and its own ``repr`` redacts it.
    """
    named = {field.name for field in fields(RestoreOutcome)} | {
        field.name for field in fields(Census)
    }

    assert not {name for name in named if "address" in name or "chat" in name}
    assert "address" in {field.name for field in fields(PreservedBinding)}
