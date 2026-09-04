"""worker statements, consequential clarifications, and a fact's link back to what was said

Intake needs three things the schema could not yet express, and each one is a safety property
rather than a convenience.

* **``case_reports``** is the raw statement a worker made, stored before anything is decided
  about it. The primary key is the *caller's* command id, which is what makes a retried
  transport delivery one statement rather than two; ``request_hash`` is what tells a
  redelivery of the same request apart from a different request wearing the same name. The
  table is append-only, because a worker who was wrong makes a new statement and nothing edits
  what they said.

* **``exception_clarifications``** is the question, its options and the answer that closed it.
  The options are the consequential part: each carries the commitment lines that choosing it
  would settle, captured from the delivery's own rows at the moment the question was asked, so
  an answer can only select among physical outcomes that were already possible. A partial
  unique index allows at most one unanswered question per case, and the ordinal is how the
  two-clarification ceiling is counted from stored rows rather than from a variable in a
  process that can be restarted.

* **``exception_facts.source_report_id``** connects a physical fact to the sentence that
  attested it. Without it the ledger says what changed and the audit row says who changed it,
  and nothing connects either to the words somebody actually spoke.

Nothing here weakens an existing guarantee. Both new tables are governed, both get the
trigger pair that refuses an unaudited write, and ``case_reports`` gets the immutability
trigger and the INSERT-only grant that go with an append-only ledger.

Revision ID: 0006_physical_exception_intake
Revises: 0005_durable_workflow_primitives
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_physical_exception_intake"
down_revision: str | None = "0005_durable_workflow_primitives"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "promisepatch"
ROLE = "promisepatch_app"

REPORT_KINDS = ("REPORT", "CLARIFICATION_ANSWER", "CORRECTION")
CLARIFICATION_SLOTS = ("COMMITMENT", "SCOPE")

APPEND_ONLY = ("case_reports",)
GOVERNED = ("case_reports", "exception_clarifications")
"""Both tables are governed; only the statement ledger is also immutable.

A clarification legitimately changes after it is written -- an answer arrives and is recorded
on the row. What may never change is the statement itself.
"""


def _values(members: Sequence[str]) -> str:
    return ", ".join(f"'{member}'" for member in members)


def upgrade() -> None:
    op.create_table(
        "case_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("reported_by", sa.String(length=64), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(f"kind IN ({_values(REPORT_KINDS)})", name=op.f("ck_case_reports_kind")),
        sa.CheckConstraint("ordinal > 0", name=op.f("ck_case_reports_ordinal_positive")),
        sa.CheckConstraint("btrim(raw_text) <> ''", name=op.f("ck_case_reports_raw_text_required")),
        sa.ForeignKeyConstraint(
            ["case_id"],
            [f"{SCHEMA}.cases.id"],
            name=op.f("fk_case_reports_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reported_by"],
            [f"{SCHEMA}.workers.id"],
            name=op.f("fk_case_reports_reported_by_workers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_reports")),
        sa.UniqueConstraint("case_id", "ordinal", name="uq_case_reports_case_ordinal"),
        schema=SCHEMA,
    )
    op.create_index("ix_case_reports_case", "case_reports", ["case_id", "ordinal"], schema=SCHEMA)

    op.create_table(
        "exception_clarifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(length=24), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answer_report_id", sa.Uuid(), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_option_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            f"slot IN ({_values(CLARIFICATION_SLOTS)})",
            name=op.f("ck_exception_clarifications_slot"),
        ),
        sa.CheckConstraint(
            "ordinal > 0", name=op.f("ck_exception_clarifications_ordinal_positive")
        ),
        sa.CheckConstraint(
            "btrim(question) <> ''", name=op.f("ck_exception_clarifications_question_required")
        ),
        sa.CheckConstraint(
            "(answer_report_id IS NULL) = (answered_at IS NULL)",
            name=op.f("ck_exception_clarifications_answer_shape"),
        ),
        sa.CheckConstraint(
            "resolved_option_code IS NULL OR answered_at IS NOT NULL",
            name=op.f("ck_exception_clarifications_resolution_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            [f"{SCHEMA}.cases.id"],
            name=op.f("fk_exception_clarifications_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["answer_report_id"],
            [f"{SCHEMA}.case_reports.id"],
            name=op.f("fk_exception_clarifications_answer_report_id_case_reports"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exception_clarifications")),
        sa.UniqueConstraint("case_id", "ordinal", name="uq_exception_clarifications_case_ordinal"),
        schema=SCHEMA,
    )
    # At most one unanswered question per case: a case is never waiting on two things at once,
    # and the constraint is in the database rather than in whichever process asked second.
    op.create_index(
        "ix_exception_clarifications_open",
        "exception_clarifications",
        ["case_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("answered_at IS NULL"),
    )

    op.add_column(
        "exception_facts",
        sa.Column("source_report_id", sa.Uuid(), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        op.f("fk_exception_facts_source_report_id_case_reports"),
        "exception_facts",
        "case_reports",
        ["source_report_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )

    # The boundary, extended to the two new tables exactly as 0002 installs it everywhere else.
    for table in APPEND_ONLY:
        op.execute(
            f'CREATE TRIGGER trg_00_append_only BEFORE UPDATE OR DELETE ON {SCHEMA}."{table}"'
            f" FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.reject_mutation()"
        )
    for table in GOVERNED:
        op.execute(
            f"CREATE TRIGGER trg_10_governed_write BEFORE INSERT OR UPDATE OR DELETE"
            f' ON {SCHEMA}."{table}"'
            f" FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.assert_governed_write()"
        )
        op.execute(
            f'CREATE TRIGGER trg_11_governed_truncate BEFORE TRUNCATE ON {SCHEMA}."{table}"'
            f" FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.assert_governed_write()"
        )

    for table in GOVERNED:
        privileges = "SELECT, INSERT" if table in APPEND_ONLY else "SELECT, INSERT, UPDATE, DELETE"
        op.execute(f'GRANT {privileges} ON {SCHEMA}."{table}" TO {ROLE}')


def downgrade() -> None:
    for table in GOVERNED:
        op.execute(f'REVOKE ALL ON {SCHEMA}."{table}" FROM {ROLE}')
        op.execute(f'DROP TRIGGER IF EXISTS trg_11_governed_truncate ON {SCHEMA}."{table}"')
        op.execute(f'DROP TRIGGER IF EXISTS trg_10_governed_write ON {SCHEMA}."{table}"')
    for table in APPEND_ONLY:
        op.execute(f'DROP TRIGGER IF EXISTS trg_00_append_only ON {SCHEMA}."{table}"')

    op.drop_constraint(
        op.f("fk_exception_facts_source_report_id_case_reports"),
        "exception_facts",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("exception_facts", "source_report_id", schema=SCHEMA)

    op.drop_index("ix_exception_clarifications_open", "exception_clarifications", schema=SCHEMA)
    op.drop_table("exception_clarifications", schema=SCHEMA)
    op.drop_index("ix_case_reports_case", "case_reports", schema=SCHEMA)
    op.drop_table("case_reports", schema=SCHEMA)
