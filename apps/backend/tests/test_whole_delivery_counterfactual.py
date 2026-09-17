"""The whole-delivery branch, taken after a customer had already changed her own order.

G5 asks for two things this file puts in one place. The canonical demo begins with an external
change to ``EXT-D`` that PromisePatch learns about before anybody speaks, so the outcome is
contingent on current reality rather than on a prepared table; and the whole-delivery answer to
the clarification must **change substitute feasibility**, not merely widen the affected set.
Taken together they are one scenario: Lena moves her cake out of the raspberry world, and then
the whole Valley Produce delivery fails rather than only half of it.

Every expected label here is loaded from the frozen manifest,
``docs/effect-sets/scenarios.v1.json``, whose published SHA is asserted before anything else
runs. Two of its sixteen scenarios cover the two halves:

* **S02** -- the whole delivery, in the unmodified world: nobody is auto-repairable, nobody is
  asked, ``ord-a`` to ``ord-d`` are all blocked, and ``ord-e``/``ord-f`` are untouched.
* **S11** -- Lena's external edit before the exception: ``ord-d`` leaves the affected set,
  because "her order no longer names a raspberry version", and her own amendment "is her command
  and is never an incident-caused effect".

The expectation for the composed scenario is S02's frozen labels with S11's frozen ``ord-d``
argument applied to them, and :func:`composed` performs exactly that move and nothing else. Both
premises are asserted against the manifest in their own test, so the composition is grounded in
two hand-labelled documents rather than in anything this suite observed.

Nothing here inserts a row or calls a domain command to move the case along. The external edit is
made through the order system's own HTTP surface, it crosses as a signed webhook, the
conversation is four real MCP tool calls, and the recovery runs in a real worker process. The
only direct database access is the reads that count what all of it left behind.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
import pytest_asyncio
from _effect_set_observation import (
    baseline_of,
    census,
    outbox_of,
    partition_of,
    reservations_by_line,
)
from _effect_sets import (
    PUBLISHED_SHA,
    Partition,
    case_universe,
    cumulative_effects_at,
    identity,
    orders,
    partition_at,
    refusals_at,
    scenario,
)
from _intake_support import BAKER, CANONICAL_REPORT, RASPBERRY_ONLY, WHOLE_DELIVERY, Intake
from _intake_support import physical as physical
from _mcp_support import SERVICE_TOKEN, McpServer, mcp_over_http, serve
from _order_system_support import LEMON_CURD, LENA_LINE, LENA_ORDER, Boundary, boundary
from mcp.types import CallToolResult

from promise_graph.model import Classification
from promisepatch.config import Settings
from promisepatch.domain import analysis, causal, recovery, status_view
from promisepatch.main import create_app
from promisepatch.worker import Worker

pytestmark = pytest.mark.integration

S02: Final = scenario("S02")
S11: Final = scenario("S11")
ORDERS: Final = orders()
UNIVERSE: Final = case_universe()

LENA: Final = "ord-d"
"""The order the customer edits before the incident, named once."""


# ------------------------------------------------------------------ the frozen expectation


def composed() -> dict[str, Any]:
    """S02's labels, with ``ord-d`` moved to untouched on S11's own frozen argument.

    One move, applied at every checkpoint: the order whose external edit removed it from the
    affected set is untouched, and it carries none of the effects S02 declares for it. Every
    other label -- ``ord-a`` and ``ord-b`` blocked on substitute stock rather than asked,
    ``ord-c`` blocked on its constraint, the escalations and the held tasks -- is S02's,
    unedited.
    """
    checkpoints = []
    for point in S02["checkpoints"]:
        partition = {name: list(members) for name, members in point["partition"].items()}
        for name in ("auto_repairable", "consent_required", "blocked"):
            partition[name] = [order for order in partition[name] if order != LENA]
        partition["untouched"] = sorted({*partition["untouched"], LENA})
        checkpoints.append(
            {
                **point,
                "partition": partition,
                "effects_added": [
                    effect for effect in point["effects_added"] if effect["order"] != LENA
                ],
            }
        )
    return {**S02, "id": "S02+S11", "checkpoints": checkpoints}


EXPECTED: Final = composed()
CHECKPOINTS: Final = tuple(point["name"] for point in EXPECTED["checkpoints"])


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


async def lena_changes_her_own_cake(intake: Intake, wired: Boundary) -> None:
    """The customer's edit, in the other application, carried across and applied.

    Through the order system's own HTTP surface and its own webhook, so PromisePatch finds out
    the way it finds out about every external change. The worker that applies the mirror update
    is the same worker every other step runs in.
    """
    await wired.operator_changes(order=LENA_ORDER, item=LEMON_CURD)
    await wired.deliver_webhooks()
    await intake.drain(worker=worker_for(intake, wired), limit=20)


async def settle(intake: Intake, wired: Boundary, *, rounds: int = 4) -> None:
    """Run the worker, carry the order system's echo across, and let the workflow finish."""
    for _ in range(rounds):
        await wired.deliver_webhooks()
        await intake.make_work_due()
        await intake.drain(worker=worker_for(intake, wired), limit=40)


# ----------------------------------------------------------------- reading what happened
#
# The partitions, the effect census and the baseline they are attributed against live in
# `_effect_set_observation`, so the suite counts an effect in exactly one place.


async def spoken(server: McpServer, case_id: UUID) -> str:
    """What a worker asking for the status is actually read, over the real transport."""
    async with server.session() as session:
        return str(body(await session.call_tool("status", {"case_id": str(case_id)}))["speech"])


# ------------------------------------------------------------------ driving the two branches


async def reported(server: McpServer, intake: Intake) -> UUID:
    """The worker's sentence, over the real transport, interpreted and found ambiguous."""
    async with server.session() as session:
        opened = body(await session.call_tool("report", {"text": CANONICAL_REPORT}))
        case_id = UUID(opened["case_id"])
    await intake.drain_intake(case_id)
    return case_id


async def answered(server: McpServer, intake: Intake, case_id: UUID, answer: str) -> None:
    async with server.session() as session:
        await session.call_tool("clarify", {"case_id": str(case_id), "answer": answer})
    await intake.drain()


async def confirmed(server: McpServer, intake: Intake, case_id: UUID) -> str:
    """The plan the surface offered, approved by the worker, and then carried out.

    The approval is not a tool call and cannot be one: a conversation spends a worker's yes and
    can never write one, so it is recorded where this system authenticated them.
    """
    async with server.session() as session:
        offered = body(await session.call_tool("status", {"case_id": str(case_id)}))
    assert offered["awaiting_confirmation"] is True, offered
    plan_id = str(offered["plan_id"])
    await intake.approve(case_id, plan_id=plan_id)
    async with server.session() as session:
        await session.call_tool("confirm", {"case_id": str(case_id), "plan_id": plan_id})
    return plan_id


async def planned_whole_delivery(server: McpServer, intake: Intake, wired: Boundary) -> UUID:
    """Lena's edit, then the report, then the whole-delivery answer. Quiescent at ``PLANNED``."""
    await lena_changes_her_own_cake(intake, wired)
    case_id = await reported(server, intake)
    await answered(server, intake, case_id, WHOLE_DELIVERY)
    return case_id


# ------------------------------------------------------------- the manifest is what it was


def test_the_frozen_manifest_is_still_the_document_whose_hash_was_published() -> None:
    """Recomputed from the bytes on disk, before a single expectation is read out of it."""
    assert identity() == PUBLISHED_SHA


def test_the_composition_rests_on_two_frozen_labels_and_changes_nothing_else() -> None:
    """The two premises, asserted against the manifest rather than assumed.

    S02 is the whole delivery with Lena still on the raspberry version, so it blocks her. S11 is
    Lena's external edit before the exception, so it leaves her alone and attributes her own
    amendment to her. This scenario is the first with the second's argument about her applied,
    and the test states both halves, so a manifest edit that weakened either would fail here.
    """
    for checkpoint in (point["name"] for point in S02["checkpoints"]):
        assert LENA in partition_at(S02, checkpoint)["blocked"]
    for checkpoint in (point["name"] for point in S11["checkpoints"]):
        assert LENA in partition_at(S11, checkpoint)["untouched"]
        assert not [key for key in cumulative_effects_at(S11, checkpoint) if key[0] == LENA]

    # And the composition moved that one order and left every other label exactly as it was.
    for checkpoint in CHECKPOINTS:
        expected = partition_at(EXPECTED, checkpoint)
        frozen = partition_at(S02, checkpoint)
        assert expected["untouched"] == frozen["untouched"] | {LENA}
        assert expected["blocked"] == frozen["blocked"] - {LENA}
        assert expected["auto_repairable"] == frozen["auto_repairable"]
        assert expected["consent_required"] == frozen["consent_required"]
        assert set().union(*expected.values()) == set(UNIVERSE)
        assert [key for key in cumulative_effects_at(EXPECTED, checkpoint) if key[0] == LENA] == []


# --------------------------------------------------- the external edit lands first, and is seen


async def test_the_order_system_changes_lenas_order_before_anybody_reports_anything(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """Three observations in order: the order system moved, we had not, and then we had.

    The middle one is the boundary. If the two applications shared a table it would be
    impossible, and the newer version PromisePatch analyses later would be a fixture rather than
    something it was told.
    """
    assert await wired.mirrored_version_of(LENA_LINE) == ORDERS[LENA]["pinned_version"]

    await wired.operator_changes(order=LENA_ORDER, item=LEMON_CURD)
    assert wired.external_order(LENA_ORDER).version == 2
    assert await wired.mirrored_version_of(LENA_LINE) == ORDERS[LENA]["pinned_version"]

    await wired.deliver_webhooks()
    await physical.drain(worker=worker_for(physical, wired), limit=20)
    assert await wired.mirrored_version_of(LENA_LINE) == LEMON_CURD

    # Only now does anybody speak, and the case is opened against the newer version.
    case_id = await reported(chain, physical)
    assert (await physical.case(case_id)).state == "CLARIFYING"
    assert await wired.mirrored_version_of(LENA_LINE) == LEMON_CURD


# ----------------------------------------------------------- the partition, at every checkpoint


async def test_the_partition_matches_the_frozen_labels_at_every_declared_checkpoint(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """PLANNED, CONFIRMED and SETTLED, each read at quiescence and compared as whole sets.

    Exact set equality for all four partitions, which is the manifest's own pass rule. A missing,
    extra or misclassified order fails it. Each checkpoint is asserted to be quiescent first,
    because the manifest defines them that way: a scenario never depends on catching the system
    mid-step, so a partition read while work was still runnable would not be the one it names.
    """
    case_id = await planned_whole_delivery(chain, physical, wired)
    assert not await physical.outstanding(case_id)
    assert await partition_of(physical, case_id) == partition_at(EXPECTED, "PLANNED")

    await confirmed(chain, physical, case_id)
    await settle(physical, wired)
    assert not await physical.outstanding(case_id)
    assert await partition_of(physical, case_id) == partition_at(EXPECTED, "CONFIRMED")

    await settle(physical, wired)
    assert not await physical.outstanding(case_id)
    assert await partition_of(physical, case_id) == partition_at(EXPECTED, "SETTLED")

    # SETTLED, in the manifest's sense: not terminal, but every track that is not terminal is on
    # the owner's desk, and nothing automatic follows any of them.
    assert {track.state for track in await physical.tracks(case_id)} == {
        recovery.TRACK_ESCALATED,
        "UNAFFECTED",
    }


async def test_the_authority_outcomes_are_the_ones_those_labels_mean(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """A partition is a claim about authority, so the product has to say the same thing.

    Every blocked order is the owner's, with a reason and a next action; every untouched one is
    nobody's. That is what makes "nobody is asked here" a fact about the case rather than a
    description of an empty queue.
    """
    case_id = await planned_whole_delivery(chain, physical, wired)
    await confirmed(chain, physical, case_id)
    await settle(physical, wired)

    expected = partition_at(EXPECTED, "SETTLED")
    status = await analysis.read_case_status(physical.database, case_id=case_id)
    projected = status_view.project(status)
    view = {item.promise_id: item for item in projected.promises}

    assert projected.promise_count == len(UNIVERSE), "the denominator is the manifest's universe"

    for order in expected["blocked"]:
        blocked = view[ORDERS[order]["promise"]]
        assert blocked.state is status_view.PromiseState.ESCALATED
        assert blocked.authority is status_view.Authority.OWNER
        assert blocked.owner is status_view.ActionOwner.OWNER
        assert blocked.reason
        assert "owner" in blocked.next_action.lower()
    for order in expected["untouched"]:
        untouched = view[ORDERS[order]["promise"]]
        assert untouched.state is status_view.PromiseState.UNTOUCHED
        assert untouched.authority is status_view.Authority.NONE
        assert untouched.owner is status_view.ActionOwner.NOBODY

    tracks = {track.promise_id: track for track in status.tracks}
    for order in expected["blocked"]:
        reached = causal.chain_for(tracks[ORDERS[order]["promise"]], facts=status.node_facts)
        assert reached.present is True, f"{order} is blocked and has no path to show"
        assert reached.steps[-1].slot is causal.CausalSlot.PROMISE
    for order in expected["untouched"]:
        traversal = causal.chain_for(tracks[ORDERS[order]["promise"]], facts=status.node_facts)
        assert traversal.present is False, f"{order} is untouched and must carry no path"
        assert traversal.steps == ()
        assert traversal.absence_reason, "and the empty column says why it is empty"

    assert status.needs_owner_attention is True
    said = await spoken(chain, case_id)
    assert "Needs the owner:" in said
    assert ": changed" not in said
    assert ": asked" not in said


# --------------------------------------------------------------------- the effects, and the zeros


async def test_the_effects_match_the_frozen_cumulative_multiset_at_every_checkpoint(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """What was done, not only what was decided -- including every zero the manifest implies.

    The census is a whole mapping compared to a whole mapping, so an ``(order, kind)`` pair the
    manifest does not declare is required to be absent. An amendment, a message to Tomas or a
    reservation moved anywhere would fail this as surely as a missing escalation.
    """
    await lena_changes_her_own_cake(physical, wired)
    since = await baseline_of(physical, wired)

    case_id = await reported(chain, physical)
    await answered(chain, physical, case_id, WHOLE_DELIVERY)
    assert await census(physical, case_id=case_id, since=since) == cumulative_effects_at(
        EXPECTED, "PLANNED"
    )

    await confirmed(chain, physical, case_id)
    await settle(physical, wired)
    assert await census(physical, case_id=case_id, since=since) == cumulative_effects_at(
        EXPECTED, "CONFIRMED"
    )

    await settle(physical, wired)
    assert await census(physical, case_id=case_id, since=since) == cumulative_effects_at(
        EXPECTED, "SETTLED"
    )

    # The frozen refusals after the clarification are empty, and an empty refusal set is also a
    # claim: nothing was attempted and turned away. Nothing left the outbox to be refused, no
    # customer was asked, and no decision was recorded to be revalidated against a moved world.
    assert refusals_at(EXPECTED, "CONFIRMED") == refusals_at(EXPECTED, "SETTLED") == frozenset()
    assert not await outbox_of(physical, case_id)
    assert not await physical.requests()
    assert not await physical.decisions()

    # The order system's own book is the independent witness for the amendment zeros.
    assert {
        order["external_id"]: wired.external_order(order["external_id"]).version
        for order in ORDERS.values()
    } == since.external_versions


async def test_planning_declares_no_operational_effect_and_the_ambiguity_refuses_to_act(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """The manifest's ``clarification_required``, and the rule that planning has done nothing.

    An ambiguous sentence is answered with a question and nothing else: no amendment, no message,
    no hold, no escalation -- and the same is still true once the answer has produced a plan,
    because a plan is a proposal. The manifest asserts this for all sixteen scenarios; this is
    that assertion made physical for one of them.
    """
    await lena_changes_her_own_cake(physical, wired)
    since = await baseline_of(physical, wired)

    case_id = await reported(chain, physical)
    async with chain.session() as session:
        asked = body(await session.call_tool("status", {"case_id": str(case_id)}))
    assert asked["headline"] == "CLARIFYING"
    assert asked["question"] is not None
    assert asked["awaiting_confirmation"] is False
    assert asked["plan_id"] is None
    assert await census(physical, case_id=case_id, since=since) == {}
    assert "clarification_required" in refusals_at(EXPECTED, "PLANNED")

    await answered(chain, physical, case_id, WHOLE_DELIVERY)
    assert (await physical.case(case_id)).state == "PLANNED"
    assert await census(physical, case_id=case_id, since=since) == {}
    assert not await physical.effects()
    assert "Nothing has been done yet." in await spoken(chain, case_id)


# ------------------------------------------------------------------------------- attribution


async def test_lenas_own_amendment_is_never_counted_as_an_incident_caused_effect(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """S11's rule, made to fail loudly: her command is hers, and the incident did not cause it.

    Her edit really did move an order and really did move its reservations -- both are asserted
    here, so this is not a case of counting nothing because nothing happened. What makes it not
    an effect of this case is that it falls outside the window the case opens, and the census
    says so with her order carrying no pair of any kind.
    """
    before = await reservations_by_line(physical)
    await lena_changes_her_own_cake(physical, wired)
    since = await baseline_of(physical, wired)

    # Her edit is real: a version in the order system, an event on its wire, moved reservations.
    assert since.external_versions[LENA_ORDER] == 2
    assert since.external_events[LENA_ORDER] == 1
    assert since.reservations[LENA_LINE] != before[LENA_LINE]

    case_id = await reported(chain, physical)
    await answered(chain, physical, case_id, WHOLE_DELIVERY)
    await confirmed(chain, physical, case_id)
    await settle(physical, wired)

    counted = await census(physical, case_id=case_id, since=since)
    assert [key for key in counted if key[0] == LENA] == []
    assert wired.external_order(LENA_ORDER).version == since.external_versions[LENA_ORDER]
    assert wired.simulator.event_count(LENA_ORDER) == since.external_events[LENA_ORDER]
    assert not await outbox_of(physical, case_id)

    # And she is untouched for what is stored, not because she was skipped: her track exists,
    # it was considered, and considering is evidence rather than an effect.
    track = await physical.track(case_id, ORDERS[LENA]["promise"])
    assert track is not None
    assert track.state == "UNAFFECTED"


async def test_every_untouched_order_carries_zero_incident_caused_effects(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """0 of 3, counted the contract's way, for the three orders this exception never reached.

    Lena joins Ahmed and Cafe Marlow here, which is the point of the whole scenario: the
    untouched set is decided by stored state at the moment of the exception, and one of its
    members got there by a change nobody in this system made.
    """
    await lena_changes_her_own_cake(physical, wired)
    since = await baseline_of(physical, wired)
    case_id = await reported(chain, physical)
    await answered(chain, physical, case_id, WHOLE_DELIVERY)
    await confirmed(chain, physical, case_id)
    await settle(physical, wired)

    untouched = partition_at(EXPECTED, "SETTLED")["untouched"]
    counted = await census(physical, case_id=case_id, since=since)
    reservations = await reservations_by_line(physical)
    tasks = await physical.tasks()

    assert untouched == {LENA, "ord-e", "ord-f"}
    assert [key for key in counted if key[0] in untouched] == []

    # The same zero, as the case itself reports it: three orders left alone out of six, and no
    # operational effect on any of them. The census above counts the world; this counts the
    # case, and a screen carrying the claim reads the second one.
    projected = status_view.project(
        await analysis.read_case_status(physical.database, case_id=case_id)
    )
    assert len(projected.untouched) == len(untouched)
    assert projected.promise_count == len(UNIVERSE)
    assert projected.untouched_effect_count == 0
    for order in sorted(untouched):
        entry = ORDERS[order]
        external = entry["external_id"]
        assert wired.external_order(external).version == since.external_versions[external]
        assert wired.simulator.event_count(external) == since.external_events[external]
        assert reservations[entry["line"]] == since.reservations[entry["line"]]
        assert tasks[f"task-{entry['line']}"][1] is None
        track = await physical.track(case_id, entry["promise"])
        assert track is not None
        assert track.state == "UNAFFECTED"
        assert await physical.request_for(track.id) is None


# ---------------------------------------------------------------- the counterfactual itself


MOVED: Final = ("ord-a", "ord-b")
"""Priya and Tomas: the two orders whose authority the answer to the clarification decides."""


def threatened(partition: Partition) -> frozenset[str]:
    """The manifest's parent set: everything this exception reaches, however it is repaired."""
    return partition["auto_repairable"] | partition["consent_required"] | partition["blocked"]


def test_the_two_frozen_branches_differ_in_feasibility_and_not_in_breadth() -> None:
    """The counterfactual, read off the frozen labels before any of it is executed.

    S11 and this scenario are the same world and the same exception, answered two different
    ways, so the manifest itself decides what the difference is allowed to be. It reaches
    exactly the same promises in both -- identical threatened set, identical untouched set, so
    the affected set did not widen -- and inside that set Priya and Tomas move from a recovery
    that needs nobody and a recovery that needs a customer, to no recovery at all. That is the
    claim S02's note makes, and it is a property of the labels rather than of the run.
    """
    narrow = partition_at(S11, "PLANNED")
    wide = partition_at(EXPECTED, "PLANNED")

    assert threatened(narrow) == threatened(wide)
    assert narrow["untouched"] == wide["untouched"]
    assert set(MOVED) <= narrow["auto_repairable"] | narrow["consent_required"]
    assert set(MOVED) <= wide["blocked"]
    assert wide["auto_repairable"] == wide["consent_required"] == frozenset()


async def test_the_raspberry_only_answer_leaves_priya_and_tomas_a_recovery(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """The other half of the pair: the same edited world, answered "just the raspberries".

    This is S11 driven over the real surface, and it is here to be the control. The strawberries
    arrived, so a pre-authored strawberry version is a recovery that exists: Priya's standing
    preapproval permits it outright and Tomas's constraint means he has to be asked, and both
    tracks carry the options that make either of those possible.

    The two branches cannot share one database, and that is a fact about the world rather than
    about the rig: answering "just the raspberries" attests that the strawberries were received,
    and a settled commitment line stays settled. A second case in the same kitchen would be
    asking what happens after somebody has already said the strawberries came.
    """
    await lena_changes_her_own_cake(physical, wired)

    case_id = await reported(chain, physical)
    await answered(chain, physical, case_id, RASPBERRY_ONLY)

    assert await partition_of(physical, case_id) == partition_at(S11, "PLANNED")
    tracks = {track.promise_id: track for track in await physical.tracks(case_id)}
    for order in MOVED:
        track = tracks[ORDERS[order]["promise"]]
        assert await physical.options(track.id) != [], order
        assert track.classification != Classification.BLOCKED.value


async def test_the_whole_delivery_answer_takes_that_recovery_away(
    chain: McpServer, wired: Boundary, physical: Intake
) -> None:
    """The counterfactual half: one word of the answer differs, and the recovery is gone.

    Same fixture, same external edit, same spoken report, same two promises. Answering "the
    whole delivery" attests that the strawberries did not arrive either, so the substitute that
    was available to Priya and Tomas a moment ago is not available now. Their tracks record the
    substitute's own stock as the reason -- not a constraint, not a missing variant, and nothing
    about scope -- and they carry no option at all, which is what makes "nobody is asked here" a
    statement about feasibility rather than about breadth.
    """
    case_id = await planned_whole_delivery(chain, physical, wired)

    assert await partition_of(physical, case_id) == partition_at(EXPECTED, "PLANNED")
    tracks = {track.promise_id: track for track in await physical.tracks(case_id)}
    for order in MOVED:
        track = tracks[ORDERS[order]["promise"]]
        assert await physical.options(track.id) == [], order
        assert track.classification == Classification.BLOCKED.value
        assert track.rule_id == "R-SUBSTOCK"
        assert track.reason_detail == "INSUFFICIENT_SUBSTITUTE_STOCK"

    # Nobody is asked, and the surface says whose these are rather than staying silent.
    assert not await physical.requests()
    assert "Needs the owner:" in await spoken(chain, case_id)
