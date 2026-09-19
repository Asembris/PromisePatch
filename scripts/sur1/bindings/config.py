"""Where the three real bindings are, and which of their prerequisites are actually present.

Every address and every credential this harness needs is read here, from the environment, and
nowhere else. A binding that resolved its own endpoint would eventually be the one that resolved
a different endpoint than the preflight checked, and the preflight would be a description of the
run rather than a gate on it.

**The defaults are the local stack's published ports and nothing else.** ``docker-compose.yml``
publishes PostgreSQL, the API, the MCP endpoint and the order system on four high loopback
ports, each overridable by a ``PROMISEPATCH_*_PUBLISHED_PORT`` variable because a high port is
not always an available one. Those same variables are read here, so a machine that had to move a
port moves it once and both the stack and this harness follow. No default here names a host other
than ``127.0.0.1``: a benchmark that silently found a deployed environment would be a benchmark
about a different world than the one it prepared.

**A credential is a name and a boolean, never a value.** :meth:`BindingConfig.as_payload` is
written into a committed run manifest, so it reports *that* a variable was set and never what it
held. :meth:`BindingConfig.missing` returns the names of the ones that were not, which is what
the preflight refuses on.

**Nothing here opens anything.** Reading configuration is not reaching a system; the probes that
do that live on the bindings themselves, and the preflight calls them separately and says so.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

LOOPBACK: Final = "127.0.0.1"
"""The only host any default here names."""

DEFAULT_PORTS: Final[dict[str, int]] = {
    "postgres": 55432,
    "api": 58000,
    "mcp": 58001,
    "order_system": 58100,
}
"""The published ports ``docker-compose.yml`` declares, restated nowhere else in this package."""

PORT_VARIABLES: Final[dict[str, str]] = {
    "postgres": "PROMISEPATCH_POSTGRES_PUBLISHED_PORT",
    "api": "PROMISEPATCH_API_PUBLISHED_PORT",
    "mcp": "PROMISEPATCH_MCP_PUBLISHED_PORT",
    "order_system": "PROMISEPATCH_ORDER_SIMULATOR_PUBLISHED_PORT",
}
"""The compose file's own overrides, read rather than duplicated.

A machine whose reserved port ranges swallowed the defaults sets these for ``docker compose``
already. Reading the same names is what keeps one answer to 'where is the stack' on a host that
had to move one.
"""

REQUIRED_FOR_SCORED: Final = (
    "SUR1_MCP_BEARER_TOKEN",
    "SUR1_WORKSPACE_WORKER",
    "SUR1_WORKSPACE_PASSWORD",
    "SUR1_WORKSPACE_ORIGIN",
    "SUR1_DATABASE_URL",
    "SUR1_AWS_REGION",
)
"""Every variable without which a scored run cannot be driven honestly.

The bearer token and the workspace credential are how arms B and C reach ordinary surfaces; the
workspace origin is the one the API was configured to accept, and without it a worker cannot
sign in and no plan can ever be confirmed; the database URL is how E2 and E3 are read; and the
region is where the one frozen model lives. A run missing any of them is refused before an arm
is constructed rather than voided nine times afterwards.

``SUR1_ORDER_SYSTEM_STORE`` is deliberately absent. E1 is read from the order system's own
``GET /admin/events``, which now publishes each event's committed body, so a scored run needs no
path into the simulator's container and no copy of its store.
"""


def _port(environ: Mapping[str, str], service: str) -> int:
    raw = environ.get(PORT_VARIABLES[service], "").strip()
    if not raw:
        return DEFAULT_PORTS[service]
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_PORTS[service]


@dataclass(frozen=True, slots=True)
class BindingConfig:
    """Everything the three bindings need, resolved once and reported without its secrets."""

    api_base_url: str
    mcp_url: str
    order_system_base_url: str
    workspace_origin: str

    mcp_bearer_token: str = ""
    workspace_worker: str = ""
    workspace_password: str = ""
    database_url: str = ""
    aws_region: str = ""

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> BindingConfig:
        """Read the addresses and the credentials. Opens nothing and contacts nobody."""
        values = os.environ if environ is None else environ
        api = values.get("SUR1_API_BASE_URL") or f"http://{LOOPBACK}:{_port(values, 'api')}"
        mcp = values.get("SUR1_MCP_URL") or f"http://{LOOPBACK}:{_port(values, 'mcp')}/mcp"
        orders = (
            values.get("SUR1_ORDER_SYSTEM_BASE_URL")
            or f"http://{LOOPBACK}:{_port(values, 'order_system')}"
        )
        return cls(
            api_base_url=api.rstrip("/"),
            mcp_url=mcp,
            order_system_base_url=orders.rstrip("/"),
            # No fallback, on purpose. The login endpoint matches ``Origin`` against
            # ``PP_CORS_ORIGINS`` by exact string, and that allowlist names browser origins, so
            # the API's own base URL -- the obvious default -- is one the product answers 403.
            # Defaulting to it made every arms-B-and-C sign-in fail as an unreachable surface
            # rather than as the missing configuration it was. Unset is unset, and
            # ``workspace_origin`` refuses the run.
            workspace_origin=values.get("SUR1_WORKSPACE_ORIGIN", "").strip(),
            mcp_bearer_token=values.get("SUR1_MCP_BEARER_TOKEN", ""),
            workspace_worker=values.get("SUR1_WORKSPACE_WORKER", ""),
            workspace_password=values.get("SUR1_WORKSPACE_PASSWORD", ""),
            database_url=values.get("SUR1_DATABASE_URL", ""),
            aws_region=values.get("SUR1_AWS_REGION") or values.get("AWS_REGION", ""),
        )

    def present(self) -> dict[str, bool]:
        """Which required variables were set. Booleans, so this may be written to a capture."""
        held = {
            "SUR1_MCP_BEARER_TOKEN": bool(self.mcp_bearer_token),
            "SUR1_WORKSPACE_WORKER": bool(self.workspace_worker),
            "SUR1_WORKSPACE_PASSWORD": bool(self.workspace_password),
            "SUR1_WORKSPACE_ORIGIN": bool(self.workspace_origin),
            "SUR1_DATABASE_URL": bool(self.database_url),
            "SUR1_AWS_REGION": bool(self.aws_region),
        }
        return {name: held[name] for name in REQUIRED_FOR_SCORED}

    def missing(self) -> tuple[str, ...]:
        """The names a scored run would be driven without. The preflight refuses on these."""
        return tuple(name for name, held in self.present().items() if not held)

    def as_payload(self) -> dict[str, Any]:
        """Addresses and booleans. No credential value reaches a committed capture."""
        return {
            "api_base_url": self.api_base_url,
            "mcp_url": self.mcp_url,
            "order_system_base_url": self.order_system_base_url,
            "workspace_origin": self.workspace_origin,
            "aws_region": self.aws_region,
            "configured": self.present(),
        }


__all__ = [
    "DEFAULT_PORTS",
    "PORT_VARIABLES",
    "REQUIRED_FOR_SCORED",
    "BindingConfig",
]
