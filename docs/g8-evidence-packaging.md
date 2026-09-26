# G8 evidence packaging

Date: **2026-09-26**. Entry at `b5cf0d38c97b6a3fe4535070ecdc6b29d51666f5`: `main` equal to
`origin/main`, and `pr` run `36064335857` **green, 13 of 13 jobs**, on that exact SHA. The
effect-set workflow on the same SHA, run `36064335907`, is red at step *The sixteen frozen
scenarios*, as expected: it judges v1, where S12 fails by decision. The frozen deployed release
candidate is **`4529a802e34e`**.

This page records the evidence-packaging session named in
[g8-remaining-gaps-audit.md](g8-remaining-gaps-audit.md) §10 action 4. It updates that audit's
matrix **beside** it: the audit and every rehearsal, run and closeout record are left exactly as
committed.

**No product code, test, deployment, benchmark result or manifest changed.** There were no AWS
calls, deployment, Telegram sends, model calls or scored reruns. No worktree was made and nothing
was pushed.

## 1. The session, and the host crash inside it

The session ran in two sittings, separated by a Windows blue screen.

**Sitting 1.** Entry and CI checks; the DEVELOPMENT curation and its provenance checks; extraction
of the R1–R5 funnel counts. Then the one authorised fresh clone was made at
`D:\pp-g8-fresh-clone`, and the standalone-engine recipe began in it. **The host blue-screened
during the recipe's fifth command.** The cause is not established, and this page does not
attribute it to that command.

**Sitting 2**, after the reboot. Every earlier result was treated as unverified until it was
re-read from disk:

| checked | found |
|---|---|
| repository | HEAD `b5cf0d3` = `origin/main`; **no tracked change and no commit survived**; the eleven known untracked artefacts present and untouched |
| the one extra untracked path | `docs/development-evidence/g8-development-evidence.v1.json`, written before the crash. **Regenerated from the raw files: byte-identical** (`bd86f3b5…f58a`). Its generator survived in the session scratchpad, sha256 `aee15151…eba` |
| the raw DEVELOPMENT files | the regenerated package embeds their 36 hashes, so the byte-identity also proves the files are unchanged |
| the fresh clone | see §5 |
| Docker | daemon `29.1.3`; the six PromisePatch containers `healthy`. Not used by this session |

Sitting 2 ran one command at a time, created and deleted no bulk files, and installed nothing.

## 2. What this session produced

| commit | page | G8 row |
|---|---|---|
| `d6c5d16` | [g8-development-evidence.md](g8-development-evidence.md) and [development-evidence/g8-development-evidence.v1.json](development-evidence/g8-development-evidence.v1.json) | 9 |
| `1232a55` | [g8-demo-funnel.md](g8-demo-funnel.md) | 21 |
| `7f4b9e2` | [g8-contribution-provenance.md](g8-contribution-provenance.md) | 12 |
| this commit | this page, and a minimal current-state line in `CLAUDE.md` | 1, 11, 20 recorded; the matrix below |

### Findings recorded beside the historical records, not edited into them

- **Two challenger selection files were rewritten on 2026-09-22.** In the GPT-4o-mini one, the
  source header was replaced by a test fixture's (`source000001`). The six pairs are unchanged and
  re-derive exactly. What wrote them is not established here. See
  [g8-development-evidence.md](g8-development-evidence.md) §6.
- **Judge calls.** P4.8's final tally names 21 Nemotron judge calls, and the files hold 42: 21 of
  them judged `p48dev`.
- **Two vacuous summaries.** Zero-reading attempts `10245bb11ec9` and `8e88336120d3` have summaries
  reading `pass`. They are not results.
- **A run cited nowhere.** `10245bb11ec9`, a Haiku Stage-A attempt, was cited by run id in no
  earlier record.

## 3. The demo-contract ruling (row 1)

**The literal requirement.** `new_roadmap.md` §11 G8: *"Demo-contract runner uses the new
transport boundaries; no direct DB consent inserts. Fixture setup and fault injection are explicit
operator actions."*

**What the frozen design means by the noun.** `ARCHITECTURE_PLAN.md` defines it as an executable:

- §3 names it *"Demo-contract runner (`scripts/demo_contract.py`) | CLI | Executes the storyboard
  as assertions, including a real worker restart"*;
- its test table names *"Demo-contract | `scripts/demo_contract.py` | pytest + subprocess | The
  full storyboard with a real worker restart and zero writes for D/E/F"*;
- its CLI names `pp demo-contract` and `pp demo-contract --deployed`.

**What exists:**

- the predeclared protocol, [g8-rehearsal-preparation.md](g8-rehearsal-preparation.md) §3;
- the frozen read-only evidence reader `g8ev.py`, `c9731c8f…`;
- operator commands run by hand: `pp restore-demo-world`, `pp confirm-plan`, and
  `docker compose restart|stop|start worker`;
- a real customer press on the phone.

In R1–R5 that combination satisfied every constraint the bullet places on the runner:

- the new transport boundaries were used: real Telegram out, the signed-link HTTP route in;
- no consent row was ever inserted directly;
- fixture setup and fault injection were explicit operator actions.

**Ruling: row 1 stays PARTIAL.** The bullet's subject is a runner, and the frozen design says what
a runner is: a program that executes the storyboard **as assertions**. None of the existing parts
is one:

- the protocol is a document a person follows;
- the reader reads and asserts nothing;
- pass or fail was judged by a person against a table.

The effect-set harness is not one either. It injects its customer answer as a raw `inbox_events`
row and its faults programmatically, so it neither uses the deployed transport boundaries nor
makes injection an operator action.

Calling the manual protocol "the runner" would rename manual evidence to close a row, and that is
refused. **Nothing was built.** The remaining condition is exactly one of these:

- **(a)** the owner authorises implementing `scripts/demo_contract.py` / `pp demo-contract` under
  G8, which is implementation work;
- **(b)** the owner accepts that row 1 is unmet. `new_roadmap.md` §10 says *"A failed MUST cannot
  be renamed 'done'"*, so under (b) G8 cannot close.

## 4. The G8 matrix, as of this page

The rows and their literal requirements are the audit's. The 2026-09-24 column is the audit's
verdict, and the 2026-09-26 column is the status now, with the page that moved it.

| # | requirement (short) | 2026-09-24 audit | now | moved by |
|---|---|---|---|---|
| 1 | demo-contract runner | PARTIAL | **PARTIAL** | §3 above: a runner is required and was not built |
| 2 | eleven adversarial faults | CLOSED | CLOSED | |
| 3 | stale approved plan refuses | CLOSED | CLOSED | |
| 4 | five deployed rehearsals | CLOSED on `4529a802e34e` | CLOSED on `4529a802e34e` | |
| 5 | whole-delivery changes the plan | CLOSED | CLOSED | |
| 6 | unrelated edits leave unrelated work | CLOSED | CLOSED | |
| 7 | protected-order zero, attributed | CLOSED | CLOSED | |
| 8 | head-of-line measured and corrected | CLOSED | CLOSED | |
| 9 | curated redacted DEVELOPMENT evidence | OPEN | **CLOSED** | [g8-development-evidence.md](g8-development-evidence.md), `d6c5d16` |
| 10 | public license/source | CLOSED | CLOSED | re-read today: `public`, `Apache-2.0` |
| 11 | standalone engine from a clean clone | PARTIAL | **CLOSED** | [g8-standalone-fresh-clone-proof.md](g8-standalone-fresh-clone-proof.md): the fifth step, the tests, 335 passed, exit 0 on the same fresh clone |
| 12 | contribution provenance within window | PARTIAL | **CLOSED** | [g8-contribution-provenance.md](g8-contribution-provenance.md), `7f4b9e2` |
| 13 | exact release SHA passes required CI | PARTIAL | PARTIAL | freeze session |
| 14 | deployed version verified | CLOSED | CLOSED | not re-read today |
| 15 | features frozen | PARTIAL | PARTIAL | freeze session |
| 16 | manifest frozen and published | CLOSED | CLOSED | |
| 17 | immutable first run, 11/16 | CLOSED | CLOSED | |
| 18 | every fix SHA published, rerun separately | PARTIAL | CLOSED | [g8-effect-set-release-condition.md](g8-effect-set-release-condition.md) §3, §6 |
| 19 | 16/16 on the release candidate | OPEN | CLOSED, against v2 | [g8-effect-set-release-condition.md](g8-effect-set-release-condition.md) §6 |
| 20 | effect-set clean-clone command tested | PARTIAL | **CLOSED** | [g8-effect-set-fresh-clone-proof.md](g8-effect-set-fresh-clone-proof.md): `uv sync --frozen` and both manifests' `--check` and verifiers, exit 0 on the same fresh clone |
| 21 | demo funnel with 0/U and effect counts | PARTIAL | **CLOSED** | [g8-demo-funnel.md](g8-demo-funnel.md), `1232a55` |
| 22 | developer-authored disclosure | CLOSED | CLOSED | |

**Counts: 22 rows. 19 CLOSED, 3 PARTIAL, 0 OPEN.**

- CLOSED: 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 17, 18, 19, 20, 21, 22.
- PARTIAL: 1, 13, 15.
- Moved to CLOSED by this session: **9, 12, 21**. Rows 18 and 19 were closed by the
  release-condition session and are listed here for the running total. Row 11 was closed later
  the same day by [g8-standalone-fresh-clone-proof.md](g8-standalone-fresh-clone-proof.md), and
  row 20 after it by [g8-effect-set-fresh-clone-proof.md](g8-effect-set-fresh-clone-proof.md).

**Row 4 still holds only on `4529a802e34e`.** If closing any PARTIAL row produces a new image,
the rehearsal count restarts on the new SHA.

## 5. The fresh clone: state, and what remains

### State, read-only, after the reboot

| | |
|---|---|
| path | `D:\pp-g8-fresh-clone\promisepatch`, cloned `2026-09-26T14:38:54Z` from `https://github.com/Asembris/PromisePatch.git`, exit `0` |
| HEAD | `b5cf0d38c97b6a3fe4535070ecdc6b29d51666f5` |
| tree | **clean.** `git status --porcelain --ignored` shows only `!! packages/promise-graph/.venv/` |
| standalone venv | `packages/promise-graph/.venv`: 889 files, 20 MB. It holds `promise_graph 0.1.0` and the 13 pinned packages, among them `pydantic 2.13.5`, `pytest 8.4.2` and `hypothesis 6.167.1` |
| pytest artefacts | none: no `.pytest_cache` and no `.hypothesis` anywhere in the clone |
| root venv | **absent.** `uv sync --frozen` was never run |
| local-only specs | absent from the clone, as they should be: `ARCHITECTURE_PLAN.md`, `PROMISEPATCH_PRODUCT_SPEC.md` and `new_roadmap.md` are not published |

The clone was not modified, deleted, recreated or installed into in sitting 2.

### What sitting 1 recorded, verbatim

Every command ran with `CLAUDE_CODE_MESSAGING_TOKEN` and `ANTHROPIC_BASE_URL` unset, and with
`AWS_CONFIG_FILE` and `AWS_SHARED_CREDENTIALS_FILE` pointed at nonexistent paths and
`AWS_EC2_METADATA_DISABLED=true`. No `AWS_*` variable was set in the shell. The uv cache was this
machine's, so it was warm. The log below is complete: it is the file as it stood after the reboot.

```text
2026-09-26T14:39:09Z
$ uv venv --python 3.12
Using CPython 3.12.12
Creating virtual environment at: .venv
Activate with: source .venv/Scripts/activate
exit=0
$ uv pip install --requirement requirements-standalone.txt
Resolved 13 packages in 1.70s
warning: Failed to hardlink files; falling back to full copy. This may lead to degraded performance.
         If the cache and target directories are on different filesystems, hardlinking may not be supported.
         If this is intentional, set `export UV_LINK_MODE=copy` or use `--link-mode=copy` to suppress this warning.
Installed 13 packages in 616ms
 + annotated-types==0.8.0
 + colorama==0.4.6
 + hypothesis==6.167.1
 + iniconfig==2.3.0
 + packaging==26.3
 + pluggy==1.6.0
 + pydantic==2.13.5
 + pydantic-core==2.46.5
 + pygments==2.21.0
 + pytest==8.4.2
 + sortedcontainers==2.4.0
 + typing-extensions==4.16.0
 + typing-inspection==0.4.4
exit=0
$ uv pip install --no-deps .
Resolved 1 package in 4ms
   Building promise-graph @ file:///D:/pp-g8-fresh-clone/promisepatch/packages/promise-graph
      Built promise-graph @ file:///D:/pp-g8-fresh-clone/promisepatch/packages/promise-graph
Prepared 1 package in 2.08s
warning: Failed to hardlink files; falling back to full copy. This may lead to degraded performance.
         If the cache and target directories are on different filesystems, hardlinking may not be supported.
         If this is intentional, set `export UV_LINK_MODE=copy` or use `--link-mode=copy` to suppress this warning.
Installed 1 package in 17ms
 + promise-graph==0.1.0 (from file:///D:/pp-g8-fresh-clone/promisepatch/packages/promise-graph)
exit=0
$ uv run --no-project python examples/one_missing_delivery.py
"today's raspberry delivery didn't arrive" -- maya, 07:00 on 04 March 2026
4 open promises read against the graph

UNAFFECTED         untouched by this exception  (1 of 4)
    EXT-4  Dev       R-UNREACH  NOT_REACHABLE

AUTO_RECOVERABLE   changed without asking anyone  (1 of 4)
    EXT-1  Amara     R-PREAPPROVED  PREAPPROVAL_COVERS

APPROVAL_REQUIRED  needs the customer to say yes  (1 of 4)
    EXT-2  Ben       R-VISIBLE-ASK  VISIBLE_CHANGE_ASK

BLOCKED            no permitted recovery; a person decides  (1 of 4)
    EXT-3  Chandra   R-NOSUB  NOSUB_CONSTRAINT

1 of 4 untouched: no message, no write, no reservation change, no hold.
Nothing above was carried out. The engine decided; acting on it is somebody else's job.
exit=0
$ uv run --no-project pytest tests -q
```

**So, for row 11:**

- The install, the pinned requirements, the `--no-deps` package install and the example all
  exited `0` on a fresh public clone at `b5cf0d3`, with no cloud credential reachable.
- The example printed the four partitions the README shows.
- **The standalone tests have no result.** The log ends at the command. That is not a pass and is
  not reported as one.

**For row 20:** nothing was run.

### The remaining commands, for a later dedicated session

**Run one command at a time. Run nothing else alongside them: no Docker build, no other suite and
no second install.** Every command below runs in one Git Bash shell, after this assignment:

```bash
CLEAN="env -u CLAUDE_CODE_MESSAGING_TOKEN -u ANTHROPIC_BASE_URL AWS_CONFIG_FILE=/nonexistent/config AWS_SHARED_CREDENTIALS_FILE=/nonexistent/credentials AWS_EC2_METADATA_DISABLED=true"
```

**Row 11, the standalone tests.** This is low churn: pytest writes only caches and `__pycache__`,
tens of files. It reuses the venv the recorded steps 1–3 built, and reads the clone's committed
tests.

```bash
cd /d/pp-g8-fresh-clone/promisepatch/packages/promise-graph
```

```bash
$CLEAN uv run --no-project pytest tests -q
```

If the owner wants all five commands in one sitting instead, the documented recipe begins with
`uv venv --python 3.12`. Over the existing environment, that deletes and recreates about 889
files (20 MB). It needs the owner's explicit approval before it runs.

**Row 20, the effect-set check. This is high churn and needs explicit approval first.** In the
clone's root, `uv sync --frozen` builds the full workspace environment. The repository's own
equivalent `.venv` holds **17 158 files**. After it, each check reads the manifests only and writes
no capture:

```bash
cd /d/pp-g8-fresh-clone/promisepatch
```

```bash
$CLEAN uv sync --frozen
```

```bash
$CLEAN uv run python scripts/run_effect_sets.py --check
```

```bash
$CLEAN uv run python scripts/run_effect_sets.py --check --manifest v2
```

```bash
$CLEAN uv run python scripts/verify_effect_set_manifest.py
```

```bash
$CLEAN uv run python scripts/verify_effect_set_manifest.py --manifest v2
```

Expected, from the committed records:

- v1 `content_hash d41f5afc…2cdc`, and v2 `77286e77…b0dd`;
- each check reports its identity intact and its manifest coherent, and exits `0`.

`--check` returns before any scenario executes (`scripts/run_effect_sets.py`, `main`). No
database, container or credential is involved, so **no scored or development run is taken**.

Record each command's exit code and full output in a new page beside this one. Then remove
`D:\pp-g8-fresh-clone` only when the owner says so.

## 6. G8: what is left, and in what order

1. **Fresh-clone session** (rows 11 and 20). The commands are in §5, run one at a time, and the
   effect-set sync needs the owner's approval first. It changes no code and no image.
2. **Owner decision on row 1.** Either authorise `scripts/demo_contract.py` / `pp demo-contract`
   as G8 implementation work, or accept that G8 cannot close.
   - If it is built, `pr` must be green on the SHA that contains it.
   - A runner that changes no product path leaves `4529a802e34e` and R1–R5 standing.
   - A runner that changed a product path would need a new release and five new rehearsals.
3. **Freeze and closeout session** (rows 13 and 15):
   - dispatch `pr` with `workflow_dispatch` on the exact release SHA and record it;
   - declare the feature freeze;
   - restate the commit count in the provenance record at that SHA;
   - write the G8 closeout.

G8 stays **OPEN** until rows 1, 13 and 15 are each met. Row 11 is met; see
[g8-standalone-fresh-clone-proof.md](g8-standalone-fresh-clone-proof.md). Row 20 is met; see
[g8-effect-set-fresh-clone-proof.md](g8-effect-set-fresh-clone-proof.md). Phase 8 does not close before G8.
