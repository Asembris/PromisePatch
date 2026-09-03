"""Routers, one module per endpoint family."""

from promisepatch.api.routers.auth import router as auth_router
from promisepatch.api.routers.health import router as health_router
from promisepatch.api.routers.promises import router as promises_router
from promisepatch.api.routers.resources import router as resources_router

__all__ = ["auth_router", "health_router", "promises_router", "resources_router"]
