"""The MCP surface: tool definitions, the result envelope, and inbound authentication.

Deliberately isolated. Nothing in this package may import :mod:`promisepatch.domain`,
:mod:`promisepatch.db` or :mod:`promisepatch.api` -- an import-linter contract enforces it --
so a tool has no way to reach a transaction, a row or a domain service except by making an
authenticated HTTP call to the intent API like any other client. The boundary is the point:
MCP is a transport and a delegation, never a second place where authority lives.
"""

from promisepatch.mcp.auth import BearerAuthMiddleware, Principal
from promisepatch.mcp.engine import CaseEngine
from promisepatch.mcp.envelope import Envelope, ToolCode, ToolRefusalError
from promisepatch.mcp.results import (
    ClarifyResult,
    ConfirmResult,
    PromiseResult,
    ReportResult,
    StatusResult,
)
from promisepatch.mcp.server import (
    MCP_PATH,
    PROTOCOL_REVISION,
    build_app,
    build_server,
    command_id_for,
)

__all__ = [
    "MCP_PATH",
    "PROTOCOL_REVISION",
    "BearerAuthMiddleware",
    "CaseEngine",
    "ClarifyResult",
    "ConfirmResult",
    "Envelope",
    "Principal",
    "PromiseResult",
    "ReportResult",
    "StatusResult",
    "ToolCode",
    "ToolRefusalError",
    "build_app",
    "build_server",
    "command_id_for",
]
