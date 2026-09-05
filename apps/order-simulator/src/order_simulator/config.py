"""The simulator's own configuration, under its own prefix.

``OS_`` rather than ``PP_``, because this is a different application. It shares no environment
file with PromisePatch, holds none of PromisePatch's credentials, and could not reach
PromisePatch's database if it wanted to: the only thing it knows about the other side is a URL
to post events at and the secret it signs them with.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything the External Order System simulator reads from its environment."""

    model_config = SettingsConfigDict(
        env_prefix="OS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    database_path: Path = Path("order-simulator.sqlite3")
    """Where this system keeps its orders. Its own file, on its own volume.

    Sharing storage with PromisePatch would make every claim in the demo untrue at once: the
    whole point of Proof A is that a change made here reaches PromisePatch through an
    integration contract rather than through a table they both write.
    """

    log_level: str = "info"

    webhook_url: str | None = None
    """Where committed order events are delivered. Unset means events queue and wait.

    Deliberately not fatal when absent: an order system whose subscriber is unreachable is
    still a working order system, and its events stay durable until delivery succeeds.
    """

    webhook_secret: SecretStr | None = None
    """The shared secret every outbound event is signed with.

    A :class:`~pydantic.SecretStr` so it cannot reach a log line or a traceback by accident.
    Deliveries are refused rather than sent unsigned when this is missing -- an unauthenticated
    webhook is one the receiver is right to reject, and sending it anyway would only make the
    failure harder to read.
    """

    webhook_timeout_seconds: float = 10.0
    webhook_max_backoff_seconds: float = 30.0
    """How long the delivery loop retreats between attempts at most.

    There is no attempt bound. A committed order event is a fact about this system's own state,
    and giving up on telling somebody about it would leave the two systems permanently
    disagreeing with no record that they do.
    """

    def require_webhook_secret(self) -> str:
        if self.webhook_secret is None:
            raise RuntimeError(
                "OS_WEBHOOK_SECRET is not configured; set it to the same value as "
                "PP_ORDER_SYSTEM_WEBHOOK_SECRET before delivering events."
            )
        return self.webhook_secret.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Tests construct :class:`Settings` directly instead."""
    return Settings()
