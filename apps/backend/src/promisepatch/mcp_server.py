"""The ``mcp`` entrypoint: an ASGI application factory for the Streamable HTTP MCP server.

Its own process, not a route on the API. Two reasons, and neither is tidiness. It is a
*separately reachable endpoint* -- the thing a real Alexa+ registration or any third-party MCP
client would be pointed at -- and it is the process that must not be able to touch a database:
running it inside the API would put the domain on its import path and make the boundary a
convention again.

A factory rather than a module-level ``app``. Building this server requires an inbound
credential and an engine address, so a module-level instance would make *importing* this module
an assertion about the environment -- and the import has to succeed on a machine that has
neither, or nothing could type-check or test it. ``uvicorn --factory`` is what runs it.
"""

from __future__ import annotations

from starlette.applications import Starlette

from promisepatch import __version__
from promisepatch.config import Settings, get_settings
from promisepatch.mcp import MCP_PATH, PROTOCOL_REVISION, build_app
from promisepatch.observability import configure_logging, get_logger

logger = get_logger(__name__)

APP_FACTORY = "promisepatch.mcp_server:create_app"
"""What uvicorn is pointed at, named once so the CLI and the container agree."""


def create_app(settings: Settings | None = None) -> Starlette:
    """Build the MCP application for the given settings.

    Refuses to build without an inbound credential and without an engine to reach. Both are
    deliberate startup failures rather than runtime ones: a server that came up with no bearer
    token would accept a tool call from whoever found the port, and one with no intent API
    would answer every call ``ENGINE_UNAVAILABLE`` while looking healthy.
    """
    resolved = settings or get_settings()
    configure_logging(resolved)
    resolved.require_mcp_bearer_token()
    resolved.require_mcp_intent_api_base_url()
    logger.info(
        "mcp.start",
        env=str(resolved.env),
        version=__version__,
        protocol=PROTOCOL_REVISION,
        path=MCP_PATH,
        allowed_origins=list(resolved.mcp_allowed_origin_list),
        allowed_hosts=list(resolved.mcp_allowed_host_list),
    )
    return build_app(resolved)
