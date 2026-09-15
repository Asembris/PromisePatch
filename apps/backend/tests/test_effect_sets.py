"""The executable effect-set scenarios: the frozen manifest, driven against the real system.

Each test here takes one scenario out of ``docs/effect-sets/scenarios.v1.json``, performs its
stipulated facts against a real seeded database with a real External Order System beside it,
reads the four partitions and the cumulative effect multiset at every checkpoint the scenario
declares, and hands both to :func:`_effect_set_judge.judge`. Nothing in this file holds an
expected label, and nothing in it decides what passing means.

**Three of the sixteen are wired.** ``S02``, ``S11`` and ``S12`` -- the ones that already had
partial coverage elsewhere in the suite -- are here to prove the harness end to end: a scenario
whose partition never moves and whose effects are all escalations, one where an external edit
takes an order out of the affected set before the incident, and its mirror image where an
external edit puts one in. The other thirteen have no executable path yet. That is stated by
:data:`scripts.run_effect_sets.WIRED`, which is what the runner reads, so the gap is a fact the
tooling reports rather than a silence.

**Nothing here is a score.** A run of this file is a harness-development run under
`docs/effect-set-run-protocol.md`: it writes per-scenario verdicts to the run's sink if it was
given one, and no ratio out of sixteen is computed here or anywhere it reaches.

Every step is taken through a real surface. The external edits go through the order system's own
HTTP screen and cross as signed webhooks; the conversation is real MCP tool calls over the real
transport; the recovery runs in a real worker process; the customer's reply arrives on the
inbound transport as a provider delivery. The only direct database access is the reads that
count what all of it left behind.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
import pytest_asyncio
from _effect_set_judge import Observation, assert_passes, harness_failure, judge, record
from _effect_set_observation import ORDERS, baseline_of, observe
from _effect_sets import checkpoint_names, scenario
from _intake_support import BAKER, CANONICAL_REPORT, RASPBERRY_ONLY, WHOLE_DELIVERY, Intake
from _intake_support import physical as physical
from _mcp_support import SERVICE_TOKEN, McpServer, mcp_over_http, serve
from _order_system_support import LEMON_CURD, LENA_ORDER, RASPBERRY_LEMON, Boundary, boundary
from mcp.types import CallToolResult

from promisepatch.config import Settings
from promisepatch.main import create_app
from promisepatch.worker import Worker

pytestmark = pytest.mark.integration

AHMED_ORDER: Final = "EXT-E"
"""The order S12's external edit moves into the blast radius."""

TOMAS: Final = "ord-b"
"""The one order whose recovery needs the customer's permission first, in S11 and S12."""

CONSENT: Final = "YES"
"""A literal yes and nothing else. The only thing that is a customer's consent."""


# ------------------------------------------------------------------------------- the rig


def api_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"internal_service_token": SERVICE_TOKEN, "surface_worker_id": BAKER}
    values.update(overrides)
    return Settings(**values)


@pytest_asyncio.fixture
async def chain(physical: Intake) -> AsyncIterator[McpServer]:
    """The MCP endpoint and the intent API, on two sockets, over the seeded database."""
    async with serve(create_app(api_settings())) as api_base, mcp_over_http(api_base) as server:
        yield server


@pytest_asyncio.fixture
async def wired(
    physical: Intake, runtime_settings: Settings, tmp_path: Path
) -> AsyncIterator[Boundary]:
    """The External Order System, running, with the traffic between it and us under control."""
    async with boundary(
        physical.database,
        settings=runtime_settings,
        sqlite_path=tmp_path / "order-simulator.sqlite3",
    ) as running:
        yield running


def worker_for(intake: Intake, wired: Boundary) -> Worker:
    """A worker wired exactly as ``promisepatch.worker.run`` wires one for a deployment."""
    return intake.worker(adapter=wired.adapter, fetch=wired.client.fetch_order)


def body(result: CallToolResult) -> dict[str, Any]:
    assert result.structured_content is not None, result
    assert not result.is_error, result
    return dict(result.structured_content)


# --------------------------------------------------------------- performing a stipulated fact


async def external_edit(intake: Intake, wired: Boundary, *, order: str, item: str) -> None:
    """A customer's own edit, in the other application, carried across and applied.

    Through the order system's own HTTP surface and its own webhook, so PromisePatch finds out
    the way it finds out about every external change. The worker that applies the mirror update
    is the same worker every other step runs in, and the edit is that customer's command: it can
    never become an effect of a case that has not opened yet.
    """
    await wired.operator_changes(order=order, item=item)
    await wired.deliver_webhooks()
    await intake.drain(worker=worker_for(intake, wired), limit=20)


async def reported(server: McpServer, intake: Intake, text: str = CANONICAL_REPORT) -> UUID:
    """The worker's sentence, over the real transport, interpreted and found ambiguous."""
    async with server.session() as session:
        opened = body(await session.call_tool("report", {"text": text}))
        case_id = UUID(opened["case_id"])
    await intake.drain_intake(case_id)
    return case_id


async def answered(server: McpServer, intake: Intake, case_id: UUID, answer: str) -> None:
    """The worker's answer to the one open question, and the analysis it lets run."""
    async with server.session() as session:
        await session.call_tool("clarify", {"case_id": str(case_id), "answer": answer})
    await intake.drain()


async def confirmed(server: McpServer, intake: Intake, case_id: UUID) -> None:
    """The plan the surface offered, quoted back to it as the worker's explicit yes."""
    async with server.session() as session:
        offered = body(await session.call_tool("status", {"case_id": str(case_id)}))
        assert offered["awaiting_confirmation"] is True, offered
        await session.call_tool(
            "confirm", {"case_id": str(case_id), "plan_id": str(offered["plan_id"])}
        )


async def settle(intake: Intake, wired: Boundary, *, rounds: int = 4) -> None:
    """Run the worker, carry the order system's echo across, and let the workflow finish."""
    for _ in range(rounds):
        await wired.deliver_webhooks()
        await intake.make_work_due()
        await intake.drain(worker=worker_for(intake, wired), limit=40)


async def customer_consents(intake: Intake, wired: Boundary, case_id: UUID) -> None:
    """Tomas replies ``YES`` on his own channel, and the workflow acts on it.

    The reply arrives on the inbound transport as a provider delivery bound to his own approval
    request, which is the only path a sentence has to becoming a decision. Nothing writes a
    decision row directly.
    """
    track = await intake.track(case_id, ORDERS[TOMAS]["promise"])
    assert track is not None, "the order whose recovery needs permission has no track"
    request = await intake.request_for(track.id)
    assert request is not None, "the customer was never asked, so there is nothing to answer"
    await intake.deliver_reply(request.id, CONSENT)
    await settle(intake, wired)


async def quiescent(intake: Intake, case_id: UUID) -> None:
    """A checkpoint is a quiescent point, so a reading taken mid-step is not the one it names."""
    remaining = await intake.outstanding(case_id)
    assert not remaining, [row.step_key for row in remaining]


# ---------------------------------------------------------- one scenario, judged and recorded


async def scored(scenario_id: str, drive: Callable[[], Awaitable[dict[str, Observation]]]) -> None:
    """Drive one scenario, judge it against its frozen labels, record the verdict, then assert.

    The verdict is written to the run's sink *before* the assertion is raised, so a scenario
    that fails still leaves its whole diff behind for the capture. A drive that raises is
    recorded as a ``HARNESS_FAILURE`` by name rather than vanishing: the protocol counts one as
    a nonpass, and a nonpass nobody can see is worse than one everybody can.
    """
    try:
        observations = await drive()
    except BaseException as error:  # re-raised immediately; the verdict is recorded first
        record(harness_failure(scenario_id, f"{type(error).__name__}: {error}"))
        raise
    verdict = judge(scenario_id, observations)
    record(verdict)
    assert_passes(verdict)


def declared(scenario_id: str) -> tuple[str, ...]:
    """The checkpoints this scenario declares, in the manifest's own order."""
    return checkpoint_names(scenario(scenario_id))


# ------------------------------------------------------- S02: the whole delivery did not arrive


async def test_s02_whole_delivery_counterfactual(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """The base world, answered "the whole delivery": nobody is asked, because nothing can be.

    Three checkpoints and no consent event, which is what makes this the scenario that proves the
    harness reads an *absence* correctly. Every declared effect is an escalation and a held task,
    and the four orders the shortfall reaches carry no amendment and no message at any checkpoint
    -- so a harness that counted an intention rather than a delivered effect would fail here
    rather than pass quietly.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S02") == ("PLANNED", "CONFIRMED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, WHOLE_DELIVERY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)
        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S02", drive)


# ------------------------------------------ S11: an external edit removes a dependency, before


async def test_s11_external_edit_removes_dependency_before(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """Lena changes her cake out of the raspberry world before anybody reports anything.

    The demo order of events, and the scenario that exercises the whole authority range in one
    case: an amendment nobody was asked about, a message that asks, an escalation, and three
    orders left entirely alone -- one of which got there by a change this system did not make.
    Her own amendment moved a real order and real reservations, and the census must still
    attribute none of it to this case.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S11") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        await external_edit(physical, wired, order=LENA_ORDER, item=LEMON_CURD)
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)
        await settle(physical, wired)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        await customer_consents(physical, wired, case_id)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S11", drive)


# --------------------------------------------- S12: an external edit adds a dependency, before


async def test_s12_external_edit_adds_dependency_before(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """Ahmed changes his cake into the blast radius before anybody reports anything.

    The mirror image of S11, and the reason the pair is worth wiring together: membership of the
    threatened set is decided by stored state at the moment of the exception, in both directions.
    His order carries no constraint that could permit a substitution and no variant exists of the
    version he has just moved to, so the shortfall reaches him and nothing this system may do
    repairs it. His production task is already started in the fixture, which the scenario
    stipulates rather than changes, and which does not alter the label.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S12") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        await external_edit(physical, wired, order=AHMED_ORDER, item=RASPBERRY_LEMON)
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)
        await settle(physical, wired)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        await customer_consents(physical, wired, case_id)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S12", drive)
