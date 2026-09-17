"""The trust boundary a plan confirmation stands on, attacked from the side that used to work.

Until this suite existed, a plan confirmation was minted by whoever called the confirming
service. Over the browser that caller was a signed-in person and the durable ``HUMAN_APPROVAL``
audit row was true. Over the MCP surface the caller was a process holding a shared service
token, the attesting identity came from ``PP_SURFACE_WORKER_ID`` -- the server's own
configuration -- and the same row said the same thing about a human nobody had authenticated. An
authenticated host, or a model driving one, could produce durable evidence that a named baker had
approved a plan they had never been read. Host authentication is not human consent; the record
said it was.

So the confirmation now *spends* a durable, plan-bound approval that only a channel where this
system authenticated a person can write, and these tests are about the difference. They come in
the order an attacker would meet them:

* what a caller holding the service credential and nothing else can do,
* what an approval is bound to, and what it therefore cannot be carried to,
* who may leave one,
* what happens when the same yes arrives twice, or is spent twice, or outlives a restart,
* and the two surfaces that still work exactly as they did.

Everything here runs against real PostgreSQL and the real routers. The MCP-facing half drives
the intent API directly, because that is the hop the MCP process makes and the only one it can
make -- it is forbidden the domain, the database and the API package by an import-linter
contract, so a tool call has no other road to a case.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from _intake_support import (
    BAKER,
    CANONICAL_REPORT,
    CORRECTION,
    OWNER,
    RASPBERRY_ONLY,
    Intake,
)
from _intake_support import physical as physical
from _mcp_support import SERVICE_TOKEN
from fastapi import FastAPI
from sqlalchemy import select

from promisepatch.api.routers import intents as intents_router
from promisepatch.config import Settings
from promisepatch.db.models import AuditEvent, PlanApproval
from promisepatch.domain import intake, plan_approval, recovery
from promisepatch.main import create_app

pytestmark = pytest.mark.integration

CONFIRM = "/internal/intents/confirm"
BASE = "http://api.test"


@pytest_asyncio.fixture
async def tools(physical: Intake) -> AsyncIterator[httpx2.AsyncClient]:
    """The intent API as the MCP process reaches it: a service token, and no session anywhere.

    Configured with ``surface_worker_id`` set, which is the point rather than an oversight. The
    surface still has a configured worker -- it attests what a worker *said* -- and the tests
    below show that identity buying nothing at all when the question is who agreed to a plan.
    """
    api: FastAPI = create_app(
        Settings(internal_service_token=SERVICE_TOKEN, surface_worker_id=BAKER)
    )
    api.state.database = physical.database
    transport = httpx2.ASGITransport(app=api)
    async with httpx2.AsyncClient(transport=transport, base_url=BASE) as client:
        yield client


async def confirm(
    client: httpx2.AsyncClient,
    case_id: UUID | str,
    plan_id: str,
    *,
    command_id: UUID | None = None,
    **extra: Any,
) -> httpx2.Response:
    """One ``confirm`` over the service surface, with whatever the caller wants to try adding."""
    body: dict[str, Any] = {
        "command_id": str(command_id or uuid4()),
        "case_id": str(case_id),
        "plan_id": plan_id,
    }
    body.update(extra)
    return await client.post(
        CONFIRM, json=body, headers={intents_router.SERVICE_TOKEN_HEADER: SERVICE_TOKEN}
    )


async def planned(physical_fixture: Intake, *, worker_id: str = BAKER) -> UUID:
    """The canonical case, carried to the point where a plan is waiting for a yes."""
    opened = await physical_fixture.report(CANONICAL_REPORT, worker_id=worker_id)
    await physical_fixture.drain()
    await physical_fixture.answer(opened.case_id, RASPBERRY_ONLY, worker_id=worker_id)
    await physical_fixture.drain()
    return opened.case_id


async def approvals_on(physical_fixture: Intake, case_id: UUID) -> list[Any]:
    async with physical_fixture.database.connect() as connection:
        return list(
            (
                await connection.execute(
                    select(PlanApproval).where(PlanApproval.case_id == case_id)
                )
            ).all()
        )


# ------------------------------------------- what a service credential alone can be made to do


async def test_a_direct_confirm_over_the_service_surface_cannot_manufacture_a_yes(
    tools: httpx2.AsyncClient, physical: Intake
) -> None:
    """The defect, exactly as it was reachable: an authenticated host calling ``confirm``.

    Everything the old caller had is still here -- a valid service token, a real case, the real
    plan identity the surface itself renders, and a case sitting in the one state where a
    confirmation means something. It is refused, nothing is enqueued, no approval row appears,
    and the case is left where it was.
    """
    case_id = await planned(physical)
    plan_id = await physical.plan_id(case_id)

    response = await confirm(tools, case_id, plan_id)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "HUMAN_APPROVAL_REQUIRED"
    assert (await physical.case(case_id)).state == "PLANNED"
    assert await approvals_on(physical, case_id) == []
    assert await physical.effects() == []


async def test_no_field_on_the_confirm_request_can_add_the_missing_approval(
    tools: httpx2.AsyncClient, physical: Intake
) -> None:
    """The refusal is not a field the caller forgot, so no field can supply it.

    Four plausible inventions -- an actor, an approver, an approval identity and a bare claim
    that somebody said yes. The request model forbids extras, so each one is a ``422`` before
    any of it is read, and none of them reaches the domain to be ignored. A caller cannot even
    *express* the thing that would make this call succeed.
    """
    case_id = await planned(physical)
    plan_id = await physical.plan_id(case_id)

    for invented in (
        {"worker_id": BAKER},
        {"approved_by": BAKER},
        {"approval_id": str(uuid4())},
        {"confirmed": True},
    ):
        response = await confirm(tools, case_id, plan_id, **invented)
        assert response.status_code == 422, invented

    assert (await physical.case(case_id)).state == "PLANNED"
    assert await approvals_on(physical, case_id) == []


async def test_the_confirming_function_has_no_parameter_naming_a_person() -> None:
    """The structural half of the same claim, asserted where it is true or not.

    A refusal can be forgotten by a new caller; a parameter that does not exist cannot be
    filled in by one. ``confirm_plan`` takes an approval identity and no worker, so every
    surface that will ever call it -- including one written after this -- carries out somebody's
    recorded decision or nothing.
    """
    parameters = inspect.signature(recovery.confirm_plan).parameters
    assert "worker_id" not in parameters
    assert "approval_id" in parameters
    assert "channel" not in parameters


async def test_the_service_surface_has_no_channel_it_could_record_an_approval_on() -> None:
    """The closed vocabulary, which is why the previous test is not merely a convention.

    Both members name a path on which a person presented a credential of their own. There is no
    member for a service surface, and the database's ``CHECK`` admits exactly these two -- so a
    future route that tried to record an approval for the MCP process would have nothing to put
    in the column and would be refused by PostgreSQL if it invented one.
    """
    assert {channel.value for channel in plan_approval.ApprovalChannel} == {
        "BROWSER_SESSION",
        "OPERATOR_CONSOLE",
    }


# --------------------------------------------------------- what an approval is bound to


async def test_an_approval_cannot_be_carried_to_another_case(
    tools: httpx2.AsyncClient, physical: Intake
) -> None:
    """A real approval, a real case, and the wrong pairing of the two.

    The approval is genuine and its worker is permitted on the case it belongs to. Spending it
    on a second case is still refused as though it did not exist, because for that case it does
    not: an approval is a statement about one plan of one case and carries no authority anywhere
    else.
    """
    mine = await planned(physical)
    theirs = await planned(physical)
    approval = await physical.approve(mine)

    with pytest.raises(recovery.HumanApprovalMissingError):
        await recovery.confirm_plan(
            physical.database,
            case_id=theirs,
            command_id=uuid4(),
            approval_id=approval.id,
            plan_id=await physical.plan_id(theirs),
        )
    assert (await physical.case(theirs)).state == "PLANNED"
    assert await approvals_on(physical, theirs) == []


async def test_a_plan_the_case_is_not_offering_is_refused_before_approvals_are_discussed(
    physical: Intake,
) -> None:
    """The refusal order, asserted where it is decided.

    A real approval, quoted with a plan identity the case has never offered. The answer is about
    the plan and not about the approval, because everything a caller is told before the authority
    check is a fact about the case -- and a caller that has not got the case and the plan right
    learns nothing whatever about who has agreed to what.
    """
    case_id = await planned(physical)
    approval = await physical.approve(case_id)

    with pytest.raises(recovery.StalePlanError):
        await recovery.confirm_plan(
            physical.database,
            case_id=case_id,
            command_id=uuid4(),
            approval_id=approval.id,
            plan_id="0" * 64,
        )
    assert (await physical.case(case_id)).state == "PLANNED"


async def test_an_approval_does_not_survive_the_case_moving_on(
    tools: httpx2.AsyncClient, physical: Intake
) -> None:
    """The stale-plan case, reached the way the product reaches it.

    The worker approves what they were read. A correcting attestation then re-analyses the case
    against the truth that now stands, so the plan on offer afterwards is a different plan even
    though the case is ``PLANNED`` again and looks confirmable. The approval that exists is for
    the first one, and the yes it carries is refused as superseded rather than applied to a set
    of orders nobody agreed to.
    """
    case_id = await planned(physical)
    read = await physical.plan_id(case_id)
    await physical.approve(case_id, plan_id=read)

    await physical.correct(case_id, CORRECTION)
    await physical.drain()
    assert (await physical.case(case_id)).state == "PLANNED"
    assert await physical.plan_id(case_id) != read

    response = await confirm(tools, case_id, read)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_SUPERSEDED"
    assert (await physical.case(case_id)).state == "PLANNED"
    assert await physical.effects() == []


async def test_the_plan_the_case_moved_to_cannot_be_confirmed_on_the_old_approval(
    tools: httpx2.AsyncClient, physical: Intake
) -> None:
    """And the other direction: the new plan is not covered by the old yes either.

    Between them these two say the whole rule. A superseded approval authorises neither the plan
    it was given for, which no longer exists, nor the one that replaced it, which nobody read.
    """
    case_id = await planned(physical)
    await physical.approve(case_id, plan_id=await physical.plan_id(case_id))
    await physical.correct(case_id, CORRECTION)
    await physical.drain()

    response = await confirm(tools, case_id, await physical.plan_id(case_id))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "HUMAN_APPROVAL_REQUIRED"
    assert (await physical.case(case_id)).state == "PLANNED"


# --------------------------------------------------------------------- who may leave one


async def test_a_worker_with_no_standing_on_a_case_cannot_approve_its_plan(
    physical: Intake,
) -> None:
    """The permission question moved to where the authority is, and is answered by the domain.

    An owner opened this case, so a baker may not act on it. They may not approve its plan
    either, and the refusal is ``require_permitted``'s -- the same function every other write in
    this system passes through, not a check this module remembered to add.
    """
    case_id = await planned(physical, worker_id=OWNER)

    with pytest.raises(intake.NotPermittedError):
        await physical.approve(case_id, worker_id=BAKER)
    assert await approvals_on(physical, case_id) == []


async def test_an_observer_cannot_approve_a_plan(physical: Intake) -> None:
    """The principal this product admits to reads and to nothing else, refused at the authority.

    An observer is a role on the worker row precisely so that the refusal belongs to the domain
    rather than to whichever transport remembered it. Approving a plan is a write, so it is
    refused for the same reason and by the same function as every other write.
    """
    case_id = await planned(physical)
    async with physical.another_worker("kim", role="observer") as watcher:
        with pytest.raises(intake.NotPermittedError):
            await physical.approve(case_id, worker_id=watcher)
    assert await approvals_on(physical, case_id) == []


async def test_a_worker_cannot_approve_a_case_that_is_not_offering_a_plan(
    physical: Intake,
) -> None:
    """There is nothing to agree to before a plan exists, so there is nothing to record."""
    opened = await physical.report(CANONICAL_REPORT)
    await physical.drain()

    with pytest.raises(recovery.PlanNotConfirmableError):
        await physical.approve(opened.case_id, plan_id="0" * 64)
    assert await approvals_on(physical, opened.case_id) == []


# ------------------------------------------------------------- twice, and after a restart


async def test_the_same_approval_spent_twice_carries_nothing_out_twice(
    tools: httpx2.AsyncClient, physical: Intake
) -> None:
    """One yes, two deliveries of it, and one authorisation.

    The first spends it. The second arrives with a fresh command id, so it is not a retry of
    anything -- and it is refused, because the case has left the state where a plan is on offer.
    A single approval is a single authority however many times a conversation quotes it.
    """
    case_id = await planned(physical)
    plan_id = await physical.plan_id(case_id)
    await physical.approve(case_id, plan_id=plan_id)

    first = await confirm(tools, case_id, plan_id)
    second = await confirm(tools, case_id, plan_id)

    assert first.status_code == 202, first.text
    assert first.json()["created"] is True
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "PLAN_NOT_CONFIRMABLE"


async def test_a_redelivered_confirmation_reports_the_same_person_and_confirms_once(
    tools: httpx2.AsyncClient, physical: Intake
) -> None:
    """Replay, under the caller's own idempotency key, which is a retry rather than a second yes.

    Both answers name the worker whose approval was carried out, because the second reads that
    back from the row the first wrote rather than recomputing it -- so a redelivery arriving
    after the plan has ceased to exist still says truthfully whose decision it was.
    """
    case_id = await planned(physical)
    plan_id = await physical.plan_id(case_id)
    await physical.approve(case_id, plan_id=plan_id)
    command_id = uuid4()

    first = await confirm(tools, case_id, plan_id, command_id=command_id)
    again = await confirm(tools, case_id, plan_id, command_id=command_id)

    assert first.json()["created"] is True
    assert again.status_code == 202
    assert again.json()["created"] is False
    assert first.json()["confirmed_by"] == again.json()["confirmed_by"] == BAKER
    assert first.json()["approved_via"] == again.json()["approved_via"] == "BROWSER_SESSION"


async def test_recording_one_persons_yes_twice_records_it_once(physical: Intake) -> None:
    """Two presses of the same control are one agreement, not two authorities for it."""
    case_id = await planned(physical)

    first = await physical.approve(case_id)
    again = await physical.approve(case_id)

    assert first.id == again.id
    assert len(await approvals_on(physical, case_id)) == 1


async def test_an_approval_outlives_the_process_that_took_it(
    tools: httpx2.AsyncClient, physical: Intake
) -> None:
    """Authority is a row, so a conversation that starts after everything restarted finds it.

    Nothing in this test holds state between the approval and the confirmation: the approval is
    written through one handle, and the service surface finds it by reading the database, with
    no session, no memory and no argument connecting the two. That is the same property a
    restarted process has.
    """
    case_id = await planned(physical)
    plan_id = await physical.plan_id(case_id)
    await physical.approve(case_id, plan_id=plan_id)

    response = await confirm(tools, case_id, plan_id)

    assert response.status_code == 202, response.text
    assert response.json()["confirmed_by"] == BAKER
    assert (await physical.case(case_id)).state == "EXECUTING"
    assert len(await approvals_on(physical, case_id)) == 1


# --------------------------------------------------------------- what the ledger says of it


async def test_an_approval_and_the_confirmation_that_spent_it_are_two_audited_facts(
    tools: httpx2.AsyncClient, physical: Intake
) -> None:
    """Provenance, durable and separable: who agreed, and what carried their agreement out.

    One row for the agreement, carrying the channel that authenticated the person; one row for
    the execution, carrying the approval it spent. Both under ``HUMAN_APPROVAL``, and now that
    word is established by the first rather than asserted by the second.
    """
    case_id = await planned(physical)
    plan_id = await physical.plan_id(case_id)
    approval = await physical.approve(case_id, plan_id=plan_id)
    assert (await confirm(tools, case_id, plan_id)).status_code == 202

    async with physical.database.connect() as connection:
        rows = list(
            (
                await connection.execute(
                    select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.seq)
                )
            ).all()
        )
    approved = [row for row in rows if row.type == plan_approval.AUDIT_PLAN_APPROVED]
    confirmed = [row for row in rows if row.type == recovery.AUDIT_PLAN_CONFIRMED]

    assert len(approved) == 1
    assert approved[0].authority == "HUMAN_APPROVAL"
    assert approved[0].actor_id == BAKER
    assert approved[0].after["channel"] == "BROWSER_SESSION"
    assert len(confirmed) == 1
    assert confirmed[0].authority == "HUMAN_APPROVAL"
    assert confirmed[0].provenance["approval_id"] == str(approval.id)
    assert confirmed[0].provenance["approved_via"] == "BROWSER_SESSION"
    assert confirmed[0].provenance["confirmed_by"] == BAKER


async def test_the_answer_names_the_approver_and_never_the_configured_surface_worker(
    physical: Intake,
) -> None:
    """The surface's own worker is not the answer to "who agreed", even when they are the same.

    Configured here as the owner, who is also the person who approved -- so the assertion that
    matters is the one about where the name came from. It is read from the approval row, and a
    surface configured with somebody else entirely returns the approver just the same.
    """
    case_id = await planned(physical, worker_id=OWNER)
    plan_id = await physical.plan_id(case_id)
    await physical.approve(case_id, worker_id=OWNER, plan_id=plan_id)

    api: FastAPI = create_app(
        Settings(internal_service_token=SERVICE_TOKEN, surface_worker_id=BAKER)
    )
    api.state.database = physical.database
    transport = httpx2.ASGITransport(app=api)
    async with httpx2.AsyncClient(transport=transport, base_url=BASE) as client:
        response = await confirm(client, case_id, plan_id)

    assert response.status_code == 202, response.text
    assert response.json()["confirmed_by"] == OWNER
    assert response.json()["confirmed_by"] != BAKER
    assert response.json()["approved_via"] == "BROWSER_SESSION"
