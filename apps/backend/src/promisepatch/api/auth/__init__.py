"""Authentication: passwords, server-side sessions, cookies and login rate limiting.

Lightweight by decision, not by omission (ARCHITECTURE_PLAN §21): two seeded logins, one
bakery, a session row per login and explicit attribution on every governed write. There is no
JWT, no OAuth, no identity provider, no registration and no password reset, because none of
those would make the demo's trust model stronger and each would add a surface to defend.
"""

from promisepatch.api.auth.cookies import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    clear_session_cookies,
    set_session_cookies,
    sign,
    unsign,
)
from promisepatch.api.auth.passwords import hash_password, verify, verify_unknown_user
from promisepatch.api.auth.rate_limit import FixedWindowLimiter, login_limiter
from promisepatch.api.auth.sessions import (
    SESSION_TTL,
    IssuedSession,
    Principal,
    create,
    find_worker,
    resolve,
    revoke,
)

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "SESSION_TTL",
    "FixedWindowLimiter",
    "IssuedSession",
    "Principal",
    "clear_session_cookies",
    "create",
    "find_worker",
    "hash_password",
    "login_limiter",
    "resolve",
    "revoke",
    "set_session_cookies",
    "sign",
    "unsign",
    "verify",
    "verify_unknown_user",
]
