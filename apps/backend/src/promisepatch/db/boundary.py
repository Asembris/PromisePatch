"""The write boundary, named once so the database, the runtime and the tests agree.

Three sets decide what PostgreSQL will accept, and they are declared here rather than being
implied by whichever migration happened to run last:

* **Governed tables** hold domain state. Nothing may insert, update, delete or truncate a row
  in one of them unless the same transaction has already written the audit event that
  authorises it. The check is a trigger, so it holds for psql, a migration, a future service
  and a mistake equally.
* **Append-only tables** are ledgers and authored history. They refuse UPDATE and DELETE
  outright — including inside a perfectly valid governed transaction, because immutability is
  not something an authorisation can buy.
* **Ungoverned tables** are the audit ledger itself, the event spine, and the machinery of the
  durable engine: sessions, inbox, outbox, timers, steps. Requiring an audit event to store an
  inbound webhook would mean auditing the arrival of a message before anyone has decided
  anything about it, and requiring one to write ``audit_events`` is circular.

``GOVERNED_TABLES | UNGOVERNED_TABLES`` is asserted to be exactly the mapped schema, so a table
added later cannot quietly land outside the boundary.
"""

from __future__ import annotations

import hashlib


def advisory_lock_key(name: str) -> int:
    """A PostgreSQL advisory-lock key derived from an operation's name.

    The first eight bytes of the SHA-256 digest, read as a signed big-endian integer, which is
    the range ``pg_advisory_xact_lock(bigint)`` accepts. Deriving rather than choosing means
    two operations cannot silently share a key, and a key cannot collide with one picked by
    another application sharing the database.
    """
    return int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big", signed=True)


AUDIT_MARKER = "promisepatch.audit_event_id"
"""Transaction-local setting naming the audit event that authorises the current write."""

EVENT_ORDER_LOCK_NAME = "promisepatch.domain_event_order"
EVENT_ORDER_LOCK_KEY = advisory_lock_key(EVENT_ORDER_LOCK_NAME)
"""The advisory lock a transaction holds from its first domain event until it ends.

Held by a ``BEFORE INSERT`` trigger on ``domain_events``, which draws ``seq`` only once it has
the lock. That is what makes the spine commit-ordered: for two committed events,
``seq(e1) < seq(e2)`` implies ``commit(e1) < commit(e2)``, so a subscriber whose cursor only
moves forward cannot step over a row that had not committed yet when it read.

**It is the last lock an event-producing transaction may take.** A transaction that appended an
event and then waited on an unrelated row would hold the whole spine while a second transaction,
holding that row, queued behind it. Every writer takes locks in this order instead:

    case_steps row → cases row → owned timer / inbox / outbox rows → this lock → COMMIT

Derived from the name rather than chosen, so it cannot collide by accident with another
application sharing the database. Migration 0005 writes the resulting integer out literally; a
test asserts the two still agree."""

RUNTIME_ROLE = "promisepatch_app"
"""The least-privileged login the application uses. It owns nothing and migrates nothing."""

ASSERT_GOVERNED_FUNCTION = "assert_governed_write"
REJECT_MUTATION_FUNCTION = "reject_mutation"
NOTIFY_EVENT_FUNCTION = "notify_domain_event"
COMMIT_ORDER_FUNCTION = "assign_commit_ordered_seq"

GOVERNED_WRITE_TRIGGER = "trg_10_governed_write"
GOVERNED_TRUNCATE_TRIGGER = "trg_11_governed_truncate"
APPEND_ONLY_TRIGGER = "trg_00_append_only"
NO_TRUNCATE_TRIGGER = "trg_01_no_truncate"
COMMIT_ORDER_TRIGGER = "trg_05_commit_ordered_seq"
NOTIFY_EVENT_TRIGGER = "trg_20_notify_domain_event"
"""Numeric prefixes are load-bearing.

PostgreSQL fires triggers of the same timing in name order, so ``trg_00_append_only`` runs
before ``trg_10_governed_write``: an update to an append-only table fails as immutable rather
than as unaudited, whether or not the transaction was authorised.

``trg_05_commit_ordered_seq`` is ``BEFORE INSERT FOR EACH ROW`` on ``domain_events``: the last
moment at which ``seq`` can still be decided, and therefore the only place the commit order can
be established. ``trg_20_notify_domain_event`` sorts last and fires ``AFTER INSERT``, so the
spine announces a row only once the guards have accepted it -- and announces the sequence
number the earlier trigger settled on.
"""

EVENT_CHANNEL = "promisepatch_events"
"""The ``LISTEN``/``NOTIFY`` channel a committed domain event announces itself on.

A wake-up hint, never a delivery mechanism. The payload is one sequence number, the durable row
is the state, and a listener that missed a notification recovers by reading the ledger.
"""

GOVERNED_TABLES: frozenset[str] = frozenset(
    {
        "approval_decisions",
        "approval_requests",
        "case_reports",
        "cases",
        "commitment_lines",
        "customers",
        "equipment_alternatives",
        "equipment_outages",
        "exception_clarifications",
        "exception_facts",
        "exceptions",
        "inbound_replies",
        "inventory_ledger",
        "order_constraints",
        "order_line_mappings",
        "order_lines",
        "orders",
        "plan_approvals",
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
    }
)

UNGOVERNED_TABLES: frozenset[str] = frozenset(
    {
        "audit_events",
        "case_steps",
        "conversations",
        "domain_events",
        "fixture_state",
        "inbox_events",
        "outbox_messages",
        "sessions",
        "timers",
    }
)

APPEND_ONLY_TABLES: frozenset[str] = frozenset(
    {
        "approval_decisions",
        "audit_events",
        "case_reports",
        "domain_events",
        "exception_facts",
        "inventory_ledger",
        "plan_approvals",
        "recipe_version_equipment",
        "recipe_version_lines",
        "recipe_versions",
    }
)

TRUNCATE_PROTECTED_TABLES: frozenset[str] = frozenset({"audit_events", "domain_events"})
"""Ledgers no authorisation can empty. Every other table's TRUNCATE is merely governed."""

MIGRATION_ONLY_TABLES: frozenset[str] = frozenset({"alembic_version"})
"""Schema bookkeeping, written only by the migration path.

The runtime role holds no privilege here that could change what it says. It holds exactly one
that lets it read what it says, for the reason set out on :data:`READINESS_READABLE_TABLES`.
"""

READINESS_READABLE_TABLES: frozenset[str] = frozenset({"alembic_version"})
"""Migration metadata the runtime role may read, and only read.

``/readyz`` compares the revision the database is at against the revision this code was built
for, and the comparison is worthless unless it is made over the connection that actually
serves requests: a probe authenticating as the migration user would be reporting on a
connection nobody uses. So the runtime role is granted ``SELECT`` on ``alembic_version`` and
nothing further -- it can see which migration ran, and it cannot claim, rewrite or erase one.
"""

READINESS_PRIVILEGES: frozenset[str] = frozenset({"SELECT"})
"""Read, and no more. Anything else here would let the application lie about its own schema."""

RUNTIME_SEQUENCES: frozenset[str] = frozenset(
    {
        "audit_events_seq_seq",
        "domain_events_seq_seq",
        "inventory_ledger_seq_seq",
    }
)
"""Sequences the runtime role may draw from: ``USAGE`` only, never ``UPDATE`` (``setval``)."""

SUPABASE_API_ROLES: tuple[str, ...] = ("anon", "authenticated", "service_role")
"""The roles a managed host exposes through its automatic REST layer. None may reach us."""

APPEND_ONLY_PRIVILEGES: frozenset[str] = frozenset({"SELECT", "INSERT"})
READ_WRITE_PRIVILEGES: frozenset[str] = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})


def all_tables() -> frozenset[str]:
    """Every table the boundary has an opinion about."""
    return GOVERNED_TABLES | UNGOVERNED_TABLES


def resettable_tables() -> frozenset[str]:
    """Every table a fixture reset may empty: the whole schema except the ledgers of record.

    Derived rather than listed, so a table added later is reset by default and only a
    deliberate entry in :data:`TRUNCATE_PROTECTED_TABLES` keeps it. Getting that wrong in the
    safe direction leaves stale demo rows behind; getting it wrong the other way would delete
    history, which is why the exclusion is the thing written down.
    """
    return all_tables() - TRUNCATE_PROTECTED_TABLES


def runtime_privileges(table: str) -> frozenset[str]:
    """Exactly what the runtime role may do to ``table``.

    An append-only ledger is granted ``INSERT`` and nothing that could rewrite it, so the
    immutability trigger is a second line rather than the only one. Migration bookkeeping is
    readable where readiness needs it and otherwise out of reach entirely.
    """
    if table in READINESS_READABLE_TABLES:
        return READINESS_PRIVILEGES
    if table in MIGRATION_ONLY_TABLES:
        return frozenset()
    if table in APPEND_ONLY_TABLES:
        return APPEND_ONLY_PRIVILEGES
    return READ_WRITE_PRIVILEGES
