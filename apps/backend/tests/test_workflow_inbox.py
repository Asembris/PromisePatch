"""Inbound records: deduplicated by the database, processed from the row, retriable on death.

The property that matters most is the one that needs no application code at all. A provider
that retries a delivery it was unsure about hits ``UNIQUE(source, provider_event_id)`` and
produces nothing -- there is no "have we seen this?" query to forget and no window between
checking and inserting.

The second property is what a crash leaves behind. Processing is one transaction, so a worker
killed halfway through leaves the record ``RECEIVED``: retriable, and indistinguishable from
one that has not been looked at yet, which is exactly what it is.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from _workflow_support import Workflow

from promisepatch.db.models import CaseStep, InboxEvent
from promisepatch.domain import crash, handlers, inbox
from promisepatch.domain.model import EVENT_INBOX_FAILED, EVENT_INBOX_PROCESSED

pytestmark = pytest.mark.integration

WORKER_A = "worker-a"


async def store(
    workflow: Workflow, *, source: str, provider_event_id: str, body: str | None
) -> UUID | None:
    async with workflow.database.begin() as connection:
        return await inbox.ingest(
            connection, source=source, provider_event_id=provider_event_id, body=body
        )


def synthetic(case_id: object = None) -> str:
    return json.dumps({"case_id": str(case_id)} if case_id else {})


# ------------------------------------------------------------------------------ deduplication


async def test_a_repeated_delivery_stores_one_record(workflow: Workflow) -> None:
    """Uniqueness in the database, not a lookup in the application."""
    provider_event_id = f"evt-{uuid4().hex[:12]}"
    first = await store(
        workflow,
        source=handlers.SYNTHETIC_SOURCE,
        provider_event_id=provider_event_id,
        body=synthetic(),
    )
    second = await store(
        workflow,
        source=handlers.SYNTHETIC_SOURCE,
        provider_event_id=provider_event_id,
        body=synthetic(),
    )

    assert first is not None
    assert second is None
    assert len(await workflow.rows(InboxEvent, provider_event_id=provider_event_id)) == 1


async def test_a_repeated_delivery_produces_no_second_piece_of_work(workflow: Workflow) -> None:
    """The point of deduplicating at all: one arrival, one consequence."""
    case_id = await workflow.create_case()
    provider_event_id = f"evt-{uuid4().hex[:12]}"
    for _ in range(3):
        await store(
            workflow,
            source=handlers.SYNTHETIC_SOURCE,
            provider_event_id=provider_event_id,
            body=synthetic(case_id),
        )

    processed = await inbox.process_one(workflow.database, worker=WORKER_A)
    assert processed is not None
    assert await inbox.process_one(workflow.database, worker=WORKER_A) is None
    assert len(await workflow.rows(CaseStep, case_id=case_id)) == 1


async def test_the_same_provider_id_from_a_different_source_is_a_different_record(
    workflow: Workflow,
) -> None:
    """The key is the pair. Two providers numbering their events from one is not our problem."""
    provider_event_id = f"evt-{uuid4().hex[:12]}"
    assert await store(
        workflow,
        source=handlers.SYNTHETIC_SOURCE,
        provider_event_id=provider_event_id,
        body=synthetic(),
    )
    assert await store(
        workflow, source="telegram", provider_event_id=provider_event_id, body=synthetic()
    )


# --------------------------------------------------------------------------------- processing


async def test_processing_records_the_verdict_and_creates_one_successor(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    inbox_id = await store(
        workflow,
        source=handlers.SYNTHETIC_SOURCE,
        provider_event_id=f"evt-{uuid4().hex[:12]}",
        body=synthetic(case_id),
    )
    assert inbox_id is not None
    before = await workflow.latest_event_seq()

    processed = await inbox.process_one(workflow.database, worker=WORKER_A)
    assert processed is not None
    assert processed.state == "PROCESSED"
    assert processed.step_key == handlers.inbox_step_key(inbox_id)

    row = await workflow.row(InboxEvent, inbox_id)
    assert row.state == "PROCESSED"
    assert row.processed_at is not None
    assert row.normalized == {"source": handlers.SYNTHETIC_SOURCE, "case_id": str(case_id)}
    assert row.raw_body is not None

    created = await workflow.rows(CaseStep, case_id=case_id)
    assert [step.step_key for step in created] == [processed.step_key]

    types = {event.type for event in await workflow.events_since(before)}
    assert EVENT_INBOX_PROCESSED in types


async def test_a_record_naming_no_case_is_understood_and_creates_nothing(
    workflow: Workflow,
) -> None:
    inbox_id = await store(
        workflow,
        source=handlers.SYNTHETIC_SOURCE,
        provider_event_id=f"evt-{uuid4().hex[:12]}",
        body=synthetic(),
    )
    processed = await inbox.process_one(workflow.database, worker=WORKER_A)
    assert processed is not None
    assert processed.state == "IGNORED"
    assert processed.step_key is None
    assert (await workflow.row(InboxEvent, inbox_id)).state == "IGNORED"


async def test_an_unknown_source_becomes_terminally_failed(workflow: Workflow) -> None:
    """Not retried: returning to a record nothing can read would mean returning forever."""
    inbox_id = await store(
        workflow,
        source="telegram",
        provider_event_id=f"evt-{uuid4().hex[:12]}",
        body=synthetic(),
    )
    before = await workflow.latest_event_seq()

    processed = await inbox.process_one(workflow.database, worker=WORKER_A)
    assert processed is not None
    assert processed.state == "FAILED"

    row = await workflow.row(InboxEvent, inbox_id)
    assert row.state == "FAILED"
    assert row.error
    assert row.raw_body is not None, "the raw material stays, so a later build can replay it"

    assert await inbox.process_one(workflow.database, worker=WORKER_A) is None
    types = {event.type for event in await workflow.events_since(before)}
    assert EVENT_INBOX_FAILED in types


async def test_unreadable_material_fails_rather_than_stopping_the_worker(
    workflow: Workflow,
) -> None:
    await store(
        workflow,
        source=handlers.SYNTHETIC_SOURCE,
        provider_event_id=f"evt-{uuid4().hex[:12]}",
        body="not json at all",
    )
    processed = await inbox.process_one(workflow.database, worker=WORKER_A)
    assert processed is not None
    assert processed.state == "FAILED"


# ---------------------------------------------------------------------------------- crashing


async def test_a_death_during_processing_leaves_the_record_retriable(workflow: Workflow) -> None:
    """``RECEIVED`` afterwards, which is indistinguishable from never having been looked at."""
    case_id = await workflow.create_case()
    inbox_id = await store(
        workflow,
        source=handlers.SYNTHETIC_SOURCE,
        provider_event_id=f"evt-{uuid4().hex[:12]}",
        body=synthetic(case_id),
    )

    with (
        crash.arm(crash.DURING_INBOX_PROCESSING),
        pytest.raises(crash.WorkerDied),
    ):
        await inbox.process_one(workflow.database, worker=WORKER_A)

    row = await workflow.row(InboxEvent, inbox_id)
    assert row.state == "RECEIVED"
    assert row.processed_at is None
    assert await workflow.rows(CaseStep, case_id=case_id) == []

    # A fresh worker picks it up and finishes the job.
    processed = await inbox.process_one(workflow.database, worker="worker-after-restart")
    assert processed is not None
    assert processed.state == "PROCESSED"
    assert len(await workflow.rows(CaseStep, case_id=case_id)) == 1


async def test_reprocessing_a_record_cannot_duplicate_its_successor(workflow: Workflow) -> None:
    """The successor's key is derived from the inbox row, so a replay proposes the same one."""
    case_id = await workflow.create_case()
    inbox_id = await store(
        workflow,
        source=handlers.SYNTHETIC_SOURCE,
        provider_event_id=f"evt-{uuid4().hex[:12]}",
        body=synthetic(case_id),
    )
    await inbox.process_one(workflow.database, worker=WORKER_A)

    async with workflow.database.begin() as connection:
        from sqlalchemy import update

        await connection.execute(
            update(InboxEvent).where(InboxEvent.id == inbox_id).values(state="RECEIVED")
        )

    again = await inbox.process_one(workflow.database, worker=WORKER_A)
    assert again is not None
    assert len(await workflow.rows(CaseStep, case_id=case_id)) == 1
