"""Generate the local stack's environment files from their committed templates.

The templates in ``docker/env/*.env.example`` are the documentation and the shape; this fills
in the values that must not be committed and writes the four files compose and the host
tooling read.

Three things follow from what these credentials are:

* **They are generated, never defaulted.** A committed default password is a password every
  copy of this repository shares, and "it is only local" is exactly how one reaches an
  environment that is not. Nothing here has a fallback value.
* **One secret, one placeholder, every file.** The superuser password appears in the
  PostgreSQL container's configuration and in the administrative URL; the runtime role's
  password appears in the migration environment that creates the role and in the URL the API
  connects with. They are substituted together so the files cannot disagree.
* **Existing files are left alone.** Regenerating in place would rotate the runtime role's
  password out from under a database that already has the old one, so a rewrite has to be
  asked for with ``--force`` and paired with removing the volume.

The output is scoped to disposable local Docker development. It is not a deployment
mechanism, and a deployed environment gets its secrets from a secret manager instead.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = ROOT / "docker" / "env"

FILES: tuple[str, ...] = ("postgres.env", "migrate.env", "api.env", "host.env")

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
    }


def render(template: str, values: dict[str, str]) -> str:
    """Substitute every placeholder, and refuse to write a file that still has one."""
    rendered = template
    for placeholder, value in values.items():
        rendered = rendered.replace(placeholder, value)
    remaining = [line for line in rendered.splitlines() if "__" in line and line.startswith("PP_")]
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
        print("re-generate with --force, then: docker compose down --volumes")
        return 0

    values = generated_secrets()
    for name in FILES:
        template = (ENV_DIR / f"{name}.example").read_text(encoding="utf-8")
        (ENV_DIR / name).write_text(render(template, values), encoding="utf-8")

    print(f"wrote {', '.join(f'docker/env/{name}' for name in FILES)}")
    print("secrets are generated; the demo logins are in docker/env/migrate.env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
