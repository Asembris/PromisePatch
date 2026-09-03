"""runtime read access to the migration revision, for readiness

``/readyz`` answers one question the process cannot answer about itself: is the schema this
code was written against the schema it is actually talking to. That comparison needs to read
``alembic_version``, and it must read it *as the runtime role* -- a readiness probe that
authenticated as the migration user would be checking a connection nobody serves traffic on.

So the runtime role gains ``SELECT`` on that one table, and nothing else. Not ``INSERT``, so it
cannot claim a revision; not ``UPDATE`` or ``DELETE``, so it cannot rewrite one; no ownership,
so it cannot drop it. The application still holds no migration privilege of any kind -- it can
read which migration ran, which is the whole of what readiness needs to know.

Revision ID: 0003_runtime_readiness_access
Revises: 0002_audit_and_runtime_boundary
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_runtime_readiness_access"
down_revision: str | None = "0002_audit_and_runtime_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "promisepatch"
ROLE = "promisepatch_app"
TABLE = "alembic_version"

# The role is created by 0002 and dropped by its downgrade, so both directions here check
# rather than assume: a migration that fails because an earlier one was reversed would make
# the history unreplayable.
GRANT = f"""
DO $do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
        EXECUTE 'GRANT SELECT ON {SCHEMA}."{TABLE}" TO {ROLE}';
    END IF;
END
$do$;
"""

REVOKE = f"""
DO $do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
        EXECUTE 'REVOKE SELECT ON {SCHEMA}."{TABLE}" FROM {ROLE}';
    END IF;
END
$do$;
"""


def upgrade() -> None:
    op.execute(GRANT)


def downgrade() -> None:
    op.execute(REVOKE)
