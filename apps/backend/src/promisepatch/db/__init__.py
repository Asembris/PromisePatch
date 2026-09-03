"""Persistence: the declarative schema, and the connections that reach it.

Every authoritative fact PromisePatch holds lives in one PostgreSQL database, so a state
transition, the events it emits and the audit row that authorises it can commit or fail
together. Graph edges are derived from foreign keys rather than stored in a generic edge
table, which keeps the graph transactional with the state it describes (ADR-0002).
"""

# Importing the registry here is what makes ``metadata`` complete for every consumer --
# Alembic, the schema tests, and anything that reflects the schema. Without it, what the
# metadata contains would depend on which modules happened to be imported first.
from promisepatch.db import models as models
from promisepatch.db.base import Base, metadata
from promisepatch.db.revision import HEAD_REVISION
from promisepatch.db.session import build_engine
from promisepatch.db.uow import Actor, GovernedWrite, UnitOfWork

__all__ = [
    "HEAD_REVISION",
    "Actor",
    "Base",
    "GovernedWrite",
    "UnitOfWork",
    "build_engine",
    "metadata",
]
