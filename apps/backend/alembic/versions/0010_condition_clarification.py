"""a clarification that asks the worker whether a model's proposed condition holds

A model may propose what a sentence the lexicon could not read is about: a category and one of
the bakery's things. Until now that proposal, once the resource was found written in the
sentence, went straight on to a physical fact -- so "I need the heavy cream invoice" read as
unusable stock by a model became a written-off cream, although nothing in the words said the
cream was anything at all.

A model's category is now a question to the worker before it is a fact. The question is a
clarification like the two that already exist, persisted in the same governed table and
answered through the same path, and it needs one more value in the closed vocabulary of what
a clarification may be about. That value is the whole of this migration: no column, no table
and no data changes.

Revision ID: 0010_condition_clarification
Revises: 0009_human_plan_approval
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_condition_clarification"
down_revision: str | None = "0009_human_plan_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "promisepatch"
TABLE = "exception_clarifications"
CONSTRAINT = "ck_exception_clarifications_slot"

BEFORE = ("COMMITMENT", "SCOPE")
AFTER = ("COMMITMENT", "SCOPE", "CONDITION")
"""Restated rather than imported, like every other vocabulary a migration writes.

``AFTER`` is asserted against ``promisepatch.db.types.CLARIFICATION_SLOTS`` by the
migration-history suite.
"""


def _values(members: Sequence[str]) -> str:
    return ", ".join(f"'{member}'" for member in members)


def _replace(members: Sequence[str]) -> None:
    op.drop_constraint(op.f(CONSTRAINT), TABLE, schema=SCHEMA, type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT), TABLE, f"slot IN ({_values(members)})", schema=SCHEMA
    )


def upgrade() -> None:
    _replace(AFTER)


def downgrade() -> None:
    # Refused rather than silently narrowed while a row still names the slot: a downgrade that
    # deleted an asked question would be rewriting what the worker was asked.
    _replace(BEFORE)
