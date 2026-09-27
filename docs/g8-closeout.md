# G8 closeout

Date: **2026-09-27**. This page closes G8, *release proof*. It records the freeze and closeout
session named in [g8-evidence-packaging.md](g8-evidence-packaging.md) §6 step 3 and
[g8-remaining-gaps-audit.md](g8-remaining-gaps-audit.md) §10 action 5. It closes rows 13 and 15,
the last two PARTIAL rows, and edits no earlier record.

**Two SHAs, and neither is the other:**

| role | SHA | what it is |
|---|---|---|
| **frozen repository release SHA** | **`56c302366b3ddc0d824c1588a4a9ddbd193ed891`** | the commit that the release's CI, feature freeze and provenance are stated against |
| **frozen deployed product / image SHA** | **`4529a802e34eff02f28fa25e12d382c50bf7cab1`** (`4529a802e34e`) | the commit the running image was built from, and the one R1–R5 ran on |

Their deployable product paths are tree-identical (§3). The commit that adds this page is a
docs-only closeout commit on top of `56c3023`. **It does not replace the release SHA.**

**No product code, test, image, deployment, migration, benchmark result or manifest changed.**
This session sent no Telegram message, called no model and took no scored run. It did not rerun
the effect sets or touch SUR-1. It made no worktree, no clone and no cleanup. Every AWS call was
a Describe, Get or List. No host session was opened, no CI was dispatched, no tag or GitHub
Release was created, and nothing was pushed.

## 1. Entry

| check | measured |
|---|---|
| `main` / `origin/main` | both `56c302366b3ddc0d824c1588a4a9ddbd193ed891`, after `git fetch` |
| tracked tree | clean |
| untracked | the eleven known artefacts, untouched: `REMAINING_WORK_ASSESSMENT.md`, four `docs/effect-sets/runs/20260917T…-development.json`, and `docs/rehearsals/runs/dr01-a/` … `dr01-f/` |
| AWS identity | `aws sts get-caller-identity --profile promisepatch`: account `265243686715`, `arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment` |

Read before acting: the G8 and freeze text of `new_roadmap.md`, `CLAUDE.md`, the evidence
packaging page, the demo-contract runner page, the provenance page and the Phase 7 closeout.
`ARCHITECTURE_PLAN.md` was searched for any release-SHA, freeze, tag or GitHub Release requirement
and holds none.

## 2. Row 13: exact release SHA passes required CI

**Literal requirement** (`new_roadmap.md`, G8): *"Exact release SHA passes required CI including
new browser workflow tests."*

The roadmap does not name a trigger. The audit and the packaging page planned a
`workflow_dispatch` only because `pr` ignores `**.md`, so a docs-only head gets no run at all. The
push of `bec3f8f..56c3023` carried code, so `pr` ran on push with `head_sha` equal to the
release SHA. **No dispatch was needed and none was made.**

| | |
|---|---|
| workflow | `pr`, `.github/workflows/pr.yml`, run number 165 |
| run id | **`36310794944`**, <https://github.com/Asembris/PromisePatch/actions/runs/36310794944> |
| event / branch / attempt | `push` / `main` / `1` |
| `head_sha` | `56c302366b3ddc0d824c1588a4a9ddbd193ed891`, exactly |
| created / finished | `2026-09-27T09:53:24Z` / `2026-09-27T10:13:49Z` |
| conclusion | **`success`, 13 of 13 jobs** |

| job | conclusion | started → completed (UTC) |
|---|---|---|
| ruff | success | 09:53:27 → 09:53:35 |
| mypy | success | 09:54:02 → 09:54:30 |
| pytest + coverage | success | 09:53:27 → 09:54:00 |
| order contract + order system | success | 09:53:26 → 09:53:40 |
| semantic boundary | success | 09:53:26 → 09:53:41 |
| mcp protocol | success | 09:53:27 → 09:53:53 |
| semantic evaluation | success | 09:53:26 → 09:55:10 |
| hypothesis (ci profile) | success | 09:53:28 → 09:54:32 |
| import-linter | success | 09:53:27 → 09:53:38 |
| **whole-stack browser** | **success** | 09:53:27 → 09:57:08 |
| backend + postgres | success | 09:53:27 → 10:13:48 |
| frontend | success | 09:53:26 → 09:54:09 |
| gitleaks | success | 09:53:26 → 09:53:34 |

The *new browser workflow tests* are the `whole-stack browser` job, green on this SHA. The
demo-contract runner's tests, `apps/backend/tests/test_demo_contract.py` (`integration`), are
collected by `backend + postgres`, whose step is `uv run pytest apps/backend
--ignore=apps/backend/tests/test_effect_sets.py`. That meets the runner page's open condition,
*`pr` green on a SHA that contains the runner*.

The effect-set workflow fired on the same push: run `36310795058`, `failure` at step *The sixteen
frozen scenarios*. That is the expected red, because it judges v1, where S12 fails by decision
(§6). It is not the product gate and was not dispatched.

Read through the public GitHub REST API, unauthenticated
(`/actions/runs?head_sha=…`, `/actions/runs/36310794944/jobs`).

**Row 13: CLOSED.**

## 3. AWS read-only reconciliation, and the repository diff

### Control plane, read 2026-09-27 around 10:50–10:59Z

Describe, Get and List only. No `DetectStackDrift` and no host session.

| | measured | against the frozen RC |
|---|---|---|
| stack `promisepatch-prod` | `UPDATE_COMPLETE`, last updated `2026-09-24T16:00:45Z`. The six latest events are all `AWS::CloudFormation::Stack`, the `16:00:45Z` and `12:54:54Z` parameter-only updates. **No event after them. 0 change sets.** `DriftInformation` `NOT_CHECKED` | identical to [phase7-closeout.md](phase7-closeout.md) §3 |
| image tag | `ImageTag` parameter `4529a802e34e`; `DeclaredImageTag` output `4529a802e34e`; SSM `/promisepatch/prod/image-tag` `4529a802e34e`, **version 9**, modified `2026-09-24T15:59:22Z` | identical |
| SSM `compose` / `caddyfile` | versions 14 / 13, modified `2026-09-24T15:59:16Z` / `15:59:19Z`. Every other parameter under `/promisepatch/prod` is at the version it had by 2026-09-21. Names and versions only; no value decrypted | identical |
| instance | `i-087c742587f83d61d`, `running`, `t4g.small`, `ami-0fa4996c14e7d501e`, launched `2026-09-18T10:19:33Z`, IMDSv2 `required`, hop limit 2, `184.194.40.87` | identical |
| volume | `vol-0f330aaa62e637ef6`, `in-use` on that instance, 30 GiB, encrypted, created `2026-09-13T18:33:34Z` | identical |
| RDS | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, not public, encrypted, PostgreSQL 16.13, created `2026-09-11T11:19:51Z`, **no pending modifications** | identical |
| log group | `/promisepatch/prod`, 14-day retention, 28.7 MB stored | grown from 25.8 MB, as logging does |
| ECR | `ecr:DescribeImages` and `ecr:DescribeRepositories` **denied** to this role | not read; IAM not broadened (§8) |

### The deployment itself, read over its public URL

| | measured |
|---|---|
| `GET /healthz` | `image: 4529a802e34e`, `boot_id 3e90146d-1484-40e9-8ab8-02cda046a664` |
| `GET /readyz` | ready; database reachable as `promisepatch_app`; migrations at head, `0009_human_plan_approval`; fixture `hollow-oak`, anchor `2026-09-24T20:54:53.431361Z`, digest `850c7cea…cbebe4` |

The `api` boot id is the one the `4529a802e34e` rollout produced and Phase 7 recorded. **The
`api` process has not restarted since the RC was deployed.** The fixture anchor and digest are
R5's own (`g8-rehearsal-r5.md`), so **nothing re-seeded the world after R5.** No deployment and
no stack update happened after the frozen RC.

### `git diff 4529a802e34e..56c3023`: 25 commits, classified

| class | paths | effect on the deployed image |
|---|---|---|
| docs | 22 files under `docs/`, and `CLAUDE.md` | none. No Dockerfile copies `docs/` or `CLAUDE.md` |
| effect-set tooling | `scripts/run_effect_sets.py`, `scripts/verify_effect_set_manifest.py`, `scripts/tests/test_effect_set_manifest.py`, `scripts/tests/test_run_effect_sets.py`, `apps/backend/tests/_effect_sets.py`, `apps/backend/tests/_effect_set_judge.py`, `apps/backend/tests/test_effect_set_judge.py`, the v2 manifest and its capture | none. `scripts/` is not copied into any image. Backend tests are copied into the build stage only, and the wheel packages `src/promisepatch` alone (`apps/backend/pyproject.toml`, `[tool.hatch.build.targets.wheel]`) |
| demo-contract runner | `scripts/demo_contract.py`, `apps/backend/tests/test_demo_contract.py` | none, for the same reasons |
| lint configuration | root `pyproject.toml`: five added lines, one `[tool.ruff] extend-exclude` and its comment (`b5cf0d3`, `cfe9937`) | none. It is copied into the build stage, but `uv sync --frozen` reads no `[tool.ruff]` table, and the runtime stage copies only `/app/.venv`, the migrations and the UI bundle |

Deployable product paths, compared as git tree/blob ids at both SHAs, are **all identical**:

| path | id at both SHAs |
|---|---|
| `apps/backend/src` | `d9cfe5103751` |
| `apps/backend/alembic` | `4ab26dc9cce0` |
| `apps/backend/alembic.ini` | `60fcf350bb29` |
| `apps/backend/pyproject.toml` | `82643ac4494e` |
| `apps/frontend` | `68368bf7d8a4` |
| `apps/order-simulator` | `35f61166f77b` |
| `packages` | `b9191b88363c` |
| `docker` (the three Dockerfiles) | `100df96036b8` |
| `.dockerignore` | `6992bd1c91d0` |
| `deploy` | `2bbb1357a5a4` |
| `uv.lock` | `ed0dcf1e4910` |
| `evals` | `903fcb85e403` |
| `.github` | `14608ea98775` |

Reproduce with `git rev-parse 4529a802e34e:<path>` against `git rev-parse 56c3023:<path>`.

**Reconciliation: clean.** `56c3023` is the frozen repository release SHA and `4529a802e34e` the
frozen deployed product/image SHA. What `56c3023` would build is what `4529a802e34e` built, apart
from the image's own `PP_IMAGE_TAG` label. What runs is `4529a802e34e`, unchanged since the RC.

## 4. Why the post-RC commits do not invalidate R1–R5

The rule, from [g8-evidence-packaging.md](g8-evidence-packaging.md) §4: *"If closing any PARTIAL
row produces a new image, the rehearsal count restarts on the new SHA."* No new image was produced:

1. **The rehearsed artefact is the running artefact.** R1–R5 ran on `4529a802e34e`. `/healthz`
   still reports `4529a802e34e`, and the `api` boot id is unchanged since that rollout.
2. **The world is the one R5 left.** The fixture anchor and digest are R5's, and no stack event,
   SSM version or instance change is dated after 2026-09-24 16:00:45Z.
3. **Nothing deployable moved.** Every product path is tree-identical (§3). The 25 commits are
   docs, effect-set tooling, the demo-contract runner and its tests, and a lint exclusion.
4. **The v2 16/16 run was taken on code product-identical to the RC** (`ec76050`, §6), and the
   runner changed no product path ([g8-demo-contract-runner.md](g8-demo-contract-runner.md)).

## 5. Row 15: features frozen

**Literal requirement** (`new_roadmap.md`, G8): *"Freeze features."*

The audit held this PARTIAL for one reason: the freeze could not be final while row 19 might move
the release SHA. Row 19 closed against v2 with no product change, row 13 is now green on the exact
SHA, and the reconciliation is clean.

> **Feature freeze, declared 2026-09-27, at repository release SHA
> `56c302366b3ddc0d824c1588a4a9ddbd193ed891`, deployed as product/image SHA `4529a802e34e`.**
>
> From this SHA on:
> - no product feature is added;
> - no product behaviour changes;
> - only submission, evidence and documentation corrections are allowed.
>
> A later change to any deployable product path in §3's table **invalidates this freeze**. That
> includes `apps/backend/src`, `apps/backend/alembic`, `apps/frontend`, `apps/order-simulator`,
> `packages`, `docker`, `deploy`, `uv.lock` and the dependency tables of any `pyproject.toml`.
> Such a change needs a new release SHA, `pr` green on it, a new deployment and five new deployed
> rehearsals. The roadmap reopens this only for *"a reproduced correctness or eligibility blocker
> that fits no existing gate, or a documented official rule change"*.

To check the freeze at any later commit `X`:

```bash
git diff --name-only 56c302366b3ddc0d824c1588a4a9ddbd193ed891 X -- apps/backend/src apps/backend/alembic apps/backend/alembic.ini apps/backend/pyproject.toml apps/frontend apps/order-simulator packages docker .dockerignore deploy uv.lock
```

The output must be empty.

**Row 15: CLOSED.**

## 6. The effect sets: two numbers, unchanged

- **Headline, immutable: 11/16.** The first scored run,
  `docs/effect-sets/runs/20260915T163255509125+0000-scored.json`, taken against the frozen v1
  manifest `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` at implementation
  `e81b5aa3af10`, runner `1.0.0`. S06, S07, S08, S12 and S13 failed. Its denominator is
  permanently sixteen. `scenarios.v1.json` and every file under `docs/effect-sets/runs/` are
  unchanged from `4529a802e34e` to `56c3023` (`git diff --quiet`). The verifier re-run today
  prints `content_hash d41f5afc…2cdc` and *"coherent"*.
- **G8 release condition: 16/16 against the v2 label correction**, a separate, versioned
  document. The manifest is `77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd`
  (R1 conditional on work not having started; S12's hold is the only label moved). It was taken
  once, `2026-09-24T21:43:52Z`, at `ec76050389e5` with runner `1.1.0`, and exited `0`. Its
  capture is `docs/effect-sets/runs-v2/20260924T214352744301+0000-scored.json`, committed bytes
  sha256 `3f8b9fcf…adbf`. See [g8-effect-set-release-condition.md](g8-effect-set-release-condition.md).

16/16 never replaces 11/16. The effect-set CI workflow stays red because it judges v1, and that
red is recorded, not repaired.

## 7. Contribution provenance at the release SHA

Restated at `56c302366b3ddc0d824c1588a4a9ddbd193ed891`, per
[g8-contribution-provenance.md](g8-contribution-provenance.md) §4. Window, from `new_roadmap.md`
§2: opens **2026-08-31 17:15 UTC**, closes **2026-10-23 19:00 UTC**.

| fact | value | command |
|---|---|---|
| commits | **793**, 0 merges | `git rev-list --count 56c3023`; `git rev-list --merges --count 56c3023` |
| root | one, `1799971440b3` | `git rev-list --max-parents=0 56c3023` |
| author dates | earliest `2026-09-02T22:25:53+02:00`, latest `2026-09-27T11:52:06+02:00` | `git log --format=%aI 56c3023 \| sort` |
| committer dates | the same bounds | `git log --format=%cI 56c3023 \| sort` |
| days with commits | 25, 2026-09-02 to 2026-09-27 | `git log --date=short --format=%ad 56c3023 \| sort -u` |
| identity | one, `Asembris`, author and committer on all 793 | `git log --format='%an' 56c3023 \| sort \| uniq -c` |
| `Co-Authored-By` trailers | 14 commits, unchanged | `git log --format='%(trailers:key=Co-Authored-By,valueonly)' 56c3023` |
| engine history | 17 commits touch `packages/promise-graph/`, unchanged | `git rev-list --count 56c3023 -- packages/promise-graph` |
| since the provenance page | 10 commits after `b5cf0d3` (783 + 10 = 793) | `git rev-list --count b5cf0d3..56c3023` |
| since the deployed RC | 25 commits after `4529a802e34e` | `git rev-list --count 4529a802e34e..56c3023` |
| GitHub | `public`, not a fork, `main`, `Apache-2.0`, created `2026-09-02T15:40:04Z`, pushed `2026-09-27T09:53:22Z` | `GET /repos/Asembris/PromisePatch`, unauthenticated |

**All 793 commits are dated inside the window.** The latest is 26 days 9 hours before it closes.
The limits in the provenance page's §3 stand unchanged: a commit date is not a writing date, no
sole-authorship or originality claim is made, and no upstream endorsement is claimed. The count
here is the release SHA's. This closeout commit extends the history by one docs-only commit and
does not move it.

## 8. Known caveats

- **ECR was not read.** `ecr:DescribeImages` and `ecr:DescribeRepositories` are denied to
  `PromisePatchDeveloperRole`, and IAM was not broadened. The deployed image is evidenced by
  `/healthz`, the stack parameter and output, and the SSM tag, not by a registry digest.
- **The host was not entered.** No `ssm:StartSession` was opened, so the container census and the
  host `boot_id` were not re-read. The last container census is R5's, all on `4529a802e34e`.
  `/healthz` shows only that `api` has not restarted.
- **Drift is `NOT_CHECKED`.** `DetectStackDrift` starts an operation and was not called.
- **Smoke is 9/12 from this operator machine**, and the three gaps are the local TLS-intercepting
  proxy, not the deployment ([CLAUDE.md](../CLAUDE.md)). Smoke was not re-run here.
- **`deploy.sh stack` cannot release** against the drifted stack template. The RC went out by a
  parameter-only change set, a documented one-off ([non-destructive-release.md](non-destructive-release.md) §10.1).
- **No refusal path has been exercised live.** `STALE`, `EXPIRED`, `UNAUTHORIZED` and `NOOP` are
  proved by tests only; a live STALE is not owed (audit §4).
- **The restore env union is a defect recorded unfixed.** No deployed container holds every
  setting `pp restore-demo-world` needs ([demo-world-restore.md](demo-world-restore.md)).
- **CloudWatch history** still holds lines written before the chat-id redaction and two spent,
  non-actionable approval tokens, until the 14-day retention expires them.
- **Telegram inbound is deliberately unbuilt.** A customer answers only through the signed web link.
- **The v2 capture records `working_tree_dirty: true`** because of untracked files that are not
  code. It is disclosed in its own record.
- **The effect-set suite is developer-authored, finite and public**, not an independently
  validated or held-out benchmark. Both evaluation holdouts remain sealed.
- **SUR-1 says nothing comparative about models**: arms B and C called the model zero times.
- **G7 closed with the demo-narrative comprehension check not performed**, declined by the owner.
- **Working-tree hashes differ from committed hashes** for LF files, because `core.autocrlf` is
  `true` here. Hash the committed bytes (`git show <sha>:<path> | sha256sum`).
- **Nothing in this session was pushed.** `56c3023` is on `origin/main`, and the closeout commit
  is local.

## 9. The G8 matrix, final

The rows and their literal requirements are the audit's. The first two status columns are
copied from [g8-evidence-packaging.md](g8-evidence-packaging.md) §4.

| # | requirement (short) | 2026-09-24 audit | before this page | **final** | closed by |
|---|---|---|---|---|---|
| 1 | demo-contract runner | PARTIAL | CLOSED | **CLOSED** | [g8-demo-contract-runner.md](g8-demo-contract-runner.md); `pr` green on the SHA containing it, §2 |
| 2 | eleven adversarial faults | CLOSED | CLOSED | **CLOSED** | [g8-remaining-gaps-audit.md](g8-remaining-gaps-audit.md) §3 |
| 3 | stale approved plan refuses | CLOSED | CLOSED | **CLOSED** | audit §4 |
| 4 | five deployed rehearsals | CLOSED on `4529a802e34e` | CLOSED | **CLOSED on `4529a802e34e`** | R1–R5; still valid, §4 |
| 5 | whole-delivery changes the plan | CLOSED | CLOSED | **CLOSED** | audit |
| 6 | unrelated edits leave unrelated work | CLOSED | CLOSED | **CLOSED** | audit |
| 7 | protected-order zero, attributed | CLOSED | CLOSED | **CLOSED** | audit |
| 8 | head-of-line measured and corrected | CLOSED | CLOSED | **CLOSED** | audit §7 |
| 9 | curated redacted DEVELOPMENT evidence | OPEN | CLOSED | **CLOSED** | [g8-development-evidence.md](g8-development-evidence.md) |
| 10 | public license/source | CLOSED | CLOSED | **CLOSED** | re-read today: `public`, `Apache-2.0`, §7 |
| 11 | standalone engine from a clean clone | PARTIAL | CLOSED | **CLOSED** | [g8-standalone-fresh-clone-proof.md](g8-standalone-fresh-clone-proof.md) |
| 12 | contribution provenance within window | PARTIAL | CLOSED | **CLOSED** | [g8-contribution-provenance.md](g8-contribution-provenance.md); restated at 793, §7 |
| 13 | exact release SHA passes required CI | PARTIAL | PARTIAL | **CLOSED** | this page §2: `pr` `36310794944`, 13/13, on `56c3023` |
| 14 | deployed version verified | CLOSED | CLOSED | **CLOSED** | re-read today: `/healthz` `4529a802e34e`, §3 |
| 15 | features frozen | PARTIAL | PARTIAL | **CLOSED** | this page §5 |
| 16 | manifest frozen and published | CLOSED | CLOSED | **CLOSED** | verifier re-run today, §6 |
| 17 | immutable first run, 11/16 | CLOSED | CLOSED | **CLOSED** | §6 |
| 18 | every fix SHA published, rerun separately | PARTIAL | CLOSED | **CLOSED** | [g8-effect-set-release-condition.md](g8-effect-set-release-condition.md) §3 |
| 19 | 16/16 on the release candidate | OPEN | CLOSED, against v2 | **CLOSED, against v2** | release-condition page §6 |
| 20 | effect-set clean-clone command tested | PARTIAL | CLOSED | **CLOSED** | [g8-effect-set-fresh-clone-proof.md](g8-effect-set-fresh-clone-proof.md) |
| 21 | demo funnel with 0/U and effect counts | PARTIAL | CLOSED | **CLOSED** | [g8-demo-funnel.md](g8-demo-funnel.md) |
| 22 | developer-authored disclosure | CLOSED | CLOSED | **CLOSED** | audit |

**Counts: 22 rows. 22 CLOSED, 0 PARTIAL, 0 OPEN.**

## 10. Verdict

**G8 is CLOSED** at repository release SHA `56c302366b3ddc0d824c1588a4a9ddbd193ed891`, deployed as
product/image SHA `4529a802e34e`, with the feature freeze in force.

The roadmap names the next gate, G9: *submission*. That work is to present the frozen release
accurately: the README, one-pager and video each surface the three measured numbers, and the
public proof index, anonymous reproduction and challenge fields are completed. The three numbers
are the immutable 11/16 beside the separate 16/16 release condition, the R1–R5 funnel with 0/U,
and the G7 voice-turn K/10. Under the freeze that work may change submission material,
evidence and docs, and **no product path**.
