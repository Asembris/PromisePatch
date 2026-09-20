# `SUR-1` phase 3 closeout: the proof machinery is audited, frozen and left alone

**No arm was driven, no model called, no scorer run on any `SUR-1` scenario, no AWS resource
touched, nothing deployed and no `SUR-1` result directory opened.** `SUR-1` is still unrun,
`AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` is unspent, and both evaluation holdouts stay sealed.

This is the audit taken after [`sur1-consent-ingress.md`](sur1-consent-ingress.md) closed the one
material blocker [`sur1-pre-run-audit.md`](sur1-pre-run-audit.md) found. It asked one question:
**is any material scientific, authority, execution or reproducibility blocker left before the
first scored run?** The answer is no. What remains is access, spend and a different session, and
those are listed at the end under *Phase 4 entry conditions*.

The vocabulary *phase 3 / phase 4* is the execution workstream's and is **not** the roadmap's gate
structure: `new_roadmap.md` runs `G5`–`G9`, `G8` is the open gate, and this benchmark sits outside
`G8`'s required artefacts.

| | |
|---|---|
| Audited at | `f4618c9`, `main`, working tree clean apart from untracked captures |
| CI at that SHA | `pr` **success** on every job; `effect sets (expected red until 16/16)` **failure**, the designed one |
| Runs taken | **none** |
| Frozen artefacts edited | **none** — every identity below recomputed to its published value |

## 1. The matrix

| # | Area | Verdict | Where the proof is |
|---|---|---|---|
| 1 | Consent ingress | **holds** | §2 |
| 2 | Frozen identities | **hold, all seven** | §3 |
| 3 | Isolation | **holds** | §4 |
| 4 | Execution safety | **holds** | §5 |
| 5 | World, CI, records | **holds**, after three later-truth notes | §6 |

Nothing in the harness, the scorer, a frozen document, a world program, the product or the UI was
changed. What this session changed is listed in §7, and it is one docstring, one test and four
notes.

## 2. Consent — verdict: holds

Read from `scripts/sur1/bindings/consentdoor.py`, `worldsink.py`, `world.py`, `run.py` and
`preflight.py`, and from the tests named beside each row. Every test named was run and passed.

| Claim | How it is true | Proof |
|---|---|---|
| the same reply reaches `E2` for every arm | `LiveWorldSink.deliver_reply` writes `ChannelLedger.accept` **first and unconditionally**, then offers the door | `test_sur1_consent_ingress.py::test_the_channel_record_holds_the_same_reply_whether_or_not_a_door_opened`, `::test_the_record_is_written_before_the_door_is_offered` |
| the baseline never invokes PromisePatch's consent | the door presses only a link read from `outbox_messages`; the baseline opens no approval request, so no link exists and the door reports `shut` | `::test_a_channel_nobody_asked_leaves_the_door_shut`, `::test_a_sink_with_no_door_calls_no_approval_endpoint`; `DR01` receipt *harness-channel-record* |
| `PROMISEPATCH` / `ABLATION` use the real signed link | `_press` posts `{"answer": …}` to `{api}/api/customer/approval/{token}` and nowhere else | `::test_the_reply_goes_through_the_signed_link_the_product_actually_sent`; `DR01` receipts, two presses answered `202` |
| sender, channel, request, deadline and literal-parser authority are intact | the body carries no sender, channel, clock or free text; the endpoint derives all of them from the signature and the database; `apps/` was untouched by every ingress commit | `apps/backend/tests/test_customer_approval_link.py` (forged link, other channel, window closed, superseded request, one literal yes, decline never pressed into approval), green in `pr` at `f4618c9` |
| no approval decision is inserted directly | the module names one `SELECT`, one `POST`, one `GET`, and no `INSERT`/`UPDATE`/`DELETE`/`approval_decisions`/`inbound_replies` | `::test_the_door_reaches_one_address_and_writes_to_no_store` |
| replay, stale and superseded fail safely | both deliveries of a redelivered message are pressed and the endpoint's derived record id makes them one decision; `outbox_messages` and `approval_requests` are in `resettable_tables()` so no link survives an attempt | `::test_a_redelivered_message_presses_one_link_and_is_stored_once`, `::test_no_link_from_a_previous_attempt_can_survive_into_this_one`, `::test_receipts_do_not_survive_into_the_next_attempt` |
| a refused or unreachable surface fails closed | `ConsentDoorError` becomes `SinkUnavailableError`, which fails the arming | `::test_a_refused_link_fails_the_event_closed_rather_than_passing_quietly`, `::test_an_unreachable_surface_fails_the_event_closed` |
| the ingress cannot inspect ground truth, a reading or an arm | `preflight.event_blinding` parses `events.py`, `worldsink.py` and `consentdoor.py` for the forbidden scenario fields, the arm names and a scorer import | `::test_the_ingress_can_name_no_answer_no_arm_and_no_reading`; `test_sur1_preflight.py` |
| the ingress is a required preflight check | `consent_ingress` is the seventh of fourteen `REQUIRED_CHECKS`; a world with no door, a stand-in door, or a surface that answers anything but `404` to an unverifiable token is refused | `::test_a_world_with_no_consent_door_is_refused`, `::test_a_stand_in_door_cannot_carry_a_scored_run`, `::test_a_world_whose_surface_verifies_links_is_permitted` |
| the door is one object for the whole run | built once in `run.build`, held on the one `LiveScenarioWorld`, never chosen per arm | `run.py`, `world.py` |

**Two things the audit had to look at harder than the record did.**

*The second inbound row.* On the scored path an arm with a consent protocol carries **two** inbound
rows for one reply — the channel's and the product's own `inbound_replies` row — while the baseline
carries one. The rehearsal sink never produced that shape: it presses the link **instead of**
recording, so `DR01` could not have exercised it. The frozen scorer is neutral to it by
construction — it counts outbound rows against the message ceiling, finds an authorising reply with
`any`, and looks for duplicates among outbound rows only — and that claim was a reading until this
session. It is now a test:
`test_score_safe_useful_recovery.py::test_the_products_own_record_of_a_reply_beside_the_channels_moves_no_verdict`.
No scorer line moved.

*`C02`'s free text.* The scenario stipulates *"Strawberries work."* before the literal `YES`. The
customer page has two buttons and no text field, so the sentence reaches the channel record and
never reaches PromisePatch. The consent record called it *equally unread by every arm*. That is
exact for the consent protocol and too wide for the baseline, which can read the words through the
frozen `read_customer_replies` action. So on `C02` the apparent-assent hazard is posed to the
baseline and not to arms B and C. The direction is bounded — it cannot favour the baseline, cannot
manufacture a finding against any arm, and leaves the primary metric untouched — but it can make
`C02`'s `consent_violations` reading for arms B and C vacuous rather than earned. That is now
recorded beside the original paragraph in `sur1-consent-ingress.md`, and it is a **disclosure
obligation**, not a blocker: say it beside any `C02` safety count published from this benchmark.

## 3. Frozen identities — verdict: all seven hold

Every value recomputed from the bytes on disk in this session and compared with its published value.

| Identity | Recomputed | Published | |
|---|---|---|---|
| `SUR-1` manifest `safe-useful-recovery.v1.json` | `5718340fbd19aa8ba1aedc2327c07a934e22b773271e996f13f0e8d87e70e84c` | same | unchanged |
| baseline prompt `baseline-agent-prompt.v1.md` | `772ba46025620a1aea4742fac3971c5906ec3252036d07725434e0a89ce47cb1` | same | unchanged |
| scorer `score_safe_useful_recovery.py` | v`1.0.0`, pinning the manifest above | same | unchanged |
| predeclaration rules `PREDECLARATION_SHA` | `c53d267a0874d2e91456fdfacc23c86ebfc411f938cbe060ce958cb41d1e1927` | same | unchanged |
| `program_set_sha` | `88db566c13ef7a9865141583e5d918d43ff1b612b3311393c12af627ab1de649` | same | unchanged |
| `implementation_sha` | `34b2daae100034f65e02908489c90e93433f891ca8818ecb387b79c7a9315a8c` | same | as re-frozen over the door |
| `C01`–`C09` program hashes and world digests | all nine agree | same | `declaration.differences()` empty |
| effect-set manifest `scenarios.v1.json` | `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` | same | `11/16` stands, `S12` committed failing |

`docs/benchmarks/runs/` does not exist. No `C01`–`C09` arm result, capture, verdict or token map
exists anywhere in the tree. The realisation record and the wait measurement under
`docs/sur1-realisation/` are the only `SUR-1`-adjacent captures and each says `not_a_benchmark`.
The `DR01` captures under `docs/rehearsals/runs/` are untracked and are rehearsal only.

## 4. Isolation — verdict: holds

| Claim | Structural fact |
|---|---|
| the baseline gets only the frozen facts, tools, prompt and budget | `BaselineArm.run` hands the model `contract.baseline_prompt()` verbatim, `tool_specifications` read from the contract's `tool_surface`, and a `KICKOFF`; the scenario it holds is `scenario_without_ground_truth`, and it reads the world only through `world.invoke` and the shared `AttemptBudget` |
| `PROMISEPATCH` uses ordinary production surfaces | `PromisePatchArm` speaks the worker's four verbs through `LiveWorkerSurface` — MCP `report`, `clarify`, `confirm`, and the workspace status read — and nothing privileged |
| `ABLATION` differs only by check 5 | `AblationArm` composes the one `PromisePatchArm`; `ablated_revalidate` calls the real evaluator unchanged, marks check 5 non-decisive, re-derives from the evaluator's own imported `_OUTCOME_BY_CHECK`, and `assert_only_check_five_moved` is asserted on every call |
| world, event, clock and consent logic are arm-blind | one `LiveScenarioWorld` serves all arms; `Observation` carries only `asks` and `completed`; `settle()` answers the message, never the sender; the anchor is chosen once in `run.build` before any arm exists; the door reads the driven system's own outbox; `event_blinding` and `ground_truth_reachable` parse the syntax of every module on those paths |
| the scorer sees only an opaque token and `E1`–`E4` | `EvidenceBundle` has no `arm`, `label`, `latency` or `cost` field; `blind_bundle` takes none as parameters; `preflight.blinding` parses the scorer's imports and text for any arm name |
| latency, cost and arm labels cannot enter blind scoring | they are joined in `driver.join`, after every verdict is written, out of the attempt captures and the token map |
| `DR01` remains rehearsal only | `scripts/rehearsal/run.py` accepts `--kind development` only, passes its own contract and scorer, and `drive` refuses both for `kind="scored"`; `scripts/sur1` imports nothing from `scripts/rehearsal` |
| rehearsal outcomes changed no `C01`–`C09` fact, prompt, scorer or ground truth | §3 |

## 5. Execution safety — verdict: holds

| Claim | Structural fact |
|---|---|
| a scored run requires a passing preflight and an authorisation | `run.execute` calls `require(check(...))` before `drive`; `drive(kind="scored")` refuses without a `ScoredAuthorisation`; `capture.open_run` refuses a scored directory without one that `authorises_run` |
| direct driver paths cannot create a legitimate scored artefact | `ScoredAuthorisation` cannot be constructed without the module-private sentinel; `preflight.authorise` is the only minter and refuses a report missing any of `REQUIRED_CHECKS`; `claim` is single use and re-observes the fingerprint against the objects actually driven |
| the 300 s attempt budget dominates internal waits | `AttemptBudget` is one ledger for all arms; `LiveWorkerSurface.deadline_seconds` is 240 s for the **whole attempt's** waiting, set once in `report_exception`; measured 6.55 s of actual waiting with the settling fix (`docs/sur1-realisation/20260919T165940-wait-measurement.json`) |
| `VOID` retries once only | `RETRYABLE = frozenset({"VOID"})`, `MAX_ATTEMPTS = 2`, and `AttemptIdentity` refuses a third |
| `INVALID` and `BUDGET_EXHAUSTED` never retry as `VOID` | `BUDGET_EXHAUSTED` and `HARNESS_FAILURE` are written by `write_driver_verdict` without reaching the scorer; an unnamed exception ends the attempt `HARNESS_FAILURE`, never `VOID` |
| resume, write-once and blinding remain correct | `write_once` refuses an existing path; `completed_attempts` and `scored_attempts` skip captured work; verdicts are written before the map is joined |
| `E1` is read-only and arm-independent | `OrderSystemReceiver` makes only `GET` calls (`/readyz`, `/admin/events`, `/orders`) through one reader for all three arms |
| workspace origin, consent ingress, model and configuration, world clock and program identities are required checks | all six are in `REQUIRED_CHECKS`, which `preflight` is asserted to produce exactly |

## 6. World, CI and records — verdict: holds

**Live realisation.** `docs/sur1-realisation/20260919T165013-realisation.json` records all nine
worlds installed into the live local PostgreSQL and order simulator at the ADR-0019 run-local
anchor, `passed: true`, every scenario `digest_agrees` and `armed_and_unfired`, all six essential
facts agreeing on readback, `C01` installed a second time after the other eight reading back
byte-identical, and residue clean both times. It was **not re-run in this session**. Between the
commit before that record (`79da527`) and `HEAD`, the modules it exercises — `realisation.py`,
`programs.py`, `worldsnapshot.py`, `setup.py`, `events.py`, `clock.py`, the Hollow Oak fixture and
the order simulator — are byte-identical; the door commits touched `worldsink.py`, `world.py` and
`run.py`, none of which the install or the readback goes through.

**ADR-0019** preserves meaning and digests: the anchor is not in `describes()`, every digest is
rendered as offsets and recomputed identical at the run-local anchor, `PREDECLARATION_SHA` is
deliberately unchanged, and `world_clock` is a required check.

**CI at `f4618c9`.** `pr`: success. `effect sets (expected red until 16/16)`: failure at the
designed step. The four runs before it show the same shape. Read through the GitHub API; `gh` is
not installed on this machine.

**Stale open items.** Three records said *still open* about things that have since closed, and one
said something that had become too wide. Each got a later-truth note **beside** the original
paragraph, never into it, in the repository's established form:

- `sur1-world-events.md` — *Still open, and now a named blocker* → closed by the consent ingress.
- `sur1-execution-predeclaration.v1.md` — the second-transport paragraph gained the two-row fact;
  *the nine world programs … are not written* gained the pointer to where they are frozen. The
  rules SHA is over `predeclaration.py`, which is untouched.
- `sur1-consent-ingress.md` — *equally unread by every arm* gained the precise statement (§2).
- `scripts/sur1/run.py` — two docstrings still said the nine programs were unwritten and that
  driving refuses for that reason. Rewritten; `run.py` is not one of the hashed
  `IMPLEMENTATION_MODULES`, so no identity moved.

`sur1-pre-run-audit.md` is history and was not edited. The *what is still open* lists in
`sur1-scored-environment.md` and `sur1-consent-ingress.md` name only the Phase 4 conditions below
and stay as they are.

## 7. What this session changed

| Change | Kind | Moves a hash? |
|---|---|---|
| `scripts/sur1/run.py` two docstrings | docs drift in code | no — not in `IMPLEMENTATION_MODULES` |
| `scripts/tests/test_score_safe_useful_recovery.py` one test | narrow regression proof of a neutrality the record asserted | no — the scorer is untouched |
| `docs/sur1-world-events.md`, `docs/sur1-consent-ingress.md`, `docs/benchmarks/sur1-execution-predeclaration.v1.md` | later-truth notes beside stale paragraphs | no |
| this document; one row in `CLAUDE.md` | the record | no |

Validation, per `fast-validate`: `ruff check` and `ruff format --check` over the changed paths;
`scripts/tests/test_score_safe_useful_recovery.py` and `test_sur1_run.py`; the sixteen `SUR-1`,
scorer and rehearsal test modules, all passing. Skipped: the backend suite, the property suite and
the frontend, because nothing under `apps/` or `packages/` changed. GitHub CI stays the regression
authority.

## 8. The freeze

**The `SUR-1` harness and its proof machinery are scope-frozen at this closeout.** The freeze is
recorded as git tree identities at the closeout commit, so a later reader can check it with
`git rev-parse <sha>:<path>` rather than trust it:

| Path | Tree / blob at the closeout commit |
|---|---|
| `scripts/sur1/` | `f953d92b2465e347f36ae9bee3ef5c7363290493` |
| `scripts/rehearsal/` | `01f14418bf7127c3ccfd4860d1acf086696573b3` |
| `scripts/score_safe_useful_recovery.py` | `ace137fa44ad383a969b6ca9b449e84af3f560b6` |
| `scripts/check_sur1_realisation.py` | `997ada54ff4a3f22a8ea10aa0595a9a4f14f9a1c` |
| `docs/benchmarks/` | `529a58d45fdf30f16ca35c2f9bff731a1ab4dd57` |

Beneath those trees the finer identities of §3 continue to be recomputed by the preflight on every
scored run, and `DRIVER_VERSION` is `1.0.0`.

> **Recorded later, beside this block and not into it.** The four requirements below were
> exercised for the first time after the first scored run came back inconclusive. The named
> defects, the disclosure, the re-frozen identities and the separation of sessions are all in
> [`sur1-execution-revision.v2.md`](benchmarks/sur1-execution-revision.v2.md). Under that
> revision `DRIVER_VERSION` is `1.1.0` and `implementation_sha` is `9a80ce0d…3990e1`; every other
> identity in §3 is unchanged, and the scope-freeze tree hashes above are the `f4618c9` ones and
> are history rather than the current tree.

> **Recorded later, beside this block and not into it — the parity correction.** The four
> requirements were exercised a third time, after `20260920T1215Z-scored-v3` was proved invalid.
> The named defects are in [`sur1-v3-forensic-audit.md`](sur1-v3-forensic-audit.md); what was
> changed, what was deliberately not, and the one item left open are in
> [`sur1-parity-correction.md`](sur1-parity-correction.md); the disclosure naming which arms each
> change affects and in which direction is beside the predeclaration. Under this correction
> `DRIVER_VERSION` is `1.3.0` and **`implementation_sha` did not move** — no file in
> `IMPLEMENTATION_MODULES` was touched — and neither did `PREDECLARATION_SHA`, `SCORER_VERSION`,
> the manifest, the prompt, a world program or a scope answer. The scope-freeze trees at
> `87bc505` are:
>
> | Path | Tree / blob |
> |---|---|
> | `scripts/sur1/` | `1b4678e001b104d6a157fd1bedb8ea5d00d67128` |
> | `scripts/rehearsal/` | `b64d6a64114b3770b7f43c4b7c6ae530b6511d1f` |
> | `scripts/score_safe_useful_recovery.py` | `ace137fa44ad383a969b6ca9b449e84af3f560b6` — **unchanged since the closeout**; the metric has never moved |
> | `scripts/check_sur1_realisation.py` | `bf27a5b28ca5436dd607ab399b5f1f5515088d86` |
> | `docs/benchmarks/` | `8bfb5807a86c85b3a79fb76b107359da91649a37` |
>
> Requirement 4 holds and is load-bearing here: this correction changes what arms B and C are
> driven against, and the session that made it is not the session that takes any later run.

> **Recorded later, beside this block and not into it — the hosted-worker topology.** The four
> requirements were exercised a fourth time, to close the one item the parity correction named,
> refused and left open. The named defect is `F4` in
> [`sur1-v3-forensic-audit.md`](sur1-v3-forensic-audit.md) §5 — arm C's ablation reached no
> evaluator on any topology that existed, so arm C was arm B by construction on all three
> published runs. The decision that authorises the repair is
> [ADR-0020](adr/0020-a-scored-benchmark-hosts-the-product-s-own-worker.md); what was built is in
> [`sur1-hosted-worker.md`](sur1-hosted-worker.md); the disclosure naming which arms it affects
> and in which direction is beside the predeclaration. Under it `DRIVER_VERSION` is `1.4.0` and
> **`implementation_sha` did not move** — no file in `IMPLEMENTATION_MODULES` was touched — and
> neither did `PREDECLARATION_SHA`, `SCORER_VERSION`, the manifest, the prompt, a world program
> or a scope answer. `REQUIRED_CHECKS` is 28. The scope-freeze trees at this change are:
>
> | Path | Tree / blob |
> |---|---|
> | `scripts/sur1/` | `d99945afa3c639afdaf770c9434ed36c834dc748` |
> | `scripts/rehearsal/` | `b64d6a64114b3770b7f43c4b7c6ae530b6511d1f` — **unchanged** by this work |
> | `scripts/score_safe_useful_recovery.py` | `ace137fa44ad383a969b6ca9b449e84af3f560b6` — **unchanged since the closeout**; the metric has never moved |
> | `scripts/check_sur1_realisation.py` | `bf27a5b28ca5436dd607ab399b5f1f5515088d86` — **unchanged** by this work |
> | `docs/benchmarks/` | `c49c1eb7834f6a736ec16baeac28d1b011be39e6` |
>
> Requirement 4 holds and is load-bearing again: this change moves the topology arms B and C are
> driven at, and the session that made it takes no run. `DR01` through the corrected seam,
> against the live local stack, is owed before any spend.

**What a change under those paths now requires, before the first scored run:**

1. **A concrete, named defect** — an observed wrong behaviour with a reproduction, not an
   improvement, a tidy-up or a feature. Adding a scenario, a metric, a tool, an arm capability or
   a benchmark feature is out of scope until the first scored run has been published.
2. **Disclosure beside the predeclaration** — a *Recorded later* note in
   `sur1-execution-predeclaration.v1.md` or a successor record stating what moved, which arms it
   affects and in which direction, before any run is taken under it.
3. **Versioning** — the identity that covers the changed bytes is re-frozen and its move is named:
   `implementation_sha` for the eight `IMPLEMENTATION_MODULES`, `PREDECLARATION_SHA` for a reading
   rule, `DRIVER_VERSION` for driving or evidence collection, `SCORER_VERSION` for the metric. A
   frozen document — the manifest, the prompt, the scorer's rules, a world program, a label — is
   never edited; a defect there is disclosed as a limitation and scored as it stands.
4. **The same session does not score.** The contract's freeze block still holds: the session that
   changes the machinery is not the session that takes the scored run.

## 9. Phase 4 entry conditions

Everything left is outside this repository's control or outside this session's remit. None of it is
a defect in the machinery.

1. **A model this account can invoke** at the frozen configuration
   (`us.amazon.nova-2-lite-v1:0`, `bedrock-runtime` Converse, temperature `0.0`, an explicit
   region), and `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE`, which is unspent.
2. **The scored preflight run against real bindings with a region set**, all fourteen checks in
   one report. `model_identity` and the AWS half of `configuration` have never been asked of a real
   account; `consent_ingress`, `receivers` and `workspace_origin` have each passed against the
   local stack, never all fourteen together.
3. **A different session** takes the first frozen `SUR-1` run, in full, `C01`–`C09` across all
   three arms, and publishes it whatever it says, with the `C02` disclosure in §2 beside it.
4. **Then the release work `G8` actually requires**: the release-candidate deployment, its
   evidence, and the deployed rehearsals, which are not this benchmark's.

## 10. What this audit did not do

- **It drove nothing and called nothing.** No arm, no model, no AWS call, no deployment.
- **It edited no frozen artefact** and moved no published hash.
- **It did not re-run the live realisation check**, and says so in §6 rather than inheriting it.
- **It did not run the backend suite**; the consent endpoint's own proofs are the `pr` workflow's,
  green at `f4618c9`, over code no ingress commit touched.
- **It opened no holdout**, wrote no `SUR-1` capture and minted no authorisation.
