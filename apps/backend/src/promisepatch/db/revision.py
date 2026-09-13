"""The schema revision this code was built against.

Readiness has to compare the migration the database is at with the migration this build
expects, and it has to do so in a deployed process where the ``alembic/`` directory is not on
disk -- a wheel ships the package, not the migration scripts. So the expected head is a
constant here rather than something read back out of Alembic at runtime.

A constant can drift, which is exactly why it does not: a test asserts this value equals the
head of the migration history, so adding a migration without updating this line fails the
suite rather than a deployment.
"""

from __future__ import annotations

from typing import Final

HEAD_REVISION: Final = "0008_observer_worker_role"
"""The Alembic revision a database must be at for this code to be ready to serve."""
