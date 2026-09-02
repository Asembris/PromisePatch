"""baseline schema

Creates the ``promisepatch`` schema and every table the architecture calls for, with the
foreign keys, unique indexes and check constraints that make the frozen invariants structural
rather than conventional.

The audited-write and immutability triggers, the least-privileged application role and its
grants are deliberately not here: they are a boundary of their own and land in their own
migration, so that a review of this one is a review of shape alone.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import promisepatch.db.types

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "promisepatch"')
    op.create_table(
        "audit_events",
        sa.Column("seq", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "xid",
            promisepatch.db.types.XID8(),
            server_default=sa.text("pg_current_xact_id()"),
            nullable=False,
        ),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("track_id", sa.UUID(), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("authority", sa.String(length=24), nullable=False),
        sa.Column("rule_id", sa.String(length=32), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_kind IN ('WORKER', 'OWNER', 'CUSTOMER', 'SYSTEM', 'LLM')",
            name=op.f("ck_audit_events_actor_kind"),
        ),
        sa.CheckConstraint(
            "authority IN ('POLICY', 'CONSTRAINT', 'HUMAN_APPROVAL', 'NONE')",
            name=op.f("ck_audit_events_authority"),
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_audit_events")),
        sa.UniqueConstraint("id", name=op.f("uq_audit_events_id")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_audit_events_case_seq",
        "audit_events",
        ["case_id", "seq"],
        unique=False,
        schema="promisepatch",
    )
    op.create_index(
        "ix_audit_events_xid", "audit_events", ["xid"], unique=False, schema="promisepatch"
    )
    op.create_table(
        "case_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("track_id", sa.UUID(), nullable=True),
        sa.Column("step_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('PENDING', 'IN_FLIGHT', 'RETRYING', 'DONE', 'FAILED', 'SKIPPED')",
            name=op.f("ck_case_steps_state"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_steps")),
        sa.UniqueConstraint("case_id", "step_key", name="uq_case_steps_case_step_key"),
        schema="promisepatch",
    )
    op.create_index(
        "ix_case_steps_state_next_attempt",
        "case_steps",
        ["state", "next_attempt_at"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("clarifications_asked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "phase IN ('IDLE', 'CASE_OPEN_CLARIFYING', 'CASE_OPEN_PLANNED')",
            name=op.f("ck_conversations_phase"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        schema="promisepatch",
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("approval_channel_kind", sa.String(length=16), nullable=False),
        sa.Column("approval_channel_address", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "approval_channel_kind IN ('telegram', 'whatsapp', 'console')",
            name=op.f("ck_customers_approval_channel_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        schema="promisepatch",
    )
    op.create_table(
        "domain_events",
        sa.Column("seq", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column(
            "entity_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_domain_events")),
        sa.UniqueConstraint("event_id", name=op.f("uq_domain_events_event_id")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_domain_events_type_seq",
        "domain_events",
        ["type", "seq"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "fixture_state",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fixture_name", sa.Text(), nullable=False),
        sa.Column("fixture_digest", sa.String(length=64), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_fixture_state_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fixture_state")),
        schema="promisepatch",
    )
    op.create_table(
        "inbox_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=200), nullable=False),
        sa.Column("raw_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_body", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("normalized", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('RECEIVED', 'PROCESSED', 'FAILED', 'IGNORED')",
            name=op.f("ck_inbox_events_state"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbox_events")),
        sa.UniqueConstraint("source", "provider_event_id", name="uq_inbox_events_source_event"),
        schema="promisepatch",
    )
    op.create_index(
        "ix_inbox_events_state_received",
        "inbox_events",
        ["state", "received_at"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        sa.Column("created_in_tx_seq", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "state IN ('PENDING', 'IN_FLIGHT', 'DELIVERED', 'FAILED')",
            name=op.f("ck_outbox_messages_state"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_messages")),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_messages_idempotency_key"),
        schema="promisepatch",
    )
    op.create_index(
        "ix_outbox_messages_state_next_attempt",
        "outbox_messages",
        ["state", "next_attempt_at"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "recipes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipes")),
        schema="promisepatch",
    )
    op.create_table(
        "resources",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=16), server_default="unit", nullable=False),
        sa.CheckConstraint("kind IN ('INGREDIENT', 'EQUIPMENT')", name=op.f("ck_resources_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resources")),
        schema="promisepatch",
    )
    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
        schema="promisepatch",
    )
    op.create_table(
        "timers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(length=64), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_timers")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_timers_due_unfired",
        "timers",
        ["due_at"],
        unique=False,
        schema="promisepatch",
        postgresql_where=sa.text("fired_at IS NULL"),
    )
    op.create_table(
        "workers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('baker', 'owner')", name=op.f("ck_workers_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workers")),
        sa.UniqueConstraint("username", name=op.f("uq_workers_username")),
        schema="promisepatch",
    )
    op.create_table(
        "equipment_alternatives",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("equipment_id", sa.String(length=64), nullable=False),
        sa.Column("alternative_equipment_id", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "equipment_id <> alternative_equipment_id",
            name=op.f("ck_equipment_alternatives_distinct_equipment"),
        ),
        sa.ForeignKeyConstraint(
            ["alternative_equipment_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_equipment_alternatives_alternative_equipment_id"),
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_equipment_alternatives_equipment_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment_alternatives")),
        sa.UniqueConstraint(
            "equipment_id", "alternative_equipment_id", name="uq_equipment_alternatives_pair"
        ),
        schema="promisepatch",
    )
    op.create_table(
        "equipment_outages",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("equipment_id", sa.String(length=64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at > starts_at",
            name=op.f("ck_equipment_outages_window_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_equipment_outages_equipment_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment_outages")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_equipment_outages_equipment",
        "equipment_outages",
        ["equipment_id", "starts_at"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "inventory_ledger",
        sa.Column("seq", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("delta", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('FIXTURE', 'COMMITMENT_RECEIPT', 'EXCEPTION_FACT', 'CORRECTION', 'RESERVATION_RELEASE')",
            name=op.f("ck_inventory_ledger_source_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_inventory_ledger_resource_id"),
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_inventory_ledger")),
        sa.UniqueConstraint("source_kind", "source_id", name="uq_inventory_ledger_source"),
        schema="promisepatch",
    )
    op.create_index(
        "ix_inventory_ledger_resource_seq",
        "inventory_ledger",
        ["resource_id", "seq"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("external_version", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("mirror_source_event_id", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('ACCEPTED', 'AMENDED', 'CANCELLED', 'FULFILLED')",
            name=op.f("ck_orders_state"),
        ),
        sa.CheckConstraint(
            "external_version > 0", name=op.f("ck_orders_external_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["promisepatch.customers.id"], name=op.f("fk_orders_customer_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("external_id", name=op.f("uq_orders_external_id")),
        schema="promisepatch",
    )
    op.create_table(
        "recipe_versions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("recipe_id", sa.String(length=64), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("authored_by", sa.String(length=64), nullable=False),
        sa.Column("authored_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "btrim(authored_by) <> ''", name=op.f("ck_recipe_versions_authorship_required")
        ),
        sa.CheckConstraint("version_no > 0", name=op.f("ck_recipe_versions_version_no_positive")),
        sa.ForeignKeyConstraint(
            ["recipe_id"], ["promisepatch.recipes.id"], name=op.f("fk_recipe_versions_recipe_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipe_versions")),
        sa.UniqueConstraint("recipe_id", "version_no", name="uq_recipe_versions_recipe_version"),
        schema="promisepatch",
    )
    op.create_table(
        "resource_aliases",
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_resource_aliases_resource_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("resource_id", "alias", name=op.f("pk_resource_aliases")),
        schema="promisepatch",
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["promisepatch.workers.id"],
            name=op.f("fk_sessions_worker_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_sessions_worker_active",
        "sessions",
        ["worker_id"],
        unique=False,
        schema="promisepatch",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "supplier_commitments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("supplier_id", sa.String(length=64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["promisepatch.suppliers.id"],
            name=op.f("fk_supplier_commitments_supplier_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_commitments")),
        schema="promisepatch",
    )
    op.create_table(
        "commitment_lines",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("commitment_id", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column(
            "received_state", sa.String(length=16), server_default="EXPECTED", nullable=False
        ),
        sa.Column("received_qty", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attested_by", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "(received_state = 'EXPECTED' AND settled_at IS NULL) OR (received_state <> 'EXPECTED' AND settled_at IS NOT NULL)",
            name=op.f("ck_commitment_lines_settled_at_matches_state"),
        ),
        sa.CheckConstraint(
            "(received_state = 'SHORT' AND received_qty IS NOT NULL) OR (received_state <> 'SHORT' AND received_qty IS NULL)",
            name=op.f("ck_commitment_lines_settlement_shape"),
        ),
        sa.CheckConstraint(
            "received_state IN ('EXPECTED', 'RECEIVED', 'NOT_RECEIVED', 'SHORT')",
            name=op.f("ck_commitment_lines_received_state"),
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name=op.f("ck_commitment_lines_quantity_non_negative"),
        ),
        sa.CheckConstraint(
            "received_qty IS NULL OR received_qty >= 0",
            name=op.f("ck_commitment_lines_received_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["commitment_id"],
            ["promisepatch.supplier_commitments.id"],
            name=op.f("fk_commitment_lines_commitment_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_commitment_lines_resource_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commitment_lines")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_commitment_lines_resource_state",
        "commitment_lines",
        ["resource_id", "received_state"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "exceptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("commitment_id", sa.String(length=64), nullable=True),
        sa.Column(
            "scope_line_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("outage_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_utterance", sa.Text(), server_default="", nullable=False),
        sa.Column("reported_by", sa.String(length=64), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category IN ('SUPPLY_NOT_RECEIVED', 'STOCK_UNUSABLE', 'EQUIPMENT_UNAVAILABLE')",
            name=op.f("ck_exceptions_category"),
        ),
        sa.ForeignKeyConstraint(
            ["commitment_id"],
            ["promisepatch.supplier_commitments.id"],
            name=op.f("fk_exceptions_commitment_id"),
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["promisepatch.resources.id"], name=op.f("fk_exceptions_resource_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exceptions")),
        schema="promisepatch",
    )
    op.create_table(
        "order_constraints",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("substitute_resource_id", sa.String(length=64), nullable=True),
        sa.Column("recorded_by", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(kind = 'PREAPPROVED_ALTERNATIVE' AND resource_id IS NOT NULL AND substitute_resource_id IS NOT NULL) OR (kind = 'EXCLUDE_RESOURCE' AND resource_id IS NOT NULL AND substitute_resource_id IS NULL) OR (kind IN ('NO_SUBSTITUTION', 'ASK_BEFORE_VISIBLE_CHANGE') AND resource_id IS NULL AND substitute_resource_id IS NULL)",
            name=op.f("ck_order_constraints_constraint_shape"),
        ),
        sa.CheckConstraint(
            "btrim(recorded_by) <> ''", name=op.f("ck_order_constraints_provenance_required")
        ),
        sa.CheckConstraint(
            "kind IN ('NO_SUBSTITUTION', 'PREAPPROVED_ALTERNATIVE', 'ASK_BEFORE_VISIBLE_CHANGE', 'EXCLUDE_RESOURCE')",
            name=op.f("ck_order_constraints_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["promisepatch.orders.id"],
            name=op.f("fk_order_constraints_order_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_order_constraints_resource_id"),
        ),
        sa.ForeignKeyConstraint(
            ["substitute_resource_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_order_constraints_substitute_resource_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_constraints")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_order_constraints_order",
        "order_constraints",
        ["order_id"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "order_line_mappings",
        sa.Column("external_item_id", sa.String(length=128), nullable=False),
        sa.Column("recipe_version_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["recipe_version_id"],
            ["promisepatch.recipe_versions.id"],
            name=op.f("fk_order_line_mappings_recipe_version_id"),
        ),
        sa.PrimaryKeyConstraint("external_item_id", name=op.f("pk_order_line_mappings")),
        schema="promisepatch",
    )
    op.create_table(
        "order_lines",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("recipe_version_id", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("customization_note", sa.Text(), server_default="", nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_lines_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["promisepatch.orders.id"],
            name=op.f("fk_order_lines_order_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_version_id"],
            ["promisepatch.recipe_versions.id"],
            name=op.f("fk_order_lines_recipe_version_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_lines")),
        schema="promisepatch",
    )
    op.create_table(
        "promises",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_classification", sa.String(length=24), nullable=True),
        sa.Column("current_track_state", sa.String(length=24), nullable=True),
        sa.Column("current_case_id", sa.UUID(), nullable=True),
        sa.Column("current_track_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "current_classification IN ('UNAFFECTED', 'AUTO_RECOVERABLE', 'APPROVAL_REQUIRED', 'BLOCKED')",
            name=op.f("ck_promises_current_classification"),
        ),
        sa.CheckConstraint(
            "current_track_state IN ('PENDING', 'UNAFFECTED', 'WAITING_FOR_CUSTOMER', 'APPLYING', 'RECOVERED', 'ESCALATED', 'WITHDRAWN', 'STALE', 'LINKED')",
            name=op.f("ck_promises_current_track_state"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["promisepatch.orders.id"],
            name=op.f("fk_promises_order_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promises")),
        sa.UniqueConstraint("order_id", name="uq_promises_order_id"),
        schema="promisepatch",
    )
    op.create_table(
        "recipe_version_equipment",
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("equipment_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_recipe_version_equipment_equipment_id"),
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["promisepatch.recipe_versions.id"],
            name=op.f("fk_recipe_version_equipment_version_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "version_id", "equipment_id", name=op.f("pk_recipe_version_equipment")
        ),
        schema="promisepatch",
    )
    op.create_table(
        "recipe_version_lines",
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("qty_per_unit", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.CheckConstraint(
            "role IN ('STRUCTURAL', 'FILLING', 'VISIBLE_DECORATION')",
            name=op.f("ck_recipe_version_lines_role"),
        ),
        sa.CheckConstraint(
            "qty_per_unit IS NULL OR qty_per_unit >= 0",
            name=op.f("ck_recipe_version_lines_qty_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_recipe_version_lines_resource_id"),
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["promisepatch.recipe_versions.id"],
            name=op.f("fk_recipe_version_lines_version_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "version_id", "resource_id", "role", name=op.f("pk_recipe_version_lines")
        ),
        schema="promisepatch",
    )
    op.create_table(
        "substitution_policies",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("affected_resource_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("source_version_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_version_id", sa.String(length=64), nullable=False),
        sa.Column("substitute_resource_id", sa.String(length=64), nullable=False),
        sa.Column("visible_change", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "role IN ('STRUCTURAL', 'FILLING', 'VISIBLE_DECORATION')",
            name=op.f("ck_substitution_policies_role"),
        ),
        sa.ForeignKeyConstraint(
            ["affected_resource_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_substitution_policies_affected_resource_id"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_version_id"],
            ["promisepatch.recipe_versions.id"],
            name=op.f("fk_substitution_policies_candidate_version_id"),
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["promisepatch.recipe_versions.id"],
            name=op.f("fk_substitution_policies_source_version_id"),
        ),
        sa.ForeignKeyConstraint(
            ["substitute_resource_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_substitution_policies_substitute_resource_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_substitution_policies")),
        sa.UniqueConstraint(
            "affected_resource_id", "role", "source_version_id", name="uq_substitution_policies_key"
        ),
        schema="promisepatch",
    )
    op.create_table(
        "cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("exception_id", sa.UUID(), nullable=True),
        sa.Column("opened_by", sa.String(length=64), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("needs_owner_attention", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('RECEIVED', 'INTERPRETING', 'CLARIFYING', 'NEEDS_HUMAN_INTERPRETATION', 'ANALYZED', 'PLANNED', 'EXECUTING', 'WAITING', 'REVALIDATING', 'RECONCILING', 'RESOLVED', 'CANCELLED')",
            name=op.f("ck_cases_state"),
        ),
        sa.ForeignKeyConstraint(
            ["exception_id"], ["promisepatch.exceptions.id"], name=op.f("fk_cases_exception_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cases")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_cases_state_updated",
        "cases",
        ["state", "updated_at"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "exception_facts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("exception_id", sa.UUID(), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "posted_ledger_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("supersedes_fact_id", sa.UUID(), nullable=True),
        sa.Column("attested_by", sa.String(length=64), nullable=False),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["exception_id"],
            ["promisepatch.exceptions.id"],
            name=op.f("fk_exception_facts_exception_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_fact_id"],
            ["promisepatch.exception_facts.id"],
            name=op.f("fk_exception_facts_supersedes_fact_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exception_facts")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_exception_facts_exception",
        "exception_facts",
        ["exception_id"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "production_tasks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("order_line_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("equipment_id", sa.String(length=64), nullable=True),
        sa.Column("held_by_case_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "state IN ('SCHEDULED', 'STARTED', 'DONE', 'HELD')",
            name=op.f("ck_production_tasks_state"),
        ),
        sa.CheckConstraint(
            "scheduled_end IS NULL OR scheduled_start IS NULL OR scheduled_end >= scheduled_start",
            name=op.f("ck_production_tasks_schedule_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_production_tasks_equipment_id"),
        ),
        sa.ForeignKeyConstraint(
            ["order_line_id"],
            ["promisepatch.order_lines.id"],
            name=op.f("fk_production_tasks_order_line_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_production_tasks")),
        sa.UniqueConstraint("order_line_id", name="uq_production_tasks_order_line_id"),
        schema="promisepatch",
    )
    op.create_index(
        "ix_production_tasks_equipment_start",
        "production_tasks",
        ["equipment_id", "scheduled_start"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "reservations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("order_line_id", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("source_recipe_version_id", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0", name=op.f("ck_reservations_quantity_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["order_line_id"],
            ["promisepatch.order_lines.id"],
            name=op.f("fk_reservations_order_line_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["promisepatch.resources.id"], name=op.f("fk_reservations_resource_id")
        ),
        sa.ForeignKeyConstraint(
            ["source_recipe_version_id"],
            ["promisepatch.recipe_versions.id"],
            name=op.f("fk_reservations_source_recipe_version_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservations")),
        sa.UniqueConstraint("order_line_id", "resource_id", name="uq_reservations_line_resource"),
        schema="promisepatch",
    )
    op.create_index(
        "ix_reservations_resource",
        "reservations",
        ["resource_id"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "tracks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("promise_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("classification", sa.String(length=24), nullable=True),
        sa.Column("rule_id", sa.String(length=32), nullable=True),
        sa.Column("reason_detail", sa.String(length=48), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("chosen_option_id", sa.UUID(), nullable=True),
        sa.Column("approval_request_id", sa.UUID(), nullable=True),
        sa.Column("linked_track_id", sa.UUID(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "classification IN ('UNAFFECTED', 'AUTO_RECOVERABLE', 'APPROVAL_REQUIRED', 'BLOCKED')",
            name=op.f("ck_tracks_classification"),
        ),
        sa.CheckConstraint(
            "rule_id IN ('R-UNREACH', 'R-COVERED', 'R-PREAPPROVED', 'R-INVISIBLE-NOASK', 'R-VISIBLE-ASK', 'R-NOT-PREAPPROVED', 'R-NOSUB', 'R-EXCLUDED', 'R-SUBSTOCK', 'R-NOEQUIP', 'R-UNKNOWN', 'R-CONFLICT')",
            name=op.f("ck_tracks_rule_id"),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'UNAFFECTED', 'WAITING_FOR_CUSTOMER', 'APPLYING', 'RECOVERED', 'ESCALATED', 'WITHDRAWN', 'STALE', 'LINKED')",
            name=op.f("ck_tracks_state"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["promisepatch.cases.id"],
            name=op.f("fk_tracks_case_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linked_track_id"], ["promisepatch.tracks.id"], name=op.f("fk_tracks_linked_track_id")
        ),
        sa.ForeignKeyConstraint(
            ["promise_id"], ["promisepatch.promises.id"], name=op.f("fk_tracks_promise_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracks")),
        schema="promisepatch",
    )
    op.create_index("ix_tracks_case", "tracks", ["case_id"], unique=False, schema="promisepatch")
    op.create_index(
        "ix_tracks_one_live_per_promise",
        "tracks",
        ["promise_id"],
        unique=True,
        schema="promisepatch",
        postgresql_where=sa.text(
            "state NOT IN ('UNAFFECTED', 'RECOVERED', 'ESCALATED', 'WITHDRAWN', 'LINKED')"
        ),
    )
    op.create_table(
        "recovery_options",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("track_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("order_line_id", sa.String(length=64), nullable=True),
        sa.Column("from_version_id", sa.String(length=64), nullable=True),
        sa.Column("to_version_id", sa.String(length=64), nullable=True),
        sa.Column("from_equipment_id", sa.String(length=64), nullable=True),
        sa.Column("to_equipment_id", sa.String(length=64), nullable=True),
        sa.Column("affected_resource_id", sa.String(length=64), nullable=True),
        sa.Column("substitute_resource_id", sa.String(length=64), nullable=True),
        sa.Column("required_quantity", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("visible_change", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("requires_approval", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("approval_rule", sa.String(length=32), nullable=True),
        sa.Column(
            "cited_constraint_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("policy_id", sa.String(length=64), nullable=True),
        sa.Column("task_start", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "approval_rule IN ('R-UNREACH', 'R-COVERED', 'R-PREAPPROVED', 'R-INVISIBLE-NOASK', 'R-VISIBLE-ASK', 'R-NOT-PREAPPROVED', 'R-NOSUB', 'R-EXCLUDED', 'R-SUBSTOCK', 'R-NOEQUIP', 'R-UNKNOWN', 'R-CONFLICT')",
            name=op.f("ck_recovery_options_approval_rule"),
        ),
        sa.CheckConstraint(
            "kind IN ('SUBSTITUTE_RESOURCE', 'REASSIGN_EQUIPMENT', 'ESCALATE_TO_OWNER')",
            name=op.f("ck_recovery_options_kind"),
        ),
        sa.CheckConstraint(
            "required_quantity IS NULL OR required_quantity >= 0",
            name=op.f("ck_recovery_options_quantity_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["affected_resource_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_recovery_options_affected_resource_id"),
        ),
        sa.ForeignKeyConstraint(
            ["from_equipment_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_recovery_options_from_equipment_id"),
        ),
        sa.ForeignKeyConstraint(
            ["from_version_id"],
            ["promisepatch.recipe_versions.id"],
            name=op.f("fk_recovery_options_from_version_id"),
        ),
        sa.ForeignKeyConstraint(
            ["order_line_id"],
            ["promisepatch.order_lines.id"],
            name=op.f("fk_recovery_options_order_line_id"),
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["promisepatch.substitution_policies.id"],
            name=op.f("fk_recovery_options_policy_id"),
        ),
        sa.ForeignKeyConstraint(
            ["substitute_resource_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_recovery_options_substitute_resource_id"),
        ),
        sa.ForeignKeyConstraint(
            ["to_equipment_id"],
            ["promisepatch.resources.id"],
            name=op.f("fk_recovery_options_to_equipment_id"),
        ),
        sa.ForeignKeyConstraint(
            ["to_version_id"],
            ["promisepatch.recipe_versions.id"],
            name=op.f("fk_recovery_options_to_version_id"),
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["promisepatch.tracks.id"],
            name=op.f("fk_recovery_options_track_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recovery_options")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_recovery_options_track",
        "recovery_options",
        ["track_id"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "track_paths",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("track_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("nodes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=True),
        sa.Column("quantification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rule_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["promisepatch.tracks.id"],
            name=op.f("fk_track_paths_track_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_track_paths")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_track_paths_track", "track_paths", ["track_id"], unique=False, schema="promisepatch"
    )
    op.create_table(
        "track_watch",
        sa.Column("track_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["promisepatch.tracks.id"],
            name=op.f("fk_track_watch_track_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "track_id", "entity_type", "entity_id", name=op.f("pk_track_watch")
        ),
        schema="promisepatch",
    )
    op.create_index(
        "ix_track_watch_entity",
        "track_watch",
        ["entity_type", "entity_id"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("track_id", sa.UUID(), nullable=False),
        sa.Column("promise_id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("order_line_id", sa.String(length=64), nullable=False),
        sa.Column("option_id", sa.UUID(), nullable=False),
        sa.Column("option_code", sa.String(length=32), nullable=False),
        sa.Column("customer_channel", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("captured_order_version", sa.Integer(), nullable=False),
        sa.Column("captured_recipe_version_id", sa.String(length=64), nullable=False),
        sa.Column("captured_constraint_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("decided", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('SENT', 'CONFIRMATION_PENDING', 'ANSWERED', 'EXPIRED', 'SUPERSEDED')",
            name=op.f("ck_approval_requests_state"),
        ),
        sa.CheckConstraint(
            "deadline > sent_at", name=op.f("ck_approval_requests_deadline_after_send")
        ),
        sa.ForeignKeyConstraint(
            ["captured_recipe_version_id"],
            ["promisepatch.recipe_versions.id"],
            name=op.f("fk_approval_requests_captured_recipe_version_id"),
        ),
        sa.ForeignKeyConstraint(
            ["option_id"],
            ["promisepatch.recovery_options.id"],
            name=op.f("fk_approval_requests_option_id"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["promisepatch.orders.id"], name=op.f("fk_approval_requests_order_id")
        ),
        sa.ForeignKeyConstraint(
            ["order_line_id"],
            ["promisepatch.order_lines.id"],
            name=op.f("fk_approval_requests_order_line_id"),
        ),
        sa.ForeignKeyConstraint(
            ["promise_id"],
            ["promisepatch.promises.id"],
            name=op.f("fk_approval_requests_promise_id"),
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["promisepatch.tracks.id"],
            name=op.f("fk_approval_requests_track_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_requests")),
        schema="promisepatch",
    )
    op.create_index(
        "ix_approval_requests_state_deadline",
        "approval_requests",
        ["state", "deadline"],
        unique=False,
        schema="promisepatch",
    )
    op.create_index(
        "ix_approval_requests_track",
        "approval_requests",
        ["track_id"],
        unique=False,
        schema="promisepatch",
    )
    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("parser", sa.String(length=16), nullable=False),
        sa.Column("sender_identity", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=200), nullable=False),
        sa.Column("raw_text", sa.Text(), server_default="", nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('APPROVE', 'DECLINE')", name=op.f("ck_approval_decisions_decision")
        ),
        sa.CheckConstraint("parser = 'LITERAL'", name=op.f("ck_approval_decisions_parser")),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["promisepatch.approval_requests.id"],
            name=op.f("fk_approval_decisions_request_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_decisions")),
        sa.UniqueConstraint(
            "provider_message_id", name="uq_approval_decisions_provider_message_id"
        ),
        sa.UniqueConstraint("request_id", name="uq_approval_decisions_request_id"),
        schema="promisepatch",
    )
    op.create_table(
        "inbound_replies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=False),
        sa.Column("sender_identity", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), server_default="", nullable=False),
        sa.Column("apparent_intent", sa.String(length=24), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["promisepatch.approval_requests.id"],
            name=op.f("fk_inbound_replies_request_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_replies")),
        sa.UniqueConstraint("provider_message_id", name="uq_inbound_replies_provider_message_id"),
        schema="promisepatch",
    )
    op.create_index(
        "ix_inbound_replies_request",
        "inbound_replies",
        ["request_id"],
        unique=False,
        schema="promisepatch",
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_replies_request", table_name="inbound_replies", schema="promisepatch")
    op.drop_table("inbound_replies", schema="promisepatch")
    op.drop_table("approval_decisions", schema="promisepatch")
    op.drop_index(
        "ix_approval_requests_track", table_name="approval_requests", schema="promisepatch"
    )
    op.drop_index(
        "ix_approval_requests_state_deadline", table_name="approval_requests", schema="promisepatch"
    )
    op.drop_table("approval_requests", schema="promisepatch")
    op.drop_index("ix_track_watch_entity", table_name="track_watch", schema="promisepatch")
    op.drop_table("track_watch", schema="promisepatch")
    op.drop_index("ix_track_paths_track", table_name="track_paths", schema="promisepatch")
    op.drop_table("track_paths", schema="promisepatch")
    op.drop_index("ix_recovery_options_track", table_name="recovery_options", schema="promisepatch")
    op.drop_table("recovery_options", schema="promisepatch")
    op.drop_index(
        "ix_tracks_one_live_per_promise",
        table_name="tracks",
        schema="promisepatch",
        postgresql_where=sa.text(
            "state NOT IN ('UNAFFECTED', 'RECOVERED', 'ESCALATED', 'WITHDRAWN', 'LINKED')"
        ),
    )
    op.drop_index("ix_tracks_case", table_name="tracks", schema="promisepatch")
    op.drop_table("tracks", schema="promisepatch")
    op.drop_index("ix_reservations_resource", table_name="reservations", schema="promisepatch")
    op.drop_table("reservations", schema="promisepatch")
    op.drop_index(
        "ix_production_tasks_equipment_start", table_name="production_tasks", schema="promisepatch"
    )
    op.drop_table("production_tasks", schema="promisepatch")
    op.drop_index(
        "ix_exception_facts_exception", table_name="exception_facts", schema="promisepatch"
    )
    op.drop_table("exception_facts", schema="promisepatch")
    op.drop_index("ix_cases_state_updated", table_name="cases", schema="promisepatch")
    op.drop_table("cases", schema="promisepatch")
    op.drop_table("substitution_policies", schema="promisepatch")
    op.drop_table("recipe_version_lines", schema="promisepatch")
    op.drop_table("recipe_version_equipment", schema="promisepatch")
    op.drop_table("promises", schema="promisepatch")
    op.drop_table("order_lines", schema="promisepatch")
    op.drop_table("order_line_mappings", schema="promisepatch")
    op.drop_index(
        "ix_order_constraints_order", table_name="order_constraints", schema="promisepatch"
    )
    op.drop_table("order_constraints", schema="promisepatch")
    op.drop_table("exceptions", schema="promisepatch")
    op.drop_index(
        "ix_commitment_lines_resource_state", table_name="commitment_lines", schema="promisepatch"
    )
    op.drop_table("commitment_lines", schema="promisepatch")
    op.drop_table("supplier_commitments", schema="promisepatch")
    op.drop_index(
        "ix_sessions_worker_active",
        table_name="sessions",
        schema="promisepatch",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_table("sessions", schema="promisepatch")
    op.drop_table("resource_aliases", schema="promisepatch")
    op.drop_table("recipe_versions", schema="promisepatch")
    op.drop_table("orders", schema="promisepatch")
    op.drop_index(
        "ix_inventory_ledger_resource_seq", table_name="inventory_ledger", schema="promisepatch"
    )
    op.drop_table("inventory_ledger", schema="promisepatch")
    op.drop_index(
        "ix_equipment_outages_equipment", table_name="equipment_outages", schema="promisepatch"
    )
    op.drop_table("equipment_outages", schema="promisepatch")
    op.drop_table("equipment_alternatives", schema="promisepatch")
    op.drop_table("workers", schema="promisepatch")
    op.drop_index(
        "ix_timers_due_unfired",
        table_name="timers",
        schema="promisepatch",
        postgresql_where=sa.text("fired_at IS NULL"),
    )
    op.drop_table("timers", schema="promisepatch")
    op.drop_table("suppliers", schema="promisepatch")
    op.drop_table("resources", schema="promisepatch")
    op.drop_table("recipes", schema="promisepatch")
    op.drop_index(
        "ix_outbox_messages_state_next_attempt", table_name="outbox_messages", schema="promisepatch"
    )
    op.drop_table("outbox_messages", schema="promisepatch")
    op.drop_index(
        "ix_inbox_events_state_received", table_name="inbox_events", schema="promisepatch"
    )
    op.drop_table("inbox_events", schema="promisepatch")
    op.drop_table("fixture_state", schema="promisepatch")
    op.drop_index("ix_domain_events_type_seq", table_name="domain_events", schema="promisepatch")
    op.drop_table("domain_events", schema="promisepatch")
    op.drop_table("customers", schema="promisepatch")
    op.drop_table("conversations", schema="promisepatch")
    op.drop_index(
        "ix_case_steps_state_next_attempt", table_name="case_steps", schema="promisepatch"
    )
    op.drop_table("case_steps", schema="promisepatch")
    op.drop_index("ix_audit_events_xid", table_name="audit_events", schema="promisepatch")
    op.drop_index("ix_audit_events_case_seq", table_name="audit_events", schema="promisepatch")
    op.drop_table("audit_events", schema="promisepatch")
