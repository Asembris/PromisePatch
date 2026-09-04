"""What the worker may and may not do to the database it runs against.

A worker is the first process other than the API to write to this database, and the whole point
of the audited boundary is that it holds for code nobody had written when the boundary was
installed. So these are not tests of the worker's intentions -- they are tests that PostgreSQL
would refuse it if the intentions were wrong.

Three things are asserted: that a consequential change still cannot happen without an audit
event, that the worker's own bookkeeping stays on the ungoverned side of the line, and that the
process holds the least-privileged runtime role and nothing more.
"""

from __future__ import annotations

import pytest
from _workflow_support import Workflow
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.config import Settings
from promisepatch.db.boundary import (
    COMMIT_ORDER_TRIGGER,
    GOVERNED_TABLES,
    RUNTIME_ROLE,
    UNGOVERNED_TABLES,
)
from promisepatch.db.models import Case, CaseStep
from promisepatch.db.runtime import RuntimeDatabase, RuntimeRoleError, login_role
from promisepatch.db.uow import Actor
from promisepatch.domain import steps
from promisepatch.domain.adapters import FakeEffectAdapter
from promisepatch.domain.model import StepKind
from promisepatch.worker import Worker

pytestmark = pytest.mark.integration

INSUFFICIENT_PRIVILEGE = "42501"
WORKER_A = "worker-a"
ACTOR_A = Actor(kind="SYSTEM", id=WORKER_A)


def sqlstate(error: DBAPIError) -> str:
    return str(getattr(error.orig, "sqlstate", ""))


# ------------------------------------------------------------------- the boundary still holds


async def test_a_case_still_cannot_be_changed_without_an_audit_event(workflow: Workflow) -> None:
    """The worker writes ``cases`` constantly. It may not do so outside a governed block.

    Asserted through the worker's own connection, because a guarantee proven on some other
    connection says nothing about the one the worker actually uses.
    """
    case_id = await workflow.create_case()
    with pytest.raises(DBAPIError) as refused:
        async with workflow.database.begin() as connection:
            await connection.execute(
                update(Case).where(Case.id == case_id).values(needs_owner_attention=True)
            )
    assert sqlstate(refused.value) == INSUFFICIENT_PRIVILEGE
    assert (await workflow.case(case_id)).needs_owner_attention is False


async def test_a_successful_transition_leaves_exactly_one_audit_row(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    audit_before = await workflow.latest_audit_seq()

    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    audits = await workflow.audits_since(audit_before, case_id=case_id)
    assert len(audits) == 1
    audit = audits[0]
    assert audit.type == "WORKFLOW_STEP_EXECUTED"
    assert audit.actor_kind == "SYSTEM"
    assert audit.actor_id == WORKER_A
    assert audit.authority == "NONE"
    assert audit.after["step_key"] == "noop:1"
    assert audit.provenance["worker"] == WORKER_A


async def test_a_rolled_back_transition_removes_every_half_of_itself(workflow: Workflow) -> None:
    """Audit row, case mutation, successor and event share one transaction and one fate."""
    from promisepatch.domain import crash

    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="chain:0", kind=StepKind.CHAIN)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    before = await workflow.case(case_id)
    audit_before = await workflow.latest_audit_seq()
    event_before = await workflow.latest_event_seq()

    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    assert await workflow.audits_since(audit_before, case_id=case_id) == []
    assert (await workflow.case(case_id)).version == before.version
    assert await workflow.rows(CaseStep, case_id=case_id, step_key="chain:1") == []
    assert [e for e in await workflow.events_since(event_before) if e.case_id == case_id] == []


async def test_infrastructure_bookkeeping_needs_no_audit_event(workflow: Workflow) -> None:
    """Claiming is ungoverned on purpose: deciding to look at a row is not a decision.

    Auditing it would fill the ledger of record with the engine's own scheduling and make the
    real entries -- the ones that changed a customer promise -- harder to find, not easier.
    """
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    audit_before = await workflow.latest_audit_seq()

    assert await steps.claim_step(workflow.database, worker=WORKER_A) is not None
    assert await workflow.audits_since(audit_before) == []


async def test_a_claim_touches_only_the_engines_own_tables(workflow: Workflow) -> None:
    """Nothing governed moves during a claim, so nothing governed needs authorising."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    before = await workflow.case(case_id)
    event_before = await workflow.latest_event_seq()

    await steps.claim_step(workflow.database, worker=WORKER_A)

    assert (await workflow.case(case_id)).version == before.version
    assert (await workflow.case(case_id)).updated_at == before.updated_at
    assert await workflow.events_since(event_before) == []


async def test_the_engines_tables_are_the_ones_the_boundary_calls_ungoverned() -> None:
    """The four tables a worker writes without an audit event, named in one place."""
    assert {"case_steps", "timers", "inbox_events", "outbox_messages"} <= UNGOVERNED_TABLES
    assert "cases" in GOVERNED_TABLES


# ------------------------------------------------------------------------------- privileges


async def test_the_worker_connects_as_the_least_privileged_role(
    workflow: Workflow, app_database_url: str
) -> None:
    """Not the migration credential. A worker that could disable a trigger is not constrained."""
    assert login_role(app_database_url) == RUNTIME_ROLE
    async with workflow.database.connect() as connection:
        assert await workflow.database.current_user(connection) == RUNTIME_ROLE


async def test_a_worker_pointed_at_the_migration_credential_refuses_to_start() -> None:
    """A startup failure rather than a quiet, total loss of least privilege."""
    settings = Settings()
    if settings.migration_database_url is None:
        pytest.skip("PP_MIGRATION_DATABASE_URL is not set")
    with pytest.raises(RuntimeRoleError):
        RuntimeDatabase.from_settings(
            Settings(database_url=settings.require_migration_database_url())
        )


async def test_the_worker_cannot_rewrite_the_event_spine(workflow: Workflow) -> None:
    """Append-only holds for the worker exactly as it holds for everything else."""
    with pytest.raises(DBAPIError) as refused:
        async with workflow.database.begin() as connection:
            await connection.execute(
                text("UPDATE promisepatch.domain_events SET type = 'tampered' WHERE seq > 0")
            )
    assert sqlstate(refused.value) == INSUFFICIENT_PRIVILEGE


async def test_the_worker_cannot_disable_the_trigger_that_orders_the_spine(
    workflow: Workflow,
) -> None:
    """The ordering guarantee is not something the process it constrains may switch off."""
    with pytest.raises(DBAPIError) as refused:
        async with workflow.database.begin() as connection:
            await connection.execute(
                text(
                    f"ALTER TABLE promisepatch.domain_events DISABLE TRIGGER {COMMIT_ORDER_TRIGGER}"
                )
            )
    assert sqlstate(refused.value) == INSUFFICIENT_PRIVILEGE


async def test_the_worker_holds_no_new_privilege(conn: AsyncConnection) -> None:
    """The runtime role gained nothing for this slice. New columns, no new grants."""
    granted = (
        await conn.execute(
            text(
                "select privilege_type from information_schema.table_privileges"
                " where table_schema = 'promisepatch' and table_name = 'case_steps'"
                " and grantee = :role"
            ),
            {"role": RUNTIME_ROLE},
        )
    ).scalars()
    assert set(granted) == {"SELECT", "INSERT", "UPDATE", "DELETE"}


async def test_the_worker_still_cannot_create_a_table(workflow: Workflow) -> None:
    with pytest.raises(DBAPIError) as refused:
        async with workflow.database.begin() as connection:
            await connection.execute(text("CREATE TABLE promisepatch.smuggled (id int)"))
    assert sqlstate(refused.value) == INSUFFICIENT_PRIVILEGE


# ----------------------------------------------------------------- the whole process, audited


async def test_a_running_worker_writes_an_audited_trail_of_what_it_did(workflow: Workflow) -> None:
    """Every governed write the loop makes names the process that made it and why."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="chain:0", kind=StepKind.CHAIN)
    audit_before = await workflow.latest_audit_seq()

    worker = Worker(database=workflow.database, adapter=FakeEffectAdapter())
    for _ in range(10):
        if not await worker.run_once():
            break

    audits = await workflow.audits_since(audit_before, case_id=case_id)
    assert len(audits) == 3
    assert {audit.actor_id for audit in audits} == {worker.identity.value}
    assert {audit.authority for audit in audits} == {"NONE"}
    assert {audit.type for audit in audits} == {"WORKFLOW_STEP_EXECUTED"}

    async with workflow.database.connect() as connection:
        versions = (
            await connection.execute(select(Case.version).where(Case.id == case_id))
        ).scalar_one()
    assert versions == 1 + len(audits)


async def test_an_unaudited_step_row_is_still_perfectly_legal(workflow: Workflow) -> None:
    """Stated explicitly, because it is the line: bookkeeping in, decisions out."""
    case_id = await workflow.create_case()
    async with workflow.database.begin() as connection:
        from uuid import uuid4

        await connection.execute(
            insert(CaseStep).values(
                id=uuid4(),
                case_id=case_id,
                step_key="direct:1",
                kind=StepKind.NOOP.value,
                state="PENDING",
            )
        )
    assert len(await workflow.rows(CaseStep, case_id=case_id)) == 1
