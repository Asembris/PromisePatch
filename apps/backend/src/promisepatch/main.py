"""The ``api`` entrypoint: a FastAPI application factory.

``create_app`` takes its settings as an argument so tests can build an app for a given
environment without touching ``os.environ``. The module-level ``app`` is what uvicorn imports
in production and under ``--reload``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from promisepatch import __version__
from promisepatch.api.errors import register_error_handlers
from promisepatch.api.middleware import CorrelationIdMiddleware
from promisepatch.api.routers import auth_router, health_router
from promisepatch.config import Environment, Settings, get_settings
from promisepatch.db import RuntimeDatabase
from promisepatch.observability import configure_logging, get_logger

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application for the given settings."""
    resolved = settings or get_settings()
    configure_logging(resolved)
    boot_id = str(uuid4())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The engine is opened here rather than at import time so that building an application
        # is not itself an attempt to reach a database: tests, ``--help`` and a container whose
        # database is still starting all need ``create_app`` to succeed on its own.
        database = RuntimeDatabase.from_settings(resolved) if resolved.database_url else None
        app.state.database = database
        logger.info(
            "api.start",
            boot_id=boot_id,
            env=str(resolved.env),
            version=__version__,
            database_configured=database is not None,
        )
        try:
            yield
        finally:
            # Explicit disposal: a reload that left its pool behind would hold connections a
            # least-privileged role has a small budget of.
            if database is not None:
                await database.dispose()
            logger.info("api.stop", boot_id=boot_id)

    # Interactive docs are a development affordance, not a product surface: they are closed
    # in a deployed environment rather than left open behind an unauthenticated path.
    expose_docs = resolved.env is not Environment.AWS

    app = FastAPI(
        title="PromisePatch API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    app.state.boot_id = boot_id
    app.state.settings = resolved
    # Replaced by the real engine in ``lifespan``; declared here so a handler can read the
    # attribute unconditionally rather than guarding on whether startup has run.
    app.state.database = None

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origin_list),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )

    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    return app


app = create_app()
