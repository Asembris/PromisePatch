"""What a PromisePatch process is, computed by that process from its own bytes and settings.

An operator could already read which migration a deployment expects off ``/readyz``, and since
``pp runtime-identity`` which model it would call. Neither answers the two questions a
measurement has to answer before it can compare three arms fairly: **is every process running
the same code**, and **is every process configured the same way in the ways that change
behaviour**.

Both gaps have been paid for here. A measurement was once taken against a container built
before the code it was measuring; another was taken against ``api``, ``worker`` and ``mcp``
containers carrying no provider configuration at all, so the product answered semantic jobs
with the deterministic fake while the thing it was being compared with called a real model. In
both cases every readiness probe passed, because no probe asked either question.

**The build identity is computed, not declared.** :func:`source_digest` hashes the source of
the three packages that decide behaviour, as they are on this process's import path. A tag, a
label or a build argument is a claim somebody made about an image; a digest over the bytes that
are actually loaded is a fact the process computes about itself, and a stale image cannot
report a fresh one. Line endings are normalised, so a CRLF checkout on a developer's machine
and the LF copy inside a container agree when the content agrees.

**Nothing here is a secret and nothing here opens anything.** The database is reported as
``user@host:port/dbname`` -- never a password, because :func:`database_target` reads the URL's
parts rather than rendering it. Whether an AWS credential *resolves* is a boolean the caller
supplies. No connection is opened, no provider is built and no model is called: this module
reads settings and files, which is what makes it safe to run against a deployment.
"""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

from promisepatch.config import LlmProvider, Settings
from promisepatch.db.revision import HEAD_REVISION

SOURCE_PACKAGES: Final = ("promisepatch", "promise_graph", "order_contract")
"""The three importable packages whose source decides what this process does.

``promisepatch`` is the application, ``promise_graph`` the engine every decision is derived by,
and ``order_contract`` the shared types both sides of the order boundary are written against. A
process running a different revision of any of them is running different behaviour, whatever
its image tag says.
"""

SOURCE_SUFFIX: Final = ".py"
EXCLUDED_PARTS: Final = frozenset({"__pycache__"})
"""Compiled output is derived from the source and differs by interpreter, so it is not hashed."""


def _source_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob(f"*{SOURCE_SUFFIX}")):
        if EXCLUDED_PARTS.isdisjoint(path.parts):
            yield path


def source_digest(packages: tuple[str, ...] = SOURCE_PACKAGES) -> str:
    """One hex digest over the source of every named package, as this process imports it.

    The algorithm is deliberately dull and is stated here in full: the path relative to the
    package root, a NUL, the bytes with CRLF normalised to LF, another NUL, over the paths in
    sorted order. A package that cannot be imported is recorded as absent rather than skipped,
    so a stack missing one does not quietly agree with a stack that has it.
    """
    hasher = hashlib.sha256()
    for name in packages:
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\0")
        try:
            module = importlib.import_module(name)
            root = Path(module.__file__ or "").resolve().parent
        except Exception:
            hasher.update(b"absent\0")
            continue
        for path in _source_files(root):
            hasher.update(path.relative_to(root).as_posix().encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(path.read_bytes().replace(b"\r\n", b"\n"))
            hasher.update(b"\0")
    return hasher.hexdigest()


def database_target(url: str) -> str:
    """``user@host:port/dbname`` from a connection string, with no password in it.

    Parsed rather than rendered. A renderer that masks the password still carries its length
    and its position, and a value written into a committed run manifest should carry neither.
    An unparseable URL returns the empty string, which every comparison then refuses.
    """
    if not url:
        return ""
    try:
        from sqlalchemy.engine.url import make_url

        parsed = make_url(url)
    except Exception:
        return ""
    host = parsed.host or ""
    port = "" if parsed.port is None else f":{parsed.port}"
    user = f"{parsed.username}@" if parsed.username else ""
    return f"{user}{host}{port}/{parsed.database or ''}"


def runtime_identity(
    settings: Settings,
    *,
    credential_resolves: bool | None = None,
) -> dict[str, Any]:
    """Everything about this process that changes what it would do, as plain JSON values.

    ``credential_resolves`` is passed in rather than asked here: resolving the AWS credential
    chain is I/O, and this module opens nothing. The caller that wants the boolean asks for it
    and hands it over; a caller that does not gets a block without one.
    """
    database_url = "" if settings.database_url is None else settings.database_url.get_secret_value()
    order_system = settings.order_system_base_url or ""
    identity: dict[str, Any] = {
        "service": "promisepatch",
        "env": settings.env,
        "source_digest": source_digest(),
        "migration_revision": HEAD_REVISION,
        "llm_provider": settings.llm_provider.value,
        "demo_session_enabled": settings.demo_session_enabled,
        "explanation_verbalisation": settings.explanation_verbalisation,
        "bakery_tz": settings.bakery_tz,
        "database_target": database_target(database_url),
        "order_system_base_url": order_system.rstrip("/"),
        "customer_link_base_url": (settings.customer_link_base_url or "").rstrip("/"),
        "cors_origins": settings.cors_origins,
    }
    if settings.llm_provider is LlmProvider.BEDROCK:
        from promisepatch.integrations.bedrock import CONVERSE_API, TEMPERATURE

        identity.update(
            {
                "api": CONVERSE_API,
                "model_id": settings.bedrock_model_id.strip(),
                "region": settings.aws_region.strip(),
                "temperature": TEMPERATURE,
                "max_attempts": settings.bedrock_max_attempts,
                "timeout_seconds": settings.bedrock_timeout_seconds,
            }
        )
        if credential_resolves is not None:
            identity["credential_resolves"] = credential_resolves
    return identity


BEHAVIOURAL_KEYS: Final = (
    "source_digest",
    "migration_revision",
    "llm_provider",
    "demo_session_enabled",
    "explanation_verbalisation",
    "bakery_tz",
    "model_id",
    "region",
    "temperature",
    "api",
)
"""The keys two processes serving one measurement must agree on exactly.

Addresses are deliberately absent. ``database_target``, ``order_system_base_url`` and the two
origin values legitimately differ between a container on a compose network and a process on the
host that publishes it, and requiring string equality there would refuse a correct stack. What
they must agree on is the *system named*, which is an alias comparison and belongs to whoever
knows the port mapping, not to this module.
"""


def behavioural_differences(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    keys: tuple[str, ...] = BEHAVIOURAL_KEYS,
) -> tuple[str, ...]:
    """Every key in ``keys`` the two identities disagree on, named with both of its values.

    A key absent from both is agreement: a stack configured for no provider publishes no model
    id, and two such stacks agree about the model they would call. A key present in one and
    absent from the other is a difference, which is what refuses a split stack where one process
    is configured for Bedrock and another fell back to the fake.
    """
    return tuple(
        f"{key}: {left.get(key)!r} vs {right.get(key)!r}"
        for key in keys
        if (key in left or key in right) and left.get(key) != right.get(key)
    )


__all__ = [
    "BEHAVIOURAL_KEYS",
    "SOURCE_PACKAGES",
    "behavioural_differences",
    "database_target",
    "runtime_identity",
    "source_digest",
]
