# `SUR-1` parity correction: five proven defects closed, one left open and refused

**No `SUR-1` run was taken, no model was called, no scorer was run against a new bundle, no AWS
API was reached, no capture or verdict was written, no holdout was opened and no published run
was altered.** This record is the correction to the defects
[`sur1-v3-forensic-audit.md`](sur1-v3-forensic-audit.md) proved in
`20260920T1215Z-scored-v3`, which stays exactly as it came out and is published **invalid**.

| | |
|---|---|
| Written at | `4f676cb` on `main`, 2026-09-20 |
| Corrects | `20260920T1215Z-scored-v3`, digest `403622ec…`, driven under `DRIVER_VERSION` `1.2.0` |
| `DRIVER_VERSION` | `1.2.0` → **`1.3.0`** |
| `implementation_sha` | **unmoved.** No file in `IMPLEMENTATION_MODULES` was touched |
| `PREDECLARATION_SHA` | **unmoved.** No reading rule changed |
| Manifest / prompt / scorer / world programs / budgets / retry policy | **unmoved** |
| `REQUIRED_CHECKS` | 18 → **25** |
| Runs taken under `1.3.0` | none |

## 0. What was corrected, and what was not

| # | Audit finding | Status |
|---|---|---|
| F1 | the baseline's messages were recorded on a bare address nothing could place | **closed** (§1) |
| F2 | the worker's own start-up contaminated every installed world | **refused** (§2) |
| F3 | the product answered semantic jobs with the deterministic fake | **refused** (§3) |
| F4 | arm C's ablation reached no evaluator, so arm C was arm B | **open, and now refuses the run** (§4) |
| F6 | the report tool published no fields for the one arm that had to fill them | **closed** (§5) |
| F5 | the frozen scope answers cannot resolve a tomorrow-delivery question | **left as a recorded limitation** (§6) |
| — | the three published runs are pinned and unedited | **held** (§7) |

**One item is not done and cannot be done here.** Arm C's ablation cannot reach the process that
decides revalidation on any topology that exists today, and the mechanism that would let it is a
decision this session is not entitled to take. §4 is the blocker in full.

## 1. Channel parity — closed

**The defect.** `get_orders` is the order system's own snapshot and shows a split
`{"kind": "telegram", "address": "1002"}`; `get_promise_graph` shows the engine's joined
`tg:1002`. The frozen fixture, the arming, the product's outbox and `FixtureMap` know only the
joined form. `LiveScenarioWorld._send_customer_message` recorded whichever string it was handed —
it was the one place on the whole path that canonicalised nothing — so the ask was counted under a
name no armed event watched, no stipulated reply ever fired, and the `E2` row was refused at
placement. Every baseline outbound row of two scored runs is bare (`1002` ×16, `1003` ×2, `1004`
×3) and no baseline capture in either run holds an `INBOUND` row.

**The correction.** `receivers.resolve_channel_address(address, known=…)` resolves an address
against the channels the world actually holds, through the codec `receivers` already restates for
outbox rows. Three spellings resolve to one identity — `tg:1002`, `1002`, `telegram:1002` — and
**anything else fails closed**: an address naming no channel here, and an address whose bare form
two known channels of different kinds carry, both refuse. `world.channel_universe()` reads the
channel set out of the frozen fixture, which is the same map `FixtureMap` places against, so the
transport cannot accept an address the placement then refuses.

The refusal is a `WorldActionError`, which is what `amend_order` already raises for an external id
outside the case universe. A tool-result error the model could correct would be a different
error surface for arm A and therefore a predeclaration question; it is not taken here.

**Proof, with no model and no run** (`scripts/tests/test_sur1_live_bindings.py`): `1002` is
recorded as `tg:1002`; each of the three spellings produces one identity; an ask sent with the
bare address fires `C01`'s stipulated reply; that reply reads back on the same identity; the row
is placed on `ord-b` by `FixtureMap`; five unresolvable addresses refuse and leave the ledger
empty.

**Preflight.** `channel_transport` requires every spelling of every one of the world's channels to
resolve, to be placeable, and to be counted by `observe()` under the arming's own name, and
requires an address naming nobody to refuse. Read-only.

## 2. Clean world — refused, and re-verified after the worker returns

**The defect.** `provisioning.ensure_demo_case` runs at every worker start, gated only on
`PP_DEMO_SESSION_ENABLED`. The per-attempt lifecycle stops and starts the worker around every
install, so on all 27 attempts it opened a case inside the freshly installed world and attested
today's raspberry line `NOT_RECEIVED` *before the arm reported anything*. `InstallationLifecycle`
verified before `resume` and never again.

**The correction, in two independent places.**

- **The lifecycle re-reads the world after `resume`.** `fingerprint()` takes counts of the eight
  tables only a case's own work writes into, plus the ordered states of `commitment_lines` and
  `production_tasks` and the `fixture_state` row. `require_untouched` compares it with the
  fingerprint the install left and refuses on any difference. It is a comparison rather than a
  rule about what a world may contain, so a world program that legitimately writes one of those
  tables is compared against itself; what refuses is a row appearing while no arm is acting.
- **The preflight refuses a stack configured to do it.** `demo_provisioning` reads
  `demo_session_enabled` out of the worker process itself and requires it false.

**The product needs no change and got none.** Its provisioning behaves as documented. What is
refused is a scored stack configured for a demo.

**Proof** (`scripts/tests/test_sur1_world_lifecycle.py`): a stand-in worker whose own `resume`
writes into the world is refused with *nobody declared*, the worker is still handed back, an
untouched world is driven, and `cases` is read exactly twice per install.

## 3. Model parity — the product now says what it will call, and the preflight requires it

**The defect.** The contract's `PROMISEPATCH.constraints` require *its semantic boundary calls the
same model, with the same parameters, as the baseline arm*, applying to all three arms. The
containers that served all three runs carried no `PP_LLM_PROVIDER`, no `PP_BEDROCK_*` and no AWS
variable, so the product resolved `LlmProvider.FAKE` while arm A called Nova. `run.json` recorded
`model_provider_configured: false` — read in the **harness** process, about the wrong process,
gated on by nothing.

**The correction.**

- **The product publishes a read-only runtime identity.** `pp runtime-identity` prints, as JSON,
  what *this* process is configured to do: the provider, and for Bedrock the model id, the API,
  the Region, the temperature, the retry ceiling, the timeout and whether a credential
  **resolves** — a boolean, never a value. It builds no provider and calls nothing. An operator
  could read which migration a deployment expects off `/readyz` and, until now, which model it
  would call off nothing at all.
- **The harness asks the worker container itself**, through
  `ComposeWorkerControl.runtime_identity()` (`docker compose exec -T worker pp runtime-identity`).
- **`product_model_identity` compares it with the frozen block** and requires provider, model id,
  API and temperature to match, a Region to be named, and a credential to resolve there.
- **`run.json` records it.** `RunManifest.product_runtime` is what the product said, and the two
  harness-process keys in `environment` are renamed `harness_*` so nobody reads one as the other
  again.

**Proof, live, from the running worker container, with no inference:**

```
$ docker compose exec -T worker pp runtime-identity
{"demo_session_enabled": true, "env": "local", "explanation_verbalisation": false,
 "llm_provider": "fake", "service": "promisepatch"}
```

That is F2 and F3 read out of the process that would have done the work, on the stack as it
stands. Configured the way a scored run needs, the same image publishes:

```
$ docker compose run --rm --no-deps -e PP_LLM_PROVIDER=bedrock -e PP_DEMO_SESSION_ENABLED=false \
    -e PP_BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0 -e PP_AWS_REGION=us-east-1 \
    worker pp runtime-identity
{"api": "bedrock-runtime Converse", "credential_resolves": false, "demo_session_enabled": false,
 "env": "local", "explanation_verbalisation": false, "llm_provider": "bedrock",
 "max_attempts": 3, "model_id": "us.amazon.nova-2-lite-v1:0", "region": "us-east-1",
 "service": "promisepatch", "temperature": 0.0, "timeout_seconds": 10.0}
```

Against the frozen contract those answers score: today's stack **refuses** on the provider, the
model and the temperature; the configured container **refuses** on `credential_resolves: false`,
because nothing mounts an AWS credential into it; with a credential resolving there it **passes**,
naming the model, the temperature and the Region. No Bedrock call was made at any point.

**What is still required of an operator before a scored run**, and what the preflight will refuse
until it is done: set the four variables in `docker/env/api.env`, give the worker container a path
by which the AWS credential chain resolves, and recreate `api` and `worker`.

## 4. Real ablation — BLOCKER

**The defect.** Arm C is defined as PromisePatch with revalidation check 5 dropped and nothing
else, removed by rebinding `promisepatch.domain.revalidation.revalidate` at the benchmark
boundary. The rebinding happens in the harness process; the evaluator that decides runs in the
`worker` container. `diagnostics.ablation` is `[]` on all nine third-run ablation captures and all
eight of the first run's. **Arm C is arm B by construction on this topology**, which makes the
ablated arm unmeasurable rather than merely unmeasured.

**What this session did.** `ablation_reach` asks the worker control which process decides
revalidation and refuses the run unless it is the one the wrapper is installed in.
`ComposeWorkerControl.evaluates_in_process()` returns `False`, so **the check refuses every
topology that exists today** — proved live above, and pinned by
`test_the_containerised_worker_is_exactly_what_ablation_reach_refuses`. A fourth scored run cannot
be bought while arm C would measure nothing.

**Why the mechanism was not built here.**

The frozen contract's `ABLATION.what_is_not_touched` includes *Every file under `packages/` and
`apps/`. The wrapper lives in the benchmark harness and no deployed process can reach it.* That
sentence rules out the obvious repair. A governed ablation seam inside the product would be a file
under `apps/`, would be reachable by a deployed process, and would be benchmark-only behaviour in
a system whose own constraints forbid it. It is not a candidate.

The one mechanism that keeps every clause of that sentence literally true is to **run the
product's own durable worker inside the harness process** for arms B and C, with the container
worker down for the whole run. The wrapper would then be installed in the process that decides;
the wrapper would still live in the benchmark harness; and no deployed process could reach it. It
is feasible — `promisepatch.worker.built()` is a clean async context manager, the product imports
cleanly into the harness venv, and `WorkerControl` is already the seam a different topology would
plug into.

It is also a change to **what is measured**, for both arms and not only the ablated one:

- Arms B and C would be driven at a worker running somewhere else than the one every prior run
  used, and arm A would be unaffected — an arm-correlated topology change, which is precisely the
  class of defect this correction exists to remove. Both arms must move together or neither may.
- The audit names it as an ADR-level decision (`sur1-v3-forensic-audit.md` §7, item 2), and
  `CLAUDE.md` requires an ADR to be amended before frozen architecture is redesigned. Writing
  `ADR-0020` to authorise a change to what a frozen benchmark measures is the project owner's
  decision, not this session's.
- `sur1-phase3-closeout.md` §8 requires a disclosure beside the predeclaration stating what moved,
  which arms it affects and in which direction, **before** any run is taken under it. That
  disclosure cannot honestly be written until the decision it discloses has been taken.

So the correct state to leave this in is: the defect named, the run refused, the mechanism
analysed, and the decision open. **The remaining work is one ADR and the in-process worker
binding it authorises**, in that order, by a session the owner directs.

## 5. Report contract — closed

**The defect.** `report_outcome` was published to Converse as `{"report": {"type": "object"}}` with
no properties, and the frozen prompt names the four outcomes without naming a single field. So
nothing anywhere told arm A that the array is called `promises`, that an entry names an `order`,
or that there is a `work_state` at all. `E4` came back with no promises on 18 of 18 baseline
attempts across two runs, and the captures held no transcript with which to show why.

**The correction.**

- **The schema is derived from the frozen manifest**, never restated:
  `adapters.run_report_schema(contract)` reads `run_report_schema.fields`, turns `one of A, B, C`
  into an enumeration, `string or null` into a nullable, `free text, at most 200 characters` into a
  bounded string, and the `promises[].*` entries into the array's `items`. Every property carries
  the frozen wording verbatim as its description. A shape it cannot read, and an array whose
  entries nothing describes, are refused rather than defaulted.
- **It publishes no field the other arms cannot fill.** `acknowledged_stops` is read by the harness
  and is scored, and is *not* in the frozen field list; the predeclaration records it empty for
  arms B and C. Publishing it to arm A alone would hand one arm a field its comparators
  structurally cannot produce, so it is not published.
- **`tool_configuration` carries a structured argument shape through** and refuses one naming no
  type.
- **Arm A's tool calls are captured.** `BaselineArm` records every call and its arguments into the
  attempt's `diagnostics`, bounded at 400 characters, 32 entries and six levels. Diagnostics are
  written into the capture and are structurally unreachable from an evidence bundle — `blind_bundle`
  has no parameter for them — which is what lets an arm-identifying record exist at all.

**Proof, synthetic and end to end, with no model**
(`scripts/tests/test_sur1_report_contract.py`): a report is built *by walking the published schema
and nothing else*, handed to the world's own `report_outcome`, read by `_report_row`, projected
through `blind_bundle`, and put through the scorer's own `_report_is_valid`, which accepts it. The
empty report both runs actually produced is still `INVALID` — the schema does not repair a missing
answer. The old bare-object shape is asserted in the same test as *the shape two scored runs were
taken with*.

**Preflight.** `report_projection` takes the same path dry and requires the result to satisfy the
frozen `invalid_report_rule`, reading the rule out of the frozen document rather than out of the
scorer.

## 6. Scope answers — recorded, not changed

`SCOPE_ANSWER_CAME` and `SCOPE_ANSWER_SHORT` cannot resolve the clarification a *contaminated*
world asks, because ` -- ` is not a clause separator and `short` makes `{raspberries,
strawberries}` match neither option. In a clean world that question is never asked, so this is
reached only through F2. Changing them would move `implementation_sha` (`programs.py` is in
`IMPLEMENTATION_MODULES`) with every world digest holding still, which is the exact failure that
hash exists to catch. **They are left as they are and recorded as a limitation.** If a clean
rehearsal shows the question is still asked, that is a re-freeze with its own disclosure and its
own defect note, not a tidy-up here.

## 7. Immutability

All three published scored runs recompute to their published digests, with the algorithm
`test_sur1_database_target` pins (relative path, NUL, bytes with CRLF normalised to LF, NUL,
sorted):

| Run | Files | Digest | |
|---|---|---|---|
| `20260919T2020Z-scored` | 57 | `d599d644c6869fe527a32cfe240fe9a20433ed4a07679b02fbb597fecdc746ed` | unchanged |
| `20260920T1100Z-scored-corrected` | 57 | `e2a46c35b53902c817b9602999bb84f3df82cd3c7b425cb813551e7817364bca` | unchanged |
| `20260920T1215Z-scored-v3` | 57 | `403622ecd45a34723517556570d1b154c3f11f0e1fcaf9201856eeff6b9e18ca` | **pinned here for the first time** |

The third is pinned in two independent places — `scripts/tests/test_sur1_database_target.py` and
`scripts/sur1/preflight.PUBLISHED_RUNS`, held together by a test — and the preflight now asks the
question before another run is bought. The session that proves a run meaningless is the session
most likely to tidy it away; a benchmark that deletes its failures publishes a number about a
history that no longer exists.

## 8. The preflight, 18 → 25

| # | Check | Refuses |
|---|---|---|
| 19 | `historical_runs` | a published scored run has been edited |
| 20 | `channel_transport` | a spelling the world shows that does not resolve, place and count as one identity |
| 21 | `report_projection` | a frozen report schema that does not yield a report the projection accepts |
| 22 | `demo_provisioning` | a worker that opens a demo case inside the world an arm is about to act on |
| 23 | `world_integrity` | a lifecycle that does not re-read the world after the worker returns |
| 24 | `product_model_identity` | a product not configured for the model the contract froze, or with no credential where the work happens |
| 25 | `ablation_reach` | an ablation that reaches no evaluator — **every topology that exists today** |

Each new check has a negative control in `scripts/tests/test_sur1_preflight.py` that proves it
bites. Three of the seven refuse against the live local stack right now, for the three defects
they were written for; the other four pass.

## 9. What was validated

`pytest scripts/tests` (1196 collected: 1195 passed, 1 skipped — a state-dependent challenger
guard, unrelated), `pytest apps/backend/tests/test_cli.py` (57 passed), `ruff check`,
`ruff format --check`, `mypy scripts` (94 files), `mypy packages/promise-graph
packages/order-contract apps/backend` (280 files). The frozen-identity checks pass inside the suite:
`assert_frozen()`, `identity_sha()`, `declaration.differences()`, the nine world digests and all
three run digests. GitHub CI is the broad regression authority and has not run on this work.

Docker was used only to build the backend image and to read `pp runtime-identity` out of the
`worker` container, once as it is configured and once under overrides. No world was installed, no
arm was driven, no inference happened and the database was not written to.

## 10. What this correction did not do

No `SUR-1` attempt was driven. No Bedrock, OpenAI or NVIDIA call was made. No AWS API was called.
No scorer ran against a new bundle. No capture, verdict, result, arm map or scored artefact was
written. No frozen document was edited — not the manifest, the prompt, the scorer, a world
program, a budget, a label or a scope answer. No published run was altered. No holdout was opened.
No scenario semantics changed and nothing was tuned against a result. `DR01` was not driven, and
the audit's §8 live validation — which must show the four runtime facts against a corrected seam —
is still owed before any spend, by a session other than the one that takes the run.
