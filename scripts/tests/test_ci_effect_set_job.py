"""The effect-set scenarios run in their own CI job, whole, and stay visibly red.

The sixteen frozen effect-set scenarios measure the implementation against a manifest whose
first scored run is published at **11/16**. The scenarios that disagree with their frozen labels
are committed *failing*, and `docs/effect-set-run-protocol.md` forbids weakening, skipping,
deselecting, removing or marking them expected-to-fail. So the suite cannot go green until the
repairs land, and until then it is permanently red.

That is a problem only if it is red in the same job as the product suite, because then the
product suite's red says nothing: a real regression anywhere in the backend looks exactly like
the failure that was already there. So the scenarios run in a job of their own.

The split is the kind of thing that decays quietly in both directions, which is why it is tested
rather than trusted. Re-add the file to the product job and the product gate goes permanently
red again. Drop the separate job, narrow its command with `-k`, or let it pass with
`continue-on-error`, and the scenarios stop being measured at all while the workflow looks
healthy -- which is exactly the weakening the protocol exists to forbid, arrived at through the
CI configuration instead of through the test file.

Four things are asserted: the product job does not run the scenarios, some job does, that job
runs them whole and is allowed to fail the workflow, and the scenario file itself carries no
skip or xfail.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr.yml"
SCENARIOS = ROOT / "apps" / "backend" / "tests" / "test_effect_sets.py"

SCENARIO_PATH = "apps/backend/tests/test_effect_sets.py"
"""The scenario suite, as a pytest argument. One spelling, used by both jobs' assertions."""

NARROWING = ("-k", "-m", "--deselect", "--ignore", "--maxfail", "-x")
"""Arguments that would run some of the sixteen rather than all of them."""


@pytest.fixture
def jobs() -> dict[str, Any]:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return dict(parsed["jobs"])


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


def test_the_product_suite_does_not_run_the_scenarios(jobs: dict[str, Any]) -> None:
    """Otherwise the product gate is permanently red and cannot report a real regression."""
    backend = jobs["backend"]
    suite = [command for command in _runs(backend) if "pytest apps/backend" in command]
    assert suite, "the backend job no longer runs the backend suite"
    assert all(f"--ignore={SCENARIO_PATH}" in command for command in suite)


def test_the_scenarios_run_in_a_job_of_their_own(jobs: dict[str, Any]) -> None:
    """Excluded from the product job is not the same as excluded from CI."""
    scenario_jobs = _scenario_jobs(jobs)
    assert set(scenario_jobs) == {"effect-sets"}


def test_that_job_runs_all_sixteen_and_may_fail_the_workflow(jobs: dict[str, Any]) -> None:
    """Whole, and visibly red. A narrowed or tolerated run is a weakened one."""
    job = jobs["effect-sets"]
    command = next(c for c in _runs(job) if SCENARIO_PATH in c)
    assert not any(f" {flag}" in command for flag in NARROWING)
    assert "continue-on-error" not in job
    assert all("continue-on-error" not in step for step in job.get("steps", []))


def test_the_scenario_file_carries_no_skip_or_expected_failure() -> None:
    """The protocol's own words, asserted against the file rather than quoted at it."""
    source = SCENARIOS.read_text(encoding="utf-8")
    assert "xfail" not in source
    assert "skipif" not in source
    assert "pytest.skip" not in source
