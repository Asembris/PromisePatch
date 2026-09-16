"""A deployed demo world that stops decaying, and the case state it is not allowed to cost.

``docs/demo-fixture-anchoring.md`` measured the decay rather than reasoning about it: the seed is
a point-in-time world written once per instance, so the day after it was taken the canonical
report resolves *today's raspberry delivery* to **tomorrow's** delivery -- which also carries
raspberries, so nothing fails -- and every promise the exception reaches falls to ``BLOCKED``.
The two bands the product exists to show are gone, silently, one day after the seed.

Every test here therefore seeds a world **in the past** and then asks the question a judge asks:
not *is there a row* but *what does the screen say*. The bands are read back through
``GET /api/cases/{id}`` as the observer session the judge entry mints, because that is the
surface the claim is about, and they are asserted in full -- one promise repaired, one asked
about, two escalated, two never touched -- because a run that produced four blocked promises
would still be a working case and a useless demo.

The distances are +1 day, +60 days and +400 days: the first day on which the decay bites at all,
the distance between recording a demo and being judged on it, and a distance at which anything
tied to a month, a quarter or a year number has certainly moved.

**The other half of every test here is what was not destroyed.** A roll concludes the case it
supersedes through the domain's own bounded withdrawal and leaves the row, its words and its
audit behind; and it refuses to happen at all if anything in the database belongs to somebody --
a live case this module did not open, a dispatched effect, a customer's reply, an approval.
P6.2 records what a re-seed that ignored that cost.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx2
import pytest
import pytest_asyncio
from _database_safety import migration_database_url
from _intake_support import Intake, bakery_anchor
from _intake_support import physical as physical
from sqlalchemy import func, select, text

from promise_graph.examples import hollow_oak as ho
from promisepatch import provisioning
from promisepatch import worker as worker_module
from promisepatch.api.routers import auth as login_router
from promisepatch.api.schemas.cases import CaseListResponse, CaseWorkspaceResponse
from promisepatch.config import Settings
from promisepatch.db import build_engine
from promisepatch.db.boundary import APPEND_ONLY_TABLES
from promisepatch.db.models import (
    Case,
    CaseReport,
    InventoryLedgerEntry,
    OutboxMessage,
    Promise,
    RecipeVersion,
    SupplierCommitment,
    Track,
)
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.domain import intake
from promisepatch.domain.cases import CASE_PLANNED
from promisepatch.domain.physical import bakery_day
from promisepatch.fixtures import demo
from promisepatch.fixtures.projection import project
from promisepatch.fixtures.reanchor import reanchor_world, shiftable
from promisepatch.fixtures.reset import reset_demo_state
from promisepatch.main import create_app
from promisepatch.provisioning import Provisioned

pytestmark = pytest.mark.integration

type Arrival = Callable[[], Awaitable[httpx2.AsyncClient]]
"""One press of *Look around a real case*, which mints an observer session and nothing more."""

DISTANCES = (1, 60, 400)
"""Days between the seed and the judge. Named rather than inlined so every test uses the same."""

CANONICAL_BANDS = {
    "AUTO_RECOVERABLE": (ho.PROMISE_A,),
    "APPROVAL_REQUIRED": (ho.PROMISE_B,),
    "BLOCKED": (ho.PROMISE_C, ho.PROMISE_D),
}
"""The heterogeneous-authority story, by classification. Untouched is asserted separately."""


@pytest.fixture
def serving(runtime_settings: Settings) -> Settings:
    """Settings for a deployment that offers the judge entry, which is what provisions a case."""
    return runtime_settings.model_copy(update={"demo_session_enabled": True})


async def provision(physical: Intake, settings: Settings, **bounds: Any) -> Any:
    return await provisioning.ensure_demo_case(
        physical.database, cycles=physical.worker(), settings=settings, **bounds
    )


async def seed_world_at(anchor: datetime) -> None:
    """Load the Hollow Oak fixture at ``anchor``, as an operator's own reset would.

    The real thing rather than a hand-built row set: this is exactly what ran on the deployed
    host, and a test that arranged a stale world any other way would be asserting about its own
    arrangement rather than about the one the deployment decays from.
    """
    settings = Settings()
    engine = build_engine(migration_database_url(settings), pool_size=1)
    try:
        async with engine.begin() as connection:
            await reset_demo_state(
                connection,
                anchor=anchor,
                now=datetime.now(UTC),
                passwords={
                    demo.BAKER_ROLE: settings.require_demo_worker_password(),
                    demo.OWNER_ROLE: settings.require_demo_owner_password(),
                },
                actor=Actor(kind="SYSTEM", id="demo-world-roll-tests"),
            )
    finally:
        await engine.dispose()


async def seed_days_ago(days: int) -> datetime:
    """A world that was seeded ``days`` ago and has been lived in since. Returns that anchor."""
    anchor = bakery_anchor(Settings()) - timedelta(days=days)
    await seed_world_at(anchor)
    return anchor


@pytest_asyncio.fixture
async def judge(serving: Settings) -> AsyncIterator[Arrival]:
    """Pressing the judge entry, as an action a test takes rather than a client it is handed.

    A factory and not a ready client, because every test here reseeds the database in its own
    body and a reset truncates ``sessions``: a session minted before that arrangement would be
    signed out by it, which is exactly what an operator taking the documented repair by hand
    also has to do afterwards.
    """
    origin = serving.cors_origins.split(",")[0].strip()
    app = create_app(serving)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=origin) as client,
    ):

        async def arrive() -> httpx2.AsyncClient:
            login_router._limiter.reset()
            response = await client.post("/api/auth/demo-session", headers={"Origin": origin})
            assert response.status_code == 200, response.text
            client.headers["Origin"] = origin
            return client

        yield arrive


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


async def commitments(physical: Intake) -> dict[str, datetime]:
    async with physical.database.connect() as connection:
        rows = (
            await connection.execute(select(SupplierCommitment.id, SupplierCommitment.due_at))
        ).all()
    return {row.id: row.due_at for row in rows}


# ------------------------------------------- what a judge reads, however long ago the seed ran


@pytest.mark.parametrize("days", DISTANCES, ids=[f"+{days}d" for days in DISTANCES])
async def test_a_judge_arriving_long_after_the_seed_still_reads_the_whole_story(
    physical: Intake, serving: Settings, judge: Arrival, days: int
) -> None:
    """The claim, end to end: the screen, not the row.

    All four bands are asserted rather than a count of them, because the decay
    ``docs/demo-fixture-anchoring.md`` measured does not empty the case -- it fills it with four
    blocked promises, which looks like a working product right up until somebody asks what the
    system decided by itself.
    """
    await seed_days_ago(days)

    outcome = await provision(physical, serving)

    assert outcome.action is Provisioned.OPENED
    assert outcome.rolled is True
    assert outcome.state == CASE_PLANNED

    view = await workspace(await judge(), outcome.case_id)
    assert bands_of(view) == CANONICAL_BANDS
    assert tuple(sorted(promise.promise_id for promise in view.untouched)) == (
        ho.PROMISE_E,
        ho.PROMISE_F,
    )
    assert view.untouched_count == 2
    assert view.untouched_effect_count == 0
    assert view.reported_text == provisioning.REPORTED


@pytest.mark.parametrize("days", DISTANCES, ids=[f"+{days}d" for days in DISTANCES])
async def test_every_deadline_the_screen_shows_is_still_ahead_of_the_judge(
    physical: Intake, serving: Settings, judge: Arrival, days: int
) -> None:
    """A promise due in the past reads as a missed one whatever the case says about it."""
    await seed_days_ago(days)
    outcome = await provision(physical, serving)
    now = datetime.now(UTC)

    view = await workspace(await judge(), outcome.case_id)
    shown = [
        promise.deadline_at
        for band in view.authority_bands
        for promise in band.promises
        if promise.deadline_at is not None
    ]
    assert shown, "a case with no deadline on any threatened promise proves nothing here"
    assert all(datetime.fromisoformat(deadline) > now for deadline in shown)

    async with physical.database.connect() as connection:
        overdue = await connection.scalar(
            select(func.count()).select_from(Promise).where(Promise.due_at <= now)
        )
    assert overdue == 0


@pytest.mark.parametrize("days", DISTANCES, ids=[f"+{days}d" for days in DISTANCES])
async def test_the_judge_entry_lands_on_the_case_the_roll_opened(
    physical: Intake, serving: Settings, judge: Arrival, days: int
) -> None:
    """Newest first, and the newest is the one anchored to today rather than to the seed."""
    await seed_days_ago(days)
    outcome = await provision(physical, serving)

    listing = CaseListResponse.model_validate((await (await judge()).get("/api/cases")).json())
    assert listing.cases, "the judge entry landed on an empty list"
    assert listing.cases[0].case_id == outcome.case_id


# ------------------------------------------------------------------- and the same on any boot


async def test_a_world_seeded_today_is_left_exactly_where_it_is(
    physical: Intake, serving: Settings
) -> None:
    """The first boot is the hundredth boot with nothing to do: same code, no roll."""
    before = await commitments(physical)

    outcome = await provision(physical, serving)

    assert outcome.action is Provisioned.OPENED
    assert outcome.rolled is False
    assert await commitments(physical) == before


@pytest.mark.parametrize("days", DISTANCES, ids=[f"+{days}d" for days in DISTANCES])
async def test_running_it_twice_on_a_stale_world_rolls_once_and_opens_one_case(
    physical: Intake, serving: Settings, days: int
) -> None:
    """Idempotent across restarts, which is the only way a boot-time action may be written."""
    await seed_days_ago(days)

    first = await provision(physical, serving)
    settled = await commitments(physical)

    second = await provision(physical, serving)

    assert first.action is Provisioned.OPENED and first.rolled is True
    assert second.action is Provisioned.PRESENT
    assert second.rolled is False
    assert await commitments(physical) == settled
    async with physical.database.connect() as connection:
        opened = (await connection.execute(select(Case.id, Case.state))).all()
    assert [(row.id, row.state) for row in opened if row.state == CASE_PLANNED] == [
        (first.case_id, CASE_PLANNED)
    ]


def test_one_world_has_one_case_identity() -> None:
    """The derivation, on its own: keyed to the world, not to the clock.

    This is what lets the same fixed-identity argument that made "run at every boot" safe also
    make "run again after a roll" possible. One identity for two worlds would read the new
    world's report as a redelivery of the old one's and hand back the case the roll had just
    concluded, which is a judge landing on a cancelled case -- a defect this suite found by
    asserting the outcome rather than the row.
    """
    anchor = datetime.now(UTC)
    assert provisioning.report_command_id(anchor) == provisioning.report_command_id(anchor)
    assert provisioning.report_command_id(anchor) != provisioning.report_command_id(
        anchor + timedelta(minutes=1)
    )
    assert provisioning.report_command_id(anchor) != provisioning.answer_command_id(anchor)


# ------------------------------------------------------ what a roll costs, and what it may not


async def open_the_demo_case_against(physical: Intake, anchor: datetime) -> Any:
    """The case a boot against the world at ``anchor`` leaves behind, opened the way it opens it.

    The provisioning identities and the provisioning sentences, through
    :mod:`promisepatch.domain.intake`, because a case arranged any other way would be a case the
    roll is entitled to treat as somebody's and refuse to touch -- which is the protection being
    relied on elsewhere in this file, so it must not be sidestepped here.
    """
    opened = await intake.open_physical_exception(
        physical.database,
        command_id=provisioning.report_command_id(anchor),
        worker_id=ho.BAKER,
        raw_text=provisioning.REPORTED,
        observed_at=datetime.now(UTC),
    )
    await physical.drain()
    await intake.answer_clarification(
        physical.database,
        case_id=opened.case_id,
        command_id=provisioning.answer_command_id(anchor),
        worker_id=ho.BAKER,
        raw_text=provisioning.ANSWERED,
    )
    await physical.drain()
    return opened.case_id


async def test_the_superseded_case_is_concluded_rather_than_destroyed(
    physical: Intake, serving: Settings, judge: Arrival
) -> None:
    """No row is deleted. The old case is still there, concluded, with its words intact.

    One day rather than sixty, because this is the distance at which a decayed case still drives
    all the way to ``PLANNED`` -- ``docs/demo-fixture-anchoring.md``'s middle row, the dangerous
    one -- so there is a real planned case with real tracks for the roll to have to deal with.

    The last assertion is the one that makes this more than bookkeeping. A live track elsewhere
    turns a promise ``LINKED`` in any later case (``promisepatch.domain.analysis``'s
    ``_live_tracks_elsewhere``), so if the old case had merely been left alone the new one would
    show six linked promises and no authority bands at all. The bands being canonical is the
    proof that concluding it really released them.
    """
    anchor = await seed_days_ago(1)
    superseded = await open_the_demo_case_against(physical, anchor)

    outcome = await provision(physical, serving)

    assert outcome.action is Provisioned.OPENED
    assert outcome.rolled is True
    assert outcome.case_id != superseded

    async with physical.database.connect() as connection:
        state = await connection.scalar(select(Case.state).where(Case.id == superseded))
        said = list(
            (
                await connection.execute(
                    select(CaseReport.raw_text)
                    .where(CaseReport.case_id == superseded)
                    .order_by(CaseReport.ordinal)
                )
            ).scalars()
        )
        tracks = list(
            (
                await connection.execute(select(Track.state).where(Track.case_id == superseded))
            ).scalars()
        )
    assert state == "CANCELLED"
    assert said == [provisioning.REPORTED, provisioning.ANSWERED]
    assert tracks, "the superseded case had no tracks, so this proves nothing about releasing any"
    assert set(tracks) <= {"WITHDRAWN", "UNAFFECTED"}

    assert bands_of(await workspace(await judge(), outcome.case_id)) == CANONICAL_BANDS


@pytest.mark.parametrize("days", DISTANCES, ids=[f"+{days}d" for days in DISTANCES])
async def test_a_case_somebody_else_opened_stops_the_world_from_moving(
    physical: Intake, serving: Settings, days: int
) -> None:
    """The footgun, refused: a judge mid-conversation is worth more than a current world."""
    await seed_days_ago(days)
    opened = await intake.open_physical_exception(
        physical.database,
        command_id=uuid4(),
        worker_id=ho.BAKER,
        raw_text="the mixer is making a noise",
        observed_at=datetime.now(UTC),
    )
    before = await commitments(physical)

    outcome = await provision(physical, serving)

    assert outcome.action is Provisioned.REFUSED
    assert str(opened.case_id) in outcome.detail
    assert await commitments(physical) == before
    async with physical.database.connect() as connection:
        assert (
            await connection.scalar(select(Case.state).where(Case.id == opened.case_id))
        ) != "CANCELLED"


async def test_an_effect_that_has_already_been_queued_stops_the_world_from_moving(
    physical: Intake, serving: Settings
) -> None:
    """A confirmed plan has reached out of this system, and the roll refuses on that alone.

    Not a synthetic row: the case is planned, its plan identity is read as the worker would read
    it and confirmed as the worker would confirm it, so the effects are the ones the product
    really raises. That is also why the guard is global -- once an amendment has gone to the
    External Order System, the mirror and the simulator no longer match a fresh seed.
    """
    outcome = await provision(physical, serving)
    assert outcome.case_id is not None
    await physical.confirm(outcome.case_id, plan_id=await physical.plan_id(outcome.case_id))
    await physical.drain()

    async with physical.database.connect() as connection:
        queued = await connection.scalar(select(func.count()).select_from(OutboxMessage))
    assert queued, "the confirmation raised no effect; this test would prove nothing"

    await _age_the_world(timedelta(days=60))
    before = await commitments(physical)

    refused = await provision(physical, serving)

    assert refused.action is Provisioned.REFUSED
    assert "effect" in refused.detail
    assert await commitments(physical) == before


async def test_a_second_process_rolling_at_once_skips_rather_than_repeating(
    physical: Intake, serving: Settings
) -> None:
    """The lock is the existing precedent, and it covers the roll as well as the opening."""
    await seed_days_ago(60)
    before = await commitments(physical)

    async with physical.database.connect() as connection:
        held = (
            await connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": provisioning.LOCK_KEY}
            )
        ).scalar_one()
        assert held is True
        try:
            outcome = await provision(physical, serving)
        finally:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": provisioning.LOCK_KEY}
            )

    assert outcome.action is Provisioned.CONTENDED
    assert await commitments(physical) == before
    async with physical.database.connect() as connection:
        assert (await connection.scalar(select(func.count()).select_from(Case))) == 0


# --------------------------------------------------------------- exactly which instants moved


@pytest.mark.parametrize("days", DISTANCES, ids=[f"+{days}d" for days in DISTANCES])
async def test_a_rolled_world_holds_the_instants_a_fresh_seed_would_have_written(
    physical: Intake, serving: Settings, days: int
) -> None:
    """The shift is exact, and it is checked against the seed rather than against arithmetic.

    Every fixture instant is an offset from the anchor, so a world moved by the right duration
    is byte-identical to one seeded now -- on every column that can be written after the fact.
    """
    await seed_days_ago(days)
    outcome = await provision(physical, serving)
    assert outcome.rolled is True

    async with physical.database.connect() as connection:
        anchor = await connection.scalar(text("SELECT anchor_at FROM promisepatch.fixture_state"))
        due = await connection.scalar(
            select(SupplierCommitment.due_at).where(SupplierCommitment.id == ho.VP_TODAY)
        )
    expected = {
        commitment.id: commitment.due_at
        for commitment in demo.build_snapshot(anchor).commitments.values()
    }
    assert due == expected[ho.VP_TODAY]
    assert await commitments(physical) == expected


@pytest.mark.parametrize("days", DISTANCES, ids=[f"+{days}d" for days in DISTANCES])
async def test_the_two_append_only_histories_are_left_where_they_happened(
    physical: Intake, serving: Settings, days: int
) -> None:
    """Recipes were authored and stock was posted in the past, and a roll does not pretend else.

    Both tables refuse an ``UPDATE`` outright, so this is as much a statement of what the
    database permits as of what the code intends -- and neither column is read against the clock
    to decide a band, which is what makes leaving them correct rather than merely unavoidable.
    """
    await seed_days_ago(days)

    async def histories() -> tuple[list[datetime], list[datetime]]:
        async with physical.database.connect() as connection:
            authored = list(
                (
                    await connection.execute(
                        select(RecipeVersion.authored_at).order_by(RecipeVersion.id)
                    )
                ).scalars()
            )
            posted = list(
                (
                    await connection.execute(
                        select(InventoryLedgerEntry.recorded_at).order_by(InventoryLedgerEntry.seq)
                    )
                ).scalars()
            )
        return authored, posted

    before = await histories()
    async with physical.database.begin() as connection:
        outcome = await reanchor_world(
            connection,
            anchor=datetime.now(UTC),
            now=datetime.now(UTC),
            actor=Actor(kind="SYSTEM", id="demo-world-roll-tests"),
        )
    assert outcome.moved is True

    assert await histories() == before


def test_every_instant_the_projection_writes_is_either_shifted_or_append_only() -> None:
    """The column list is derived, so nothing can be forgotten when a table gains a time.

    A table that starts carrying a ``datetime`` and is neither shifted nor append-only would be
    an instant frozen at the bootstrap day inside a world that had moved past it, which is the
    original defect wearing a smaller hat.
    """
    anchor = ho.ANCHOR
    moved = {table: set(columns) for table, columns in shiftable()}
    for table in project(demo.build_snapshot(anchor), mirrored_at=anchor):
        times = {
            column
            for row in table.rows
            for column, value in row.items()
            if isinstance(value, datetime)
        }
        if not times:
            continue
        if table.table in APPEND_ONLY_TABLES:
            assert table.table not in moved
            continue
        assert moved.get(table.table) == times, table.table


# ------------------------------------------------------------------- when the worker looks


async def test_the_worker_looks_once_a_bakery_day_and_once_at_start(
    physical: Intake, serving: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A boot-only check would serve the bootstrap day's world for ever on a host nobody reboots.

    The gate is the bakery day rather than an interval, so the look happens exactly when the
    thing it looks for can have changed, and costs a clock read on every other idle cycle.
    """
    looked: list[datetime] = []

    async def counted(*_: Any, **__: Any) -> Any:
        looked.append(datetime.now(UTC))
        return provisioning.ProvisionOutcome(Provisioned.DISABLED)

    monkeypatch.setattr(provisioning, "ensure_demo_case", counted)
    keeper = worker_module._DemoCaseKeeper(physical.worker(), serving)

    await keeper.check()
    await keeper.check_if_the_day_turned()
    await keeper.check_if_the_day_turned()
    assert len(looked) == 1

    keeper.checked_day = bakery_day(datetime.now(UTC))[0] - timedelta(days=1)
    await keeper.check_if_the_day_turned()
    assert len(looked) == 2


async def test_a_look_that_failed_is_not_retried_every_idle_cycle(
    physical: Intake, serving: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The broad handler is the point, and so is marking the day anyway.

    A provisioning failure costs a judge a case to read; a worker that spun on it every idle
    cycle would cost the deployment the loop. The day is marked before the call for exactly
    that reason.
    """
    attempts = 0

    async def explode(*_: Any, **__: Any) -> Any:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("the provisioning run failed in a way nobody anticipated")

    monkeypatch.setattr(provisioning, "ensure_demo_case", explode)
    keeper = worker_module._DemoCaseKeeper(physical.worker(), serving)

    await keeper.check()
    await keeper.check_if_the_day_turned()
    await keeper.check_if_the_day_turned()

    assert attempts == 1


async def _age_the_world(by: timedelta) -> None:
    """Move the whole demo world backwards, so that now is ``by`` later than the seed was.

    The clock cannot be moved for a process talking to a real database, so the world is moved
    under it instead -- which is the shape of the decay being tested, and touches exactly the
    columns the roll itself writes. Governed, and through the migration role, because the
    database's own trigger refuses an unaudited ``UPDATE`` whoever makes it: reaching past the
    boundary is not something a fixture gets to do quietly either.
    """
    settings = Settings()
    engine = build_engine(migration_database_url(settings), pool_size=1)
    try:
        async with engine.begin() as connection:
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="FIXTURE_LOAD",
                actor=Actor(kind="SYSTEM", id="demo-world-roll-tests"),
                authority="NONE",
            ) as write:
                for table, columns in shiftable():
                    assignment = ", ".join(
                        f'"{column}" = "{column}" - CAST(:by AS interval)' for column in columns
                    )
                    await write.execute(
                        text(f'UPDATE promisepatch."{table}" SET {assignment}').bindparams(by=by)
                    )
                await write.execute(
                    text(
                        "UPDATE promisepatch.fixture_state "
                        "SET anchor_at = anchor_at - CAST(:by AS interval)"
                    ).bindparams(by=by)
                )
    finally:
        await engine.dispose()
