"""The conversational orchestrator: a model chooses among permitted verbs, and nothing else.

This package is a *client* of the MCP surface, not part of it. It holds no case, opens no
transaction, reads no row and presents no credential of its own beyond the bearer token any
third-party client would present. An import-linter contract forbids it the domain, the
database, the API package, SQLAlchemy and the MCP server's own internals -- so everything it
can do is something an unrelated client could already do, and every rule about who may do what
still runs on the far side of the transport.

The model understands; the deterministic protocol authorizes. Here that means: the model reads
one worker turn and names one verb from a list PromisePatch computed for the case's actual
durable state. It supplies no arguments, invents no identity, confirms no plan, and any
sentence it writes is conversational glue that stands in front of a deterministic rendering and
never in place of one.
"""

from promisepatch.orchestrator.loop import Orchestrator, TurnResult
from promisepatch.orchestrator.policy import (
    MAX_TOOL_CALLS_PER_TURN,
    Action,
    Blocked,
    CaseReading,
    Conversation,
    permitted_for,
    phase_of,
    plan,
    reads_as_worker_confirmation,
)
from promisepatch.orchestrator.surface import (
    McpToolSurface,
    ToolOutcome,
    ToolSurface,
    connect,
    refusal_code,
)

__all__ = [
    "MAX_TOOL_CALLS_PER_TURN",
    "Action",
    "Blocked",
    "CaseReading",
    "Conversation",
    "McpToolSurface",
    "Orchestrator",
    "ToolOutcome",
    "ToolSurface",
    "TurnResult",
    "connect",
    "permitted_for",
    "phase_of",
    "plan",
    "reads_as_worker_confirmation",
    "refusal_code",
]
