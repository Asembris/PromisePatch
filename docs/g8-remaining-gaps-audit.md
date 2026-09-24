# G8 remaining-gaps audit

Date: **2026-09-24**. Read-only audit. Entry at `06a122074f951b01df4647404cae4b5cc169d9a7`: `main`
equal to `origin/main`, tracked tree clean, and the eleven known untracked artefacts left as they
were. The frozen deployed release candidate is **`4529a802e34e`**.

**Nothing was changed except this page and a minimal current-state correction to `CLAUDE.md`.**
Nothing was built, deployed, restored, sent, rerun or called. There was no model call and no
Telegram send. No SUR-1 or effect-set scenario was executed, and no worktree or clone was made. No
AWS API was called. The live reads were two public HTTPS GETs of the deployed `/healthz` and
`/readyz`, and unauthenticated GitHub REST reads of CI runs, jobs, annotations and repository
metadata. The local reads were `scripts/verify_effect_set_manifest.py`, which is read-only, and
Python loads of the committed run captures. Every historical record cited here is left as it was.

## 1. Authority and method

The gate is `new_roadmap.md` §11 *G8 — release proof* and *G8 addition — reproducible ground-truth
effect sets (MUST)*. That file is local-only and frozen, and it was read first, with §10's P8 row and
its frozen amendment. Each row below copies one literal requirement from those two sections. Where
one bullet names several conditions, each condition has its own row.

For each row, the evidence was opened, not taken from a summary:

- the 69 backend test functions the proof map cites were resolved by name at HEAD, and all 69
  exist;
- the stale-plan tests were read for their assertions;
- the rehearsal records were cross-checked against each other's counters;
- CI results come from the GitHub API;
- the deployed image comes from the live endpoint.

Evidence categories are kept apart and never upgraded into one another:

- **D**: deterministic or local tests;
- **CI**: those tests green in required CI;
- **L**: deployed and live;
- **H**: historical published capture.

Verdicts:

- **CLOSED**: existing evidence fully satisfies the requirement's literal text.
- **PARTIAL**: evidence exists, and one explicit condition is missing.
- **OPEN**: the required artefact or action does not exist.

## 2. The matrix

| # | literal requirement (roadmap §11) | verdict | evidence, or the exact missing condition |
|---|---|---|---|
| 1 | *"Demo-contract runner uses the new transport boundaries; no direct DB consent inserts. Fixture setup and fault injection are explicit operator actions."* | **PARTIAL** | **Missing: a runner.** Nothing called or serving as a demo-contract runner is tracked. `scripts/demo_contract.py` exists only in `ARCHITECTURE_PLAN.md`, and `pp` has no `demo-contract` command. The behaviour the bullet constrains does exist, as a manual protocol. R1–R5 (**L**) set up fixtures with `pp restore-demo-world` and inject faults with `compose restart/stop/start worker`, both operator actions. Consent came through real Telegram and the signed-link HTTP route, with no DB consent insert. The effect-set harness (**D**) writes only a raw `inbox_events` transport row (`_intake_support.py:736`), and the worker decides. That is not a direct consent insert, but it is also not a runner |
| 2 | *"Test lost MCP response/replay, foreign identity, model self-confirmation, stale plan/callback, wrong customer, duplicate webhook, timeout, crash before/after external acceptance, browser disconnect and external convergence. Reuse core tests rather than duplicate for counts."* | **CLOSED** (D + CI) | All eleven faults are covered in §3. `pr` was 13/13 green at `da7ceca`, run `36026681252`, whose code is identical to `4529a80` (§5) |
| 3 | *"Show an approved stale plan refusing mutation after external order/stock changes. Ten green checks alone are insufficient."* | **CLOSED** (D + CI) | See §4. **A live STALE is not literally required** |
| 4 | *"Five complete deployed rehearsals from clean fixtures, each with real customer transport and a worker restart, satisfy effect/outcome invariants. Preserve failures and repairs."* | **CLOSED** (L), on `4529a802e34e` only | See §6. It holds only while `4529a802e34e` remains the release candidate |
| 5 | *"Whole-delivery changes the plan"* | **CLOSED** (D + CI) | `test_whole_delivery_counterfactual.py`: `::test_the_raspberry_only_answer_leaves_priya_and_tomas_a_recovery`, `::test_the_whole_delivery_answer_takes_that_recovery_away` and `::test_the_two_frozen_branches_differ_in_feasibility_and_not_in_breadth`. Effect-set S02 passed the scored run (**H**) |
| 6 | *"unrelated external changes do not invalidate unrelated work"* | **CLOSED** (D + CI + H) | `test_effect_sets.py::test_s14_unrelated_external_edit_after_exception`, which passed the immutable scored run `20260915T163255509125+0000-scored.json`. `test_whole_delivery_counterfactual.py::test_lenas_own_amendment_is_never_counted_as_an_incident_caused_effect` |
| 7 | *"Verify zero protected-order recovery amendments/messages/reservation changes/task holds with baseline/case attribution."* | **CLOSED** (D + CI; L corroborating) | `test_whole_delivery_counterfactual.py::test_every_untouched_order_carries_zero_incident_caused_effects`, with the census in `_effect_set_observation.py`, which attributes effects by the idempotency keys of this case's tracks. Deployed corroboration: every R1–R5 record reports an unchanged unrelated digest from the frozen reader `c9731c8f…`, `EXT-C`…`EXT-F` at v1, and zero attribution counts for `pr-e`/`pr-f` |
| 8 | *"Measure delayed semantic calls alongside unrelated ready work. … Make the smallest scheduling correction only if observed responsiveness misses the gate."* | **CLOSED** (H + D + CI; the correction is in the deployed image) | See §7 |
| 9 | *"Curated redacted DEVELOPMENT evidence includes source commits, run IDs, hashes, limits and scorer-correction provenance. Keep failed evidence and sealed holdouts."* | **OPEN** | **The curated, redacted artefact does not exist.** Its raw material is local-only: 28 files in the git-ignored `.eval-results/`. Among them are `development-*.jsonl`, `explanation-p48dev.jsonl`, `explanation-p48dev-repaired.jsonl`, `explanation-7172c7c894ae.jsonl`, the challenger sets and the cost ledgers. Run IDs, commits and limits are scattered across `explanation-quality-gate.md`, `semantic-benchmark*.md` and the challenger records. None of those records carries a sha256 of any DEVELOPMENT result file. Nothing is published in redacted form, and no single page gives scorer-correction provenance. Two sub-conditions do hold: failed evidence is kept, and both holdouts stay sealed |
| 10 | *"Public license/source check"* | **CLOSED** (L) | GitHub API, read today: `Asembris/PromisePatch` is `visibility: public` with `license.spdx_id: Apache-2.0` detected. `LICENSE` at the root is Apache 2.0 |
| 11 | *"standalone engine installation/example/tests without cloud credentials"* | **PARTIAL** | **Missing: a recorded run from a clean clone.** The recipe exists: `packages/promise-graph/README.md` §*Standalone*, the pinned `requirements-standalone.txt`, `examples/one_missing_delivery.py`, and `tests/test_example.py` asserting the example's transcript (`ce8674f`, `e42528b`). The engine suite runs in `pr` inside the monorepo (**CI**). No record shows those commands run from a clean clone, and no CI job runs the standalone path |
| 12 | *"contribution provenance within window"* | **PARTIAL** | **Missing: the written provenance record.** The facts can be checked. The first commit, `1799971`, is dated `2026-09-02T20:25:53Z`, after submissions opened at `2026-08-31T17:15Z` (roadmap §2). The repository was created `2026-09-02T15:40:04Z`. HEAD is 777 commits, all authored within the window. No document states this |
| 13 | *"Exact release SHA passes required CI including new browser workflow tests."* | **PARTIAL** (CI) | **Missing: a `pr` run whose `head_sha` is the release SHA.** `pr` run `36026681252` passed 13 of 13 jobs, `whole-stack browser` among them, at `da7ceca`, attempt 1. From `4529a80` to `da7ceca` only `CLAUDE.md` and one doc changed, and from `da7ceca` to HEAD only docs changed (`git diff --stat`, re-run here). `4529a80` has no run of its own. `pr` has `workflow_dispatch`, so the missing run can be obtained |
| 14 | *"Verify deployed version, not old image."* | **CLOSED** (L) | `GET /healthz`, today: `image: 4529a802e34e`, `boot_id 3e90146d-…`, the rollout's own boot id. `/readyz`: migrations at head `0009_human_plan_approval`. The R5 control plane records `ImageTag`, `DeclaredImageTag`, SSM `image-tag` and every container on `4529a802e34e` |
| 15 | *"Freeze features."* | **PARTIAL** | **Missing: a declared final freeze.** In fact nothing has changed: no product code since `4529a80`. But the freeze cannot be declared final while row 19 decides whether the release SHA moves |
| 16 | *"P5 freezes and publishes the commit SHA of the versioned manifest of 16 scenarios"*, hand-labelled, with checkpoints and expected effects | **CLOSED** (H) | `scripts/verify_effect_set_manifest.py`, run here: `scenarios 16`, `content_hash d41f5afc…2cdc`, *"coherent: partitions, checkpoints, effects and identities all hold"* |
| 17 | *"the first complete run against the original P5 labels, X/16 … Capture it immutably with manifest SHA, implementation SHA, runner version, command, outputs and every diff before repairs"*, with harness failures counted as nonpasses | **CLOSED** (H) | `docs/effect-sets/runs/20260915T163255509125+0000-scored.json`: `kind scored`, `score 11/16`, implementation `e81b5aa3…`, manifest `d41f5afc…`, runner `1.0.0`, command `scripts/run_effect_sets.py --scored`, `working_tree_dirty: false`. S06, S07, S08, S12 and S13 `FAIL`; no `HARNESS_FAILURE`. Its diagnosis is `effect-set-failure-diagnosis.md` |
| 18 | *"Publish every fix SHA and rerun separately."* | **PARTIAL** | **Missing: the publication.** The fixes are in history: `5444ad2`, `1777435`, `c8c27f3`, `1e80c90` and others. Five development captures are committed: `20260917T085253…`, `…090959…`, `…095103…`, `…104245…` and `…105012…`. The last reached 15/16 with S12 failing, on a dirty tree. No page links each fix SHA to the rerun that measured it, no clean rerun exists, and four later captures stay untracked on purpose (`7032f25`) |
| 19 | *"G8 requires 16/16 on the release candidate only"* | **OPEN** | See §8. S12 stays failing by decision (ADR-0017, [started-work-contract.md](started-work-contract.md)). The effect-set job at `da7ceca` is `failure` (run `36026681236`, job `107724888511`, step *The sixteen frozen scenarios*). Its log needs authentication, so this audit cannot say whether S12 is the only scenario failing on the release candidate's code |
| 20 | *"Provide a documented clean-clone command, pinned dependencies and local prerequisites; no AWS/cloud credentials … Test that command from a fresh checkout. Mark transport fixtures explicitly."* | **PARTIAL** | **Missing: the recorded fresh-checkout test.** The command is documented in `effect-set-run-protocol.md` (fresh clone, `uv sync --frozen`, then `run_effect_sets.py --check`) and in `effect-set-harness.md` §*Running it*, and `uv.lock` is pinned. No record shows it run from a fresh checkout |
| 21 | *"Report the demo funnel with actual measured counts: total orders -> threatened [auto / consent / blocked] + untouched -> actually recovered / waiting / escalated … 0/U … plus effect counts"* | **PARTIAL** | **Missing: the report.** The counts were measured: in the census tests (**D**) and in each of R1–R5 (**L**), which gave the canonical partition, the settled outcomes, exactly 3 outbox effects and the untouched zero. No funnel document exists. [prerequisites-integration-cost-and-limitations.md](prerequisites-integration-cost-and-limitations.md) defers it to P9 |
| 22 | *"Disclose that labels and suite are developer-authored, finite and public, not an independently validated or held-out benchmark."* | **CLOSED** | `effect-set-manifest.md:202`, `effect-set-first-scored-run.md:155` and `README.md:103` |

**Counts: 22 rows. 12 CLOSED, 8 PARTIAL, 2 OPEN.**

- CLOSED: 2, 3, 4, 5, 6, 7, 8, 10, 14, 16, 17, 22.
- PARTIAL: 1, 11, 12, 13, 15, 18, 20, 21.
- OPEN: 9, 19.

## 3. The eleven adversarial faults (row 2)

[g8-adversarial-proof-map.md](g8-adversarial-proof-map.md) §1 was audited at `c4e7503`, amended
on 2026-09-17, and extended by [adversarial-race-proofs.md](adversarial-race-proofs.md). Each test
name it cites was re-resolved at HEAD. **All 69 exist.** The roadmap says *"Reuse core tests rather
than duplicate for counts"*, so the core tests count as they are.

| fault | proof-map section | holds at HEAD |
|---|---|---|
| lost MCP response / replay | §1.1 | yes |
| foreign identity | §1.2 | yes |
| model self-confirmation | §1.3, plus the 2026-09-17 amendment (`test_human_confirmation_boundary.py`, `test_orchestrated_conversation.py`) | yes |
| stale plan / stale callback | §1.4 | yes |
| wrong customer | §1.5 | yes |
| duplicate webhook | §1.6 | yes |
| timeout | §1.7, precision stated | yes |
| crash before external acceptance | §1.8 | yes |
| crash after external acceptance | §1.9, plus S15, which passed the scored run | yes |
| browser disconnect | §1.10, limitation stated | yes |
| external convergence | §1.11 | yes |

The two stated limitations are real: no e2e severs a browser mid-mutation, and no test enumerates
a *read* timeout. The roadmap's reuse rule argues against new tests written for a count, and
neither limitation is a missing requirement. None of the eleven was exercised live, and this row
does not claim they were.

## 4. The stale approved plan (row 3), and whether a live STALE is owed

The roadmap's words are *"Show an approved stale plan refusing mutation after external order/stock
changes. Ten green checks alone are insufficient."* **They contain no word that requires a
deployed or live run.** The G8 bullets that do require deployment say so: *"Five complete deployed
rehearsals"*. The P8 row lists *"canonical/counterfactual/stale/replay/restart proofs"* and gives
the local, credential-free effect-set suite as their vehicle: S06 is a stale approved order
version, S07 a stale approved stock state.

The following were opened and read at HEAD. All are in `test_recovery_revalidation.py`, green in
`backend + postgres`.

**The order change.**
`::test_an_order_amended_while_waiting_makes_the_approval_stale` builds an approved case, moves
`ORDER_B` from version N to N+1, and asserts that `RECOVERY_STALE` is audited. Check 2 carries `vN`
as expected and `vN+1` as actual.

**The stock change.** `::test_a_substitute_eaten_while_waiting_makes_the_approval_stale` consumes
the approved substitute and asserts that `RECOVERY_STALE` is audited.

**Why ten green checks are not enough.**
`::test_a_change_landing_after_a_passing_revalidation_still_stops_the_amendment` lets the
checklist *pass* and leaves the case `RECONCILING`. It then moves the order and asserts:

- `amendments_for(track) == []`;
- the track is `TRACK_ESCALATED`;
- the task is `HELD` by the case.

That answers the roadmap's second sentence directly.

One wording has drifted. The proof map says the track is left `TRACK_STALE`. Since `5444ad2`, the
stale plan goes to the owner with its kitchen work held, so the track is `TRACK_ESCALATED`. The
claim itself, no amendment, is unchanged.

**Shown on screen.** `apps/frontend/tests/evidence.test.tsx` renders expected beside actual under
`STALE`, and `vocabulary.test.tsx` is exhaustive over the promise states.

**Verdict: a live STALE is not owed by G8's text.**
[phase7-closeout.md](phase7-closeout.md) §7–§9 wrote *"G8 asks for a live stale refusal"* and listed
one as next step 4. That reads more into the gate than it says. The closeout is history and is not
edited; this page is the later reading beside it. A live STALE is still worth having as demo
material for G9, and it would be the first refusal ever run live. It is a choice for the video, not
a G8 item, and it should not spend a destructive restore for G8's sake.

## 5. Release-SHA CI (row 13)

GitHub REST, unauthenticated:

- `pr` run `36026681252` at `da7ceca429d3…`, attempt 1, **success**. Its thirteen jobs include
  `whole-stack browser`, `frontend`, `backend + postgres`, `mcp protocol`, `pytest + coverage`,
  `hypothesis (ci profile)`, `mypy`, `ruff`, `import-linter` and `gitleaks`.
- HEAD `06a1220` has no run. Docs-only commits are path-ignored.

`git diff --stat` was re-run here. `4529a80..da7ceca` touches `CLAUDE.md` and
`docs/phase7-approval-log-privacy-repair.md` only. `da7ceca..06a1220` touches `CLAUDE.md` and
`docs/` only. So the tested code is the deployed code. The roadmap still says *exact* SHA, and no
run has `head_sha` `4529a80`. That is why the row is PARTIAL, not CLOSED.

## 6. The five deployed rehearsals (row 4)

The protocol is [g8-rehearsal-preparation.md](g8-rehearsal-preparation.md) §3, predeclared at
`9198f42`. Its pass rule: any deviation is a FAIL; an operational failure to reach the restart
point is a VOID; five PASS runs on one image close the item; *"A repair that changes the image
restarts the count on the new SHA."*

| run | record | restart point | image | verdict | `sendMessage` over the run | `worker.start` / `.stop` |
|---|---|---|---|---|---|---|
| R1 | `g8-rehearsal-r1.md`, `5e6e43f` | waiting for consent | `4529a802e34e` | PASS, 1 of 5 | 1 → 2 | 2/1 before its restart |
| R2 | `g8-rehearsal-r2.md`, `5bdc774` | across plan confirmation (stop … start) | `4529a802e34e` | PASS, 2 of 5 | 2 → 3 | |
| R3 | `g8-rehearsal-r3.md`, `69079ad` | across the customer's answer (stop … start) | `4529a802e34e` | PASS, 3 of 5 | 3 → 4 | |
| R4 | `g8-rehearsal-r4.md`, `e79288d` | after `RESOLVED` | `4529a802e34e` | PASS, 4 of 5 | 4 → 5 | |
| R5 | `g8-rehearsal-r5.md`, `06a1220` | waiting for consent (R1 repeated) | `4529a802e34e` | PASS, 5 of 5 | 5 → 6 | 6/5 before its restart |

**No run is hidden, failed, voided or replaced.**

- **The message counter is continuous.** The worker's lifetime `sendMessage` is 1 at R1's entry,
  from the Phase 7 privacy repair. It goes up by exactly one per rehearsal to 6, with no gap for an
  unrecorded run.
- **So is the start counter.** `worker.start` was 2 before R1's restart: the rollout plus the one
  restart the preparation authorised. It was 6 before R5's: one more for each of R1–R4.
- **Each run starts where the last one ended.** Every entry census names the previous run's case
  as `RESOLVED` with no `PENDING`/`IN_FLIGHT` outbox rows. R1's entry case, `87590614-…`, is the
  preparation's own restore. It escalated `PLAN_UNCONFIRMED` and resolved with owner attention,
  as the preparation §5 records.
- **No FAIL or VOID appears** in any record.

**The frozen reader did not change.** R1 froze `g8ev.py` at sha256
`c9731c8f8dedfe15fbc6af0c2db6a8d5d19ca090d7863f3d2e945b18220b0dd4`, before its restore, and embedded
it in its appendix. R2, R3, R4 and R5 each record that same sha256, and each says the host printed it
before every read.

**The contract was amended once, before spend.** `48cf104` corrected R3's "while down" row. The
decision is written by the worker, so with no worker running only a `RECEIVED` inbox row can exist.
It was committed at `20:14:29Z`, ten minutes before R3's entry census at `20:24:12Z`. No
restore, confirmation or message preceded it. It is recorded as a pre-run correction, and R3 was
judged against it.

**Condition.** Row 4 is CLOSED **on `4529a802e34e`**. If G8's remaining work produces a new image,
§3.1's own rule restarts the count, and all five must be taken again on the new SHA.

## 7. Head-of-line: measurement, disposition, correction (row 8)

In order:

1. **Measured**, 2026-09-16, [g8-head-of-line-measurement.md](g8-head-of-line-measurement.md).
   Nine captures committed unedited under `docs/head-of-line/runs/`, implementation `7cb188c`.
   `H_representative = 1545.8 ms` and `H_treatment = 8173.4 ms` against the predeclared
   `H ≤ 1000.0 ms`. **FAIL on both delayed arms.** This discharges the requirement to measure.
2. **Disposition**, 2026-09-17, [g8-head-of-line-disposition.md](g8-head-of-line-disposition.md).
   The owner declined the correction. The FAIL stands, and the threshold is unmoved.
3. **Correction**, 2026-09-18, [head-of-line-correction.md](head-of-line-correction.md). The
   owner reversed the decline:
   - `46ad4e1` runs a semantic preparation beside the loop, bounded by
     `DEFERRED_SEMANTIC_LIMIT = 4`, with `exclude_cases` and `exclude_kinds` applied at claim time;
   - `0af6f74` adds `test_worker_responsiveness.py`, 7 tests. It imports `IDLE_INTERVAL` as the
     gate and measures B's wait as 5212.7 ms before the change and 49.3 ms after.

**The conditional is discharged.** The gate was missed, and the smallest correction was made:
the roadmap says *"only if … misses the gate"*, and it did.

**The correction is deployed.** `git merge-base --is-ancestor 46ad4e1 4529a80` holds, and
`worker.py` at `4529a80` names `DEFERRED_SEMANTIC_LIMIT` three times. The regression is green in
`backend + postgres` at `da7ceca`.

**Nothing more is owed.** The roadmap does not ask for the nine-capture protocol to be re-run
against the corrected worker. That would need its own predeclared amendment, and it is not owed.
The published FAIL stays exactly as measured.

## 8. Effect sets: 11/16 against 16/16 (row 19)

**16/16 is required for G8, in the roadmap's own words.** The G8 addition says: *"Publish every fix
SHA and rerun separately. G8 requires 16/16 on the release candidate only; never replace the
headline with the repaired score or remove a failing scenario."* The P8 row repeats it: *"16/16
only a release condition"*. This comes from the roadmap, not from another document.

**The two are separate sentences.** `11/16` is the immutable first-run headline. `16/16` is a
release condition on the release candidate. Neither is ever reported as the other.

**Why the release candidate cannot reach 16/16 as things stand:**

- **S12 stays failing by decision.** ADR-0017 (Phase 8, accepted) declined the repair: *"S12 stays
  failing, permanently and on the record."*
- **The only product repair ever named is unsound as specified.**
  [started-work-contract.md](started-work-contract.md) shows that ADR-0017's decision 5 would also
  need `_task_is_ours` to refuse a hold whose remembered state was `STARTED`.
- **The invariant now in force forbids it.** It reads *"started work is escalated to its owner and
  never held"*.
- **S12's label cannot be fixed alone either.** It is rule R1 of the frozen manifest, applied
  correctly. The manifest's own verifier refuses a v1 manifest in which an order escalates without
  a hold.
- **The route that remains is a separately versioned manifest.** In it R1 becomes conditional on
  the task not having started. It carries its own hash, an argument from stipulated facts alone,
  and a **separate result published beside 11/16**. The started-work contract specifies that delta
  and deliberately does not write it. Under the roadmap's text, *"A genuine label error receives a
  separately versioned, explained correction and separate result"*, 16/16 against that versioned
  manifest can satisfy the release condition. `11/16` against v1 stays the headline forever.

**Unknown: whether S12 is the only failure on the release candidate's code.** The last committed
development capture, 15/16 with S12 the only failure, was taken on a dirty tree at `8f7e1f9`. Later
behaviour changes (ADR-0022 to ADR-0026) all landed after it. CI's effect-set job at `da7ceca` is
red, and its log needs authentication. **Reading that log is the first action in §10.** If any
scenario other than S12 fails there, it is a defect in the frozen release candidate, and it is
repaired under G8 through a new release. That supersedes `4529a802e34e` and restarts row 4's count.

## 9. `CLAUDE.md` consistency

Found stale, corrected minimally in the same commit:

- *"G8 remains open, separately: none of its five deployed rehearsals has been run"*. The same
  paragraph then records all five as passed. Corrected to say they have been.
- The historical-record row *"Demo world restore (local proof only)"*. The deployed proof was taken
  on 2026-09-23 and is recorded in `demo-world-restore.md` and in `CLAUDE.md`'s own current-state
  text. Corrected.
- Added one line and one table row pointing here.

Found and **not edited**, because each is a historical record:

- [phase7-closeout.md](phase7-closeout.md) §7–§9 on a "live stale refusal". §4 of this page reads
  the gate differently.
- [g8-rehearsal-preparation.md](g8-rehearsal-preparation.md) §1, *"No rehearsal was run"*, which is
  true of that session.
- [g8-adversarial-proof-map.md](g8-adversarial-proof-map.md): §3's *"out of scope … remain open"*,
  and §2's `TRACK_STALE` wording.

## 10. Minimum remaining actions, in order

1. **Read the effect-set job log at `da7ceca`.** Run `36026681236`, job `107724888511`, step *The
   sixteen frozen scenarios*. It needs a GitHub login, which is the owner's. Record which scenarios
   fail on the release candidate's code. This settles whether the release candidate needs a
   product repair.
   - **If only S12 fails**, `4529a802e34e` stands, and so do R1–R5.
   - **If anything else fails**, repair it under G8, cut a new release with `pr` green on its exact
     SHA, and take five new deployed rehearsals on it.
2. **Owner decision on S12.** Either authorise the versioned-manifest correction as the
   started-work contract specifies, or accept that G8's 16/16 is not met. The roadmap says *"A
   failed MUST cannot be renamed 'done'"*, so accepting it means G8 cannot close. **No product
   change is indicated for S12.**
3. **Correction session.** Author the next manifest version with conditional R1: its own hash, an
   argument from stipulated facts alone, and the verifier's qualification. Leave v1 byte-identical.
   Run the sixteen scenarios once, clean-tree, against code identical to the release candidate, as
   a **release-condition result published beside 11/16**. Publish the fix-SHA → rerun lineage
   (row 18) in the same session.
4. **Evidence packaging session.** Docs, plus one fresh clone:
   - the curated, redacted DEVELOPMENT evidence page, with a sha256 per result file, run IDs,
     source commits, limits and scorer-correction provenance (row 9);
   - the demo funnel from R1–R5's measured counts, with 0/U (row 21);
   - the contribution-provenance statement (row 12);
   - one fresh-clone execution of the standalone engine recipe and of `run_effect_sets.py --check`
     (rows 11 and 20);
   - the owner's ruling on whether the predeclared rehearsal protocol with its frozen reader is the
     demo-contract runner of record (row 1). The alternative is to build `scripts/demo_contract.py`,
     which is implementation work.
5. **Freeze session.** Dispatch `pr` on the exact release SHA, which the owner can do with
   `workflow_dispatch`, and record it (row 13). Declare the freeze (row 15). Write the G8 closeout.

**Minimum sessions before Phase 8 closes and G9 can begin: 3**, if action 1 finds only S12 failing.
That is the correction session, the evidence session, and the freeze and closeout session. Actions
1 and 2 are owner reads and decisions made before the first. **If action 1 finds a second failing
scenario, add at least 2 more**: one to repair and release, and one to take five new deployed
rehearsals. R1–R5 took one evening, from R1's entry census at `19:13Z` to R5's settled evidence
at `21:00Z`.

## 11. What must NOT be rebuilt or rerun

- **The first scored run, `11/16`.** It is immutable. Never edit `scenarios.v1.json`, its hash or
  its capture.
- **The eleven adversarial-fault proofs.** Write no new test for a count; the roadmap forbids it.
- **The stale-plan proofs, and a live STALE for G8's sake.** §4.
- **The whole-delivery, unrelated-edit and protected-order-zero tests.**
- **The head-of-line nine-capture protocol**, its measurement, disposition or correction. Do not
  re-measure it.
- **R1–R5**, unless the release candidate is superseded. The frozen reader `c9731c8f…` stays as
  embedded.
- **The Phase 7 audit, smoke, deployed restore proof, privacy re-proof and behavioural proof.**
- **The P4.8 and semantic DEVELOPMENT runs.** Curate the existing files; generate nothing again.
  Both holdouts stay sealed.
- **SUR-1.** All five runs are pinned; nothing there is G8's.
- **ADR-0017's `held_from_state` repair.** It is unsound as specified and against the current
  invariant.

## 12. Answers

- **Counts:** 12 CLOSED, 8 PARTIAL, 2 OPEN, of 22.
- **Remaining G8 blockers:**
  - the release candidate at 16/16 (row 19), which needs the owner's S12 decision and, first, the
    CI log reading;
  - the curated, redacted DEVELOPMENT evidence (row 9);
  - the eight PARTIAL rows' single missing conditions (1, 11, 12, 13, 15, 18, 20, 21).
- **Live STALE owed:** no. The roadmap's text is satisfied by the deterministic proofs, and the
  on-screen rendering is proved in §4.
- **16/16 owed:** yes, literally, on the release candidate, as a separate sentence from `11/16`.
- **Product code change justified now:** **no.** The one known blocker, S12, is a contract
  question, and the only product repair ever named for it is unsound. A change becomes justified
  only if action 1 shows another scenario failing on the release candidate's code.
