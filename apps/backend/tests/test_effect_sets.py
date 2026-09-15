"""The executable effect-set scenarios: the frozen manifest, driven against the real system.

Each test here takes one scenario out of ``docs/effect-sets/scenarios.v1.json``, performs its
stipulated facts against a real seeded database with a real External Order System beside it,
reads the four partitions and the cumulative effect multiset at every checkpoint the scenario
declares, and hands both to :func:`_effect_set_judge.judge`. Nothing in this file holds an
expected label, and nothing in it decides what passing means.

**All sixteen are wired.** Each one performs its own stipulated facts and reads every checkpoint
it declares; :data:`scripts.run_effect_sets.WIRED` is what the runner reads, and it now names the
whole manifest. Wired is not the same as agreeing: four of these tests are committed **failing**,
because a disagreement between a frozen label and what the system does is the measurement arriving
early, and the protocol is explicit that it is recorded and left alone until the first scored run
has been taken. Nothing is skipped, weakened or marked expected-to-fail.

**Nothing here is a score.** A run of this file is a harness-development run under
`docs/effect-set-run-protocol.md`: it writes per-scenario verdicts to the run's sink if it was
given one, and no ratio out of sixteen is computed here or anywhere it reaches.

**A scenario performs its stipulated facts and nothing else.** Where the manifest names a
confirmation, one is given; where it does not, none is. Several scenarios also stipulate *when*
something happened relative to the case's own progress, and those orderings are made deliberate
rather than raced for -- see :func:`work_held`. Four scenarios need a fault rather than a happy
path: a reply carrying somebody else's channel, the same delivery twice under one provider
identity, a process killed at a named persistence boundary after the order system had already
acted, and a second worker with a different boot identity taking over durable state. Each is an
explicit action a test takes, named where it happens.

Every step is taken through a real surface. The external edits go through the order system's own
HTTP screen and cross as signed webhooks; the conversation is real MCP tool calls over the real
transport; the recovery runs in a real worker process; the customer's reply arrives on the
inbound transport as a provider delivery. The only direct database access is the reads that
count what all of it left behind.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
import pytest_asyncio
from _effect_set_judge import Observation, assert_passes, harness_failure, judge, record
from _effect_set_observation import ORDERS, baseline_of, observe, reservations_by_line
from _effect_sets import checkpoint_names, scenario
from _intake_support import (
    BAKER,
    CANONICAL_REPORT,
    RASPBERRY_ONLY,
    STRAWBERRIES,
    TOMAS_CHANNEL,
    WHOLE_DELIVERY,
    Intake,
)
from _intake_support import physical as physical
from _mcp_support import SERVICE_TOKEN, McpServer, mcp_over_http, serve
from _order_system_support import LEMON_CURD, LENA_ORDER, RASPBERRY_LEMON, Boundary, boundary
from mcp.types import CallToolResult

from promise_graph.examples import hollow_oak
from promisepatch.config import Settings
from promisepatch.domain import crash, recovery
from promisepatch.fixtures.projection import TableRows, project
from promisepatch.main import create_app
from promisepatch.worker import Worker

pytestmark = pytest.mark.integration

AHMED_ORDER: Final = "EXT-E"
"""The order S12's external edit moves into the blast radius."""

TOMAS: Final = "ord-b"
"""The one order whose recovery needs the customer's permission first, in S11 and S12."""

PRIYA: Final = "ord-a"
"""The one order a standing preapproval lets this system repair without asking anybody."""

CAFE: Final = "ord-f"
"""The standing pastry order the raspberry shortfall never reaches."""

AHMED: Final = "ord-e"

PRIYA_ORDER: Final = ORDERS[PRIYA]["external_id"]
TOMAS_ORDER: Final = ORDERS[TOMAS]["external_id"]
CAFE_ORDER: Final = ORDERS[CAFE]["external_id"]
AHMED_CHANNEL: Final = ORDERS[AHMED]["channel"]
"""Identities read out of the manifest's own order table rather than typed a second time."""

CONSENT: Final = "YES"
"""A literal yes and nothing else. The only thing that is a customer's consent."""

NONLITERAL: Final = "Strawberries work"
"""An agreeable sentence that is not a literal YES, and therefore authorises nothing."""

MASCARPONE_SPOILED: Final = "the mascarpone in the walk-in went off"
"""S03's exception: a real physical fact that no accepted order's recipe version reserves."""

STRAWBERRIES_SPOILED: Final = "the strawberries that came this morning are spoiled"
"""S04's second, independent physical fact: the substitute arrived and was unusable."""


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


async def answered_without_analysis(
    server: McpServer, intake: Intake, case_id: UUID, answer: str
) -> None:
    """The same answer, stopped at the boundary intake itself ends at.

    A resolved intake enqueues the impact analysis, and :func:`answered` carries the case
    straight through it. One scenario needs the instant in between -- both delivery lines
    attested and the six kilos posted, before anything has been concluded from them -- because
    that is where its second physical fact belongs.
    """
    async with server.session() as session:
        await session.call_tool("clarify", {"case_id": str(case_id), "answer": answer})
    await intake.drain_intake(case_id)


async def confirmed(server: McpServer, intake: Intake, case_id: UUID) -> None:
    """The plan the surface offered, quoted back to it as the worker's explicit yes."""
    async with server.session() as session:
        offered = body(await session.call_tool("status", {"case_id": str(case_id)}))
        assert offered["awaiting_confirmation"] is True, offered
        await session.call_tool(
            "confirm", {"case_id": str(case_id), "plan_id": str(offered["plan_id"])}
        )


async def settle(
    intake: Intake, wired: Boundary, *, rounds: int = 4, worker: Worker | None = None
) -> None:
    """Run the worker, carry the order system's echo across, and let the workflow finish.

    ``worker`` is named only where the scenario is *about* which process did the work -- a crash
    and a restart both turn on a second worker with a different boot identity picking up durable
    state the first one left behind.
    """
    runner = worker or worker_for(intake, wired)
    for _ in range(rounds):
        await wired.deliver_webhooks()
        await intake.make_work_due()
        await intake.drain(worker=runner, limit=40)


async def ask_for(intake: Intake, case_id: UUID, order: str) -> Any:
    """The most recent approval request this case sent about one order.

    The most recent rather than the only one, because a plan that goes stale after a customer
    has already answered asks again, and the second request is the one the rest of that
    scenario is about.
    """
    track = await intake.track(case_id, ORDERS[order]["promise"])
    assert track is not None, f"{order} has no track in this case"
    sent = [row for row in await intake.requests() if row.track_id == track.id]
    assert sent, f"{order}'s customer was never asked, so there is nothing to answer"
    return sent[-1]


OPEN_ASK_STATES: Final = ("SENT", "CONFIRMATION_PENDING")
"""An approval request nobody has answered yet, and can therefore still be let expire."""


async def expire_open_ask(intake: Intake, case_id: UUID, order: str) -> bool:
    """Let the deadline pass on this order's open approval request, if one is open.

    Two scenarios stipulate an ask that is never answered and expires at its deadline, and one
    of them reaches that fact only if a fresh ask was sent after a re-plan. So this performs the
    fact on whatever is genuinely open and says whether there was anything to perform it on. An
    ask that does not exist cannot be made to expire, and reaching for a superseded or already
    answered one instead would be performing a different scenario quietly.

    Deterministic where sleeping is not: the deadline is compared against the database's own
    clock, so moving the row backwards is exactly equivalent to the window having closed.
    """
    track = await intake.track(case_id, ORDERS[order]["promise"])
    assert track is not None, f"{order} has no track in this case"
    open_now = [
        row
        for row in await intake.requests()
        if row.track_id == track.id and row.state in OPEN_ASK_STATES
    ]
    for row in open_now:
        await intake.close_window(row.id)
    return bool(open_now)


async def customer_consents(intake: Intake, wired: Boundary, case_id: UUID) -> None:
    """Tomas replies ``YES`` on his own channel, and the workflow acts on it.

    The reply arrives on the inbound transport as a provider delivery bound to his own approval
    request, which is the only path a sentence has to becoming a decision. Nothing writes a
    decision row directly.
    """
    await intake.deliver_reply((await ask_for(intake, case_id, TOMAS)).id, CONSENT)
    await settle(intake, wired)


@asynccontextmanager
async def work_held(intake: Intake, case_id: UUID) -> AsyncIterator[None]:
    """Hold this case's runnable work still while a fact is made true around it.

    Several scenarios stipulate *when* something happened relative to this case's own progress:
    an order edited after a plan was confirmed and before its amendment reached the order
    system, a customer changing their order between a decision and the revalidation that would
    have acted on it. Both are races in a deployment and neither may be a race in a measurement,
    so the interleaving is made deliberate rather than waited for: every step this case has
    outstanding is pushed out of reach, the fact is performed and carried across by a worker
    that can therefore only do the mirror's work, and the steps are brought back.

    The hold is on steps, never on the boundary. Webhooks still arrive, the inbox is still
    processed and the mirror still moves -- which is exactly the ordering being stipulated.
    """
    held = [row.id for row in await intake.outstanding(case_id)]
    for step_id in held:
        await intake.defer(step_id)
    try:
        yield
    finally:
        for step_id in held:
            await intake.release(step_id)


async def external_quantity_edit(
    intake: Intake, wired: Boundary, *, order: str, quantity: int, case_id: UUID
) -> None:
    """A customer resizes their own order, in the order system's own screen, mid-case.

    Through that system's HTTP surface and its signed webhook, exactly as
    :func:`external_edit` carries an item change. What is different is only the timing: this
    one happens while a case is open, which is why it is performed inside :func:`work_held`.
    """
    async with work_held(intake, case_id):
        await wired.operator_changes_quantity(order=order, quantity=quantity)
        await wired.deliver_webhooks()
        await intake.drain(worker=worker_for(intake, wired), limit=20)


def newly_authored(mirrored_at: Any) -> tuple[TableRows, ...]:
    """The rows the engine fixture's own Charlotte variant adds, and nothing else.

    S05 stipulates one authoring change made in advance: a strawberry Charlotte version and its
    substitution policy entry. That change already exists in the frozen fixture module as
    :func:`hollow_oak.with_charlotte_variant`, so it is taken from there and projected with the
    deployment's own projector -- which means not one column of it is typed here, and the day
    the fixture moves, this moves with it.
    """
    base = hollow_oak.hollow_oak(mirrored_at)
    extended = hollow_oak.with_charlotte_variant(base)

    def key(row: Any) -> str:
        return json.dumps(dict(row), sort_keys=True, default=str)

    before = {
        table.table: {key(row) for row in table.rows}
        for table in project(base, mirrored_at=mirrored_at)
    }
    return tuple(
        TableRows(
            table=table.table,
            rows=tuple(row for row in table.rows if key(row) not in before[table.table]),
        )
        for table in project(extended, mirrored_at=mirrored_at)
    )


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


# ---------------------------------------------- S01: one ingredient of one delivery did not come


async def test_s01_single_ingredient_canonical(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """The canonical case, and the only scenario that reaches all four authority outcomes.

    The hardest checkpoint is ``CONSENT_SETTLED``: Tomas's amendment appears there and nowhere
    else, which is the whole of "an approval is authority and not application". A system that
    applied his change on the strength of the plan rather than of his reply would produce the
    same ``SETTLED`` state through a different history, and the cumulative multiset at the
    checkpoint before his answer is what tells the two apart.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S01") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
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

    await scored("S01", drive)


# ------------------------------------------- S03: a real physical exception that threatens nobody


async def test_s03_no_dependent_promises(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """The mascarpone really went off, and not one promise in the book reserves any.

    Two checkpoints, no clarification, no confirmation and no effect anywhere. The hardest one
    is ``PLANNED``, and what makes it hard is that the right answer is a case rather than
    silence: the fact is authoritative and is recorded, six promises are decided about, and all
    six are decided to be untouched. A system that opened no case would leave the same empty
    effect multiset behind and be wrong, and a system that held a task just in case would leave
    a different one.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S03") == ("PLANNED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical, MASCARPONE_SPOILED)
        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S03", drive)


# ------------------------------------------------ S04: the substitute arrived and was unusable


async def test_s04_substitute_unavailable(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """The strawberries came, and were spoiled. The same partition as S02 by a different route.

    The hardest checkpoint is ``PLANNED``, because it has to be reached through *two* physical
    facts rather than one, in an order that matters: the delivery's strawberry line is attested
    received and its six kilos posted, and only then is the second, independent fact attested --
    that what arrived is unusable. Reaching the same four blocked promises by telling the system
    the strawberries never came would be the conflation the manifest forbids, and it would pass
    this scenario while proving nothing it claims.

    One divergence from the stipulated facts is disclosed rather than hidden. The manifest says
    the two kilos already on hand stay usable and only the delivered six are lost. The
    deterministic interpreter has no way to attest a partial loss with a number -- an unqualified
    spoilage is all of it, and a qualified one without a quantity stops and asks a human -- so
    the attestation performed here writes off the whole strawberry stock. It cannot reach any
    label in this scenario: both candidate substitutions need more than the two kilos the
    manifest leaves standing, so the promise is blocked on substitute stock at either figure.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S04") == ("PLANNED", "CONFIRMED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered_without_analysis(chain, physical, case_id, RASPBERRY_ONLY)

        async with work_held(physical, case_id):
            spoiled = await reported(chain, physical, STRAWBERRIES_SPOILED)
            await settle(physical, wired)
            await quiescent(physical, spoiled)
        assert await physical.on_hand(STRAWBERRIES) == 0, "the substitute is still usable"

        await settle(physical, wired)
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

    await scored("S04", drive)


# ------------------------------- S05: a recovery exists, is in stock, and the customer forbade it


async def test_s05_constraint_blocks_substitution(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """A strawberry Charlotte now exists and there is enough of everything to make it.

    The hardest checkpoint is ``CONFIRMED``, and specifically the wedding order's two lines in
    it: an escalation and a held task, with no message and no amendment. S01 blocks that order
    for two independent reasons at once; this scenario authors away one of them, so the only
    remaining reason not to make the cake is the constraint its customer recorded. If the engine
    were quietly blocking on the missing variant rather than on the constraint, this is where it
    would show, because the variant is no longer missing.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S05") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        await physical.author(newly_authored(await physical.fixture_anchor()))
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

    await scored("S05", drive)


# ------------------------------------------ S06: the customer said yes, then changed the order


async def test_s06_stale_approved_order_version(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """Tomas approves a change to one cake, and then orders two.

    The hardest checkpoint is ``CONSENT_SETTLED``, where the declared count for his amendment is
    zero. The decision is real, is kept, and authorises nothing, because it was given about an
    order that has since moved. A fresh ask goes out instead -- one more message, no write --
    and the difference between that and an amendment is the whole scenario.

    The edit is made deliberate rather than raced for: his order is changed while this case's own
    work is held still, so "between the YES and the revalidation" is a fact about the sequence
    rather than about which of two workers happened to win.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S06") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)
        await settle(physical, wired)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        await physical.deliver_reply((await ask_for(physical, case_id, TOMAS)).id, CONSENT)
        await physical.drain_until_decided(worker=worker_for(physical, wired))
        await external_quantity_edit(
            physical, wired, order=TOMAS_ORDER, quantity=2, case_id=case_id
        )
        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        await expire_open_ask(physical, case_id, TOMAS)
        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S06", drive)


# ------------------------------------- S07: the customer said yes, then the substitute was gone


async def test_s07_stale_approved_stock_state(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """Tomas approves a strawberry crown the kitchen can no longer make.

    The hardest checkpoint is ``CONSENT_SETTLED``, and it is the one place in the whole manifest
    where a partition legitimately moves: his promise goes from needing his permission to
    needing its owner, because the re-plan against the world as it now stands finds no valid
    option at all. Asking him again -- which is right in S06 and would be wrong here -- would
    show as a message this checkpoint does not declare.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S07") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)
        await settle(physical, wired)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        await physical.deliver_reply((await ask_for(physical, case_id, TOMAS)).id, CONSENT)
        await physical.drain_until_decided(worker=worker_for(physical, wired))
        await physical.consume_stock(STRAWBERRIES, "-5.6")
        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S07", drive)


# ------------------------------------------------------------- S08: a yes from the wrong person


async def test_s08_foreign_sender(chain: McpServer, wired: Boundary, physical: Intake) -> None:
    """A literal YES arrives about Tomas's cake, from Ahmed's channel.

    The hardest checkpoint is ``CONSENT_SETTLED``, where the partition has not moved at all and
    every count is the one it was. The word is literal and the request is open, and neither of
    those makes the sender its customer. Ahmed's own order is the other half of it: a message
    arriving on his channel is not an instruction about his cake, and his zero at every
    checkpoint is as much the point as the refusal is.

    The foreign sender is an explicit operator action rather than a misdirected fixture: the
    reply is put on the inbound transport carrying Ahmed's channel as its sender, which is the
    one thing about it that differs from the reply S01 sends.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S08") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)
        await settle(physical, wired)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        ask = await ask_for(physical, case_id, TOMAS)
        assert AHMED_CHANNEL != TOMAS_CHANNEL, "the foreign sender is not foreign"
        await physical.deliver_reply(ask.id, CONSENT, sender=AHMED_CHANNEL)
        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        assert await expire_open_ask(physical, case_id, TOMAS), "his request was not left open"
        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S08", drive)


# ---------------------------------------------------------------------- S09: strawberries work


async def test_s09_nonliteral_apparent_assent(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """An agreeable sentence, and then the literal word that actually authorises the change.

    The hardest checkpoint is ``CONSENT_SETTLED``: one message and no amendment. "Strawberries
    work" decides nothing and earns exactly one confirmation prompt carrying the literal
    instruction. The outcome is the same for an approve-shaped reading, a decline-shaped one, an
    unclear one, a malformed model response and no model call at all, because nothing reads it
    -- and the amendment that arrives at ``SETTLED`` is authorised by the YES that followed.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S09") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)
        await settle(physical, wired)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        await physical.deliver_reply((await ask_for(physical, case_id, TOMAS)).id, NONLITERAL)
        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        await physical.deliver_reply((await ask_for(physical, case_id, TOMAS)).id, CONSENT)
        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S09", drive)


# ------------------------------------------------------------- S10: the same yes, twice over


async def test_s10_replayed_approval_webhook(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """One customer, one answer, one decision, one amendment -- and two deliveries.

    The partition is identical to S01 at every checkpoint, so the whole content of this scenario
    is the count, and ``CONSENT_SETTLED`` is where it lands: exactly one amendment and exactly
    one reservation change for an order whose approval arrived twice. Two would fail it as
    surely as none.

    The replay is an explicit operator action: the same reply is put on the transport a second
    time under the provider message identity the first one carried, which is what a provider
    retrying a delivery does and is the only thing this scenario changes.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S10") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)
        await settle(physical, wired)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        ask = await ask_for(physical, case_id, TOMAS)
        delivery = await physical.deliver_reply(ask.id, CONSENT)
        await physical.deliver_reply(ask.id, CONSENT, event_id=delivery)
        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S10", drive)


# ---------------------------------------- S13: the customer edited the order the plan was about


async def test_s13_related_external_edit_after_exception(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """Priya doubles her order after the plan is confirmed and before its amendment is sent.

    The hardest checkpoint is ``CONFIRMED``, where her declared amendment count is zero and her
    track is on the owner's desk instead. An automatic recovery has no customer waiting on it,
    which makes it the easiest place in the system to quietly claim a success: the plan was
    authorised, the write was refused, and the honest outcome is the escalation rather than a
    cake nobody planned for. Her classification does not move -- what the case decided about her
    promise was right, and what failed was the write.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S13") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)
        await external_quantity_edit(
            physical, wired, order=PRIYA_ORDER, quantity=2, case_id=case_id
        )
        await settle(physical, wired)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        await customer_consents(physical, wired, case_id)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S13", drive)


# --------------------------------- S14: the cafe changed a standing order in the middle of it all


async def test_s14_unrelated_external_edit_after_exception(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """A busy order book, and an untouched order that stays untouched through all of it.

    Byte for byte S01 in partitions and in incident-caused effects, which is the claim: the
    cafe's amendment is real, is recorded in the order system, moved that order's version and
    really did change its reservations -- and none of it is an effect of this incident, because
    the cafe commanded it. The hardest checkpoint is ``SETTLED``, where the cafe's order has to
    carry five zeros while its reservation rows demonstrably differ from the ones the incident
    opened with. A census that read the window and stopped there would report a false positive
    exactly here, which is why the test asserts the rows really moved before asking for the
    count.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S14") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await external_quantity_edit(
            physical, wired, order=CAFE_ORDER, quantity=30, case_id=case_id
        )
        line = ORDERS[CAFE]["line"]
        moved = await reservations_by_line(physical)
        assert moved[line] != since.reservations[line], "the cafe's own edit changed nothing"

        await confirmed(chain, physical, case_id)
        await settle(physical, wired)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        await customer_consents(physical, wired, case_id)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        await settle(physical, wired)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S14", drive)


# ------------------------------------------ S15: the order system said yes and the worker died


async def test_s15_crash_after_external_acceptance(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """The amendment is applied, and the process dies before anybody writes that down.

    The hardest checkpoint is ``CONFIRMED``, where the declared count is one: one amendment, one
    reservation change, one recovery. The dangerous failure here is a second cake rather than a
    lost one, and two would fail this scenario as surely as zero would. The replacement worker
    retries under the same derived idempotency key, and the order system answers out of its own
    idempotency ledger rather than acting again.

    The death is an explicit operator action at a named persistence boundary, not a timing
    accident: ``crash.AFTER_EXTERNAL_SUCCESS`` is armed with a guard that fires only once the
    order system's own event count shows Priya's amendment applied, so the process stops inside
    the uncertain window rather than on whichever effect happened to go first.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S15") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)

        def die_once_the_order_has_moved() -> None:
            if wired.simulator.event_count(PRIYA_ORDER) == 1:
                raise crash.WorkerDied(crash.AFTER_EXTERNAL_SUCCESS)

        before = physical.worker(
            identity="worker-before-the-crash",
            adapter=wired.adapter,
            fetch=wired.client.fetch_order,
        )
        with (
            crash.arm(crash.AFTER_EXTERNAL_SUCCESS, die_once_the_order_has_moved),
            pytest.raises(crash.WorkerDied),
        ):
            await settle(physical, wired, worker=before)

        assert wired.external_order(PRIYA_ORDER).version == 2, "the order system did not apply it"
        stranded = next(
            row for row in await physical.effects() if row.kind == recovery.EFFECT_ORDER_AMEND
        )
        await physical.expire_effect_lease(stranded.id)

        after = physical.worker(
            identity="worker-after-the-crash",
            adapter=wired.adapter,
            fetch=wired.client.fetch_order,
        )
        await settle(physical, wired, worker=after)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        await physical.deliver_reply((await ask_for(physical, case_id, TOMAS)).id, CONSENT)
        await settle(physical, wired, worker=after)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        await settle(physical, wired, worker=after)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)
        return observations

    await scored("S15", drive)


# ----------------------------------- S16: the worker restarted while the customer was thinking


async def test_s16_restart_while_waiting_for_consent(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """One process stops, another starts, and Tomas never learns that anything happened.

    Identical to S01 in every partition and every effect, which is the claim: the wait is durable
    state rather than a process holding a socket. The hardest checkpoint is ``CONSENT_SETTLED``,
    because it is the one a restart could plausibly break -- an approval accepted by a worker
    that never sent it, against a plan it did not make, on a deadline it did not set. The
    scenario passes only if the restart is invisible in the result and visible in the worker
    identity that produced it, so both are asserted.

    The restart is an explicit operator action: the first worker is named, is used for everything
    up to the confirmation, and is then dropped; a second worker with a different boot identity
    is constructed and does everything after it.
    """

    async def drive() -> dict[str, Observation]:
        assert declared("S16") == ("PLANNED", "CONFIRMED", "CONSENT_SETTLED", "SETTLED")
        since = await baseline_of(physical, wired)
        observations: dict[str, Observation] = {}

        first = physical.worker(
            identity="worker-before-the-restart",
            adapter=wired.adapter,
            fetch=wired.client.fetch_order,
        )
        case_id = await reported(chain, physical)
        await answered(chain, physical, case_id, RASPBERRY_ONLY)
        await quiescent(physical, case_id)
        observations["PLANNED"] = await observe(physical, case_id=case_id, since=since)

        await confirmed(chain, physical, case_id)
        await settle(physical, wired, worker=first)
        observations["CONFIRMED"] = await observe(physical, case_id=case_id, since=since)

        # The restart itself. Nothing else moves: no fixture, order, stock level or constraint.
        second = physical.worker(
            identity="worker-after-the-restart",
            adapter=wired.adapter,
            fetch=wired.client.fetch_order,
        )
        assert first.identity.value != second.identity.value

        await physical.deliver_reply((await ask_for(physical, case_id, TOMAS)).id, CONSENT)
        await settle(physical, wired, worker=second)
        observations["CONSENT_SETTLED"] = await observe(physical, case_id=case_id, since=since)

        await settle(physical, wired, worker=second)
        await quiescent(physical, case_id)
        observations["SETTLED"] = await observe(physical, case_id=case_id, since=since)

        actors = {row.actor_id for row in await physical.audits(case_id)}
        assert second.identity.value in actors, "the replacement worker did none of the work"
        return observations

    await scored("S16", drive)
