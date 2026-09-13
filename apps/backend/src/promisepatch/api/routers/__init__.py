"""Routers, one module per endpoint family."""

from promisepatch.api.routers.auth import router as auth_router
from promisepatch.api.routers.cases import router as cases_router
from promisepatch.api.routers.conversation import router as conversation_router
from promisepatch.api.routers.events import router as events_router
from promisepatch.api.routers.health import router as health_router
from promisepatch.api.routers.integrations import router as integrations_router
from promisepatch.api.routers.intents import router as intents_router
from promisepatch.api.routers.promises import router as promises_router
from promisepatch.api.routers.resources import router as resources_router

__all__ = [
    "auth_router",
    "cases_router",
    "conversation_router",
    "events_router",
    "health_router",
    "integrations_router",
    "intents_router",
    "promises_router",
    "resources_router",
]
