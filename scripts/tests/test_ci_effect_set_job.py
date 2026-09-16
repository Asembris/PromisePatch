"""The effect-set scenarios run in a workflow of their own, whole, and stay visibly red.

The sixteen frozen effect-set scenarios measure the implementation against a manifest whose
first scored run is published at **11/16**. The scenarios that disagree with their frozen labels
are committed *failing*, and `docs/effect-set-run-protocol.md` forbids weakening, skipping,
deselecting, removing or marking them expected-to-fail. So the suite cannot go green until the
repairs land, and until then it is permanently red.

That is a problem only if it is red in the same place as the product suite, because then the
product suite's red says nothing: a real regression anywhere in the backend looks exactly like
the failure that was already there. The separation was first made job-deep, which fixed the job's
red and not the repository's: a status badge is per *workflow*, so one permanently red job left a
permanently red badge on a repository whose product suite passes, and a reader saw "broken" where
the truth is "publishes its failures". So the scenarios now run in a workflow of their own,
`.github/workflows/effect-sets.yml`, and the two badges answer two different questions.

The split is the kind of thing that decays quietly in both directions, which is why it is tested
rather than trusted. Re-add the file to the product job and the product gate goes permanently red
again. Drop the separate workflow, narrow its command with `-k`, or let it pass with
`continue-on-error`, and the scenarios stop being measured at all while the badge looks healthy --
which is exactly the weakening the protocol exists to forbid, arrived at through the CI
configuration instead of through the test file.

Splitting one workflow into two added a failure mode that a single file could not have, and it is
pinned here too: GitHub cancels runs that share a `concurrency` group, so two workflows keyed on
`github.ref` alone would cancel each other on every push and take turns reporting nothing. A
cancelled run is not a red one -- it is no answer at all, in the direction that fails silently.

Six things are asserted: the product job does not run the scenarios, no job in the product
workflow does, exactly one job anywhere does, that job runs them whole and is allowed to fail its
workflow, the two workflows cannot cancel each other, and the scenario file itself carries no skip
or xfail.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

PRODUCT = WORKFLOW_DIR / "pr.yml"
"""The product gate. Its red means a regression, which is why the scenarios are not in it."""

BENCHMARK = WORKFLOW_DIR / "effect-sets.yml"
"""The benchmark. Expected red until 16/16, in a file of its own so its badge can say so."""

SCENARIOS = ROOT / "apps" / "backend" / "tests" / "test_effect_sets.py"

SCENARIO_PATH = "apps/backend/tests/test_effect_sets.py"
"""The scenario suite, as a pytest argument. One spelling, used by every assertion below."""

NARROWING = ("-k", "-m", "--deselect", "--ignore", "--maxfail", "-x")
"""Arguments that would run some of the sixteen rather than all of them."""


def _parse(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.fixture
def product() -> dict[str, Any]:
    return _parse(PRODUCT)


@pytest.fixture
def benchmark() -> dict[str, Any]:
    return _parse(BENCHMARK)


def _runs(job: dict[str, Any]) -> list[str]:
    """Every shell command in a job, in order."""
    return [step["run"] for step in job.get("steps", []) if isinstance(step.get("run"), str)]


def _scenario_jobs(jobs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every job with a step that runs the scenario file as a pytest *target*.

    ``--ignore=<path>`` names the same file in order to exclude it, so the exclusions are
    removed before looking for the target. Naming a file is not running it.
    """
    found = {}
    for name, job in jobs.items():
        for command in _runs(job):
            targets = command.replace(f"--ignore={SCENARIO_PATH}", "")
            if re.search(rf"pytest\b[^\n]*\b{re.escape(SCENARIO_PATH)}", targets):
                found[name] = job
                break
    return found


def _every_job() -> dict[str, dict[str, Any]]:
    """Every job in every workflow, keyed by ``<file>:<job>`` so two files cannot collide."""
    jobs: dict[str, dict[str, Any]] = {}
    for path in sorted(WORKFLOW_DIR.glob("*.y*ml")):
        for name, job in _parse(path)["jobs"].items():
            jobs[f"{path.name}:{name}"] = job
    return jobs


def test_the_product_suite_does_not_run_the_scenarios(product: dict[str, Any]) -> None:
    """Otherwise the product gate is permanently red and cannot report a real regression."""
    backend = product["jobs"]["backend"]
    suite = [command for command in _runs(backend) if "pytest apps/backend" in command]
    assert suite, "the backend job no longer runs the backend suite"
    assert all(f"--ignore={SCENARIO_PATH}" in command for command in suite)


def test_no_job_in_the_product_workflow_runs_the_scenarios(product: dict[str, Any]) -> None:
    """A badge is per workflow. One scenario job anywhere in this file turns the badge red."""
    assert _scenario_jobs(dict(product["jobs"])) == {}


def test_the_scenarios_run_in_a_workflow_of_their_own() -> None:
    """Excluded from the product workflow is not the same as excluded from CI."""
    assert set(_scenario_jobs(_every_job())) == {"effect-sets.yml:effect-sets"}


def test_that_job_runs_all_sixteen_and_may_fail_the_workflow(benchmark: dict[str, Any]) -> None:
    """Whole, and visibly red. A narrowed or tolerated run is a weakened one."""
    job = benchmark["jobs"]["effect-sets"]
    command = next(c for c in _runs(job) if SCENARIO_PATH in c)
    assert not any(f" {flag}" in command for flag in NARROWING)
    assert "continue-on-error" not in job
    assert all("continue-on-error" not in step for step in job.get("steps", []))


def test_the_benchmark_job_keeps_its_name(benchmark: dict[str, Any]) -> None:
    """The name is what a reader sees beside the red, and it explains the red."""
    assert benchmark["jobs"]["effect-sets"]["name"] == "effect sets (expected red until 16/16)"


def test_the_two_workflows_cannot_cancel_each_other(
    product: dict[str, Any], benchmark: dict[str, Any]
) -> None:
    """Shared groups cancel across workflows, and a cancelled run is no answer rather than red."""
    groups = [product["concurrency"]["group"], benchmark["concurrency"]["group"]]
    assert len(set(groups)) == len(groups), f"both workflows share a concurrency group: {groups}"

    keyed = [_parse(path)["concurrency"]["group"] for path in sorted(WORKFLOW_DIR.glob("*.y*ml"))]
    assert len(set(keyed)) == len(keyed), f"two workflows share a concurrency group: {keyed}"


def test_the_scenario_file_carries_no_skip_or_expected_failure() -> None:
    """The protocol's own words, asserted against the file rather than quoted at it."""
    source = SCENARIOS.read_text(encoding="utf-8")
    assert "xfail" not in source
    assert "skipif" not in source
    assert "pytest.skip" not in source
