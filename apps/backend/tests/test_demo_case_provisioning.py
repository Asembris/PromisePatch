"""Provisioning: a deployment comes up with one case open, and never erases one that exists.

Two properties are worth more here than anything about the happy path, because P6.2 records a
reboot that silently re-seeded the database and erased the very cases the deployment exists to
prove outlive the host:

* **idempotent** -- a restart produces no second case;
* **non-destructive** -- a database already holding a case is not touched, whatever that case
  is and however it got there.

Both are asserted against real PostgreSQL, by running the thing twice and by running it over a
case somebody else opened, rather than by reasoning about the emptiness check.

Nothing here arranges a state by writing a row. The provisioned case is planned because the
canonical sentence was said and the canonical question answered, through the same
:mod:`promisepatch.domain.intake` calls the CLI and the MCP surface use, and carried by ordinary
worker cycles.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from _intake_support import Intake
from _intake_support import physical as physical
from sqlalchemy import func, select, text

from promise_graph.examples import hollow_oak as ho
from promisepatch import cli as cli_module
from promisepatch import provisioning
from promisepatch import worker as worker_module
from promisepatch.api.routers import auth as login_router
from promisepatch.api.schemas.cases import CaseListResponse, CaseWorkspaceResponse
from promisepatch.config import Settings
from promisepatch.db.models import Case, OutboxMessage
from promisepatch.domain import intake
from promisepatch.domain.cases import CASE_PLANNED
from promisepatch.domain.observation import CASE_RECEIVED
from promisepatch.main import create_app
from promisepatch.provisioning import Provisioned

pytestmark = pytest.mark.integration


@pytest.fixture
def serving(runtime_settings: Settings) -> Settings:
    """Settings for a deployment that offers the judge entry, which is what provisions a case."""
    return runtime_settings.model_copy(update={"demo_session_enabled": True})


async def provision(physical: Intake, settings: Settings, **bounds: Any) -> Any:
    return await provisioning.ensure_demo_case(
        physical.database, cycles=physical.worker(), settings=settings, **bounds
    )


async def cases(physical: Intake) -> list[tuple[UUID, str, str]]:
    async with physical.database.connect() as connection:
        rows = (
            await connection.execute(select(Case.id, Case.state, Case.opened_by).order_by(Case.id))
        ).all()
    return [(row.id, row.state, row.opened_by) for row in rows]


async def effects(physical: Intake) -> int:
    """How many operational effects have been queued. A planned case must have raised none."""
    async with physical.database.connect() as connection:
        return int(
            (await connection.execute(select(func.count()).select_from(OutboxMessage))).scalar_one()
        )


# ------------------------------------------------------------------- a fresh stack coming up


async def test_a_fresh_stack_comes_up_with_exactly_one_planned_case(
    physical: Intake, serving: Settings
) -> None:
    """The defect, stated as its fix: a judge arriving finds a case rather than an empty list."""
    assert await cases(physical) == []

    outcome = await provision(physical, serving)

    assert outcome.action is Provisioned.OPENED
    assert outcome.reached_plan
    assert await cases(physical) == [(outcome.case_id, CASE_PLANNED, ho.BAKER)]


async def test_the_provisioned_case_carries_the_bands_a_judge_is_shown(
    physical: Intake, serving: Settings
) -> None:
    """`PLANNED` is chosen because it is the one state where every band is populated at once.

    Three authority groups and the untouched set, and -- the reason it is this state and not a
    later one -- **no operational effect at all**, because nobody has confirmed anything.
    """
    outcome = await provision(physical, serving)
    assert outcome.case_id is not None

    from promisepatch.domain import analysis

    status = await analysis.read_case_status(physical.database, case_id=outcome.case_id)
    classified = {track.promise_id: track.classification for track in status.tracks}

    assert classified[ho.PROMISE_A] == "AUTO_RECOVERABLE"
    assert classified[ho.PROMISE_B] == "APPROVAL_REQUIRED"
    assert classified[ho.PROMISE_C] == "BLOCKED"
    assert classified[ho.PROMISE_D] == "BLOCKED"
    assert {ho.PROMISE_E, ho.PROMISE_F} <= {
        track.promise_id for track in status.tracks if track.classification == "UNAFFECTED"
    }
    assert await effects(physical) == 0


async def test_the_worker_says_the_words_rather_than_writing_the_case(
    physical: Intake, serving: Settings
) -> None:
    """The case exists because somebody said something, and the record says who and what."""
    outcome = await provision(physical, serving)
    assert outcome.case_id is not None

    async with physical.database.connect() as connection:
        said = (
            await connection.execute(
                text(
                    "SELECT raw_text FROM promisepatch.case_reports "
                    "WHERE case_id = :case ORDER BY ordinal"
                ),
                {"case": outcome.case_id},
            )
        ).scalars()
        spoken = list(said)

    assert spoken == [provisioning.REPORTED, provisioning.ANSWERED]


async def test_the_operator_command_provisions_through_the_deployed_wiring(
    physical: Intake, serving: Settings
) -> None:
    """``pp ensure-demo-case`` reaches the same case, built by ``worker.built``.

    It is the boot path's own wiring rather than a second copy of it, which is what stops the
    command an operator runs from quietly reaching a different provider than the deployed worker
    does. The database handle here is the command's, not the fixture's.
    """
    outcome = await cli_module._run_ensure_demo_case(serving)

    assert outcome.action is Provisioned.OPENED
    assert await cases(physical) == [(outcome.case_id, CASE_PLANNED, ho.BAKER)]


# ---------------------------------------------------------------- restarting, twice and over


async def test_a_restart_does_not_open_a_second_case(physical: Intake, serving: Settings) -> None:
    """The boot path runs at every start, so running it again must add nothing."""
    first = await provision(physical, serving)
    before = await cases(physical)

    second = await provision(physical, serving)

    assert second.action is Provisioned.PRESENT
    # It names the case it found rather than saying nothing: the identity is derived from the
    # world, so recognising it *is* the reason nothing was opened, and a caller reading the log
    # should be able to see which case that was.
    assert second.case_id == first.case_id
    assert await cases(physical) == before
    assert len(before) == 1 and before[0][0] == first.case_id


async def test_a_case_that_already_exists_is_never_replaced(
    physical: Intake, serving: Settings
) -> None:
    """P6.2's defect, refused: a restart finds somebody else's case and leaves it alone.

    The case here is not the provisioned one -- it is opened by hand under its own command id,
    so it is neither the same row nor recognisable as a redelivery. Provisioning must still do
    nothing, because what it checks is whether *any* case exists rather than whether *its* case
    does.
    """
    opened = await intake.open_physical_exception(
        physical.database,
        command_id=uuid4(),
        worker_id=ho.BAKER,
        raw_text="the mixer is making a noise",
        observed_at=physical.observed_at,
    )
    before = await cases(physical)

    outcome = await provision(physical, serving)

    assert outcome.action is Provisioned.PRESENT
    assert await cases(physical) == before
    assert [row[0] for row in before] == [opened.case_id]


async def test_a_second_process_provisioning_at_once_skips_rather_than_repeating(
    physical: Intake, serving: Settings
) -> None:
    """The lock is `try`, not `wait`: two hosts booting together produce one case and one skip."""
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
    assert await cases(physical) == []


# -------------------------------------------------------------------------- refusing to act


async def test_a_deployment_that_does_not_offer_the_judge_entry_provisions_nothing(
    physical: Intake, runtime_settings: Settings
) -> None:
    """One switch, not two: the entry and the case it lands on are enabled by the same setting."""
    outcome = await provision(physical, runtime_settings)

    assert outcome.action is Provisioned.DISABLED
    assert await cases(physical) == []


async def test_a_run_that_cannot_finish_leaves_the_case_where_it_stopped(
    physical: Intake, serving: Settings
) -> None:
    """Out of budget is not a reason to guess, and never a reason to remove anything.

    With no cycles to spend the case is opened and never interpreted, so it sits at `RECEIVED`
    with its words intact. Nothing is withdrawn, nothing is answered blindly, and no effect is
    raised -- which is exactly what a judge arriving mid-failure should find.
    """
    outcome = await provision(physical, serving, max_cycles=0)

    assert outcome.action is Provisioned.STOPPED
    assert outcome.state == CASE_RECEIVED
    assert await cases(physical) == [(outcome.case_id, CASE_RECEIVED, ho.BAKER)]
    assert await effects(physical) == 0


async def test_a_stopped_run_is_finished_by_the_next_start(
    physical: Intake, serving: Settings
) -> None:
    """A half-provisioned case is left for the loop, and the loop is what carries it.

    The second run finds a case and declines to touch it, and the ordinary worker cycles that
    follow take it the rest of the way -- so a boot that ran out of budget costs a judge nothing
    once the worker is running.
    """
    stopped = await provision(physical, serving, max_cycles=0)
    assert stopped.action is Provisioned.STOPPED

    assert (await provision(physical, serving)).action is Provisioned.PRESENT
    await physical.drain()
    await physical.answer(stopped.case_id, provisioning.ANSWERED)
    await physical.drain()

    assert await cases(physical) == [(stopped.case_id, CASE_PLANNED, ho.BAKER)]


async def test_a_provisioning_failure_never_stops_the_worker_starting(
    physical: Intake, serving: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A judge losing a case to read is survivable; a worker that will not start is not."""

    async def explode(*_: Any, **__: Any) -> Any:
        raise RuntimeError("the provisioning run failed in a way nobody anticipated")

    monkeypatch.setattr(provisioning, "ensure_demo_case", explode)

    await worker_module._DemoCaseKeeper(physical.worker(), serving).check()

    assert await cases(physical) == []


# ------------------------------------------------------- what a judge reaches, and cannot do


@pytest_asyncio.fixture
async def visitor(serving: Settings, physical: Intake) -> AsyncIterator[httpx2.AsyncClient]:
    """A browser holding the session the judge entry mints: an observer, and nothing more."""
    login_router._limiter.reset()
    origin = serving.cors_origins.split(",")[0].strip()
    app = create_app(serving)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=origin) as client,
    ):
        response = await client.post("/api/auth/demo-session", headers={"Origin": origin})
        assert response.status_code == 200, response.text
        client.headers["Origin"] = origin
        yield client


async def test_the_judge_entry_lands_on_the_provisioned_case(
    physical: Intake, serving: Settings, visitor: httpx2.AsyncClient
) -> None:
    """One action, and the first row of the list the entry opens is the case that was seeded."""
    outcome = await provision(physical, serving)

    listing = CaseListResponse.model_validate((await visitor.get("/api/cases")).json())
    assert [row.case_id for row in listing.cases] == [outcome.case_id]

    response = await visitor.get(f"/api/cases/{outcome.case_id}")
    assert response.status_code == 200, response.text
    view = CaseWorkspaceResponse.model_validate(response.json())
    assert view.untouched
    assert any(band.promises for band in view.authority_bands)


async def test_a_judge_reading_the_provisioned_case_still_may_not_speak_on_it(
    physical: Intake, serving: Settings, visitor: httpx2.AsyncClient
) -> None:
    """The refusal that stood before this case existed stands over this case too."""
    outcome = await provision(physical, serving)

    view = CaseWorkspaceResponse.model_validate(
        (await visitor.get(f"/api/cases/{outcome.case_id}")).json()
    )
    assert view.may_speak is False
    # A read verb is offered and no effecting one is: the screen may show a judge the case's
    # own status sentence, and has nothing to draw that would change it.
    assert set(view.permitted_verbs) == {"status"}
    assert not {"report", "clarify", "confirm", "withdraw"} & set(view.permitted_verbs)

    refused = await visitor.post(
        "/api/conversation/clarify",
        json={"case_id": str(outcome.case_id), "text": provisioning.ANSWERED},
    )
    assert refused.status_code in (403, 422), refused.text
    assert await cases(physical) == [(outcome.case_id, CASE_PLANNED, ho.BAKER)]
