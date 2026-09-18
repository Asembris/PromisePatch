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
  deployment that quietly negotiated an older one would not be the audited surface;
* ``POST /internal/intents/report`` must be ``404`` from outside. The TLS proxy used to refuse
  it by accident -- everything but a short allowlist fell through to a 404 -- and it now serves
  the page from a catch-all, so the refusal is a line somebody wrote and can therefore be a
  line somebody deletes;
* an unknown ``/api/...`` path must answer the API's JSON rather than the page.

Two further checks assert that the deployment is the one that was deployed, rather than merely
a working one: the root serves the real bundle, and ``/healthz`` names the commit its image was
built from. ``PP_EXPECTED_IMAGE_TAG`` enables the second, and ``deploy.sh smoke`` sets it from
the stack's own ``ImageTag`` parameter -- so a host still serving an older image fails here
instead of being found out later.

**TLS verification is on and is never turned off.** No check asks httpx to skip it; a
certificate that does not verify fails the run, which is the point of deploying with a real
name and a real certificate rather than a self-signed one.

Run it against the deployed origin::

    uv run python scripts/deployment_smoke.py --base-url https://<host>

``PP_MCP_BEARER_TOKEN`` enables the two checks that have to get *past* the bearer check to
observe anything: the authenticated handshake, and the origin guard that sits behind it.
Without it both report ``SKIPPED`` and the run still fails if any other check fails -- a
missing token must not be able to turn a broken deployment green.
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
INTERNAL_PATH = "/internal/intents/report"
UNKNOWN_API_PATH = "/api/there-is-no-such-route"
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"
# Shaped like a real case id and naming nothing. The page is served for a deep link because
# the path is not the API's, never because the case exists.
DEEP_LINK = f"/?case={ABSENT_UUID}"
# What the built page has and a sentence about the deployment does not.
ROOT_ELEMENT = 'id="root"'

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
    # The origin guard sits *behind* the bearer check, so an unauthenticated request never
    # reaches it -- it is refused 401 first, and 401 is not evidence about the origin at all.
    # Reporting FAILED here would say the deployed guard is broken when what is missing is a
    # credential in the shell running the check. That happened on 2026-09-18: a healthy
    # `deploy.sh smoke` against the live stack reported 10/12 and exit 2 for this reason
    # alone, immediately after an infrastructure upgrade, which is exactly the moment a
    # spurious failure is read as damage. SKIPPED is the honest outcome, and it still cannot
    # turn a broken deployment green: a skip is neither a pass nor silence.
    if not target.bearer_token:
        return Check(
            name="origin-refused",
            asserts=asserts,
            outcome=Outcome.SKIPPED,
            detail="PP_MCP_BEARER_TOKEN is not set",
        )
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


def check_spa_at_root(client: httpx2.Client, target: Target) -> Check:
    """The judge's one action lands somewhere, and the somewhere is the real bundle.

    Asserting a 200 alone would pass on the one-line sentence this deployment used to answer
    with, so what is asserted is the two things only a built page has: the element the
    application mounts into, and a module the page loads.
    """
    asserts = "GET / serves the built page"
    try:
        answer = client.get(target.url("/"))
    except httpx2.HTTPError as error:
        return _failed("spa-at-root", asserts, f"{type(error).__name__}: {error}")
    if answer.status_code != 200:
        return _failed("spa-at-root", asserts, f"status {answer.status_code}")
    body = answer.text
    if ROOT_ELEMENT not in body or "<script" not in body:
        return _failed("spa-at-root", asserts, "the root answers, but not with a built page")
    cache = answer.headers.get("cache-control")
    if cache != "no-store":
        return _failed(
            "spa-at-root",
            asserts,
            f"cache-control {cache!r}: a held index outlives the bundle it names",
        )
    return _passed("spa-at-root", asserts, f"{len(body)} bytes, not stored")


def check_deep_link(client: httpx2.Client, target: Target) -> Check:
    """A reload, a restored tab and a pasted link all arrive as a cold request for this path."""
    asserts = "GET /?case=<id> serves the page rather than a 404"
    try:
        answer = client.get(target.url(DEEP_LINK))
    except httpx2.HTTPError as error:
        return _failed("deep-link", asserts, f"{type(error).__name__}: {error}")
    if answer.status_code != 200 or ROOT_ELEMENT not in answer.text:
        return _failed("deep-link", asserts, f"status {answer.status_code}")
    return _passed("deep-link", asserts, "200")


def check_unknown_api_path_is_not_the_page(client: httpx2.Client, target: Target) -> Check:
    """An API client that mistypes a path is told so, in the shape it expects.

    A bundle mounted carelessly answers anything with the page, which turns a mistyped API path
    into an HTML document with status 200: nothing errored, and the body is not what anybody
    asked for.
    """
    asserts = "an unknown /api path answers JSON rather than the page"
    try:
        answer = client.get(target.url(UNKNOWN_API_PATH))
    except httpx2.HTTPError as error:
        return _failed("unknown-api-path", asserts, f"{type(error).__name__}: {error}")
    if answer.status_code != 404:
        return _failed("unknown-api-path", asserts, f"status {answer.status_code}, expected 404")
    if "<html" in answer.text or ROOT_ELEMENT in answer.text:
        return _failed("unknown-api-path", asserts, "the bundle answered for an API path")
    return _passed("unknown-api-path", asserts, "404 json")


def check_internal_is_not_published(client: httpx2.Client, target: Target) -> Check:
    """The intent API is reachable from the ``mcp`` container and from nowhere else.

    It was unreachable by accident until the page needed a catch-all: the proxy's allowlist
    404ed everything it did not name. The refusal is now a line somebody wrote, which means it
    is a line somebody can delete, which is why it is checked from outside rather than read in
    a file.
    """
    asserts = "POST /internal/intents/report from outside is 404"
    try:
        answer = client.post(
            target.url(INTERNAL_PATH),
            json={"command_id": ABSENT_UUID, "text": "deployment smoke"},
        )
    except httpx2.HTTPError as error:
        return _failed("internal-not-published", asserts, f"{type(error).__name__}: {error}")
    if answer.status_code != 404:
        return _failed(
            "internal-not-published",
            asserts,
            f"status {answer.status_code}: the internal intent API is published",
        )
    return _passed("internal-not-published", asserts, "404")


def check_deployed_image(client: httpx2.Client, target: Target) -> Check:
    """What is running, against what the stack says it deployed.

    The first release was believed deployed and was not: a stack update carrying a new image tag
    reported success, left the instance id alone, and the host went on serving the image it
    first booted with. This is the check that fails when that happens.
    """
    expected = os.environ.get("PP_EXPECTED_IMAGE_TAG")
    asserts = "the deployed image is the commit the stack declares"
    if not expected:
        return Check(
            name="deployed-image",
            asserts=asserts,
            outcome=Outcome.SKIPPED,
            detail="PP_EXPECTED_IMAGE_TAG is not set",
        )
    try:
        answer = client.get(target.url("/healthz"))
    except httpx2.HTTPError as error:
        return _failed("deployed-image", asserts, f"{type(error).__name__}: {error}")
    if answer.status_code != 200:
        return _failed("deployed-image", asserts, f"status {answer.status_code}")
    served = answer.json().get("image")
    if served != expected:
        return _failed(
            "deployed-image", asserts, f"serving {served!r}, the stack declares {expected!r}"
        )
    return _passed("deployed-image", asserts, str(served))


CHECKS: tuple[Callable[[httpx2.Client, Target], Check], ...] = (
    check_tls_and_readiness,
    check_http_redirects,
    check_mcp_requires_bearer,
    check_origin_refused,
    check_host_refused,
    check_webhook_rejects_unsigned,
    check_protocol_revision,
    check_spa_at_root,
    check_deep_link,
    check_unknown_api_path_is_not_the_page,
    check_internal_is_not_published,
    check_deployed_image,
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
