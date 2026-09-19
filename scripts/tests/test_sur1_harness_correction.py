"""The regression proofs for the three harness defects the first scored run exposed.

`docs/sur1-first-scored-run-defect.md` records a run that spent its authorisation and returned
nothing comparative: 24 of 27 attempts ended ``HARNESS_FAILURE``. Three separate faults did
that, and this module is where each one is held down so it cannot come back quietly.

| defect | attempts | what is proved here |
|---|---|---|
| no committed event body on the order log | 20 | the preflight refuses a build not declaring it |
| the world's two writes were ungoverned | 3 | both go through the product's governed write |
| the fixture ``TRUNCATE`` raced the worker | 1 | ``test_sur1_world_lifecycle.py`` |

**No arm is driven here and no model is called.** Every proof is structural, or is made against
a stand-in that records what it was asked to do. Nothing in this module opens a PostgreSQL
connection, reaches the order system or writes a ``SUR-1`` capture.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from scripts.sur1.bindings import governed
from scripts.sur1.bindings.governed import AUDIT_PREFIX, GovernedWriter
from scripts.sur1.bindings.setup import HELD, SCHEDULED, KitchenWriter
from scripts.sur1.bindings.worldsink import LedgerWriter

BINDINGS = Path(governed.__file__).resolve().parent


class RecordingWriter:
    """A :class:`GovernedWriter` that records the call instead of opening a transaction."""

    def __init__(self, moved: int = 1) -> None:
        self.moved = moved
        self.calls: list[dict[str, Any]] = []

    def write(
        self,
        *,
        event_type: str,
        after: Mapping[str, Any],
        statement: str,
        parameters: Mapping[str, Any],
    ) -> int:
        self.calls.append(
            {
                "event_type": event_type,
                "after": dict(after),
                "statement": statement,
                "parameters": dict(parameters),
            }
        )
        return self.moved


# --------------------------------------------------- the world's writes are governed writes


def test_the_two_tables_the_world_writes_are_governed_by_the_product() -> None:
    """Why this whole defect existed: both tables refuse an unaudited statement, by trigger.

    Stated from the product's own boundary rather than from memory, so a table that stopped
    being governed would make this test say so rather than leave the fix looking pointless.
    """
    from promisepatch.db.boundary import GOVERNED_TABLES

    assert "production_tasks" in GOVERNED_TABLES
    assert "inventory_ledger" in GOVERNED_TABLES


def test_a_world_task_hold_is_authorised_by_an_audit_event(monkeypatch: Any) -> None:
    holder = uuid4()
    recording = RecordingWriter()
    writer = KitchenWriter(url="postgresql+asyncpg://u:p@h:5432/db", holder=holder)
    monkeypatch.setattr(KitchenWriter, "_writer", lambda self: recording)

    assert writer.hold("task-1") == {"held": True, "task_id": "task-1"}

    (call,) = recording.calls
    assert call["event_type"].startswith(AUDIT_PREFIX)
    assert call["parameters"] == {
        "state": HELD,
        "holder": holder,
        "task_id": "task-1",
        "scheduled": SCHEDULED,
    }


def test_a_world_task_release_is_authorised_by_an_audit_event(monkeypatch: Any) -> None:
    holder = uuid4()
    recording = RecordingWriter(moved=0)
    writer = KitchenWriter(url="postgresql+asyncpg://u:p@h:5432/db", holder=holder)
    monkeypatch.setattr(KitchenWriter, "_writer", lambda self: recording)

    refused = writer.release("task-1")

    assert refused["released"] is False
    assert recording.calls[0]["event_type"].startswith(AUDIT_PREFIX)


def test_a_stipulated_stock_movement_is_authorised_by_an_audit_event(monkeypatch: Any) -> None:
    """The ``C06`` failure, in one test: the movement is posted, and it is posted audited."""
    from datetime import UTC, datetime
    from decimal import Decimal

    recording = RecordingWriter()
    monkeypatch.setattr(
        "scripts.sur1.bindings.worldsink.GovernedWriter", lambda **_: recording, raising=True
    )

    receipt = LedgerWriter(url="postgresql+asyncpg://u:p@h:5432/db").post(
        resource_id="res-strawberry",
        delta=Decimal("-2.0"),
        source_id="counter-sales:ord-b",
        recorded_at=datetime(2026, 9, 19, tzinfo=UTC),
    )

    (call,) = recording.calls
    assert receipt == "ledger:sur1:counter-sales:ord-b"
    assert call["event_type"].startswith(AUDIT_PREFIX)
    assert call["parameters"]["source_id"] == "sur1:counter-sales:ord-b"


def test_neither_world_writer_can_open_a_bare_connection_any_more() -> None:
    """The structural half. A module that imports ``asyncpg`` can write around the audit.

    Read from the syntax rather than from behaviour, exactly as the preflight's blinding checks
    are: the defect was a statement nobody had ever executed, so a proof that depends on
    executing it would not have caught it either.
    """
    for name in ("setup.py", "worldsink.py"):
        tree = ast.parse((BINDINGS / name).read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert "asyncpg" not in imported, f"{name} can still write around the audit boundary"


def test_the_audit_event_never_claims_an_authority_nobody_gave() -> None:
    """A benchmark world facility is not a policy, a constraint or a human approval."""
    assert governed.AUTHORITY == "NONE"
    assert governed.WORLD_ACTOR == "sur1 world facility"


def test_the_receivers_and_the_governed_writer_name_one_database() -> None:
    """Two spellings of one connection string, and neither is a second database."""
    from scripts.sur1.bindings.receivers import DatabaseReader

    url = "postgresql+asyncpg://u:p@h:5432/db"

    assert DatabaseReader(url=url).dsn() == "postgresql://u:p@h:5432/db"
    assert governed.sqlalchemy_url(url) == url
    assert governed.sqlalchemy_url("postgresql://u:p@h:5432/db") == url


def test_the_governed_writer_is_part_of_the_frozen_implementation() -> None:
    """A change to how a world write is authorised has to move a published identity."""
    from scripts.sur1.bindings.declaration import IMPLEMENTATION_MODULES

    assert governed in IMPLEMENTATION_MODULES


def test_a_failed_governed_write_is_named_rather_than_leaking_a_driver_error() -> None:
    writer = GovernedWriter(url="postgresql+asyncpg://nobody@127.0.0.1:1/none")

    with pytest.raises(governed.GovernedWriteError):
        writer.write(
            event_type=governed.TASK_HELD,
            after={},
            statement="SELECT 1",
            parameters={},
        )


# ------------------------------------------- a stale build is refused before anything is spent


@dataclass(slots=True)
class DeclaringOrderSystem:
    """An ``E1`` reader that answers what a build of the order system would publish."""

    projection: Mapping[str, Any] | None
    binding_kind: str = "real"

    def published_projection(self) -> Mapping[str, Any]:
        from scripts.sur1.bindings.receivers import ReceiverUnreadableError

        if self.projection is None:
            raise ReceiverUnreadableError(
                "E1",
                "this order system publishes no /admin/capabilities, so it predates the "
                "projection the contract's E1 fields are read from",
            )
        return dict(self.projection)


@dataclass(slots=True)
class WorldWith:
    """Only what the three new checks reach. It is not a world and drives nothing."""

    orders: Any = None
    worker: Any = None


def a_current_projection(**overrides: Any) -> dict[str, Any]:
    from scripts.sur1.preflight import (
        REQUIRED_ORDER_BODY_FIELDS,
        REQUIRED_ORDER_CAPABILITIES,
        REQUIRED_ORDER_ENTRY_FIELDS,
    )

    published: dict[str, Any] = {
        "capabilities": list(REQUIRED_ORDER_CAPABILITIES),
        "entry_fields": list(REQUIRED_ORDER_ENTRY_FIELDS),
        "body_fields": list(REQUIRED_ORDER_BODY_FIELDS),
        "observed_entry_fields": sorted(REQUIRED_ORDER_ENTRY_FIELDS),
    }
    published.update(overrides)
    return published


def test_a_simulator_too_old_to_declare_its_projection_is_refused() -> None:
    """The 20-attempt defect, refused at the gate instead of twenty times downstream."""
    from scripts.sur1.preflight import order_projection

    refused = order_projection(world=WorldWith(orders=DeclaringOrderSystem(projection=None)))

    assert not refused.passed
    assert "/admin/capabilities" in refused.detail


def test_a_projection_that_publishes_no_command_is_refused() -> None:
    """The exact shape the stale container served: an event log with no command on it."""
    from scripts.sur1.preflight import order_projection

    stale = a_current_projection(
        capabilities=["admin-events.committed-body"],
        body_fields=["changed_line_ids", "order"],
        observed_entry_fields=[
            "attempts",
            "delivery_state",
            "event_id",
            "external_order_id",
            "occurred_at",
            "source",
            "type",
            "version",
        ],
    )

    refused = order_projection(world=WorldWith(orders=DeclaringOrderSystem(projection=stale)))

    assert not refused.passed
    assert "command" in refused.detail
    assert "event" in refused.detail


def test_a_current_order_system_passes_the_projection_check() -> None:
    from scripts.sur1.preflight import order_projection

    allowed = order_projection(
        world=WorldWith(orders=DeclaringOrderSystem(projection=a_current_projection()))
    )

    assert allowed.passed, allowed.detail


def test_the_preflight_asks_for_exactly_what_this_simulator_declares() -> None:
    """The two ends are tied together, so neither can drift away from the other quietly.

    The harness names the capability it needs and the order system names the capability it
    serves, in two packages that never import one another. This is the only place they meet.
    """
    from scripts.sur1.preflight import (
        REQUIRED_ORDER_BODY_FIELDS,
        REQUIRED_ORDER_CAPABILITIES,
        REQUIRED_ORDER_ENTRY_FIELDS,
    )

    from order_simulator import capabilities

    declared = capabilities.declaration()
    projection = declared["projection"]["admin_events"]

    assert set(REQUIRED_ORDER_CAPABILITIES) <= set(declared["capabilities"])
    assert set(REQUIRED_ORDER_ENTRY_FIELDS) <= set(projection["entry_fields"])
    assert set(REQUIRED_ORDER_BODY_FIELDS) <= set(projection["body_fields"])


def test_the_required_entry_fields_are_the_ones_the_e1_reader_actually_opens() -> None:
    """The preflight's list is checked against the reader's own source, not against memory."""
    from scripts.sur1.bindings import receivers as receivers_module
    from scripts.sur1.preflight import REQUIRED_ORDER_BODY_FIELDS, REQUIRED_ORDER_ENTRY_FIELDS

    tree = ast.parse(Path(receivers_module.__file__).read_text(encoding="utf-8"))
    read = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }

    for name in (*REQUIRED_ORDER_ENTRY_FIELDS, *REQUIRED_ORDER_BODY_FIELDS):
        assert name in read, f"the preflight requires {name!r} and no E1 reader opens it"


@dataclass(slots=True)
class ServingApi:
    """A worker surface that answers what a running PromisePatch was built for."""

    payload: Mapping[str, Any] | None

    def readiness(self) -> Mapping[str, Any]:
        if self.payload is None:
            raise RuntimeError("the API could not be reached")
        return dict(self.payload)


def test_a_backend_serving_another_migration_head_is_refused() -> None:
    """The stale-image question, asked of a value the running process computes about itself."""
    from scripts.sur1.preflight import backend_build

    refused = backend_build(
        surface=ServingApi({"migrations": {"expected_revision": "0007_old", "at_head": True}})
    )

    assert not refused.passed
    assert "0007_old" in refused.detail


def test_a_backend_whose_database_is_behind_its_code_is_refused() -> None:
    from scripts.sur1.preflight import backend_build

    from promisepatch.db import HEAD_REVISION

    refused = backend_build(
        surface=ServingApi(
            {
                "migrations": {
                    "expected_revision": HEAD_REVISION,
                    "actual_revision": "0007_old",
                    "at_head": False,
                }
            }
        )
    )

    assert not refused.passed
    assert "0007_old" in refused.detail


def test_an_api_that_cannot_be_read_is_refused_rather_than_assumed_current() -> None:
    from scripts.sur1.preflight import backend_build

    refused = backend_build(surface=ServingApi(None))

    assert not refused.passed
    assert "could not be read" in refused.detail


def test_a_backend_at_this_source_revision_passes() -> None:
    """Including the capability the harness's own in-process world install depends on."""
    from scripts.sur1.preflight import backend_build

    from promisepatch.db import HEAD_REVISION

    allowed = backend_build(
        surface=ServingApi(
            {
                "migrations": {
                    "expected_revision": HEAD_REVISION,
                    "actual_revision": HEAD_REVISION,
                    "at_head": True,
                }
            }
        )
    )

    assert allowed.passed, allowed.detail
    assert "governed fixture load" in allowed.detail


def test_the_governed_fixture_load_takes_the_world_the_harness_installs() -> None:
    """Defect 2.2 as the record stated it, checked directly against the code that runs."""
    import inspect

    from promisepatch.fixtures.reset import reset_demo_state

    accepted = set(inspect.signature(reset_demo_state).parameters)

    assert {"snapshot", "fixture_name"} <= accepted


# ------------------------------------------------ the E1 round trip the stale projection broke


def test_an_e1_row_read_from_a_current_projection_survives_its_own_round_trip() -> None:
    """The exact disagreement that cost twenty attempts, held down from both ends.

    ``receivers._event`` is tolerant -- an event with no command is read as having none -- and
    ``replay._text`` is strict, refusing an empty string. Both are right. Against a projection
    that publishes the command they agree, and this asserts that agreement over the real
    reader, the real capture payload and the real strict reader, with nothing stubbed between
    them.
    """
    from datetime import UTC, datetime

    from scripts.sur1.bindings.receivers import OrderSystemReceiver
    from scripts.sur1.evidence import ReceiverEvidence
    from scripts.sur1.replay import evidence_from_payload

    entry = {
        "event_id": "8f0d2f4e-0000-4000-8000-000000000001",
        "external_order_id": "EXT-A",
        "type": "order.updated",
        "previous_version": 1,
        "version": 2,
        "occurred_at": "2026-09-19T20:08:00+00:00",
        "source": "amendment",
        "delivery_state": "DELIVERED",
        "attempts": 1,
        "event": {
            "command": {"idempotency_key": "pp:amend:one", "provider_ref": "ref-1"},
            "changed_line_ids": ["LINE-A"],
            "order": {"lines": [{"external_line_id": "LINE-A", "external_item_id": "ITEM-X"}]},
        },
    }

    reader = OrderSystemReceiver(base_url="http://order-system.invalid")
    event = reader._event(entry, datetime(2026, 9, 19, 20, 8, tzinfo=UTC))

    assert event.idempotency_key == "pp:amend:one"
    assert event.previous_version == 1
    assert event.line_external_item_id == "ITEM-X"

    payload = ReceiverEvidence(order_events=(event,)).as_payload()
    replayed = evidence_from_payload(payload)

    assert replayed.order_events[0].idempotency_key == "pp:amend:one"


def test_an_e1_row_read_from_the_stale_projection_is_what_broke_the_capture() -> None:
    """The failure mode itself, asserted rather than remembered.

    This is what the running container actually published: no ``event`` key at all. The reader
    writes an empty key, the capture's own round trip refuses it, and the driver calls that
    ``HARNESS_FAILURE``. Nothing here is a bug to fix downstream -- it is why
    ``order_projection`` has to ask first.
    """
    from datetime import UTC, datetime

    from scripts.sur1.bindings.receivers import OrderSystemReceiver
    from scripts.sur1.evidence import EvidenceMalformedError, ReceiverEvidence
    from scripts.sur1.replay import evidence_from_payload

    stale = {
        "event_id": "8f0d2f4e-0000-4000-8000-000000000001",
        "external_order_id": "EXT-A",
        "type": "order.updated",
        "version": 2,
        "occurred_at": "2026-09-19T20:08:00+00:00",
        "source": "amendment",
        "delivery_state": "DELIVERED",
        "attempts": 1,
    }

    reader = OrderSystemReceiver(base_url="http://order-system.invalid")
    event = reader._event(stale, datetime(2026, 9, 19, 20, 8, tzinfo=UTC))

    assert event.idempotency_key == ""

    payload = ReceiverEvidence(order_events=(event,)).as_payload()
    with pytest.raises(EvidenceMalformedError, match="idempotency_key"):
        evidence_from_payload(payload)
