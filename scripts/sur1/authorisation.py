"""The capability a scored ``SUR-1`` run is driven under, and the only thing that mints one.

The harness already had a preflight that asked every question and refused a scored run which
failed one. What it did not have was a reason the driver could not simply be called around it:
:func:`~scripts.sur1.driver.drive` took ``kind="scored"`` as a string, and a caller who never
ran a preflight -- a test, a notebook, a future module, a session in a hurry -- got a directory
full of scored artefacts indistinguishable from an authorised run's. The preflight was a
document about how a run ought to be started rather than a control on starting one.

So the preflight now hands back a **capability**, and the scored path asks for the capability
rather than for a promise that one exists.

**It binds the inputs that were checked, not the fact that checking happened.** A
:class:`RunFingerprint` is observed from the live objects -- the frozen identities recomputed
from disk, the model configuration, the declared ``asserts_change`` rule, the world-program
freeze, the world binding's own declared kind and identity, every arm's type and the bindings
reachable through it, the run id, the output root and the selected scenarios. The capability
carries that fingerprint's digest. At drive time the same fingerprint is observed again from
the objects actually handed to the driver, and one differing field refuses the run. Minting a
capability against real bindings and then driving stubs fails, because stubs fingerprint
differently.

**It is single-use.** :meth:`ScoredAuthorisation.claim` refuses a second claim. A scored run is
one purchase, and a capability that authorised two of them would let a session which disliked
the first buy a second under the first one's preflight. Resuming is unaffected: a resume is a
fresh invocation, which runs a fresh preflight and mints a fresh capability for the same run id.

**It cannot be constructed.** The initialiser refuses every caller that does not hold this
module's own sentinel, so ``ScoredAuthorisation(fingerprint)`` raises. The one function holding
the sentinel is module-private, and :func:`~scripts.sur1.preflight.authorise` is the only public
way to reach it -- and that refuses a report which is not a passing scored preflight naming
every required check.

**This module is a leaf.** It imports nothing from :mod:`scripts.sur1` at module scope, so the
capture layer, the driver and the preflight can all depend on it without a cycle. What it needs
from the contract it imports inside the function that needs it.

**Nothing here has authorised a run.** No capability has been minted against real bindings, and
no scored ``SUR-1`` attempt exists.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

SCORED: Final = "scored"
"""Restated rather than imported, because importing the preflight here would make a cycle."""

_GRANT: Final = object()
"""The sentinel :func:`_grant` holds. Nothing else in this repository is handed it."""

MAX_ARM_DEPTH: Final = 4
"""How far into an arm's composed bindings a fingerprint looks. Arm C is one level deep."""


class AuthorisationError(RuntimeError):
    """A scored run was asked for without a capability, or with one that does not fit it."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest_of(value: Any) -> str:
    """One hashing rule for every digest here, computed as the frozen reader computes its own."""
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def binding_identity(candidate: object) -> tuple[str, ...]:
    """What an object says it is bound to, or the fact that it says nothing.

    Read off the object rather than from its type. A double that reaches nothing carries no
    ``binding_kind`` and usually no ``identity``, and it is recorded here as declaring neither
    -- which is a different fingerprint from a real binding's, and that difference is the whole
    mechanism by which a stub cannot be driven under a capability minted against a real one.
    """
    if candidate is None:
        return ("absent",)
    kind = getattr(candidate, "binding_kind", None)
    rendered = [f"kind={kind if kind is not None else 'none'}"]
    identity = getattr(candidate, "identity", None)
    if not callable(identity):
        rendered.append("identity=absent")
        return tuple(rendered)
    try:
        declared: Mapping[str, Any] = identity()
    except Exception as failure:  # an identity that cannot be read is a fact, not a crash
        rendered.append(f"identity=unreadable:{type(failure).__name__}")
        return tuple(rendered)
    rendered.extend(f"{key}={declared[key]!s}" for key in sorted(declared))
    return tuple(rendered)


def arm_identity(arm: object, *, depth: int = MAX_ARM_DEPTH) -> tuple[str, ...]:
    """An arm's label, its concrete type, and the bindings reachable through it.

    The type is in here because a label is a string an adapter chooses. Two objects both
    labelled ``BASELINE`` -- one holding a Bedrock client, one a scripted list of replies --
    have the same label, and must not have the same fingerprint.
    """
    kind = type(arm)
    rendered = [
        f"label={getattr(arm, 'label', '?')!s}",
        f"type={kind.__module__}.{kind.__qualname__}",
    ]
    if depth <= 0:
        return tuple(rendered)
    for attribute in ("model", "surface", "world"):
        held = getattr(arm, attribute, None)
        if held is not None:
            rendered.append(f"{attribute}={'|'.join(binding_identity(held))}")
    inner = getattr(arm, "inner", None)
    if inner is not None:
        rendered.append(f"inner={'|'.join(arm_identity(inner, depth=depth - 1))}")
    return tuple(rendered)


def classifier_rule(classifier: object) -> str:
    """Which ``asserts_change`` rule this is, named from the function rather than from a flag."""
    module = getattr(classifier, "__module__", "?")
    qualified = getattr(classifier, "__qualname__", repr(classifier))
    return f"{module}.{qualified}"


@dataclass(frozen=True, slots=True)
class RunFingerprint:
    """Every input a scored preflight checked, reduced to values that compare exactly.

    Nothing here is a credential. The binding identities name addresses, model ids and regions,
    exactly as :meth:`~scripts.sur1.bindings.config.BindingConfig.as_payload` does, which is why
    a fingerprint may be digested and reported without a capture ever holding a secret.
    """

    kind: str
    run_id: str
    root: str
    scenarios: tuple[str, ...]
    benchmark_id: str
    manifest_sha: str
    baseline_prompt_sha: str
    scorer_version: str
    driver_version: str
    model_configuration: tuple[tuple[str, str], ...]
    predeclaration_sha: str
    classifier_rule: str
    world_program_sha: str
    world: tuple[str, ...]
    arms: tuple[tuple[str, ...], ...]

    def digest(self) -> str:
        return digest_of(asdict(self))

    def differences(self, other: RunFingerprint) -> tuple[str, ...]:
        """Every field on which these are not the same run, named one at a time.

        Named rather than counted, for the reason :func:`~scripts.sur1.preflight.require` gives
        about its own refusal: a caller fixing a refused run wants to be told what moved.
        """
        mine, theirs = asdict(self), asdict(other)
        return tuple(
            f"{field}: authorised {mine[field]!r}, now {theirs[field]!r}"
            for field in mine
            if mine[field] != theirs[field]
        )


def observe(
    *,
    kind: str,
    run_id: str,
    root: Path,
    scenarios: Sequence[str],
    world: object,
    arms: Sequence[object],
    classifier: object,
) -> RunFingerprint:
    """Fingerprint the run these live objects would be, recomputing every frozen identity.

    Called twice: once by :func:`~scripts.sur1.run.execute` when the preflight passed, and once
    by :func:`~scripts.sur1.driver.drive` against whatever it was actually handed. The second
    call is what makes the capability a binding rather than a receipt, so it reads the objects
    in front of it and never a value a caller passed alongside them.

    The contract is loaded here rather than accepted as an argument. A fingerprint built from a
    contract somebody else read would pin whatever that reader saw, and the point of recomputing
    is that a manifest edited between the preflight and the drive changes the digest.
    """
    from scripts.sur1 import DRIVER_VERSION, predeclaration
    from scripts.sur1.bindings.declaration import implementation_sha
    from scripts.sur1.frozen import Contract

    contract = Contract.load()
    selected = tuple(scenarios) or tuple(contract.scenario_ids)
    configured = contract.model_configuration.as_payload()
    return RunFingerprint(
        kind=kind,
        run_id=run_id,
        root=str(Path(root).resolve()),
        scenarios=selected,
        benchmark_id=contract.identity.benchmark_id,
        manifest_sha=contract.identity.manifest_sha,
        baseline_prompt_sha=contract.identity.baseline_prompt_sha,
        scorer_version=contract.identity.scorer_version,
        driver_version=DRIVER_VERSION,
        model_configuration=tuple((key, str(configured[key])) for key in sorted(configured)),
        predeclaration_sha=predeclaration.identity_sha(),
        classifier_rule=classifier_rule(classifier),
        world_program_sha=implementation_sha(),
        world=binding_identity(world),
        arms=tuple(arm_identity(arm) for arm in arms),
    )


class ScoredAuthorisation:
    """One scored run, authorised once, for exactly the inputs a preflight was asked about.

    Deliberately not a dataclass and deliberately not constructible: ``ScoredAuthorisation(...)``
    raises, because a capability anybody may build is a naming convention. It is minted by
    :func:`~scripts.sur1.preflight.authorise` and by nothing else.
    """

    __slots__ = ("_claimed", "_digest", "_fingerprint", "_preflight_digest")

    def __init__(self, grant: object, fingerprint: RunFingerprint, preflight_digest: str) -> None:
        if grant is not _GRANT:
            raise AuthorisationError(
                "a scored authorisation is not constructed; it is minted by a passing scored "
                "preflight through scripts.sur1.preflight.authorise and by nothing else"
            )
        self._fingerprint = fingerprint
        self._digest = fingerprint.digest()
        self._preflight_digest = preflight_digest
        self._claimed = False

    def __repr__(self) -> str:
        state = "claimed" if self._claimed else "unclaimed"
        return f"<ScoredAuthorisation {self._fingerprint.run_id} {self._digest[:8]} {state}>"

    @property
    def run_id(self) -> str:
        return self._fingerprint.run_id

    @property
    def digest(self) -> str:
        return self._digest

    @property
    def preflight_digest(self) -> str:
        """The digest of the report that minted this. Names the preflight, holds no secret."""
        return self._preflight_digest

    @property
    def claimed(self) -> bool:
        return self._claimed

    def authorises_run(self, *, run_id: str, kind: str, root: Path) -> bool:
        """Whether this capability is about that output. Asked by the capture layer, no spend.

        Narrower than :meth:`claim` on purpose: :func:`~scripts.sur1.capture.open_run` is handed
        a manifest and a root and can compare only those, and asking it to re-observe the world
        would give the capture layer a reason to import the bindings.
        """
        return (
            kind == self._fingerprint.kind
            and run_id == self._fingerprint.run_id
            and str(Path(root).resolve()) == self._fingerprint.root
        )

    def claim(self, fingerprint: RunFingerprint) -> None:
        """Spend this capability on one run, or refuse and say which input moved."""
        if self._claimed:
            raise AuthorisationError(
                f"the scored authorisation for {self._fingerprint.run_id} has already been "
                "claimed; one preflight authorises one scored run, and a resume runs its own"
            )
        moved = self._fingerprint.differences(fingerprint)
        if moved:
            raise AuthorisationError(
                "the run being driven is not the run the preflight authorised:\n"
                + "\n".join(f"  - {difference}" for difference in moved)
            )
        self._claimed = True

    def as_payload(self) -> dict[str, Any]:
        """Two digests and a run id. Reportable, and holds nothing a capture may not carry."""
        return {
            "run_id": self._fingerprint.run_id,
            "run_digest": self._digest,
            "preflight_digest": self._preflight_digest,
            "claimed": self._claimed,
        }


def _grant(fingerprint: RunFingerprint, preflight_digest: str) -> ScoredAuthorisation:
    """Mint a capability. Module-private, and called from exactly one place in this repository.

    That place is :func:`~scripts.sur1.preflight.authorise`, which is where the report is checked
    to be a passing scored preflight that asked every required question. Keeping the sentinel
    here and the report check there is what stops either of them from being the whole gate.
    """
    return ScoredAuthorisation(_GRANT, fingerprint, preflight_digest)


__all__ = [
    "MAX_ARM_DEPTH",
    "SCORED",
    "AuthorisationError",
    "RunFingerprint",
    "ScoredAuthorisation",
    "arm_identity",
    "binding_identity",
    "classifier_rule",
    "digest_of",
    "observe",
]
