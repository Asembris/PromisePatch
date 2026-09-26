# G8 row 20: the effect-set clean-clone command, from a fresh clone

**Date:** 2026-09-26. **Row:** G8 row 20, *effect-set clean-clone command tested*.
**Verdict:** **CLOSED.**

The row's literal requirement, as the audit quotes it, is *"Provide a documented clean-clone
command, pinned dependencies and local prerequisites; no AWS/cloud credentials … Test that command
from a fresh checkout."* [g8-remaining-gaps-audit.md](g8-remaining-gaps-audit.md) named one thing
missing: *the recorded fresh-checkout test*. The command is documented in
[effect-set-run-protocol.md](effect-set-run-protocol.md) as `git clone`, `uv sync --frozen`,
`uv run python scripts/run_effect_sets.py --check`, and `uv.lock` pins it.

[g8-evidence-packaging.md](g8-evidence-packaging.md) §5 left row 20 with nothing run. This page
records that run, taken once in the same fresh clone that closed row 11
([g8-standalone-fresh-clone-proof.md](g8-standalone-fresh-clone-proof.md)). Neither of those pages
is edited; this is the later truth beside them.

## 1. What was run

Five commands were run from `D:\pp-g8-fresh-clone\promisepatch`, one at a time, in Git Bash under
the §5 `CLEAN` prefix:

```bash
CLEAN="env -u CLAUDE_CODE_MESSAGING_TOKEN -u ANTHROPIC_BASE_URL AWS_CONFIG_FILE=/nonexistent/config AWS_SHARED_CREDENTIALS_FILE=/nonexistent/credentials AWS_EC2_METADATA_DISABLED=true"
```

1. `$CLEAN uv sync --frozen`. The owner authorised exactly this one high-churn command for the
   session. It was run once and not retried.
2. `$CLEAN uv run python scripts/run_effect_sets.py --check`
3. `$CLEAN uv run python scripts/run_effect_sets.py --check --manifest v2`
4. `$CLEAN uv run python scripts/verify_effect_set_manifest.py`
5. `$CLEAN uv run python scripts/verify_effect_set_manifest.py --manifest v2`

No other process ran alongside any of them: no Docker, no suite and no second install.

`--check` returns at `scripts/run_effect_sets.py` `main`, before any scenario runs and before any
capture or subprocess is made. This was re-read in the clone's own source before the checks ran.
No `--scored` run, effect-set pytest run, model call or SUR-1 command was made.

## 2. The sync, verbatim

The package lines are complete. The last line is the wrapper's own timing stamp. `bc` is not
installed on this host, so the sub-second wall figure came out empty, and wall time is read from
the UTC stamps.

```text
Using CPython 3.12.12
Creating virtual environment at: .venv
   Building order-contract @ file:///D:/pp-g8-fresh-clone/promisepatch/packages/order-contract
   Building order-simulator @ file:///D:/pp-g8-fresh-clone/promisepatch/apps/order-simulator
   Building promise-graph @ file:///D:/pp-g8-fresh-clone/promisepatch/packages/promise-graph
   Building promisepatch @ file:///D:/pp-g8-fresh-clone/promisepatch/apps/backend
      Built order-contract @ file:///D:/pp-g8-fresh-clone/promisepatch/packages/order-contract
      Built promisepatch @ file:///D:/pp-g8-fresh-clone/promisepatch/apps/backend
      Built order-simulator @ file:///D:/pp-g8-fresh-clone/promisepatch/apps/order-simulator
      Built promise-graph @ file:///D:/pp-g8-fresh-clone/promisepatch/packages/promise-graph
Prepared 4 packages in 1.89s
warning: Failed to hardlink files; falling back to full copy. This may lead to degraded performance.
         If the cache and target directories are on different filesystems, hardlinking may not be supported.
         If this is intentional, set `export UV_LINK_MODE=copy` or use `--link-mode=copy` to suppress this warning.
Installed 83 packages in 5.32s
 + alembic==1.19.1
 + annotated-doc==0.0.5
 + annotated-types==0.8.0
 + anyio==4.14.2
 + argon2-cffi==23.1.0
 + argon2-cffi-bindings==26.1.0
 + ast-serialize==0.9.0
 + asyncpg==0.30.0
 + attrs==26.1.0
 + boto3==1.43.89
 + botocore==1.43.89
 + cffi==2.1.1
 + click==8.3.3
 + colorama==0.4.6
 + coverage==7.16.0
 + cryptography==50.0.1
 + fastapi==0.141.1
 + greenlet==3.5.5
 + grimp==3.16
 + h11==0.16.0
 + httpcore2==2.12.0
 + httptools==0.8.0
 + httpx2==2.12.0
 + hypothesis==6.167.1
 + idna==3.19
 + import-linter==2.14
 + iniconfig==2.3.0
 + jmespath==1.1.0
 + jsonschema==4.26.0
 + jsonschema-specifications==2025.9.1
 + librt==0.15.0
 + mako==1.4.1
 + markdown-it-py==4.2.0
 + markupsafe==3.0.3
 + mcp==2.2.0
 + mcp-types==2.2.0
 + mdurl==0.1.2
 + mypy==2.3.1
 + mypy-extensions==1.1.0
 + opentelemetry-api==1.44.0
 + order-contract==0.1.0 (from file:///D:/pp-g8-fresh-clone/promisepatch/packages/order-contract)
 + order-simulator==0.1.0 (from file:///D:/pp-g8-fresh-clone/promisepatch/apps/order-simulator)
 + packaging==26.3
 + pathspec==1.1.1
 + pluggy==1.6.0
 + promise-graph==0.1.0 (from file:///D:/pp-g8-fresh-clone/promisepatch/packages/promise-graph)
 + promisepatch==0.1.0 (from file:///D:/pp-g8-fresh-clone/promisepatch/apps/backend)
 + pycparser==3.0
 + pydantic==2.13.5
 + pydantic-core==2.46.5
 + pydantic-settings==2.15.0
 + pygments==2.21.0
 + pyjwt==2.13.0
 + pytest==8.4.2
 + pytest-asyncio==0.26.0
 + pytest-cov==7.1.0
 + python-dateutil==2.9.0.post0
 + python-dotenv==1.2.3
 + python-multipart==0.0.32
 + pywin32==312
 + pyyaml==6.0.3
 + referencing==0.37.0
 + rich==14.3.4
 + rpds-py==2026.6.3
 + ruff==0.16.5
 + s3transfer==0.19.2
 + shellingham==1.5.4
 + six==1.17.0
 + sortedcontainers==2.4.0
 + sqlalchemy==2.0.52
 + sse-starlette==3.4.11
 + starlette==1.6.0
 + structlog==24.4.0
 + truststore==0.10.4
 + typer==0.27.2
 + types-pyyaml==6.0.12.20260906
 + typing-extensions==4.16.0
 + typing-inspection==0.4.4
 + tzdata==2026.3
 + urllib3==2.7.0
 + uvicorn==0.52.4
 + watchfiles==1.2.0
 + websockets==17.1
start=2026-09-26T19:44:57Z end=2026-09-26T19:45:05Z exit=0 wall=s
```

**Result: exit `0`, about 8 s of wall time.** A new root `.venv` was created (it did not exist
before), and 83 packages were installed from the lock, among them the four workspace members.
uv made no resolution: `--frozen` installs the lock as written and does not update it.

## 3. The four checks, verbatim

```text
$ uv run python scripts/run_effect_sets.py --check
manifest      promisepatch-effect-sets v1.0.0
manifest_sha  d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc
published     d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc
runner        1.1.0

wired         16: S01, S02, S03, S04, S05, S06, S07, S08, S09, S10, S11, S12, S13, S14, S15, S16
unwired       0: 

identity intact, manifest coherent. --scored is refused while any scenario is unwired.
exit=0
```

```text
$ uv run python scripts/run_effect_sets.py --check --manifest v2
manifest      promisepatch-effect-sets v2.0.0
manifest_sha  77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd
published     77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd
runner        1.1.0

wired         16: S01, S02, S03, S04, S05, S06, S07, S08, S09, S10, S11, S12, S13, S14, S15, S16
unwired       0: 

identity intact, manifest coherent. --scored is refused while any scenario is unwired.
exit=0
```

```text
$ uv run python scripts/verify_effect_set_manifest.py
manifest      promisepatch-effect-sets v1.0.0
path          D:\pp-g8-fresh-clone\promisepatch\docs\effect-sets\scenarios.v1.json
scenarios     16
content_hash  d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc

coherent: partitions, checkpoints, effects and identities all hold
exit=0
```

```text
$ uv run python scripts/verify_effect_set_manifest.py --manifest v2
manifest      promisepatch-effect-sets v2.0.0
path          D:\pp-g8-fresh-clone\promisepatch\docs\effect-sets\scenarios.v2.json
scenarios     16
content_hash  77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd

coherent: partitions, checkpoints, effects and identities all hold
exit=0
```

All four exit `0`. The v1 hash is the frozen `d41f5afc…2cdc`, and the v2 hash is the separately
versioned label correction `77286e77…b0dd`. Each equals its published value.

## 4. The facts around it

| | |
|---|---|
| clone | `D:\pp-g8-fresh-clone\promisepatch`, cloned 2026-09-26 from the public repository (§5 of the packaging page) |
| clone HEAD | `b5cf0d38c97b6a3fe4535070ecdc6b29d51666f5` before the sync, after it, and after the four checks |
| tracked tree before | clean. `git status --porcelain` printed nothing. The ignored entries were the standalone `.venv/` and row 11's pytest caches |
| tracked tree after | clean. After the sync and again after the four checks, `git status --porcelain` printed nothing: no tracked change and no untracked file. `uv.lock` was not rewritten. The ignored entries gained `.venv/` at the root and `__pycache__/` under `scripts/` and `packages/promise-graph/src/` |
| capture | none written. No new file under `docs/effect-sets/runs/` or `runs-v2/`, as the empty porcelain shows |
| Python | CPython `3.12.12`, uv `0.9.18` |
| root venv | **created** by the sync. It was absent before, as `ls` confirmed at entry |
| standalone venv | `packages/promise-graph/.venv` was not touched, deleted or recreated |
| credentials | no `AWS_*` variable was set in the shell, as checked at entry by name only. `CLAUDE_CODE_MESSAGING_TOKEN` and `ANTHROPIC_BASE_URL` were unset for every command. The AWS config and credential files pointed at nonexistent paths, and instance metadata was disabled. `boto3` is installed by the lock but was never called |
| disk at entry | `D:` 91 GB free, `C:` 18 GB free |
| main repo | `D:\PromisePatch` at `a84d345302b900404cb372d48b8233e4fe23792a`. Its untracked files were left untouched |

## 5. What this does and does not say

- **Row 20 is met** for what the audit named missing: the documented clean-clone command, `uv sync
  --frozen` followed by `run_effect_sets.py --check`, exits `0` on a fresh checkout of the public
  repository at `b5cf0d3`, with no cloud credential reachable. It holds for both frozen manifests,
  and both manifest verifiers agree.
- The uv cache was this machine's and warm, as for row 11. The clone is fresh; the package cache
  is not. A cold-cache run would also download the 83 packages, which this page does not measure.
- This is not an effect-set result. `--check` executes no scenario, so it proves only that the
  clone can reach the harness with its identity intact. The headline stays `11/16` against v1, and
  the `16/16` release condition stays as
  [g8-effect-set-release-condition.md](g8-effect-set-release-condition.md) records it.
- The audit's other clauses in row 20 were not re-judged here. The audit found no gap in them.
- No code, test, manifest, image, deployment or AWS resource changed. No model was called, no
  scored or development run was taken, and nothing was pushed.
- The clone and both of its venvs remain on disk. Remove `D:\pp-g8-fresh-clone` only when the
  owner says so.
