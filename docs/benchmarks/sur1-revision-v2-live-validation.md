# `SUR-1` execution revision `v2`, validated against the live stack

[`sur1-execution-revision.v2.md`](sur1-execution-revision.v2.md) §7 said plainly what its
thirty-four proofs did **not** establish: *nothing asserts that the corrected lifecycle survives
a live `docker compose` cycle, or that a governed world write commits against a live PostgreSQL.*
§9.3 named the remedy — *a smoke pass over one scenario's install would retire the risk earlier,
and would be a development run, not a scored one.*

This is that pass, taken on 2026-09-20. It found one defect in the corrected lifecycle, which is
recorded and fixed here.

**`20260919T2020Z-scored` is untouched.** No arm was driven, no model called, no scorer run, no
AWS resource contacted, no holdout opened and nothing deployed or pushed. `C01`–`C09` were not
executed and no ground truth was read.

| | |
|---|---|
| Kind | development validation — **not a run, not a benchmark** |
| Scenario | `DRV2-01`, invented here, in no manifest, with no ground truth and no arm |
| `DRIVER_VERSION` | `1.1.0` → **`1.1.1`** |
| `implementation_sha` | **unchanged**, `cb1686bf…` |
| Frozen benchmark elements | **all unchanged** — see §6 |
| Defects found | 1, reproduced and fixed — see §4 |

## 1. The images the first run used were still the images running

Before anything was rebuilt, the containers were the exact ones
[`sur1-first-scored-run-defect.md`](../sur1-first-scored-run-defect.md) names:

| Image | ID | Built |
|---|---|---|
| `promisepatch-backend:local` | `4592d864745a` | 2026-09-18 19:20 |
| `promisepatch-order-simulator:local` | `e78c86e6000d` | 2026-09-15 14:30 |

Asked, before the rebuild, they answered exactly as recorded:

```
GET /admin/capabilities  ->  404 {"detail":"Not Found"}
GET /admin/events  entry keys:
  ['attempts','delivery_state','event_id','external_order_id','occurred_at','source','type','version']
  'event' absent, 'previous_version' absent
```

That is the defect record's own printout, reproduced live rather than quoted.

**One disclosed limitation confirmed rather than discovered.** The stale backend answered
`/readyz` with `expected_revision: 0009_human_plan_approval`, `at_head: true` — the same value
this source tree carries. So `backend_build` **passes against the stale backend image**, exactly
as `v2` §3.1 states: *an image stale only in code that no migration accompanied reports the same
revision and passes.* The check is not weakened by this; the limitation is real, was declared in
advance, and is now observed rather than assumed.

## 2. Rebuilt, and what is running now

Both scored-path images were rebuilt from `HEAD` and every service recreated onto them.

| Image | ID | Built |
|---|---|---|
| `promisepatch-backend:local` | `1c0653c73dd6` | 2026-09-20 01:12 |
| `promisepatch-order-simulator:local` | `2636d2ceb79d` | 2026-09-20 01:11 |

| Container | Image | State |
|---|---|---|
| `promisepatch-api-1` | `sha256:1c0653c73dd6` | running / **healthy** |
| `promisepatch-worker-1` | `sha256:1c0653c73dd6` | running / **healthy** |
| `promisepatch-mcp-1` | `sha256:1c0653c73dd6` | running / healthy |
| `promisepatch-order-simulator-1` | `sha256:2636d2ceb79d` | running / healthy |

The worker reports a health status at all, which is the signal `up --wait` blocks on and which
this revision added. On the previous image that column read *no healthcheck*.

## 3. The three new checks, asked of the running processes

Asked through `scripts.sur1.preflight`'s own functions against real bindings. The scored
preflight was **not** run — that is the corrected run's, not this session's.

| Check | Answer |
|---|---|
| `order_projection` | PASS — *E1 publishes the committed body; checked against a published entry* |
| `backend_build` | PASS — *API and source both at migration `0009_human_plan_approval`; the governed fixture load takes a stated world* |
| `worker_lifecycle` | PASS — *worker is running and can be stopped and started* |

And each refuses the shape it exists to refuse: a reader answering as a `404` build fails
`order_projection`; an `UncontrolledWorker` and a world with no control at all both fail
`worker_lifecycle`.

**The `E1` key survives a live round trip.** The *same stored event* the stale container
published with no command came back through the rebuilt projection carrying
`idempotency_key='pp:amend:1d9df4b1…:9750f063…:1'`, and the strict capture reader accepted it.
Driven through the stale entry shape, the tolerant reader produced `''` and the strict reader
refused it — *an E1 row for 'EXT-A' is missing idempotency_key*, the first run's own sentence.
The defect was a projection, never the data.

## 4. The defect this pass found

**Handing the worker back destroyed the world that had just been installed.**

`ComposeWorkerControl.resume` ran `docker compose up -d --wait --no-recreate worker`. The worker
declares `depends_on: seed: service_completed_successfully`, and compose satisfies that by
**re-running `seed`** — whose command is `pp reset-demo-state`. So the lifecycle's four steps
ran in this order: quiesce, install, verify (passed), resume — *and the resume reset the
database.*

`verify` could not catch it, because `verify` runs before `resume`. Nothing in the thirty-four
proofs could catch it either: they drive a `ScriptedWorker` stand-in and never invoke `docker`.
This is precisely the gap §7 declared.

**Impact had it reached a corrected run.** Every attempt would have been driven at the canonical
demo fixture instead of at its scenario's world — silently, with `fixture_state` verified
moments earlier and the applied-step list naming the right load. Arm-blind and total.

**Reproduced in isolation**, not inferred. A sentinel was written into `fixture_state` and one
quiesce/resume pair run with nothing else touching the stack:

```
fixture_state marked  : sentinel-do-not-overwrite
seed StartedAt before : 2026-09-19T23:17:15Z
seed StartedAt after  : 2026-09-19T23:18:08Z      seed RE-RAN: YES
fixture_state now     : hollow-oak
```

**The fix is one flag**, `--no-deps`, and it weakens nothing. The dependency is not being
bootstrapped: the stack is up and the service was stopped seconds earlier by `quiesce`. `--wait`
still blocks on the worker's own healthcheck, that healthcheck is a real query against the
database, and `resume` still reads the service state back afterwards. The same experiment with
the fix in place:

```
fixture_state marked  : sentinel-survives-resume
seed StartedAt before : 2026-09-19T23:18:08Z
seed StartedAt after  : 2026-09-19T23:18:08Z      seed RE-RAN: no
fixture_state now     : sentinel-survives-resume
```

**Regression proofs**, in `scripts/tests/test_sur1_world_lifecycle.py`: one asserts `resume`
issues `--no-deps` while still issuing `--wait`, and fails against the unfixed code with the
argv printed; the other reads from `docker-compose.yml` that the dependency a resume must not
re-run is the one whose command is `pp reset-demo-state`, so the reason stays checkable rather
than remembered.

## 5. `DRV2-01`, the development scenario

Invented for this pass. It is in no manifest, has no ground truth, no `the_point`, no arm, no
scorer and no capture; it is driven from a session script and never from `scripts.sur1.run`. The
frozen registry and the frozen declaration are both untouched — `realise` was given this one
program's digest through its own `published_programs` seam, which is the parameter that exists
for exactly this. Its world digest is `704fd7506c602034…` and belongs to nothing frozen.

After the fix, 19 of 19 checks pass:

| What | Observed |
|---|---|
| the worker is `RUNNING` before the lifecycle touches it | yes |
| the worker is `STOPPED` **at the moment the install writes** | observed from inside the install itself |
| the worker is `RUNNING` again afterwards | yes, on its healthcheck |
| `fixture_state` names the installed world | `hollow-oak+sur1-DRV2-01` |
| the install's own receipt | `['order-system:reset', 'load:hollow-oak+sur1-DRV2-01']` |
| governed hold on a production task | `HELD` in the database |
| governed release | `SCHEDULED` again |
| one armed reply and the movement armed on it | `['DRV2-01:reply:1', 'DRV2-01:stock:1']` |
| the governed inventory-ledger write | `inventory_ledger` 17 → 18 |
| every world write carries its own audit event | `BENCHMARK_WORLD_TASK_HELD`, `…TASK_RELEASED`, `…STOCK_MOVEMENT` |
| what those events claim | actor `sur1 world facility`, authority `NONE`, on every row |
| a governed order amendment | order system answered `200`, `EXT-F` v1 → v2 |
| it reaches `E1` with a key | `idempotency_key` non-empty and equal to the key the amendment was made with |
| the strict capture reader | accepts the committed row |

**Both governed writes commit against live PostgreSQL through the product's own
`UnitOfWork.governed` block.** That is the second thing §7 said was unproven, and it is the
thing that cost three attempts in the first run. It is now proven by execution.

### 5.1 Isolation, read from state rather than waited for

- **The worker is stopped while the destructive install runs.** Not inferred from the call
  order: the install callable itself reads `ComposeWorkerControl.state()` and asserts `STOPPED`
  before `realise` writes anything.
- **No `TRUNCATE` deadlock occurred** on any of the three installs this session performed.
- **A retry begins clean.** `inventory_ledger` read `17 → 18` on every attempt, so each install
  put the ledger back to the same seventeen rows rather than accumulating.
- **No sleeps, no polling, no retry-until-success.** Every step ends in a read of the state it
  was meant to produce, and nothing here was attempted twice to make it pass.
- **`audit_events` accumulating across installs is not residue.** `reset_demo_state` never
  empties the ledgers of record — `audit_events` and `domain_events` are outside it by design —
  so the `BENCHMARK_WORLD_*` trail is durable history. Nothing the scorer reads comes from it.

## 6. What did not move

Recomputed from the bytes on disk with the fix in place:

| Frozen element | Value | |
|---|---|---|
| manifest `safe-useful-recovery.v1.json` | `5718340fbd19aa8ba1aedc2327c07a934e22b773271e996f13f0e8d87e70e84c` | unchanged |
| baseline prompt | `772ba46025620a1aea4742fac3971c5906ec3252036d07725434e0a89ce47cb1` | unchanged |
| scorer `SCORER_VERSION` | `1.0.0` | unchanged |
| `PREDECLARATION_SHA` | `c53d267a0874d2e91456fdfacc23c86ebfc411f938cbe060ce958cb41d1e1927` | unchanged |
| `program_set_sha` | `88db566c13ef7a9865141583e5d918d43ff1b612b3311393c12af627ab1de649` | unchanged |
| `implementation_sha` | `cb1686bf011d7cf66ad139f6cbbb6b33b7df986d89ef64fc58a02544703493df` | **unchanged** |
| `C01`–`C09` world digests | all nine present and agreeing | unchanged |
| `declaration.differences()` | `()` | empty |

`implementation_sha` does not move because `lifecycle.py` is deliberately outside
`IMPLEMENTATION_MODULES` — it decides *when* an install is safe, not what a program is. Driving
is `DRIVER_VERSION`'s to cover, and that is what was bumped. Ground truth, the arm definitions,
the eleven frozen actions, the attempt budget, `RETRYABLE` and the blinding rules are untouched.
Both evaluation holdouts remain sealed.

**`20260919T2020Z-scored` is byte-identical to what was published.** Its tree is
`080fceda57a56cb36b1c32088eb74822c2fb7ebd`, the value `v2` names; all 57 files are present;
`git status` reports no modification under it; and it remains the only directory in
`docs/benchmarks/runs/`, so no replacement result exists.

## 7. What this pass does not do

- **It takes no run and authorises none.** No arm, no model, no scorer, no capture, no verdict.
  `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` was spent on the first run and nothing here
  spends anything.
- **It does not reinterpret the first run.** No verdict re-read, no outcome recomputed.
- **It edits no frozen document**, no ground truth, no prompt, no scorer rule and no manifest.
- **It says nothing about `C01`–`C09`.** None was driven. That `DRV2-01` installs and settles
  cleanly is evidence about the machinery and about nothing any scenario measures.

## 8. What still stands between this and a corrected run

`v2` §9 listed five. This pass clears the two that were technical; the rest are unchanged and
none is this session's to clear.

1. **A fresh paid-inference authorisation.** Still required. Nothing here re-authorises anything.
2. ~~A rebuilt local stack.~~ **Cleared** — both images rebuilt and serving, §2.
3. ~~The lifecycle and the governed write against the live stack.~~ **Cleared, and it found a
   defect**, §4 and §5.
4. **All seventeen checks passing in one report against real bindings.** Three were asked
   individually here and passed. `model_identity` and the AWS half of `configuration` have still
   never been asked of a real account, and the full scored preflight has not been run.
5. **A different session.** The session that changes the machinery does not take the run — and
   this session changed the machinery, so it is now disqualified twice over.

The `C02` disclosure in [`sur1-consent-ingress.md`](../sur1-consent-ingress.md) and
`sur1-phase3-closeout.md` §2 carries forward unchanged. Both evaluation holdouts remain sealed.
