"""Who is holding a lease.

A worker identity has one job: to be different from every other worker that could be running
against the same database, including a *previous* instance of this same worker. That last part
is why a boot id is in it. A container that is killed and restarted keeps its hostname and can
be given back its process id; without something that changes across restarts, the new process
would match the fence of the dead one's claims and could complete work it never did.

Kept inside ``lease_owner``'s sixty-four characters, with the hostname truncated rather than
the boot id, because a truncated hostname is still a useful thing to read in a log and a
truncated boot id is a collision waiting to happen.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Final
from uuid import uuid4

MAX_LENGTH: Final = 64
"""``case_steps.lease_owner`` and ``outbox_messages.lease_owner`` are ``VARCHAR(64)``."""

HOSTNAME_LIMIT: Final = 32
BOOT_ID_LENGTH: Final = 8


@dataclass(frozen=True, slots=True)
class WorkerIdentity:
    """``host:pid:boot`` -- where the machine is, which process, and which life of it."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("a worker identity cannot be empty")
        if len(self.value) > MAX_LENGTH:
            raise ValueError(
                f"worker identity {self.value!r} exceeds the {MAX_LENGTH}-character lease column"
            )

    @classmethod
    def create(cls) -> WorkerIdentity:
        """Mint an identity for this process, now."""
        host = socket.gethostname()[:HOSTNAME_LIMIT] or "unknown"
        return cls(f"{host}:{os.getpid()}:{uuid4().hex[:BOOT_ID_LENGTH]}")

    def __str__(self) -> str:
        return self.value
