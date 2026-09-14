"""The backend suite is split across runners, and the split is a partition of the whole suite.

`.github/workflows/pr.yml` used to run `pytest apps/backend` once, in one job called
`backend + postgres`, and that job was the critical path of every pull request. It now runs on
three runners, and two things about that are load-bearing in a way nothing goes red about on
its own.

The first is that **sharding must not be selecting**. pytest-split partitions the collected
list into contiguous chunks, so three groups out of three splits is the whole suite and any
other arithmetic is not. A shard command that said `--splits 4` while the matrix offered three
groups would drop a quarter of the backend tests, pass, and report a green tick with the same
name as before. That is the one failure this file exists to make impossible to introduce
quietly: the collection itself is checked elsewhere, by actually collecting, but the *shape*
that makes the collection correct is checked here.

The second is that **the name branch protection requires must keep meaning what it meant**.
`backend + postgres` is a required status check. A matrix job cannot carry that name -- GitHub
appends the matrix value to it -- so the name now belongs to an aggregator that runs no tests
and passes only when every shard passed. If that aggregator ever stopped depending on a shard,
or started treating a cancelled run as a pass, the check would still be green and would still
be called `backend + postgres`, and nothing would say that a third of the suite had stopped
being required.

Nothing here asserts how *fast* the split is. Balance is a property of the committed
`.test_durations` and drifts harmlessly; coverage is a property of the shape, and does not.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pr.yml"

REQUIRED_CHECK = "backend + postgres"
"""The name branch protection requires. Renaming this job is a branch-protection change."""

EXPECTED_GROUPS = (1, 2, 3)
"""The shard count. Changing it means changing `--splits` in the same commit, or dropping tests."""


@pytest.fixture
def workflow() -> dict[str, Any]:
    parsed: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return parsed


@pytest.fixture
def jobs(workflow: dict[str, Any]) -> dict[str, Any]:
    running: dict[str, Any] = workflow["jobs"]
    return running


def _is_split(command: Any) -> bool:
    """A step that runs part of a split suite rather than a named set of files.

    Matched on `--splits` rather than on the directory, because the `semantic` and `transport`
    jobs also run `pytest apps/backend/...` -- against files they name one by one, which is a
    different thing and is not sharded.
    """
    return isinstance(command, str) and "--splits" in command


def _suite_step(job: dict[str, Any]) -> str:
    """The one step in ``job`` that runs a shard of the backend suite."""
    running = [step["run"] for step in job["steps"] if _is_split(step.get("run"))]
    assert len(running) == 1, f"expected exactly one backend suite step, found {len(running)}"
    return str(running[0])


def _shard_jobs(jobs: dict[str, Any]) -> dict[str, Any]:
    """Every job that runs a *part* of the backend suite."""
    return {
        name: job
        for name, job in jobs.items()
        if any(_is_split(step.get("run")) for step in job.get("steps", []))
    }


def test_the_backend_suite_runs_in_exactly_one_matrix_job(jobs: dict[str, Any]) -> None:
    shards = _shard_jobs(jobs)
    assert list(shards) == ["backend-shard"]
    matrix = shards["backend-shard"]["strategy"]["matrix"]
    assert tuple(matrix["group"]) == EXPECTED_GROUPS
    # And it runs the whole directory, not a list of files somebody has to keep up to date.
    assert "pytest apps/backend" in _suite_step(shards["backend-shard"])


def test_a_failing_shard_does_not_cancel_the_others(jobs: dict[str, Any]) -> None:
    """Otherwise a run reports a third of the truth and somebody comes back for the rest."""
    assert jobs["backend-shard"]["strategy"]["fail-fast"] is False


def test_every_shard_shares_one_splits_value_and_it_is_the_shard_count(
    jobs: dict[str, Any],
) -> None:
    """`--splits N` with fewer than N groups offered is a silent deselection of the remainder."""
    command = _suite_step(jobs["backend-shard"])
    splits = re.findall(r"--splits\s+(\d+)", command)
    assert splits == [str(len(EXPECTED_GROUPS))]
    assert "--group ${{ matrix.group }}" in command


def test_the_shards_read_the_committed_durations_file(jobs: dict[str, Any]) -> None:
    command = _suite_step(jobs["backend-shard"])
    assert "--durations-path .test_durations" in command
    assert (WORKFLOW.parents[2] / ".test_durations").is_file()


def test_no_shard_deselects_anything(jobs: dict[str, Any]) -> None:
    """The split is the only thing narrowing what a shard runs."""
    command = _suite_step(jobs["backend-shard"])
    for narrowing in ("--deselect", "--ignore", "-k ", "--lf", "--ff", "-m "):
        assert narrowing not in command, f"the shard command narrows the suite with {narrowing!r}"


def test_durations_are_recorded_on_main_and_never_on_a_pull_request(
    jobs: dict[str, Any],
) -> None:
    """Storing is how the balance is refreshed; doing it on a pull request would measure a fork."""
    command = _suite_step(jobs["backend-shard"])
    assert "--store-durations --clean-durations" in command
    assert "github.ref == 'refs/heads/main'" in command


def test_the_required_check_is_a_job_that_runs_no_tests(jobs: dict[str, Any]) -> None:
    named = [name for name, job in jobs.items() if job.get("name") == REQUIRED_CHECK]
    assert named == ["backend"]
    aggregator = jobs["backend"]
    assert not any("pytest" in str(step.get("run", "")) for step in aggregator["steps"])


def test_the_required_check_depends_on_every_shard(jobs: dict[str, Any]) -> None:
    """`needs` names the matrix job, and the matrix job is all three shards."""
    needs = jobs["backend"]["needs"]
    assert needs == ["backend-shard"]
    covered = {
        group
        for name in needs
        for group in jobs[name].get("strategy", {}).get("matrix", {}).get("group", [])
    }
    assert covered == set(EXPECTED_GROUPS)
    assert set(needs) >= set(_shard_jobs(jobs))


def test_the_required_check_is_reached_even_when_a_shard_fails(jobs: dict[str, Any]) -> None:
    """Without `always()` a failed shard skips the aggregator, and a skip is not a failure."""
    assert jobs["backend"]["if"] == "always()"


def test_the_required_check_passes_only_on_success(jobs: dict[str, Any]) -> None:
    """Compared against `success` rather than against `failure`, so cancelled fails closed."""
    gate = "\n".join(str(step.get("run", "")) for step in jobs["backend"]["steps"])
    assert "needs.backend-shard.result" in gate
    assert '!= "success"' in gate
    assert "exit 1" in gate


def test_the_durations_refresh_runs_on_main_only_and_pushes_nothing(
    workflow: dict[str, Any], jobs: dict[str, Any]
) -> None:
    refresh = jobs["test-durations"]
    assert refresh["needs"] == ["backend-shard"]
    assert "github.ref == 'refs/heads/main'" in refresh["if"]
    assert workflow["permissions"] == {"contents": "read"}
    steps = "\n".join(str(step.get("run", "")) for step in refresh["steps"])
    assert "git push" not in steps and "git commit" not in steps
