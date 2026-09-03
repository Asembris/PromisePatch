"""The demo fixture: which dataset is loaded, how it becomes rows, and how it is reset."""

from promisepatch.fixtures.demo import FIXTURE_NAME, STAFF, build_snapshot
from promisepatch.fixtures.projection import StaffSeed, TableRows, digest, project, project_staff
from promisepatch.fixtures.reset import (
    FixtureResetNotAllowedError,
    ResetOutcome,
    ensure_reset_allowed,
    reset_demo_state,
)

__all__ = [
    "FIXTURE_NAME",
    "STAFF",
    "FixtureResetNotAllowedError",
    "ResetOutcome",
    "StaffSeed",
    "TableRows",
    "build_snapshot",
    "digest",
    "ensure_reset_allowed",
    "project",
    "project_staff",
    "reset_demo_state",
]
