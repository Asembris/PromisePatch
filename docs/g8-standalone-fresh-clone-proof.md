# G8 row 11: the standalone engine's tests, from a fresh clone

**Date:** 2026-09-26. **Row:** G8 row 11, *standalone engine from a clean clone*.
**Verdict:** **CLOSED.**

[g8-evidence-packaging.md](g8-evidence-packaging.md) §5 recorded four of the five standalone
steps exiting `0` on a fresh public clone: the venv, the pinned requirements, the `--no-deps`
package install and the example. A host blue screen then cut off the fifth step, the tests, before
it produced a result. This page records that fifth step, run once and alone, in the same clone and
the same environment. Nothing on that page is edited; this is the later truth beside it.

## 1. What was run

It was one command, run from `D:\pp-g8-fresh-clone\promisepatch\packages\promise-graph` in Git
Bash under the §5 `CLEAN` prefix:

```bash
CLEAN="env -u CLAUDE_CODE_MESSAGING_TOKEN -u ANTHROPIC_BASE_URL AWS_CONFIG_FILE=/nonexistent/config AWS_SHARED_CREDENTIALS_FILE=/nonexistent/credentials AWS_EC2_METADATA_DISABLED=true"
```

```bash
$CLEAN uv run --no-project pytest tests -q
```

No other process was run alongside it: no Docker, no other suite and no install.

## 2. The output, verbatim

```text
2026-09-26T19:31:18Z
$ uv run --no-project pytest tests -q
........................................................................ [ 21%]
........................................................................ [ 42%]
........................................................................ [ 64%]
........................................................................ [ 85%]
...............................................                          [100%]
exit=0
2026-09-26T19:31:48Z
```

**Result: 335 passed, 0 failed, 0 errors, 0 skipped, 0 xfailed. Exit `0`, in about 30 s of wall
time.**

There is no `N passed` summary line, and that is expected. The package's `pyproject.toml` already
sets `addopts = "-q --strict-markers --strict-config --import-mode=importlib"`, so the documented
`-q` makes the run `-qq`, and `-qq` suppresses the summary. The count is read from the progress
lines: four full lines of 72 plus one of 47, for **335** outcome characters. Every one of them is
`.`; there is no `F`, `E`, `s`, `x` or `X`. pytest was not re-run to get the summary.

## 3. The facts around it

| | |
|---|---|
| clone | `D:\pp-g8-fresh-clone\promisepatch`, cloned 2026-09-26 from the public repository (§5 of the packaging page) |
| clone HEAD | `b5cf0d38c97b6a3fe4535070ecdc6b29d51666f5`, before and after |
| tracked tree before | clean. `git status --porcelain --ignored` showed only `!! packages/promise-graph/.venv/` |
| tracked tree after | clean. `git status --porcelain --untracked-files=all` printed nothing. The ignored entries now also include `.pytest_cache/`, `.hypothesis/` and four `__pycache__/` directories, the test run's own caches |
| Python | CPython `3.12.12`, taken from the venv's `pyvenv.cfg`. uv `0.9.18` created the venv |
| venv reuse | the existing `packages/promise-graph/.venv` built in sitting 1 was reused as is. `--no-project` does not sync, and the installed set after the run is the same 14 distributions: the 13 pinned packages plus `promise_graph 0.1.0` |
| credentials | no `AWS_*` variable was set in the shell. `CLAUDE_CODE_MESSAGING_TOKEN` and `ANTHROPIC_BASE_URL` were unset for the command. The AWS config and credential files pointed at nonexistent paths, and instance metadata was disabled |
| main repo | `D:\PromisePatch` at `cfe9937d5a4ba2433968f30ad7a86bff2f31b160`. Its untracked files were left untouched |

## 4. What this does and does not say

- **Row 11 is met.** All five standalone steps now exit `0` on one fresh clone of the public
  repository at `b5cf0d3`, with no cloud credential reachable. Four were recorded in sitting 1,
  and the tests are recorded here.
- The uv cache was this machine's and warm, as in sitting 1. The clone is fresh; the package
  cache is not.
- The five steps were not taken in one sitting. Steps 1–4 ran before the host crash; step 5 ran
  here, against the venv they built. Re-running step 1 over that venv would have deleted and
  recreated about 889 files, and was deliberately not done.
- **Row 20 is untouched.** No root `uv sync --frozen` was run, and no effect-set check was run.
- No code, image, deployment or AWS resource changed, and no model was called.
