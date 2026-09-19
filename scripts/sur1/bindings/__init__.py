"""The concrete bindings: the model, the world and PromisePatch's own surfaces.

:mod:`scripts.sur1` defines three ports -- ``ModelClient``, ``ScenarioWorld`` and
``WorkerSurface`` -- and deliberately constructs none of them, because a harness that built its
own Bedrock client is a harness that can call one by accident. This subpackage is where they are
built, and it is separate for that reason: importing :mod:`scripts.sur1.driver` still reaches no
provider, no order system and no database.

**A binding says out loud that it is real.** Every object here carries
:attr:`Binding.binding_kind` set to ``"real"`` and an :meth:`Binding.identity` that names what it
is bound to. The doubles in :mod:`scripts.sur1.doubles` carry neither, which is how
:mod:`scripts.sur1.preflight` refuses a scored run driven by a stand-in rather than trusting the
caller to have passed the right object.

**Arm actions and fixture construction are different modules on purpose.**
:mod:`~scripts.sur1.bindings.promisepatch` holds only surfaces a worker actually uses -- the MCP
tools and the workspace a person signs in to. :mod:`~scripts.sur1.bindings.setup` holds the
fixture construction and the receiver reads, which are the harness's own privileges and are
never reachable from an arm: an :class:`~scripts.sur1.arms.AttemptRequest` carries a world and a
budget, and nothing in it exposes a setup helper.

**These bindings have carried one scored run**, ``20260919T2020Z-scored``, which is published
inconclusive and unaltered. See ``docs/sur1-first-scored-run-defect.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

REAL: str = "real"
"""What a binding that reaches a real system reports as its kind. A double reports nothing."""


@dataclass(frozen=True, slots=True)
class Probe:
    """Whether one source answered, recorded rather than assumed.

    A probe is a read and never a write. It exists so the preflight can say *this receiver is
    reachable* as an observation rather than as a hope, and so that a scored run refuses before
    an attempt is bought rather than voiding nine scenarios afterwards.
    """

    source: str
    reachable: bool
    detail: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {"source": self.source, "reachable": self.reachable, "detail": self.detail}


@runtime_checkable
class Binding(Protocol):
    """What every real binding answers about itself, and what a double cannot fake by accident.

    ``binding_kind`` is a value rather than a method so that a preflight can read it off an
    object it must not otherwise touch, and ``identity`` returns names and addresses only --
    never a credential, because a run manifest carrying one would be committed.
    """

    binding_kind: str

    def identity(self) -> Mapping[str, Any]: ...

    def probe(self) -> Probe: ...


def is_real(candidate: object) -> bool:
    """Whether this object declares itself a real binding.

    Deliberately not ``isinstance(candidate, Binding)``: a runtime-checkable protocol only
    checks that the members exist, and a double with a ``binding_kind`` attribute of some other
    value would satisfy it. The value is what is checked.
    """
    return getattr(candidate, "binding_kind", None) == REAL


__all__ = ["REAL", "Binding", "Probe", "is_real"]
