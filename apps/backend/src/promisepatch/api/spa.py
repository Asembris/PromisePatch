"""The browser bundle, served by the process that answers everything on it.

[ADR-0012](../../../../docs/adr/0012-spa-served-by-the-deployed-host.md) records why: the
deployed composition has 44 bytes of headroom, the instance role's registry read names exactly
two repositories, and the page is up exactly when the API is up if the API is what serves it.

Two properties make the difference between a static mount and a correct one.

**The API owns its own paths, and the page never answers for them.** A single-page application
is served by answering *anything* with ``index.html``, and a bundle mounted carelessly turns
every mistyped API path into an HTML page with status 200 -- so a client that meant to call the
API receives a document, parses nothing, and reports a bug about the wrong system. Every prefix
this process serves is enumerated in :data:`API_OWNED` and answered with the API's own JSON
``404`` instead. ``/internal`` is in that list twice over: the intent API is reachable only from
the ``mcp`` container across the private network, the deployment's TLS proxy refuses it from
outside, and it is never a page here either.

**The index is never cached and the hashed assets always are.** Vite emits
``assets/<name>-<hash>.js``: the content is in the name, so those may be held forever. The index
names them, changes on every release, and is the one file whose staleness is fatal -- a cached
``index.html`` pointing at a bundle the next release deleted is a blank page for exactly as long
as the browser keeps it.

The whole module is inert unless :attr:`~promisepatch.config.Settings.static_root` is set, which
it is only in the deployed image. Local development keeps the Vite dev server and its proxy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import FastAPI, HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.routing import Route

from promisepatch.observability import get_logger

logger = get_logger(__name__)

INDEX: Final = "index.html"
ASSETS: Final = "assets"

API_OWNED: Final[tuple[str, ...]] = (
    "/api",
    "/events",
    "/internal",
    "/healthz",
    "/readyz",
    "/docs",
    "/redoc",
    "/openapi.json",
)
"""Every prefix this process serves itself. A path under one of these is never a page.

Kept as one list rather than as a check per router, because the failure it prevents -- an API
client receiving HTML with status 200 -- is the same failure whichever router forgot.
"""

IMMUTABLE: Final = "public, max-age=31536000, immutable"
"""For content-hashed assets: the name changes when the content does."""

NEVER_STORED: Final = "no-store"
"""For the index, and for anything else not named by its hash."""

SERVED_METHODS: Final = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]
"""All of them, so that an unknown path answers 404 rather than 405.

The fallback only ever *serves* a GET or a HEAD; the rest are accepted so the route matches and
can refuse them the way an unrouted path was refused before this file existed.
"""


def is_api_owned(path: str) -> bool:
    """Whether this path belongs to a router rather than to the page."""
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in API_OWNED)


def _resolve(root: Path, path: str) -> Path | None:
    """The file this request names, or ``None`` when it names none inside the bundle.

    The containment check is the point. A request path is attacker-controlled text, and
    ``root / "../../etc/passwd"`` is an ordinary ``Path`` that resolves outside the bundle
    perfectly happily -- so the resolved candidate is required to be under the resolved root
    rather than merely built from it.
    """
    candidate = Path(root, path.lstrip("/")).resolve()
    base = root.resolve()
    if candidate != base and base not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _cache_control(base: Path, file: Path) -> str:
    assets = (base / ASSETS).resolve()
    return IMMUTABLE if assets in file.parents else NEVER_STORED


def mount_spa(app: FastAPI, static_root: Path | None) -> None:
    """Serve the bundle at ``static_root``, after every router and only if there is one.

    Called last on purpose: the fallback matches any path, so anything that is a route has to
    have been registered already.

    A configured directory with no ``index.html`` in it raises here rather than at the first
    request. The setting is written by the image that builds the bundle, so a missing index
    means the image was built wrong, and a process that started anyway would serve a working
    API behind a blank page -- the one failure this whole path exists to avoid, discovered by
    whoever opened the site rather than by the deploy.
    """
    if static_root is None:
        return
    root = static_root.resolve()
    index = root / INDEX
    if not index.is_file():
        raise RuntimeError(
            f"PP_STATIC_ROOT is {static_root}, which holds no {INDEX}. "
            "The image was built without the browser bundle."
        )

    async def serve(request: Request) -> Response:
        if request.method not in ("GET", "HEAD"):
            raise HTTPException(status_code=404)
        path = request.url.path
        if is_api_owned(path):
            raise HTTPException(status_code=404)
        file = _resolve(root, path)
        if file is not None:
            return FileResponse(file, headers={"Cache-Control": _cache_control(root, file)})
        # A path that names no file is a route inside the page -- a deep link, a reload, a
        # restored tab. The page is served and the address bar is left alone, which is what
        # makes `?case=<id>` reach the same durable case after a refresh.
        return FileResponse(index, headers={"Cache-Control": NEVER_STORED})

    app.router.routes.append(Route("/{spa_path:path}", serve, methods=SERVED_METHODS))
    logger.info("api.spa_mounted", static_root=str(root))
