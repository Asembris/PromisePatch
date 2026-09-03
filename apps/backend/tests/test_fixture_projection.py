"""The fixture projection, proved without a database.

Two claims are worth asserting at import speed rather than against PostgreSQL. The first is
that the projection is *structural*: it emits rows shaped by the schema and valued entirely
off the snapshot it was handed, with no Hollow Oak number, name or id written into backend
code. The second is that a projected row is loadable at all — every column exists, and every
column the database insists on is present — because discovering that in an integration run
tells you far less about which of twenty tables is wrong.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest

from promise_graph import model as engine_model
from promise_graph.examples import hollow_oak
from promise_graph.model import Record
from promise_graph.snapshot import GraphSnapshot
from promisepatch.db.base import SCHEMA, metadata
from promisepatch.db.boundary import (
    TRUNCATE_PROTECTED_TABLES,
    all_tables,
    resettable_tables,
)
from promisepatch.db.types import CHANNEL_KINDS
from promisepatch.fixtures import demo
from promisepatch.fixtures.projection import (
    PROJECTED_TABLES,
    STAFF_TABLE,
    VOLATILE_COLUMNS,
    TableRows,
    digest,
    project,
    project_staff,
)
from promisepatch.graph.channel import (
    PREFIX_BY_KIND,
    UnknownChannelError,
    join_channel,
    split_channel,
)

ANCHOR = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
OTHER_ANCHOR = ANCHOR + timedelta(hours=9, minutes=17)

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "promisepatch"

BACKEND_MODULES = tuple(
    sorted(
        path.relative_to(SOURCE_ROOT).as_posix()
        for package in ("fixtures", "graph")
        for path in (SOURCE_ROOT / package).glob("*.py")
    )
)
"""Every module on the fixture-to-database path, discovered rather than listed.

A written-down list is a list that goes stale: the module added next week is exactly the one
whose author might paste a quantity in, and it would be the one the check skipped.
"""


@pytest.fixture
def snapshot() -> GraphSnapshot:
    return demo.build_snapshot(ANCHOR)


@pytest.fixture
def projected(snapshot: GraphSnapshot) -> tuple[TableRows, ...]:
    return project(snapshot, mirrored_at=ANCHOR)


def staff_rows(created_at: datetime = ANCHOR) -> TableRows:
    return project_staff(
        demo.STAFF,
        password_hashes={seed.worker_id: f"hash:{seed.worker_id}" for seed in demo.STAFF},
        created_at=created_at,
    )


# --------------------------------------------------------------------- the reset boundary


def test_a_reset_may_empty_everything_except_the_ledgers_of_record() -> None:
    assert resettable_tables() == all_tables() - TRUNCATE_PROTECTED_TABLES
    assert not resettable_tables() & TRUNCATE_PROTECTED_TABLES


def test_the_audit_ledger_and_the_event_spine_are_never_reset() -> None:
    """The record of what was done has to outlive the state it describes."""
    assert {"audit_events", "domain_events"} & resettable_tables() == set()


# --------------------------------------------------------------------- projected shape


def test_every_projected_table_is_reset_first(projected: tuple[TableRows, ...]) -> None:
    """Writing into a table the reset does not empty would leave the previous demo behind."""
    written = {table.table for table in (*projected, staff_rows())}
    assert written <= resettable_tables()


def test_projection_emits_the_declared_tables_in_order(projected: tuple[TableRows, ...]) -> None:
    assert tuple(table.table for table in projected) == PROJECTED_TABLES


def test_every_projected_table_exists_in_the_schema() -> None:
    mapped = {table.name for table in metadata.tables.values()}
    assert set(PROJECTED_TABLES) <= mapped
    assert STAFF_TABLE in mapped


def test_no_table_is_projected_twice(projected: tuple[TableRows, ...]) -> None:
    tables = [table.table for table in (*projected, staff_rows())]
    assert len(tables) == len(set(tables))


def test_the_insert_order_is_foreign_key_safe(projected: tuple[TableRows, ...]) -> None:
    """A row is never written before a row it points at.

    Checked against the declared foreign keys rather than against a remembered order, so
    adding a table with a new reference cannot quietly break the reset.
    """
    written: set[str] = set()
    for table_rows in (*projected, staff_rows()):
        table = metadata.tables[f"{SCHEMA}.{table_rows.table}"]
        referenced = {
            key.column.table.name
            for key in table.foreign_keys
            if key.column.table.name != table.name
        }
        assert referenced <= written, f"{table.name} is written before {referenced - written}"
        written.add(table.name)


@pytest.mark.parametrize("table_name", [*PROJECTED_TABLES, STAFF_TABLE])
def test_every_projected_row_fits_its_table(
    table_name: str, projected: tuple[TableRows, ...]
) -> None:
    """Every emitted column exists, and every column the database requires is emitted."""
    table_rows = next(rows for rows in (*projected, staff_rows()) if rows.table == table_name)
    table = metadata.tables[f"{SCHEMA}.{table_name}"]
    columns = {column.name for column in table.columns}
    required = {
        column.name
        for column in table.columns
        if not column.nullable
        and column.server_default is None
        and column.default is None
        and column.autoincrement is not True
    }
    for row in table_rows.rows:
        assert set(row) <= columns, f"{table_name}: unknown columns {set(row) - columns}"
        assert required <= set(row), f"{table_name}: missing {required - set(row)}"


def test_the_ledger_is_projected_without_its_sequence_numbers(
    projected: tuple[TableRows, ...],
) -> None:
    """The database assigns them, from a sequence the reset restarts."""
    ledger = next(rows for rows in projected if rows.table == "inventory_ledger")
    assert ledger.rows
    assert all("seq" not in row for row in ledger.rows)


def test_the_ledger_is_projected_in_engine_sequence_order(
    snapshot: GraphSnapshot, projected: tuple[TableRows, ...]
) -> None:
    """Order is the only thing carrying the sequence, so it has to be the engine's order."""
    ledger = next(rows for rows in projected if rows.table == "inventory_ledger")
    assert [row["source_id"] for row in ledger.rows] == [
        entry.source_id for entry in sorted(snapshot.ledger, key=lambda entry: entry.seq)
    ]


def test_unknown_quantities_are_projected_as_unknown() -> None:
    """``None`` is not zero, and a projection that decided otherwise would fail open."""
    base = demo.build_snapshot(ANCHOR)
    line = next(iter(base.commitment_lines.values()))
    commitment = base.commitments[line.commitment_id]
    lines = tuple(
        item.model_copy(update={"quantity": None}) if item.id == line.id else item
        for item in commitment.lines
    )
    commitments = dict(base.commitments)
    commitments[commitment.id] = commitment.model_copy(update={"lines": lines})

    rows = project(base.replace(commitments=commitments), mirrored_at=ANCHOR)
    projected_lines = next(item for item in rows if item.table == "commitment_lines")
    unknown = next(row for row in projected_lines.rows if row["id"] == line.id)
    assert unknown["quantity"] is None


def test_quantities_are_projected_as_decimals(projected: tuple[TableRows, ...]) -> None:
    reservations = next(rows for rows in projected if rows.table == "reservations")
    quantities = [row["quantity"] for row in reservations.rows if row["quantity"] is not None]
    assert quantities
    assert all(isinstance(quantity, Decimal) for quantity in quantities)


# --------------------------------------------------------------------- the digest


def test_the_same_anchor_digests_the_same(snapshot: GraphSnapshot) -> None:
    first = digest(
        fixture_name=demo.FIXTURE_NAME, anchor=ANCHOR, tables=project(snapshot, mirrored_at=ANCHOR)
    )
    second = digest(
        fixture_name=demo.FIXTURE_NAME,
        anchor=ANCHOR,
        tables=project(demo.build_snapshot(ANCHOR), mirrored_at=ANCHOR),
    )
    assert first == second


def test_a_different_anchor_digests_differently(snapshot: GraphSnapshot) -> None:
    other = demo.build_snapshot(OTHER_ANCHOR)
    assert digest(
        fixture_name=demo.FIXTURE_NAME, anchor=ANCHOR, tables=project(snapshot, mirrored_at=ANCHOR)
    ) != digest(
        fixture_name=demo.FIXTURE_NAME,
        anchor=OTHER_ANCHOR,
        tables=project(other, mirrored_at=OTHER_ANCHOR),
    )


def test_a_password_hash_cannot_change_the_digest(projected: tuple[TableRows, ...]) -> None:
    """Argon2 salts every hash, so hashing them in would make identical resets look different."""
    one = project_staff(
        demo.STAFF,
        password_hashes={seed.worker_id: "hash-one" for seed in demo.STAFF},
        created_at=ANCHOR,
    )
    two = project_staff(
        demo.STAFF,
        password_hashes={seed.worker_id: "hash-two" for seed in demo.STAFF},
        created_at=ANCHOR,
    )
    assert one.rows != two.rows
    assert digest(
        fixture_name=demo.FIXTURE_NAME, anchor=ANCHOR, tables=(*projected, one)
    ) == digest(fixture_name=demo.FIXTURE_NAME, anchor=ANCHOR, tables=(*projected, two))


def test_only_the_password_hash_is_left_out_of_the_digest() -> None:
    assert frozenset({(STAFF_TABLE, "password_hash")}) == VOLATILE_COLUMNS


def test_a_changed_quantity_changes_the_digest(snapshot: GraphSnapshot) -> None:
    """The digest is a statement about domain state, so domain state has to move it."""
    resources = dict(snapshot.resources)
    first = next(iter(sorted(resources)))
    resources[first] = resources[first].model_copy(update={"name": "something else"})
    assert digest(
        fixture_name=demo.FIXTURE_NAME, anchor=ANCHOR, tables=project(snapshot, mirrored_at=ANCHOR)
    ) != digest(
        fixture_name=demo.FIXTURE_NAME,
        anchor=ANCHOR,
        tables=project(snapshot.replace(resources=resources), mirrored_at=ANCHOR),
    )


# --------------------------------------------------------------------- the channel codec


@pytest.mark.parametrize("kind", sorted(CHANNEL_KINDS))
def test_every_channel_kind_round_trips(kind: str) -> None:
    channel = join_channel(kind, "1001")
    assert split_channel(channel) == (kind, "1001")


def test_the_codec_covers_exactly_the_kinds_the_schema_permits() -> None:
    assert set(PREFIX_BY_KIND) == set(CHANNEL_KINDS)


def test_an_address_containing_a_separator_survives() -> None:
    assert split_channel("console:a:b") == ("console", "a:b")


@pytest.mark.parametrize("channel", ["1001", "sms:1001", "tg:"])
def test_an_unusable_channel_is_refused_rather_than_guessed(channel: str) -> None:
    with pytest.raises(UnknownChannelError):
        split_channel(channel)


def test_an_unknown_kind_cannot_be_written() -> None:
    with pytest.raises(UnknownChannelError):
        join_channel("carrier-pigeon", "1001")


def test_every_fixture_customer_channel_round_trips(snapshot: GraphSnapshot) -> None:
    for customer in snapshot.customers.values():
        kind, address = split_channel(customer.approval_channel)
        assert join_channel(kind, address) == customer.approval_channel


# --------------------------------------------------------------------- no literals leak


def bakery_literals(snapshot: GraphSnapshot) -> set[str]:
    """Every string and quantity the fixture authors, as it would appear if copied out."""
    values: set[str] = set()
    _collect(snapshot.resources.values(), values)
    _collect(snapshot.suppliers.values(), values)
    _collect(snapshot.commitments.values(), values)
    _collect(snapshot.recipes.values(), values)
    _collect(snapshot.versions.values(), values)
    _collect(snapshot.customers.values(), values)
    _collect(snapshot.orders.values(), values)
    _collect(snapshot.constraints.values(), values)
    _collect(snapshot.promises.values(), values)
    _collect(snapshot.tasks.values(), values)
    _collect(snapshot.reservations.values(), values)
    _collect(snapshot.ledger, values)
    _collect(snapshot.policies.values(), values)
    _collect(snapshot.equipment_alternatives.values(), values)
    # The empty string is every optional note's default, not a bakery fact.
    return values - _schema_words() - _engine_vocabulary() - {""}


def _collect(records: Iterable[Any], into: set[str]) -> None:
    for record in records:
        if isinstance(record, Record):
            _collect(record.__dict__.values(), into)
        elif isinstance(record, tuple | list):
            _collect(record, into)
        elif isinstance(record, StrEnum):
            continue
        elif isinstance(record, str):
            into.add(record)
        elif isinstance(record, Decimal):
            into.add(format(record.normalize(), "f"))


def _schema_words() -> set[str]:
    """Table and column names are the projection's own vocabulary, not the bakery's."""
    words = set()
    for table in metadata.tables.values():
        words.add(table.name)
        words.update(column.name for column in table.columns)
    return words


def _engine_vocabulary() -> set[str]:
    members: set[str] = set()
    for name in dir(engine_model):
        candidate = getattr(engine_model, name)
        if isinstance(candidate, type) and issubclass(candidate, StrEnum):
            members.update(str(member.value) for member in candidate)
    return members


def source_constants(path: Path) -> set[str]:
    """Every string literal in a module, excluding its docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        node.value
        for parent in ast.walk(tree)
        for node in ast.iter_child_nodes(parent)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docstrings
    }


@pytest.mark.parametrize("module", BACKEND_MODULES)
def test_no_bakery_value_is_written_into_backend_code(module: str, snapshot: GraphSnapshot) -> None:
    """The fixture is authored once. A copy here is a second thing to keep in step."""
    leaked = source_constants(SOURCE_ROOT / module) & bakery_literals(snapshot)
    assert leaked == set(), f"{module} restates fixture values: {sorted(leaked)}"


def test_the_leak_check_would_catch_a_leak(snapshot: GraphSnapshot) -> None:
    """A guard nobody has seen fail is a guard nobody should trust."""
    literals = bakery_literals(snapshot)
    assert hollow_oak.RASPBERRIES in literals
    assert hollow_oak.AUTHOR in literals
    assert hollow_oak.POLICY_ROSE_CROWN in literals
    assert snapshot.customers[next(iter(snapshot.customers))].approval_channel in literals
    assert "2.4" in literals


def test_the_staff_seeds_are_the_fixtures_own_people() -> None:
    """Their ids are what the fixture already attributes attestation and authorship to."""
    assert {seed.worker_id for seed in demo.STAFF} == {hollow_oak.BAKER, hollow_oak.AUTHOR}
    assert {seed.role for seed in demo.STAFF} == {demo.BAKER_ROLE, demo.OWNER_ROLE}
