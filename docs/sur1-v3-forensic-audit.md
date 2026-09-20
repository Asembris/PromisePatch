# `SUR-1` v3 forensic audit: the baseline that could not be placed, the arms that did nothing, and the model that was never there

**Diagnosis only, taken fresh.** No `C01`–`C09` attempt was driven, no model was called, no scorer
ran, no AWS API was touched, no capture, verdict, `result.json`, `run.json` or `arm_map.json` was
written, no frozen document, prompt, manifest, scorer, world program, budget or label was edited,
no holdout was opened and no code was patched. Every claim below was re-derived in this session
from the artefacts, the container runtime, the live local database and the source at HEAD; an
earlier untracked draft of this record was read and is superseded by this one, not relied on.

| | |
|---|---|
| Run audited | `20260920T1215Z-scored-v3`, driven 2026-09-20 12:05:07–12:13:17 UTC, `DRIVER_VERSION` `1.2.0`, `implementation_sha` at `bbd16d6e6135` |
| Audited at | `1c41c3c4c63a` (`main`), tracked tree clean; untracked files only |
| Evidence read | the 27 captures and 27 verdicts; `run.json`, `result.json`, `arm_map.json`; the `worker`, `api` and `mcp` container logs over 12:04–12:14Z; `docker inspect` of the three containers that served the run (environment key names, and the values of the non-secret provider and demo keys only); the compose file and the generated env-file key names; the local PostgreSQL database as the run left it, read only; the live order simulator's `GET /orders`; harness, product and simulator source at HEAD; the two prior runs; `scripts/tests` |
| Computations | the three run digests; `frozen.assert_frozen()`, `predeclaration.identity_sha()`, `declaration.differences()` |

## 0. Findings

| # | Finding | Class |
|---|---|---|
| F1 | The harness's own transport accepts arm A's `channel_address` verbatim. The model is shown the split form by `get_orders` (`{"kind": "telegram", "address": "1002"}`) and sends the bare `1002`; the fixture, the arming and the placement know only `tg:1002`. Nothing on the path rejoins it. | **ROOT CAUSE** of 8 `HARNESS_FAILURE`, and of the baseline never being answered on any scenario in either run |
| F2 | On every worker start the product's demo provisioning opens the canonical demo case inside the freshly installed `SUR-1` world and attests today's raspberry line `NOT_RECEIVED` before the arm reports. The v2/v3 per-attempt worker lifecycle made this happen on all 27 attempts. The arm's identical report then binds to tomorrow's delivery, is asked a scope question its frozen answer cannot resolve, is asked again, and stops. | **ROOT CAUSE** of arms B and C producing no effect on `C01`–`C03`, `C05`–`C09`; a world-integrity defect on all 27 attempts |
| F3 | The `api`, `worker` and `mcp` containers that served the run carry no `PP_LLM_PROVIDER`, no `PP_BEDROCK_*`, no `PP_AWS_REGION` and no `AWS_*` variable. The product resolved `LlmProvider.FAKE`. Arms B and C could not have called the frozen model by any path. | **MATERIAL SCIENTIFIC BLOCKER** — the contract's same-model constraint is not met and no preflight question asks |
| F4 | Arm C's wrapper rebinds `promisepatch.domain.revalidation.revalidate` in the harness process; the evaluator that decides runs in the `worker` container. `diagnostics.ablation` is `[]` on all nine v3 attempts and on all eight run-1 ablation captures. Arm C is arm B by construction on this topology. | **MATERIAL SCIENTIFIC BLOCKER** — the ablated arm is unmeasurable, not merely unmeasured |
| F5 | The harness's frozen scope answers are not resolvable against the question the contaminated world asks: `SCOPE_ANSWER_CAME` reads as one positive clause (` -- ` is not a clause separator), `SCOPE_ANSWER_SHORT` splits on ` but ` into two missing resources that match neither option. | **CONTRIBUTING**, latent: only reached because F2 caused a question the clean world never asks |
| F6 | Arm A's `report_outcome` produced an empty `E4` on 18 of 18 baseline attempts across two runs. The Converse schema declares `report` as a bare `object` with no properties, and the baseline's message list is local to `BaselineArm.run` and discarded, so the capture holds no transcript. | **CONTRIBUTING**; the exact mechanism is an **OPEN QUESTION** the artefacts cannot close |
| F7 | The served image carries the measured product code; the database target was one on every attempt; no first-run failure signature recurred. | NOT A DEFECT — confirmed |
| F8 | The v3 record's §3.1 says the bare address is "how the database stores an approval channel", and §3.2 stops at "never reached the model". The `E2` row is the harness ledger's (`provider_event_id: sur1-out-…`), not an outbox row; and B and C did not stop for want of a model. | CORRECTED HERE; the record is not edited |

## 1. Baseline `E2` failure, traced end to end

### 1.1 The trace

1. **Customer identity in the fixture.** `promise_graph.examples.hollow_oak` gives `cus-tomas`
   `approval_channel="tg:1002"` (`hollow_oak.py:610`). The frozen manifest's `fixture.orders.ord-b.channel`
   is `tg:1002`. The `C01` program's armed event is `reply 1 on tg:1002`
   (`docs/benchmarks/sur1-world-programs.v1.json`, `programs.C01.armed_events`).
2. **What arm A is shown.** `get_orders` is the order simulator's own snapshot. The simulator is
   seeded with `SeedCustomer("cus-tomas", …, "telegram", "1002")` (`apps/order-simulator/.../seed.py:80`),
   stores `channel_kind`/`channel_address` split, and serialises `CustomerRef.approval_channel`
   as `ChannelRef(kind, address)` (`packages/order-contract/.../events.py:59-69`,
   `store.py:532`). Read live from the running simulator during this audit:
   `"approval_channel": {"kind": "telegram", "address": "1001"}`. `get_promise_graph` renders the
   same customer as `approval_channel: "tg:1002"` (`scripts/sur1/bindings/worldsnapshot.py:139-143`).
   The frozen tool contract says only *One outbound message to one channel address*; the harness's
   argument shape says only `channel_address: string` (`scripts/sur1/adapters.py:88`); the frozen
   prompt says *from that order's own approval channel address* (`baseline-agent-prompt.v1.md:94-97`).
   Two spellings are shown and no rule is stated.
3. **The action.** The model called `send_customer_message` with `channel_address: "1002"` (all
   eight placed `E2` rows on `ord-b`; `1003` on `C02`, `1004` on `C07`).
   `LiveScenarioWorld._send_customer_message` builds
   `ChannelMessage(channel_address=str(arguments.get("channel_address", "")), …)` and hands it to
   `ChannelLedger.accept`, which appends it unchanged (`world.py:447-461`, `receivers.py:499-501`).
   The `E2` row's `provider_event_id` is `sur1-out-<uuid>`, the ledger's own prefix: the row is
   the harness transport's, not an outbox row.
4. **The arming.** `settle()` reads `ChannelReceiver.read`, which unions the outbox (rejoined by
   `channel_identity`, correctly), `inbound_replies` (sender as stored) and the ledger (as stored)
   (`receivers.py:429-434, 453, 475`). `observe()` counts asks by `channel_address`
   (`events.py:125-136`); the trigger watches `tg:1002`; the count lands under `1002`; `C01:reply:1`
   never fires. **Every baseline capture in both runs holds only `OUTBOUND` rows and no `INBOUND`
   row.** The baseline was never answered on any scenario.
5. **Placement.** `driver.score_attempt` → `blind_bundle` → `_sequenced` →
   `FixtureMap.order_for_channel("1002")` raises `EvidenceMalformedError`; the driver writes a
   `HARNESS_FAILURE` verdict with the note quoted in the v3 record (`evidence.py:283-290`,
   `driver.py:253-268`).

### 1.2 Answers

- **Exactly where `tg:1002` becomes `1002`:** nowhere on the harness path. The joined identity
  never entered the transport. The order system holds the split form by contract, showed the model
  the bare address, the model repeated it, and the harness transport recorded it verbatim. The one
  join the harness performs, `receivers.channel_identity`, is applied to outbox payloads only.
- **Normalisation, transport or fixture mismatch:** a representation mismatch between two systems
  of record (engine: one opaque joined string; order contract and database: split kind and
  address), exposed at the harness's own transport boundary because that boundary is the one place
  on the path that canonicalises nothing. The `promisepatch.graph.channel` codec exists exactly to
  move between the two shapes, and the harness restates it for outbox rows and for the consent
  door (`receivers.py:83-99`, `consentdoor.py:196-210`) but not for the ledger.
- **Canonical representation every arm should use:** the engine's opaque joined string,
  `tg:<address>` (`promisepatch.graph.channel.join_channel`), which is also the frozen fixture's
  form, the arming's form, the product's outbox and `inbound_replies` form (run 1 shows `INBOUND
  tg:1002` from both records), and the only form `FixtureMap` can place. The order contract's
  split form is the order system's and stays where it is.
- **Same risk elsewhere:** yes, systematically. All 10 v3 baseline outbound rows and all 11 run-1
  baseline outbound rows are bare (`1002` ×16, `1003` ×2, `1004` ×3). Every fixture channel is
  telegram; the fixture has no whatsapp or console customer, so no other kind is exercised. A
  second consequence is latent in `_read_customer_replies` (`world.py:400-406`): it renders
  whatever the channel holds, so a baseline that had been answered would read a reply from
  `tg:1002` against a message it sent to `1002`, and its own prompt tells it *a reply from any other
  address is not that customer's answer*. **The test suite never sends the bare form**: every
  `send_customer_message` in `scripts/tests/test_sur1_live_bindings.py` (lines 625–767) uses
  `tg:100x`, and `test_sur1_frozen.py` only names the tool.

Not patched. The correction belongs at `world._send_customer_message` (and `_read_customer_replies`
for symmetry), resolving an address through the codec the receivers already restate and refusing
one that resolves to no known channel; not at placement, which would leave the arming blind, and not
in the fixture, the contract or `get_orders`, which are frozen or are another system's own snapshot.
Whether the tool contract should additionally *state* the form changes what arm A is told and is a
predeclaration question (§7).

## 2. Arms B and C: where each stopped making progress

### 2.1 The captures

All 18 B/C attempts: `model_calls 0`, `tool_calls 4`, `E1 []`, `E2 []`, `E3` six tasks unchanged
with `held_by: null`, `E4` `exception_recorded: true` with six `UNTOUCHED` promises. On the eight
raspberry scenarios the reason is `not named by the case status`; on `C04` it is `left alone`. The
`mcp` log shows the four calls: `report` ×18, `clarify` ×16, `confirm` ×2 (`C04` ×2), `status` ×110
across the run (`status` is not charged as a frozen action).

### 2.2 The product, per attempt, from three container logs and the database

`C01` / `PROMISEPATCH`, case `651a56b3`:

| UTC | Process | Event |
|---|---|---|
| 12:09:30.5 | worker | `worker.stop` — quiesce for the `C01` install |
| 12:09:33.9 | worker | **`intake.case.opened` `5ffe7323` by `maya`** — `provisioning.ensure_demo_case` at worker start, saying `today's raspberry delivery didn't arrive` into the just-installed world |
| 12:09:33.9–34.3 | worker | that case: `interpret`, `resolve`, `analyze`, `plan` all `COMPLETED`; `worker.demo_case STOPPED PLANNED "no answerable question was reached"` |
| 12:09:34.3 | worker | `worker.start` |
| 12:09:39.9 | api / mcp | `mcp.tool.report` → `intents.report.accepted` → `intake.case.opened` **`651a56b3`** — the arm's report |
| 12:09:40.5 | worker | `interpret` + `resolve` for statement `641093ac` |
| 12:09:41.7 | api / mcp | `mcp.tool.clarify` → `intake.clarification.answered` |
| 12:09:42.7 | worker | `interpret` + `resolve` for statement `e48ab4ba` — and nothing after |
| 12:09:44.0 | worker | `worker.stop` for the next install |

The database still holds the last world of the run (`fixture_state` = `hollow-oak+sur1-C09`), and
it shows the same shape directly, without inference:

- `exception_facts`: one row, `cl-vp-today-raspberries` `EXPECTED → NOT_RECEIVED`, `attested_by
  maya`, **12:13:09.63** — the demo case's, four seconds before the arm's report at 12:13:14.05.
- `exceptions`: one row, the demo case's (`com-vp-today`, `["cl-vp-today-raspberries"]`). The arm's
  case has none: it never bound an exception.
- `exception_clarifications` for the arm's case `7b6d78c1`: ordinal 1, slot `SCOPE`, question *The
  Valley Produce delivery also includes blueberries. Did the whole delivery fail, or just the
  raspberries?*, options `WHOLE_DELIVERY` → `com-vp-tomorrow` `[cl-vp-tomorrow-blueberries,
  cl-vp-tomorrow-raspberries]` and `JUST_RASPBERRIES` → `com-vp-tomorrow` `[cl-vp-tomorrow-raspberries]`,
  `answer_text` = `just the raspberries -- but the strawberries were short`, **`resolved_option_code`
  NULL**; ordinal 2, the identical question, unanswered. The case is `CLARIFYING`.
- `commitment_lines`: `cl-vp-today-raspberries NOT_RECEIVED`, `cl-vp-today-strawberries SHORT`
  (the program's own step), the tomorrow lines `EXPECTED`.

Step accounting across the whole run window (`worker.step.executed`): `BEGIN_INTERPRETATION` 64 =
27 demo reports + 3 demo answers (`C04` worlds) + 18 arm reports + 16 arm answers;
`RESOLVE_OBSERVATION` 64; `ANALYZE_IMPACT` 29 = 27 demo + 2 arm (`C04` ×2); `PLAN_RECOVERY` 29;
`RECONCILE_CASE` 2. **No arm case on a raspberry scenario reached `ANALYZE_IMPACT`.** No
`semantic.*` event of any level appears in the worker log in the window (`PP_LOG_LEVEL=info`,
`ObservedSemanticProvider` logs at INFO/WARNING).

### 2.3 The mechanism

`provisioning.ensure_demo_case` runs from `worker.py:487` at every worker start, gated only on
`PP_DEMO_SESSION_ENABLED` (`provisioning.py:242`), which is `true` in the `api` and `worker`
containers. It finds a world whose single today's raspberry delivery makes it "current"
(`_world_tells_the_story`), no live case (the install truncated `cases`), no case with the derived
identity, and opens one with `REPORTED = "today's raspberry delivery didn't arrive"` as `ATTESTOR =
hollow_oak.BAKER` (`maya`). The v2 lifecycle (`ComposeWorkerControl.quiesce`/`resume`) stops and
restarts the worker around every install, so this ran **27 times in the window**: 27 `worker.start`,
27 `worker.demo_case` — 24 `STOPPED` at `PLANNED` (raspberry worlds, where the program had already
settled strawberries so no question is reachable) and 3 `OPENED` at `PLANNED` (the `C04` worlds,
where the demo case asked and answered its own scope question at 12:06:44, 12:10:10 and 12:12:06).
`InstallationLifecycle.around` runs `verify` **before** `resume` (`lifecycle.py:235-242`), so the
world is never re-read after the worker comes back. The first scored run's worker was never
restarted, which is why its B/C captures show amendments on `EXT-A`/`EXT-B`, asks on `tg:1002` and
replies received — the clean path, with the same four tool calls and no `clarify`.

After the demo case settles today's raspberry line, the arm's identical sentence finds no
commitment with an open raspberry line except `com-vp-tomorrow`; that candidate has another open
line (blueberries), so the deterministic reader asks the scope question about tomorrow's delivery.
The harness's frozen answer then fails `_resolve_scope_answer` (`interpretation.py:736-757`):

- `just the raspberries -- the strawberries came` (`C01`–`C03`, `C05`–`C08`): ` -- ` is not in
  `_CLAUSE_SEPARATORS` (`interpretation.py:202-216`), so it is one clause; `came` is a
  `POSITIVE_MARKER`, both named resources land in `arrived`, `missing` is empty, the result is `None`.
- `just the raspberries -- but the strawberries were short` (`C09`): ` but ` **is** a separator;
  clause one is `just the raspberries` (`RESTRICT_MARKER`, default missing → raspberries), clause two
  has `short`, a `NEGATIVE_MARKER` → strawberries; `missing = {raspberries, strawberries}` equals
  neither `{raspberries}` nor `{blueberries, raspberries}`; `None`.

The question is re-asked (ordinal 2, under `CLARIFICATION_CEILING = 2`).
`PromisePatchArm.drive_through_surface` answers once by design and breaks on a second request
(`adapters.py:186-221`), reads `status`, and `predeclaration.worker_report` projects a case naming no
promise as six `UNTOUCHED` / `not named by the case status`. `C04` differs only because its
mascarpone report is unambiguous: it resolved, analysed, planned, was approved on the workspace and
confirmed (`recovery.plan.confirmed applying: 0, escalated: 0, awaiting_approval: 0`), a correct
nothing taken in a world that also held a foreign case.

### 2.4 The checklist, per arm, all nine scenarios

| Step | `C01`–`C03`, `C05`–`C09` (B and C alike) | `C04` (B and C alike) |
|---|---|---|
| incident reported | yes, `report` accepted, case opened | yes |
| clarification requested / answered | requested about **tomorrow's** delivery; answered once with the frozen words; **unresolved**; re-asked; unanswered | not asked |
| semantic intake started | deterministic reader only; never `HumanInterpretationRequired`, so no semantic job | same |
| model / provider invoked | **no** — and could not be (§3) | no |
| plan created | no | yes, `PLAN_RECOVERY` |
| human confirmation | n/a | yes: workspace approve (`401` from the truncated `sessions`, re-login, `201`), `plan.approval.recorded`, `mcp.tool.confirm` |
| consent request / reply | none; no `approval_requests` row, no outbox `MESSAGE_SEND` | none needed |
| recovery / revalidation | none | `applying: 0`; nothing to apply |
| outbox / provider effect | none | none |
| terminal status | `CLARIFYING` on an unanswered second question | `RESOLVED`/confirmed, six promises left alone |
| **first point progress stops** | **the second `SCOPE` question, caused by the demo case's attestation (F2) and unresolvable by the frozen answer (F5)** | it does not stop; the reading is a correct nothing in a contaminated world |

A post-run observation shows what the foreign case can do to `E3` if an attempt window were longer:
the `C09` world's demo case auto-escalated at 12:23:10 (`ESCALATE_PLAN PLAN_UNCONFIRMED`) and now
holds `task-ol-a`…`task-ol-d` (`held_by_case_id = 5ffe7323`). That was ten minutes after the run's
last collection and touched no capture.

## 3. Product model parity

| Question | Answer, from the runtime |
|---|---|
| provider configured in `api` / `worker` | **none set**; `docker inspect` of `promisepatch-api-1`, `-worker-1`, `-mcp-1` (image `1c0653c73dd6`, created 2026-09-19T23:12Z; `api`/`mcp` started 09:07Z, `worker` last started 12:13:07Z by the run's final resume) shows no `PP_LLM_PROVIDER`, `PP_BEDROCK_MODEL_ID`, `PP_AWS_REGION`, `AWS_PROFILE`, `AWS_ACCESS_KEY_ID` or `AWS_REGION`. `docker/env/api.env` (the file both `api` and `worker` load) has no such key; `api.env.example` sets `PP_LLM_PROVIDER=fake` and says nothing mounts an AWS profile. Compose mounts none. |
| provider the product resolved | `Settings.llm_provider` defaults to `LlmProvider.FAKE` and is deliberately not inferred (`config/settings.py:198-206`); `build_semantic_provider` returns `ObservedSemanticProvider(FakeSemanticProvider())` (`integrations/semantic_provider.py:102-104`). **The fake, on every attempt.** |
| model id and parameters the product *would* use | `bedrock_model_id` default `us.amazon.nova-2-lite-v1:0`, `TEMPERATURE = 0.0` (`integrations/bedrock.py:49, 229`), `aws_region` default `us-east-1`. They match the frozen requirement only in a process configured for Bedrock. |
| did the worker make provider calls during v3 | no: zero `semantic.*` events in the window, and the deterministic reader never escalated (§2.2). Two independent reasons; either alone is sufficient. |
| Bedrock, another provider, fallback, disabled or absent | **absent by configuration**: the fake, which reaches no network. Not a fallback (there is none) and not a failure. |
| baseline's model | `BedrockConverseClient.from_contract`, `us.amazon.nova-2-lite-v1:0`, temperature `0.0`, `us-east-1`, opened in the harness process with the host's AWS credentials; `preflight.model_identity` checks this object and nothing else. |
| `run.json` `environment.model_provider_configured: false` | `bool(os.environ.get("PP_LLM_PROVIDER"))` read in the **harness** process (`manifest.py:96`); informational, about the wrong process, gated on by nothing. |
| did BASELINE and B/C use the frozen model | **No.** BASELINE used it. B and C ran on a product that held the fake. |

**Classification: scientific blocker.** The manifest's `PROMISEPATCH.constraints` — *Its semantic
boundary calls the same model, with the same parameters, as the baseline arm* — and
`model_configuration.applies_to: [BASELINE, PROMISEPATCH, ABLATION]` are not satisfied by the local
stack as it ran. In v3 the gap was latent because no semantic job was ever reachable; after F1, F2
and F5 are corrected, every sentence the deterministic reader cannot bind would go to the fake in
arms B and C and to Nova in arm A, and the comparison would be attributing a model difference to
architecture. Correcting it changes the deployed configuration under test, so it is a disclosure
under `sur1-phase3-closeout.md` §8 before any run, not a quiet env-file edit.

**The image was the measured code.** The last commit touching `apps/` or `packages/` is `c9a16dd`
(2026-09-19T20:44Z); the image was built 2026-09-19T23:12Z; no product commit followed. The
stale-image defect of the first run did not recur.

## 4. Preflight gaps

`REQUIRED_CHECKS` is eighteen and all eighteen passed. What each proves, and what none asks:

| Guarantee | Proved today? | The check that would have refused v3 |
|---|---|---|
| baseline model identity | **yes** — `model_identity` compares the binding's `identity()` with `contract.model_configuration` and requires a region | — |
| product-side semantic provider / model identity | **no** — `backend_build` reads `/readyz`, whose schema is `status, service, version, boot_id, database, migrations, fixture` (`api/schemas/readiness.py:72-83`); no field names a provider or a model | `product_model_identity`: read a provider identity the running product publishes (`llm_provider`, `bedrock_model_id`, `aws_region`, temperature) from the process that executes semantic jobs, and require equality with `contract.model_configuration`. Would have refused every run on this stack. |
| product-side credentials / provider readiness | **no** | the same surface stating whether a credential resolves for that provider (a boolean, never a value), required `true` when the provider is `bedrock` |
| canonical customer-channel representation | **no** — `receivers` probes reachability only; the codec test covers outbox rows only | `channel_transport`: send one synthetic message through the world's own `send_customer_message` path with each address form the world shows (`get_orders`'s bare address and `get_promise_graph`'s joined one) against a throwaway ledger, and require both to resolve to a channel `FixtureMap` can place and `observe()` counts under the arming's name. Would have refused v3 and run 1. |
| `E2` placement compatibility | **no** | the same check's second half, plus a dry projection of a synthetic `report_outcome` through `tool_configuration` and `_report_row` that survives `_report_is_valid`; would have flagged the empty-`E4` path before spend (F6) |
| world clean when the arm acts | **no** — `worker_lifecycle` proves the worker can be stopped and started; `lifecycle.verify` reads `fixture_state` before `resume` | `world_integrity`: refuse a scored stack whose `worker` carries `PP_DEMO_SESSION_ENABLED=true`, or, in the lifecycle, re-read `cases` (must be empty) and `commitment_lines` (must equal the declared world) **after** `resume`. Would have refused all 27 attempts. |
| arm C reaches the evaluator | **no** — `real_bindings` and `test_sur1_ablation.py` prove in-process rebinding | `ablation_reach`: require that the process evaluating revalidation for arms B and C is the process the wrapper is installed in, or refuse. Would have refused every containerised run. |

## 5. Adjacent parity audit

| Area | Finding | Class |
|---|---|---|
| Channel / customer identity | three unnormalised sites on the harness side: `world._send_customer_message`, `world._read_customer_replies`, and the two spellings the reads show (`get_orders` split, `get_promise_graph` joined); `receivers.channel_identity` covers outbox rows only; no test sends the bare form | ROOT CAUSE (§1) |
| Customer replies | `worldsink.deliver_reply` writes the ledger first with the joined channel and offers the door second; the door compares `channel_identity(body)` with the joined channel; arm-blind and correct. It never ran for the baseline because the arming never saw its ask, and never for B/C because they never asked | consequence, NOT A DEFECT of the sink |
| World integrity | every one of the 27 worlds carried an undeclared case, an undeclared `NOT_RECEIVED` attestation on `cl-vp-today-raspberries` by `maya` and a `PLANNED` plan before any arm acted. Arm-blind in application, arm-correlated in effect: B and C read the world through intake; arm A's `get_promise_graph`, `get_stock` and `get_tasks` are live reads of the same database, so A saw it too, and what that did to A's reasoning is not recoverable from the captures | ROOT CAUSE (§2) |
| Tool names / arguments | `report_outcome` is published to Converse as `{"report": {"type": "object"}}` with no properties (`bedrock.py:126-159` maps the word before the comma; `adapters.py:91`); `_report_row` found no `promises` on 18/18 baseline attempts across two runs; `BaselineArm.run` keeps `messages` local and records no transcript (`adapters.py:142-167`); the mechanism cannot be shown | CONTRIBUTING; OPEN |
| Timestamps / clock | anchor `2026-09-20T11:00Z`, run 12:05–12:13Z, `Africa/Tunis`; `world_clock` passed; the reader's day narrowing places today's delivery today. `started_at` is taken after `resume`, so the demo case's writes may precede `since` and are invisible to the receivers while visible to the product | NOT A DEFECT of the clock; a consequence of F2 |
| Order / version identifiers | `E1` rows are the order system's own events at version 2; 14 `worker.order_mirror.processed` in the window; the `C05`/`C08` `STALE` dispositions were not re-derived here | not examined further |
| Provider / event ids | ledger rows `sur1-out-<uuid>`; product rows carry `provider_ref` / `provider_message_id`; `C07`'s redelivery keeps one `message_id` by design | NOT A DEFECT |
| Model / provider config | §3 | BLOCKER |
| Ablation reach | `ablation()` does `setattr(promisepatch.domain.revalidation, "revalidate", …)` in the harness process (`ablation.py:228-245`); `sur1-execution-harness.md` states no deployed process can reach the wrapper — which is exactly why the deployed worker cannot be ablated by it; `diagnostics.ablation == []` on 9/9 v3 and 8/8 run-1 ablation captures | BLOCKER |
| Workspace session | the install truncates `sessions`; `POST /api/conversation/approve` answered `401` once per `C04` attempt, the client re-signed in (`auth.login` ×3 in the window) and succeeded | NOT A DEFECT |
| MCP auth rejections | `mcp.auth.rejected` ×176 in the window, all from `127.0.0.1` every ~3.4 s: the compose healthcheck POSTs `/mcp` without a bearer and expects `401` (`docker-compose.yml`, `mcp.healthcheck`) | NOT A DEFECT |
| Audit ledger truthfulness | `KitchenWriter.hold` writes its governed audit row (`BENCHMARK_WORLD_TASK_HELD`, `after.state = HELD`) inside the same governed block as the `UPDATE … WHERE state = SCHEDULED`, so a refused hold on started work still records `HELD` (`setup.py::hold`, `governed.py:109-136`). Seen on `C05`: `task-ol-e` at 12:07:25Z while `production_tasks` stayed `STARTED` and `E3` correctly read `STARTED` | MINOR; `E3` is read from `production_tasks`, the audit row is not scored |
| `E4` for arms B and C | `_projected_report` passes `exception_recorded=True` unconditionally (`world.py:549-557`); on the eight raspberry scenarios the arm's case had recorded no fact. The scorer declares the field and does not read it | MINOR; not a scoring effect |
| `audit_events` / `domain_events` | never emptied by the governed load, by design (`fixtures/reset.py:10`); 152 100 rows spanning every prior run; read by no receiver | NOT A DEFECT |
| Stock event `C06:stock:1` | depends on `C06:reply:1`, which never fired for the baseline and was never owed to B/C | consequence |

## 6. Preservation

Recomputed at `1c41c3c`, read-only, with the algorithm `test_sur1_database_target.py` pins (path,
`\0`, bytes with `\r\n` normalised, `\0`, sorted):

| Artefact | Files | Digest | |
|---|---|---|---|
| `20260919T2020Z-scored` | 57 | `d599d644c6869fe527a32cfe240fe9a20433ed4a07679b02fbb597fecdc746ed` | matches the pin |
| `20260920T1100Z-scored-corrected` | 57 | `e2a46c35b53902c817b9602999bb84f3df82cd3c7b425cb813551e7817364bca` | matches the pin |
| `20260920T1215Z-scored-v3` | 57 | `403622ecd45a34723517556570d1b154c3f11f0e1fcaf9201856eeff6b9e18ca` | **not pinned anywhere yet**; recorded here so a later edit is detectable |

`git diff HEAD -- docs/benchmarks scripts/score_safe_useful_recovery.py scripts/sur1` is empty; the
scorer blob is `ace137fa44ad383a969b6ca9b449e84af3f560b6`, `scripts/sur1` tree
`7a31faa35e76ada8efe5a6f6c8a05558dbf15e23`, `docs/benchmarks` tree `b4d0a43edb55bfada0b37247a8f465637f73c61f`.
`frozen.assert_frozen()`: manifest `5718340f…e70e84c`, prompt `772ba460…9ce47cb1`, scorer `1.0.0`.
`predeclaration.identity_sha()` `c53d267a…1e1927`. `declaration.differences()` is `()`.
`DRIVER_VERSION` `1.2.0`. No holdout was opened. Nothing was rescored or reinterpreted.

## 7. Correction plan, ordered by severity, with the identities that move

None of it is done here. Each item that touches `scripts/sur1/` needs the four requirements of
`sur1-phase3-closeout.md` §8; each item that changes the system under test needs a disclosure
beside the predeclaration as well.

| # | Correction | Where | Identity that moves | Disclosure |
|---|---|---|---|---|
| 1 | **Product model parity.** The processes that execute semantic jobs must run `PP_LLM_PROVIDER=bedrock` with `PP_BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0`, `PP_AWS_REGION`, and a credential path into the container; the product must publish its provider identity on a read-only surface; the preflight must compare it with the contract | product (`readyz` or beside it), `docker/env/api.env`, compose, `preflight.py`, `REQUIRED_CHECKS` → 19 | `DRIVER_VERSION`; the product's own revision; the run manifest gains the product's provider identity | yes — the system under test changes; say which arms it affects (B and C) and in which direction (they gain a model they did not have) |
| 2 | **Arm C reach.** Decide, under the contract, how the ablation reaches the evaluator that decides: an in-process worker for the scored run, or a declared governed seam. Both change what is measured | ADR; `scripts/sur1/ablation.py`, `adapters.py`, the run topology | `DRIVER_VERSION`; possibly `implementation_sha` if a binding module moves; the contract's `how_it_is_removed` is frozen and would be disclosed as a limitation if the mechanism differs | yes |
| 3 | **Clean world after resume.** Run the scored stack with `PP_DEMO_SESSION_ENABLED=false` on the `worker` (and `api`) and refuse otherwise, and/or re-verify `cases` and `commitment_lines` after `resume` in the lifecycle. The product's provisioning behaves as documented and needs no change | `docker/env/api.env`, `preflight.py`, `bindings/lifecycle.py` | `DRIVER_VERSION` (`lifecycle.py` is not in `IMPLEMENTATION_MODULES`); `REQUIRED_CHECKS` → 20 | yes — the deployed configuration changes |
| 4 | **Channel identity at the harness transport.** Resolve `channel_address` in `_send_customer_message` and render the same identity in `_read_customer_replies` through the restated codec; refuse an unresolvable address. Add tests that send the bare form. Whether the tool contract should state the form is a separate question, because it changes what arm A is told | `bindings/world.py`, `scripts/tests` | `DRIVER_VERSION`; the manifest stays frozen | yes if the arm A instruction changes; otherwise the §8 defect note suffices |
| 5 | **Scope answers.** `SCOPE_ANSWER_CAME` / `SCOPE_ANSWER_SHORT` are unresolvable against a tomorrow-delivery question. After item 3 they are never consumed in a clean world, so this may be left as a recorded limitation; changing them re-freezes `implementation_sha` (`programs.py` is in `IMPLEMENTATION_MODULES`) with world digests unaffected | `bindings/programs.py` | `implementation_sha` if changed | disclosure if changed |
| 6 | **Baseline transcript and report schema.** Capture arm A's tool calls and arguments in `diagnostics` (captured, never scored) and publish the `RunReport` properties in the Converse schema instead of a bare `object` | `adapters.py`, `bindings/bedrock.py` | `DRIVER_VERSION` | yes for the schema, because it changes what arm A is told |
| 7 | **Pin the v3 digest** beside the two already pinned | `scripts/tests/test_sur1_database_target.py` | none | no |
| 8 | Minor: write the hold audit row only when a row moved; derive `exception_recorded` from the status projection rather than hard-coding it | `bindings/setup.py`, `bindings/world.py` | `DRIVER_VERSION` | no |

## 8. Is another non-`SUR-1` live validation required before spending again?

**Yes, and it is not optional.** Items 1, 2 and 3 change the system under test and the measurement
topology; item 4 changes the one transport arm A depends on. None of that is proved by unit tests.
Before any paid run, `DR01` — which consumes no `SUR-1` outcome — must be driven through the
corrected seam against the live local stack and must show, read out of the systems rather than out
of return values:

- the product's published provider identity equals the contract's, in the `worker` container, and a
  credential resolves there;
- the `worker` comes back after `resume` with `PP_DEMO_SESSION_ENABLED=false` in effect, `cases`
  empty and `commitment_lines` equal to the declared world;
- one `send_customer_message` with the bare address the order system shows is recorded under
  `tg:1002`, counted by `observe()` under that name, fires the rehearsal's armed reply, and is placed
  by `FixtureMap`;
- arm C's wrapper is reached by the process that evaluates revalidation, with a non-empty ablation
  log on a scenario where check 5 runs;
- the scored preflight answers all of the enlarged `REQUIRED_CHECKS` in one report against real
  bindings, and a negative control for each new check refuses.

The same session that makes the changes does not take the scored run.

## 9. What this audit did not do

No `C01`–`C09` attempt was driven. No Bedrock, OpenAI or NVIDIA call was made. No AWS API was
called. No scorer ran. No capture, verdict, result, manifest or arm map was written. No frozen
document, prompt, manifest, scorer, world program, budget or label was edited. No code was
patched. No holdout was opened. The local stack was read — container logs, container environment
key names and non-secret provider and demo keys, the compose file, one `GET /orders` against the
simulator, and read-only `SELECT`s against the local PostgreSQL — and was not changed. The one file
written is this record, which is untracked; the tracked tree is unchanged.

## 10. Third verification, 2026-09-20, at `1c41c3c` — re-derived from primary evidence, nothing changed

Taken fresh by a later session under the same constraints (no attempt driven, no model, no
scorer, no AWS, no code, no frozen artefact, no holdout). Every finding F1–F8 was re-established
from the artefacts, the live containers, the container logs over 12:04–12:14:30Z, the local
database and the source at HEAD, and none was contradicted. What this pass adds:

| Item | Evidence read this pass |
|---|---|
| F1 confirmed across runs | Every baseline `E2` row in run 1 (11 rows) and run 3 (10 rows) is bare: `1002` ×16, `1003` ×2, `1004` ×3; no baseline capture in either run holds an `INBOUND` row. Every B/C `E2` row in run 1 is joined (`tg:1002`), both outbound and inbound. The v3 `E2` row's `provider_event_id` is `sur1-out-…`, i.e. `ChannelLedger.accept` (`world.py:447-461`), not the outbox. |
| F1 placement site | `FixtureMap.by_channel` is keyed on the frozen `fixture.orders.*.channel` (`tg:1002`); `order_for_channel("1002")` raises (`evidence.py:283-290`); `driver.score_attempt` writes `HARNESS_FAILURE` with the recorded note (`driver.py:253-268`). The verdict file for `C01`/baseline carries exactly that note and `decided_by: driver`. |
| Unknown-kind fallback | `receivers.channel_identity` returns the bare address when the kind is not in `CHANNEL_PREFIX_BY_KIND`, and `test_sur1_live_bindings.py:943-945` pins that as intended (the projection then refuses by name). Arm-neutral; not a defect, but it means the outbox path also fails closed to `HARNESS_FAILURE` rather than to a placed row if the product ever stored an unlisted kind. |
| F2 confirmed | Worker log in the window: 27 `worker.start`, 27 `worker.stop`, 27 `worker.demo_case`, 27 `intake.case.opened` by `maya` for case `5ffe7323`; each one precedes the arm's report. Step kinds in the window: `BEGIN_INTERPRETATION` 64, `RESOLVE_OBSERVATION` 64, `ANALYZE_IMPACT` 29, `PLAN_RECOVERY` 29, `RECONCILE_CASE` 2. `provisioning.ensure_demo_case` is gated only on `settings.demo_session_enabled` (`provisioning.py:242`), called from `worker.py:487`; `PP_DEMO_SESSION_ENABLED=true` is in `docker/env/api.env`, which compose loads into both `api` and `worker` (`docker-compose.yml:112,158`). |
| F2 in the database | `fixture_state` = `hollow-oak+sur1-C09` at 12:13:06.8Z. `exception_facts`: one row, `cl-vp-today-raspberries` `EXPECTED → NOT_RECEIVED` by `maya` at 12:13:09.63Z. `exceptions`: one row, the demo case's. `cases`: `5ffe7323` (demo, now `RESOLVED`, updated 12:23:10Z) and `7b6d78c1` (the arm's, `CLARIFYING`). `production_tasks`: `task-ol-a`…`d` `HELD` by `5ffe7323` (post-run escalation, after the last collection). `approval_requests` 0, run-window `outbox_messages` 0, run-window `inbound_replies` 0. |
| F5 confirmed by reading | `_CLAUSE_SEPARATORS` (`interpretation.py:202-216`) contains ` - `, ` but `, ` and `, an em dash and an en dash, and not ` -- `; `came` is in `POSITIVE_MARKERS`; `short` is in `NEGATIVE_MARKERS`; `_resolve_scope_answer` returns `None` when `missing` is empty or matches no option (`interpretation.py:736-757`). `exception_clarifications` for `7b6d78c1`: ordinal 1 answered with the frozen `SCOPE_ANSWER_SHORT`, `resolved_option_code` NULL; ordinal 2 unanswered. |
| F3 confirmed | `docker inspect` of `promisepatch-api-1`, `-worker-1`, `-mcp-1` (all image `1c0653c73dd6…`, created 2026-09-19T23:12Z; `worker` started 12:13:07.85Z by the run's last resume): the environment key set contains no `PP_LLM_PROVIDER`, `PP_BEDROCK_*`, `PP_AWS_*` or `AWS_*` key. `docker/env/api.env` has no such key either (the `.example` files set `PP_LLM_PROVIDER=fake` explicitly; the live file omits it and the default is the same fake, `settings.py:198`). Zero lines matching `semantic` in the `worker`, `api` or `mcp` logs in the window. `BindingConfig` requires `SUR1_AWS_REGION` for the harness's own client and names nothing about the product's provider (`config.py:57-62`). |
| F4 confirmed | `AblationArm.run` enters `ablation()` in the harness process and drives the same `PromisePatchArm` (`adapters.py:238-254`); `ablation()` does `setattr(promisepatch.domain.revalidation, "revalidate", …)` locally (`ablation.py:228-245`); the product reaches the worker over MCP and HTTP only (`bindings/promisepatch.py`). `diagnostics.ablation == []` on 9/9 v3 and 8/8 run-1 ablation captures. `sur1-execution-harness.md:38` states no deployed process can reach the wrapper. |
| F6 confirmed | `C04`/baseline: 8 model calls, 7 tool calls, `E4` `{"exception_recorded": false, "promises": []}`, `diagnostics {}`; `C01`/baseline `E4` identical in shape. `tool_configuration` publishes `report` as `{"type": "object"}` with no properties (`bindings/bedrock.py:126-159`); `_report_row` reads `promises` and finds none (`world.py:565-590`). The mechanism stays open for want of a transcript. |
| Parity of the two Converse requests | Harness: `system` from the frozen prompt, tool surface of eleven frozen actions, no `toolChoice`, `retries max_attempts 1`, temperature from `ModelIdentity` (`bindings/bedrock.py:240-262, 333-344`). Product: `system` from `spec.system_instruction`, exactly one tool with `toolChoice` forced, `retries max_attempts settings.bedrock_max_attempts`, `TEMPERATURE 0.0` literal, one corrective retry (`integrations/bedrock.py:204-231, 115-132`). Same model id and temperature *when configured for Bedrock*; different system prompts, tool access and retry policy by design of the two roles. Only the model id, API and temperature are what the contract freezes; those would match. The product was not configured for Bedrock (F3). |
| Preservation | Recomputed with the pinned algorithm: run 1 `d599d644…` (57), run 2 `e2a46c35…` (57), run 3 `403622ec…` (57) — all three unchanged from §6. `git status` is clean under `docs/benchmarks`, `scripts/sur1`, `scripts/score_safe_useful_recovery.py` and `scripts/tests`. `frozen.assert_frozen()` → manifest `5718340f…e70e84c`, prompt `772ba460…9ce47cb1`, scorer `1.0.0`; `predeclaration.identity_sha()` `c53d267a…1e1927`; `declaration.differences()` `()`; `DRIVER_VERSION` `1.2.0`. The v3 digest is still pinned nowhere. On disk `sur1-world-programs.v1.json` carries CRLF bytes (its raw and LF-normalised SHA-256 differ) while the manifest and prompt do not; `git diff HEAD` is empty for it and `differences()` is empty, so this is a checkout line-ending artefact and not a content change. |

Nothing in §7 or §8 is changed by this pass. The plan stands in the order given: product model parity (blocker), arm C reach (blocker), clean world after `resume`, channel identity at the harness transport, scope answers, baseline transcript and report schema, pin the v3 digest, the two minor items. `DR01` against the corrected seam before any spend, by a session other than the one that takes the run.
