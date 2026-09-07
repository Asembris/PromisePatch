"""Run a command against the local stack without disturbing the repository's ``.env``.

Repository tooling -- Alembic, the integration suite, ``pp reset-demo-state`` -- reads its
connection strings from the environment, and pydantic-settings falls back to ``.env`` in the
working directory. A developer whose ``.env`` points at a hosted database should not have to
overwrite it to run the suite against a disposable local one, so this loads
``docker/env/host.env`` and runs the command with it:

    uv run python scripts/with_local_env.py -- uv run pytest apps/backend

The loaded values take precedence over ``.env`` because they are set in the real environment,
which pydantic-settings prefers over a file. Nothing is printed: the file holds credentials.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from bootstrap_local_env import published_port

ROOT = Path(__file__).resolve().parents[1]
HOST_ENV = ROOT / "docker" / "env" / "host.env"

_LOCAL_ENDPOINT = re.compile(r"@(127\.0\.0\.1|localhost|\[::1\]):(\d+)/")
"""The host and port in a local connection string. Loopback only, so a URL naming anything
else is left exactly as it was rather than quietly repointed."""


def repoint(values: dict[str, str], port: str) -> dict[str, str]:
    """Move the loopback connection strings onto ``port``.

    ``host.env`` is generated once and then left alone -- regenerating it rotates the runtime
    role's password out from under a database that still has the old one. So when a machine
    has to publish PostgreSQL somewhere other than the port its `host.env` was written with,
    the launcher moves the address rather than asking for the file to be rebuilt.
    """
    return {
        key: (_LOCAL_ENDPOINT.sub(rf"@\g<1>:{port}/", value) if "DATABASE_URL" in key else value)
        for key, value in values.items()
    }


def load(path: Path) -> dict[str, str]:
    """Read ``KEY=value`` lines, ignoring comments and blanks. No interpolation, no quoting.

    The file is generated from a committed template by ``bootstrap_local_env.py``, so it has
    exactly this shape; a general dotenv parser here would be inventing a contract nothing
    else in the repository speaks.
    """
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def main(argv: list[str]) -> int:
    command = argv[1:]
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("usage: with_local_env.py -- COMMAND [ARGS...]", file=sys.stderr)
        return 2
    if not HOST_ENV.is_file():
        print(
            "docker/env/host.env is missing; run: uv run python scripts/bootstrap_local_env.py",
            file=sys.stderr,
        )
        return 1

    # Resolved with `bootstrap_local_env`'s own rule rather than a second one, so the port the
    # suite connects to is by construction the port compose publishes.
    values = repoint(load(HOST_ENV), published_port(ROOT))
    environment = {**os.environ, **values}
    # `shell=False`: the command is an argument vector the caller already split, and passing it
    # through a shell would make quoting in a test command a source of surprise.
    return subprocess.run(command, env=environment, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv))
