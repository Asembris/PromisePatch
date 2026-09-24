"""Execute the frozen effect-set scenarios, and capture what happened before anything is fixed.

This is the runner the predeclared protocol names --- see `docs/effect-set-run-protocol.md`,
which was written and committed before this file existed. It does three things and refuses a
fourth.

It **reads**: the manifest's identity is recomputed from the bytes on disk and compared with the
published hash before anything else runs, so a run always says which labels it was scored
against and a run against edited labels cannot happen quietly.

It **executes**: the scenarios are pytest tests over the existing engine, workflow, MCP and
simulator fixtures, and this runner invokes them with a sink to write their verdicts to. It
judges nothing itself. The judging lives in ``apps/backend/tests/_effect_set_judge.py``, next to
the manifest reader, and reads its expectations out of the frozen document rather than from
anything typed by hand.

It **captures**: one JSON file per run, written before any repair, holding the manifest SHA, the
implementation SHA, the runner version, the command as invoked, the environment, and every
difference between a frozen label and an observed result, in full.

And it **refuses to score a subset**. ``--scored`` is the protocol's intent-to-record flag, and
it exits non-zero without executing anything while any of the sixteen scenarios is unwired. A
run without that flag is a harness-development run: it writes a capture marked ``development``,
and no ratio out of sixteen is computed or printed for it, ever.

Check the clone, with no database and no container::

    uv run python scripts/run_effect_sets.py --check

Run the wired scenarios against the local stack::

    uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py

Two frozen manifests exist and ``--manifest`` chooses between them; it defaults to ``v1``, the
original whose first scored run is the immutable 11/16 headline. ``v2`` is its separately
versioned label correction (``docs/effect-set-manifest-v2.md``), scored only as G8's release
condition and captured under ``docs/effect-sets/runs-v2/`` so its record never sits among v1's.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]

# Run as a path script -- which is how the clean-clone command invokes it -- only this file's own
# directory is importable, and the verifier beside it resolves under its package name everywhere
# else. Put the repository root on the path so one spelling works from a fresh clone and from
# pytest alike, rather than having the module name depend on how somebody started the process.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_effect_set_manifest import (  # noqa: E402
    MANIFEST_PATHS,
    Manifest,
    load,
    problems,
)

RUNNER_VERSION: Final = "1.1.0"
"""Bumped whenever the harness changes how it observes or judges. Recorded in every capture.

``1.1.0`` adds the choice of manifest. Observation and the pass rule are unchanged from ``1.0.0``;
what moved is which frozen document the expectations are read from.
"""

PUBLISHED_SHA: Final = "d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc"
"""The identity published in `docs/effect-set-manifest.md` and frozen at commit 9a7f4a8."""

PUBLISHED_V2_SHA: Final = "77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd"
"""The identity published in `docs/effect-set-manifest-v2.md`, the label correction of v1."""

MANIFEST_VARIABLE: Final = "PP_EFFECT_SET_MANIFEST"
"""Names the runner's manifest choice to the pytest process, which judges against nothing else."""

WIRED: Final[tuple[str, ...]] = (
    "S01",
    "S02",
    "S03",
    "S04",
    "S05",
    "S06",
    "S07",
    "S08",
    "S09",
    "S10",
    "S11",
    "S12",
    "S13",
    "S14",
    "S15",
    "S16",
)
"""The scenarios that have an executable path.

All sixteen. Each one performs its own stipulated facts against the real system and reads every
checkpoint it declares, so ``--scored`` is no longer refused for want of an executable path --
which is the only thing that refusal was ever about. It says nothing whatever about whether the
scenarios agree with their frozen labels, and several committed here do not; see
`docs/effect-set-run-protocol.md` for what may and may not be done about that before the first
scored run exists.
"""

SCENARIO_SUITE: Final = "apps/backend/tests/test_effect_sets.py"
"""Where the executable scenarios live. Ordinary pytest, ordinary fixtures, no private path."""

SINK_VARIABLE: Final = "PP_EFFECT_SET_SINK"
"""The file each scenario appends its verdict to, as one JSON object per line."""

CAPTURE_DIRECTORY: Final = ROOT / "docs" / "effect-sets" / "runs"

CAPTURE_V2_DIRECTORY: Final = ROOT / "docs" / "effect-sets" / "runs-v2"

PUBLISHED: Final = {"v1": PUBLISHED_SHA, "v2": PUBLISHED_V2_SHA}
CAPTURES: Final = {"v1": CAPTURE_DIRECTORY, "v2": CAPTURE_V2_DIRECTORY}

PROTOCOL: Final = "docs/effect-set-run-protocol.md"

PASS: Final = "PASS"
FAIL: Final = "FAIL"
HARNESS_FAILURE: Final = "HARNESS_FAILURE"

NOT_WIRED: Final = (
    "not wired: this scenario has no executable path yet, so the harness cannot tell whether "
    "the system agrees with its frozen labels"
)
"""Why an unwired scenario is a nonpass rather than an absence.

The protocol fixes this: a harness that cannot execute a scenario has failed to demonstrate it,
and "we could not tell" belongs in the diagnosis rather than in the number. It can never reach a
scored capture, because ``--scored`` is refused while any scenario is unwired -- but it is
recorded honestly in a development one rather than quietly skipped.
"""


# ------------------------------------------------------------------------------ the record


@dataclass(frozen=True, slots=True)
class Outcome:
    """One scenario's verdict, as it is written into a capture."""

    scenario: str
    outcome: str
    reason: str = ""
    diffs: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "outcome": self.outcome,
            "reason": self.reason,
            "diffs": [dict(diff) for diff in self.diffs],
        }


def implementation() -> tuple[str, bool]:
    """The commit this ran against, and whether the tree it ran from was dirty.

    A dirty tree is recorded rather than refused. Refusing would make the runner unusable during
    the work that builds it; hiding it would make a capture name a commit whose content was not
    what ran. So it says both.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return head, bool(status)


def environment() -> dict[str, Any]:
    """What ran it, and whether anything that could have spent money was even configured.

    Names and booleans only. A capture is committed, so it holds no value of any variable it
    reports on.
    """
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "model_provider_configured": bool(os.environ.get("PP_LLM_PROVIDER")),
        "aws_credentials_configured": any(
            os.environ.get(name) for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID")
        ),
        "transport_fixtures": (
            "The customer channel and the external order system are local fixtures driven in "
            "process. Local replay is not proof of live delivery."
        ),
    }


def read_sink(path: Path) -> dict[str, Outcome]:
    """Every verdict the scenarios wrote, keyed by scenario id.

    A scenario that wrote two verdicts is a harness fault of its own: the last one does not win,
    because a run that reported a scenario twice cannot say which of them it means.
    """
    found: dict[str, Outcome] = {}
    if not path.exists():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        scenario = str(entry["scenario"])
        if scenario in found:
            found[scenario] = Outcome(
                scenario=scenario,
                outcome=HARNESS_FAILURE,
                reason="reported more than once in a single run",
            )
            continue
        found[scenario] = Outcome(
            scenario=scenario,
            outcome=str(entry["outcome"]),
            reason=str(entry.get("reason", "")),
            diffs=tuple(dict(diff) for diff in entry.get("diffs", ())),
        )
    return found


def reconcile(manifest: Manifest, reported: dict[str, Outcome]) -> tuple[Outcome, ...]:
    """One outcome per scenario in the manifest, in manifest order, with no gaps.

    The manifest decides the list, never the sink: a scenario that never reported is a
    ``HARNESS_FAILURE`` rather than a row that is simply absent, which is what keeps the
    denominator at sixteen whatever the run did.
    """
    outcomes: list[Outcome] = []
    for scenario in manifest.scenarios:
        identifier = str(scenario["id"])
        if identifier not in WIRED:
            outcomes.append(Outcome(scenario=identifier, outcome=HARNESS_FAILURE, reason=NOT_WIRED))
            continue
        found = reported.get(identifier)
        if found is None:
            outcomes.append(
                Outcome(
                    scenario=identifier,
                    outcome=HARNESS_FAILURE,
                    reason="wired, but reached no verdict: it raised, timed out or never ran",
                )
            )
            continue
        outcomes.append(found)
    return tuple(outcomes)


def capture(
    *,
    manifest: Manifest,
    kind: str,
    command: Sequence[str],
    started_at: datetime,
    finished_at: datetime,
    outcomes: Sequence[Outcome],
) -> dict[str, Any]:
    """The immutable record of one run, assembled before anything may be repaired."""
    head, dirty = implementation()
    document: dict[str, Any] = {
        "protocol": PROTOCOL,
        "kind": kind,
        "runner_version": RUNNER_VERSION,
        "manifest": manifest.name,
        "manifest_version": manifest.version,
        "manifest_sha": manifest.content_hash,
        "implementation_sha": head,
        "working_tree_dirty": dirty,
        "command": list(command),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "environment": environment(),
        "wired": list(WIRED),
        "unwired": [
            str(scenario["id"]) for scenario in manifest.scenarios if scenario["id"] not in WIRED
        ],
        "outcomes": [outcome.as_dict() for outcome in outcomes],
        "score": None,
    }
    if kind == "scored":
        # Unreachable while any scenario is unwired, which is enforced before a scored run
        # executes anything. It is written here so the shape of a scored capture is fixed in
        # advance rather than decided by whoever takes the measurement.
        document["score"] = {
            "passed": sum(outcome.outcome == PASS for outcome in outcomes),
            "of": len(manifest.scenarios),
        }
    return document


def write_capture(document: dict[str, Any], *, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = document["started_at"].replace(":", "").replace("-", "").replace(".", "")
    path = directory / f"{stamp}-{document['kind']}.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# -------------------------------------------------------------------------------- the run


def execute(sink: Path, *, choice: str = "v1", selection: Sequence[str] = ()) -> int:
    """Run the scenario suite with a sink to report into, and hand back pytest's own code.

    The manifest choice is always written into the child's environment, overriding anything it
    would have inherited, so the document the suite judges against is the one this run names in
    its capture and never one an ambient variable chose.
    """
    command = [sys.executable, "-m", "pytest", SCENARIO_SUITE, "-q"]
    if selection:
        command += ["-k", " or ".join(selection)]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, SINK_VARIABLE: str(sink), MANIFEST_VARIABLE: choice},
        check=False,
    )
    return completed.returncode


def render(manifest: Manifest, outcomes: Sequence[Outcome], *, kind: str) -> None:
    """What the run did, per scenario. No ratio, and none computed, for a development run."""
    print(f"\nmanifest      {manifest.name} v{manifest.version}")
    print(f"manifest_sha  {manifest.content_hash}")
    print(f"runner        {RUNNER_VERSION}")
    print(f"kind          {kind}\n")
    for outcome in outcomes:
        suffix = f"  -- {outcome.reason}" if outcome.reason else ""
        print(f"  {outcome.scenario}  {outcome.outcome}{suffix}")
        for diff in outcome.diffs:
            print(
                f"      {diff.get('checkpoint')}/{diff.get('aspect')} {diff.get('subject')}: "
                f"expected {diff.get('expected')}, observed {diff.get('observed')}"
            )
    if kind == "development":
        print(
            "\nThis was a harness-development run. It is not a score, it has no denominator of "
            "sixteen, and none is computed."
        )


def check(manifest: Manifest, *, published: str = PUBLISHED_SHA) -> int:
    """The clean-clone step: identity, coherence and wiring, with nothing else running."""
    print(f"manifest      {manifest.name} v{manifest.version}")
    print(f"manifest_sha  {manifest.content_hash}")
    print(f"published     {published}")
    print(f"runner        {RUNNER_VERSION}")

    if manifest.content_hash != published:
        print("\nREFUSED: this is not the document whose hash was published.")
        return 1
    found = problems(manifest)
    if found:
        print(f"\n{len(found)} coherence problem(s):")
        for problem in found:
            print(f"  - {problem}")
        return 1

    unwired = [str(s["id"]) for s in manifest.scenarios if s["id"] not in WIRED]
    print(f"\nwired         {len(WIRED)}: {', '.join(WIRED)}")
    print(f"unwired       {len(unwired)}: {', '.join(unwired)}")
    print(
        "\nidentity intact, manifest coherent. --scored is refused while any scenario is unwired."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the manifest's identity, coherence and wiring. Executes no scenario.",
    )
    parser.add_argument(
        "--scored",
        action="store_true",
        help=(
            "Take the measurement with intent to record. Refused while any of the sixteen "
            "scenarios is unwired; see docs/effect-set-run-protocol.md."
        ),
    )
    parser.add_argument(
        "--manifest",
        choices=tuple(PUBLISHED),
        default="v1",
        help=(
            "Which frozen manifest to judge against. v1 is the original; v2 is its separately "
            "versioned label correction, scored only as G8's release condition."
        ),
    )
    parser.add_argument(
        "--capture-directory",
        type=Path,
        default=None,
        help=(
            "Where the run's immutable capture is written. Defaults to docs/effect-sets/runs "
            "for v1 and docs/effect-sets/runs-v2 for v2."
        ),
    )
    args = parser.parse_args(argv)

    choice: str = args.manifest
    published = PUBLISHED[choice]
    manifest = load(MANIFEST_PATHS[choice])

    if manifest.content_hash != published:
        print("REFUSED: the manifest is not the document whose hash was published.")
        print(f"  published  {published}")
        print(f"  on disk    {manifest.content_hash}")
        return 1

    if args.check:
        return check(manifest, published=published)

    unwired = [str(s["id"]) for s in manifest.scenarios if s["id"] not in WIRED]
    if args.scored and unwired:
        print("REFUSED: a scored run executes all sixteen scenarios, and these are unwired:")
        print(f"  {', '.join(unwired)}")
        print(
            "\nNothing was executed and no capture was written. The protocol fixes this: a "
            "scored run over a subset is not a thing that can be produced."
        )
        return 1

    kind = "scored" if args.scored else "development"
    command = [sys.argv[0], *(argv if argv is not None else sys.argv[1:])]
    started_at = datetime.now(UTC)

    with tempfile.TemporaryDirectory() as workspace:
        sink = Path(workspace) / "verdicts.jsonl"
        execute(sink, choice=choice)
        reported = read_sink(sink)

    finished_at = datetime.now(UTC)
    outcomes = reconcile(manifest, reported)
    document = capture(
        manifest=manifest,
        kind=kind,
        command=command,
        started_at=started_at,
        finished_at=finished_at,
        outcomes=outcomes,
    )
    path = write_capture(document, directory=args.capture_directory or CAPTURES[choice])

    render(manifest, outcomes, kind=kind)
    print(f"\ncapture       {path}")
    return (
        0
        if all(outcome.outcome == PASS for outcome in outcomes if outcome.scenario in WIRED)
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
