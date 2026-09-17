"""The ten checks, the stale path, and the ending -- against a real database and a real worker.

The shape of these tests is the shape of the guarantee, and it has four parts.

The first is **that the checks are real and all ten of them run**. The canonical case passes
every one, each is an audit row carrying the two values it compared, and the deciding failure is
the lowest-numbered one rather than whichever query happened to notice first.

The second is **that each check can be made to fail on its own**. Order version, pinned recipe
version, constraint snapshot, substitute stock after an earlier recovery, production task,
deadline, sender, and the decision's own binding each get a test that moves exactly that one
thing between the customer's yes and the worker's revalidation. Every one of them must end with
zero external effect for B.

The third is **that a refusal is not a deletion**. A stale track keeps the option the customer
was asked about, the request that captured the world, and the decision that carries their word.
What it does not keep is the authority: the request is superseded, the track is unbound from it,
and the fresh plan starts with no consent at all.

The fourth is **that the case ends**. Approved, declined, expired or stale -- every path either
reaches ``RESOLVED`` or is still visibly working, and no path needs an approved execution to
finish. Throughout, E and F are never written, never messaged and never mentioned.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from _intake_support import RASPBERRY_ONLY, TOMAS_CHANNEL, Intake
from _intake_support import physical as physical
from sqlalchemy import insert, select

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import ApprovalRequestState, ParserKind
from promise_graph.revalidation import RevalidationOutcome
from promisepatch.db.models import ApprovalDecision, RecoveryOption
from promisepatch.domain import (
    analysis,
    approvals,
    cases,
    crash,
    messaging,
    recovery,
    revalidation,
)
from promisepatch.domain.adapters import FakeEffectAdapter, ProviderBehaviour

pytestmark = pytest.mark.integration

A, B, C, D, E, F = (
    ho.PROMISE_A,
    ho.PROMISE_B,
    ho.PROMISE_C,
    ho.PROMISE_D,
    ho.PROMISE_E,
    ho.PROMISE_F,
)

UNRELATED_TABLES = ("orders", "order_lines", "reservations", "recipe_versions", "promises")


# ------------------------------------------------------------------------------------ driving


async def waiting_case(intake: Intake, *, adapter: FakeEffectAdapter | None = None) -> UUID:
    """The canonical case: A recovered, B waiting on Tomas, C/D escalated, E/F untouched."""
    opened = await intake.report()
    await intake.drain()
    await intake.answer(opened.case_id, RASPBERRY_ONLY)
    await intake.drain()
    await intake.confirm(opened.case_id)
    await intake.drain(worker=intake.worker(adapter=adapter), limit=40)
    return opened.case_id


async def approved_case(
    intake: Intake, *, adapter: FakeEffectAdapter | None = None
) -> tuple[UUID, Any]:
    """The same case, stopped the instant the customer's literal yes is durable.

    Everything after this point is the revalidation's, which is what makes a mutation applied
    here genuinely "while the case was waiting" rather than a race with the worker.
    """
    case_id = await waiting_case(intake, adapter=adapter)
    request = await the_request(intake)
    await intake.deliver_reply(request.id, "YES")
    await intake.drain_until_decided()
    return case_id, request


async def the_request(intake: Intake) -> Any:
    requests = await intake.requests()
    assert len(requests) == 1
    return requests[0]


async def track_of(intake: Intake, case_id: UUID, promise_id: str) -> Any:
    row = await intake.track(case_id, promise_id)
    assert row is not None
    return row


async def states(intake: Intake, case_id: UUID) -> dict[str, str]:
    return {track.promise_id: track.state for track in await intake.tracks(case_id)}


async def amendments_for(intake: Intake, track_id: UUID) -> list[Any]:
    """Order-system effects for one track. The approval message names the track too."""
    return [
        row for row in await intake.effects_for(track_id) if row.kind == recovery.EFFECT_ORDER_AMEND
    ]


async def audit_types(intake: Intake, case_id: UUID) -> list[str]:
    return [row.type for row in await intake.audits(case_id)]


async def revalidation_result(intake: Intake, case_id: UUID, track_id: UUID) -> Any:
    """What the checklist recorded on its own step row."""
    step = await intake.step_named(case_id, cases.revalidate_step_key(track_id))
    assert step is not None, "the decision did not enqueue a revalidation"
    return step


async def checks_of(intake: Intake, case_id: UUID, track_id: UUID) -> list[dict[str, Any]]:
    step = await revalidation_result(intake, case_id, track_id)
    return list(step.result.get("checks", []))


async def refused(
    intake: Intake, case_id: UUID, track_id: UUID, index: int, *, amendments: int = 0
) -> None:
    """The whole shape of a refusal: this check decided it, and nothing new was sent.

    ``amendments`` is the number of order-system effects this track is *already* entitled to.
    It is zero everywhere except the replay tests, where the point is that a track which has
    legitimately recovered once does not recover twice.
    """
    step = await revalidation_result(intake, case_id, track_id)
    assert step.result["deciding_check"] == index, step.result
    checks = list(step.result["checks"])
    assert len(checks) == 10
    assert [check["index"] for check in checks] == list(range(1, 11))
    assert not checks[index - 1]["passed"]
    assert all(check["passed"] for check in checks[: index - 1])
    assert len(await amendments_for(intake, track_id)) == amendments


# ============================================================ the canonical successful checklist


async def test_all_ten_checks_pass_against_an_untouched_world(physical: Intake) -> None:
    """§14.3, run for real: ten named checks, every one of them evaluated and every one true."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    await physical.drain(limit=40)

    checks = await checks_of(physical, case_id, track_b.id)
    assert len(checks) == 10
    assert [check["index"] for check in checks] == list(range(1, 11))
    assert all(check["passed"] for check in checks), checks
    assert all(check["expected"] and check["actual"] for check in checks)
    step = await revalidation_result(physical, case_id, track_b.id)
    assert step.result["outcome"] == RevalidationOutcome.PROCEED.value


async def test_every_check_is_its_own_audit_row_with_the_values_it_compared(
    physical: Intake,
) -> None:
    """§22: the Audit screen shows all ten with their values, so all ten are rows."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    await physical.drain(limit=40)

    rows = [
        row
        for row in await physical.audits(case_id)
        if row.type == revalidation.AUDIT_REVALIDATION_CHECK
    ]
    assert len(rows) == 10
    assert sorted(row.provenance["check"] for row in rows) == list(range(1, 11))
    for row in rows:
        assert row.track_id == track_b.id
        assert row.provenance["request_id"] == str(request.id)
        assert row.provenance["name"]
        assert row.before["expected"]
        assert row.after["actual"]
        assert row.after["passed"] is True
        assert row.authority == "NONE"


async def test_a_passing_revalidation_takes_the_case_to_reconciling(physical: Intake) -> None:
    """§14.2: valid + APPROVE -> RECONCILING. Not RECOVERED, and not by the revalidator."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    seq = await physical.latest_event_seq()

    # One cycle at a time, stopping the moment the checklist has committed.
    worker = physical.worker()
    for _ in range(12):
        step = await physical.step_named(case_id, cases.revalidate_step_key(track_b.id))
        if step is not None and step.state == "DONE":
            break
        await worker.run_once()

    assert (await physical.case(case_id)).state == cases.CASE_RECONCILING
    assert (await track_of(physical, case_id, B)).state != recovery.TRACK_RECOVERED
    types = [event.type for event in await physical.events_after(seq)]
    assert revalidation.EVENT_TRACK_REVALIDATION_PASSED in types
    assert cases.EVENT_CASE_RECONCILING in types


async def test_the_approved_recovery_runs_through_the_existing_saga(physical: Intake) -> None:
    """The same ``APPLY_RECOVERY`` an automatic track uses: one step, one key, one effect."""
    adapter = FakeEffectAdapter()
    case_id, request = await approved_case(physical, adapter=adapter)
    track_b = await track_of(physical, case_id, B)

    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)

    amendments = await amendments_for(physical, track_b.id)
    assert len(amendments) == 1
    key = recovery.amend_idempotency_key(
        track_id=track_b.id,
        option_id=request.option_id,
        order_version=request.captured_order_version,
    )
    assert amendments[0].idempotency_key == key
    assert amendments[0].state == "DELIVERED"
    assert amendments[0].payload["option_id"] == str(request.option_id)
    assert adapter.effect_for(key) is not None


async def test_the_option_that_executes_is_the_one_the_customer_approved(
    physical: Intake,
) -> None:
    """Raspberry Rose v2 -> the pre-authored Strawberry Crown v3, and nothing else."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    await physical.drain(limit=40)

    amendment = (await amendments_for(physical, track_b.id))[0]
    assert amendment.payload["from_version_id"] == ho.RRC_V2
    assert amendment.payload["to_version_id"] == ho.RRC_V3
    assert amendment.payload["order_line_id"] == ho.LINE_B
    assert UUID(amendment.payload["option_id"]) == request.option_id


async def test_the_case_reaches_a_terminal_state_with_every_track_terminal(
    physical: Intake,
) -> None:
    """§14.1's ending: A and B recovered, C and D on the owner's desk, E and F untouched."""
    case_id, _ = await approved_case(physical)

    await physical.drain(limit=40)

    assert await states(physical, case_id) == {
        A: recovery.TRACK_RECOVERED,
        B: recovery.TRACK_RECOVERED,
        C: recovery.TRACK_ESCALATED,
        D: recovery.TRACK_ESCALATED,
        E: "UNAFFECTED",
        F: "UNAFFECTED",
    }
    case = await physical.case(case_id)
    assert case.state == cases.CASE_RESOLVED
    # Escalated is a legitimate terminal outcome; it is also a person's problem.
    assert case.needs_owner_attention is True


async def test_the_case_walks_the_frozen_states_in_order(physical: Intake) -> None:
    """WAITING -> REVALIDATING -> RECONCILING -> RESOLVED, with nothing invented in between."""
    seq = await physical.latest_event_seq()
    case_id, _ = await approved_case(physical)
    await physical.drain(limit=40)

    types = [event.type for event in await physical.events_after(seq)]
    milestones = [
        name
        for name in types
        if name
        in {
            cases.EVENT_CASE_WAITING,
            cases.EVENT_CASE_REVALIDATION_READY,
            cases.EVENT_CASE_RECONCILING,
            cases.EVENT_CASE_RESOLVED,
        }
    ]
    assert milestones == [
        cases.EVENT_CASE_WAITING,
        cases.EVENT_CASE_REVALIDATION_READY,
        cases.EVENT_CASE_RECONCILING,
        cases.EVENT_CASE_RESOLVED,
    ]
    assert case_id is not None


async def test_the_amendment_is_audited_as_the_customers_own_authority(
    physical: Intake,
) -> None:
    """§46: worker confirmed the plan, the customer approved this change, revalidation passed."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    await physical.drain(limit=40)

    applied = [
        row
        for row in await physical.audits(case_id)
        if row.type == recovery.AUDIT_RECOVERY_APPLIED and row.track_id == track_b.id
    ]
    assert len(applied) == 1
    row = applied[0]
    assert row.authority == "HUMAN_APPROVAL"
    assert row.provenance["approval_request_id"] == str(request.id)
    assert row.provenance["customer_decision"] == "APPROVE"
    assert row.provenance["parser"] == ParserKind.LITERAL.value
    assert row.provenance["sender_identity"] == TOMAS_CHANNEL
    assert row.provenance["approval_decision_id"]

    passed = [
        row
        for row in await physical.audits(case_id)
        if row.type == revalidation.AUDIT_REVALIDATION_PASSED
    ]
    assert len(passed) == 1
    assert passed[0].authority == "HUMAN_APPROVAL"
    assert passed[0].provenance["current_fingerprint"]


async def test_the_automatic_track_is_still_authorised_by_policy_and_not_by_consent(
    physical: Intake,
) -> None:
    """A recovered under the order's own pre-approval. The two authorities stay distinct."""
    case_id, _ = await approved_case(physical)
    track_a = await track_of(physical, case_id, A)

    await physical.drain(limit=40)

    applied = [
        row
        for row in await physical.audits(case_id)
        if row.type == recovery.AUDIT_RECOVERY_APPLIED and row.track_id == track_a.id
    ]
    assert len(applied) == 1
    assert applied[0].authority in {"POLICY", "CONSTRAINT"}
    assert applied[0].authority != "HUMAN_APPROVAL"
    assert "approval_decision_id" not in applied[0].provenance


# ================================================================= check 5, and what A took


async def test_the_substitute_check_counts_the_recovery_that_already_happened(
    physical: Intake,
) -> None:
    """§9.5: A's strawberries are gone before B's approval is honoured, and are subtracted."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED

    await physical.drain(limit=40)

    check = (await checks_of(physical, case_id, track_b.id))[4]
    assert check["passed"]
    option_a = await physical.options((await track_of(physical, case_id, A)).id)
    taken = next(
        row.required_quantity for row in option_a if row.substitute_resource_id == ho.STRAWBERRIES
    )
    on_hand = Decimal(str(await physical.on_hand(ho.STRAWBERRIES)))
    # The availability B was measured against is short of the shelf by at least A's share.
    assert Decimal(check["actual"]) <= on_hand - taken


async def test_a_substitute_eaten_while_waiting_makes_the_approval_stale(
    physical: Intake,
) -> None:
    """Consent to a change that can no longer be made is not consent to make it anyway."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.consume_stock(ho.STRAWBERRIES, "-7.0")

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 5)
    # The refusal itself is the assertion; the re-plan it enqueues has since moved the track on.
    assert recovery.AUDIT_RECOVERY_STALE in await audit_types(physical, case_id)


# ============================================================================ check 2: the order


async def test_an_order_amended_while_waiting_makes_the_approval_stale(
    physical: Intake,
) -> None:
    """The mandatory proof: planned at version N, approved, amended to N+1, refused."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.bump_order_version(ho.ORDER_B)

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 2)
    assert recovery.AUDIT_RECOVERY_STALE in await audit_types(physical, case_id)
    checks = await checks_of(physical, case_id, track_b.id)
    assert f"v{request.captured_order_version}" in checks[1]["expected"]
    assert f"v{request.captured_order_version + 1}" in checks[1]["actual"]


async def test_a_stale_refusal_keeps_every_word_the_customer_said(physical: Intake) -> None:
    """§26: the plan, the request and the decision are evidence, and evidence is not deleted."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.bump_order_version(ho.ORDER_B)

    await physical.drain(limit=40)

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVE"
    assert decisions[0].raw_text == "YES"
    after = await the_request(physical)
    assert after.captured_order_version == request.captured_order_version
    assert after.captured_fingerprint == request.captured_fingerprint
    assert after.captured_recipe_version_id == request.captured_recipe_version_id
    assert after.decided is True
    # The option the customer was actually asked about outlives its own supersession.
    async with physical.database.connect() as connection:
        option = (
            await connection.execute(
                select(RecoveryOption).where(RecoveryOption.id == request.option_id)
            )
        ).one_or_none()
    assert option is not None
    assert track_b.id is not None


async def test_a_stale_refusal_is_audited_as_ours_and_not_as_the_customers(
    physical: Intake,
) -> None:
    """ "We refused to act on your yes" must never read like "you said no"."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.bump_order_version(ho.ORDER_B)

    await physical.drain(limit=40)

    stale = [
        row
        for row in await physical.audits(case_id)
        if row.type == recovery.AUDIT_RECOVERY_STALE and row.track_id == track_b.id
    ]
    assert len(stale) == 1
    assert stale[0].actor_kind == "SYSTEM"
    assert stale[0].authority == "NONE"
    assert stale[0].after["deciding_check"] == 2
    assert approvals.ESCALATION_APPROVAL_DECLINED not in str(stale[0].after)


# ==================================================================== check 3: the recipe version


async def test_a_repinned_recipe_version_makes_the_approval_stale(physical: Intake) -> None:
    """An approval names a change from one authored version to another, and both are pinned."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    # Without moving the order version, so check 2 cannot claim the failure first.
    await physical.repin_order_line(ho.LINE_B, ho.RRC_V3, bump_order=False)

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 3)
    checks = await checks_of(physical, case_id, track_b.id)
    assert checks[2]["expected"] == ho.RRC_V2
    assert checks[2]["actual"] == ho.RRC_V3


# ======================================================================= check 4: the constraints


async def test_a_rewritten_constraint_snapshot_makes_the_approval_stale(
    physical: Intake,
) -> None:
    """ASK_BEFORE_VISIBLE_CHANGE became NO_SUBSTITUTION. The old yes cannot survive that."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.set_constraint_kind(ho.CONSTRAINT_B_ASK, "NO_SUBSTITUTION")

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 4)
    checks = await checks_of(physical, case_id, track_b.id)
    assert checks[3]["expected"] != checks[3]["actual"]


async def test_the_fresh_plan_reads_the_new_constraint_rather_than_being_told_it(
    physical: Intake,
) -> None:
    """No branch anywhere expects BLOCKED: the engine derives it from the row a human changed."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.set_constraint_kind(ho.CONSTRAINT_B_ASK, "NO_SUBSTITUTION")

    await physical.drain(limit=40)

    replan = await physical.step_named(case_id, analysis.replan_step_key(track_b.id))
    assert replan is not None
    assert replan.state == "DONE"
    assert replan.result["classification"] == "BLOCKED"
    assert replan.result["rule_id"] == "R-NOSUB"


# ==================================================================== check 6: the production task


async def test_a_task_that_has_started_makes_the_approval_stale(physical: Intake) -> None:
    """The kitchen is already making it. Amending the order now would change nothing real."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.set_task_state(ho.LINE_B, "STARTED")

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 6)


async def test_a_task_whose_start_has_passed_makes_the_approval_stale(
    physical: Intake,
) -> None:
    """Compared against the database's clock, never the worker's."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.bring_task_start_forward(ho.LINE_B)

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 6)


async def test_a_task_another_case_holds_makes_the_approval_stale(physical: Intake) -> None:
    """§13.5's hold belongs to the case that took it; releasing it is that owner's decision."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.hold_task_for(ho.LINE_B, uuid4())

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 6)


async def test_a_task_this_case_holds_does_not_block_its_own_recovery(
    physical: Intake,
) -> None:
    """The other half of check 6, so the rule is a distinction and not a blanket refusal."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.hold_task_for(ho.LINE_B, case_id)

    await physical.drain(limit=40)

    checks = await checks_of(physical, case_id, track_b.id)
    assert checks[5]["passed"], checks[5]


# ========================================================================== check 7: the deadline


async def test_an_approval_that_expires_before_the_worker_runs_executes_nothing(
    physical: Intake,
) -> None:
    """Valid when it arrived, out of time when it was going to be acted on."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.close_window(request.id)

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 7)
    step = await revalidation_result(physical, case_id, track_b.id)
    assert step.result["outcome"] == RevalidationOutcome.EXPIRED.value
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    assert (await physical.case(case_id)).needs_owner_attention is True


async def test_an_expired_authority_still_documents_what_the_customer_said(
    physical: Intake,
) -> None:
    """The APPROVE row is a record of a sentence, not a licence with no end date."""
    case_id, request = await approved_case(physical)
    await physical.close_window(request.id)

    await physical.drain(limit=40)

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVE"
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED


# ======================================================================= checks 8, 9 and 10


async def test_a_recorded_decision_cannot_be_rewritten_by_anything(physical: Intake) -> None:
    """The strongest form of check 8's premise: the sender on a decision is not editable.

    Attempted with the migration credential, which is the most authority the deployment has
    anywhere, and refused by the append-only trigger rather than by a grant. A customer's
    recorded consent is a fact about something they did; correcting one means appending, and
    there is no path -- operator, application or otherwise -- that overwrites it in place.
    """
    from sqlalchemy.exc import ProgrammingError

    case_id, request = await approved_case(physical)

    with pytest.raises(ProgrammingError, match="append-only"):
        await physical.rewrite_decision_sender(request.id, "tg:9999")

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].sender_identity == TOMAS_CHANNEL
    assert case_id is not None


async def test_a_decision_that_no_longer_matches_the_orders_channel_authorises_nothing(
    physical: Intake,
) -> None:
    """Check 8: the reply came from the number we asked, and that number is read again now."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.move_customer_channel(request.id, "tg:9999")

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 8)
    step = await revalidation_result(physical, case_id, track_b.id)
    assert step.result["outcome"] == RevalidationOutcome.UNAUTHORIZED.value
    # §14.3: the track keeps waiting and a person is told. It is not escalated by a bad record.
    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert (await physical.case(case_id)).needs_owner_attention is True
    assert approvals.AUDIT_UNAUTHORIZED_APPROVAL in await audit_types(physical, case_id)


async def test_a_decision_whose_stored_reply_came_from_elsewhere_authorises_nothing(
    physical: Intake,
) -> None:
    """Check 8 against the record behind the claim, not the denormalised copy of it."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.corrupt_reply_sender(request.id, "tg:9999")

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 8)
    checks = await checks_of(physical, case_id, track_b.id)
    assert "broken chain" in checks[7]["actual"]


async def test_the_database_refuses_a_decision_the_literal_parser_did_not_make(
    physical: Intake,
) -> None:
    """Check 9 cannot be reached with a non-literal decision, because one cannot be stored.

    The constraint is the guarantee. A model's reading of free text is not a row this database
    will accept, so "the LLM never produces a consent decision" is enforced rather than checked;
    the evaluator's own refusal is pinned in the engine suite, where it needs no database.
    """
    case_id, request = await approved_case(physical)
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with physical.database.begin() as connection:
            from promisepatch.db.uow import Actor, UnitOfWork

            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="REVALIDATION_TEST_SETUP",
                actor=Actor(kind="SYSTEM", id="revalidation-tests"),
                authority="NONE",
            ) as write:
                await write.execute(
                    insert(ApprovalDecision).values(
                        id=uuid4(),
                        request_id=request.id,
                        decision="APPROVE",
                        parser=ParserKind.LLM.value,
                        sender_identity=TOMAS_CHANNEL,
                        provider_message_id=f"forged-{uuid4()}",
                        raw_text="strawberries work",
                        received_at=physical.observed_at,
                    )
                )
    assert case_id is not None


async def test_a_superseded_request_authorises_nothing(physical: Intake) -> None:
    """Check 10: a request a re-plan withdrew carries no authority, whatever it once carried."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.supersede_request(request.id)

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 10)
    step = await revalidation_result(physical, case_id, track_b.id)
    assert step.result["outcome"] == RevalidationOutcome.NOOP.value
    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER


async def test_a_decision_bound_to_another_plan_authorises_nothing(physical: Intake) -> None:
    """Consent is to a named change. Point the track elsewhere and the consent stops fitting."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    other = uuid4()
    await physical.rebind_chosen_option(track_b.id, other)

    await physical.drain(limit=40)

    await refused(physical, case_id, track_b.id, 10)
    checks = await checks_of(physical, case_id, track_b.id)
    assert str(request.option_id) in checks[9]["expected"]
    assert str(other) in checks[9]["actual"]


async def test_a_revalidation_of_a_settled_track_refuses_at_the_first_check(
    physical: Intake,
) -> None:
    """A track that has already recovered is not waiting on anybody, and check 1 says so."""
    adapter = FakeEffectAdapter()
    case_id, _ = await approved_case(physical, adapter=adapter)
    track_b = await track_of(physical, case_id, B)
    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)
    assert len(await amendments_for(physical, track_b.id)) == 1
    effects_before = adapter.effect_count

    await physical.reopen_for_revalidation(case_id, cases.revalidate_step_key(track_b.id))
    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)

    await refused(physical, case_id, track_b.id, 1, amendments=1)
    assert adapter.effect_count == effects_before


async def test_one_decision_cannot_authorise_a_second_recovery(physical: Intake) -> None:
    """The one-consumption rule, reached directly past the guard that would refuse first.

    Check 1 already stops a replay of a settled track, so the world is wound back further than
    any code path could take it -- the track put back to waiting and the case back to
    revalidating -- to ask whether the *decision* still authorises anything. It does not: it has
    been spent, and the step ledger is where that is written down.
    """
    adapter = FakeEffectAdapter()
    case_id, _ = await approved_case(physical, adapter=adapter)
    track_b = await track_of(physical, case_id, B)
    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)
    assert len(await amendments_for(physical, track_b.id)) == 1
    effects_before = adapter.effect_count

    await physical.reopen_for_revalidation(
        case_id, cases.revalidate_step_key(track_b.id), track_id=track_b.id
    )
    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)

    await refused(physical, case_id, track_b.id, 10, amendments=1)
    checks = await checks_of(physical, case_id, track_b.id)
    assert "already consumed" in checks[9]["actual"]
    assert adapter.effect_count == effects_before


# ============================================================ first-failure determinism


async def test_the_lowest_numbered_failure_decides_the_outcome(physical: Intake) -> None:
    """Order, recipe, constraint, stock, task and deadline all wrong at once resolves to check 2."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    await physical.bump_order_version(ho.ORDER_B)
    await physical.repin_order_line(ho.LINE_B, ho.RRC_V3, bump_order=False)
    await physical.set_constraint_kind(ho.CONSTRAINT_B_ASK, "NO_SUBSTITUTION")
    await physical.consume_stock(ho.STRAWBERRIES, "-7.0")
    await physical.set_task_state(ho.LINE_B, "STARTED")
    await physical.close_window(request.id)

    await physical.drain(limit=40)

    checks = await checks_of(physical, case_id, track_b.id)
    failed = {check["index"] for check in checks if not check["passed"]}
    assert {2, 3, 4, 6, 7} <= failed
    step = await revalidation_result(physical, case_id, track_b.id)
    assert step.result["deciding_check"] == 2
    assert step.result["outcome"] == RevalidationOutcome.STALE.value
    assert await amendments_for(physical, track_b.id) == []


# ================================================================ the stale re-plan


async def test_a_stale_track_is_re_planned_against_current_truth(physical: Intake) -> None:
    """§14.4: propagation runs again for that promise, and only that promise."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    before = await states(physical, case_id)
    await physical.bump_order_version(ho.ORDER_B)

    await physical.drain(limit=40)

    replan = await physical.step_named(case_id, analysis.replan_step_key(track_b.id))
    assert replan is not None
    assert replan.state == "DONE"
    assert replan.result["outcome"] == "REPLANNED"
    after = await states(physical, case_id)
    # Only B moved. A stayed recovered, C and D stayed escalated, E and F stayed unaffected.
    assert {promise: state for promise, state in after.items() if promise != B} == {
        promise: state for promise, state in before.items() if promise != B
    }


async def test_a_re_planned_track_starts_again_with_no_consent_at_all(
    physical: Intake,
) -> None:
    """The strongest rule in the slice: an old yes never authorises a new plan."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.bump_order_version(ho.ORDER_B)

    await physical.drain(limit=40)

    after = await the_request(physical)
    assert after.state == ApprovalRequestState.SUPERSEDED.value
    replanned = await track_of(physical, case_id, B)
    assert replanned.approval_request_id is None
    assert replanned.state == analysis.TRACK_PENDING
    assert (await physical.case(case_id)).state == cases.CASE_PLANNED
    # The decision survives as history and authorises nothing.
    assert len(await physical.decisions()) == 1
    assert await amendments_for(physical, track_b.id) == []


async def _notices(intake: Intake, track_id: UUID) -> list[Any]:
    """Every §14.4 supersede notice queued for one track, by its own idempotency shape."""
    return [
        row
        for row in await intake.effects_for(track_id)
        if row.kind == approvals.EFFECT_MESSAGE_SEND
        and str(row.idempotency_key).startswith("pp:supersede:")
    ]


async def test_a_customer_whose_order_moved_is_told_once_and_asked_for_nothing(
    physical: Intake,
) -> None:
    """§14.4 and §23: the customer is told their order changed, exactly once.

    The strongest part is what the message is *not*. It carries no reply instruction, so it
    cannot be answered and cannot become a second consent; and it does not travel under the
    ``request_id`` key, because the request it is about is superseded by the same transaction
    that queues it and the dispatcher's window guard would refuse it unsent.
    """
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    request = await the_request(physical)

    await physical.bump_order_version(ho.ORDER_B)
    await physical.drain(limit=40)

    notices = await _notices(physical, track_b.id)
    assert len(notices) == 1
    assert notices[0].idempotency_key == analysis.supersede_idempotency_key(request.id)
    assert notices[0].payload["superseded_request_id"] == str(request.id)
    assert "request_id" not in notices[0].payload
    assert messaging.SUPERSEDE_NOTICE in notices[0].payload["text"]
    assert messaging.CONSENT_INSTRUCTION not in notices[0].payload["text"]
    assert await amendments_for(physical, track_b.id) == []


async def test_a_re_plan_the_customers_order_did_not_cause_tells_them_nothing(
    physical: Intake,
) -> None:
    """The message says their order changed. Here it did not, so there is no message.

    The owner rewrote a constraint, which makes the approval stale and re-plans the promise just
    as an order edit would. Telling Tomas his order changed would be a false sentence about his
    own order, and §23 gives that row no customer message.
    """
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    await physical.set_constraint_kind(ho.CONSTRAINT_B_ASK, "NO_SUBSTITUTION")
    await physical.drain(limit=40)

    replan = await physical.step_named(case_id, analysis.replan_step_key(track_b.id))
    assert replan is not None
    assert replan.state == "DONE"
    assert replan.result["supersede_notice"] is None
    assert await _notices(physical, track_b.id) == []


async def test_a_re_plan_produces_a_fresh_fingerprint_and_options(physical: Intake) -> None:
    """The new plan is derived, not copied: it is stamped against the world that now exists."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    planned_before = track_b.fingerprint
    await physical.bump_order_version(ho.ORDER_B)

    await physical.drain(limit=40)

    replanned = await track_of(physical, case_id, B)
    assert replanned.fingerprint is not None
    assert replanned.fingerprint != planned_before
    assert await physical.options(track_b.id)


async def test_the_re_plan_reads_live_state_for_every_promise_it_evaluates(
    physical: Intake,
) -> None:
    """The engine really re-runs: a line re-pinned in the order system changes what it concludes.

    D is BLOCKED in the fixture because its raspberries do not arrive before its task starts.
    Re-pin it to the pre-authored Lemon Curd version -- a change the order system makes, not us --
    and a fresh analysis says so. Its track stays ``ESCALATED`` because escalation is terminal
    and belongs to the owner now; what the re-plan records is what the engine saw.
    """
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.repin_order_line(ho.LINE_D, ho.LCL_V1)
    await physical.bump_order_version(ho.ORDER_B)

    await physical.drain(limit=40)

    replan = [
        row
        for row in await physical.audits(case_id)
        if row.type == analysis.AUDIT_TRACK_REPLANNED and row.track_id == track_b.id
    ]
    assert len(replan) == 1
    assert replan[0].provenance["classifications"][D] == "UNAFFECTED"
    assert (await track_of(physical, case_id, D)).state == recovery.TRACK_ESCALATED


async def test_a_stale_case_does_not_resolve_while_it_is_being_re_planned(
    physical: Intake,
) -> None:
    """§23: a track awaiting a re-plan is outstanding work, and outstanding work blocks the end."""
    case_id, _ = await approved_case(physical)
    await physical.bump_order_version(ho.ORDER_B)

    await physical.drain(limit=40)

    assert (await physical.case(case_id)).state != cases.CASE_RESOLVED


# ==================================================================== declines and expiries end


async def test_a_declined_case_reaches_a_terminal_state(physical: Intake) -> None:
    """§44: no approved execution is required for a case to finish."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await physical.deliver_reply(request.id, "NO")
    await physical.drain(limit=40)

    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    case = await physical.case(case_id)
    assert case.state == cases.CASE_RESOLVED
    assert case.needs_owner_attention is True
    assert await amendments_for(physical, (await track_of(physical, case_id, B)).id) == []


async def test_an_expired_case_reaches_a_terminal_state(physical: Intake) -> None:
    """The other unapproved ending, and no decision is fabricated to reach it."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    await physical.close_window(request.id)

    await physical.drain(limit=40)

    assert await physical.decisions() == []
    assert (await the_request(physical)).state == ApprovalRequestState.EXPIRED.value
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED


# ============================================================================ reconciliation


async def test_a_case_cannot_resolve_while_a_track_is_still_applying(
    physical: Intake,
) -> None:
    """The reconciler refuses to finish work that is still going on, and says which track."""
    adapter = FakeEffectAdapter()
    adapter.fail_with = None
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    # Let the checklist pass and the amendment go out, then stop before it is acknowledged.
    stalling = FakeEffectAdapter(script=[ProviderBehaviour.TIMEOUT_BEFORE_APPLYING] * 8)
    await physical.drain(worker=physical.worker(adapter=stalling), limit=40)

    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_APPLYING
    reconcile = await physical.step_named(case_id, cases.reconcile_step_key(case_id))
    assert reconcile is not None
    assert reconcile.state == "SKIPPED"
    assert track_b.id is not None
    assert (await physical.case(case_id)).state == cases.CASE_RECONCILING


async def test_resolution_writes_nothing_to_unrelated_business_state(
    physical: Intake,
) -> None:
    """§13.7: reconciling a case is not a licence to touch the rest of the order book."""
    case_id, _ = await approved_case(physical)
    before = await physical.order_book()
    tasks_before = await physical.tasks()

    await physical.drain(limit=40)

    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED
    after = await physical.order_book()
    for table in UNRELATED_TABLES:
        assert after[table] == before[table], table
    assert await physical.tasks() == tasks_before


async def test_nothing_unrelated_is_ever_touched_by_the_whole_run(physical: Intake) -> None:
    """E and F: no effect, no request, no reply, no revalidation, no re-plan."""
    case_id, _ = await approved_case(physical)

    await physical.drain(limit=40)

    tracks = {track.promise_id: track.id for track in await physical.tracks(case_id)}
    for promise_id in (E, F):
        assert await physical.effects_for(tracks[promise_id]) == []
        assert await physical.request_for(tracks[promise_id]) is None
        assert (
            await physical.step_named(case_id, cases.revalidate_step_key(tracks[promise_id]))
            is None
        )
        assert (
            await physical.step_named(case_id, analysis.replan_step_key(tracks[promise_id])) is None
        )
    assert [row.track_id for row in await physical.requests()] == [tracks[B]]


# ================================================================== idempotency and duplicates


async def test_a_revalidation_delivered_twice_has_one_logical_outcome(
    physical: Intake,
) -> None:
    """The same work run again finds a case that has moved on, and writes nothing."""
    adapter = FakeEffectAdapter()
    case_id, _ = await approved_case(physical, adapter=adapter)
    track_b = await track_of(physical, case_id, B)
    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)
    effects = adapter.effect_count
    audits = len(await physical.audits(case_id))

    step = await revalidation_result(physical, case_id, track_b.id)
    await physical.requeue(step.id)
    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)

    assert adapter.effect_count == effects
    assert len(await amendments_for(physical, track_b.id)) == 1
    replayed = await revalidation_result(physical, case_id, track_b.id)
    assert replayed.result["outcome"] == "NOT_APPLICABLE"
    # The replay is audited as a step and changes nothing else about the case.
    assert len(await physical.audits(case_id)) == audits + 1


async def test_a_stale_revalidation_delivered_twice_re_plans_once(physical: Intake) -> None:
    """A second stale pass must not produce a second generation of plan work."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.bump_order_version(ho.ORDER_B)
    await physical.drain(limit=40)

    replan_before = await physical.step_named(case_id, analysis.replan_step_key(track_b.id))
    assert replan_before is not None
    step = await revalidation_result(physical, case_id, track_b.id)
    await physical.requeue(step.id)
    await physical.drain(limit=40)

    replan_after = await physical.step_named(case_id, analysis.replan_step_key(track_b.id))
    assert replan_after is not None
    assert replan_after.id == replan_before.id
    assert await amendments_for(physical, track_b.id) == []


async def test_a_replayed_re_plan_writes_the_same_plan_once(physical: Intake) -> None:
    """The re-plan is idempotent by posture: a track that is no longer stale is left alone."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.bump_order_version(ho.ORDER_B)
    await physical.drain(limit=40)
    options_before = [row.id for row in await physical.options(track_b.id)]

    replan = await physical.step_named(case_id, analysis.replan_step_key(track_b.id))
    assert replan is not None
    await physical.requeue(replan.id)
    await physical.drain(limit=40)

    assert [row.id for row in await physical.options(track_b.id)] == options_before
    assert len(await physical.requests()) == 1


# ============================================================================= crash boundaries


async def test_a_worker_that_dies_before_the_revalidation_commits_leaves_nothing(
    physical: Intake,
) -> None:
    """Before the boundary: no transition, no recovery work, no evidence."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    audits = len(await physical.audits(case_id))
    events = len(await physical.events(case_id))

    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.worker().run_once()

    assert len(await physical.audits(case_id)) == audits
    assert len(await physical.events(case_id)) == events
    assert await physical.step_named(case_id, recovery.apply_step_key(track_b.id)) is None
    assert (await physical.case(case_id)).state == cases.CASE_REVALIDATING


async def test_a_worker_that_dies_after_the_revalidation_commits_loses_nothing(
    physical: Intake,
) -> None:
    """After the boundary: the transition is durable and the recovery work survives the process."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    worker = physical.worker(identity="worker-that-dies")
    with crash.arm(crash.AFTER_TRANSITION_COMMIT):
        for _ in range(12):
            try:
                await worker.run_once()
            except crash.WorkerDied:
                step = await physical.step_named(case_id, cases.revalidate_step_key(track_b.id))
                if step is not None and step.state == "DONE":
                    break

    assert (await physical.case(case_id)).state == cases.CASE_RECONCILING
    assert await physical.step_named(case_id, recovery.apply_step_key(track_b.id)) is not None

    await physical.drain(worker=physical.worker(identity="worker-after-the-crash"), limit=40)
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_RECOVERED
    assert len(await amendments_for(physical, track_b.id)) == 1


async def test_a_lost_revalidation_lease_is_picked_up_by_a_fresh_worker(
    physical: Intake,
) -> None:
    """A claim is a statement about the past. A dead worker's step comes back on its own."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    with crash.arm(crash.DURING_HANDLER), pytest.raises(crash.WorkerDied):
        await physical.worker(identity="worker-that-vanished").run_once()

    step = await revalidation_result(physical, case_id, track_b.id)
    assert step.state == "IN_FLIGHT"
    await physical.expire_lease(step.id)

    await physical.drain(worker=physical.worker(identity="worker-that-took-over"), limit=40)
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_RECOVERED
    assert len(await amendments_for(physical, track_b.id)) == 1


async def test_a_worker_that_dies_before_the_stale_commit_leaves_the_plan_alone(
    physical: Intake,
) -> None:
    """A refusal that never committed leaves the track exactly as the customer left it."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.bump_order_version(ho.ORDER_B)

    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.worker().run_once()

    after = await track_of(physical, case_id, B)
    assert after.state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert after.fingerprint == track_b.fingerprint
    assert after.chosen_option_id == track_b.chosen_option_id
    assert (await the_request(physical)).state == ApprovalRequestState.ANSWERED.value


async def test_the_stale_re_plan_survives_the_worker_that_started_it(
    physical: Intake,
) -> None:
    """After the stale commit: the refusal is durable and a fresh worker finishes the re-plan."""
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.bump_order_version(ho.ORDER_B)

    worker = physical.worker(identity="worker-that-dies")
    with crash.arm(crash.AFTER_TRANSITION_COMMIT):
        for _ in range(12):
            try:
                await worker.run_once()
            except crash.WorkerDied:
                if (await track_of(physical, case_id, B)).state == recovery.TRACK_STALE:
                    break

    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_STALE
    await physical.drain(worker=physical.worker(identity="worker-after-the-crash"), limit=40)
    replan = await physical.step_named(case_id, analysis.replan_step_key(track_b.id))
    assert replan is not None
    assert replan.state == "DONE"


async def test_an_approved_amendment_applied_twice_by_transport_is_one_effect(
    physical: Intake,
) -> None:
    """The honest guarantee, on the approved path: two transport calls, one logical effect."""
    adapter = FakeEffectAdapter()
    case_id, request = await approved_case(physical, adapter=adapter)
    track_b = await track_of(physical, case_id, B)
    # Armed only now: A's amendment and the approval message have already gone out cleanly, and
    # the window under test is the one after B's own approved amendment reaches the provider.
    adapter.script = [ProviderBehaviour.APPLY_THEN_LOSE_RESPONSE]

    worker = physical.worker(adapter=adapter)
    await physical.drain(worker=worker, limit=40)
    amendment = (await amendments_for(physical, track_b.id))[0]
    await physical.make_effect_due(amendment.id)
    await physical.drain(worker=worker, limit=40)

    key = recovery.amend_idempotency_key(
        track_id=track_b.id,
        option_id=request.option_id,
        order_version=request.captured_order_version,
    )
    sent = [attempt for attempt in adapter.attempts if attempt.idempotency_key == key]
    assert len(sent) == 2
    assert len({attempt.idempotency_key for attempt in sent}) == 1
    assert len([effect for effect in adapter.effects if effect == key]) == 1
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_RECOVERED


async def test_a_recovered_case_is_finished_by_whichever_worker_comes_next(
    physical: Intake,
) -> None:
    """After B recovered and before the case resolved: nothing is repaired by hand."""
    adapter = FakeEffectAdapter()
    case_id, _ = await approved_case(physical, adapter=adapter)

    worker = physical.worker(identity="worker-one", adapter=adapter)
    for _ in range(20):
        await worker.run_once()
        if (await track_of(physical, case_id, B)).state == recovery.TRACK_RECOVERED:
            break
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_RECOVERED

    await physical.drain(worker=physical.worker(identity="worker-two"), limit=20)
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED


# ================================================================================= concurrency


async def test_a_change_to_watched_state_is_seen_by_the_commit_guard(
    physical: Intake,
) -> None:
    """The mechanism that stops an obsolete PASS committing, exercised on its own.

    The fingerprint is the digest of everything a track watches, so comparing the one the
    checks were taken against with the one that holds now answers exactly "did the world move
    while we were deciding". A revalidation that sees this refuses to commit its answer.
    """
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    async with physical.database.connect() as connection:
        seen = await recovery.current_fingerprint(connection, track_b)
        assert not await revalidation.watched_state_moved(connection, track=track_b, seen=seen)

    await physical.bump_order_version(ho.ORDER_B)

    async with physical.database.connect() as connection:
        assert await revalidation.watched_state_moved(connection, track=track_b, seen=seen)
    assert case_id is not None


async def test_a_change_landing_after_a_passing_revalidation_still_stops_the_amendment(
    physical: Intake,
) -> None:
    """The last line of defence: execution revalidates too, so a late change is still refused.

    A change committed in the window between a passing checklist and the transaction that emits
    the amendment cannot be caught by the checklist -- it had already finished. ``APPLY_RECOVERY``
    recomputes the fingerprint inside the transaction that would send the effect, which is what
    makes "no external effect under a plan that no longer describes the world" hold whatever the
    interleaving. That claim is the subject here and it is asserted first: no amendment exists
    for this track afterwards, however the track itself ends up.

    How it ends up is the owner's desk with the kitchen work held. There is no re-plan to
    enqueue from this boundary -- the checklist had already passed, and deriving a fresh plan
    would spend the customer's yes on something they were never asked about -- so a resting
    ``STALE`` would be a promise nothing in the system could ever move again.
    """
    case_id, _ = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)

    # Run only as far as the checklist, which passes against the world as it stands.
    worker = physical.worker()
    for _ in range(12):
        step = await physical.step_named(case_id, cases.revalidate_step_key(track_b.id))
        if step is not None and step.state == "DONE":
            break
        await worker.run_once()
    assert (await physical.case(case_id)).state == cases.CASE_RECONCILING

    await physical.bump_order_version(ho.ORDER_B)
    await physical.drain(limit=40)

    assert await amendments_for(physical, track_b.id) == []
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    assert (await physical.tasks())[f"task-{ho.LINE_B}"] == ("HELD", case_id)
