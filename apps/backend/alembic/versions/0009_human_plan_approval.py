"""the human approval a confirmation consumes, written only where a person was authenticated

Until now a plan confirmation was minted by whoever called the confirming service. Over the
browser that caller was a signed-in person and the audit row saying ``HUMAN_APPROVAL`` was
true. Over the MCP surface the caller was a process holding a shared service token, and the
same row said the same thing about a human nobody had authenticated -- a model that could
reach the tool could produce evidence that a worker had approved a plan they had never been
read.

So the approval becomes a row of its own, written before and separately from the confirmation
that consumes it. ``channel`` is checked against a closed pair naming the two paths on which
this system authenticates a person; there is no member for a service surface, so the MCP path
cannot write here at all. ``(case_id, plan_id)`` is unique, which makes an approval bound to
one exact plan rather than to a case, and a second yes to the same plan the same yes.

Governed, because an approval is domain state and is the one authority in the conversational
surface that is not the engine's own bookkeeping: writing one requires the audit event that
says who approved what. Append-only, because it is an authored record of what somebody
claimed. A plan that should no longer execute is withdrawn, which is its own authority with
its own row -- an approval is never edited away.

Revision ID: 0009_human_plan_approval
Revises: 0008_observer_worker_role
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_human_plan_approval"
down_revision: str | None = "0008_observer_worker_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "promisepatch"
ROLE = "promisepatch_app"
TABLE = "plan_approvals"

CHANNELS = ("BROWSER_SESSION", "OPERATOR_CONSOLE")
"""Restated rather than imported, like every other vocabulary a migration writes.

A migration has to keep running against the code of its own day, and the runtime constant it
mirrors -- ``promisepatch.db.types.APPROVAL_CHANNELS`` -- is asserted against this tuple by the
migration-history suite instead.
"""


def _values(members: Sequence[str]) -> str:
    return ", ".join(f"'{member}'" for member in members)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("approved_by", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"channel IN ({_values(CHANNELS)})", name=op.f("ck_plan_approvals_channel")
        ),
        sa.CheckConstraint("btrim(plan_id) <> ''", name=op.f("ck_plan_approvals_plan_id_required")),
        sa.CheckConstraint(
            "btrim(evidence) <> ''", name=op.f("ck_plan_approvals_evidence_required")
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            [f"{SCHEMA}.cases.id"],
            name=op.f("fk_plan_approvals_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            [f"{SCHEMA}.workers.id"],
            name=op.f("fk_plan_approvals_approved_by_workers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_approvals")),
        sa.UniqueConstraint("case_id", "plan_id", name="uq_plan_approvals_case_plan"),
        schema=SCHEMA,
    )

    # The boundary, installed exactly as 0002 installs it everywhere else. Append-only first,
    # so an attempt to edit an approval fails as immutable rather than as unaudited.
    op.execute(
        f'CREATE TRIGGER trg_00_append_only BEFORE UPDATE OR DELETE ON {SCHEMA}."{TABLE}"'
        f" FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.reject_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER trg_10_governed_write BEFORE INSERT OR UPDATE OR DELETE"
        f' ON {SCHEMA}."{TABLE}"'
        f" FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.assert_governed_write()"
    )
    op.execute(
        f'CREATE TRIGGER trg_11_governed_truncate BEFORE TRUNCATE ON {SCHEMA}."{TABLE}"'
        f" FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.assert_governed_write()"
    )
    op.execute(f'GRANT SELECT, INSERT ON {SCHEMA}."{TABLE}" TO {ROLE}')


def downgrade() -> None:
    op.execute(f'REVOKE ALL ON {SCHEMA}."{TABLE}" FROM {ROLE}')
    op.execute(f'DROP TRIGGER IF EXISTS trg_11_governed_truncate ON {SCHEMA}."{TABLE}"')
    op.execute(f'DROP TRIGGER IF EXISTS trg_10_governed_write ON {SCHEMA}."{TABLE}"')
    op.execute(f'DROP TRIGGER IF EXISTS trg_00_append_only ON {SCHEMA}."{TABLE}"')
    op.drop_table(TABLE, schema=SCHEMA)
