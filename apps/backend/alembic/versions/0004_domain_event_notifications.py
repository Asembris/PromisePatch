"""wake-up notifications for committed domain events

The live feed needs to learn that the event spine has moved. It could poll, and it would then
be either slow or expensive; instead PostgreSQL tells us, and it tells us at exactly the right
moment, because ``NOTIFY`` is delivered on commit and never before.

Two decisions here are the whole design:

* **The notification is attached to the insert, not to the caller.** A trigger on
  ``domain_events`` means a call site cannot append an event and forget to announce it -- and
  cannot announce one it then rolls back, because a rolled-back transaction sends nothing. The
  alternative, an application-level publish after commit, is a rule every future writer has to
  remember and a window in which the two can disagree.
* **The payload is the sequence number and nothing else.** A notification is a wake-up hint,
  not a delivery mechanism: the durable row is the state, and a listener reads the ledger to
  learn what happened. Putting business fields in the payload would put customer and order
  detail into a channel that has no authorisation, no audit and no delivery guarantee, and
  would tempt a consumer into treating an unacknowledged, undurable message as fact.

``trg_20_`` sorts after the guards installed by 0002, and the trigger is ``AFTER INSERT``, so a
row is announced only once the write boundary has already accepted it.

Revision ID: 0004_domain_event_notifications
Revises: 0003_runtime_readiness_access
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_domain_event_notifications"
down_revision: str | None = "0003_runtime_readiness_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "promisepatch"
TABLE = "domain_events"
CHANNEL = "promisepatch_events"
FUNCTION = "notify_domain_event"
TRIGGER = "trg_20_notify_domain_event"

NOTIFY_DOMAIN_EVENT = f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.{FUNCTION}() RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    -- The sequence number, as text, and nothing else. A listener uses it to know that the
    -- spine has moved; it reads the row itself from the table.
    PERFORM pg_notify('{CHANNEL}', NEW.seq::text);
    RETURN NULL;
END;
$function$;
"""


def upgrade() -> None:
    op.execute(NOTIFY_DOMAIN_EVENT)
    op.execute(
        f'CREATE TRIGGER {TRIGGER} AFTER INSERT ON {SCHEMA}."{TABLE}"'
        f" FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(f'DROP TRIGGER IF EXISTS {TRIGGER} ON {SCHEMA}."{TABLE}"')
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{FUNCTION}()")
