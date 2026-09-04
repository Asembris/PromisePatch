"""Impact analysis and recovery planning against a real database.

The shape of these tests is the shape of the guarantee, and it has two halves.

The first is that the answer is the *engine's* answer. Wherever it is practical, the expected
value is computed by calling ``promise_graph`` directly on the same persisted graph and
compared to what the worker wrote, rather than restated as a literal -- because a backend that
had quietly grown its own copy of the classification ladder would pass a table of literals and
fail an equivalence.

The second is that analysis and planning *do* nothing. The order book is read before the
worker runs and compared row for row afterwards; the outbox stays empty; no track claims to
have recovered anything. Nothing in this slice is allowed to touch a customer's order, and the
strongest way to say that is to check every row of it.

The frozen A-F matrix is still asserted literally as well, so a regression reads as a
regression rather than as two computations agreeing about the wrong thing.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from _intake_support import (
    BAKER,
    RASPBERRY_ONLY,
    STRAWBERRY_LINE,
    WHOLE_DELIVERY,
    Intake,
)
from _intake_support import physical as physical

from promise_graph.classification import priority_order
from promise_graph.examples import hollow_oak as ho
from promise_graph.fingerprint import fingerprint, scope_for
from promise_graph.model import Classification, ReasonDetail, RuleId
from promisepatch.db.models import ApprovalRequest, OutboxMessage, RecipeVersion, Track
from promisepatch.db.uow import Actor
from promisepatch.domain import analysis, steps
from promisepatch.domain.model import StepResult
from promisepatch.domain.observation import AUDIT_PHYSICAL_FACT_RECORDED

pytestmark = pytest.mark.integration

A, B, C, D, E, F = (
    ho.PROMISE_A,
    ho.PROMISE_B,
    ho.PROMISE_C,
    ho.PROMISE_D,
    ho.PROMISE_E,
    ho.PROMISE_F,
)

CREAM_UNUSABLE = "the cream in the walk-in went off"
DECK_OVEN_DOWN = "the deck oven is down"


async def planned_case(intake: Intake, answer: str = RASPBERRY_ONLY) -> UUID:
    """The canonical path, driven all the way to ``PLANNED`` by the real worker."""
    opened = await intake.report()
    await intake.drain()
    await intake.answer(opened.case_id, answer)
    await intake.drain()
    return opened.case_id


async def classifications(intake: Intake, case_id: UUID) -> dict[str, str]:
    return {track.promise_id: track.classification for track in await intake.tracks(case_id)}


# ------------------------------------------------------------- the canonical result (§28)


async def test_the_canonical_path_reaches_planned(physical: Intake) -> None:
    case_id = await planned_case(physical)
    case = await physical.case(case_id)

    assert case.state == analysis.CASE_PLANNED
    assert case.needs_owner_attention is False
    assert [step.state for step in await physical.outstanding(case_id)] == []


async def test_the_canonical_classifications_are_the_frozen_matrix(physical: Intake) -> None:
    """The demo's whole claim, read back out of ``tracks``.

    ``D`` is ``BLOCKED`` because Lena's order still names Raspberry Lemon Layer v2, which no
    substitution policy offers a variant for. The video's ``UNAFFECTED`` comes later, from a
    mutation made in the order system, and forcing it here would prove nothing.
    """
    case_id = await planned_case(physical)

    assert await classifications(physical, case_id) == {
        A: Classification.AUTO_RECOVERABLE.value,
        B: Classification.APPROVAL_REQUIRED.value,
        C: Classification.BLOCKED.value,
        D: Classification.BLOCKED.value,
        E: Classification.UNAFFECTED.value,
        F: Classification.UNAFFECTED.value,
    }


async def test_every_classification_cites_the_rule_that_produced_it(physical: Intake) -> None:
    case_id = await planned_case(physical)
    tracks = {track.promise_id: track for track in await physical.tracks(case_id)}

    assert tracks[A].rule_id == RuleId.R_PREAPPROVED.value
    assert tracks[A].reason_detail == ReasonDetail.PREAPPROVAL_COVERS.value
    assert tracks[B].rule_id == RuleId.R_VISIBLE_ASK.value
    assert tracks[B].reason_detail == ReasonDetail.VISIBLE_CHANGE_ASK.value
    assert tracks[C].rule_id == RuleId.R_NOSUB.value
    assert tracks[C].reason_detail == ReasonDetail.NOSUB_CONSTRAINT.value
    assert tracks[D].rule_id == RuleId.R_NOSUB.value
    assert tracks[D].reason_detail == ReasonDetail.NO_PREAUTHORED_VARIANT.value
    for promise_id in (E, F):
        assert tracks[promise_id].rule_id == RuleId.R_UNREACH.value


async def test_the_blocked_tracks_cite_their_constraints_on_the_audit_row(
    physical: Intake,
) -> None:
    """``C`` carries no option row to hold its citation, so the ledger has to."""
    case_id = await planned_case(physical)
    analyzed = next(
        row for row in await physical.audits(case_id) if row.type == analysis.AUDIT_IMPACT_ANALYZED
    )

    assert analyzed.after["cited"][A] == [ho.CONSTRAINT_A_PREAPPROVED]
    assert analyzed.after["cited"][B] == [ho.CONSTRAINT_B_ASK]
    assert analyzed.after["cited"][C] == [ho.CONSTRAINT_C_NOSUB]
    assert D not in analyzed.after["cited"]


async def test_the_case_records_which_promises_it_considered_and_dismissed(
    physical: Intake,
) -> None:
    """Selectivity is evidence: E and F are on the case, saying they were looked at."""
    case_id = await planned_case(physical)
    tracks = {track.promise_id: track for track in await physical.tracks(case_id)}

    for promise_id in (E, F):
        assert tracks[promise_id].state == analysis.TRACK_UNAFFECTED
        assert tracks[promise_id].reason_detail == ReasonDetail.NOT_REACHABLE.value


# ------------------------------------------------------- exact pure-engine equivalence (§29)


async def test_persisted_classifications_are_exactly_the_engine_s(physical: Intake) -> None:
    """Not "roughly the same": the same four values, promise by promise."""
    case_id = await planned_case(physical)
    _, computed = await physical.engine_analysis(case_id)

    persisted = {
        track.promise_id: (track.classification, track.rule_id, track.reason_detail)
        for track in await physical.tracks(case_id)
    }
    expected = {
        promise_id: (
            result.classification.value,
            result.rule_id.value,
            result.reason_detail.value,
        )
        for promise_id, result in computed.classifications.items()
    }
    assert persisted == expected


async def test_persisted_priorities_are_the_engine_s_allocation_order(physical: Intake) -> None:
    case_id = await planned_case(physical)
    graph, computed = await physical.engine_analysis(case_id)

    expected = {
        promise_id: rank
        for rank, promise_id in enumerate(priority_order(graph, computed.impact), start=1)
    }
    persisted = {
        track.promise_id: track.priority
        for track in await physical.tracks(case_id)
        if track.priority
    }
    assert persisted == expected


async def test_persisted_paths_are_exactly_the_engine_s(physical: Intake) -> None:
    case_id = await planned_case(physical)
    _, computed = await physical.engine_analysis(case_id)

    for track in await physical.tracks(case_id):
        rows = await physical.paths(track.id)
        persisted = [tuple(node["node_ref"] for node in row.nodes) for row in rows]
        expected = [
            tuple(step.node_ref for step in path)
            for path in computed.impact.paths_by_promise.get(track.promise_id, ())
        ]
        assert persisted == expected, track.promise_id


async def test_persisted_paths_carry_the_engine_s_own_arithmetic(physical: Intake) -> None:
    """The numbers that make a reached line short rather than merely reachable."""
    case_id = await planned_case(physical)
    _, computed = await physical.engine_analysis(case_id)
    track = await physical.track(case_id, A)
    (row,) = await physical.paths(track.id)

    (quantification,) = computed.impact.quantifications_by_line[ho.LINE_A]
    assert row.quantification["need"] == str(quantification.need)
    assert row.quantification["shortfall"] == str(quantification.shortfall)
    assert row.quantification["available_before_start"] == str(
        quantification.available_before_start
    )
    assert row.quantification["satisfied"] is False
    assert row.quantification["reservation_id"] == quantification.reservation_id


async def test_persisted_options_are_exactly_the_engine_s(physical: Intake) -> None:
    case_id = await planned_case(physical)
    _, computed = await physical.engine_analysis(case_id)

    for track in await physical.tracks(case_id):
        rows = await physical.options(track.id)
        persisted = [
            (row.kind, row.order_line_id, row.from_version_id, row.to_version_id, row.approval_rule)
            for row in rows
        ]
        expected = [
            (
                option.kind.value,
                option.order_line_id,
                option.from_version_id,
                option.to_version_id,
                option.approval_rule.value,
            )
            for option in computed.option_sets[track.promise_id].valid
        ]
        assert persisted == expected, track.promise_id


async def test_the_chosen_option_is_the_one_the_engine_chose(physical: Intake) -> None:
    case_id = await planned_case(physical)
    _, computed = await physical.engine_analysis(case_id)

    for track in await physical.tracks(case_id):
        chosen = computed.classifications[track.promise_id].chosen_option_id
        expected = None if chosen is None else analysis.option_id_for(track.id, chosen)
        assert track.chosen_option_id == expected, track.promise_id


async def test_persisted_fingerprints_are_exactly_the_engine_s(physical: Intake) -> None:
    case_id = await planned_case(physical)
    graph, computed = await physical.engine_analysis(case_id)

    for track in await physical.tracks(case_id):
        if track.state != analysis.TRACK_PENDING:
            assert track.fingerprint is None
            continue
        scope = scope_for(
            graph,
            computed.impact,
            computed.option_sets[track.promise_id],
            track.promise_id,
        )
        assert track.fingerprint == fingerprint(graph, scope).hash, track.promise_id


# --------------------------------------------------------------- the whole delivery (§30)


async def test_the_whole_delivery_blocks_both_substitutions_on_substitute_stock(
    physical: Intake,
) -> None:
    """No special path: the strawberries never arrived, so there is nothing to substitute."""
    case_id = await planned_case(physical, WHOLE_DELIVERY)
    tracks = {track.promise_id: track for track in await physical.tracks(case_id)}

    assert tracks[A].classification == Classification.BLOCKED.value
    assert tracks[B].classification == Classification.BLOCKED.value
    assert tracks[A].rule_id == RuleId.R_SUBSTOCK.value
    assert tracks[B].rule_id == RuleId.R_SUBSTOCK.value
    assert tracks[A].reason_detail == ReasonDetail.INSUFFICIENT_SUBSTITUTE_STOCK.value
    assert tracks[B].reason_detail == ReasonDetail.INSUFFICIENT_SUBSTITUTE_STOCK.value


async def test_the_whole_delivery_leaves_nobody_with_a_recovery_option(
    physical: Intake,
) -> None:
    case_id = await planned_case(physical, WHOLE_DELIVERY)

    for track in await physical.tracks(case_id):
        assert await physical.options(track.id) == [], track.promise_id
        assert track.chosen_option_id is None


# --------------------------------------------------------- Lena, before and after (§31)


async def test_lena_is_blocked_while_her_order_still_names_the_raspberry_version(
    physical: Intake,
) -> None:
    case_id = await planned_case(physical)
    track = await physical.track(case_id, D)
    graph = await physical.snapshot()

    assert graph.order_lines[ho.LINE_D].recipe_version_id == ho.RLL_V2
    assert track.classification == Classification.BLOCKED.value
    assert track.rule_id == RuleId.R_NOSUB.value
    assert track.reason_detail == ReasonDetail.NO_PREAUTHORED_VARIANT.value


async def test_repinning_lena_to_the_lemon_curd_version_makes_her_unaffected(
    physical: Intake,
) -> None:
    """Analysis answers about the state that is stored, not about the promise's name."""
    await physical.repin_order_line(ho.LINE_D, ho.LCL_V1)
    case_id = await planned_case(physical)
    track = await physical.track(case_id, D)

    assert track.classification == Classification.UNAFFECTED.value
    assert track.rule_id == RuleId.R_UNREACH.value
    assert track.state == analysis.TRACK_UNAFFECTED
    assert await physical.paths(track.id) == []


async def test_the_mutation_moves_nobody_but_lena(physical: Intake) -> None:
    await physical.repin_order_line(ho.LINE_D, ho.LCL_V1)
    after = await classifications(physical, await planned_case(physical))

    assert after == {
        A: Classification.AUTO_RECOVERABLE.value,
        B: Classification.APPROVAL_REQUIRED.value,
        C: Classification.BLOCKED.value,
        D: Classification.UNAFFECTED.value,
        E: Classification.UNAFFECTED.value,
        F: Classification.UNAFFECTED.value,
    }


# ------------------------------------------------------- nothing is executed (§8, §12, §32)


async def test_planning_writes_nothing_to_the_order_book(physical: Intake) -> None:
    """Every row of orders, lines, reservations, tasks, versions and promises, unchanged.

    The claim the product makes is that unrelated work receives zero writes. The strongest
    form of that is not "no write to an unaffected order" but "no write to the order book at
    all", because this slice has not been authorised to change anything yet.
    """
    opened = await physical.report()
    await physical.drain_intake(opened.case_id)
    await physical.answer(opened.case_id, RASPBERRY_ONLY)
    await physical.drain_intake(opened.case_id)

    before = await physical.order_book()
    await physical.drain()
    after = await physical.order_book()

    assert (await physical.case(opened.case_id)).state == analysis.CASE_PLANNED
    assert after == before


async def test_an_unaffected_promise_gets_a_track_and_nothing_else(physical: Intake) -> None:
    case_id = await planned_case(physical)

    for promise_id in (E, F):
        track = await physical.track(case_id, promise_id)
        assert track.state == analysis.TRACK_UNAFFECTED
        assert await physical.options(track.id) == []
        assert await physical.paths(track.id) == []
        assert await physical.watch(track.id) == []
        assert track.fingerprint is None
        assert track.chosen_option_id is None
        assert track.deadline_at is None


async def test_no_unaffected_promise_reaches_the_event_spine(physical: Intake) -> None:
    """A feed naming an unrelated customer's order would break selectivity where nobody looks."""
    before = await physical.latest_event_seq()
    case_id = await planned_case(physical)
    unaffected = {str((await physical.track(case_id, promise_id)).id) for promise_id in (E, F)}

    named = {
        ref.get("id")
        for event in await physical.events_after(before)
        if event.case_id == case_id
        for ref in event.entity_refs
    }
    assert unaffected
    assert named.isdisjoint(unaffected)


async def test_planning_asks_nobody_and_sends_nothing(physical: Intake) -> None:
    case_id = await planned_case(physical)

    assert await physical.rows_of(ApprovalRequest) == []
    assert await physical.rows_of(OutboxMessage) == []
    for track in await physical.tracks(case_id):
        assert track.state in (analysis.TRACK_PENDING, analysis.TRACK_UNAFFECTED)
        assert track.approval_request_id is None


async def test_an_auto_recoverable_track_has_not_been_applied(physical: Intake) -> None:
    """``AUTO_RECOVERABLE`` is a permission to act later, not a record of having acted."""
    case_id = await planned_case(physical)
    track = await physical.track(case_id, A)

    assert track.classification == Classification.AUTO_RECOVERABLE.value
    assert track.state == analysis.TRACK_PENDING
    assert track.chosen_option_id is not None


# ------------------------------------------------------------------ recovery options (§33)


async def test_the_pre_authored_variants_are_the_ones_selected(physical: Intake) -> None:
    case_id = await planned_case(physical)

    (option_a,) = await physical.options((await physical.track(case_id, A)).id)
    assert (option_a.from_version_id, option_a.to_version_id) == (ho.RAC_V3, ho.RAC_V4)
    assert option_a.substitute_resource_id == ho.STRAWBERRIES
    assert option_a.requires_approval is False
    assert option_a.policy_id == ho.POLICY_ALMOND_FILLING

    (option_b,) = await physical.options((await physical.track(case_id, B)).id)
    assert (option_b.from_version_id, option_b.to_version_id) == (ho.RRC_V2, ho.RRC_V3)
    assert option_b.visible_change is True
    assert option_b.requires_approval is True
    assert option_b.policy_id == ho.POLICY_ROSE_CROWN

    assert await physical.options((await physical.track(case_id, C)).id) == []


async def test_no_recipe_version_is_created_at_runtime(physical: Intake) -> None:
    """Recovery selects what a human authored. Nothing derives, and nothing synthesises."""
    before = await physical.rows_of(RecipeVersion)
    case_id = await planned_case(physical)
    after = await physical.rows_of(RecipeVersion)

    assert len(after) == len(before)
    graph = await physical.snapshot()
    for track in await physical.tracks(case_id):
        for option in await physical.options(track.id):
            assert option.to_version_id in graph.versions
            assert graph.versions[option.to_version_id].authored_by == ho.AUTHOR


async def test_an_approval_gated_option_carries_a_planned_window(physical: Intake) -> None:
    case_id = await planned_case(physical)
    track_b = await physical.track(case_id, B)
    track_a = await physical.track(case_id, A)

    assert track_b.deadline_at is not None
    assert track_a.deadline_at is None


# ------------------------------------------------------------ fingerprints and watch (§34)


async def test_a_planned_fingerprint_recomputes_identically_from_its_watch_rows(
    physical: Intake,
) -> None:
    """Revalidation later needs the scope back, not a description of it."""
    case_id = await planned_case(physical)
    graph = await physical.snapshot()

    for promise_id in (A, B):
        track = await physical.track(case_id, promise_id)
        scope = analysis.scope_from_watch(
            await physical.watch(track.id), promise_id=track.promise_id
        )
        assert fingerprint(graph, scope).hash == track.fingerprint, promise_id


async def test_a_changed_order_version_moves_the_fingerprint(physical: Intake) -> None:
    case_id = await planned_case(physical)
    track = await physical.track(case_id, A)
    scope = analysis.scope_from_watch(await physical.watch(track.id), promise_id=A)

    assert fingerprint(await physical.snapshot(), scope).hash == track.fingerprint
    await physical.bump_order_version(ho.ORDER_A)
    assert fingerprint(await physical.snapshot(), scope).hash != track.fingerprint


async def test_a_repinned_line_moves_the_fingerprint(physical: Intake) -> None:
    case_id = await planned_case(physical)
    track = await physical.track(case_id, D)
    scope = analysis.scope_from_watch(await physical.watch(track.id), promise_id=D)

    assert fingerprint(await physical.snapshot(), scope).hash == track.fingerprint
    await physical.repin_order_line(ho.LINE_D, ho.LCL_V1)
    assert fingerprint(await physical.snapshot(), scope).hash != track.fingerprint


async def test_the_watch_names_what_the_plan_actually_depends_on(physical: Intake) -> None:
    case_id = await planned_case(physical)
    watch = await physical.watch((await physical.track(case_id, A)).id)

    assert (analysis.WATCH_ORDER, ho.ORDER_A) in watch
    assert (analysis.WATCH_ORDER_LINE, ho.LINE_A) in watch
    assert (analysis.WATCH_RECIPE_VERSION, ho.RAC_V3) in watch
    assert (analysis.WATCH_RECIPE_VERSION, ho.RAC_V4) in watch
    assert (analysis.WATCH_CONSTRAINT, ho.CONSTRAINT_A_PREAPPROVED) in watch
    assert (analysis.WATCH_RESOURCE, ho.RASPBERRIES) in watch
    assert (analysis.WATCH_RESOURCE, ho.STRAWBERRIES) in watch
    assert any(entity_type == analysis.WATCH_TASK for entity_type, _ in watch)
    assert any(entity_type == analysis.WATCH_RESERVATION for entity_type, _ in watch)


# ------------------------------------------------------------------- crash safety (§35)


async def test_a_death_before_the_analysis_commits_leaves_nothing_behind(
    physical: Intake,
) -> None:
    from promisepatch.domain import crash

    case_id = await _ready_for_analysis(physical)
    worker = physical.worker(identity="dies-mid-analysis")

    audit_before = len(await physical.audits(case_id))
    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    assert await physical.tracks(case_id) == []
    assert (await physical.case(case_id)).state == "INTERPRETING"
    assert len(await physical.audits(case_id)) == audit_before
    assert analysis.EVENT_CASE_ANALYZED not in await physical.events(case_id)


async def test_the_analysis_survives_that_death_and_completes_next_time(
    physical: Intake,
) -> None:
    from promisepatch.domain import crash

    case_id = await _ready_for_analysis(physical)
    worker = physical.worker(identity="dies-mid-analysis")
    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    for step in await physical.outstanding(case_id):
        await physical.expire_lease(step.id)
    await physical.drain(worker=physical.worker(identity="finishes-the-job"))

    assert (await physical.case(case_id)).state == analysis.CASE_PLANNED
    assert await classifications(physical, case_id) != {}


async def test_a_death_after_the_analysis_commits_leaves_it_standing(
    physical: Intake,
) -> None:
    from promisepatch.domain import crash

    case_id = await _ready_for_analysis(physical)
    worker = physical.worker(identity="dies-after-analysing")
    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    assert (await physical.case(case_id)).state == analysis.CASE_ANALYZED
    assert len(await physical.tracks(case_id)) == 6
    for track in await physical.tracks(case_id):
        assert track.fingerprint is None

    await physical.drain(worker=physical.worker(identity="plans-it"))
    assert (await physical.case(case_id)).state == analysis.CASE_PLANNED
    assert len(await physical.tracks(case_id)) == 6


async def test_a_death_before_the_plan_commits_leaves_the_case_analyzed(
    physical: Intake,
) -> None:
    from promisepatch.domain import crash

    case_id = await _ready_for_analysis(physical)
    await physical.drain(limit=1)
    assert (await physical.case(case_id)).state == analysis.CASE_ANALYZED

    worker = physical.worker(identity="dies-mid-planning")
    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    assert (await physical.case(case_id)).state == analysis.CASE_ANALYZED
    for track in await physical.tracks(case_id):
        assert track.fingerprint is None
        assert await physical.options(track.id) == []


async def test_a_worker_that_dies_after_claiming_the_analysis_leaves_it_for_the_next(
    physical: Intake,
) -> None:
    from promisepatch.domain import crash

    case_id = await _ready_for_analysis(physical)
    first = physical.worker(identity="dies-after-claiming")

    with crash.arm(crash.AFTER_CLAIM_COMMIT), pytest.raises(crash.WorkerDied):
        await first.run_once()

    (claimed,) = await physical.outstanding(case_id)
    assert claimed.kind == analysis.STEP_ANALYZE_IMPACT
    assert claimed.state == "IN_FLIGHT"

    await physical.expire_lease(claimed.id)
    await physical.drain(worker=physical.worker(identity="picks-it-up"))

    assert (await physical.case(case_id)).state == analysis.CASE_PLANNED


async def test_a_death_after_the_plan_commits_leaves_the_case_planned(
    physical: Intake,
) -> None:
    from promisepatch.domain import crash

    case_id = await _ready_for_analysis(physical)
    await physical.drain(limit=1)
    worker = physical.worker(identity="dies-after-planning")

    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    assert (await physical.case(case_id)).state == analysis.CASE_PLANNED
    settled = await _row_counts(physical, case_id)

    await physical.drain(worker=physical.worker(identity="tries-again"))
    assert await _row_counts(physical, case_id) == settled
    assert (await physical.case(case_id)).state == analysis.CASE_PLANNED


async def test_a_second_analysis_of_the_same_truth_adds_no_rows(physical: Intake) -> None:
    """The replay guarantee, made visible: derived ids, so a second pass writes the same rows."""
    case_id = await planned_case(physical)
    before = await _row_counts(physical, case_id)

    async with physical.database.begin() as connection:
        await steps.enqueue_step(
            connection,
            case_id=case_id,
            step_key=analysis.analyze_step_key(uuid4()),
            kind=analysis.STEP_ANALYZE_IMPACT,
        )
    await physical.drain()

    assert (await physical.case(case_id)).state == analysis.CASE_PLANNED
    assert await _row_counts(physical, case_id) == before


# ------------------------------------------------------------------- stale workers (§36)


async def test_a_worker_that_lost_its_lease_cannot_persist_its_analysis(
    physical: Intake,
) -> None:
    """A stalled claim names an attempt that no longer exists, and matches no row."""
    case_id = await _ready_for_analysis(physical)

    stale = await steps.claim_step(physical.database, worker="worker-a")
    assert stale is not None and stale.kind == analysis.STEP_ANALYZE_IMPACT
    await physical.expire_lease(stale.step_id)

    await physical.drain(worker=physical.worker(identity="worker-b"))
    after_b = await _row_counts(physical, case_id)
    assert (await physical.case(case_id)).state == analysis.CASE_PLANNED

    result = await steps.execute_step(
        physical.database, claim=stale, actor=Actor(kind="SYSTEM", id="worker-a")
    )
    assert result in (StepResult.LEASE_LOST, StepResult.STALE)
    assert await _row_counts(physical, case_id) == after_b


async def test_a_graph_change_between_analysis_and_planning_supersedes_the_plan(
    physical: Intake,
) -> None:
    """The world moved under a finished analysis, so no plan is written for the old one."""
    case_id = await _ready_for_analysis(physical)
    await physical.drain(limit=1)
    assert (await physical.case(case_id)).state == analysis.CASE_ANALYZED
    assert (await classifications(physical, case_id))[D] == Classification.BLOCKED.value

    plan_step = await _step_of_kind(physical, case_id, analysis.STEP_PLAN_RECOVERY)
    await physical.repin_order_line(ho.LINE_D, ho.LCL_V1)
    await physical.drain(limit=1)

    settled = await physical.step_named(case_id, plan_step.step_key)
    assert settled.state == "SKIPPED"
    assert settled.result["outcome"] == "SUPERSEDED"
    assert D in settled.result["drift"]
    assert (await physical.case(case_id)).state == analysis.CASE_ANALYZED
    for track in await physical.tracks(case_id):
        assert await physical.options(track.id) == []
        assert track.fingerprint is None
    assert analysis.EVENT_ANALYSIS_SUPERSEDED in await physical.events(case_id)


async def test_a_correction_stops_the_old_analysis_from_becoming_a_plan(
    physical: Intake,
) -> None:
    """The physical truth moved, so the plan that followed the old truth is never written.

    A correction re-opens interpretation, so the deferred plan step finds a case that is no
    longer ``ANALYZED`` and writes nothing at all. Either guard is a refusal; what matters is
    that no route exists by which the pre-correction answer becomes the plan.
    """
    case_id = await _ready_for_analysis(physical)
    await physical.drain(limit=1)
    assert (await classifications(physical, case_id))[A] == Classification.AUTO_RECOVERABLE.value

    plan_step = await _step_of_kind(physical, case_id, analysis.STEP_PLAN_RECOVERY)
    await physical.defer(plan_step.id)

    await physical.correct(case_id)
    await physical.drain_intake(case_id)
    fresh = await _step_of_kind(physical, case_id, analysis.STEP_ANALYZE_IMPACT, pending=True)
    await physical.defer(fresh.id)

    await physical.release(plan_step.id)
    await physical.drain(limit=1)

    settled = await physical.step_named(case_id, plan_step.step_key)
    assert settled.state == "SKIPPED"
    assert settled.result["outcome"] in ("SUPERSEDED", "NOT_APPLICABLE")
    assert (await physical.case(case_id)).state != analysis.CASE_PLANNED
    for track in await physical.tracks(case_id):
        assert await physical.options(track.id) == []
        assert track.fingerprint is None


async def test_the_fresh_analysis_then_plans_the_corrected_truth(physical: Intake) -> None:
    case_id = await _ready_for_analysis(physical)
    await physical.drain(limit=1)
    plan_step = await _step_of_kind(physical, case_id, analysis.STEP_PLAN_RECOVERY)
    await physical.defer(plan_step.id)

    await physical.correct(case_id)
    await physical.drain_intake(case_id)
    fresh = await _step_of_kind(physical, case_id, analysis.STEP_ANALYZE_IMPACT, pending=True)
    await physical.defer(fresh.id)
    await physical.release(plan_step.id)
    await physical.drain(limit=1)

    await physical.release(fresh.id)
    await physical.drain()

    assert (await physical.case(case_id)).state == analysis.CASE_PLANNED
    tracks = {track.promise_id: track for track in await physical.tracks(case_id)}
    assert tracks[A].classification == Classification.BLOCKED.value
    assert tracks[A].rule_id == RuleId.R_SUBSTOCK.value
    assert tracks[B].classification == Classification.BLOCKED.value
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "NOT_RECEIVED"


# ------------------------------------------------------------------- concurrency (§37)


async def test_two_cases_analyse_without_corrupting_each_other(physical: Intake) -> None:
    """Different exceptions, different promises, one worker sweeping both."""
    delivery = await planned_case(physical)
    spoilage = await physical.report(CREAM_UNUSABLE)
    await physical.drain()

    assert (await physical.case(spoilage.case_id)).state == analysis.CASE_PLANNED
    assert (await physical.case(delivery)).state == analysis.CASE_PLANNED

    cream = {track.promise_id: track for track in await physical.tracks(spoilage.case_id)}
    assert cream[E].classification == Classification.BLOCKED.value
    assert cream[E].rule_id == RuleId.R_UNKNOWN.value
    assert cream[E].state == analysis.TRACK_PENDING
    for promise_id in (A, B, C, D):
        assert cream[promise_id].classification == Classification.UNAFFECTED.value

    assert (await classifications(physical, delivery))[A] == (Classification.AUTO_RECOVERABLE.value)


async def test_two_workers_sweeping_two_cases_at_once_make_progress_on_both(
    physical: Intake,
) -> None:
    """``SKIP LOCKED`` means two sweeps take different rows rather than queueing."""
    import asyncio

    delivery = await _ready_for_analysis(physical)
    spoilage = await physical.report(CREAM_UNUSABLE)
    await physical.drain_intake(spoilage.case_id)

    a = physical.worker(identity="sweeper-a")
    b = physical.worker(identity="sweeper-b")
    for _ in range(6):
        await asyncio.gather(a.run_once(), b.run_once())

    assert (await physical.case(delivery)).state == analysis.CASE_PLANNED
    assert (await physical.case(spoilage.case_id)).state == analysis.CASE_PLANNED
    assert (await classifications(physical, delivery))[A] == (Classification.AUTO_RECOVERABLE.value)
    assert (await classifications(physical, spoilage.case_id))[E] == Classification.BLOCKED.value


async def test_a_second_case_reaching_a_live_promise_links_instead_of_competing(
    physical: Intake,
) -> None:
    """The partial unique index decides the race; the second case links and says so."""
    delivery = await planned_case(physical)
    outage = await physical.report(DECK_OVEN_DOWN)
    await physical.drain()

    held = {track.promise_id: track.id for track in await physical.tracks(delivery)}
    linked = [
        track
        for track in await physical.tracks(outage.case_id)
        if track.state == analysis.TRACK_LINKED
    ]
    assert linked
    for track in linked:
        assert track.linked_track_id == held[track.promise_id]
        assert await physical.options(track.id) == []

    audits = [
        row
        for row in await physical.audits(outage.case_id)
        if row.type == analysis.AUDIT_PROMISE_ALREADY_IN_CASE
    ]
    assert len(audits) == 1
    assert set(audits[0].after["linked"]) == {track.promise_id for track in linked}


async def test_one_promise_is_never_live_in_two_cases_at_once(physical: Intake) -> None:
    delivery = await planned_case(physical)
    outage = await physical.report(DECK_OVEN_DOWN)
    await physical.drain()

    live = await physical.rows_of(Track)
    counted: dict[str, int] = {}
    for track in live:
        if track.state in ("PENDING", "WAITING_FOR_CUSTOMER", "APPLYING", "STALE"):
            counted[track.promise_id] = counted.get(track.promise_id, 0) + 1
    assert counted and max(counted.values()) == 1
    assert {delivery, outage.case_id} == {track.case_id for track in live}


# --------------------------------------------------------------- audit and events (§38)


async def test_analysis_and_planning_are_audited_under_the_system_worker(
    physical: Intake,
) -> None:
    """Two authorities, kept apart: Maya attested the facts, the engine classified them."""
    case_id = await planned_case(physical)
    audits = {row.type: row for row in await physical.audits(case_id)}

    analyzed = audits[analysis.AUDIT_IMPACT_ANALYZED]
    planned = audits[analysis.AUDIT_RECOVERY_PLANNED]
    for row in (analyzed, planned):
        assert row.actor_kind == "SYSTEM"
        assert row.actor_id != BAKER
        assert row.authority == "NONE"
        assert row.case_id == case_id

    attested = audits[AUDIT_PHYSICAL_FACT_RECORDED]
    assert attested.actor_kind == "WORKER"
    assert attested.actor_id == BAKER


async def test_the_audit_row_carries_the_whole_classification(physical: Intake) -> None:
    case_id = await planned_case(physical)
    analyzed = next(
        row for row in await physical.audits(case_id) if row.type == analysis.AUDIT_IMPACT_ANALYZED
    )

    assert analyzed.before["case_state"] == "INTERPRETING"
    assert analyzed.after["case_state"] == analysis.CASE_ANALYZED
    assert analyzed.after["classifications"] == await classifications(physical, case_id)
    assert analyzed.provenance["category"] == "SUPPLY_NOT_RECEIVED"


async def test_the_plan_audit_names_the_options_it_wrote(physical: Intake) -> None:
    case_id = await planned_case(physical)
    planned = next(
        row for row in await physical.audits(case_id) if row.type == analysis.AUDIT_RECOVERY_PLANNED
    )
    track_a = await physical.track(case_id, A)

    assert planned.after["options"][A] == 1
    assert planned.after["options"][C] == 0
    assert planned.after["chosen"][A] == str(track_a.chosen_option_id)
    assert planned.after["fingerprints"][A] == track_a.fingerprint


async def test_the_spine_carries_analysis_and_planning_in_order(physical: Intake) -> None:
    case_id = await planned_case(physical)
    events = await physical.events(case_id)

    assert events.index("case.ready_for_analysis") < events.index(analysis.EVENT_CASE_ANALYZED)
    assert events.index(analysis.EVENT_CASE_ANALYZED) < events.index(analysis.EVENT_CASE_PLANNED)
    assert events.count(analysis.EVENT_TRACK_CLASSIFIED) == 4
    assert events.count(analysis.EVENT_CASE_ANALYZED) == 1
    assert events.count(analysis.EVENT_CASE_PLANNED) == 1


async def test_the_spine_stays_ordered_across_the_whole_run(physical: Intake) -> None:
    before = await physical.latest_event_seq()
    case_id = await planned_case(physical)
    collected = await physical.events_after(before)

    sequences = [event.seq for event in collected]
    assert sequences == sorted(sequences)
    assert {event.type for event in collected} >= {
        analysis.EVENT_CASE_ANALYZED,
        analysis.EVENT_CASE_PLANNED,
        analysis.EVENT_TRACK_CLASSIFIED,
    }
    assert case_id in {event.case_id for event in collected}


# -------------------------------------------------------------- the operator view (§40)


async def test_the_operator_view_reads_the_persisted_plan(physical: Intake) -> None:
    """One reusable read behind the CLI, the trace and the evidence screen."""
    case_id = await planned_case(physical)
    status = await analysis.read_case_status(physical.database, case_id=case_id)

    assert status.state == analysis.CASE_PLANNED
    assert status.category == "SUPPLY_NOT_RECEIVED"
    assert status.needs_owner_attention is False

    by_promise = {track.promise_id: track for track in status.tracks}
    assert by_promise[A].classification == Classification.AUTO_RECOVERABLE.value
    assert by_promise[A].customer_name and by_promise[A].order_external_id
    assert [option.to_version_id for option in by_promise[A].options] == [ho.RAC_V4]
    assert by_promise[A].options[0].chosen is True
    assert by_promise[A].paths == 1
    assert by_promise[A].watched_entities > 0

    assert by_promise[B].options[0].requires_approval is True
    assert by_promise[C].options == ()
    assert by_promise[E].state == analysis.TRACK_UNAFFECTED
    assert by_promise[E].watched_entities == 0


async def test_the_operator_view_orders_tracks_by_the_allocator_s_priority(
    physical: Intake,
) -> None:
    status = await analysis.read_case_status(
        physical.database, case_id=await planned_case(physical)
    )
    priorities = [track.priority for track in status.tracks]

    assert priorities == sorted(priorities)
    assert [track.promise_id for track in status.tracks if track.priority] == [A, B, C, D]


async def test_the_operator_view_refuses_a_case_that_does_not_exist(physical: Intake) -> None:
    with pytest.raises(analysis.CaseNotFoundError):
        await analysis.read_case_status(physical.database, case_id=uuid4())


# -------------------------------------------------------------------------------- helpers


async def _ready_for_analysis(intake: Intake) -> UUID:
    """The canonical intake, stopped with the analysis step enqueued and nothing run."""
    opened = await intake.report()
    await intake.drain_intake(opened.case_id)
    await intake.answer(opened.case_id, RASPBERRY_ONLY)
    await intake.drain_intake(opened.case_id)
    return opened.case_id


async def _row_counts(intake: Intake, case_id: UUID) -> dict[str, int]:
    tracks = await intake.tracks(case_id)
    counts = {"tracks": len(tracks), "paths": 0, "options": 0, "watch": 0}
    for track in tracks:
        counts["paths"] += len(await intake.paths(track.id))
        counts["options"] += len(await intake.options(track.id))
        counts["watch"] += len(await intake.watch(track.id))
    return counts


async def _step_of_kind(intake: Intake, case_id: UUID, kind: str, *, pending: bool = False) -> Any:
    rows = [step for step in await intake.steps(case_id) if step.kind == kind]
    if pending:
        rows = [step for step in rows if step.state == "PENDING"]
    assert len(rows) == 1, [(step.step_key, step.state) for step in rows]
    return rows[0]
