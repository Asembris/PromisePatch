"""Every workflow skips documentation, and skips nothing else.

This repository has two workflows, and both carry the same `paths-ignore` filter so that a change
touching only Markdown does not spend a runner on jobs that would test the same code twice.
`.github/workflows/pr.yml` is the product gate; `.github/workflows/effect-sets.yml` is the frozen
sixteen-scenario benchmark, which lives in a file of its own because a badge is per workflow
rather than per job and that one is expected to be red. A path filter is a piece of logic that
decides whether the rest of the repository's correctness gates run at all, and it fails silently
in the one direction that matters: if it ever excludes real code, nothing goes red -- CI simply
says nothing, and a pull request merges having been tested by no one. So it is tested here rather
than trusted.

Every assertion below runs against *both* files, and a fifth one pins the set of files itself:
adding a third workflow whose filter nobody checked fails here rather than shipping a gate that
skips real code. The two workflows are not allowed to drift apart -- a benchmark that ran on a
changeset the product gate skipped, or the reverse, would be measuring and gating different
repositories.

Three things are asserted of each file, and they are not the same thing.

The first is the **shape of the filter**: both triggers carry it, both carry the same list, and
neither uses `paths`, which GitHub refuses to accept alongside `paths-ignore`.

The second is the **behaviour** of that list over representative changesets, using GitHub's
filter-pattern semantics rather than the standard library's -- `*` stops at a slash and `**`
does not, and `fnmatch` knows the difference to neither.

The third is the property the exclusion strategy exists to have. Every non-Markdown file that
this repository actually tracks, today, is asserted to run CI. That is what makes the filter
future-safe rather than merely correct now: an allowlist would have to be extended for each new
language, package or fixture directory and would fail closed only if somebody remembered, while
this list has to be extended for a file to be *skipped*. `docs/effect-sets/scenarios.v1.json`
is the case that names the reason -- it lives under `docs/` and is frozen published evidence,
so a filter that ignored `docs/**` would have stopped testing the one file nobody may change
quietly.

A fourth thing is asserted beside them, for the same reason in the opposite direction: the
manual trigger. Because a documentation-only commit matches the filter, it produces no check at
all -- not a red one to re-run, not a green one to read -- and `workflow_dispatch` is the only
way to produce a run on a release SHA that touches no code. It is pinned on both files so that
tidying either `on:` block cannot silently remove it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

WORKFLOWS = (WORKFLOW_DIR / "pr.yml", WORKFLOW_DIR / "effect-sets.yml")
"""Every workflow in this repository. The product gate, and the benchmark that is expected red."""

EXPECTED_PATTERNS = ("**.md",)
"""The frozen filter. Widening it means skipping something that is not documentation."""

SUPPORTED = re.compile(r"^[A-Za-z0-9_./*-]+$")
"""Patterns this matcher models exactly. Anything else fails rather than being approximated."""


def _on_block(text: str) -> list[str]:
    """The lines of the top-level ``on:`` mapping, without the key line itself."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.rstrip() == "on:")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        block.append(line)
    return block


def _triggers(block: list[str]) -> list[str]:
    """The trigger names of the ``on:`` mapping: its keys, ignoring comments and nesting."""
    names: list[str] = []
    for line in block:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(line) - len(line.lstrip()) != 2:
            continue
        names.append(stripped.split(":", 1)[0])
    return names


def _path_filters(block: list[str], key: str) -> list[tuple[str, ...]]:
    """Every ``key:`` list in ``block``, in order, as a tuple of its quoted items."""
    found: list[tuple[str, ...]] = []
    index = 0
    while index < len(block):
        line = block[index]
        if line.strip() == f"{key}:":
            indent = len(line) - len(line.lstrip())
            items: list[str] = []
            index += 1
            while index < len(block):
                item = block[index]
                if not item.strip():
                    index += 1
                    continue
                if len(item) - len(item.lstrip()) <= indent or not item.lstrip().startswith("- "):
                    break
                items.append(item.strip()[2:].strip().strip("'\""))
                index += 1
            found.append(tuple(items))
            continue
        index += 1
    return found


def _regex(pattern: str) -> re.Pattern[str]:
    """GitHub's filter-pattern semantics: ``**`` crosses a slash, a lone ``*`` does not."""
    assert SUPPORTED.match(pattern), f"unmodelled filter pattern: {pattern!r}"
    compiled = ""
    index = 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            compiled += ".*"
            index += 2
        elif pattern[index] == "*":
            compiled += "[^/]*"
            index += 1
        else:
            compiled += re.escape(pattern[index])
            index += 1
    return re.compile(f"^{compiled}$")


def ci_runs(changed: tuple[str, ...], patterns: tuple[str, ...] = EXPECTED_PATTERNS) -> bool:
    """GitHub skips a run only when *every* changed file matches an ignored pattern."""
    if not changed:
        return True
    ignored = [_regex(pattern) for pattern in patterns]
    return not all(any(rule.match(path) for rule in ignored) for path in changed)


def tracked_files() -> tuple[str, ...]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return tuple(path for path in listing.stdout.split("\0") if path)


@pytest.fixture(params=WORKFLOWS, ids=lambda path: path.name)
def workflow(request: pytest.FixtureRequest) -> str:
    """Each shape assertion below, run once per workflow file rather than once in total."""
    return str(request.param.read_text(encoding="utf-8"))


def test_every_workflow_file_is_covered_by_these_assertions() -> None:
    """A third workflow whose filter nobody checked is a gate that can skip real code."""
    present = sorted(path.name for path in WORKFLOW_DIR.glob("*.y*ml"))
    assert present == sorted(path.name for path in WORKFLOWS)


def test_both_triggers_ignore_the_same_documentation_list(workflow: str) -> None:
    filters = _path_filters(_on_block(workflow), "paths-ignore")
    assert filters == [EXPECTED_PATTERNS, EXPECTED_PATTERNS]


def test_no_trigger_uses_an_allowlist(workflow: str) -> None:
    """`paths` is not merely a different style here. GitHub rejects it beside `paths-ignore`."""
    assert _path_filters(_on_block(workflow), "paths") == []


def test_the_manual_trigger_exists(workflow: str) -> None:
    """The only way to produce a run on a release SHA that changed no code."""
    assert "workflow_dispatch" in _triggers(_on_block(workflow))


def test_documentation_only_changes_skip_ci() -> None:
    assert not ci_runs(("docs/p5.4-truthful-recovery-and-case-workspace.md",))
    assert not ci_runs(("README.md", "CLAUDE.md"))
    assert not ci_runs(("docs/adr/0011-conversational-orchestrator-authority.md", "docs/x.md"))
    assert not ci_runs(("apps/backend/README.md",))


def test_python_changes_run_ci() -> None:
    assert ci_runs(("apps/backend/src/promisepatch/domain/recovery.py",))
    assert ci_runs(("packages/promise-graph/src/promise_graph/propagation.py",))
    assert ci_runs(("apps/backend/tests/test_truthful_recovery.py",))
    assert ci_runs(("apps/backend/alembic/versions/0007_external_effect_results.py",))


def test_frontend_changes_run_ci() -> None:
    assert ci_runs(("apps/frontend/src/features/case/CaseWorkspace.tsx",))
    assert ci_runs(("apps/frontend/tests/caseWorkspace.test.tsx",))
    assert ci_runs(("apps/frontend/src/api/client.ts",))
    assert ci_runs(("apps/frontend/eslint.config.js",))
    assert ci_runs(("apps/frontend/e2e/order-system.spec.ts",))


def test_build_dependency_and_config_changes_run_ci() -> None:
    assert ci_runs((".github/workflows/pr.yml",))
    assert ci_runs((".github/workflows/effect-sets.yml",))
    assert ci_runs(("pyproject.toml",))
    assert ci_runs(("uv.lock",))
    assert ci_runs(("apps/frontend/package-lock.json",))
    assert ci_runs(("docker/Dockerfile.backend",))
    assert ci_runs(("docker-compose.yml",))
    assert ci_runs(("docker/postgres/init/10-managed-api-roles.sql",))


def test_the_frozen_manifest_runs_ci_although_it_lives_under_docs() -> None:
    assert ci_runs(("docs/effect-sets/scenarios.v1.json",))


def test_documentation_mixed_with_code_runs_ci() -> None:
    assert ci_runs(("docs/effect-set-manifest.md", "scripts/verify_effect_set_manifest.py"))
    assert ci_runs(("CLAUDE.md", "apps/frontend/src/app/App.tsx"))


def test_every_tracked_non_markdown_file_runs_ci() -> None:
    code = [path for path in tracked_files() if not path.endswith(".md")]
    assert [path for path in code if not ci_runs((path,))] == []


def test_every_tracked_markdown_file_is_treated_as_documentation() -> None:
    markdown = [path for path in tracked_files() if path.endswith(".md")]
    assert markdown, "the repository tracks Markdown; this test would otherwise assert nothing"
    assert [path for path in markdown if ci_runs((path,))] == []
