"""The confirmed canonical case, carried to real outcomes, said in truthful words.

``test_orchestrated_conversation.py`` stops where P5.3 stopped: a worker has confirmed a plan
and nothing has been carried out. This file starts there and finishes the story, and every
sentence in it is checked against a durable condition rather than against an intention.

Nothing here inserts a row and no domain command is called to move the case along. The
conversation happens over the real MCP transport, the recoveries happen in a real worker
process, the order amendment is a real HTTP request the External Order System parses, and the
echo is a real signed webhook PromisePatch verifies. The only direct database access is the
reads that check what all of that left behind.

The negative assertions carry the weight. Three of the product's four truthfulness rules are
about words that must **not** appear -- "changed" before the order system has said so, "asked"
before the provider acknowledged delivery, and any operational effect at all against a promise
this incident never reached -- and a suite that only checked the happy ending would pass on a
system that said all three too early.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from _intake_support import BAKER, CANONICAL_REPORT, RASPBERRY_ONLY, Intake
from _intake_support import physical as physical
from _mcp_support import SERVICE_TOKEN, McpServer, mcp_over_http, serve
from _order_system_support import Boundary, boundary
from mcp.types import CallToolResult

from promise_graph.examples import hollow_oak as ho
from promisepatch.config import Settings
from promisepatch.domain import analysis, recovery, status_view
from promisepatch.main import create_app
from promisepatch.worker import Worker

pytestmark = pytest.mark.integration

AUTO, ASK = ho.PROMISE_A, ho.PROMISE_B
BLOCKED = (ho.PROMISE_C, ho.PROMISE_D)
UNTOUCHED = (ho.PROMISE_E, ho.PROMISE_F)
UNTOUCHED_LINES = (ho.LINE_E, ho.LINE_F)
BLOCKED_LINES = (ho.LINE_C, ho.LINE_D)
"""The canonical case's four outcomes, named so a fixture change fails loudly rather than
quietly turning this into a test of three promises and a coincidence."""


def api_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "internal_service_token": SERVICE_TOKEN,
        "surface_worker_id": BAKER,
    }
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


# ------------------------------------------------------------------------------ driving


def worker_for(intake: Intake, wired: Boundary) -> Worker:
    """A worker wired exactly as ``promisepatch.worker.run`` wires one for a deployment."""
    return intake.worker(adapter=wired.adapter, fetch=wired.client.fetch_order)


def body(result: CallToolResult) -> dict[str, Any]:
    assert result.structured_content is not None, result
    assert not result.is_error, result
    return dict(result.structured_content)


async def confirmed_over_the_wire(server: McpServer, intake: Intake) -> UUID:
    """The canonical conversation, every turn a real tool call, ending in an explicit yes.

    Four tools and no shortcuts: the case id comes back from ``report``, the plan identity
    comes back from ``status``, and the confirmation quotes that identity. Nothing in this
    helper knows a table exists.
    """
    async with server.session() as session:
        opened = body(await session.call_tool("report", {"text": CANONICAL_REPORT}))
        case_id = UUID(opened["case_id"])

        # The interpreter runs and finds the sentence ambiguous; the worker answers it.
        await intake.drain_intake(case_id)
        await session.call_tool("clarify", {"case_id": str(case_id), "answer": RASPBERRY_ONLY})
        await intake.drain()

        offered = body(await session.call_tool("status", {"case_id": str(case_id)}))
        assert offered["awaiting_confirmation"] is True
        assert offered["plan_id"]
        await session.call_tool("confirm", {"case_id": str(case_id), "plan_id": offered["plan_id"]})
    return case_id


async def settle(intake: Intake, wired: Boundary, *, rounds: int = 4) -> None:
    """Run the worker, carry the order system's echo across, and let the workflow finish."""
    for _ in range(rounds):
        await wired.deliver_webhooks()
        await intake.make_work_due()
        await intake.drain(worker=worker_for(intake, wired), limit=40)


async def spoken(server: McpServer, case_id: UUID) -> str:
    """What a worker asking for the status is actually read, over the real transport."""
    async with server.session() as session:
        return str(body(await session.call_tool("status", {"case_id": str(case_id)}))["speech"])


async def promises(intake: Intake, case_id: UUID) -> dict[str, status_view.PromiseView]:
    """The product's view of every promise in this case, keyed by promise."""
    status = await analysis.read_case_status(intake.database, case_id=case_id)
    return {item.promise_id: item for item in status_view.project(status).promises}


async def track_row(intake: Intake, case_id: UUID, promise_id: str) -> Any:
    row = await intake.track(case_id, promise_id)
    assert row is not None, promise_id
    return row


# ------------------------------------------------------- the confirmed case reaches real outcomes


async def test_a_confirmed_case_reaches_three_real_outcomes_and_leaves_two_promises_alone(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """One spoken exception, four tool calls, and four different truthful endings.

    This is the whole product in one test: the promise a standing preference covers is really
    changed in another system, the one that needs the customer is really asked, the two nothing
    can be done about are really on the owner's desk, and the two the incident never reached
    have nothing at all done to them.
    """
    case_id = await confirmed_over_the_wire(chain, physical)
    await settle(physical, wired)

    view = await promises(physical, case_id)
    assert view[AUTO].state is status_view.PromiseState.RECOVERED
    assert view[ASK].state is status_view.PromiseState.REQUESTED
    assert [view[promise].state for promise in BLOCKED] == [status_view.PromiseState.ESCALATED] * 2
    assert [view[promise].state for promise in UNTOUCHED] == [
        status_view.PromiseState.UNTOUCHED
    ] * 2

    # And the order system itself agrees, which is the only thing that makes "changed" true.
    assert wired.external_order("EXT-A").version > 1


async def test_the_automatic_recovery_says_changed_only_after_the_order_system_observed_it(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """The uncertain window, held open on purpose, and read out loud in the middle of it.

    Between the amendment being accepted and the order system's own event coming back, the
    honest answer is "changing the order now". A product that said "changed" on the
    acknowledgement would be right most of the time and wrong exactly when it mattered.
    """
    case_id = await confirmed_over_the_wire(chain, physical)
    # A worker cycle with no webhook delivery: the amendment goes out and nothing echoes back.
    await physical.drain(worker=worker_for(physical, wired), limit=40)

    mid_flight = (await promises(physical, case_id))[AUTO]
    assert mid_flight.state is status_view.PromiseState.APPLYING
    assert mid_flight.phrase == "changing the order now"
    assert ": changed" not in await spoken(chain, case_id)

    # The order system really did apply it -- this is a reporting boundary, not a lost effect.
    effects = [row.state for row in await physical.effects_for(UUID(mid_flight.track_id))]
    assert "DELIVERED" in effects

    await settle(physical, wired)
    assert (await promises(physical, case_id))[AUTO].state is status_view.PromiseState.RECOVERED
    assert ": changed" in await spoken(chain, case_id)


async def test_the_customer_is_said_to_be_asked_only_after_the_provider_acknowledged_it(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """ "Asked Tomas" is a claim about delivery, so it waits for the provider's receipt.

    The approval request is held before it is dispatched, which is the state a queued or
    retrying message leaves the track in. The product's word for it there is "planned", and the
    request carries no provider reference to justify anything stronger.
    """
    case_id = await confirmed_over_the_wire(chain, physical)
    await physical.defer_approvals(case_id)
    await physical.drain(worker=worker_for(physical, wired), limit=40)

    undelivered = (await promises(physical, case_id))[ASK]
    assert undelivered.state is not status_view.PromiseState.REQUESTED
    assert ": asked" not in await spoken(chain, case_id)

    await physical.release_approvals(case_id)
    await settle(physical, wired)

    delivered = (await promises(physical, case_id))[ASK]
    assert delivered.state is status_view.PromiseState.REQUESTED
    assert delivered.phrase == "asked"
    request = await physical.request_for(UUID(delivered.track_id))
    assert request.provider_ref, "the receipt is what makes the word true"
    assert ": asked" in await spoken(chain, case_id)


async def test_the_blocked_promises_stay_an_explicit_owner_action(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """Nothing automatic happens to a blocked promise, and the product says whose it is.

    The two blocked promises are the ones no pre-authored variant can recover. They reach the
    owner with a reason and a next action, they cause no outbound effect of any kind, and the
    case as a whole is flagged as needing a person.
    """
    case_id = await confirmed_over_the_wire(chain, physical)
    await settle(physical, wired)

    view = await promises(physical, case_id)
    for promise_id in BLOCKED:
        blocked = view[promise_id]
        assert blocked.authority is status_view.Authority.OWNER
        assert blocked.owner is status_view.ActionOwner.OWNER
        assert "owner" in blocked.next_action.lower()
        assert blocked.reason, "a blocked promise without a reason is a dead end"
        assert not await physical.effects_for(UUID(blocked.track_id)), "no effect was ever raised"
        assert (await track_row(physical, case_id, promise_id)).state == recovery.TRACK_ESCALATED

    status = await analysis.read_case_status(physical.database, case_id=case_id)
    assert status.needs_owner_attention is True
    assert "Needs the owner:" in await spoken(chain, case_id)


async def test_the_untouched_promises_carry_no_incident_caused_operational_effect(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """0 of 2, counted the way the contract counts it: by case, command and effect identity.

    An untouched promise does receive an ``UNAFFECTED`` track row -- the contract says so, and
    says the product must not pretend otherwise. What it must not receive is an amendment, a
    message, a reservation change, a production hold or an escalation, and none of those exist
    for either of these two after a case that changed one order and asked one customer.
    """
    before = {line: await wired.mirrored_version_of(line) for line in UNTOUCHED_LINES}
    case_id = await confirmed_over_the_wire(chain, physical)
    await settle(physical, wired)

    view = await promises(physical, case_id)
    for promise_id in UNTOUCHED:
        untouched = view[promise_id]
        assert untouched.state is status_view.PromiseState.UNTOUCHED
        assert untouched.owner is status_view.ActionOwner.NOBODY
        assert not await physical.effects_for(UUID(untouched.track_id))
        assert await physical.request_for(UUID(untouched.track_id)) is None
        assert (await track_row(physical, case_id, promise_id)).state == "UNAFFECTED"

    # The order system's own book, for the orders this case never had business with.
    assert wired.external_order("EXT-E").version == 1
    assert wired.external_order("EXT-F").version == 1
    assert wired.simulator.event_count("EXT-E") == 0
    assert wired.simulator.event_count("EXT-F") == 0
    after = {line: await wired.mirrored_version_of(line) for line in UNTOUCHED_LINES}
    assert after == before, "the mirror still pins the versions these two were promised"

    # A production hold is the fourth kind of effect, and this case really does raise two of
    # them -- on the blocked promises, whose work must stop until the owner decides. The claim
    # is that they are attributed to those two and to nothing else.
    held = {line for line, (_, held_by) in (await physical.tasks()).items() if held_by == case_id}
    assert held == {f"task-{line}" for line in BLOCKED_LINES}, held


async def test_a_second_status_call_after_the_work_finished_describes_the_same_case(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """Two independent connections, one durable case, one answer.

    Each ``session()`` is a fresh handshake over a new transport with nothing carried over but
    a case id, so this is the reconnect claim stated as a test: what the second connection
    reads is what the database holds, not what the first one was remembering.
    """
    case_id = await confirmed_over_the_wire(chain, physical)
    await settle(physical, wired)

    assert await spoken(chain, case_id) == await spoken(chain, case_id)


async def test_a_refused_amendment_never_reads_as_a_changed_order(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """A recovery the order system rejects escalates. It does not quietly report success.

    The plan is aimed at a version the order system has already moved past, which is the
    ordinary way an external system refuses one. The promise ends on the owner's desk, and the
    word "changed" is never said about it.
    """
    case_id = await confirmed_over_the_wire(chain, physical)
    # The order system moves EXT-A on under its own authority, after this plan was made against
    # it and before PromisePatch has heard about it. The amendment goes out expecting a version
    # that is no longer current, and is refused.
    await wired.operator_changes(order="EXT-A", item="rv-raspberry-charlotte-1")
    await physical.drain(worker=worker_for(physical, wired), limit=40)
    await settle(physical, wired)

    refused = (await promises(physical, case_id))[AUTO]
    assert refused.state is status_view.PromiseState.ESCALATED
    assert refused.phrase != "changed"
    assert ": changed" not in await spoken(chain, case_id)
    assert wired.external_order("EXT-A").lines[0].external_item_id == "rv-raspberry-charlotte-1"


async def test_nothing_is_carried_out_until_the_worker_confirms(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """A planned case, run through as many worker cycles as it will take, does nothing at all.

    The confirmation is the gate, so this drains everything the workflow has to offer without
    one. Every promise stays "planned", no effect row exists, and the order system's book is
    untouched -- which is what makes an ``AUTO_RECOVERABLE`` classification a permission rather
    than an act.
    """
    async with chain.session() as session:
        opened = body(await session.call_tool("report", {"text": CANONICAL_REPORT}))
        case_id = UUID(opened["case_id"])
        await physical.drain_intake(case_id)
        await session.call_tool("clarify", {"case_id": str(case_id), "answer": RASPBERRY_ONLY})

    await settle(physical, wired)

    view = await promises(physical, case_id)
    assert view[AUTO].state is status_view.PromiseState.PLANNED
    assert view[ASK].state is status_view.PromiseState.PLANNED
    assert not await physical.effects()
    assert wired.external_order("EXT-A").version == 1
    assert "Nothing has been done yet." in await spoken(chain, case_id)


async def test_a_confirmation_quoting_a_plan_nobody_offered_carries_out_nothing(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """The fabricated identity, over the real transport, followed by every worker cycle.

    The refusal is P5.2's and is already proven there; what this adds is the consequence a
    recovery slice has to establish -- that a refused confirmation leaves a case with nothing
    to execute, so no amount of subsequent worker activity turns it into an effect.
    """
    async with chain.session() as session:
        opened = body(await session.call_tool("report", {"text": CANONICAL_REPORT}))
        case_id = UUID(opened["case_id"])
        await physical.drain_intake(case_id)
        await session.call_tool("clarify", {"case_id": str(case_id), "answer": RASPBERRY_ONLY})
        await physical.drain()
        refused = await session.call_tool(
            "confirm", {"case_id": str(case_id), "plan_id": uuid4().hex}
        )

    assert refused.is_error or (refused.structured_content or {}).get("ok") is False

    await settle(physical, wired)
    assert not await physical.effects()
    assert wired.external_order("EXT-A").version == 1
    assert (await physical.case(case_id)).state == "PLANNED"
