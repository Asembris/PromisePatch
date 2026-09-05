"""what a provider actually did, recorded beside the effect that asked it to

Until now an outbound effect recorded that a provider accepted it and the reference it gave
back. That was enough while every provider was a fake one: acceptance was the whole of the
answer, and there was nothing on the other side whose state we could later be wrong about.

An external system of record changes that. When PromisePatch pushes a recovery amendment at the
order system, the answer is not merely "accepted" -- it is *this order is now at version N with
this variant on this line*. That statement is what a recovery is later required to see reflected
in the mirror before it may call itself complete, and it has to survive the process that
received it. Holding it in memory would mean a worker that died between the provider's answer
and the recovery's completion had lost the only description of what the provider did.

So the outbox row gains one nullable ``JSONB`` column. Nullable because most effects have no
such answer to give and inventing an empty one would blur the difference between "the provider
reported nothing" and "the provider reported nothing *yet*".

Nothing else moves. ``outbox_messages`` is ungoverned infrastructure, it is not append-only, and
the runtime role already holds the privileges it needs on it, so this migration is a column and
no policy change at all.

Revision ID: 0007_external_effect_results
Revises: 0006_physical_exception_intake
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_external_effect_results"
down_revision: str | None = "0006_physical_exception_intake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "promisepatch"
TABLE = "outbox_messages"
COLUMN = "result"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(COLUMN, postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN, schema=SCHEMA)
