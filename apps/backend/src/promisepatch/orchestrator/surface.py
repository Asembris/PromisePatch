"""How the loop reaches a tool: as an ordinary MCP client, over the real protocol.

The orchestrator is not part of the server. It holds no case, no row and no authority, and the
only way it can affect anything is by calling a tool over Streamable HTTP with a bearer
credential, exactly as a third-party client would. That is what makes the authority argument
survive the arrival of a model: everything the loop can do is something an unrelated client
could already do, and every rule about who may do what still runs on the far side.

**Every failure becomes an outcome, never an exception.** A refused tool call, an unreachable
server, a response this client cannot read -- all of them arrive at the loop as a
:class:`ToolOutcome` carrying one of the frozen :class:`~promisepatch.mcp.envelope.ToolCode`
values. That is the P4.9 lesson applied to a new boundary: a conversation whose caller catches
two kinds of failure must not be handed a third, and an untyped exception escaping here would
end a turn somewhere that has no sentence to say about it.

**Nothing is retried.** A refusal is an answer. The loop reads the code, says the deterministic
sentence for it, and gives the worker back their turn -- rather than presenting the same call
again until something works, which is how a conversational layer quietly becomes an agent
looking for a way around a rule.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from promisepatch.mcp.envelope import ToolCode
from promisepatch.observability import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """What one tool call produced: a structured body, or a code saying why there is none.

    Exactly one of ``body`` and ``refusal`` is set. There is no third state and no partial
    one -- a call that returned something unreadable is a refusal with
    ``ENGINE_UNAVAILABLE``, because a body this client could not parse is not evidence of
    anything that happened.
    """

    tool: str
    body: Mapping[str, Any] | None = None
    refusal: ToolCode | None = None

    @property
    def ok(self) -> bool:
        return self.body is not None

    def speech(self) -> str | None:
        """The sentence the server rendered for this call, if it rendered one.

        Read out of the body rather than composed here. Every tool that has something to say
        says it in ``speech``, deterministically, and this returns that string unchanged --
        the loop delivers it, and there is no branch anywhere that rewrites it.
        """
        if self.body is None:
            return None
        value = self.body.get("speech")
        return value if isinstance(value, str) and value else None


class ToolSurface(Protocol):
    """Somewhere the four frozen tools can be called. The whole interface the loop needs.

    A protocol rather than a class, so the loop is written against *a tool surface* and the
    tests that assert its behaviour can drive one that answers from a script. The one that
    matters is :class:`McpToolSurface`, and the canonical conversation is proved through it
    over a real socket -- a scripted surface proves the loop's rules, not the protocol.
    """

    async def call(self, tool: str, arguments: Mapping[str, str]) -> ToolOutcome:
        """Call one tool and return what happened. Never raises for a refusal or an outage."""
        ...


class McpToolSurface:
    """One MCP client session, held for the length of a conversation.

    The server is stateless and issues no session id, so this holds a connection rather than a
    session in the protocol's sense: continuity is the durable case's, and reconnecting costs
    a handshake and loses nothing. Opened by :meth:`connect`, which is the only way to get one
    -- a surface that could be used unopened would be a surface that opened a connection
    somewhere nobody was waiting for it.
    """

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def call(self, tool: str, arguments: Mapping[str, str]) -> ToolOutcome:
        """One tool call, with every way it can go wrong turned into an outcome."""
        try:
            result = await self._session.call_tool(tool, dict(arguments))
        except Exception as error:
            # Deliberately everything. This is a boundary whose contract is that it fails in
            # one shape, and the SDK, the HTTP client and the async runtime underneath it can
            # each raise something of their own. A conversation cannot act on an exception it
            # has no sentence for, and the honest reading of any of them is the same: this
            # call reached nothing, so nothing happened.
            logger.warning("orchestrator.tool.unreachable", tool=tool, error=type(error).__name__)
            return ToolOutcome(tool=tool, refusal=ToolCode.ENGINE_UNAVAILABLE)

        if result.is_error:
            code = refusal_code(_text_of(result))
            logger.info("orchestrator.tool.refused", tool=tool, code=code.value)
            return ToolOutcome(tool=tool, refusal=code)

        body = result.structured_content
        if not isinstance(body, Mapping):
            # A successful call with no structured body is a result this client cannot read.
            # Reported as unavailability rather than as an empty success: a turn that answered
            # from a body it never got would be inventing the case's state.
            logger.error("orchestrator.tool.unshaped", tool=tool)
            return ToolOutcome(tool=tool, refusal=ToolCode.ENGINE_UNAVAILABLE)
        return ToolOutcome(tool=tool, body=body)


@asynccontextmanager
async def connect(url: str, *, token: str, timeout_seconds: float) -> AsyncIterator[McpToolSurface]:
    """Open one authenticated Streamable HTTP session and yield a surface over it.

    The bearer credential is a header on the transport, not a tool argument: the server checks
    it before the JSON-RPC layer sees a byte, so an unauthenticated loop never even discovers
    what tools exist.
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=timeout_seconds) as client,
        streamable_http_client(url, http_client=client) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield McpToolSurface(session)


_CODE_PATTERN = re.compile(r"\b(" + "|".join(sorted(code.value for code in ToolCode)) + r")\b")
"""The frozen refusal codes, as a pattern that finds one wherever it sits in a sentence.

Searched for rather than read off the front, because the text a client receives is not the text
the tool wrote: the SDK reports a tool failure as "Error executing tool confirm: <our text>",
so the code is in the middle. Matching on the enum's own members keeps the two in step -- a
code added to the vocabulary is found here without anybody remembering to -- and word
boundaries keep it from matching a longer word that happens to contain one.
"""


def refusal_code(text: str) -> ToolCode:
    """Read the frozen code out of a tool error's text, or report unavailability.

    The transport carries a tool failure as ``isError`` with text content and no structured
    body, so the code travels in the text rather than in a field. An unrecognised refusal is
    read as ``ENGINE_UNAVAILABLE`` rather than guessed at: a client that mapped an unknown
    refusal onto the nearest familiar one would eventually tell a worker their case had moved
    on when it had not.
    """
    match = _CODE_PATTERN.search(text)
    return ToolCode(match.group(1)) if match else ToolCode.ENGINE_UNAVAILABLE


def _text_of(result: Any) -> str:
    """Every text block of a tool result, joined. Nothing here is shown to a worker."""
    blocks = getattr(result, "content", None) or ()
    return "\n".join(block.text for block in blocks if getattr(block, "type", None) == "text")


__all__ = ["McpToolSurface", "ToolOutcome", "ToolSurface", "connect", "refusal_code"]
