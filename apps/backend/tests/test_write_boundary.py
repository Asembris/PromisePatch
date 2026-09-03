"""The write boundary as a property of the declared schema, with no database in sight.

The database tests prove the boundary is installed. These prove it is *complete*: that no
mapped table sits outside it, that no table is claimed by two sets that mean opposite things,
and that a governed write cannot be attributed to an actor or an authority the ledger has no
vocabulary for. A table added later without a decision fails here, at import speed, rather than
in whichever integration run first happens to touch it.
"""

from __future__ import annotations

import pytest

from promisepatch.db import models as _registry  # noqa: F401  populates the metadata
from promisepatch.db.base import metadata
from promisepatch.db.boundary import (
    APPEND_ONLY_PRIVILEGES,
    APPEND_ONLY_TABLES,
    AUDIT_MARKER,
    GOVERNED_TABLES,
    MIGRATION_ONLY_TABLES,
    READ_WRITE_PRIVILEGES,
    READINESS_PRIVILEGES,
    TRUNCATE_PROTECTED_TABLES,
    UNGOVERNED_TABLES,
    all_tables,
    runtime_privileges,
)
from promisepatch.db.types import ACTOR_KINDS, AUTHORITIES
from promisepatch.db.uow import Actor

MAPPED = frozenset(table.name for table in metadata.tables.values())


def test_every_mapped_table_is_on_one_side_of_the_boundary() -> None:
    """A new table is a decision: governed, or explicitly not. Silence is not an answer."""
    assert all_tables() == MAPPED


def test_no_table_is_both_governed_and_ungoverned() -> None:
    assert not GOVERNED_TABLES & UNGOVERNED_TABLES


def test_every_append_only_table_is_a_real_table() -> None:
    assert APPEND_ONLY_TABLES <= MAPPED


def test_the_ledgers_that_may_never_be_emptied_are_append_only() -> None:
    """Truncation protection is a stronger claim, so it may only apply where the weaker holds."""
    assert TRUNCATE_PROTECTED_TABLES <= APPEND_ONLY_TABLES


def test_the_audit_ledger_and_the_event_spine_are_outside_the_governed_set() -> None:
    """Requiring an audit event to write the audit ledger would be circular, not stricter."""
    assert {"audit_events", "domain_events"} <= UNGOVERNED_TABLES


def test_the_migration_ledger_is_not_part_of_the_application_schema() -> None:
    assert not MIGRATION_ONLY_TABLES & MAPPED


def test_an_append_only_table_is_granted_nothing_that_could_rewrite_it() -> None:
    for table in sorted(APPEND_ONLY_TABLES):
        assert runtime_privileges(table) == APPEND_ONLY_PRIVILEGES
        assert "UPDATE" not in runtime_privileges(table)
        assert "DELETE" not in runtime_privileges(table)


def test_a_mutable_table_is_granted_the_four_ordinary_privileges() -> None:
    for table in sorted(MAPPED - APPEND_ONLY_TABLES):
        assert runtime_privileges(table) == READ_WRITE_PRIVILEGES


def test_no_table_is_ever_granted_truncate() -> None:
    """Emptying a table is never something the running application needs to do."""
    for table in sorted(MAPPED | MIGRATION_ONLY_TABLES):
        assert "TRUNCATE" not in runtime_privileges(table)


def test_the_migration_ledger_is_readable_and_nothing_more() -> None:
    """Readiness has to compare revisions over the connection that serves requests.

    ``0003_runtime_readiness_access`` grants that read and only that read: the application can
    see which migration ran and holds nothing that could claim, rewrite or erase one, so it
    cannot misreport its own schema.
    """
    assert runtime_privileges("alembic_version") == READINESS_PRIVILEGES
    assert runtime_privileges("alembic_version") == frozenset({"SELECT"})


def test_no_migration_table_is_writable_by_the_runtime_role() -> None:
    for table in sorted(MIGRATION_ONLY_TABLES):
        assert not runtime_privileges(table) & {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}


def test_the_marker_is_namespaced_to_this_application() -> None:
    """A bare setting name could collide with anything else sharing the session."""
    assert AUDIT_MARKER.startswith("promisepatch.")


def test_an_actor_must_have_a_kind_the_ledger_can_record() -> None:
    for kind in ACTOR_KINDS:
        assert Actor(kind=kind, id="someone").kind == kind
    with pytest.raises(ValueError, match="unknown actor kind"):
        Actor(kind="ROBOT")


def test_the_authorities_include_the_honest_absence_of_one() -> None:
    """A physical fact is authoritative without anyone approving it, and says so."""
    assert "NONE" in AUTHORITIES
