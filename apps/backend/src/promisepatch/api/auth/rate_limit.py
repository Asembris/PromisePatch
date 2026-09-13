"""A small fixed-window limiter for the login endpoint.

Deliberately in-process and deliberately not distributed. This system runs one API process for
one bakery, and the threat it addresses is a script trying passwords, not a botnet. A Redis
dependency and a token-bucket cluster would be a platform this demo has no use for, and the
architecture's own note on rate limiting puts the real perimeter at the load balancer.

Time is injected rather than read, so the window is testable without sleeping.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

LOGIN_ATTEMPT_LIMIT: Final = 10
LOGIN_WINDOW: Final = timedelta(minutes=1)

DEMO_SESSION_LIMIT: Final = 20
DEMO_SESSION_WINDOW: Final = timedelta(minutes=1)
"""How often one client may be issued a scoped observer session.

Higher than the sign-in budget, which looks backwards until you notice they are counting
different things. A sign-in attempt is somebody guessing a password, and ten a minute is
generous for that. A demo session is somebody being shown the product, the endpoint takes no
credentials, and what it issues can read a case and change nothing -- so there is no secret
here to be guessed at and no authority to be accumulated.

The key is a client address, and several people watching the same demo are behind one of those:
a room, a conference network, a browser suite opening a context per test. A limit tuned for
password guessing would refuse the second half of the room. Twenty a minute still bounds
scripted churn, which is the only thing this is for.

Counted separately from sign-in so that neither can exhaust the other's allowance.
"""


@dataclass
class FixedWindowLimiter:
    """Counts recent attempts per key and refuses once the window is full."""

    limit: int
    window: timedelta
    _attempts: dict[str, deque[datetime]] = field(default_factory=dict, repr=False)

    def allow(self, key: str, now: datetime) -> bool:
        """Record an attempt for ``key`` and say whether it is within the limit."""
        seen = self._attempts.setdefault(key, deque())
        cutoff = now - self.window
        while seen and seen[0] <= cutoff:
            seen.popleft()
        if len(seen) >= self.limit:
            return False
        seen.append(now)
        return True

    def forget(self, key: str) -> None:
        """Drop a key's history. Called after a success, so one good login clears the count."""
        self._attempts.pop(key, None)

    def reset(self) -> None:
        """Forget every key. The process-wide limiter is shared, so a test suite needs this."""
        self._attempts.clear()


def login_limiter() -> FixedWindowLimiter:
    return FixedWindowLimiter(limit=LOGIN_ATTEMPT_LIMIT, window=LOGIN_WINDOW)


def demo_session_limiter() -> FixedWindowLimiter:
    return FixedWindowLimiter(limit=DEMO_SESSION_LIMIT, window=DEMO_SESSION_WINDOW)
