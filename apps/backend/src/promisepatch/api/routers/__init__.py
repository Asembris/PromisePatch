"""Routers, one module per endpoint family."""

from promisepatch.api.routers.health import router as health_router

__all__ = ["health_router"]
