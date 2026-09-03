"""The session cookie: what it carries, how it is signed, and the flags it is set with.

The cookie holds a session id and a MAC over that id. It is not a token containing claims:
authority lives in a database row, and the cookie is only the name of that row. The signature
therefore does one job -- it stops us spending a database round trip on an id a browser
invented -- and revocation, expiry and identity all remain server-side facts.

The flags are set once, here, so no route can accidentally issue a weaker cookie:

* ``HttpOnly`` on the session cookie: script cannot read the session name at all.
* ``SameSite=Lax``: the cookie is not attached to cross-site sub-requests, which removes most
  of the CSRF surface before the token check even runs, while keeping ordinary navigation
  working.
* ``Secure`` outside local development, where the demo is served over plain HTTP on loopback
  and a secure-only cookie would simply never arrive.

The CSRF cookie is the deliberate exception to ``HttpOnly``: the browser client has to read it
to echo it back in a header. Its value is worthless on its own -- the server compares the
header against the session row, not against the cookie.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Final
from uuid import UUID

from starlette.responses import Response

from promisepatch.config import Settings

SESSION_COOKIE: Final = "pp_session"
CSRF_COOKIE: Final = "pp_csrf"
CSRF_HEADER: Final = "X-CSRF-Token"
COOKIE_PATH: Final = "/"
SAME_SITE: Final = "lax"


def _mac(session_id: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def sign(session_id: UUID, secret: str) -> str:
    """The cookie value for a session: ``<id>.<mac>``."""
    identifier = str(session_id)
    return f"{identifier}.{_mac(identifier, secret)}"


def unsign(value: str, secret: str) -> UUID | None:
    """The session id in a cookie value, or ``None`` if it was not signed by us.

    ``compare_digest`` rather than ``==`` so the comparison does not leak the correct MAC one
    character at a time, and a malformed value is rejected as unsigned rather than raising.
    """
    identifier, separator, mac = value.partition(".")
    if not separator or not identifier or not mac:
        return None
    if not hmac.compare_digest(mac, _mac(identifier, secret)):
        return None
    try:
        return UUID(identifier)
    except ValueError:
        return None


def set_session_cookies(
    response: Response, *, cookie_value: str, csrf_token: str, max_age: int, settings: Settings
) -> None:
    """Attach both cookies with the flags this deployment requires."""
    secure = not settings.is_local
    response.set_cookie(
        SESSION_COOKIE,
        cookie_value,
        max_age=max_age,
        path=COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite=SAME_SITE,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        path=COOKIE_PATH,
        # Readable on purpose: the client has to echo this value in a header, and the server
        # validates that header against the session row rather than against this cookie.
        httponly=False,
        secure=secure,
        samesite=SAME_SITE,
    )


def clear_session_cookies(response: Response, *, settings: Settings) -> None:
    """Remove both cookies. Paired with revoking the row, never a substitute for it."""
    secure = not settings.is_local
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            name,
            path=COOKIE_PATH,
            httponly=name == SESSION_COOKIE,
            secure=secure,
            samesite=SAME_SITE,
        )
