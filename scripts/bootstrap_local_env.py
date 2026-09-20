"""Generate the local stack's environment files from their committed templates.

The templates in ``docker/env/*.env.example`` are the documentation and the shape; this fills
in the values that must not be committed and writes the files compose, the order system and
the host tooling read.

Three things follow from what these credentials are:

* **They are generated, never defaulted.** A committed default password is a password every
  copy of this repository shares, and "it is only local" is exactly how one reaches an
  environment that is not. Nothing here has a fallback value.
* **One secret, one placeholder, every file.** The superuser password appears in the
  PostgreSQL container's configuration and in the administrative URL; the runtime role's
  password appears in the migration environment that creates the role and in the URL the API
  connects with; the order-system webhook secret appears in both applications' environments,
  because a shared secret only works if both sides were given the same one. They are
  substituted together so the files cannot disagree.
* **Existing files are left alone.** Regenerating in place would rotate the runtime role's
  password out from under a database that already has the old one, so a rewrite has to be
  asked for with ``--force`` and paired with removing the volume.

The output is scoped to disposable local Docker development. It is not a deployment
mechanism, and a deployed environment gets its secrets from a secret manager instead.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from pathlib import Path

_PLACEHOLDER = re.compile(r"__[A-Z0-9_]+__")
"""What an unsubstituted template value looks like, whatever prefix its variable carries.

Matched against every rendered line rather than against the ones starting ``PP_``: two
applications read these files now, and a guard that only knew one of their prefixes would let
the other ship a file with a placeholder in it."""

ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = ROOT / "docker" / "env"

FILES: tuple[str, ...] = (
    "postgres.env",
    "migrate.env",
    "api.env",
    "mcp.env",
    "host.env",
    "order-simulator.env",
)

PUBLISHED_PORT_VARIABLE = "PROMISEPATCH_POSTGRES_PUBLISHED_PORT"
DEFAULT_PUBLISHED_PORT = "55432"
"""Which host port the database is published on, and the value every machine had before.

Not a secret and not generated: it is a choice about this machine's free ports. It is resolved
the way compose resolves it -- the real environment first, then the repository's own `.env` --
so `docker compose up` and the `host.env` this writes cannot end up naming different ports.
Reading one non-secret key out of `.env` is not the interpolation compose refuses: a port
number cannot redirect the stack at another database.
"""

ORDER_SIMULATOR_PORT_VARIABLE = "PROMISEPATCH_ORDER_SIMULATOR_PUBLISHED_PORT"
DEFAULT_ORDER_SIMULATOR_PORT = "58100"
"""The same question for the order system, and the same answer for the same reason.

A host process reaches the order system on its published port; a container reaches it by
service name. A machine that had to move the published port and a template that still names the
default is how ``docker/env/host.env`` came to say ``58100`` while compose publishes ``48100``:
a host process would push every governed amendment at nothing. See
``scripts.sur1.preflight.config_parity``, which refuses a scored run for exactly that.
"""


def published_port(
    root: Path,
    variable: str = PUBLISHED_PORT_VARIABLE,
    default: str = DEFAULT_PUBLISHED_PORT,
) -> str:
    """The host port a published service is reachable on, following compose's own precedence.

    The real environment first, then the repository's own ``.env``, then the default -- which is
    the order ``docker compose`` itself resolves an interpolated value in. Defaulted to
    PostgreSQL's variable so every existing caller keeps asking the question it was asking.
    """
    from_environment = os.environ.get(variable)
    if from_environment:
        return _valid_port(variable, from_environment)

    dotenv = root / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip() == variable and value.strip():
                return _valid_port(variable, value.strip())

    return default


def _valid_port(variable: str, value: str) -> str:
    """Refuse anything that is not a port, rather than writing it into a connection string."""
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise SystemExit(f"{variable}={value!r} is not a TCP port number")
    return value


EXTRA_CA = "extra-ca.crt"
"""An optional additional root CA the container builds trust, created empty.

It exists so the build-secret mount always resolves. Leave it empty unless TLS on this
machine is terminated by an antivirus or corporate proxy whose issuer no base image knows,
in which case put that root certificate here and the images will build against it."""


def generated_secrets() -> dict[str, str]:
    """One value per placeholder, generated once and shared across every template.

    The two database passwords are hex: they are carried inside a connection URI, and a
    character set that needs no percent-encoding removes a whole class of "works until the
    generator happens to emit a slash" failure. The session secret is not in a URI and is
    drawn from the wider alphabet. The demo logins are shorter because a human types them.
    """
    return {
        "__POSTGRES_PASSWORD__": secrets.token_hex(24),
        "__APP_PASSWORD__": secrets.token_hex(24),
        "__SESSION_SECRET__": secrets.token_urlsafe(48),
        "__WORKER_PASSWORD__": secrets.token_urlsafe(12),
        "__OWNER_PASSWORD__": secrets.token_urlsafe(12),
        # Shared by two applications rather than held by one, which is what makes it a
        # shared secret: PromisePatch verifies exactly what the order system signs.
        "__ORDER_WEBHOOK_SECRET__": secrets.token_urlsafe(32),
        # The MCP process presents this to the intent API. Shared by exactly those two, so an
        # MCP endpoint somebody stands up elsewhere reaches no case in this stack.
        "__INTERNAL_SERVICE_TOKEN__": secrets.token_urlsafe(32),
        # What an MCP client presents to the MCP endpoint. Generated rather than defaulted,
        # because a default would mean every copy of this repository shipped one usable token.
        "__MCP_BEARER_TOKEN__": secrets.token_urlsafe(32),
        # What a customer's approval link is signed with. Generated per machine for the same
        # reason: a shipped default would let anybody write a link this stack would open.
        "__CUSTOMER_LINK_SECRET__": secrets.token_urlsafe(32),
    }


def render(template: str, values: dict[str, str]) -> str:
    """Substitute every placeholder, and refuse to write a file that still has one."""
    rendered = template
    for placeholder, value in values.items():
        rendered = rendered.replace(placeholder, value)
    remaining = [line for line in rendered.splitlines() if _PLACEHOLDER.search(line)]
    if remaining:
        raise SystemExit(
            "a template placeholder was not substituted; "
            "scripts/bootstrap_local_env.py and docker/env/*.env.example have drifted"
        )
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Rewrite files that already exist, with freshly generated secrets. "
            "Remove the database volume as well: the runtime role's password lives in it."
        ),
    )
    args = parser.parse_args(argv)

    # Created before the early return: it is not a secret and not generated, and a stack
    # whose environment already exists still needs the mount to resolve.
    (ENV_DIR / EXTRA_CA).touch()

    existing = [name for name in FILES if (ENV_DIR / name).exists()]
    if existing and not args.force:
        print(f"already present, leaving untouched: {', '.join(existing)}")
        missing = [name for name in FILES if name not in existing]
        if missing:
            # Named explicitly rather than quietly generated. A file that is missing because
            # the stack gained a service holds a *shared* secret, and generating one side of a
            # shared secret while the other side keeps its old one produces a stack that comes
            # up healthy and cannot talk to itself.
            print(f"missing, and not generated: {', '.join(missing)}")
            print("these hold secrets shared with the files above; regenerate all of them:")
        print("re-generate with --force, then: docker compose down --volumes")
        return 0

    values = generated_secrets()
    # Substituted alongside the secrets so `render` still refuses a file with an
    # unsubstituted placeholder left in it.
    values["__POSTGRES_PUBLISHED_PORT__"] = published_port(ROOT)
    for name in FILES:
        template = (ENV_DIR / f"{name}.example").read_text(encoding="utf-8")
        (ENV_DIR / name).write_text(render(template, values), encoding="utf-8")

    print(f"wrote {', '.join(f'docker/env/{name}' for name in FILES)}")
    print("secrets are generated; the demo logins are in docker/env/migrate.env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
