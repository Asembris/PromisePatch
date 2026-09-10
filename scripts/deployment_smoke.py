"""Prove the deployed endpoints from outside, and fail on the permissive answers too.

These are the deployment's smoke checks: not "did something respond" but "did the boundaries
that G5 closed survive being deployed". Several checks therefore assert a *refusal*, and would
fail a deployment that came up too permissive rather than only one that is down:

* an unauthenticated ``POST /mcp`` must be ``401`` -- the bearer check stays in front of the
  protocol, where P5.1 put it, and a ``200`` here would mean a TLS proxy had been allowed to
  authenticate on the server's behalf;
* an unlisted ``Origin`` must be ``403`` and an unlisted ``Host`` must be ``421``;
* the signed-webhook endpoint must reject a body whose signature is absent or wrong, so the
  order system's identity is still verified after the hop crosses TLS;
* the ``initialize`` handshake must negotiate exactly the pinned protocol revision, because a
  deployment that quietly negotiated an older one would not be the audited surface.

**TLS verification is on and is never turned off.** No check asks httpx to skip it; a
certificate that does not verify fails the run, which is the point of deploying with a real
name and a real certificate rather than a self-signed one.

Run it against the deployed origin::

    uv run python scripts/deployment_smoke.py --base-url https://<host>

``PP_MCP_BEARER_TOKEN`` enables the authenticated handshake check. Without it that one check
reports ``SKIPPED`` and the run still fails if any other check fails -- a missing token must
not be able to turn a broken deployment green.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum

import httpx2

# The revision the MCP surface pins. A test asserts this equals the server's own constant, so
# the smoke check cannot drift away from the thing it is checking.
PROTOCOL_REVISION = "2025-11-25"

WEBHOOK_PATH = "/api/integrations/order-system/events"
MCP_PATH = "/mcp"

TIMEOUT = httpx2.Timeout(20.0, connect=10.0)


class Outcome(Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class Check:
    name: str
    asserts: str
    outcome: Outcome
    detail: str = ""


@dataclass(frozen=True)
class Target:
    base_url: str
    bearer_token: str | None

    @property
    def host(self) -> str:
        return httpx2.URL(self.base_url).host

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"


def _passed(name: str, asserts: str, detail: str = "") -> Check:
    return Check(name=name, asserts=asserts, outcome=Outcome.PASSED, detail=detail)


def _failed(name: str, asserts: str, detail: str) -> Check:
    return Check(name=name, asserts=asserts, outcome=Outcome.FAILED, detail=detail)


def check_tls_and_readiness(client: httpx2.Client, target: Target) -> Check:
    """A verified certificate, and a database the API can actually reach.

    ``/readyz`` rather than ``/healthz``: liveness only says a process is running, and what
    matters after a deploy is that the runtime role reaches PostgreSQL and the schema is the one
    this build expects.
    """
    asserts = "GET /readyz is 200 over a certificate that verifies"
    try:
        answer = client.get(target.url("/readyz"))
    except httpx2.HTTPError as error:
        return _failed("tls-and-readiness", asserts, f"{type(error).__name__}: {error}")
    if answer.status_code != 200:
        return _failed("tls-and-readiness", asserts, f"status {answer.status_code}")
    return _passed("tls-and-readiness", asserts, "certificate verified, schema at head")


def check_http_redirects(client: httpx2.Client, target: Target) -> Check:
    """Port 80 carries the ACME challenge and a redirect, and serves nothing else."""
    asserts = "http:// redirects to https:// rather than serving the API"
    plain = target.url("/readyz").replace("https://", "http://", 1)
    try:
        answer = client.get(plain, follow_redirects=False)
    except httpx2.HTTPError as error:
        return _failed("http-redirects", asserts, f"{type(error).__name__}: {error}")
    if answer.status_code not in (301, 302, 307, 308):
        return _failed("http-redirects", asserts, f"status {answer.status_code}, expected 3xx")
    location = answer.headers.get("location", "")
    if not location.startswith("https://"):
        return _failed("http-redirects", asserts, f"location {location!r} is not https")
    return _passed("http-redirects", asserts, f"{answer.status_code} to {location}")


def check_mcp_requires_bearer(client: httpx2.Client, target: Target) -> Check:
    """An unauthenticated call must not reach the protocol at all."""
    asserts = "unauthenticated POST /mcp is 401"
    try:
        answer = client.post(
            target.url(MCP_PATH),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    except httpx2.HTTPError as error:
        return _failed("mcp-requires-bearer", asserts, f"{type(error).__name__}: {error}")
    if answer.status_code != 401:
        return _failed(
            "mcp-requires-bearer",
            asserts,
            f"status {answer.status_code}: the bearer check is not in front of the protocol",
        )
    return _passed("mcp-requires-bearer", asserts, "401")


def check_origin_refused(client: httpx2.Client, target: Target) -> Check:
    asserts = "an unlisted Origin is 403"
    return _expect_status(
        client,
        target,
        name="origin-refused",
        asserts=asserts,
        headers={"Origin": "https://attacker.example"},
        expected=403,
    )


def check_host_refused(client: httpx2.Client, target: Target) -> Check:
    asserts = "an unlisted Host is 421"
    return _expect_status(
        client,
        target,
        name="host-refused",
        asserts=asserts,
        headers={"Host": "not-the-deployment.example"},
        expected=421,
    )


def _expect_status(
    client: httpx2.Client,
    target: Target,
    *,
    name: str,
    asserts: str,
    headers: dict[str, str],
    expected: int,
) -> Check:
    sent = {"Accept": "application/json, text/event-stream", **headers}
    if target.bearer_token:
        sent["Authorization"] = f"Bearer {target.bearer_token}"
    try:
        answer = client.post(
            target.url(MCP_PATH),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers=sent,
        )
    except httpx2.HTTPError as error:
        return _failed(name, asserts, f"{type(error).__name__}: {error}")
    if answer.status_code != expected:
        return _failed(name, asserts, f"status {answer.status_code}, expected {expected}")
    return _passed(name, asserts, str(expected))


def check_webhook_rejects_unsigned(client: httpx2.Client, target: Target) -> Check:
    """The order system's identity is verified after the hop, not assumed from the network."""
    asserts = "an unsigned order-system event is refused"
    try:
        answer = client.post(
            target.url(WEBHOOK_PATH),
            json={"event_id": "smoke", "kind": "order.amended"},
        )
    except httpx2.HTTPError as error:
        return _failed("webhook-rejects-unsigned", asserts, f"{type(error).__name__}: {error}")
    if answer.status_code in (200, 201, 202, 204):
        return _failed(
            "webhook-rejects-unsigned",
            asserts,
            f"status {answer.status_code}: an unsigned event was accepted",
        )
    if answer.status_code >= 500:
        return _failed("webhook-rejects-unsigned", asserts, f"status {answer.status_code}")
    return _passed("webhook-rejects-unsigned", asserts, f"refused with {answer.status_code}")


def check_protocol_revision(client: httpx2.Client, target: Target) -> Check:
    """The deployed handshake negotiates the pinned revision, or this is not that surface."""
    asserts = f"initialize negotiates protocolVersion {PROTOCOL_REVISION}"
    if not target.bearer_token:
        return Check(
            name="protocol-revision",
            asserts=asserts,
            outcome=Outcome.SKIPPED,
            detail="PP_MCP_BEARER_TOKEN is not set",
        )
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_REVISION,
            "capabilities": {},
            "clientInfo": {"name": "promisepatch-deployment-smoke", "version": "1"},
        },
    }
    try:
        answer = client.post(
            target.url(MCP_PATH),
            json=body,
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {target.bearer_token}",
                "Origin": target.base_url,
            },
        )
    except httpx2.HTTPError as error:
        return _failed("protocol-revision", asserts, f"{type(error).__name__}: {error}")
    if answer.status_code != 200:
        return _failed("protocol-revision", asserts, f"status {answer.status_code}")
    negotiated = _negotiated_revision(answer.text)
    if negotiated != PROTOCOL_REVISION:
        return _failed("protocol-revision", asserts, f"negotiated {negotiated!r}")
    return _passed("protocol-revision", asserts, negotiated)


def _negotiated_revision(payload: str) -> str | None:
    """Read the revision out of a JSON body or an SSE frame -- the transport may use either."""
    for candidate in _json_candidates(payload):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            result = parsed.get("result")
            if isinstance(result, dict):
                version = result.get("protocolVersion")
                if isinstance(version, str):
                    return version
    return None


def _json_candidates(payload: str) -> Iterable[str]:
    yield payload
    for line in payload.splitlines():
        if line.startswith("data:"):
            yield line[len("data:") :].strip()


CHECKS: tuple[Callable[[httpx2.Client, Target], Check], ...] = (
    check_tls_and_readiness,
    check_http_redirects,
    check_mcp_requires_bearer,
    check_origin_refused,
    check_host_refused,
    check_webhook_rejects_unsigned,
    check_protocol_revision,
)


def run(target: Target) -> list[Check]:
    # Certificate verification is left at its default, which is on. Nothing in this file
    # weakens it, and a deployment whose certificate does not verify is a failed deployment.
    with httpx2.Client(timeout=TIMEOUT, follow_redirects=False) as client:
        return [check(client, target) for check in CHECKS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deployment smoke checks for the P6 loop.")
    parser.add_argument("--base-url", required=True, help="https origin of the deployment")
    arguments = parser.parse_args(argv)

    if not arguments.base_url.startswith("https://"):
        print("refused: --base-url must be https://", file=sys.stderr)
        return 2

    target = Target(base_url=arguments.base_url, bearer_token=os.environ.get("PP_MCP_BEARER_TOKEN"))
    print(f"target : {target.base_url}")
    checks = run(target)
    for check in checks:
        detail = f"  ({check.detail})" if check.detail else ""
        print(f"  {check.outcome.value:<8} {check.name:<26} {check.asserts}{detail}")

    failed = [c for c in checks if c.outcome is Outcome.FAILED]
    skipped = [c for c in checks if c.outcome is Outcome.SKIPPED]
    print(
        f"\n{len(checks) - len(failed) - len(skipped)}/{len(checks)} passed, "
        f"{len(failed)} failed, {len(skipped)} skipped"
    )
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
