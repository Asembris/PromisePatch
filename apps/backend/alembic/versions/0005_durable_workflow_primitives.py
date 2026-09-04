"""commit-ordered domain events, step and effect leases, live-timer uniqueness

Four changes land together because they are the one thing a worker needs before it may write:
a durable unit of work that exactly one process owns, and an event spine a forward-only reader
can trust.

* **Commit-ordered ``domain_events.seq``.** ``seq`` is drawn at INSERT and becomes visible at
  COMMIT, so two overlapping writers could commit sequence values out of order and a cursor
  that only moves forward would step over the later-committing, lower-numbered row. Until now
  the only writer was the fixture reset, which serialised itself; a worker is the second
  writer, and the fix has to be structural. A ``BEFORE INSERT`` trigger takes a transaction
  advisory lock and *then* draws the sequence value, so a transaction cannot obtain a number
  until every transaction holding a lower unfinished number has committed or rolled back. The
  guarantee is exactly ``seq(e1) < seq(e2) ⇒ commit(e1) < commit(e2)`` for committed rows.

  The column default is left in place. It draws a value that the trigger then discards, so the
  sequence advances by two per row and the committed numbers have gaps. That is the deliberate
  trade: gaplessness was never the property anything depends on, and removing the default
  would leave a direct INSERT that bypassed the trigger with a null primary key instead of a
  wrong one.

  **Lock discipline.** The advisory lock is the *last* lock an event-producing transaction may
  acquire. Appending an event and then waiting on an unrelated row lock would let one
  transaction hold the whole spine while a second, holding the row it wants, queued behind it.
  The order every writer follows is: ``case_steps`` row, ``cases`` row, the timer / inbox /
  outbox rows it owns, then the event lock, then commit.

* **Case-step leases.** ``lease_owner`` and ``lease_expires_at`` say which worker is executing
  a step and until when, so a process that dies is a lease that expires rather than a step that
  is stuck forever. ``attempts`` doubles as the fencing token: it is incremented by the claim,
  so a reclaimed step carries a number the stalled worker cannot match, and the stalled worker's
  own completion update matches no row.

* **Live-timer uniqueness.** One unfired timer per ``(kind, subject_type, subject_id)``. Arming
  the same deadline twice is then a no-op in the database rather than two wake-ups, and once a
  timer has fired the same semantic deadline may be armed again.

* **Outbox leases and delivery bookkeeping.** The same lease shape as steps, plus the fields a
  dispatcher needs to say honestly what happened: when a message was accepted, and what the
  last failure said.

Revision ID: 0005_durable_workflow_primitives
Revises: 0004_domain_event_notifications
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_durable_workflow_primitives"
down_revision: str | None = "0004_domain_event_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "promisepatch"
FUNCTION = "assign_commit_ordered_seq"
TRIGGER = "trg_05_commit_ordered_seq"
SEQUENCE = "domain_events_seq_seq"

EVENT_ORDER_LOCK_KEY = 3326604242101168682
"""``pg_advisory_xact_lock`` key for the event spine.

The first eight bytes of ``sha256('promisepatch.domain_event_order')`` read as a signed
big-endian integer, which is the same derivation the fixture reset uses for its own lock: a key
that cannot collide by accident with another application sharing the database. The literal is
written out here because a migration is a record of what was applied, and a test asserts it
still equals the value :mod:`promisepatch.db.boundary` derives.
"""

# `trg_05_` sorts after the immutability guards installed by 0002 and before the notification
# installed by 0004. The first two are BEFORE STATEMENT and the last is AFTER INSERT, so the
# ordering is really about reading the inventory rather than about firing order -- except for
# the one that matters: `trg_20_notify_domain_event` reads `NEW.seq`, and a BEFORE ROW trigger
# is the only place that value can still be decided.
ASSIGN_COMMIT_ORDERED_SEQ = f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.{FUNCTION}() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, {SCHEMA}
AS $function$
BEGIN
    -- Serialise the *drawing* of sequence numbers, not the work that led to them. The lock is
    -- held until commit, so a transaction that has a number is the only one that can have the
    -- next one, and a reader walking `seq` forward can never step over an unfinished row.
    PERFORM pg_advisory_xact_lock({EVENT_ORDER_LOCK_KEY});
    NEW.seq := nextval('{SCHEMA}.{SEQUENCE}');
    RETURN NEW;
END;
$function$;
"""

# Two predicates, one meaning: a step is executing if and only if a named worker holds it until
# a stated instant. A row claiming IN_FLIGHT with no lease could never be reclaimed, because
# nothing would say when its owner's claim ran out.
IN_FLIGHT_LEASE = (
    "state <> 'IN_FLIGHT' OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)"
)

# Written as SQL rather than through `op.create_check_constraint`, which applies the metadata
# naming convention to whatever it is handed and would turn `ck_case_steps_in_flight_lease`
# into `ck_case_steps_ck_case_steps_in_flight_lease`. The name a violation reports has to be
# the name the models declare, so it is stated once, exactly, here.
CHECKS: tuple[tuple[str, str, str], ...] = (
    ("case_steps", "ck_case_steps_attempts_non_negative", "attempts >= 0"),
    ("case_steps", "ck_case_steps_in_flight_lease", IN_FLIGHT_LEASE),
    ("outbox_messages", "ck_outbox_messages_attempts_non_negative", "attempts >= 0"),
    ("outbox_messages", "ck_outbox_messages_in_flight_lease", IN_FLIGHT_LEASE),
)


def upgrade() -> None:
    op.execute(ASSIGN_COMMIT_ORDERED_SEQ)
    op.execute(
        f'CREATE TRIGGER {TRIGGER} BEFORE INSERT ON {SCHEMA}."domain_events"'
        f" FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{FUNCTION}()"
    )

    # ------------------------------------------------------------------ case-step leases
    op.add_column(
        "case_steps",
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "case_steps",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "case_steps",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_case_steps_lease_expires_at",
        "case_steps",
        ["lease_expires_at"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("state = 'IN_FLIGHT'"),
    )

    # ---------------------------------------------------------------- live-timer uniqueness
    op.create_index(
        "ix_timers_live_subject",
        "timers",
        ["kind", "subject_type", "subject_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("fired_at IS NULL"),
    )

    # ----------------------------------------------------------------------- outbox leases
    op.add_column(
        "outbox_messages",
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "outbox_messages",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "outbox_messages", sa.Column("last_error", sa.Text(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "outbox_messages",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "outbox_messages",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_outbox_messages_lease_expires_at",
        "outbox_messages",
        ["lease_expires_at"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("state = 'IN_FLIGHT'"),
    )

    for table, name, predicate in CHECKS:
        op.execute(f'ALTER TABLE {SCHEMA}."{table}" ADD CONSTRAINT {name} CHECK ({predicate})')


def downgrade() -> None:
    for table, name, _predicate in reversed(CHECKS):
        op.execute(f'ALTER TABLE {SCHEMA}."{table}" DROP CONSTRAINT IF EXISTS {name}')

    op.drop_index("ix_outbox_messages_lease_expires_at", "outbox_messages", schema=SCHEMA)
    for column in ("created_at", "delivered_at", "last_error", "lease_expires_at", "lease_owner"):
        op.drop_column("outbox_messages", column, schema=SCHEMA)

    op.drop_index("ix_timers_live_subject", "timers", schema=SCHEMA)

    op.drop_index("ix_case_steps_lease_expires_at", "case_steps", schema=SCHEMA)
    for column in ("created_at", "lease_expires_at", "lease_owner"):
        op.drop_column("case_steps", column, schema=SCHEMA)

    op.execute(f'DROP TRIGGER IF EXISTS {TRIGGER} ON {SCHEMA}."domain_events"')
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{FUNCTION}()")
