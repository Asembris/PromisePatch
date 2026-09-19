"""The scored boundary: a comparative ``SUR-1`` run cannot be taken without a passing preflight.

Before this, ``kind="scored"`` was a string. :func:`~scripts.sur1.driver.drive` accepted it,
:func:`~scripts.sur1.capture.open_run` wrote the directory, and the preflight in
:func:`~scripts.sur1.run.execute` was one composition away from being skipped -- by a test, by a
future module, by anybody calling the driver directly. The number that came out would have read
exactly like an authorised one.

So the gate is a capability now, and this file is where the gate is proved rather than described.

**Nothing here runs ``SUR-1``.** No arm is driven at a scenario, no model is reached, no AWS
resource is read and no comparative number is produced. Every binding is a value defined in this
file, every fingerprint is observed from those values, and every capability is minted from a
report this file wrote by hand. That forgery is deliberate and is itself part of the proof: the
only way to reach authority even from inside a test is through
:func:`~scripts.sur1.preflight.authorise`, and nothing in the shipped package can do what
:func:`granted` does here.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from scripts.sur1 import predeclaration
from scripts.sur1.authorisation import (
    AuthorisationError,
    RunFingerprint,
    ScoredAuthorisation,
    arm_identity,
    binding_identity,
    observe,
)
from scripts.sur1.capture import CaptureError, open_run
from scripts.sur1.doubles import ScriptedModel, StubArm, SyntheticWorld
from scripts.sur1.frozen import PUBLISHED_MANIFEST_SHA, Contract
from scripts.sur1.manifest import RunManifest, utc_now
from scripts.sur1.preflight import (
    REQUIRED_CHECKS,
    SCORED,
    Check,
    PreflightRefusedError,
    PreflightReport,
    authorise,
    preflight,
)

SUR1 = Path(__file__).resolve().parents[1] / "sur1"

CONTRACT = Contract.load()


# ------------------------------------------------------------------ values, not bindings


@dataclass(frozen=True)
class DeclaredReal:
    """An object that says it is a real binding. Reaches nothing, and is never driven.

    It exists because the interesting failure is not "a double was refused by the preflight" --
    that was already true -- but "a capability minted against something declaring itself real
    cannot be spent on something that does not". Proving that needs two fingerprints which
    differ only in what the objects say about themselves.
    """

    name: str
    binding_kind: str = "real"

    def identity(self) -> Mapping[str, Any]:
        return {"bound_to": self.name, "host": "127.0.0.1"}


def report(
    *, kind: str = SCORED, passed: bool = True, names: Sequence[str] = REQUIRED_CHECKS
) -> PreflightReport:
    """A preflight report written by hand, so this file can mint without a stack or an account."""
    return PreflightReport(
        kind=kind, checks=tuple(Check(name, passed, "synthetic") for name in names)
    )


def fingerprint(
    *,
    run_id: str = "boundary-run",
    root: Path,
    world: object | None = None,
    arms: Sequence[object] = (),
    kind: str = SCORED,
) -> RunFingerprint:
    return observe(
        kind=kind,
        run_id=run_id,
        root=root,
        scenarios=("C01",),
        world=world if world is not None else DeclaredReal("world"),
        arms=arms or (DeclaredReal("arm"),),
        classifier=predeclaration.asserts_change,
    )


def granted(**overrides: Any) -> ScoredAuthorisation:
    return authorise(report(), fingerprint(**overrides))


# -------------------------------------------------------------- a capability is not built


def test_a_capability_cannot_be_constructed(tmp_path: Path) -> None:
    """The initialiser refuses every caller that is not this module's own minting function."""
    with pytest.raises(AuthorisationError, match="is not constructed"):
        ScoredAuthorisation(object(), fingerprint(root=tmp_path), "")


def test_only_a_preflight_report_mints(tmp_path: Path) -> None:
    """An object shaped like a report is not a report. The check is by type, not by duck."""

    @dataclass(frozen=True)
    class LooksLikeOne:
        kind: str = SCORED
        passed: bool = True
        checks: tuple[Check, ...] = ()

    with pytest.raises(AuthorisationError, match="not from LooksLikeOne"):
        authorise(LooksLikeOne(), fingerprint(root=tmp_path))  # type: ignore[arg-type]


def test_a_failed_preflight_cannot_mint(tmp_path: Path) -> None:
    with pytest.raises(PreflightRefusedError, match="cannot be authorised"):
        authorise(report(passed=False), fingerprint(root=tmp_path))


def test_one_failed_check_among_many_cannot_mint(tmp_path: Path) -> None:
    """Every check, not most of them. A run refused on one question is a refused run."""
    checks = tuple(Check(name, name != "real_bindings", "synthetic") for name in REQUIRED_CHECKS)
    with pytest.raises(PreflightRefusedError, match="real_bindings"):
        authorise(PreflightReport(kind=SCORED, checks=checks), fingerprint(root=tmp_path))


def test_a_partial_report_cannot_mint(tmp_path: Path) -> None:
    """A report holding one passing check is not a preflight, however cheerful it is."""
    with pytest.raises(AuthorisationError, match="did not ask every question"):
        authorise(report(names=("frozen_identities",)), fingerprint(root=tmp_path))


def test_a_development_preflight_cannot_mint(tmp_path: Path) -> None:
    with pytest.raises(AuthorisationError, match="only a scored preflight"):
        authorise(report(kind="development"), fingerprint(root=tmp_path))
    with pytest.raises(AuthorisationError, match="only a scored preflight"):
        authorise(report(), fingerprint(root=tmp_path, kind="development"))


def test_the_required_checks_are_the_questions_the_preflight_actually_asks(
    tmp_path: Path,
) -> None:
    """The constant cannot drift away from the preflight, so a new check cannot be skipped.

    If a twelfth check is added and this list is not, this fails -- which is the point. A
    capability minted from a report that never asked the new question would be authority for a
    run nobody checked in the new way.
    """
    from scripts.sur1.bindings.config import BindingConfig

    asked = preflight(
        kind="development",
        run_id="boundary-run",
        model=DeclaredReal("model"),
        world=DeclaredReal("world"),
        surface=DeclaredReal("surface"),
        config=BindingConfig.from_environment({}),
        scenarios=("C01",),
        root=tmp_path,
    )
    assert tuple(check.name for check in asked.checks) == REQUIRED_CHECKS


# ------------------------------------------------------- what the capability is bound to


def test_the_fingerprint_binds_every_frozen_identity(tmp_path: Path) -> None:
    """Hashes, not descriptions. Each of these moving changes the digest the capability holds."""
    observed = fingerprint(root=tmp_path)

    assert observed.manifest_sha == PUBLISHED_MANIFEST_SHA
    assert observed.manifest_sha == CONTRACT.identity.manifest_sha
    assert observed.baseline_prompt_sha == CONTRACT.identity.baseline_prompt_sha
    assert observed.scorer_version == CONTRACT.identity.scorer_version
    assert observed.benchmark_id == CONTRACT.identity.benchmark_id
    assert observed.predeclaration_sha == predeclaration.PREDECLARATION_SHA
    assert observed.classifier_rule.endswith(".asserts_change")
    assert dict(observed.model_configuration)["model_id"] == CONTRACT.model_configuration.model_id


def test_the_fingerprint_binds_the_world_program_freeze(tmp_path: Path) -> None:
    from scripts.sur1.bindings.declaration import implementation_sha, published

    observed = fingerprint(root=tmp_path)
    assert observed.world_program_sha == implementation_sha()
    assert observed.world_program_sha == published()["implementation_sha"]


def test_the_fingerprint_carries_no_credential(tmp_path: Path) -> None:
    """A digest of it may be reported, so what it is made of has to be addresses and names."""
    payload = granted(root=tmp_path).as_payload()

    assert set(payload) == {"run_id", "run_digest", "preflight_digest", "claimed"}
    assert payload["run_digest"] != payload["preflight_digest"]
    assert len(payload["run_digest"]) == 64


@pytest.mark.parametrize(
    "moved",
    [
        {"run_id": "a-different-run"},
        {"root": "/somewhere/else"},
        {"scenarios": ("C02",)},
        {"manifest_sha": "0" * 64},
        {"baseline_prompt_sha": "0" * 64},
        {"scorer_version": "9.9.9"},
        {"driver_version": "9.9.9"},
        {"predeclaration_sha": "0" * 64},
        {"classifier_rule": "somewhere.else"},
        {"world_program_sha": "0" * 64},
        {"model_configuration": (("model_id", "some-other-model"),)},
        {"world": ("kind=none", "identity=absent")},
        {"arms": (("label=BASELINE", "type=tests.Forged"),)},
    ],
)
def test_one_moved_input_invalidates_the_capability(tmp_path: Path, moved: dict[str, Any]) -> None:
    """Whatever changed between the preflight and the run, the capability stops fitting it."""
    authorisation = granted(root=tmp_path)
    with pytest.raises(AuthorisationError, match="not the run the preflight authorised"):
        authorisation.claim(replace(fingerprint(root=tmp_path), **moved))
    assert not authorisation.claimed


def test_a_matching_fingerprint_is_claimed_exactly_once(tmp_path: Path) -> None:
    authorisation = granted(root=tmp_path)
    authorisation.claim(fingerprint(root=tmp_path))
    assert authorisation.claimed

    with pytest.raises(AuthorisationError, match="already been claimed"):
        authorisation.claim(fingerprint(root=tmp_path))


def test_a_refused_claim_does_not_spend_the_capability(tmp_path: Path) -> None:
    """A run refused for the wrong run id has not consumed the preflight that authorised it."""
    authorisation = granted(root=tmp_path)
    with pytest.raises(AuthorisationError):
        authorisation.claim(fingerprint(root=tmp_path, run_id="not-this-one"))
    authorisation.claim(fingerprint(root=tmp_path))
    assert authorisation.claimed


# --------------------------------------------------------------- a stand-in is not a binding


def test_a_capability_minted_against_a_real_world_cannot_drive_a_double(tmp_path: Path) -> None:
    authorisation = granted(root=tmp_path)
    with pytest.raises(AuthorisationError, match="world:"):
        authorisation.claim(fingerprint(root=tmp_path, world=SyntheticWorld()))


def test_the_same_arm_holding_a_scripted_model_fingerprints_differently() -> None:
    """The failure a label alone would hide: one class, one label, two different models.

    ``BASELINE`` is arm A whichever object is under it. What separates the arm that would call
    Bedrock from the one replaying a list in a test file is the binding it holds, so that is
    what the fingerprint reaches through to.
    """
    from scripts.sur1.adapters import BaselineArm

    real = BaselineArm(model=DeclaredReal("bedrock"))  # type: ignore[arg-type]
    scripted = BaselineArm(model=ScriptedModel(replies=[]))

    assert arm_identity(real)[0] == arm_identity(scripted)[0] == "label=BASELINE"
    assert arm_identity(real)[1] == arm_identity(scripted)[1]
    assert arm_identity(real) != arm_identity(scripted)
    assert "kind=none" in "|".join(binding_identity(ScriptedModel(replies=[])))
    assert "kind=real" in "|".join(binding_identity(DeclaredReal("bedrock")))


def test_a_stub_arm_fingerprints_as_the_class_it_is() -> None:
    assert "type=scripts.sur1.doubles.StubArm" in arm_identity(
        StubArm(label="BASELINE", outcomes=[])
    )


def test_a_stand_in_declares_no_binding_kind_and_that_is_the_difference() -> None:
    assert binding_identity(SyntheticWorld())[0] == "kind=none"
    assert binding_identity(None) == ("absent",)


# ------------------------------------------------------- the capture layer asks for it too


def scored_manifest(run_id: str = "boundary-run") -> RunManifest:
    return RunManifest(
        run_id=run_id,
        kind=SCORED,
        identity=CONTRACT.identity,
        model_configuration=CONTRACT.model_configuration,
        ceilings=CONTRACT.ceilings,
        read_tools=CONTRACT.read_tools,
        write_tools=CONTRACT.write_tools,
        command=("pytest",),
        started_at=utc_now(),
        implementation_sha="0" * 40,
        working_tree_dirty=True,
    )


def test_a_scored_directory_is_not_opened_without_a_capability(tmp_path: Path) -> None:
    """The one function that creates ``run.json`` and the token map asks for authority too.

    This is the bypass that would survive a gate living only in the driver: a caller reaching
    past :func:`~scripts.sur1.driver.drive` straight to the capture layer.
    """
    with pytest.raises(CaptureError, match="only under a scored authorisation"):
        open_run(scored_manifest(), labels=["HARNESS-A"], root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_scored_directory_refuses_a_capability_about_another_run(tmp_path: Path) -> None:
    with pytest.raises(CaptureError, match="is not about"):
        open_run(
            scored_manifest("some-other-run"),
            labels=["HARNESS-A"],
            root=tmp_path,
            authorisation=granted(root=tmp_path),
        )
    assert list(tmp_path.iterdir()) == []


def test_a_scored_directory_refuses_a_capability_about_another_root(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(CaptureError, match="is not about"):
        open_run(
            scored_manifest(),
            labels=["HARNESS-A"],
            root=elsewhere,
            authorisation=granted(root=tmp_path),
        )
    assert list(elsewhere.iterdir()) == []


def test_a_development_directory_still_opens_with_no_capability(tmp_path: Path) -> None:
    """The gate is on the scored layout. Development is what the harness is usable during."""
    manifest = replace(scored_manifest(), kind="development")
    directory, tokens = open_run(manifest, labels=["HARNESS-A"], root=tmp_path)

    assert directory.run_file.exists()
    assert set(tokens) == {"HARNESS-A"}


# ---------------------------------------------------------- no second door, read from source


SANCTIONED: dict[str, str] = {
    "RunManifest": "driver",
    "open_run": "driver",
    "write_attempt": "driver",
    "write_verdict": "driver",
    "write_driver_verdict": "driver",
    "_grant": "preflight",
    "ScoredAuthorisation": "authorisation",
}
"""Who may call the things that produce a scored artefact or the authority to write one.

Read from the syntax rather than from a convention, exactly as
:func:`~scripts.sur1.preflight.blinding` reads the scorer's import surface. A second module that
started constructing run manifests, opening run directories or minting capabilities would be a
second scored-artefact path, and the whole value of the boundary is that there is one.
"""


def callers_of(name: str) -> set[str]:
    found: set[str] = set()
    for path in sorted(SUR1.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            identifier = (
                called.id
                if isinstance(called, ast.Name)
                else called.attr
                if isinstance(called, ast.Attribute)
                else None
            )
            if identifier == name:
                found.add(path.stem)
    return found


@pytest.mark.parametrize(("name", "module"), sorted(SANCTIONED.items()))
def test_one_module_calls_each_scored_artefact_path(name: str, module: str) -> None:
    assert callers_of(name) == {module}, (
        f"{name} is called from {sorted(callers_of(name))}; the scored path has one door and "
        f"that door is {module}.py"
    )


def test_nothing_in_the_package_can_mint_without_the_report_check() -> None:
    """``_grant`` holds the sentinel and ``authorise`` holds the report check. Neither is both."""
    grant_source = (SUR1 / "authorisation.py").read_text(encoding="utf-8")
    mint_source = (SUR1 / "preflight.py").read_text(encoding="utf-8")

    assert "_GRANT: Final = object()" in grant_source
    assert "_GRANT" not in mint_source
    assert "REQUIRED_CHECKS" in mint_source


# --------------------------------------------------------------- the freeze did not move


def test_the_boundary_moved_no_frozen_identity() -> None:
    """Everything this slice touched is harness code. The published hashes are unchanged."""
    from scripts.sur1.bindings.declaration import differences

    assert CONTRACT.identity.manifest_sha == PUBLISHED_MANIFEST_SHA
    assert predeclaration.identity_sha() == predeclaration.PREDECLARATION_SHA
    assert differences() == ()
