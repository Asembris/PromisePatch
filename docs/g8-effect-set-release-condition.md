# G8 effect-set release condition

Date: **2026-09-24**. The release candidate is **`4529a802e34e`**. This page records the whole
lineage from the immutable first run to the release-condition result. It edits no earlier record.

**Two numbers, two sentences, and neither is the other:**

- **Headline, forever: 11/16** exact effect-set matches, the first scored run against the frozen
  v1 manifest, `d41f5afc…2cdc`. Immutable. Its denominator is permanently sixteen.
- **G8 release condition: 16/16** against the **v2 label correction**, `77286e77…b0dd`, on
  code whose product paths are identical to the release candidate.

The original benchmark did not become 16/16, and it never will. v2 is a different, separately
versioned document with its own hash, and its result stands beside 11/16, never over it.

## 1. The immutable first run: 11/16

| | |
|---|---|
| Capture | `docs/effect-sets/runs/20260915T163255509125+0000-scored.json`, with its `.log` |
| Manifest | `promisepatch-effect-sets` v1.0.0, `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` |
| Implementation | `e81b5aa3af10`, working tree clean |
| Runner | `1.0.0` |
| Command | `uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py --scored` |
| Result | **11/16**. `S06`, `S07`, `S08`, `S12` and `S13` `FAIL`; no `HARNESS_FAILURE` |

Record: [effect-set-first-scored-run.md](effect-set-first-scored-run.md). Diagnosis:
[effect-set-failure-diagnosis.md](effect-set-failure-diagnosis.md). Neither is edited here.

## 2. The five original failures

All the differences, copied from the immutable capture:

| scenario | checkpoint | `order/effect` | expected | observed | cause |
|---|---|---|---|---|---|
| S06 | CONSENT_SETTLED, SETTLED | `ord-b/customer_message` | 2 | 1 | E |
| S06 | SETTLED | `ord-b/owner_escalation` | 1 | 0 | C (then A) |
| S06 | SETTLED | `ord-b/task_hold` | 1 | 0 | C (then A) |
| S07 | SETTLED | `ord-b/owner_escalation`, `ord-b/task_hold` | 1, 1 | 0, 0 | C |
| S08 | SETTLED | `ord-b/task_hold` | 1 | 0 | A |
| S12 | CONFIRMED, CONSENT_SETTLED, SETTLED | `ord-e/task_hold` | 1 | 0 | B |
| S13 | CONFIRMED, CONSENT_SETTLED, SETTLED | `ord-a/owner_escalation`, `ord-a/task_hold` | 1, 1 | 0, 0 | D |

The diagnosis found five causes:

- **A**, **C**, **D** and **E** are implementation defects.
- **B** is undecided. ADR-0017 later decided it: the product does not hold started work.

## 3. Fix SHAs and the development reruns that measured them

Each fix commit also committed the development capture that measured it. Each such capture names
the fix's *parent* commit and is marked dirty, because the fix was in the working tree when the
capture was taken. **They are development evidence and none of them is a score**, as the protocol
requires.

| cause | fix commit | development capture (committed with the fix) | names | tree | result |
|---|---|---|---|---|---|
| A: an expired approval escalates without a hold | `2d8eee6` (2026-09-16) | `20260917T085253648173+0000-development.json`, the first capture after it | `eb0eb23` | dirty | S08 passes; S06, S07, S12, S13 do not |
| D: a refused amendment has no route onward | `5444ad2` (2026-09-17) | `20260917T085253…` and `20260917T090959530093+0000-development.json` | `eb0eb23` | dirty | S13 passes; S06, S07, S12 do not |
| E: no "your order changed" message | `1777435` (2026-09-17) | `20260917T095103947622+0000-development.json` | `5444ad2` | dirty | S06, S07, S12 still fail (S06 also needs C) |
| C: a re-planned case waits unbounded | `c8c27f3` (2026-09-17) | `20260917T104245266739+0000-development.json` (intermediate) and `20260917T105012389111+0000-development.json` | `8f7e1f9` | dirty | S12 alone fails |
| B: a started task is not held | none, by decision | ADR-0017 `eb0eb23` (2026-09-17); started-work contract `03713f1` | | | S12 stays failing against v1 |

Four later development captures, taken at `c8c27f3`, are **untracked on purpose** (`7032f25`)
and are left untracked by this page. Three of them show S12 as the only failure. One shows S08,
S12 and S13 failing.

Later behaviour changes reached the release candidate after all these captures:

- `1e80c90`, ADR-0022: re-ask a re-planned track as a new request;
- ADR-0023 to ADR-0026: the re-plan round, freshness at commit, revalidating an answer on arrival,
  and a first dispatch judged again.

No committed development capture measures them. The measurement that covers them is §4.

## 4. The release candidate against v1: 15/16, S12 the only mismatch

The owner read the authenticated GitHub CI log of the `effect sets (expected red until 16/16)`
job on the release candidate's code: `pr`-equivalent `da7ceca`, product-identical to
`4529a802e34e`, run `36026681236`, job `107724888511`. It ran
`uv run pytest apps/backend/tests/test_effect_sets.py` and got **1 failed, 15 passed**. The only
failure was **S12**, with exactly three differences:

- `CONFIRMED` `ord-e/task_hold`: expected 1, observed 0;
- `CONSENT_SETTLED`: the same;
- `SETTLED`: the same.

That is a pytest run, which the protocol classifies as harness-development evidence. **It is not
a score.** It is the finding that settled
[g8-remaining-gaps-audit.md](g8-remaining-gaps-audit.md) §10 action 1: no scenario other than S12
fails on the release candidate. So **no product repair is owed**, `4529a802e34e` stands, and so do
rehearsals R1–R5. This session did not re-read that log. It is recorded here as the owner's
reading, as the brief supplied it.

## 5. The v2 correction: a label version, not a product repair

Predeclared and committed **before** any v2 run, in
[effect-set-manifest-v2.md](effect-set-manifest-v2.md):

- `1b47ab8`: the v2 manifest, the verifier's conditional R1 and the argument;
- `ec76050`: the runner's manifest selection, `RUNNER_VERSION` `1.1.0`.

- **What moved:** R1 became conditional on the order's production task not having already
  started. One label follows from it: S12 `CONFIRMED` loses `ord-e task_hold 1`, so the cumulative
  `ord-e/task_hold` is 0 at `CONFIRMED`, `CONSENT_SETTLED` and `SETTLED`. One rationale sentence
  and the metadata were added. Nothing else changed. A test asserts this.
- **Why it is a label error and not a result-driven edit:** the rule it applies comes from
  ADR-0017 and the started-work contract, dated 2026-09-17. That is after the first scored run
  and a week before this correction. The contract specified this exact delta and left it
  unwritten on purpose. S12 stipulates the started task in its own words.
- **What did not move:** v1 is byte-identical and still verified with its unconditional R1. The
  11/16 capture and log, and every historical run, are untouched. No product code changed:
  `git diff --name-only 4529a802e34e HEAD` names only `docs/`, `CLAUDE.md`, `scripts/` and
  `apps/backend/tests/`. The CI workflow is untouched, still judges v1, and stays red on S12.
- **Disclosed deviation:** the protocol keeps the harness-building session apart from the scoring
  session. The owner directed this one to do both. See the predeclaration, §6.

## 6. The release-condition run against v2

Taken **once**, at `2026-09-24T21:43:52Z`, after both pre-run commits. It was not repeated,
and nothing was edited after it.

| | |
|---|---|
| **Result** | **16/16. All sixteen `PASS`, zero diffs, zero `HARNESS_FAILURE`** |
| Command | `uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py --scored --manifest v2`, exactly as predeclared |
| Capture | [`docs/effect-sets/runs-v2/20260924T214352744301+0000-scored.json`](effect-sets/runs-v2/20260924T214352744301+0000-scored.json), committed unedited at `5e87d1a` |
| Console output | [`…-scored.log`](effect-sets/runs-v2/20260924T214352744301+0000-scored.log) |
| Manifest | `promisepatch-effect-sets` v2.0.0, `77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd` |
| Implementation | `ec76050389e5`. Its product paths are identical to `4529a802e34e`: `git diff --name-only 4529a802e34e HEAD` over `apps/backend/src`, `packages`, `apps/order-simulator`, `apps/frontend`, `docker`, `deploy`, `docker-compose.yml`, `pyproject.toml` and `uv.lock` was empty |
| Runner | `1.1.0` |
| Started / finished | `2026-09-24T21:43:52.744301+00:00` / `2026-09-24T21:46:20.273520+00:00` |
| Exit code | `0` |
| sha256 of the committed bytes | capture `3f8b9fcf…adbf`, log `8e790b98…3892`, `scenarios.v2.json` `d4d1df80…2f01`, `scenarios.v1.json` `e9d828cb…fa00b` (identical at `4529a80`) |

**Tree state.** `git status --porcelain --untracked-files=no` was empty immediately before and after
the run. The capture nevertheless records `working_tree_dirty: true`. The runner reads
`git status --porcelain` including untracked files, and the only entries were the eleven known
untracked artefacts: `REMAINING_WORK_ASSESSMENT.md`, four `docs/effect-sets/runs/20260917T1…`
development captures and six `docs/rehearsals/runs/dr01-*` directories. None of those is code the
suite reads. They were left untouched, and the runner was not changed after predeclaration to
report it differently.

**Environment, disclosed.** The capture records `model_provider_configured: true` and
`aws_credentials_configured: false`. The first scored run recorded `false` for both. The flag is
`bool(os.environ["PP_LLM_PROVIDER"])`, and `scripts/with_local_env.py` loads
`docker/env/host.env`, which has held `PP_LLM_PROVIDER=bedrock` since the SUR-1 scored stack of
2026-09-20. **No model could be reached by this run:**

- every effect-set worker is built by `Intake.worker(...)` with
  `semantic or FakeSemanticProvider()` (`apps/backend/tests/_intake_support.py`), and no scenario
  passes one;
- neither the API app nor the MCP app built by the suite constructs a semantic provider;
- `build_semantic_provider`, the one reader of `PP_LLM_PROVIDER`, is reached only from
  `pp converse` and the deployment's `promisepatch.worker.run`, and the suite calls neither.

The variable was configured and never read. Transport fixtures are local, as the capture says.

**Per scenario.** S01 to S16 are all `PASS` with no diff. Against v1 the same code differs only on
S12's `ord-e/task_hold`, per §4. v2 changes exactly that label. S12 therefore passes because the
label version differs, and the product did nothing differently.

### What this closes, and what it does not

- **Row 19 of [g8-remaining-gaps-audit.md](g8-remaining-gaps-audit.md), *"G8 requires 16/16 on
  the release candidate only"*, is CLOSED** as a release condition. It is closed against the
  separately versioned v2 label correction, on code whose product paths are identical to
  `4529a802e34e`, by the roadmap's own route: *"A genuine label error receives a separately
  versioned, explained correction and separate result."*
- **Row 18, *"Publish every fix SHA and rerun separately"***: its missing condition was the
  publication. §3 of this page supplies it, and this section is the clean-tree rerun.
- **The headline is unchanged: 11/16**, first run, v1, immutable. This result never replaces it
  and is never reported as it.
- **`4529a802e34e` stands as the release candidate**, so R1–R5 stand. No product code moved, and
  no image was built or deployed.
- **G8 as a whole stays OPEN.** Row 9, the curated and redacted DEVELOPMENT evidence, is still
  OPEN. Rows 1, 11, 12, 13, 15, 20 and 21 still each lack their one condition. The next step is
  the evidence-packaging session in the audit's §10 action 4, then the freeze and closeout in
  action 5.

## 7. What is not claimed

- Not that the effect-set benchmark scored 16/16. Its only score is 11/16.
- Not that S12 was repaired. The product behaviour for S12 is exactly what it was at the first
  scored run. What changed is the label version it is judged against.
- Not independent validation. The labels and the correction are developer-authored, finite and
  public, and the corrected label is not independent of the implementation in time. v2's own
  `provenance` says so.
- Not live proof. Transport fixtures are local, and local replay is not proof of live delivery.
