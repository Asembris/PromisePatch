"""Schema properties that hold without a database.

These guard the two ways the persistence layer could quietly stop matching the engine: a
column type that cannot round-trip an engine record, and a closed vocabulary that drifts from
the enum it is supposed to mirror. Both would surface much later as a wrong classification
rather than as a failure, so they are asserted here against the metadata itself.
"""

from __future__ import annotations

import re
from enum import StrEnum

import pytest
from sqlalchemy import CheckConstraint, DateTime, Numeric, Table

from promise_graph.model import (
    ApprovalRequestState,
    Classification,
    ConstraintKind,
    ExceptionCategory,
    LedgerSourceKind,
    OptionKind,
    OrderState,
    ReceivedState,
    RecipeLineRole,
    ResourceKind,
    RuleId,
    TaskState,
)
from promisepatch.db import models as _registry  # noqa: F401  populates the metadata
from promisepatch.db.base import SCHEMA, metadata
from promisepatch.db.types import QUANTITY_PRECISION, QUANTITY_SCALE

TABLES = sorted(metadata.tables.values(), key=lambda table: table.name)
TABLE_IDS = [table.name for table in TABLES]

ENUM_COLUMNS: list[tuple[str, str, type[StrEnum]]] = [
    ("resources", "kind", ResourceKind),
    ("commitment_lines", "received_state", ReceivedState),
    ("recipe_version_lines", "role", RecipeLineRole),
    ("substitution_policies", "role", RecipeLineRole),
    ("orders", "state", OrderState),
    ("order_constraints", "kind", ConstraintKind),
    ("promises", "current_classification", Classification),
    ("production_tasks", "state", TaskState),
    ("inventory_ledger", "source_kind", LedgerSourceKind),
    ("exceptions", "category", ExceptionCategory),
    ("tracks", "classification", Classification),
    ("tracks", "rule_id", RuleId),
    ("recovery_options", "kind", OptionKind),
    ("approval_requests", "state", ApprovalRequestState),
]


def check_values(table: Table, column: str) -> set[str]:
    """The literals a column's ``IN (...)`` check permits."""
    for constraint in table.constraints:
        if not isinstance(constraint, CheckConstraint):
            continue
        text = str(constraint.sqltext)
        if not text.startswith(f"{column} IN ("):
            continue
        return set(re.findall(r"'([^']+)'", text))
    raise AssertionError(f"{table.name}.{column} has no IN check")


def test_the_schema_has_the_expected_shape() -> None:
    assert len(TABLES) == 44


@pytest.mark.parametrize("table", TABLES, ids=TABLE_IDS)
def test_every_table_lives_in_the_private_schema(table: Table) -> None:
    """Nothing goes in ``public``, where a managed host may expose it automatically."""
    assert table.schema == SCHEMA


@pytest.mark.parametrize("table", TABLES, ids=TABLE_IDS)
def test_every_timestamp_column_is_timezone_aware(table: Table) -> None:
    """A naive timestamp cannot round-trip: engine records reject a datetime with no zone."""
    for column in table.columns:
        if isinstance(column.type, DateTime):
            assert column.type.timezone, f"{table.name}.{column.name} is not TIMESTAMPTZ"


@pytest.mark.parametrize("table", TABLES, ids=TABLE_IDS)
def test_every_quantity_column_matches_the_engine_scale(table: Table) -> None:
    """Three decimal places, exactly -- the scale the engine normalises every quantity to."""
    for column in table.columns:
        if isinstance(column.type, Numeric):
            assert (column.type.precision, column.type.scale) == (
                QUANTITY_PRECISION,
                QUANTITY_SCALE,
            ), f"{table.name}.{column.name} has the wrong numeric scale"


@pytest.mark.parametrize("table", TABLES, ids=TABLE_IDS)
def test_no_column_is_a_float(table: Table) -> None:
    """The engine refuses to build a quantity from a float; the schema must not reintroduce one."""
    for column in table.columns:
        assert "FLOAT" not in column.type.__class__.__name__.upper()
        assert "DOUBLE" not in column.type.__class__.__name__.upper()


@pytest.mark.parametrize(
    ("table_name", "column", "enum_cls"),
    ENUM_COLUMNS,
    ids=[f"{t}.{c}" for t, c, _ in ENUM_COLUMNS],
)
def test_closed_vocabularies_match_the_engine(
    table_name: str, column: str, enum_cls: type[StrEnum]
) -> None:
    """A value the database accepts but the engine cannot parse is a row nobody can load."""
    table = metadata.tables[f"{SCHEMA}.{table_name}"]
    assert check_values(table, column) == {member.value for member in enum_cls}


def test_only_the_literal_parser_can_produce_a_decision() -> None:
    """The consent boundary, as a constraint rather than a convention."""
    table = metadata.tables[f"{SCHEMA}.approval_decisions"]
    texts = {str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}
    assert "parser = 'LITERAL'" in texts


def test_every_check_constraint_is_named() -> None:
    """An anonymous check that fires in production names nothing an operator can act on."""
    for table in TABLES:
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint):
                assert constraint.name, f"{table.name} has an unnamed check"
