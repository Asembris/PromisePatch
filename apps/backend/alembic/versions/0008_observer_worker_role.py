"""a principal that may be shown a case and may change nothing

``workers.role`` has admitted two values since the baseline: the baker who attests physical
facts, and the owner who resolves escalations. Both may speak on a case. This adds a third,
``observer``, which may not.

The reason it is a role on the worker row rather than a scope on a session is that the refusal
then belongs to the domain. Every write in this system gates on
``promisepatch.domain.intake.require_permitted``, which admits the worker who opened the case or
an owner, and knows nothing about observers -- so a write added later with no observer check
still refuses one. A session-scope check would have to be remembered by every transport, and the
first one that forgot would fail open.

Nothing is granted by this migration. ``workers`` is ungoverned infrastructure whose privileges
the runtime role already holds, and widening a ``CHECK`` admits a value, not a person: a row has
to be seeded before an observer exists, and the seeded one carries a password hash Argon2 cannot
parse, so it can never be reached by ``POST /api/auth/login`` at all.

Revision ID: 0008_observer_worker_role
Revises: 0007_external_effect_results
Create Date: 2026-09-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_observer_worker_role"
down_revision: str | None = "0007_external_effect_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "promisepatch"
TABLE = "workers"
CONSTRAINT = "ck_workers_role"

BEFORE = ("baker", "owner")
AFTER = ("baker", "owner", "observer")

AUDIT_MARKER = "promisepatch.audit_event_id"
AUDIT_EVENT_TYPE = "schema.observer_role_removed"
"""Restated rather than imported: a migration must keep working against the code of its own day.

``promisepatch.db.boundary`` may be refactored, renamed or reorganised long after this revision
is history, and a migration that imported from it would stop running the moment it was. The
literal is asserted against the constant by the migration-history suite instead.
"""


def _rendered(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _replace(values: tuple[str, ...]) -> None:
    """Swap the vocabulary the ``CHECK`` admits, under its own name.

    Spelled out rather than left to ``op.create_check_constraint``'s naming convention: the
    constraint the baseline created is named in the baseline, a later migration has to be able to
    refer to it by that name, and a violation message is only useful when it names the rule.
    """
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE} ADD CONSTRAINT {CONSTRAINT} "
        f"CHECK (role IN ({_rendered(values)}))"
    )


def upgrade() -> None:
    _replace(AFTER)


def downgrade() -> None:
    """Narrow the vocabulary again, after removing anything it would no longer admit.

    The delete is not incidental: a ``CHECK`` cannot be created against rows that violate it, so
    a downgrade that left an observer seeded would fail halfway through. An observer row holds
    no attestation and authorises nothing, so nothing is lost with it.

    It is audited, because ``workers`` is a governed table and a migration is not exempt from the
    write boundary. Removing a principal from the system is exactly the kind of change the ledger
    exists to answer for, so the audit row is written first and the delete is performed under it
    -- the same order every other governed write in this system uses.
    """
    op.execute(
        f"""
        WITH authorisation AS (
            INSERT INTO {SCHEMA}.audit_events (
                id, type, actor_kind, actor_id, authority, after, correlation_id
            )
            VALUES (
                gen_random_uuid(),
                '{AUDIT_EVENT_TYPE}',
                'SYSTEM',
                'alembic downgrade {revision}',
                'NONE',
                '{{"removed_role": "observer"}}'::jsonb,
                gen_random_uuid()
            )
            RETURNING seq
        )
        SELECT set_config('{AUDIT_MARKER}', seq::text, true) FROM authorisation
        """
    )
    op.execute(f"DELETE FROM {SCHEMA}.{TABLE} WHERE role = 'observer'")
    op.execute(f"SELECT set_config('{AUDIT_MARKER}', '', true)")
    _replace(BEFORE)
