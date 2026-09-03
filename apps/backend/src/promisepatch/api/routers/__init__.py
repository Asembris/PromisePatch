"""Routers, one module per endpoint family."""

from promisepatch.api.routers.auth import router as auth_router
from promisepatch.api.routers.health import router as health_router

__all__ = ["auth_router", "health_router"]
