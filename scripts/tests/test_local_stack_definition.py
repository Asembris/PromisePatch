"""The local stack definition, and the one property this slice found it had lost.

No container is started here and nothing is read from a running stack: these are properties of
the files on disk, which is where the defect was.

The property is agreement between two files that have no reason to know about each other.
``docker-compose.yml`` chooses which host address the frontend is published on, and
``docker/env/api.env.example`` chooses which browser origins may post a login. A browser sent
to the published address reports that address as its ``Origin``, and the login endpoint matches
it against the allowlist exactly -- so if the two files name different spellings of the same
loopback address, every login from the address the stack advertises is refused with
``ORIGIN_NOT_ALLOWED``. That is what happened, and reading either file alone shows nothing
wrong with it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
API_TEMPLATE = ROOT / "docker" / "env" / "api.env.example"

FRONTEND_CONTAINER_PORT = "5173"
"""What Vite listens on inside the network. The published host port is free to differ."""


def _published_frontend_port() -> str:
    """The host port ``docker compose`` publishes the frontend on."""
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    published = compose["services"]["frontend"]["ports"]
    for mapping in published:
        host, _, container = str(mapping).rpartition(":")
        if container == FRONTEND_CONTAINER_PORT:
            return host.rpartition(":")[2]
    raise AssertionError(f"no published mapping for container port {FRONTEND_CONTAINER_PORT}")


def _allowlist(template: Path) -> tuple[str, ...]:
    """``PP_CORS_ORIGINS`` as the settings model would read it."""
    for line in template.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "PP_CORS_ORIGINS":
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
    raise AssertionError(f"{template.name} does not set PP_CORS_ORIGINS")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_the_api_template_serves_the_address_compose_publishes(host: str) -> None:
    """Both spellings of the published loopback address may sign in.

    Parametrised rather than written once because the two are genuinely separate origins to an
    exact-match allowlist, and naming only the one a developer happens to type is how the
    other becomes a 403 nobody can explain from the code.
    """
    port = _published_frontend_port()
    assert f"http://{host}:{port}" in _allowlist(API_TEMPLATE)


def test_the_api_template_allowlist_is_literal_loopback_only() -> None:
    """No wildcard and no off-machine host: widening this is not how a local origin is added."""
    for origin in _allowlist(API_TEMPLATE):
        assert "*" not in origin, f"{origin} is a wildcard"
        assert re.fullmatch(r"http://(localhost|127\.0\.0\.1):\d+", origin), origin
