# Evidence hardening: a clean-source replay of the v2 release condition

Date: **2026-09-28**. Branch `evidence/hardening`, cut from `origin/main` at
`430a269b6f2a1919233ff7c478cc5dfaa7864f17`. This page is additive. It edits no capture, manifest,
run record, rehearsal record or ADR, and it takes **no scored run**.

**Nothing here is a score.** The headline stays **11/16**, the first scored run against the frozen
v1 manifest, and it is immutable. The G8 release condition stays **16/16 against the v2 label
correction**, taken once, on 2026-09-24, and recorded in
[g8-effect-set-release-condition.md](g8-effect-set-release-condition.md). The two runs below are
**harness-development runs** in the protocol's own vocabulary. They have no denominator of sixteen,
and they replace nothing.

Evidence labels used on this page:

| label | meaning |
|---|---|
| **VERIFIED IN THIS SESSION** | recomputed or re-read from repository bytes or a public API in this session |
| **REPRODUCED LOCALLY** | executed in this session's disposable container against a local disposable database |
| **OBSERVED ON THE PUBLIC DEPLOYMENT** | read from the live host over its public URL (**nothing on this page**) |
| **SOURCE CLAIM** | stated by an earlier committed record and not re-derived here |
| **NOT VERIFIED** | not checked, with the reason |

## 1. The weakness being addressed

The committed v2 release-condition capture,
`docs/effect-sets/runs-v2/20260924T214352744301+0000-scored.json`, records
`working_tree_dirty: true`. Its own record explains why: the runner reads `git status --porcelain`
*including untracked files*, and eleven known untracked artefacts were present, while the tracked
tree was clean. That explanation is a **SOURCE CLAIM**. The capture cannot prove it by itself,
because the flag does not tell a dirty tracked file apart from an untracked one. That capture is
left exactly as it is. Its sha256 is re-verified below.

## 2. The protocol decision: no second scored run

[effect-set-run-protocol.md](effect-set-run-protocol.md) recognises two kinds of run and only two:

- A **scored** run is the exact command with `--scored`, over all sixteen scenarios, taken *with
  intent to record*. Its result is published as the number.
- A **harness-development** run is everything else. It *"may happen freely"*. It is *"never scored"*
  and *"never published as X/16"*, and it writes a capture marked `development`.

The v2 predeclaration, [effect-set-manifest-v2.md](effect-set-manifest-v2.md) §7, fixed the release
condition as a run taken **"exactly once"**, and says that *"the run is not repeated"*. The
release-condition record says it *"was not repeated"*.

A second `--scored --manifest v2` would therefore break the predeclaration. It would create two
scored v2 results, and any reader would be free to pick between them, which is the best-of-N the
protocol exists to prevent. It would also contradict the committed statement that the run was taken
once. **It was not taken.**

What the protocol does permit, and what materially strengthens the record, is a
**harness-development run from a provably clean checkout at the release-condition run's own
implementation SHA**. It does not re-score anything. It shows whether the same source, from a tree
with no tracked or untracked modification at all, observes the same per-scenario behaviour. It runs
on a different operating system, a different Python patch release and a different machine. It was
predeclared before any scenario executed, as follows:

```text
Predeclared 2026-09-28T14:16:07Z, before any effect-set execution in this session.
One harness-development run (no --scored) against manifest v2, in a clean detached worktree at
ec76050389e56cd205bdc8dd6d23e3938dc20d7f, with --capture-directory outside the worktree:
  uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py --manifest v2 --capture-directory <scratch>/captures
Its capture is published verbatim whatever it says, is not a score, carries no X/16, and is not repeated.
Amended 2026-09-28T14:18:40Z, AFTER the v2 development run above had finished and its result was seen:
one further harness-development run (no --scored) against manifest v1, same worktree, same database,
to check independently the owner's CI reading that S12 ord-e/task_hold is the only v1 difference.
Published verbatim whatever it says; not a score; not repeated.
```

The second paragraph was added **after** the v2 run had finished and its result was seen, and it is
disclosed as such. It adds a run against the *other* manifest. The reason is to check
independently a statement the release-condition page records as the owner's reading and says it did
not re-read: that under v1 the same code differs only at S12's `ord-e/task_hold`.

## 3. Source identity (VERIFIED IN THIS SESSION)

| item | value | how |
|---|---|---|
| release-condition implementation | `ec76050389e56cd205bdc8dd6d23e3938dc20d7f` | `git rev-parse ec76050` after `git fetch --unshallow origin main` |
| frozen repository release SHA | `56c302366b3ddc0d824c1588a4a9ddbd193ed891` | `git rev-parse 56c3023` |
| frozen deployed product / image SHA | `4529a802e34eff02f28fa25e12d382c50bf7cab1` | `git rev-parse 4529a802e34e` |
| `scenarios.v2.json` committed bytes, sha256 | `d4d1df809dde16531a9118824173148bd34af2a8e7b8a3b37c84add967d92f01` | `git show <sha>:docs/effect-sets/scenarios.v2.json \| sha256sum` at `ec76050`, `56c3023` and `430a269`: identical |
| `scenarios.v1.json` committed bytes, sha256 | `e9d828cbb8366d5823a74e151d28a2f50848a1c1586fef185f9c6b84468fa00b` | same, identical at all three |
| v2 canonical content hash | `77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd` | `verify_effect_set_manifest.py --manifest v2`: *coherent*; `run_effect_sets.py --check --manifest v2` in the clean worktree: exit `0`, *identity intact* |
| v1 canonical content hash | `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` | `verify_effect_set_manifest.py`: *coherent* |
| runner `scripts/run_effect_sets.py` | `RUNNER_VERSION` `1.1.0`; blob sha256 prefix `041276c1ffdbadc4` | identical at `ec76050`, `56c3023` and `430a269` |
| verifier, scenario suite | sha256 prefixes `b2c8a0e832b8a2be`, `dea92db392b77697` | identical at all three. `git diff --stat ec76050 HEAD -- apps/backend/tests/` adds only `test_demo_contract.py`, which the runner does not execute |
| committed v2 scored capture and log | `3f8b9fcf698065eff52d4a01152925de3e0849bc4631329970f5cf7ec4f4adbf`, `8e790b98496e180db50e0fdd707c7b6111dff9ff12e68d6e7effc1d43dac3892` | `sha256sum`, matches the prefixes the release-condition page publishes. **Unmodified** |

Product-path equivalence, as git tree/blob ids. These are identical at `4529a802e34e`, `ec76050`,
`56c3023` and `430a269`, and they match the table in [g8-closeout.md](g8-closeout.md) §3:
`apps/backend/src` `d9cfe5103751`, `apps/backend/alembic` `4ab26dc9cce0`,
`apps/backend/alembic.ini` `60fcf350bb29`, `apps/backend/pyproject.toml` `82643ac4494e`,
`apps/frontend` `68368bf7d8a4`, `apps/order-simulator` `35f61166f77b`, `packages`
`b9191b88363c`, `docker` `100df96036b8`, `.dockerignore` `6992bd1c91d0`, `deploy`
`2bbb1357a5a4`, `uv.lock` `ed0dcf1e4910`.

## 4. The execution (REPRODUCED LOCALLY)

Environment, stated plainly:

- A Linux cloud container. The tree was a detached `git worktree` at `ec76050` outside the main
  checkout, and `git status --porcelain --untracked-files=all` printed nothing immediately before
  and after each run. The generated `docker/env/*.env`, `.venv` and `__pycache__` are all ignored
  by `ec76050`'s own `.gitignore`. Each capture was written with `--capture-directory` outside the
  worktree, so writing the record could not dirty the tree it recorded.
- The database was PostgreSQL 16 from the compose `postgres` service alone, on a fresh volume.
  **Deviation from the clean-clone command:** `docker compose up --wait` of the whole stack could
  not build the backend image, because this session's egress proxy refused the
  `ghcr.io/astral-sh/uv` layer. So the schema was migrated from the host with the repository's own
  Alembic, `with_local_env.py -- uv run alembic -c apps/backend/alembic.ini upgrade head`, to
  `0009_human_plan_approval (head)`. No `worker`, `api` or `mcp` container was ever started. The
  scenarios build their own API, MCP server, worker and order-system simulator in process.
- `host.env` was freshly generated by `bootstrap_local_env.py` and names `PP_LLM_PROVIDER=fake`. The
  capture's `model_provider_configured: true` reflects that non-empty value. The container also
  carries `AWS_ACCESS_KEY_ID`, which STS rejects as `InvalidClientTokenId`, and this is why the
  capture says `aws_credentials_configured: true`. No scenario constructs a semantic provider or
  reaches AWS. See the release-condition page §6 for the same reasoning.

### 4.1 Against v2

```bash
uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py --manifest v2 --capture-directory <scratch>/captures
```

Exit `0`. `kind: development`, `score: null`, `implementation_sha: ec76050…`,
**`working_tree_dirty: false`**, runner `1.1.0`, manifest `77286e77…b0dd`. Every scenario's
recorded outcome is `PASS`, with an empty diff list. There is no `HARNESS_FAILURE`. Capture sha256
`3098858dc41a076e1b2ff728d5fa8556c56fd52b449c914469a3445adbb39980`, reproduced verbatim:

```json
{
  "command": [
    "scripts/run_effect_sets.py",
    "--manifest",
    "v2",
    "--capture-directory",
    "/tmp/claude-0/-home-user-PromisePatch/0e846537-f8e3-41be-9de6-019b7a782860/scratchpad/captures"
  ],
  "environment": {
    "aws_credentials_configured": true,
    "model_provider_configured": true,
    "platform": "Linux-6.18.44-fc-v37-x86_64-with-glibc2.39",
    "python": "3.12.3",
    "transport_fixtures": "The customer channel and the external order system are local fixtures driven in process. Local replay is not proof of live delivery."
  },
  "finished_at": "2026-09-28T14:18:21.384373+00:00",
  "implementation_sha": "ec76050389e56cd205bdc8dd6d23e3938dc20d7f",
  "kind": "development",
  "manifest": "promisepatch-effect-sets",
  "manifest_sha": "77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd",
  "manifest_version": "2.0.0",
  "outcomes": [
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S01"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S02"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S03"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S04"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S05"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S06"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S07"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S08"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S09"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S10"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S11"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S12"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S13"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S14"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S15"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S16"
    }
  ],
  "protocol": "docs/effect-set-run-protocol.md",
  "runner_version": "1.1.0",
  "score": null,
  "started_at": "2026-09-28T14:17:03.424056+00:00",
  "unwired": [],
  "wired": [
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
    "S16"
  ],
  "working_tree_dirty": false
}
```

### 4.2 Against v1

```bash
uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py --manifest v1 --capture-directory <scratch>/captures-v1
```

Exit `1`. `working_tree_dirty: false`. S12 is `FAIL` with exactly three differences, all
`ord-e/task_hold` at `CONFIRMED`, `CONSENT_SETTLED` and `SETTLED`, expected `1` and observed `0`.
Every other scenario's recorded outcome is `PASS`. Capture sha256
`24abd10e66694ac9ebe926edbb5d4480cfd9a1dc87ea89e6095a3c7dad0d4d23`, reproduced verbatim:

```json
{
  "command": [
    "scripts/run_effect_sets.py",
    "--manifest",
    "v1",
    "--capture-directory",
    "/tmp/claude-0/-home-user-PromisePatch/0e846537-f8e3-41be-9de6-019b7a782860/scratchpad/captures-v1"
  ],
  "environment": {
    "aws_credentials_configured": true,
    "model_provider_configured": true,
    "platform": "Linux-6.18.44-fc-v37-x86_64-with-glibc2.39",
    "python": "3.12.3",
    "transport_fixtures": "The customer channel and the external order system are local fixtures driven in process. Local replay is not proof of live delivery."
  },
  "finished_at": "2026-09-28T14:19:54.423222+00:00",
  "implementation_sha": "ec76050389e56cd205bdc8dd6d23e3938dc20d7f",
  "kind": "development",
  "manifest": "promisepatch-effect-sets",
  "manifest_sha": "d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc",
  "manifest_version": "1.0.0",
  "outcomes": [
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S01"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S02"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S03"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S04"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S05"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S06"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S07"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S08"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S09"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S10"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S11"
    },
    {
      "diffs": [
        {
          "aspect": "effects",
          "checkpoint": "CONFIRMED",
          "expected": "1",
          "observed": "0",
          "subject": "ord-e/task_hold"
        },
        {
          "aspect": "effects",
          "checkpoint": "CONSENT_SETTLED",
          "expected": "1",
          "observed": "0",
          "subject": "ord-e/task_hold"
        },
        {
          "aspect": "effects",
          "checkpoint": "SETTLED",
          "expected": "1",
          "observed": "0",
          "subject": "ord-e/task_hold"
        }
      ],
      "outcome": "FAIL",
      "reason": "",
      "scenario": "S12"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S13"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S14"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S15"
    },
    {
      "diffs": [],
      "outcome": "PASS",
      "reason": "",
      "scenario": "S16"
    }
  ],
  "protocol": "docs/effect-set-run-protocol.md",
  "runner_version": "1.1.0",
  "score": null,
  "started_at": "2026-09-28T14:18:41.157732+00:00",
  "unwired": [],
  "wired": [
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
    "S16"
  ],
  "working_tree_dirty": false
}
```

### 4.3 An independent corroboration on current `main` (VERIFIED IN THIS SESSION)

GitHub Actions run `36431878482`, *effect sets (expected red until 16/16)*, ran on the `push` of
`430a269` to `main` on 2026-09-28. Job `108959841753`'s log, read through the GitHub API, ends:

```text
FAILED apps/backend/tests/test_effect_sets.py::test_s12_external_edit_adds_dependency_before - AssertionError: S12: FAIL
  CONFIRMED/effects ord-e/task_hold: expected 1, observed 0
  CONSENT_SETTLED/effects ord-e/task_hold: expected 1, observed 0
  SETTLED/effects ord-e/task_hold: expected 1, observed 0
1 failed, 15 passed in 45.38s
```

That job judges v1, so its red is expected. This is a pytest count, which the protocol classifies
as development evidence, and it is not a score.

## 5. What this establishes, and what it does not

It establishes three things:

- **The clean committed source reproduces the same per-scenario behavior, so the historical
  dirty flag no longer creates an outcome-reproducibility concern.** The same
  implementation SHA was run from a tree with nothing modified and nothing untracked. It recorded
  the same per-scenario outcome as the scored v2 capture, scenario by scenario, with no diff. That
  is the strongest clean-source reproduction the protocol allows.
- **The v2 result depends only on the label.** From the same clean source, v1 differs at S12's
  `ord-e/task_hold` and nowhere else. This agrees with the owner's reading recorded as a SOURCE
  CLAIM in [g8-effect-set-release-condition.md](g8-effect-set-release-condition.md) §4, and with CI
  on current `main` (§4.3).
- **The observation is not tied to one machine.** The scored run was taken on Windows with Python
  `3.12.0`. This one ran on Linux with Python `3.12.3`, against a freshly bootstrapped database.

It does **not** establish, and nothing here may be read as:

- **a new score.** Neither run is scored, and neither has a denominator. The v2 release condition
  remains the single 2026-09-24 capture, and the headline remains **11/16** against v1;
- a claim that the original benchmark became 16/16;
- independent validation of the labels. They are developer-authored, finite and public, as v2's
  own `provenance` says;
- anything about the deployed host. Every scenario ran against local fixtures, and local replay is
  not proof of live delivery.

## 6. Not verified

- **The eleven untracked artefacts** named by the release-condition page are not present in this
  clone, so their contents were not examined. They are only on the owner's machine.
- **The full `docker compose up --wait` path** was not exercised, because the image build was blocked
  by egress policy (§4).
- **No scored run was taken**, by decision (§2).
