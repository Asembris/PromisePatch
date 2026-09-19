# `SUR-1` execution revision `v2`: the measurement system, corrected beside the first run

**`20260919T2020Z-scored` is not superseded, replaced, reinterpreted or re-run by anything in
this document.** It stands published, immutable and **inconclusive**, exactly as it came out. Any
run taken under this revision is a *corrected execution beside* it, and must be published as such.

This is the disclosure `sur1-phase3-closeout.md` §8 requires before a change beneath
`scripts/sur1/` may be made: a named defect, a statement of what moved and in which direction, and
the re-frozen identity that covers the changed bytes. **No run was taken to produce it, no model
was called, no AWS resource was touched, nothing was deployed and no holdout was opened.**

| | |
|---|---|
| Revision | `v2` |
| Supersedes | **nothing** |
| Corrects | the measurement system only |
| Prior run preserved | `20260919T2020Z-scored`, INCONCLUSIVE, 24 `HARNESS_FAILURE` / 1 `INVALID` / 2 `SAFE_AND_COMPLETE` |
| Prior run tree | `080fceda57a56cb36b1c32088eb74822c2fb7ebd`, byte-identical at this revision |
| `DRIVER_VERSION` | `1.0.0` → **`1.1.0`** |
| `implementation_sha` | `34b2daae…` → **`cb1686bf011d7cf66ad139f6cbbb6b33b7df986d89ef64fc58a02544703493df`** |
| Frozen benchmark elements | **all unchanged** — see §4 |
| Scored preflight | 14 checks → **17** |

## 1. Why the first run was inconclusive

Eight of nine scenarios failed on every arm for reasons that have nothing to do with what any arm
decided. Two scored verdicts survive out of twenty-seven cells, every safety counter is a zero
that was never measured, and both primary-metric denominators are `0` on all three arms. No thesis
was tested and no falsification was attempted. The full record is
[`sur1-first-scored-run-defect.md`](../sur1-first-scored-run-defect.md); nothing in it is revised
here.

## 2. The defects, and what each one actually was

The first-run record was written without reproducing two of the three faults. One of its
attributions is **wrong**, and correcting it is part of this revision.

### 2.1 The order system published no committed event body — 20 attempts — *as recorded*

`promisepatch-order-simulator:local` was four days older than `f02e4ad`, so `GET /admin/events`
published no `event` key and therefore no `command.idempotency_key`. `receivers._event` is
deliberately tolerant and wrote `idempotency_key=""`; `replay._text` is deliberately strict and
refused it; the driver classified the disagreement `HARNESS_FAILURE`. **Both readers are correct
as they are and neither was relaxed.** What was missing was a question asked early enough for the
disagreement never to arise.

### 2.2 The world's two writes were ungoverned — 3 attempts — **not** a stale backend image

The record attributed this to a `promisepatch-backend:local` image predating `5973602`. That
diagnosis does not hold, and the failure is reproducible on any image:

- `setup.KitchenWriter.hold`/`release` issued a bare `UPDATE` on `production_tasks`.
- `worldsink.LedgerWriter.post` issued a bare `INSERT` into `inventory_ledger`.
- Both tables are in `promisepatch.db.boundary.GOVERNED_TABLES`. The database's own
  `assert_governed_write` trigger refuses any statement against them that is not accompanied, in
  the same transaction, by an `audit_events` row that transaction wrote.

A bare statement on a bare `asyncpg` connection can never satisfy that, so **both writes would
have failed against every build of the backend, including the current one.** They were never
noticed because neither had ever been executed against the live database: the realisation record
leaves every declared event `armed_and_unfired`, and `DR01` fired no stock movement and drove no
baseline `hold_task`. The first scored run was the first execution of both.

The correction is to write *governed*, not to make the database lenient. Nothing was weakened, no
privilege was granted and no trigger was touched. `scripts/sur1/bindings/governed.py` opens one
transaction, asks the product's own `UnitOfWork.governed` block to authorise it, and performs the
statement inside it. Every such row carries an audit event whose type begins `BENCHMARK_WORLD_`
and whose actor is `sur1 world facility`, with authority `NONE` — so a reader of the ledger of
record can never mistake the measurement harness for a decision the product made.

**Direction of the correction.** Arm A (`BASELINE`) and arm C (`ABLATION`) reach `hold_task` and
`release_task` through this facility; arms B and C additionally depend on the stipulated stock
movement firing on `C06`. Under `v1` those calls *failed*, so the affected cells produced no
verdict at all rather than a wrong one — which is why the effect is 3 `HARNESS_FAILURE` cells and
not a bias in any surviving number. Under `v2` they succeed, so a later run measures what those
scenarios were written to measure. This changes no scoring rule.

### 2.3 The fixture `TRUNCATE` deadlocked against the live worker — 1 attempt — *as recorded*

`reset_demo_state` empties forty-two tables in one transaction, taking `ACCESS EXCLUSIVE` on each
in statement order; the `worker` container's cycle holds `ACCESS SHARE` on several of them in an
order of its own. The captured detail is unambiguous:

```
Process 131199 waits for AccessExclusiveLock on relation 16412; blocked by process 93662.
Process 93662  waits for AccessShareLock     on relation 16989; blocked by process 131199.
```

This is two processes that must not be writing at the same time. It is not a flake and it was not
made less likely — it was removed.

## 3. What was changed

| Change | Where | Identity it moves |
|---|---|---|
| the admin projection is declared and served from one place | `apps/order-simulator/.../capabilities.py`, `app.py` | none — the order system carries no `SUR-1` hash |
| the world's two writes go through the product's governed write | `scripts/sur1/bindings/governed.py`, `setup.py`, `worldsink.py` | `implementation_sha` |
| the worker is quiesced around an install and the world is read back | `scripts/sur1/bindings/lifecycle.py`, `world.py`, `run.py` | `DRIVER_VERSION` |
| the worker service gained a healthcheck so `up --wait` has a signal | `docker-compose.yml` | none |
| three capability checks | `scripts/sur1/preflight.py`, `receivers.py`, `promisepatch.py` | `DRIVER_VERSION` |

### 3.1 The runtime capability preflight

Three checks were added to `REQUIRED_CHECKS`, which is now seventeen. Each asks a **capability of
a process that is already running**, because reachability passed on all three while the run was
lost. None of them is an image timestamp.

**`order_projection`.** The order system is asked `GET /admin/capabilities` — a read-only route
this revision adds — and has to declare that it publishes the committed event body and the
command's idempotency key, and to name the entry and body fields it serves. The preflight then
requires the fields `receivers.OrderSystemReceiver._event` actually opens, and, when the log
already holds an event, checks the published entry against the declaration. A build too old to
carry the route answers `404`, which is read as the fact it is. Receiver evidence requirements
were **not** weakened to accommodate an old build.

**`backend_build`.** Two facts about two different things. The running API is asked `/readyz`,
which names the migration revision *its own code* was built for, and that has to equal this source
tree's `HEAD_REVISION` with the database at it. Separately, the in-process fixture load — which is
what actually installs a world — has to accept a stated `snapshot` and `fixture_name`, checked
against the signature of the function that will run, and `promisepatch` has to resolve inside this
repository. **Stated limitation:** an image stale only in code that no migration accompanied
reports the same revision and passes. Migration head is the strongest identity this product
publishes about itself today; it is a value the running process computes from its own bytes rather
than a tag anybody chose, which is the property that matters, but it is not a content hash of the
image and this revision does not claim it is.

**`worker_lifecycle`.** The world's worker control has to be real by declared kind — the same rule
`real_bindings` and `consent_ingress` use — and has to be able to observe the worker. A run that
cannot stop the worker cannot remove the race, and is refused rather than driven and hoped over.

### 3.2 The world-installation lifecycle

`LiveScenarioWorld.prepare` now runs every install through `InstallationLifecycle.around`:

1. **quiesce** — `docker compose stop worker`, then read the service state back and refuse to
   proceed unless it is actually stopped;
2. **install** — unchanged; `realisation.realise` still resets the order book, loads the canonical
   graph through the governed fixture load, and crosses each external change;
3. **verify** — read the product's own `fixture_state` row and require it to name
   `hollow-oak+sur1-<scenario>`. That row is written inside the load's own transaction, so it is
   the load's own evidence that it committed. A load refused by a trigger, a privilege or a
   deadlock leaves the previous row, and it is caught here instead of being measured;
4. **resume** — `docker compose up -d --wait --no-recreate worker`, then read the state back.

There is **no sleep and nothing is attempted twice.** Both compose operations are synchronous;
`--wait` blocks on the worker's healthcheck, which this revision adds because the service had none
and "compose says the container is running" was the only available signal. Every step ends with a
read of the state it was supposed to produce.

A failed install still resumes the worker, because leaving it down would turn one bad attempt into
a broken run — every later scenario would be driven at a system whose durable work never runs. The
original failure is what propagates; a resume that also failed is attached beside it as a note
rather than replacing it.

## 4. What did not move

Recomputed from the bytes on disk at this revision:

| Frozen element | Value | |
|---|---|---|
| manifest `safe-useful-recovery.v1.json` | `5718340fbd19aa8ba1aedc2327c07a934e22b773271e996f13f0e8d87e70e84c` | unchanged |
| baseline prompt `baseline-agent-prompt.v1.md` | `772ba46025620a1aea4742fac3971c5906ec3252036d07725434e0a89ce47cb1` | unchanged |
| scorer `score_safe_useful_recovery.py` | `SCORER_VERSION` `1.0.0` | unchanged |
| `PREDECLARATION_SHA` | `c53d267a0874d2e91456fdfacc23c86ebfc411f938cbe060ce958cb41d1e1927` | unchanged |
| `program_set_sha` | `88db566c13ef7a9865141583e5d918d43ff1b612b3311393c12af627ab1de649` | unchanged |
| `C01`–`C09` program hashes and world digests | all nine agree | unchanged |

`declaration.differences()` is empty. Ground truth, `the_point`, the arm definitions, the eleven
frozen actions, the tool surface, the attempt budget, the message ceilings, `RETRYABLE`,
`MAX_ATTEMPTS` and the blinding rules are **untouched**. No scenario was added, removed or
reworded. Both evaluation holdouts remain sealed.

`implementation_sha` moved, for two reasons and no others. The first is the governed-write
correction: `setup.py`, `worldsink.py` and the new `governed.py` are in `IMPLEMENTATION_MODULES`.
The second is §4.1. `lifecycle.py` is deliberately **not** added to that list: it decides when an
install is safe to perform, not what a program is or what its world looks like, and `world.py` —
which orchestrates preparation — has always sat outside that hash for the same reason. Driving is
`DRIVER_VERSION`'s to cover, and it was bumped.

### 4.1 The never-run claims were retired

Twelve modules under `scripts/sur1/` carried a sentence of the form *nothing here has been pointed
at a `SUR-1` scenario*, and the frozen declaration carried *no BASELINE, PROMISEPATCH or ABLATION
attempt has been driven at any `SUR-1` scenario*. All of those became false on 2026-09-19. They
were replaced with what is now true — that one scored run went through each of them, that it is
published inconclusive, and where applicable that the module is where it failed — rather than left
standing, because a freeze whose honesty rests on a statement that has become false is not a
freeze.

Nothing about behaviour changed in that pass: it is docstrings and one declaration string. What
the freeze actually claims — that the nine programs were fixed before any outcome was seen — is
unchanged and is still the first sentence of `NO_ARM_EXECUTED`. `program_set_sha`, all nine
program hashes and all nine world digests are unmoved, which §4 shows.

### 4.2 The scope freeze, re-recorded

`sur1-phase3-closeout.md` §8 recorded the scope freeze as git tree identities at `f4618c9`. Three
of those four are unmoved; the one that carries the correction is not. Checkable with
`git rev-parse <sha>:<path>` rather than trusted:

| Path | Tree / blob at the commit that bumped `DRIVER_VERSION` | |
|---|---|---|
| `scripts/sur1/` | `fef06e222af9a4bc9e230903c2ffd139a5c1544d` | moved |
| `scripts/rehearsal/` | `01f14418bf7127c3ccfd4860d1acf086696573b3` | unchanged |
| `scripts/score_safe_useful_recovery.py` | `ace137fa44ad383a969b6ca9b449e84af3f560b6` | **unchanged — the scorer** |
| `scripts/check_sur1_realisation.py` | `997ada54ff4a3f22a8ea10aa0595a9a4f14f9a1c` | unchanged |

`docs/benchmarks/` is deliberately not listed: this document lives in it, so any value quoted here
would be the tree that existed before it was written. The identities that matter beneath it —
the manifest, the prompt, `PREDECLARATION_SHA` and `program_set_sha` — are in §4 and are unmoved,
and the preflight recomputes every one of them on every scored run.

## 5. The `C02` disclosure, carried forward unchanged

On `C02` the apparent-assent hazard is posed to the baseline and not to arms B and C, so a `C02`
`consent_violations` reading for B and C may be vacuous rather than earned. Nothing in this
revision touches it. Say it beside any `C02` safety count published from this benchmark. See
[`sur1-consent-ingress.md`](../sur1-consent-ingress.md) and `sur1-phase3-closeout.md` §2.

## 6. Recorded, not fixed

- **`estimated_usd` is `unavailable` on every attempt.** The `SUR-1` capture path does not consult
  `evals/budget.py`, which carries a verified `us-east-1` price for the frozen model. Left alone:
  it touches the capture schema, and the run's cost is recomputable outside the harness (≈ $0.195
  for the first run).
- **`run.json` carries `finished_at: null`.** It is written once at run open and `write_once`
  forbids updating it. Left alone: correcting it means either a second write to a write-once
  record or a new record, and both are changes to the capture contract rather than to a defect
  that cost a verdict.

Neither affects a score. Both are restated here so the revision does not read as if the first
run's smaller observations had been quietly closed.

## 7. The proofs

Thirty-four of them, in two modules, none of which drives an arm, calls a model, opens a
database or runs `docker`. `C01`–`C09` were not driven to produce any of this.

`scripts/tests/test_sur1_harness_correction.py` — 24 checks:

| Claim | How |
|---|---|
| both tables the world writes are governed by the product | read from `promisepatch.db.boundary.GOVERNED_TABLES` |
| a hold, a release and a stock movement each carry an audit event | the writer records the call; every event type begins `BENCHMARK_WORLD_` |
| neither world writer can open a bare connection any more | AST over `setup.py` and `worldsink.py`: no `asyncpg` import |
| the audit claims no authority nobody gave | `AUTHORITY` is `NONE`, actor is the world facility |
| a failed governed write is named, not leaked as a driver error | a refused connection raises `GovernedWriteError` |
| a simulator too old to declare its projection is refused | `order_projection` against a reader that answers as a `404` build does |
| a projection publishing no command is refused | the exact entry shape the stale container served |
| a current order system passes | the declaration this build actually serves |
| the preflight asks for exactly what this simulator declares | the two packages meet in one assertion and nowhere else |
| the required fields are the ones the `E1` reader opens | AST over `receivers.py` |
| a backend on another migration head is refused | `/readyz` answering a different `expected_revision` |
| a backend whose database is behind its code is refused | `at_head: false` |
| an API that cannot be read is refused, not assumed current | the surface raises |
| a backend at this source revision passes | `HEAD_REVISION` on both sides |
| the governed fixture load takes a stated world | the signature of the function that runs |
| an `E1` row from a current projection survives its round trip | real reader → real payload → real strict reader, key intact |
| an `E1` row from the stale projection is what broke the capture | same path, `EvidenceMalformedError` on the empty key |
| the first scored run is byte-identical to what was published | 57 files, one pinned digest |
| the published run still says what it said | 24 / 1 / 2, counted out of the verdict files |
| every frozen benchmark identity is the published one | all five, recomputed, plus `differences() == ()` |

`scripts/tests/test_sur1_world_lifecycle.py` — 10 checks:

| Claim | How |
|---|---|
| the worker is down for the whole install and back up afterwards | the install observes the worker's state from inside itself |
| a world that did not land is refused rather than measured | `fixture_state` still naming the previous world |
| a database with no fixture row is refused | empty read |
| a failed install still hands the worker back | the quiesce/resume pair completes |
| a worker that will not come back is named beside the original failure | the note is attached, the original propagates |
| a retry begins clean | two attempts in a row, each quiesce → resume |
| a run that cannot control its worker is refused | `UncontrolledWorker` fails `worker_lifecycle` |
| a world with no worker control at all is refused | the check names the deadlock |
| a run binds the real worker control | `run.build` names `ComposeWorkerControl` |
| the compose worker can be waited on | the service carries a healthcheck |

**What is not proved here.** Nothing asserts that the corrected lifecycle survives a *live*
`docker compose` cycle, or that a governed world write commits against a *live* PostgreSQL —
both need the stack, and exercising them is the corrected run's preflight, not this session's.
They are named in §9.

## 8. What this revision does not do

- **It takes no run.** No arm was driven, no model called, no evidence collected and no verdict
  written. `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` was spent on the first run and nothing
  here spends anything.
- **It does not reinterpret the first run.** No verdict was re-read, no outcome recomputed and no
  narrative attached to `20260919T2020Z-scored` beyond the corrected root cause in §2.2.
- **It edits no frozen document**, no ground truth, no prompt, no scorer rule, no budget and no
  retry rule.
- **It deploys nothing and pushes nothing.**
- **It does not authorise the corrected run.** The session that changes the machinery is not the
  session that scores; that rule is unchanged.

## 9. What stands between this revision and a corrected run

None of it is a defect in the machinery, and none of it is this session's to clear.

1. **A fresh paid-inference authorisation.** `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` was
   spent on `20260919T2020Z-scored`. Nothing here re-authorises anything.
2. **A rebuilt local stack.** The corrections only take effect in *running* processes:
   `promisepatch-order-simulator:local` has to be rebuilt to serve `/admin/capabilities`, and
   `promisepatch-backend:local` has to be rebuilt to carry the worker healthcheck `up --wait`
   blocks on. The new preflight refuses a run against unrebuilt images, which is the point, but
   it cannot rebuild them.
3. **The lifecycle and the governed write against the live stack.** Neither has been executed
   against a running `docker compose` or a live PostgreSQL in this session — §7 says so. The
   first thing the corrected run's preflight does is exercise both; a smoke pass over one
   scenario's install would retire the risk earlier, and would be a *development* run, not a
   scored one.
4. **All seventeen checks passing in one report against real bindings.** `model_identity` and
   the AWS half of `configuration` have still never been asked of a real account.
5. **A different session.** The session that changes the machinery does not take the run. That
   rule is unchanged and this session is the one that changed the machinery.

Both evaluation holdouts remain sealed.
