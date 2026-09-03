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

from promisepatch.db.revision import HEAD_REVISION

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
