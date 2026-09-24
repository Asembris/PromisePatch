# G8 rehearsal preparation — the protocol, and the two operational concerns reproduced

Date: **2026-09-24**, host work between `17:31Z` and `17:44Z`. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, verified before anything was read.

G8's central requirement is five complete deployed rehearsals from clean fixtures, each with
real customer transport and a worker restart ([phase7-closeout.md](phase7-closeout.md) §8).
[phase7-closeout.md](phase7-closeout.md) §9 named two recorded concerns that stand in the way:
the restore env union ([demo-world-restore.md](demo-world-restore.md) §4) and the start-up
world roll ([phase7-rc-deployment.md](phase7-rc-deployment.md) §3). This record does three things:

- it predeclares the five-run protocol (section 3);
- it reproduces both concerns against the frozen release candidate `4529a802e34e` (sections 4
  and 5);
- it classifies each one.

**No rehearsal was run.** No plan was confirmed, no approval was asked for, and no message was
sent.

## 1. Verdicts

| concern | verdict |
|---|---|
| restore env union | **NOT A BLOCKER.** Reproduced exactly at the RC. It is an operator and documentation inconvenience with a repeatable, value-free recipe. New here: a dry run does not see the gap, so the gate must include a settings preflight (section 4) |
| worker-start world roll | **NOT A BLOCKER.** A documented restart of a freshly restored world preserved it exactly: `PRESENT`, `rolled: false`, **zero rows written**. The earlier `NO_OPEN_COMMITMENT` case belongs to the demo world aging while nothing pins it, not to a restart. A rehearsal restores first and is pinned by its own effects once the plan is confirmed (section 5) |

**The frozen RC needs no code change before rehearsal #1.** No product code, test, deployment
file or infrastructure was changed.

## 2. Entry, and what was authorised

| | measured |
|---|---|
| HEAD / `origin/main` | `46804ef8d6ca…`, equal; tracked tree clean; the eleven known untracked artefacts untouched |
| Stack | `promisepatch-prod`, `UPDATE_COMPLETE`, last updated `2026-09-24T16:00:45Z`, **0 change sets**; `ImageTag`, `DeclaredImageTag` and SSM `image-tag` (v9) all `4529a802e34e`; SSM `compose` (v14) and `caddyfile` (v13) byte-equal to HEAD |
| Instance / volume / RDS | `i-087c742587f83d61d` `t4g.small` `ami-0fa4996c14e7d501e`, launched `2026-09-18T10:19:33Z`, IMDSv2 required, hop limit 2 / `vol-0f330aaa62e637ef6` / `db-U2JWQBTINX6W6GAB56EOTHOCSM`, private, encrypted |
| Host `boot_id` | `109dccdf-b7fb-4882-8b28-c963b2f0f7b9` (`uptime -s` `2026-09-24 16:02:33`), unchanged throughout |
| `/healthz` / `/readyz` | `image: 4529a802e34e`; ready; migrations at head `0009_human_plan_approval` |
| Provider | `telegram` in `api` and `worker`; bot token present (value not read) |
| World at entry | the privacy repair's world: anchor `16:07:35Z`; one case `98aa7036-…` `RESOLVED`; outbox 3, all `DELIVERED`, **0 `PENDING`/`IN_FLIGHT`**; `cus-tomas` bound (address length 10), the other five at placeholders |

The owner authorised **exactly one** guarded `pp restore-demo-world --confirm
destroy-and-restore` and **exactly one** worker restart by the documented mechanism. **Each was
used once.** Host access was `ssm:StartSession` with `AWS-StartNonInteractiveCommand` alone. No
IAM change, release, redeploy, change set, SSM write or volume change was made.

## 3. The five-run rehearsal protocol (predeclared)

### 3.1 Common to every rehearsal

**Release.** All five rehearsals run on one deployed image. That image is `4529a802e34e` unless a
repair supersedes it. A repair that changes the image restarts the count on the new SHA. Runs
already taken stay recorded under their own SHA.

**Authorisation.** Each rehearsal needs the owner's explicit authorisation for:

- its one restore;
- its one plan confirmation;
- its one real approval message;
- its restart.

The customer's press is the owner's own action on the phone. Nothing in the session opens,
follows, simulates or writes it.

**Timing, declared rather than hoped for.**

- The restore anchors at `now` only inside Tunis local `[01:00, 23:00)` (`resolve_demo_anchor`).
- Plan confirmation must come within the ten-minute §14.1 window, or the case escalates
  `PLAN_UNCONFIRMED` (measured again in section 5).
- The customer answers inside the approval window, which is anchor + 5 h.
- The whole rehearsal finishes **before `22:00Z`**. That keeps it clear of the bakery-day turn at
  `23:00Z`, where the worker's keeper runs provisioning again, and well ahead of `EXT-B`'s
  production start at anchor + 6 h (ADR-0024/0026).

**Step 0 — entry census** (read-only):

- the image on stack, SSM, `/healthz` and every container;
- migration at head;
- provider `telegram`;
- **0 `PENDING`/`IN_FLIGHT` outbox rows**;
- exactly one customer bound;
- the worker-log counters `sendMessage`, `worker.telegram.sent` and `getUpdates`;
- `audit_events` and `domain_events` max `seq`.

**Step 1 — guarded restore**, run in `worker` with the env union injected on the host (section
4). Values are read out of `env/migrate.env` and never printed. The restore proceeds only if all
of these hold:

- (a) a **settings preflight under the union** reports every `require_*` as `ok`, with
  `allow_fixture_reset` and `demo_session_enabled` both `True`;
- (b) the `--dry-run` under the union exits `0`;
- (c) the dry run reports `binding: restored`, `unsettled=0` and `fixture=hollow-oak`.

Then the restore runs once. The expected state after it:

- a fresh anchor;
- exactly one case, `PLANNED`, in the canonical partition:
  - `pr-a` `AUTO_RECOVERABLE` `R-PREAPPROVED`;
  - **`pr-b` `APPROVAL_REQUIRED` `R-VISIBLE-ASK` `rose-2 → rose-3`, the only approval-required
    option**;
  - `pr-c` and `pr-d` `BLOCKED` `R-NOSUB`;
  - `pr-e` and `pr-f` `UNAFFECTED`;
- one unfired `PLAN_AUTO_ESCALATION` timer;
- outbox, requests, decisions, `plan_approvals` and replies all `0`;
- every order at external version 1, in the mirror and in the order system;
- `cus-tomas` bound, verified through `_verify_destination` (`returned_id_matches_stored=True`,
  `chat_type=private`, no message);
- the ledgers only grew.

**Step 2 — baseline evidence.** Take the per-rehearsal *unrelated digest* over every promise,
order, line, task and customer outside `pr-a`/`EXT-A` and `pr-b`/`EXT-B`. Compute it with **one**
evidence reader, fixed before rehearsal #1, whose sha256 is recorded, and use the same bytes all
five times.

**Checkpoints.** The state each rehearsal must reach, which is effect-set scenario `S16`'s,
unchanged:

| checkpoint | expected |
|---|---|
| `PLANNED` | as step 1; no effect |
| `CONFIRMED` | `plan_approvals` 1, from `OPERATOR_CONSOLE`; audit `PLAN_APPROVED` and `PLAN_CONFIRMED` both `HUMAN_APPROVAL`, actor `WORKER maya` |
| | `pr-a` applied under `CONSTRAINT`: one `ORDER_AMEND`, `EXT-A` v1 → v2 `almond-4` |
| | `pr-b` `WAITING_FOR_CUSTOMER`, one request `SENT`, one `MESSAGE_SEND` `DELIVERED` at attempt 1, `sendMessage` +1 |
| | `pr-c` and `pr-d` `ESCALATED`, with `task-ol-c` and `task-ol-d` `HELD` |
| | `task-ol-e` stays `STARTED` and is **never held** ([started-work-contract.md](started-work-contract.md)); case `WAITING` |
| `CONSENT_SETTLED` | one `approval_decisions` row: `APPROVE`, parser `LITERAL`, sender equal to the request's channel; one `inbound_replies` row; the `customer-reply` inbox row `PROCESSED`; audit `APPROVAL_DECISION_RECORDED` by `CUSTOMER cus-tomas`, `HUMAN_APPROVAL` |
| | **ten `REVALIDATION_CHECK` rows, all passed, against a fresh snapshot, written after the decision** |
| | `RECOVERY_REVALIDATED`, `RECOVERY_APPLIED` and `RECOVERY_COMPLETED`, all `HUMAN_APPROVAL` |
| | one `ORDER_AMEND`: `EXT-B` v1 → v2 `AMENDED` `rose-3`, claimed at `attempts == 1` while the production start is ahead (ADR-0026) |
| | the order system's own store equal to the mirror (`ORDER_MIRROR_UPDATED`) |
| `SETTLED` | `pr-b` `RECOVERED`; case `RESOLVED`; `plan_approvals` **still 1** |

**Exactly-once, at the end of every rehearsal:**

- outbox exactly 3 rows (`ORDER_AMEND` ×2, `MESSAGE_SEND` ×1), all `DELIVERED` at attempt 1, with
  3 distinct keys;
- `sendMessage` exactly +1 over the rehearsal, `getUpdates` 0;
- 1 request, 1 decision and 1 reply;
- exactly one case;
- the restart itself adds **no** effect, no step retry, no case and no plan approval.

**Untouched:**

- `EXT-C` to `EXT-F` at external version 1, in the mirror and in the order system;
- `pr-e` and `pr-f` `UNAFFECTED`, with no message, write, hold or audit event attributed to them;
- the unrelated digest equal between `CONFIRMED` and `SETTLED`.

**Privacy:**

- no chat id, token or link in any output, container log or CloudWatch event written during the
  rehearsal;
- scans print counts and fingerprints only.

**Restart evidence** (every rehearsal):

- the worker's `StartedAt` moved;
- a `worker.stop` line, then a `worker.start` line with a **new instance id**;
- the new instance's `worker.demo_case` line reads `PRESENT` (or `REFUSED`), with `rolled: false`;
- every step after the restart point is executed by the new instance id;
- pre- and post-restart snapshots of the fixture, cases, tracks, timers, steps, counts, orders,
  customers and tasks, with no difference other than the work the protocol expects.

**Pass/fail.** A rehearsal **passes** only if every checkpoint, exactly-once, untouched, privacy
and restart item above holds.

- **Any deviation is a FAIL.** A fail is recorded and its evidence preserved. It is never
  re-labelled, re-run into a pass or edited.
- A rehearsal that cannot reach its restart point for an operational reason, such as the plan
  window closing before confirmation, is **VOID**: recorded, not counted, never deleted.
- Five **PASS** runs on one image close this G8 item. A failure found in the RC is recorded beside
  [phase7-closeout.md](phase7-closeout.md) and repaired under G8 through a new release.

### 3.2 The five restart points

Each rehearsal uses the documented mechanism. The restart is
`docker compose --env-file env/stack.env restart worker`. R2 and R3 split the same mechanism into
its two halves, `stop worker` … `start worker`, so that one declared action happens while no
worker runs. While the worker is stopped, operator commands run in `api`, which has the same
image and the same `api.env` + `channel.env`.

| run | restart point | before the restart | while down / after the restart | what it adds |
|---|---|---|---|---|
| **R1** | while waiting for consent (`S16`) | restore, confirm, the `MESSAGE_SEND` `DELIVERED`, the request `SENT`, the message seen on the phone | `restart worker`, then the customer presses APPROVE | the wait is durable: a different worker instance revalidates and applies, once |
| **R2** | across the plan confirmation | restore, then `stop worker` | `pp confirm-plan` in `api` while no worker runs: `plan_approvals` 1 and **no** `sendMessage`, no `ORDER_AMEND` delivered; then `start worker` | queued work is dispatched exactly once by the new instance: the `CONFIRMED` effects, each at attempt 1 |
| **R3** | across the customer's answer | restore, confirm, delivery, then `stop worker` | the customer presses APPROVE while no worker runs: the decision is recorded, **no** `REVALIDATION_CHECK` row, `EXT-B` still v1; then `start worker` | the answer waits and is revalidated when a worker returns, against a fresh snapshot (ADR-0025) |
| **R4** | after settlement | the full loop to `RESOLVED` | `restart worker` | a restart of a finished, pinned world writes nothing: `PRESENT`/`REFUSED`, no new case, no effect |
| **R5** | while waiting for consent (repeat of R1) | as R1 | as R1 | the canonical shape repeated exactly, for repeatability |

None of the five is G8's live stale refusal, which is a separate item.

## 4. The restore env union, reproduced

### 4.1 What the command needs, and where it lives on the host

Key names only, read on the host. No value was printed.

| setting | `api` | `worker` | `mcp` | `migrate.env` | `api.env` | `channel.env` |
|---|---|---|---|---|---|---|
| `PP_ALLOW_FIXTURE_RESET` | – | – | – | yes | – | – |
| `PP_DEMO_SESSION_ENABLED` | yes | yes | – | – | yes | – |
| `PP_ORDER_SYSTEM_BASE_URL` | yes | yes | – | – | yes | – |
| `PP_DATABASE_URL` | yes | yes | – | – | yes | – |
| `PP_MIGRATION_DATABASE_URL` | – | – | – | yes | – | – |
| `PP_DEMO_WORKER_PASSWORD` | – | – | – | yes | – | – |
| `PP_DEMO_OWNER_PASSWORD` | – | – | – | yes | – | – |
| `PP_CUSTOMER_CHANNEL_PROVIDER` | yes | yes | – | – | – | yes |
| `PP_TELEGRAM_BOT_TOKEN` | yes | yes | – | – | – | yes |

Compose gives `migrate` and `seed` `env/migrate.env`, and gives `api` and `worker`
`env/api.env` + `env/channel.env`. **No deployed container holds the union.** The worker's own
`Settings`, asked in place, reports:

- `allow_fixture_reset=False`;
- `migration_database_url_set=False`;
- both demo passwords unset;
- `require_demo_worker_password`, `require_demo_owner_password` and
  `require_migration_database_url` each refusing, with the documented `RuntimeError`.

### 4.2 The dry run does not see the gap

This is new, and it is why the gate changed.

```text
pp restore-demo-world --dry-run                      (nothing injected)                 -> exit 1
fixture resets are disabled; set PP_ALLOW_FIXTURE_RESET=true to enable one.

pp restore-demo-world --dry-run                      (only PP_ALLOW_FIXTURE_RESET=true) -> exit 0
action:   inspected
before:   fixture=hollow-oak cases=1 live=0 outbox=3 unsettled=0 requests=1 decisions=1 approvals=1 replies=1 audit=367 events=467 bound=True
binding:  restored (would be carried across)
result:   nothing was written
```

The second dry run passes. The confirmed run in the same environment would still refuse,
because `_reseed` starts with `require_demo_worker_password()`. That refusal is free: it comes
before the engine is built and before the `TRUNCATE`
([demo-world-restore.md](demo-world-restore.md) §4). So nothing is at risk. But **a dry run alone
cannot tell the operator the command will run**, which is why step 1 of the protocol gates on
the settings preflight as well. Both dry runs wrote nothing: the census before and after was
identical, and `sendMessage` stayed at its prior lifetime count of 1.

### 4.3 The one restore, through the union

The values were read on the host from `env/migrate.env` into shell variables, passed with
`docker compose exec -e`, and unset afterwards.

- **Preflight:** all four `require_*` `ok`, `allow_fixture_reset=True`,
  `demo_session_enabled=True`, `provider=telegram`.
- **Dry run:** exit `0`, `binding: restored`, `unsettled=0`, `fixture=hollow-oak`.

Then, once, `17:32:54Z` → `17:32:59Z`:

```text
pp restore-demo-world --confirm destroy-and-restore          -> exit 0
action:   restored
before:   fixture=hollow-oak cases=1 live=0 outbox=3 unsettled=0 requests=1 decisions=1 approvals=1 replies=1 audit=367 events=467 bound=True
after:    fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=381 events=486 bound=True
anchor:   2026-09-24T17:32:56.380649+00:00
digest:   b326e2db83a65d4a6e236c73bfae2a7b4dc828fe30a0b64be38562f1198fc1e7
rows:     160
orders:   6 reset in the external order system
case:     87590614-896c-5388-bd3b-7efdad906b4d
state:    PLANNED
binding:  restored
ledgers:  grew only
```

Verified independently, by SQL and by `pp case-status`:

- **The partition:** `pr-a` `AUTO_RECOVERABLE` `R-PREAPPROVED` `almond-3 → -4` (no approval);
  **`pr-b` `APPROVAL_REQUIRED` `R-VISIBLE-ASK` `rose-2 → -3`, the only approval-required option,
  window closes `22:32:56Z`**; `pr-c`/`pr-d` `BLOCKED` `R-NOSUB`; `pr-e`/`pr-f` `UNAFFECTED`.
- **Orders:** all six at external version 1; the order simulator `200`.
- **Ledgers:** `audit_events` 367 → 381, `seq` 1–381 contiguous.
- **Counters:** outbox and every authority counter `0`.
- **Binding:** exactly one customer bound. `_verify_destination` in `worker`:
  `returned_id_matches_stored=True`, `chat_type=private`, `@PromisePatchDemoBot`.
- **Public payloads:** the address is absent from `GET /api/cases` and `GET /api/cases/{id}`
  (12 414 bytes), and neither carries a `provider_ref` or `sender_identity` key.
- **Container logs:** 0 address lines and 0 chat-id-shaped lines in `api`, `worker`, `mcp`,
  `caddy` and `order-simulator`.
- **Nothing sent:** `sendMessage` unchanged.
- **No reboot:** host `boot_id` unchanged.

### 4.4 Classification: NOT A BLOCKER

The restore does not run from any one deployed container as shipped. It runs reliably and
repeatably with a fixed, value-free recipe: read the four settings on the host, pass them with
`exec -e`, and gate on preflight + dry run. The ledger's `fixture.reset` rows show the command
taken **five times on the deployed host** with that recipe:

- 2026-09-23, per [demo-world-restore.md](demo-world-restore.md);
- 2026-09-24 at `12:59Z`, per [phase7-rc-deployment.md](phase7-rc-deployment.md);
- 2026-09-24 at `14:13Z`, per
  [phase7-deployed-behavioral-proof.md](phase7-deployed-behavioral-proof.md);
- 2026-09-24 at `16:07Z`, per
  [phase7-approval-log-privacy-repair.md](phase7-approval-log-privacy-repair.md);
- here.

It exited `0` every time, carried the binding every time, and sent nothing. Every
missing-setting refusal happens before the first destructive statement. What the gap costs is
operator care, not correctness or repeatability. It stays **P2**, recorded and unfixed. Closing
it would be a change to the deployment definition, and it is not needed to start G8.

## 5. The worker-start world roll, reproduced

### 5.1 The one restart, on a clean restored world

**Before**, `17:33:54Z`, 58 s after the restore:

- fixture anchor `17:32:56.380649Z`, digest `b326e2db…`;
- case `87590614-…` `PLANNED` v7;
- tracks `pr-a`…`pr-d` `PENDING`, `pr-e`/`pr-f` `UNAFFECTED`;
- `PLAN_AUTO_ESCALATION` due `17:42:58.49Z`, unclaimed;
- six steps `DONE`;
- outbox, requests, decisions, approvals, replies and inbox all 0;
- `audit_max` 381, `events_max` 972;
- orders all v1;
- tasks: `task-ol-e` `STARTED`, the other five `SCHEDULED`.

**The restart**, `17:33:55.500Z`, by the documented
`docker compose --env-file env/stack.env restart worker`:

```text
{"worker": "ef6428bb042b:1:d2f54ecd", "event": "worker.stop", "timestamp": "2026-09-24T17:33:55.599847Z"}
{"action": "PRESENT", "case_id": "87590614-896c-5388-bd3b-7efdad906b4d", "detail": "this world's case already exists; nothing was touched", "rolled": false, "event": "worker.demo_case", "timestamp": "2026-09-24T17:33:58.479246Z"}
{"worker": "ef6428bb042b:1:1e096e25", "event": "worker.start", "timestamp": "2026-09-24T17:33:58.479377Z"}
```

The same container (`ef6428bb042b`) is back, with `StartedAt` `17:33:56.63Z`, a new instance id
`…:1e096e25`, and no error-level line.

**After**, `17:34:03Z`: the diff of the fixture, cases, tracks, timers, steps, counts, orders,
customers and tasks is **empty**. `audit_max` is still 381 and `events_max` still 972, so **the
restart wrote no row at all**:

- no re-anchor;
- no reseed;
- no second case;
- no conclusion of the live case;
- no effect;
- no message (`sendMessage` unchanged, `getUpdates` 0).

**The durable timer survived the restart and fired exactly once**, from the new instance:

| | row |
|---|---|
| timer | `PLAN_AUTO_ESCALATION` due `17:42:58.491Z`, claimed and fired `17:42:58.847Z` |
| step | `ESCALATE_PLAN` `DONE` at attempt 1: `PLAN_UNCONFIRMED` over four tracks |
| audit 382 | `PLAN_AUTO_ESCALATED`, actor `SYSTEM ef6428bb042b:1:1e096e25`, authority `NONE` |
| audit 384 | `CASE_RECONCILED` → `RESOLVED`, owner attention |
| events 978–984 | four `track.escalated` (`R-NOSUB` ×2, `R-PREAPPROVED`, `R-VISIBLE-ASK`), `tasks_held: 1` each |
| tasks | `task-ol-a` to `task-ol-d` `HELD`; **`task-ol-e` still `STARTED`, not held** |
| effects | outbox 0, requests 0, decisions 0, `plan_approvals` 0, replies 0 |

That is §14.1 behaving as recorded in [phase7-rc-deployment.md](phase7-rc-deployment.md) §8,
again, now across a restart. It is the reason each rehearsal must confirm within ten minutes of
its restore.

### 5.2 Why the earlier `NO_OPEN_COMMITMENT` case is aging and not a restart defect

The append-only ledger holds every reset, re-anchor and physical fact since 2026-09-23:

| seq | event | at | what |
|---|---|---|---|
| 560 / 576 | `fixture.reset` / `physical_fact.recorded` | `09-23 13:06Z` | restore; case `5b825f1b` settles a raspberry line |
| 616 | `fixture.reanchored` | `09-23 23:00:00Z` | **day-turn roll**, not a start: `13:06Z → 09-24 00:00Z`, `shifted_by_seconds` 39 203 |
| 632 | `physical_fact.recorded` | `09-23 23:00:03Z` | case `f02697c0` finds an open raspberry line and plans |
| 670 | `fixture.reanchored` | `09-24 12:57:01Z` | **worker start after the rollout reboot**: `00:00Z → 12:57Z`, 46 622 s |
| — | audit `NEEDS_HUMAN_INTERPRETATION` | `09-24 12:57:02Z` | case `8c652643` stops at `NO_OPEN_COMMITMENT`; **no physical fact recorded** |
| 680 onward | `fixture.reset` ×4 | `12:59Z`, `14:13Z`, `16:07Z`, `17:32Z` | restores; each case records its physical fact normally |

Both rolls happened on a world **nothing pinned**: no outbox row, no request, no reply, and every
earlier case terminal. Each happened hours after its anchor, when `_world_tells_the_story` had
turned false. Roll 1 happened at the bakery-day turn. Roll 2 happened when promise `pr-e` came
due at anchor + 9 h, well before the next start.

The code explains the difference between the two:

- `reanchor_world` shifts every instant and **never writes `received_state`**. A settled line
  stays settled, which is the physical-facts invariant working.
- The fixture has two raspberry commitment lines, today's and tomorrow's.
- Each provisioned case settles one of them at `RESOLVE_OBSERVATION`.
- `_commitment_candidates` narrows to today's delivery only when one has an open line. Otherwise
  it keeps every open candidate.

So roll 1 resolved to tomorrow's still-open line, and roll 2, after both lines were settled,
found none. That reading is **inferred from the code and these rows**. It is consistent with
both, and it was not reproduced by driving a roll.

The defect it points at is real but narrow. `_world_tells_the_story` counts raspberry-bearing
deliveries today without asking whether their line is still **open**, so it calls a world
rollable that a roll cannot bring back to the story. That is demo tooling and P2, recorded and
unfixed. **It is unreachable from a rehearsal**, for two reasons:

1. Every rehearsal begins with a **restore, which reseeds** every line to `EXPECTED`. It is not a
   roll.
2. Once the plan is confirmed, the outbox is non-empty, and `_what_would_be_lost` refuses every
   later roll for the life of that world, monotonically. Before confirmation, a restart within
   hours of the restore finds the world current and reports `PRESENT`, as measured in 5.1.

The deployed world as left now is unpinned. Its today raspberry line is `NOT_RECEIVED` and its
tomorrow line is `EXPECTED`. Its first non-current moment is `pr-e`'s due time,
`2026-09-25T02:32:56Z`. After that, the next keeper check or worker start will roll it: the
bakery-day turn at `2026-09-25T23:00Z`, or a reboot before then. The case that roll opens will
resolve against tomorrow's line, exactly as roll 1 did. That is expected aging, and the next
rehearsal's restore clears it.

### 5.3 Classification: NOT A BLOCKER

A documented restart preserves a restored world exactly. It preserves the durable timer and
fires it once. The only way a start moves the world is the intended roll of an aged, unpinned
world, and a rehearsal cannot reach that path.

## 6. Safety and health, at the end

Read at `17:43:34Z`–`17:43:37Z` on the host, and at `19:00Z` from the control plane.

| | state |
|---|---|
| effects | outbox 0, **0 `PENDING`/`IN_FLIGHT`**; requests, decisions, `plan_approvals`, replies and inbox all 0. Nothing in flight, nothing waiting on a person |
| messages | worker `sendMessage` 1 and `worker.telegram.sent` 1, both over the container's lifetime and both from the privacy repair's loop before this session; **0 added**; `getUpdates` 0 |
| cases | exactly one, `87590614-…`, `RESOLVED` with owner attention (`PLAN_UNCONFIRMED`) |
| binding | `cus-tomas` bound (length 10), re-verified; the other five at placeholders |
| privacy | 0 address lines, 0 chat-id-shaped lines and 0 unredacted link forms in all five container logs; nothing printed in this session carried an address, token or secret |
| health | `/healthz` `4529a802e34e`; `/readyz` ready, migrations at head, fixture anchor `17:32:56Z`; all containers running on `4529a802e34e` (`caddy` on `caddy:2.10-alpine`) with 0 restarts; `migrate` exited 0; order simulator 200 |
| host | `boot_id` `109dccdf-…` throughout: **no reboot**; `converge.sh` `09105b10…` and `channel.env` `c3a6e4de…` unchanged; certificate and key dated `2026-09-13 18:35`; all three Docker volumes present |
| infrastructure | stack `UPDATE_COMPLETE` at `16:00:45Z`, 0 change sets; SSM unchanged; instance, AMI, launch time, volume and RDS identical to entry |

Smoke was not re-run. The known port-80 self-hairpin limitation applies unchanged
([phase7-closeout.md](phase7-closeout.md) §4).

## 7. What this does not prove

- **No rehearsal was run**, and nothing here counts as one of the five. There was no plan
  confirmation, message or customer answer.
- **The restart was taken on a `PLANNED` world, not a `WAITING` one.** With no confirmed plan
  there was no in-flight work to resume, so R1–R3's resumption behaviour is predeclared here,
  not measured.
- **The `NO_OPEN_COMMITMENT` mechanism is inferred**, not reproduced by driving a roll.
- **No refusal path of the restore** (a moved topology, a second bound customer, a pending effect,
  an unreachable order system) was exercised live.
- The evidence reader for the unrelated digest is not yet fixed. Section 3.1 requires that before
  rehearsal #1.

## 8. Remediation scope

**None required before G8's rehearsals.** Two P2 items stay recorded and unfixed, neither
blocking:

- **The env union.** A value-free way to run the restore from one container, for example a
  compose service carrying both env files. That is a deployment-definition change.
- **The roll's currency check.** It should require an *open* raspberry line.

## 9. Next

**Deployed rehearsal #1 (R1)** under section 3, with the owner authorising its restore, plan
confirmation, one real approval message and its restart. First fix the evidence reader and record
its sha256.
