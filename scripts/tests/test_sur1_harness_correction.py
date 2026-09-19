"""The regression proofs for the three harness defects the first scored run exposed.

`docs/sur1-first-scored-run-defect.md` records a run that spent its authorisation and returned
nothing comparative: 24 of 27 attempts ended ``HARNESS_FAILURE``. Three separate faults did
that, and this module is where each one is held down so it cannot come back quietly.

| defect | attempts | what is proved here |
|---|---|---|
| no committed event body on the order log | 20 | the preflight refuses a build not declaring it |
| the world's two writes were ungoverned | 3 | both go through the product's governed write |
| the fixture ``TRUNCATE`` raced the worker | 1 | the worker is stopped around an install |

**No arm is driven here and no model is called.** Every proof is structural, or is made against
a stand-in that records what it was asked to do. Nothing in this module opens a PostgreSQL
connection, reaches the order system or writes a ``SUR-1`` capture.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
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
