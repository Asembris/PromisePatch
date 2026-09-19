"""Arms B and C: PromisePatch, reached exactly the way a worker and their assistant reach it.

Two ordinary surfaces and nothing else.

**The MCP endpoint**, over Streamable HTTP at the address the stack publishes, with a bearer
credential, through the official client SDK. It is the surface a third-party MCP client would be
pointed at, and the five tools on it are the whole frozen intent surface. Nothing here imports
:mod:`promisepatch.domain` or :mod:`promisepatch.db`, opens a transaction, or reads a row: the
harness reaches a case the way the MCP process itself does, by asking another process.

**The workspace**, where a worker signs in with their own credential and approves a plan. It is
here because of ADR-0018 and it is not a convenience. A confirmation *spends* a durable human
approval it cannot write, so a benchmark arm that only held a service credential could never get
past a plan -- not because the harness is missing a shortcut, but because the product refuses one.
The arm therefore does what a worker does: approves on the surface this system authenticated them
on, and then lets the conversation carry that approval out. Both halves are ordinary product
endpoints and neither is opened for this measurement.

**A session per call, because the server has none.** The MCP server is stateless by design and
issues no session id, so a fresh transport per call is what a compliant client does rather than a
shortcut. Continuity comes from the durable case, exactly as the server's own instructions say.

**Waiting is not an action.** PromisePatch does its work in a durable worker, so a surface that
returned the instant ``report`` was accepted would be reporting that nothing had happened yet.
This binding polls ``status`` until the case is asking for something or has stopped moving.
Those polls are the transport waiting for the product; they are **not** frozen actions and are
deliberately not charged against the tool-call ceiling, which counts the eleven actions the
contract froze. What bounds them is the attempt's wall-clock ceiling, which the arm's own budget
enforces, and the binding's deadline, which is the smaller of the two.

**Nothing here has been pointed at a ``SUR-1`` scenario.**
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import uuid4

from scripts.sur1.bindings import REAL, Probe

MCP_TOOLS: Final = ("report", "clarify", "confirm", "status", "withdraw")
"""The whole frozen intent surface. A binding that needed a sixth would be describing a
different product."""

CSRF_HEADER: Final = "X-CSRF-Token"
SESSION_COOKIE: Final = "pp_session"

POLL_SECONDS: Final = 1.0
"""How long between two readings of a case that is still moving."""

QUIET_READINGS: Final = 3
"""How many identical readings mean the case has stopped rather than paused.

Three rather than one, because a durable worker between two steps briefly looks exactly like a
worker that has finished, and reading the first of those as the end of the attempt would score an
arm on a case that had not got there yet.
"""


class SurfaceError(RuntimeError):
    """An ordinary product surface refused, or could not be reached.

    Never softened into a plausible answer. A conversation that filled this silence with a guess
    is the failure the product's own semantic boundary exists to prevent, and a benchmark that
    did it would be scoring the guess.
    """


# ----------------------------------------------------------------------------- the MCP client


@dataclass(slots=True)
class McpToolClient:
    """The five tools, over Streamable HTTP, through the official SDK client.

    Synchronous on the outside because the harness is, and asynchronous underneath because the
    SDK is. Each call runs one session on its own event loop, which is what a stateless server
    expects and what makes a call here independent of every other.
    """

    url: str
    bearer_token: str
    timeout_seconds: float = 30.0
    calls: list[str] = field(default_factory=list)
    binding_kind: str = REAL

    def identity(self) -> Mapping[str, Any]:
        return {"surface": "mcp", "url": self.url, "tools": list(MCP_TOOLS)}

    def probe(self) -> Probe:
        """List the tools. A read, and the one that proves the credential and the protocol.

        Listing is deliberately the probe rather than a call to ``status``: it opens nothing,
        changes nothing and reaches no case, and a server that answers it has completed the
        handshake, accepted the bearer credential and published a tool surface.
        """
        try:
            names = self.list_tools()
        except Exception as failure:
            return Probe("PROMISEPATCH", False, f"{type(failure).__name__}: {failure}")
        missing = sorted(set(MCP_TOOLS) - set(names))
        if missing:
            return Probe("PROMISEPATCH", False, f"the server publishes no {missing}")
        return Probe("PROMISEPATCH", True, self.url)

    def list_tools(self) -> tuple[str, ...]:
        return asyncio.run(self._list_tools())

    def call(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """One tool call, and its structured result. The envelope is read, never interpreted."""
        if name not in MCP_TOOLS:
            raise SurfaceError(f"{name} is not one of the five tools this product publishes")
        self.calls.append(name)
        return asyncio.run(self._call(name, dict(arguments)))

    # -- the async half, which nothing outside this class touches -----------------------------

    def _http_client(self) -> Any:
        """The HTTP client the SDK transport runs on, carrying the bearer credential.

        Built through the SDK's own factory so the transport keeps the timeouts its protocol
        expects, and carrying the bearer credential, which is this harness's configuration: a
        transport that resolved a credential for itself would be a second place a run's identity
        is decided. The per-call read timeout is passed to the call, where it belongs.
        """
        from mcp.shared._httpx_utils import create_mcp_http_client

        return create_mcp_http_client(headers={"Authorization": f"Bearer {self.bearer_token}"})

    async def _list_tools(self) -> tuple[str, ...]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with (
            self._http_client() as http,
            streamable_http_client(self.url, http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            listing = await session.list_tools()
            return tuple(tool.name for tool in listing.tools)

    async def _call(self, name: str, arguments: dict[str, Any]) -> Mapping[str, Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with (
            self._http_client() as http,
            streamable_http_client(self.url, http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                name, arguments, read_timeout_seconds=self.timeout_seconds
            )
        if result.is_error:
            raise SurfaceError(f"{name} was refused: {_text_of(result)}")
        structured = result.structured_content
        if isinstance(structured, Mapping):
            return dict(structured)
        text = _text_of(result)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as failure:
            raise SurfaceError(f"{name} answered something this client cannot read") from failure
        if not isinstance(parsed, Mapping):
            raise SurfaceError(f"{name} answered a {type(parsed).__name__} rather than a result")
        return dict(parsed)


def _text_of(result: Any) -> str:
    blocks = getattr(result, "content", ()) or ()
    return "\n".join(str(getattr(block, "text", "")) for block in blocks)


# ------------------------------------------------------------------------- the workspace


@dataclass(slots=True)
class WorkspaceClient:
    """A worker's own signed-in session, for the one thing a service credential may not do.

    It holds a session cookie and a CSRF token, obtained by signing in with a worker's
    credential, and it uses them for exactly one endpoint: ``POST /api/conversation/approve``,
    which records that this person approved this plan and carries nothing out.

    The credential is the harness's configuration and is never written into a capture.
    """

    base_url: str
    origin: str
    username: str
    password: str
    timeout_seconds: float = 15.0
    _cookies: dict[str, str] = field(default_factory=dict)
    _csrf: str = ""
    binding_kind: str = REAL

    def identity(self) -> Mapping[str, Any]:
        return {"surface": "workspace", "base_url": self.base_url, "origin": self.origin}

    def probe(self) -> Probe:
        """Sign in. That is the fact the preflight needs, and it writes nothing but a session."""
        try:
            self.sign_in()
        except Exception as failure:
            return Probe("WORKSPACE", False, f"{type(failure).__name__}: {failure}")
        return Probe("WORKSPACE", True, f"{self.username} at {self.base_url}")

    def sign_in(self) -> None:
        import httpx2

        answer = httpx2.post(
            f"{self.base_url}/api/auth/login",
            json={"username": self.username, "password": self.password},
            headers={"Origin": self.origin},
            timeout=self.timeout_seconds,
        )
        if answer.status_code != 200:
            raise SurfaceError(f"the workspace refused this credential: {answer.status_code}")
        self._cookies = dict(answer.cookies.items())
        self._csrf = self._cookies.get("pp_csrf", "")
        if SESSION_COOKIE not in self._cookies or not self._csrf:
            raise SurfaceError("the workspace issued no session this client can carry")

    def approve(self, *, case_id: str, plan_id: str) -> Mapping[str, Any]:
        """Record this worker's approval of this plan. ``201``, and nothing has moved.

        This is the durable human approval ADR-0018 says a confirmation spends and cannot
        create. Recording it twice records it once, so a retry is safe and is not a second
        authority for one agreement.
        """
        import httpx2

        if not self._csrf:
            self.sign_in()
        answer = httpx2.post(
            f"{self.base_url}/api/conversation/approve",
            json={"case_id": case_id, "plan_id": plan_id},
            headers={"Origin": self.origin, CSRF_HEADER: self._csrf},
            cookies=self._cookies,
            timeout=self.timeout_seconds,
        )
        if answer.status_code not in (200, 201):
            raise SurfaceError(f"the workspace refused the approval: {answer.status_code}")
        body: Mapping[str, Any] = answer.json()
        return body


# --------------------------------------------------------------------------- the worker surface


@dataclass(slots=True)
class LiveWorkerSurface:
    """The :class:`~scripts.sur1.arms.WorkerSurface` arms B and C are driven through.

    The vocabulary is the worker's, not the harness's: say what happened, answer the one thing
    you were asked, approve the plan that was read back to you, read the status. What this class
    adds is the waiting, because the product is durable and a surface that answered before the
    work ran would be answering about a case that had not moved.
    """

    tools: McpToolClient
    workspace: WorkspaceClient
    deadline_seconds: float = 240.0
    sleep: Any = None
    case_id: str = ""
    case_ids: list[str] = field(default_factory=list)
    binding_kind: str = REAL

    def identity(self) -> Mapping[str, Any]:
        return {
            "surface": "promisepatch",
            "mcp": self.tools.identity(),
            "workspace": self.workspace.identity(),
        }

    def probe(self) -> Probe:
        for probe in (self.tools.probe(), self.workspace.probe()):
            if not probe.reachable:
                return Probe("PROMISEPATCH", False, f"{probe.source}: {probe.detail}")
        return Probe("PROMISEPATCH", True, self.tools.url)

    def forget(self) -> None:
        """Between scenarios. The next attempt opens its own case and inherits none."""
        self.case_id = ""
        self.case_ids.clear()

    # -- the four verbs ------------------------------------------------------------------------

    def report_exception(self, utterance: str) -> Mapping[str, Any]:
        result = self.tools.call(
            "report", {"text": utterance, "client_request_id": f"sur1-{uuid4()}"}
        )
        self.case_id = str(result.get("case_id", ""))
        if not self.case_id:
            raise SurfaceError("report opened no case this client can name")
        self.case_ids.append(self.case_id)
        return self._settled()

    def answer_clarification(self, answer: str) -> Mapping[str, Any]:
        self.tools.call(
            "clarify",
            {"case_id": self.case_id, "text": answer, "client_request_id": f"sur1-{uuid4()}"},
        )
        return self._settled()

    def confirm_plan(self, plan_id: str) -> Mapping[str, Any]:
        """Approve on the worker's own surface, then ask the conversation to carry it out.

        The order is the product's own and is not a detail. ``approve`` is a person agreeing;
        ``confirm`` spends that agreement. Reversing them, or skipping the first, is refused by
        the intent API with ``HUMAN_APPROVAL_REQUIRED`` -- which is the system working.
        """
        self.workspace.approve(case_id=self.case_id, plan_id=plan_id)
        self.tools.call(
            "confirm",
            {
                "case_id": self.case_id,
                "plan_id": plan_id,
                "client_request_id": f"sur1-{uuid4()}",
            },
        )
        return self._settled()

    def status(self) -> Mapping[str, Any]:
        """The status projection, as the product renders it for a worker. E4 for arms B and C."""
        return self.tools.call("status", {"case_id": self.case_id})

    # -- the waiting ---------------------------------------------------------------------------

    def _settled(self) -> Mapping[str, Any]:
        """Read the case until it asks for something or stops changing.

        Three readings of the same thing, rather than one, because a durable worker between two
        steps looks exactly like one that has finished. A deadline ends the wait either way and
        the last reading is returned: a case that is still moving when the clock runs out is
        reported as it stands rather than as whatever it might have become.
        """
        import time

        sleep = self.sleep or time.sleep
        clock = time.monotonic
        until = clock() + self.deadline_seconds
        seen = ""
        quiet = 0
        reading = self.status()
        while True:
            need = self._needs(reading)
            if need is not None:
                return need
            fingerprint = json.dumps(reading, sort_keys=True, default=str)
            quiet = quiet + 1 if fingerprint == seen else 0
            seen = fingerprint
            if quiet >= QUIET_READINGS or clock() >= until:
                return {"needs": None, "status": reading}
            sleep(POLL_SECONDS)
            reading = self.status()

    @staticmethod
    def _needs(reading: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """What the case is waiting for, in the two words the arm's loop knows.

        Read off the status projection's own fields rather than inferred from prose: a question
        is a ``question`` object, and a plan waiting for a yes is ``awaiting_confirmation`` with
        the ``plan_id`` the engine rendered.
        """
        question = reading.get("question")
        if isinstance(question, Mapping):
            return {
                "needs": "clarification",
                "question": question,
                "status": reading,
            }
        if reading.get("awaiting_confirmation") and reading.get("plan_id"):
            return {
                "needs": "confirmation",
                "plan_id": str(reading["plan_id"]),
                "status": reading,
            }
        return None


def live_worker_surface(
    *,
    mcp_url: str,
    bearer_token: str,
    api_base_url: str,
    origin: str,
    username: str,
    password: str,
) -> LiveWorkerSurface:
    """The surface arms B and C share. One object, because arm C composes arm B."""
    return LiveWorkerSurface(
        tools=McpToolClient(url=mcp_url, bearer_token=bearer_token),
        workspace=WorkspaceClient(
            base_url=api_base_url, origin=origin, username=username, password=password
        ),
    )


def tool_names(surface: LiveWorkerSurface) -> Sequence[str]:
    """Every MCP tool this surface has called, in order. Read by a test, never by an arm."""
    return tuple(surface.tools.calls)


__all__ = [
    "MCP_TOOLS",
    "QUIET_READINGS",
    "LiveWorkerSurface",
    "McpToolClient",
    "SurfaceError",
    "WorkspaceClient",
    "live_worker_surface",
    "tool_names",
]
