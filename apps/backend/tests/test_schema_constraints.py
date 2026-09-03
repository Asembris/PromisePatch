"""What PostgreSQL itself refuses to store.

Each test names an invariant from the frozen model and shows the database enforcing it, not
the application remembering to. A constraint that only lives in Python is a constraint that
holds until the first script, migration or future slice writes around it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.base import Base
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    Case,
    CaseStep,
    CommitmentLine,
    Customer,
    InboxEvent,
    InventoryLedgerEntry,
    Order,
    OrderConstraint,
    OrderLine,
    OutboxMessage,
    ProductionTask,
    Promise,
    Recipe,
    RecipeVersion,
    Reservation,
    Resource,
    SubstitutionPolicy,
    Supplier,
    SupplierCommitment,
    Track,
)
from promisepatch.db.uow import Actor, UnitOfWork

pytestmark = pytest.mark.integration

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=8)


@pytest_asyncio.fixture(autouse=True)
async def authorised(conn: AsyncConnection) -> AsyncIterator[None]:
    """Every write in this module goes through the governed path, as production's do.

    The audited-write trigger refuses an unaudited write to a governed table, so a fixture row
    is not something a test can simply insert any more. Nothing about what these tests assert
    changes: the constraint still has to be the thing that rejects the row, and a check that
    stopped firing would still fail here. Only the way the row is offered has changed.
    """
    fixture_load = UnitOfWork(conn).governed(
        event_type="FIXTURE_LOAD",
        actor=Actor(kind="SYSTEM", id="schema-constraint-tests"),
        authority="NONE",
    )
    async with fixture_load:
        yield


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


async def add(conn: AsyncConnection, model: type[Base], **values: Any) -> None:
    await conn.execute(insert(model).values(**values))


# --------------------------------------------------------------------------- row builders


async def a_resource(conn: AsyncConnection, kind: str = "INGREDIENT") -> str:
    resource_id = unique("res")
    await add(conn, Resource, id=resource_id, kind=kind, name="thing", unit="kg")
    return resource_id


async def a_commitment(conn: AsyncConnection) -> str:
    supplier_id, commitment_id = unique("sup"), unique("com")
    await add(conn, Supplier, id=supplier_id, name="Supplier")
    await add(conn, SupplierCommitment, id=commitment_id, supplier_id=supplier_id, due_at=NOW)
    return commitment_id


async def a_version(conn: AsyncConnection, version_no: int = 1, recipe_id: str = "") -> str:
    recipe = recipe_id or unique("rec")
    if not recipe_id:
        await add(conn, Recipe, id=recipe, name="Cake")
    version_id = unique("rv")
    await add(
        conn,
        RecipeVersion,
        id=version_id,
        recipe_id=recipe,
        version_no=version_no,
        authored_by="jo",
        authored_at=NOW,
    )
    return version_id


async def an_order(conn: AsyncConnection, version_id: str) -> tuple[str, str]:
    customer_id, order_id, line_id = unique("cus"), unique("ord"), unique("ol")
    await add(
        conn,
        Customer,
        id=customer_id,
        name="Customer",
        approval_channel_kind="telegram",
        approval_channel_address="1001",
    )
    await add(
        conn,
        Order,
        id=order_id,
        external_id=unique("EXT"),
        external_version=1,
        customer_id=customer_id,
        due_at=LATER,
        state="ACCEPTED",
        updated_at=NOW,
    )
    await add(
        conn,
        OrderLine,
        id=line_id,
        order_id=order_id,
        recipe_version_id=version_id,
        quantity=1,
    )
    return order_id, line_id


async def a_promise(conn: AsyncConnection, order_id: str) -> str:
    promise_id = unique("pr")
    await add(conn, Promise, id=promise_id, order_id=order_id, due_at=LATER)
    return promise_id


async def a_case(conn: AsyncConnection) -> UUID:
    case_id = uuid4()
    await add(
        conn, Case, id=case_id, state="ANALYZED", opened_by="maya", opened_at=NOW, updated_at=NOW
    )
    return case_id


async def a_track(conn: AsyncConnection, case_id: UUID, promise_id: str, state: str) -> UUID:
    track_id = uuid4()
    await add(conn, Track, id=track_id, case_id=case_id, promise_id=promise_id, state=state)
    return track_id


# --------------------------------------------------------------------------- settlement


async def test_short_line_must_say_how_much_arrived(conn: AsyncConnection) -> None:
    """A partial delivery with no quantity would make the shortfall unknowable."""
    commitment_id = await a_commitment(conn)
    resource_id = await a_resource(conn)
    with pytest.raises(IntegrityError, match="settlement_shape"):
        await add(
            conn,
            CommitmentLine,
            id=unique("cl"),
            commitment_id=commitment_id,
            resource_id=resource_id,
            quantity=Decimal("4.000"),
            received_state="SHORT",
            received_qty=None,
            settled_at=NOW,
        )


async def test_a_fully_received_line_carries_no_partial_quantity(conn: AsyncConnection) -> None:
    commitment_id = await a_commitment(conn)
    resource_id = await a_resource(conn)
    with pytest.raises(IntegrityError, match="settlement_shape"):
        await add(
            conn,
            CommitmentLine,
            id=unique("cl"),
            commitment_id=commitment_id,
            resource_id=resource_id,
            quantity=Decimal("4.000"),
            received_state="RECEIVED",
            received_qty=Decimal("4.000"),
            settled_at=NOW,
        )


async def test_an_open_line_is_not_settled(conn: AsyncConnection) -> None:
    commitment_id = await a_commitment(conn)
    resource_id = await a_resource(conn)
    with pytest.raises(IntegrityError, match="settled_at_matches_state"):
        await add(
            conn,
            CommitmentLine,
            id=unique("cl"),
            commitment_id=commitment_id,
            resource_id=resource_id,
            quantity=Decimal("4.000"),
            received_state="EXPECTED",
            settled_at=NOW,
        )


async def test_a_settled_line_records_when(conn: AsyncConnection) -> None:
    commitment_id = await a_commitment(conn)
    resource_id = await a_resource(conn)
    with pytest.raises(IntegrityError, match="settled_at_matches_state"):
        await add(
            conn,
            CommitmentLine,
            id=unique("cl"),
            commitment_id=commitment_id,
            resource_id=resource_id,
            quantity=Decimal("4.000"),
            received_state="NOT_RECEIVED",
            settled_at=None,
        )


async def test_an_unknown_received_state_is_rejected(conn: AsyncConnection) -> None:
    commitment_id = await a_commitment(conn)
    resource_id = await a_resource(conn)
    with pytest.raises(IntegrityError, match="received_state"):
        await add(
            conn,
            CommitmentLine,
            id=unique("cl"),
            commitment_id=commitment_id,
            resource_id=resource_id,
            quantity=Decimal("4.000"),
            received_state="PARTIALLY_MAYBE",
        )


# --------------------------------------------------------------------------- exactly-once


async def test_a_physical_posting_can_only_land_once(conn: AsyncConnection) -> None:
    """The exactly-once guarantee: a replayed receipt is a violation, not a second delivery."""
    resource_id = await a_resource(conn)
    source_id = unique("cl")
    await add(
        conn,
        InventoryLedgerEntry,
        resource_id=resource_id,
        delta=Decimal("6.000"),
        source_kind="COMMITMENT_RECEIPT",
        source_id=source_id,
        recorded_at=NOW,
    )
    with pytest.raises(IntegrityError, match="uq_inventory_ledger_source"):
        await add(
            conn,
            InventoryLedgerEntry,
            resource_id=resource_id,
            delta=Decimal("6.000"),
            source_kind="COMMITMENT_RECEIPT",
            source_id=source_id,
            recorded_at=NOW,
        )


async def test_the_same_source_id_under_a_different_kind_is_a_different_posting(
    conn: AsyncConnection,
) -> None:
    """A correction is its own posting, not a duplicate of the receipt it compensates."""
    resource_id = await a_resource(conn)
    source_id = unique("cl")
    await add(
        conn,
        InventoryLedgerEntry,
        resource_id=resource_id,
        delta=Decimal("6.000"),
        source_kind="COMMITMENT_RECEIPT",
        source_id=source_id,
        recorded_at=NOW,
    )
    await add(
        conn,
        InventoryLedgerEntry,
        resource_id=resource_id,
        delta=Decimal("-6.000"),
        source_kind="CORRECTION",
        source_id=source_id,
        recorded_at=NOW,
    )
    total = await conn.scalar(
        select(InventoryLedgerEntry.delta).where(
            InventoryLedgerEntry.source_kind == "CORRECTION",
            InventoryLedgerEntry.source_id == source_id,
        )
    )
    assert total == Decimal("-6.000")


async def test_quantities_keep_three_decimal_places(conn: AsyncConnection) -> None:
    """The engine normalises to three places; a lossy column would change allocation."""
    resource_id = await a_resource(conn)
    await add(
        conn,
        InventoryLedgerEntry,
        resource_id=resource_id,
        delta=Decimal("0.125"),
        source_kind="FIXTURE",
        source_id=unique("fx"),
        recorded_at=NOW,
    )
    stored = await conn.scalar(
        select(InventoryLedgerEntry.delta).where(InventoryLedgerEntry.resource_id == resource_id)
    )
    assert stored == Decimal("0.125")
    assert str(stored) == "0.125"


# --------------------------------------------------------------------------- constraints


async def test_a_constraint_without_provenance_is_refused(conn: AsyncConnection) -> None:
    """An unattributable rule cannot justify a substitution to a customer."""
    order_id, _ = await an_order(conn, await a_version(conn))
    with pytest.raises(IntegrityError, match="provenance_required"):
        await add(
            conn,
            OrderConstraint,
            id=unique("cn"),
            order_id=order_id,
            kind="NO_SUBSTITUTION",
            recorded_by="   ",
            recorded_at=NOW,
        )


async def test_a_preapproval_names_both_resources(conn: AsyncConnection) -> None:
    order_id, _ = await an_order(conn, await a_version(conn))
    resource_id = await a_resource(conn)
    with pytest.raises(IntegrityError, match="constraint_shape"):
        await add(
            conn,
            OrderConstraint,
            id=unique("cn"),
            order_id=order_id,
            kind="PREAPPROVED_ALTERNATIVE",
            resource_id=resource_id,
            substitute_resource_id=None,
            recorded_by="jo",
            recorded_at=NOW,
        )


async def test_a_blanket_rule_carries_no_resources(conn: AsyncConnection) -> None:
    order_id, _ = await an_order(conn, await a_version(conn))
    resource_id = await a_resource(conn)
    with pytest.raises(IntegrityError, match="constraint_shape"):
        await add(
            conn,
            OrderConstraint,
            id=unique("cn"),
            order_id=order_id,
            kind="NO_SUBSTITUTION",
            resource_id=resource_id,
            recorded_by="jo",
            recorded_at=NOW,
        )


# --------------------------------------------------------------------------- cardinality


async def test_one_promise_per_order(conn: AsyncConnection) -> None:
    order_id, _ = await an_order(conn, await a_version(conn))
    await a_promise(conn, order_id)
    with pytest.raises(IntegrityError, match="uq_promises_order_id"):
        await a_promise(conn, order_id)


async def test_one_production_task_per_order_line(conn: AsyncConnection) -> None:
    """The engine indexes tasks by line one-to-one; a second would be silently dropped."""
    _, line_id = await an_order(conn, await a_version(conn))
    await add(conn, ProductionTask, id=unique("task"), order_line_id=line_id, state="SCHEDULED")
    with pytest.raises(IntegrityError, match="uq_production_tasks_order_line_id"):
        await add(conn, ProductionTask, id=unique("task"), order_line_id=line_id, state="SCHEDULED")


async def test_one_reservation_per_line_and_resource(conn: AsyncConnection) -> None:
    version_id = await a_version(conn)
    _, line_id = await an_order(conn, version_id)
    resource_id = await a_resource(conn)
    values = {
        "order_line_id": line_id,
        "resource_id": resource_id,
        "quantity": Decimal("2.400"),
        "source_recipe_version_id": version_id,
    }
    await add(conn, Reservation, id=unique("rsv"), **values)
    with pytest.raises(IntegrityError, match="uq_reservations_line_resource"):
        await add(conn, Reservation, id=unique("rsv"), **values)


async def test_one_substitution_policy_per_key(conn: AsyncConnection) -> None:
    """Two policies for one key would silently drop one from the engine's lookup map."""
    recipe_id = unique("rec")
    await add(conn, Recipe, id=recipe_id, name="Cake")
    source = await a_version(conn, version_no=1, recipe_id=recipe_id)
    first = await a_version(conn, version_no=2, recipe_id=recipe_id)
    second = await a_version(conn, version_no=3, recipe_id=recipe_id)
    affected = await a_resource(conn)
    substitute = await a_resource(conn)
    common = {
        "affected_resource_id": affected,
        "role": "FILLING",
        "source_version_id": source,
        "substitute_resource_id": substitute,
        "visible_change": False,
    }
    await add(conn, SubstitutionPolicy, id=unique("pol"), candidate_version_id=first, **common)
    with pytest.raises(IntegrityError, match="uq_substitution_policies_key"):
        await add(conn, SubstitutionPolicy, id=unique("pol"), candidate_version_id=second, **common)


async def test_one_version_number_per_recipe(conn: AsyncConnection) -> None:
    recipe_id = unique("rec")
    await add(conn, Recipe, id=recipe_id, name="Cake")
    await a_version(conn, version_no=3, recipe_id=recipe_id)
    with pytest.raises(IntegrityError, match="uq_recipe_versions_recipe_version"):
        await a_version(conn, version_no=3, recipe_id=recipe_id)


# --------------------------------------------------------------------------- referential


async def test_an_order_line_cannot_pin_a_version_that_does_not_exist(
    conn: AsyncConnection,
) -> None:
    """Every accepted line points at exactly one authored version. No dangling lines."""
    order_id, _ = await an_order(conn, await a_version(conn))
    with pytest.raises(IntegrityError, match="recipe_version"):
        await add(
            conn,
            OrderLine,
            id=unique("ol"),
            order_id=order_id,
            recipe_version_id="rv-invented-at-runtime",
            quantity=1,
        )


async def test_a_reservation_cannot_name_an_unknown_resource(conn: AsyncConnection) -> None:
    version_id = await a_version(conn)
    _, line_id = await an_order(conn, version_id)
    with pytest.raises(IntegrityError, match="resource"):
        await add(
            conn,
            Reservation,
            id=unique("rsv"),
            order_line_id=line_id,
            resource_id="res-nonexistent",
            quantity=Decimal("1.000"),
            source_recipe_version_id=version_id,
        )


async def test_a_task_cannot_name_an_unknown_order_line(conn: AsyncConnection) -> None:
    with pytest.raises(IntegrityError, match="order_line"):
        await add(
            conn,
            ProductionTask,
            id=unique("task"),
            order_line_id="ol-nonexistent",
            state="SCHEDULED",
        )


async def test_an_order_line_quantity_must_be_positive(conn: AsyncConnection) -> None:
    version_id = await a_version(conn)
    order_id, _ = await an_order(conn, version_id)
    with pytest.raises(IntegrityError, match="quantity_positive"):
        await add(
            conn,
            OrderLine,
            id=unique("ol"),
            order_id=order_id,
            recipe_version_id=version_id,
            quantity=0,
        )


async def test_a_version_must_name_its_author(conn: AsyncConnection) -> None:
    recipe_id = unique("rec")
    await add(conn, Recipe, id=recipe_id, name="Cake")
    with pytest.raises(IntegrityError, match="authorship_required"):
        await add(
            conn,
            RecipeVersion,
            id=unique("rv"),
            recipe_id=recipe_id,
            version_no=1,
            authored_by="",
            authored_at=NOW,
        )


# --------------------------------------------------------------------------- case machine


async def test_a_promise_can_only_be_live_in_one_case(conn: AsyncConnection) -> None:
    """Two cases racing for one promise is decided by the index, not by whoever checked first."""
    order_id, _ = await an_order(conn, await a_version(conn))
    promise_id = await a_promise(conn, order_id)
    await a_track(conn, await a_case(conn), promise_id, "WAITING_FOR_CUSTOMER")
    with pytest.raises(IntegrityError, match="ix_tracks_one_live_per_promise"):
        await a_track(conn, await a_case(conn), promise_id, "PENDING")


async def test_a_settled_promise_can_be_claimed_again(conn: AsyncConnection) -> None:
    """The index is partial: once a track is terminal it no longer holds its promise."""
    order_id, _ = await an_order(conn, await a_version(conn))
    promise_id = await a_promise(conn, order_id)
    await a_track(conn, await a_case(conn), promise_id, "RECOVERED")
    await a_track(conn, await a_case(conn), promise_id, "LINKED")
    await a_track(conn, await a_case(conn), promise_id, "PENDING")
    count = await conn.scalar(
        select(Track.id).where(Track.promise_id == promise_id).with_only_columns(Track.id)
    )
    assert count is not None


async def test_an_unknown_case_state_is_rejected(conn: AsyncConnection) -> None:
    with pytest.raises(IntegrityError, match="ck_cases_state"):
        await add(
            conn,
            Case,
            id=uuid4(),
            state="THINKING_ABOUT_IT",
            opened_by="maya",
            opened_at=NOW,
            updated_at=NOW,
        )


async def test_a_step_key_is_unique_within_its_case(conn: AsyncConnection) -> None:
    """Resuming after a crash re-enters the plan; it must not be able to re-run a step."""
    case_id = await a_case(conn)
    values = {"case_id": case_id, "step_key": "apply:track-1", "kind": "APPLY", "state": "DONE"}
    await add(conn, CaseStep, id=uuid4(), **values)
    with pytest.raises(IntegrityError, match="uq_case_steps_case_step_key"):
        await add(conn, CaseStep, id=uuid4(), **values)


async def test_a_redelivered_inbound_event_is_refused(conn: AsyncConnection) -> None:
    """Provider retries are deduplicated by the database, not by application memory."""
    values = {"source": "telegram", "provider_event_id": unique("upd"), "state": "RECEIVED"}
    await add(conn, InboxEvent, id=uuid4(), received_at=NOW, **values)
    with pytest.raises(IntegrityError, match="uq_inbox_events_source_event"):
        await add(conn, InboxEvent, id=uuid4(), received_at=NOW, **values)


async def test_an_outbound_effect_has_one_idempotency_key(conn: AsyncConnection) -> None:
    key = unique("pp:amend")
    values = {"kind": "ORDER_AMEND", "payload": {}, "idempotency_key": key, "state": "PENDING"}
    await add(conn, OutboxMessage, id=uuid4(), **values)
    with pytest.raises(IntegrityError, match="uq_outbox_messages_idempotency_key"):
        await add(conn, OutboxMessage, id=uuid4(), **values)


# --------------------------------------------------------------------------- consent


async def _an_approval_request(conn: AsyncConnection) -> UUID:
    version_id = await a_version(conn)
    order_id, line_id = await an_order(conn, version_id)
    promise_id = await a_promise(conn, order_id)
    track_id = await a_track(conn, await a_case(conn), promise_id, "WAITING_FOR_CUSTOMER")
    option_id, request_id = uuid4(), uuid4()
    await conn.execute(
        insert(Base.metadata.tables["promisepatch.recovery_options"]).values(
            id=option_id, track_id=track_id, kind="SUBSTITUTE_RESOURCE"
        )
    )
    await add(
        conn,
        ApprovalRequest,
        id=request_id,
        track_id=track_id,
        promise_id=promise_id,
        order_id=order_id,
        order_line_id=line_id,
        option_id=option_id,
        option_code="A1",
        customer_channel="1002",
        sent_at=NOW,
        deadline=LATER,
        captured_fingerprint="f" * 64,
        captured_order_version=1,
        captured_recipe_version_id=version_id,
        captured_constraint_hash="c" * 64,
        state="SENT",
    )
    return request_id


async def test_only_the_literal_parser_can_record_a_decision(conn: AsyncConnection) -> None:
    """A consent decision derived from free text is not a row this database will accept."""
    request_id = await _an_approval_request(conn)
    with pytest.raises(IntegrityError, match="ck_approval_decisions_parser"):
        await add(
            conn,
            ApprovalDecision,
            id=uuid4(),
            request_id=request_id,
            decision="APPROVE",
            parser="LLM",
            sender_identity="1002",
            provider_message_id=unique("msg"),
            raw_text="strawberries work",
            received_at=NOW,
        )


async def test_one_decision_per_request(conn: AsyncConnection) -> None:
    """A second reply is acknowledged, never applied: the first decision stands."""
    request_id = await _an_approval_request(conn)
    values = {
        "request_id": request_id,
        "decision": "APPROVE",
        "parser": "LITERAL",
        "sender_identity": "1002",
        "received_at": NOW,
    }
    await add(conn, ApprovalDecision, id=uuid4(), provider_message_id=unique("msg"), **values)
    with pytest.raises(IntegrityError, match="uq_approval_decisions_request_id"):
        await add(conn, ApprovalDecision, id=uuid4(), provider_message_id=unique("msg"), **values)


async def test_a_request_is_never_sent_into_a_closed_window(conn: AsyncConnection) -> None:
    """A deadline at or before the send time is a request no valid answer could reach."""
    version_id = await a_version(conn)
    order_id, line_id = await an_order(conn, version_id)
    promise_id = await a_promise(conn, order_id)
    track_id = await a_track(conn, await a_case(conn), promise_id, "PENDING")
    option_id = uuid4()
    await conn.execute(
        insert(Base.metadata.tables["promisepatch.recovery_options"]).values(
            id=option_id, track_id=track_id, kind="SUBSTITUTE_RESOURCE"
        )
    )
    with pytest.raises(IntegrityError, match="deadline_after_send"):
        await add(
            conn,
            ApprovalRequest,
            id=uuid4(),
            track_id=track_id,
            promise_id=promise_id,
            order_id=order_id,
            order_line_id=line_id,
            option_id=option_id,
            option_code="A1",
            customer_channel="1002",
            sent_at=NOW,
            deadline=NOW,
            captured_fingerprint="f" * 64,
            captured_order_version=1,
            captured_recipe_version_id=version_id,
            captured_constraint_hash="c" * 64,
            state="SENT",
        )


# --------------------------------------------------------------------------- placement


async def test_no_promisepatch_table_leaked_into_public(conn: AsyncConnection) -> None:
    """Tables in ``public`` may be exposed automatically by a managed host."""
    leaked = (
        await conn.execute(
            text(
                "select table_name from information_schema.tables"
                " where table_schema = 'public' and table_name = any(:names)"
            ),
            {"names": [table.name for table in Base.metadata.tables.values()]},
        )
    ).all()
    assert leaked == []


async def test_the_applied_schema_has_every_table(conn: AsyncConnection) -> None:
    applied = {
        row[0]
        for row in (
            await conn.exec_driver_sql(
                "select table_name from information_schema.tables"
                " where table_schema = 'promisepatch'"
            )
        ).all()
    }
    expected = {table.name for table in Base.metadata.tables.values()}
    assert expected <= applied
    assert "alembic_version" in applied


async def test_every_timestamp_column_is_timestamptz_in_the_database(
    conn: AsyncConnection,
) -> None:
    naive = (
        await conn.exec_driver_sql(
            "select table_name, column_name from information_schema.columns"
            " where table_schema = 'promisepatch'"
            " and data_type = 'timestamp without time zone'"
        )
    ).all()
    assert naive == []


async def test_no_column_is_stored_as_a_float(conn: AsyncConnection) -> None:
    floats = (
        await conn.exec_driver_sql(
            "select table_name, column_name from information_schema.columns"
            " where table_schema = 'promisepatch'"
            " and data_type in ('double precision', 'real')"
        )
    ).all()
    assert floats == []


async def test_a_bad_statement_still_reports_through_the_driver(conn: AsyncConnection) -> None:
    """Sanity: the suite would notice a database that silently accepted everything."""
    with pytest.raises(DBAPIError):
        await conn.exec_driver_sql("select from promisepatch.nothing_here")
