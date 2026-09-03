"""Password verification, and the work done deliberately on a username that does not exist.

Argon2 is the hash, with the library's own parameters -- the same ones ``pp reset-demo-state``
used to write the stored hashes, so verification cost matches by construction rather than by a
number copied into two places.

The unusual part is :func:`verify_unknown_user`. Answering an unknown username immediately and
a known one after ~50 ms of hashing turns login into a user directory: an attacker learns who
exists without ever guessing a password. So an unknown username is verified against a real
Argon2 hash of a value nobody holds. The answer is always no, and it costs what a no costs.
"""

from __future__ import annotations

import secrets
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher: Final = PasswordHasher()

DUMMY_HASH: Final = _hasher.hash(secrets.token_urlsafe(32))
"""A real hash of a value that was discarded the moment it was hashed.

Computed once at import, from fresh randomness: nothing in the source, the environment or the
database can be checked against it, so the only thing it can do is take the right amount of
time to say no.
"""


def hash_password(password: str) -> str:
    """Hash a password for storage. Used by the fixture seeder, never by a request."""
    return _hasher.hash(password)


def verify(password_hash: str, password: str) -> bool:
    """Whether ``password`` matches ``password_hash``.

    Every failure mode -- wrong password, malformed stored hash, unsupported parameters -- is
    the same answer. A stored hash the library cannot parse is a data problem, and treating it
    as "no" is the only safe reading of it.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_unknown_user(password: str) -> bool:
    """Spend a verification on a username that does not exist, then answer no.

    Returns ``False`` unconditionally. The work is the point.
    """
    verify(DUMMY_HASH, password)
    return False
