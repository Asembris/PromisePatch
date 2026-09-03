"""The approval channel, in the two shapes the system needs it in.

The engine carries a customer's approval channel as one opaque string, because the only thing
it ever does with it is compare it to the identity a reply arrived from. The database splits
it into a kind and an address, because the consent protocol has to know *which* provider to
ask and the kind is a closed vocabulary the schema checks.

Neither shape is a lossy view of the other, and this module is the only place that knows how
to move between them. A codec written twice is a codec that eventually disagrees with itself,
and a customer whose channel decodes to a different address than it was stored with is a
customer whose consent cannot be matched to their reply.
"""

from __future__ import annotations

from typing import Final

from promisepatch.db.types import CHANNEL_KINDS

PREFIX_BY_KIND: Final[dict[str, str]] = {
    "telegram": "tg",
    "whatsapp": "wa",
    "console": "console",
}
"""Short prefix per channel kind. Every kind the schema permits has exactly one."""

KIND_BY_PREFIX: Final[dict[str, str]] = {
    prefix: kind for kind, prefix in sorted(PREFIX_BY_KIND.items())
}

SEPARATOR: Final = ":"


class UnknownChannelError(ValueError):
    """Raised when a channel string names a provider the schema has no vocabulary for."""


def split_channel(channel: str) -> tuple[str, str]:
    """``"tg:1001"`` to ``("telegram", "1001")``.

    The address is everything after the first separator, so an address that itself contains
    one survives the round trip intact.
    """
    prefix, separator, address = channel.partition(SEPARATOR)
    if not separator:
        raise UnknownChannelError(f"approval channel {channel!r} names no provider")
    kind = KIND_BY_PREFIX.get(prefix)
    if kind is None:
        raise UnknownChannelError(
            f"approval channel {channel!r} names an unknown provider {prefix!r}"
        )
    if not address:
        raise UnknownChannelError(f"approval channel {channel!r} carries no address")
    return kind, address


def join_channel(kind: str, address: str) -> str:
    """``("telegram", "1001")`` to ``"tg:1001"``."""
    prefix = PREFIX_BY_KIND.get(kind)
    if prefix is None:
        raise UnknownChannelError(f"unknown approval channel kind {kind!r}")
    return f"{prefix}{SEPARATOR}{address}"


def _check_vocabularies_agree() -> None:
    """Every kind the database accepts must be one this codec can write and read back."""
    if set(PREFIX_BY_KIND) != set(CHANNEL_KINDS):
        raise RuntimeError(
            "approval channel kinds and their prefixes have drifted apart: "
            f"{sorted(set(PREFIX_BY_KIND) ^ set(CHANNEL_KINDS))}"
        )
    if len(KIND_BY_PREFIX) != len(PREFIX_BY_KIND):
        raise RuntimeError("two channel kinds share one prefix")


_check_vocabularies_agree()
