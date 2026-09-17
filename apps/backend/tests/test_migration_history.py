"""The migration history, and the one fact about it that runtime code hard-codes.

``promisepatch.db.revision.HEAD_REVISION`` exists because a deployed process has no
``alembic/`` directory to read. That makes it the one place where the schema's identity is
restated rather than derived, so it is pinned here: adding a migration without moving the
constant fails this test instead of a readiness probe in production.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from promisepatch.db.boundary import AUDIT_MARKER
from promisepatch.db.revision import HEAD_REVISION
from promisepatch.db.types import APPROVAL_CHANNELS, WORKER_ROLES

BACKEND = Path(__file__).resolve().parents[1]


def script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(config)


def test_the_expected_head_is_the_head_of_the_history() -> None:
    assert script_directory().get_current_head() == HEAD_REVISION


def test_the_history_is_a_single_unbranched_line() -> None:
    """Two heads would make "at the head" ambiguous, and readiness could not answer it."""
    assert len(script_directory().get_heads()) == 1


def test_the_baseline_migrations_are_still_in_the_history() -> None:
    """The audited boundary is not something a later migration may quietly replace."""
    revisions = {script.revision for script in script_directory().walk_revisions()}
    assert {"0001_baseline", "0002_audit_and_runtime_boundary"} <= revisions


# ------------------------------------------------------ what 0008 restates rather than imports


OBSERVER_MIGRATION = BACKEND / "alembic" / "versions" / "0008_observer_worker_role.py"


def test_the_observer_migration_states_the_audit_marker_the_runtime_sets() -> None:
    """The migration writes a literal; the application derives one. They must be the same name.

    A downgrade removes a principal, and ``workers`` is a governed table, so the delete has to
    carry an audit event exactly as every other governed write does. The setting that binds the
    two is named literally in the migration because a migration cannot import a constant that
    may be renamed under it, and this is the only thing holding the two ends together.
    """
    source = OBSERVER_MIGRATION.read_text(encoding="utf-8")
    assert f'AUDIT_MARKER = "{AUDIT_MARKER}"' in source


def test_the_observer_migration_admits_exactly_the_roles_the_runtime_declares() -> None:
    """The vocabulary the database will accept, against the vocabulary the models declare."""
    source = OBSERVER_MIGRATION.read_text(encoding="utf-8")
    rendered = ", ".join(f'"{role}"' for role in WORKER_ROLES)
    assert f"AFTER = ({rendered})" in source


# ------------------------------------------------------ what 0009 restates rather than imports


APPROVAL_MIGRATION = BACKEND / "alembic" / "versions" / "0009_human_plan_approval.py"


def test_the_approval_migration_admits_exactly_the_channels_the_runtime_declares() -> None:
    """The closed set of channels that may record a human approval, at both ends.

    It is the boundary itself: the database admits a channel only if it is in this tuple, and
    there is no member here for a service surface. A migration that admitted one would let the
    MCP path write an approval whatever the application code said.
    """
    source = APPROVAL_MIGRATION.read_text(encoding="utf-8")
    rendered = ", ".join(f'"{channel}"' for channel in APPROVAL_CHANNELS)
    assert f"CHANNELS = ({rendered})" in source
