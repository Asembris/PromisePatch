"""No log line this process writes carries a customer approval link.

The link's token is a possession credential: whoever holds it can answer the approval request it
opens, and its payload carries the customer's channel address. Until this module, uvicorn's
access log wrote both forms it arrives in -- the page at ``/?approve=<token>`` and the API at
``/api/customer/approval/<token>`` -- verbatim into CloudWatch, and a plaintext search for the
address found nothing because the address is base64 inside the token.

Two halves. The first tests the pure redaction against the real link and the real route, so the
pattern ``observability`` declares on its own cannot drift from what ``customer_link`` mints.
The second is the property itself, measured the way the deployment writes it: a real uvicorn
server in a process of its own, the real application built the way ``pp api`` builds it, and
everything that process wrote to stdout and stderr read back -- the request line, the refusal,
the validation error and an unhandled failure with its traceback. Each assertion that the token
is absent is paired with one that the redacted line is *present*, so a capture that silently
caught nothing cannot pass.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID

import pytest

from promisepatch.api.routers import customer as customer_router
from promisepatch.config import Settings
from promisepatch.domain import customer_link
from promisepatch.observability.logging import (
    REDACTED,
    configure_logging,
    redact_approval_links,
)

SECRET = "a-local-customer-link-secret"
CHAT = "9876543210"
"""A sentinel chat id: ten digits, the shape of a real one, belonging to nobody."""

REQUEST = UUID("69c047c7-0000-4000-8000-00000000abcd")
TOKEN = customer_link.mint(secret=SECRET, request_id=REQUEST, channel=f"tg:{CHAT}")
PAYLOAD, SIGNATURE = TOKEN.split(".")[1:]
PAGE_URL = customer_link.url_for(
    base_url="https://bakery.test", secret=SECRET, request_id=REQUEST, channel=f"tg:{CHAT}"
)


def _leaks(text: str) -> list[str]:
    """Which recoverable part of the credential ``text`` still holds, if any."""
    return [
        name
        for name, value in (
            ("token", TOKEN),
            ("payload", PAYLOAD),
            ("signature", SIGNATURE),
            ("chat id", CHAT),
        )
        if value in text
    ]


# ------------------------------------------------------------------- the redaction itself


def test_the_sentinel_is_a_real_link_of_both_forms() -> None:
    """The pattern is tested against what ``customer_link`` actually mints, not a guess at it."""
    assert f"?{customer_link.PARAM}={TOKEN}" in PAGE_URL
    routes = {getattr(route, "path", "") for route in customer_router.router.routes}
    assert "/api/customer/approval/{token}" in routes
    assert len(PAYLOAD) > 20 and len(SIGNATURE) > 20


@pytest.mark.parametrize(
    ("line", "kept"),
    [
        (PAGE_URL, f"https://bakery.test/?approve={REDACTED}"),
        (f"/?case=abc&approve={TOKEN}&x=1", f"/?case=abc&approve={REDACTED}&x=1"),
        (f"/api/customer/approval/{TOKEN}", f"/api/customer/approval/{REDACTED}"),
        (
            f"/api/customer/approval/{TOKEN}?approve={TOKEN}",
            f"/api/customer/approval/{REDACTED}?approve={REDACTED}",
        ),
        (
            f'127.0.0.1:5000 - "POST /api/customer/approval/{TOKEN} HTTP/1.1" 202',
            f'127.0.0.1:5000 - "POST /api/customer/approval/{REDACTED} HTTP/1.1" 202',
        ),
        (
            json.dumps({"path": f"/api/customer/approval/{TOKEN}", "n": 1}),
            json.dumps({"path": f"/api/customer/approval/{REDACTED}", "n": 1}),
        ),
        (
            json.dumps({"exception": f"Traceback\nRuntimeError: at /?approve={TOKEN}\nend"}),
            json.dumps({"exception": f"Traceback\nRuntimeError: at /?approve={REDACTED}\nend"}),
        ),
        (f"input: '{TOKEN}x'", f"input: '{REDACTED}'"),
    ],
)
def test_both_forms_and_the_bare_token_are_removed(line: str, kept: str) -> None:
    """Every place a token sits, and nothing either side of it -- the route stays readable."""
    redacted = redact_approval_links(line)
    assert _leaks(redacted) == []
    assert redacted == kept


@pytest.mark.parametrize(
    "line",
    [
        "/api/cases/69c047c7-0000-4000-8000-000000000001?case=abc&x=1",
        '127.0.0.1:5000 - "POST /api/conversation/approve HTTP/1.1" 200',
        "promisepatch-effect-sets v1.0.0, DRIVER_VERSION 1.5.0",
        json.dumps({"event": "api.customer_approval.answered", "phase": "RECEIVED"}),
        "",
    ],
)
def test_a_line_holding_no_link_is_returned_unchanged(line: str) -> None:
    """Not a general scrubber: a worker's approval, a case id and a version string survive."""
    assert redact_approval_links(line) == line


def test_a_handler_that_cannot_write_does_not_print_the_record_raw() -> None:
    """``handleError`` bypasses every formatter, so it is the one path the wrapping cannot see.

    A stream that fails -- closed, a broken pipe -- would otherwise have the standard library
    print the record's message and arguments, the token among them, to stderr. Captured with
    ``redirect_stderr`` rather than ``capsys``: configuring logging under a per-test capture
    would leave structlog printing to a stream pytest closes when the test ends.
    """
    configure_logging(Settings(log_level="info"))
    broken = io.StringIO()
    broken.close()
    handler = logging.StreamHandler(broken)
    logger = logging.getLogger("promisepatch.tests.broken_stream")
    logger.addHandler(handler)
    logger.propagate = False
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            logger.info(
                '%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", f"/?approve={TOKEN}", "1.1", 200
            )
    finally:
        logger.removeHandler(handler)
    assert logging.raiseExceptions is False
    assert _leaks(stderr.getvalue()) == []


# ------------------------------------------------------------ the deployment's own log lines

SERVER = """
import sys

import uvicorn

from promisepatch.config import Settings

SECRET, TOKEN, PORT = sys.argv[1], sys.argv[2], int(sys.argv[3])


class Unreachable:
    # A database whose every use fails, with the link in its own message: it forces the one
    # path on which the API writes a request's path itself, and puts the token in a traceback.
    def connect(self):
        raise RuntimeError(f"cannot open /api/customer/approval/{TOKEN} or /?approve={TOKEN}")

    begin = connect


def factory():
    from promisepatch.main import create_app

    api = create_app(
        Settings(
            customer_link_secret=SECRET,
            customer_link_base_url="https://bakery.test",
            database_url=None,
            static_root=None,
            log_level="info",
        )
    )
    api.state.database = Unreachable()
    return api


uvicorn.run(factory, factory=True, host="127.0.0.1", port=PORT, lifespan="off")
"""
"""What ``pp api`` runs -- ``uvicorn.run`` with its default logging, the application built after
uvicorn has configured its loggers -- in a process of its own, so what is read back is exactly
what that process wrote to its stdout and stderr, which is what the container log driver ships."""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Callable[[], str]]]:
    """A real uvicorn process on a free port, and a way to read what it wrote once stopped.

    Its output goes to a file rather than a pipe: a pipe nobody reads fills, and a server
    blocked writing a traceback into it stops answering.
    """
    port = _free_port()
    log = tmp_path / "server.log"
    with log.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(
            [sys.executable, "-c", SERVER, SECRET, TOKEN, str(port)],
            stdout=sink,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        )

    def written() -> str:
        time.sleep(0.5)
        process.kill()
        process.wait(timeout=20)
        return log.read_text(encoding="utf-8")

    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while True:
        assert process.poll() is None, "the server process exited before it served"
        assert time.monotonic() < deadline, "uvicorn did not start"
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=2):
                break
        except OSError:
            time.sleep(0.2)
    try:
        yield base, written
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=20)


def _call(url: str, *, method: str = "GET", body: bytes | None = None) -> int:
    headers = {"Content-Type": "application/json"} if body else {}
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return int(response.status)
    except urllib.error.HTTPError as failure:
        return int(failure.code)


def test_no_line_the_served_api_writes_holds_the_link(
    served: tuple[str, Callable[[], str]],
) -> None:
    """Both URL forms, answered and refused and failed, through the handlers that write them."""
    base, written_by_server = served
    forged = f"v1.{PAYLOAD}.{'A' * len(SIGNATURE)}"
    answer = json.dumps({"answer": "APPROVE"}).encode()
    statuses = {
        "page": _call(f"{base}/?approve={TOKEN}"),
        "page-among-others": _call(f"{base}/?case=abc&approve={TOKEN}&x=1"),
        "read-failing": _call(f"{base}/api/customer/approval/{TOKEN}"),
        "answer-failing": _call(
            f"{base}/api/customer/approval/{TOKEN}", method="POST", body=answer
        ),
        "forged": _call(f"{base}/api/customer/approval/{forged}"),
        "oversized": _call(f"{base}/api/customer/approval/{TOKEN}{'x' * 1100}"),
        "bad-body": _call(f"{base}/api/customer/approval/{TOKEN}", method="POST", body=b"{}"),
    }
    assert statuses == {
        "page": 404,
        "page-among-others": 404,
        "read-failing": 500,
        "answer-failing": 500,
        "forged": 404,
        "oversized": 422,
        "bad-body": 422,
    }
    written = written_by_server()

    assert _leaks(written) == [], "a log line kept part of the approval credential"

    # The lines are there, and still say which route was asked for and how it ended.
    assert f'"GET /?approve={REDACTED} HTTP/1.1" 404' in written
    assert f'"GET /?case=abc&approve={REDACTED}&x=1 HTTP/1.1" 404' in written
    assert f'"GET /api/customer/approval/{REDACTED} HTTP/1.1" 500' in written
    assert f'"POST /api/customer/approval/{REDACTED} HTTP/1.1" 500' in written
    assert f'"GET /api/customer/approval/{REDACTED} HTTP/1.1" 422' in written
    events = [json.loads(line) for line in written.splitlines() if line.startswith("{")]
    failures = [event for event in events if event.get("event") == "api.unhandled_error"]
    assert len(failures) == 2
    for failure in failures:
        assert failure["path"] == f"/api/customer/approval/{REDACTED}"
        assert f"cannot open /api/customer/approval/{REDACTED}" in failure["exception"]
    assert any(event.get("event") == "api.customer_approval.rejected" for event in events)
    assert any(event.get("event") == "api.request_invalid" for event in events)
