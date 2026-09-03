"""audit boundary, append-only enforcement and the least-privileged runtime role

Three things land together because they are one boundary:

* **The governed-write trigger.** A write to a domain table is refused unless the same
  transaction has already inserted the audit event that authorises it, proven by matching
  ``pg_current_xact_id()`` rather than by the mere existence of a row somewhere. An audit
  marker left over from an earlier, committed transaction is therefore worthless.
* **Append-only enforcement.** Authored history and physical ledgers refuse UPDATE and DELETE
  outright. The trigger name sorts first so immutability is decided before authorisation:
  being allowed to write is not the same as being allowed to rewrite.
* **The runtime role.** ``promisepatch_app`` owns nothing, migrates nothing, cannot disable a
  trigger, and holds no UPDATE, DELETE or TRUNCATE on any append-only ledger. Privilege and
  trigger say the same thing twice, on purpose: the trigger survives a privilege mistake, and
  the privilege survives a trigger somebody found a way around.

The table lists are written out rather than derived from the models. A migration is a record of
what was applied on a date, and it must keep meaning that after the application's own idea of
the boundary moves on; the two are held together by a test that compares the live database with
``promisepatch.db.boundary``, not by a shared import.

Revision ID: 0002_audit_and_runtime_boundary
Revises: 0001_baseline
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from promisepatch.config import Settings

revision: str = "0002_audit_and_runtime_boundary"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "promisepatch"
ROLE = "promisepatch_app"
MARKER = "promisepatch.audit_event_id"

# Domain state. Every insert, update, delete or truncate here needs an audit event first.
GOVERNED_TABLES: tuple[str, ...] = (
    "approval_decisions",
    "approval_requests",
    "cases",
    "commitment_lines",
    "customers",
    "equipment_alternatives",
    "equipment_outages",
    "exception_facts",
    "exceptions",
    "inbound_replies",
    "inventory_ledger",
    "order_constraints",
    "order_line_mappings",
    "order_lines",
    "orders",
    "production_tasks",
    "promises",
    "recipe_version_equipment",
    "recipe_version_lines",
    "recipe_versions",
    "recipes",
    "recovery_options",
    "reservations",
    "resource_aliases",
    "resources",
    "substitution_policies",
    "supplier_commitments",
    "suppliers",
    "track_paths",
    "track_watch",
    "tracks",
    "workers",
)

# The audit ledger itself, the event spine, and the machinery of the durable engine. Requiring
# an audit event to store an inbound webhook would audit an arrival nobody has decided anything
# about yet; requiring one to write `audit_events` would be circular.
UNGOVERNED_TABLES: tuple[str, ...] = (
    "audit_events",
    "case_steps",
    "conversations",
    "domain_events",
    "fixture_state",
    "inbox_events",
    "outbox_messages",
    "sessions",
    "timers",
)

# Authored history and physical postings: correcting one means appending, never overwriting.
APPEND_ONLY_TABLES: tuple[str, ...] = (
    "approval_decisions",
    "audit_events",
    "domain_events",
    "exception_facts",
    "inventory_ledger",
    "recipe_version_equipment",
    "recipe_version_lines",
    "recipe_versions",
)

# Ledgers no authorisation can empty. Every other table's TRUNCATE is merely governed.
TRUNCATE_PROTECTED_TABLES: tuple[str, ...] = ("audit_events", "domain_events")

RUNTIME_SEQUENCES: tuple[str, ...] = (
    "audit_events_seq_seq",
    "domain_events_seq_seq",
    "inventory_ledger_seq_seq",
)

SUPABASE_API_ROLES: tuple[str, ...] = ("anon", "authenticated", "service_role")

ASSERT_GOVERNED_WRITE = f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.assert_governed_write() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, {SCHEMA}
AS $function$
DECLARE
    marker text := current_setting('{MARKER}', true);
    audit_seq bigint;
BEGIN
    IF marker IS NULL OR btrim(marker) = '' THEN
        RAISE EXCEPTION
            'ungoverned write: % on %.% has no audit event in this transaction',
            TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    BEGIN
        audit_seq := marker::bigint;
    EXCEPTION WHEN others THEN
        RAISE EXCEPTION
            'unusable audit marker %: % on %.% cannot be authorised',
            marker, TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END;

    IF NOT EXISTS (
        SELECT 1 FROM {SCHEMA}.audit_events
        WHERE seq = audit_seq AND xid = pg_current_xact_id()
    ) THEN
        RAISE EXCEPTION
            'stale audit marker: audit event % was not written by this transaction (% on %.%)',
            audit_seq, TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    RETURN NULL;
END;
$function$;
"""

REJECT_MUTATION = f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.reject_mutation() RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION
        '%.% is append-only: % is never permitted',
        TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$function$;
"""

CREATE_ROLE = f"""
DO $do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
        EXECUTE format(
            'ALTER ROLE {ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
            ' NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
            current_setting('promisepatch.bootstrap_password')
        );
    ELSE
        EXECUTE format(
            'CREATE ROLE {ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
            ' NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
            current_setting('promisepatch.bootstrap_password')
        );
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO {ROLE}', current_database());
END
$do$;
"""

REVOKE_API_ROLES = f"""
DO $do$
DECLARE
    api_role text;
BEGIN
    FOREACH api_role IN ARRAY ARRAY[{", ".join(f"'{r}'" for r in SUPABASE_API_ROLES)}]
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA {SCHEMA} FROM %I', api_role);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM %I', api_role);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA {SCHEMA} FROM %I', api_role);
            EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {SCHEMA} FROM %I', api_role);
        END IF;
    END LOOP;
END
$do$;
"""

REVOKE_RUNTIME_ROLE = f"""
DO $do$
DECLARE
    relation text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
        RETURN;
    END IF;
    FOREACH relation IN ARRAY ARRAY[{{RELATIONS}}]
    LOOP
        EXECUTE format('REVOKE ALL ON %I.%I FROM {ROLE}', '{SCHEMA}', relation);
    END LOOP;
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM {ROLE}', current_database());
    REVOKE ALL ON SCHEMA {SCHEMA} FROM {ROLE};
    DROP ROLE {ROLE};
END
$do$;
"""


def _privileges(table: str) -> str:
    """An append-only ledger is granted nothing that could rewrite or empty it."""
    return "SELECT, INSERT" if table in APPEND_ONLY_TABLES else "SELECT, INSERT, UPDATE, DELETE"


def upgrade() -> None:
    op.execute(ASSERT_GOVERNED_WRITE)
    op.execute(REJECT_MUTATION)

    # Immutability first: `trg_00_` sorts before `trg_10_`, so an update to an append-only table
    # is refused as immutable even inside a transaction that was properly authorised.
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f'CREATE TRIGGER trg_00_append_only BEFORE UPDATE OR DELETE ON {SCHEMA}."{table}"'
            f" FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.reject_mutation()"
        )
    for table in TRUNCATE_PROTECTED_TABLES:
        op.execute(
            f'CREATE TRIGGER trg_01_no_truncate BEFORE TRUNCATE ON {SCHEMA}."{table}"'
            f" FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.reject_mutation()"
        )

    for table in GOVERNED_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_10_governed_write BEFORE INSERT OR UPDATE OR DELETE"
            f' ON {SCHEMA}."{table}"'
            f" FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.assert_governed_write()"
        )
        op.execute(
            f'CREATE TRIGGER trg_11_governed_truncate BEFORE TRUNCATE ON {SCHEMA}."{table}"'
            f" FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.assert_governed_write()"
        )

    password = Settings().require_db_app_password()
    bind = op.get_bind()
    # The credential is passed as a bind parameter and quoted by `format(%L)` inside the DO
    # block, so it is never interpolated into this file or into a migration script on disk.
    bind.execute(
        sa.text("SELECT set_config('promisepatch.bootstrap_password', :password, true)"),
        {"password": password},
    )
    op.execute(CREATE_ROLE)

    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")
    op.execute(REVOKE_API_ROLES)

    # Explicit, per-table grants. `GRANT ... ON ALL TABLES` would silently widen the moment a
    # table is added, and the point of this role is that its reach is written down.
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE}")
    for table in sorted((*GOVERNED_TABLES, *UNGOVERNED_TABLES)):
        op.execute(f'GRANT {_privileges(table)} ON {SCHEMA}."{table}" TO {ROLE}')
    for sequence in RUNTIME_SEQUENCES:
        # USAGE, not UPDATE: nextval is required, setval would let a ledger be rewound.
        op.execute(f'GRANT USAGE ON SEQUENCE {SCHEMA}."{sequence}" TO {ROLE}')


def downgrade() -> None:
    relations = ", ".join(
        f"'{name}'" for name in sorted((*GOVERNED_TABLES, *UNGOVERNED_TABLES, *RUNTIME_SEQUENCES))
    )
    op.execute(REVOKE_RUNTIME_ROLE.replace("{RELATIONS}", relations))

    for table in GOVERNED_TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS trg_11_governed_truncate ON {SCHEMA}."{table}"')
        op.execute(f'DROP TRIGGER IF EXISTS trg_10_governed_write ON {SCHEMA}."{table}"')
    for table in TRUNCATE_PROTECTED_TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS trg_01_no_truncate ON {SCHEMA}."{table}"')
    for table in APPEND_ONLY_TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS trg_00_append_only ON {SCHEMA}."{table}"')

    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.assert_governed_write()")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.reject_mutation()")
