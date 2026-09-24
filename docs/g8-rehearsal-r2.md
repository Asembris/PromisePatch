# G8 deployed rehearsal R2 — the plan confirmed while no worker runs

Date: **2026-09-24**, host work between `19:47Z` and `19:56Z`. Entry at
`5e6e43f9a683899b40cedb4eefd66c1c5f3297fa`: `main` equal to `origin/main`, tracked tree clean, and
the eleven known untracked artefacts left as they were. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`.

This is rehearsal #2 of the five that [g8-rehearsal-preparation.md](g8-rehearsal-preparation.md)
§3 predeclared, run against the frozen release candidate `4529a802e34e`
([phase7-closeout.md](phase7-closeout.md)). R2's restart point is **across the plan
confirmation**. The documented mechanism is split into its two halves (§3.2):

1. `stop worker`;
2. `pp confirm-plan` in `api` while no worker runs;
3. `start worker`.

The pass/fail contract is §3.1 of that document, plus R2's row in §3.2, unchanged. It was not
redefined here.

## 1. Verdict

**R2: PASS.** Every checkpoint, exactly-once, untouched, privacy and restart item in §3.1 holds,
as does R2's own requirement:

- the confirmation, taken while no worker ran, was durable and sent nothing;
- the new worker instance dispatched the queued `CONFIRMED` work exactly once, each effect at
  attempt 1.

It counts as **2 of 5** on image `4529a802e34e`, after R1
([g8-rehearsal-r1.md](g8-rehearsal-r1.md)). No product code, test, deployment file,
infrastructure, IAM, SSM parameter or release was changed.

## 2. Authorisation, and what was spent

The owner authorised exactly:

- one guarded demo restore;
- stopping the worker only;
- one plan confirmation while the worker was stopped, through `pp confirm-plan` in `api`;
- starting the worker again;
- one real Telegram approval message.

**Each was used once.** The customer's press was the owner's own action on the phone: the owner
opened the signed link from the one message and pressed APPROVE, and reported "approved, exactly
one message seen". Nothing in the session opened, followed, simulated or wrote that answer.

Host access was `ssm:StartSession` with `AWS-StartNonInteractiveCommand` alone. Every census ran
in a read-only transaction. Nothing printed in this session carried a chat id, a bot token, a
password or the approval link.

## 3. The frozen evidence reader

- **Extraction:** the reader was extracted from the appendix of
  [g8-rehearsal-r1.md](g8-rehearsal-r1.md) at `HEAD`, by the recorded
  `awk '/^```python$/{f=1;next} /^```$/{if(f){exit}} f'`.
- **Hash:** sha256 **`c9731c8f8dedfe15fbc6af0c2db6a8d5d19ca090d7863f3d2e945b18220b0dd4`**. It is
  byte-identical to R1's frozen copy, compared with `cmp`.
- **On the host:** the host printed the same sha256 before every one of the five reads.
- **Edits:** never edited.

While the worker was down, the reader ran in `api`. That is the same image, and it has the same
`api.env` and `channel.env`.

## 4. Timeline

| UTC | event |
|---|---|
| `19:47:43` | entry census: R1's case `e66069d7-…` `RESOLVED`, outbox 3 all `DELIVERED`, **0 `PENDING`/`IN_FLIGHT`**, one customer bound, worker `sendMessage` lifetime 2 |
| `19:49:52.845` → `19:49:57.415` | **restore** (the one) |
| `19:50:07.433` | **worker stop** issued (the one); `worker.stop` logged `19:50:07.559`, container `exited` by `19:50:08.178` |
| `19:50:09.443` → `19:50:11.819` | **plan confirmation in `api`** (the one), no worker running |
| `19:50:12` → `19:51:18` | stopped hold: snapshot A, then snapshot B 60 s later, identical |
| `19:52:00.591` | **worker start** issued (the one); `StartedAt` `19:52:03.581`, `worker.start` `19:52:05.510` |
| `19:52:05.542` → `19:52:06.610` | the new instance runs the queued work; the one `MESSAGE_SEND` delivered `19:52:06.345`, request `SENT` `19:52:06.545` |
| `19:54:17.642` | the owner's APPROVE arrives (`inbound_replies`) |
| `19:54:20.381` | `RECOVERY_COMPLETED`; case `RESOLVED` |
| `19:55:08` → `19:55:56` | settled evidence, CloudWatch scan, store and control plane |

It finished at `19:56Z`, well before the `22:00Z` bound. The confirmation came 14 s after
planning, inside the ten-minute §14.1 window. The approval window closes
`2026-09-25T00:49:54Z`.

## 5. Entry (step 0)

| | measured |
|---|---|
| Stack | `promisepatch-prod` `UPDATE_COMPLETE`, last updated `16:00:45Z`, **0 change sets** |
| Image | `ImageTag`, `DeclaredImageTag` and SSM `image-tag` (v9) all `4529a802e34e`; SSM `compose` v14 and `caddyfile` v13 byte-equal to HEAD |
| Instance / volume / RDS | `i-087c742587f83d61d` `t4g.small` `ami-0fa4996c14e7d501e`, launched `2026-09-18T10:19:33Z`, IMDSv2 required, hop limit 2 / `vol-0f330aaa62e637ef6` encrypted / `db-U2JWQBTINX6W6GAB56EOTHOCSM` private, encrypted |
| Host | `boot_id` `109dccdf-b7fb-4882-8b28-c963b2f0f7b9`, up since `16:02:33` |
| Containers | `api`, `worker`, `mcp` and `migrate` on `backend:4529a802e34e`; `order-simulator` on `order-simulator:4529a802e34e`; `caddy:2.10-alpine`; 0 restarts. Worker `ef6428bb042b`, instance `…:1:4ccc1ebc` (R1's post-restart instance) |
| `/readyz` | ready; migrations at head `0009_human_plan_approval` |
| Provider | `telegram` in `api` and `worker`, bot token present (value not read) |
| Effects | **0 `PENDING`/`IN_FLIGHT`**; nothing waiting on a person |
| Binding | `cus-tomas` bound (address length 10), the other five at 4-character placeholders |
| Counters | worker `sendMessage` 2, `worker.telegram.sent` 2, `api.telegram.org` 200s 2, non-200 0, `getUpdates` 0 |
| Files | `converge.sh` `09105b10…`, `env/channel.env` `c3a6e4de…` |
| Logs | 0 token-shaped, 0 unredacted, 0 address and 0 chat-id lines in all five containers |

## 6. Step 1 — guarded restore (`PLANNED`)

The env union was read on the host from `env/migrate.env`, passed with `exec -e` into `worker` and
unset. No value was printed.

- **(a) Settings preflight under the union:** all four `require_*` `ok`;
  `allow_fixture_reset=True`, `demo_session_enabled=True`, `provider=telegram`; `preflight=ok`.
- **(b) Dry run:** exit `0`.
- **(c) Dry-run content:** `binding: restored`, `unsettled=0`, `fixture=hollow-oak`.
  `restore_gate=ok`.

```text
action:   restored
before:   fixture=hollow-oak cases=1 live=0 outbox=3 unsettled=0 requests=1 decisions=1 approvals=1 replies=1 audit=430 events=545 bound=True
after:    fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=444 events=564 bound=True
anchor:   2026-09-24T19:49:54.663866+00:00
local:    2026-09-24T20:49:54.663866+01:00 Africa/Tunis
digest:   6ffe60f768e3767ff9ed1117ae5c14bdb7c62e1750ff64ca96a0593683f52495
rows:     160
orders:   6 reset in the external order system
case:     75dd110e-9313-55c6-9926-773ce333881d
state:    PLANNED
binding:  restored
ledgers:  grew only
result:   restored; no plan was confirmed and no message was sent
restore_exit=0
```

**The `PLANNED` checkpoint**, gated automatically before anything else and confirmed by census:

- **Partition:**
  - `pr-a` `AUTO_RECOVERABLE` `R-PREAPPROVED` `almond-3 → -4`, no approval;
  - **`pr-b` `APPROVAL_REQUIRED` `R-VISIBLE-ASK` `rose-2 → rose-3`, the only approval-required
    option**;
  - `pr-c` `BLOCKED` `R-NOSUB` (`NOSUB_CONSTRAINT`) and `pr-d` `BLOCKED` `R-NOSUB`
    (`NO_PREAUTHORED_VARIANT`);
  - `pr-e` and `pr-f` `UNAFFECTED` `R-UNREACH`.
  - `partition_gate=ok`.
- **Case:** `75dd110e-…` `PLANNED` v7, the only case. Plan `c9cae006…`. One unfired
  `PLAN_AUTO_ESCALATION` due `19:59:56.75Z`.
- **Counters:** outbox, requests, decisions, `plan_approvals`, replies and inbox all 0.
- **Orders:** all six at v1 in the mirror and in the order system.
- **Tasks:** `task-ol-e` `STARTED`, the other five `SCHEDULED`.
- **Binding:** exactly one customer bound. `_verify_destination` (a `getChat`, no message) gave
  `returned_id_matches_stored=True`, `chat_type=private` and `@PromisePatchDemoBot`. The address
  is absent from `GET /api/cases` and `GET /api/cases/{id}` (12 414 bytes), and neither body has
  a `provider_ref` or `sender_identity` key.
- **Ledgers:** audit 430 → 444, `seq` contiguous 1–444, and events 1090 → 1128. Only grew.
- **Nothing sent:** `sendMessage` 2 → 2, `api.telegram.org` 200s 2 → 2.
- **Host:** same `boot_id`.
- **Reader at `PLANNED`:**
  - `unrelated_digest` `feae96f887742dafc334cb3c1747300f471ff778d3869e34bde6458e90879497`;
  - **`ef_digest` `4819055dc6c5a530b2dde4c35448c613a2e70a8ddd2520c3a8d842e286ade795`**;
  - attribution `0/0/0/0`.

The restore's own inline provisioning wrote audit rows 433–443 as
`SYSTEM:ef6428bb042b:411:364568cd`. That is the `pp restore-demo-world` process's own id inside
the worker container, not the worker daemon, and it is the same shape R1 recorded.

## 7. Step 2 — the worker stopped, and proved stopped

**Before the stop** (`19:50:07Z`):

- worker container `ef6428bb042b`, `running`, `StartedAt` `19:19:02.362Z`, `RestartCount` 0;
- instance `ef6428bb042b:1:4ccc1ebc`;
- `pp worker` present in the host's process table once.

**The stop**, `19:50:07.433Z`, by `docker compose --env-file env/stack.env stop worker`. Exit `0`,
returned at `19:50:08.178Z`. Only the worker was touched.

```text
{"worker": "ef6428bb042b:1:4ccc1ebc", "event": "worker.stop", "level": "info", "timestamp": "2026-09-24T19:50:07.559069Z"}
```

**Stop proof**, all taken before the confirmation:

| | measured |
|---|---|
| container state | `exited`, `Running=false`, `Pid 0`, `FinishedAt` `19:50:07.887Z`, exit 0 |
| `docker ps` running worker containers | 0 |
| `compose ps worker` | `exited`, `Exited (0)` |
| `docker top worker` | refused (not running) |
| host processes running `pp worker` | **1 → 0** |
| worker log after the stop | exactly one line, the `worker.stop` above |
| every other container | `StartedAt` unchanged |

## 8. Step 3 — the confirmation while no worker runs

**Immediately before** the confirmation, a census run in `api` was identical to the `PLANNED`
checkpoint. The case was still `PLANNED` v7 and the timer unfired.

The confirmation, `pp confirm-plan --worker maya` in **`api`**, ran on the operator console at
`19:50:09.443Z` → `19:50:11.819Z`, with command id `c77a96be-…`. The worker was still stopped
when it returned (`running=false`).

```text
plan.approval.recorded   case_id=75dd110e-… channel=OPERATOR_CONSOLE worker=maya
recovery.plan.confirmed  applying=1 awaiting_approval=1 case_id=75dd110e-… escalated=2 worker=maya
state:     EXECUTING
accepted:  now
applying:  1
escalated: 2
awaiting approval: 1
confirm_exit=0
```

**The durable state it left, while stopped (snapshot A, `19:50:12Z`):**

| requirement | measured |
|---|---|
| exactly one plan approval, durable | `plan_approvals` **1**: `channel=OPERATOR_CONSOLE`, `by=maya`, plan `c9cae006…`, at `19:50:11.378Z` |
| human authority in the ledger | audit 445 `PLAN_APPROVED` and 446 `PLAN_CONFIRMED`, both **`HUMAN_APPROVAL`**, actor `WORKER:maya` |
| case and plan state persisted | case `EXECUTING` v8, owner attention set; `pr-c`/`pr-d` `ESCALATED` with `task-ol-c`/`task-ol-d` `HELD`; `task-ol-e` still `STARTED`, **not held**; `PLAN_AUTO_ESCALATION` timer **cancelled** (timers 0) in the same transaction |
| the work queued, not done | steps `APPLY_RECOVERY` (`pr-a`) and `REQUEST_APPROVAL` (`pr-b`) **`PENDING` at `attempts=0`, no lease**; `CONFIRM_PLAN` `DONE` inline at 0 |
| no worker processing | `pr-a` and `pr-b` still `PENDING`; no `WORKFLOW_STEP_EXECUTED` row after 446; events stop at 1134 (`case.execution_confirmed`, two `track.escalated`) |
| no Telegram send | outbox **0**, requests 0; `sendMessage` 2 → 2, `api.telegram.org` 200s 2 → 2, `getUpdates` 0 |
| no `ORDER_AMEND` delivered | outbox 0; `EXT-A` and `EXT-B` at v1 `ACCEPTED`, mirror and store |
| no duplicate workflow or effect | exactly one case, one `CONFIRM_PLAN`, one step per queued track |

**The stopped hold.** Snapshot B was taken 60 s after A, at `19:51:18Z`. The diff of A against B,
excluding only `db_now`, is **empty**:

- case, tracks, steps, attempts and leases;
- counts, outbox, requests and plan approvals;
- orders, tasks, lines and customers;
- the audit and domain-event rows.

The worker was still stopped, with its `StartedAt` unmoved. Its log gained no line. Nothing on the
host processed the queued work while no worker ran; that includes `api`, which holds the same code.

**Reader, `CONFIRMED` while stopped:**

- `unrelated_digest` **`9f7b29a05bf375b62dd7a800bd7dba609f47a5ab382c53df75d4860c0fae593c`**;
- `ef_digest` `4819055d…`, unchanged since `PLANNED`;
- attribution `0/0/0/0`.

The change since `PLANNED` is in two components only, `tasks` and `tracks`, and it is the
protocol's own `CONFIRMED` work: `pr-c`/`pr-d` escalated and their tasks held. Every other
component digest is unchanged.

## 9. Step 4 — the worker started; the new instance consumes the confirmation once (`CONFIRMED`)

**Before the start** (`19:51:58Z`), the gate re-checked:

- the worker `exited`;
- both steps still `PENDING` at `attempts=0`;
- counts unchanged.

**The start**, `19:52:00.591Z`, by `docker compose --env-file env/stack.env start worker`. Exit
`0`, returned at `19:52:03.595Z`.

```text
{"action": "PRESENT", "case_id": "75dd110e-9313-55c6-9926-773ce333881d", "state": null, "detail": "this world's case already exists; nothing was touched", "rolled": false, "event": "worker.demo_case", "level": "info", "timestamp": "2026-09-24T19:52:05.510408Z"}
{"worker": "ef6428bb042b:1:9190c196", "event": "worker.start", "level": "info", "timestamp": "2026-09-24T19:52:05.510543Z"}
```

- **The worker:** `StartedAt` moved to `19:52:03.581Z`. The new instance id is
  **`ef6428bb042b:1:9190c196`**. The container is the same, and `RestartCount` stays 0.
- **Other containers:** every other long-running container kept its `StartedAt`.
- **Errors:** none. There were 0 error-level lines from the stop to the end of the rehearsal.

The queued work ran within 1.1 s of `worker.start`, in the new instance's first cycles. Nothing
was sent by hand.

| predeclared | measured |
|---|---|
| `plan_approvals` 1, `OPERATOR_CONSOLE` | **1**, unchanged by the start |
| `PLAN_APPROVED`, `PLAN_CONFIRMED` `HUMAN_APPROVAL`, `WORKER maya` | audit 445 and 446, written by the confirmation in `api` before the start |
| `pr-a` applied under `CONSTRAINT` | `APPLY_RECOVERY` `COMPLETED` at **attempt 1**; audit 447 `RECOVERY_APPLIED` `CONSTRAINT` `R-PREAPPROVED`; one `ORDER_AMEND` `DELIVERED` **attempt 1**, key `pp:amend:91e62dca-…:7396bdbf-…:1`, `provider_ref` `amd-417b5bda06c0`, `replayed False`; `EXT-A` v1 → v2 `AMENDED` `almond-4`; audit 451 `ORDER_MIRROR_UPDATED`; `FINALIZE_RECOVERY` attempt 1; audit 452 `RECOVERY_COMPLETED`; `pr-a` `RECOVERED` |
| `pr-b` `WAITING_FOR_CUSTOMER`, one request `SENT` | `REQUEST_APPROVAL` `COMPLETED` at **attempt 1**; request `ca815675-4693-5ad7-8886-2aead249f0fd` `OPT-2CC16D`, `SENT` `19:52:06.545Z`, deadline `2026-09-25T00:49:54Z`; `APPROVAL_DEADLINE` timer armed |
| one `MESSAGE_SEND` `DELIVERED` at attempt 1 | `DELIVERED` **attempt 1**, key `pp:approval:ca815675-…`, `provider_ref` `telegram:<id>:8` persisted |
| `sendMessage` +1 | `sendMessage` 2 → **3**, `worker.telegram.sent` 2 → 3, `api.telegram.org` 200s 2 → **3** (HTTP 200), non-200 **0**, `getUpdates` **0** |
| `pr-c`/`pr-d` `ESCALATED`, tasks `HELD` | both `ESCALATED`; `task-ol-c` and `task-ol-d` `HELD` |
| `task-ol-e` `STARTED`, never held; case `WAITING` | `task-ol-e` `STARTED`, not held; case `WAITING` v12 |

**Consumed exactly once, and by the new instance:**

- **Steps:** each of `APPLY_RECOVERY`, `REQUEST_APPROVAL`, `FINALIZE_RECOVERY` and
  `MARK_APPROVAL_SENT` ran at attempt 1.
- **Audit rows 447–455:** every one is `SYSTEM:ef6428bb042b:1:9190c196`. None carries the old
  instance id, `api`, or a foreign worker.
- **Outbox:** exactly 2 rows with 2 distinct keys, 0 unsettled.

**Reader, `CONFIRMED` after the start:**

- `unrelated_digest` `9f7b29a0…`, **equal to the stopped `CONFIRMED` reading**, in every component;
- `ef_digest` `4819055d…`;
- attribution `0/0/0/0`.

**The approval link** was never seen by the session. It is fingerprinted inside the container as
sha256 `475b0077…`. It occurred 0 times, whole, as payload or as signature, in any of the five
container logs.

**One recorded observation: `start worker` re-ran `migrate`.**

- **What happened:** the compose file declares the worker `depends_on: migrate` with
  `condition: service_completed_successfully`. So `docker compose start worker` also started the
  exited one-shot `migrate` container, at `19:52:01.143Z` → `19:52:02.986Z`, exit 0.
- **What it did:** it ran its fixed command, `alembic -c apps/backend/alembic.ini upgrade head`,
  against a database already at head. It logged only the two alembic context lines and no
  `Running upgrade` line.
- **What it did not do:** it wrote no audit or domain-event row, sent nothing, and moved no
  fixture. `/readyz` still reports head `0009_human_plan_approval`.
- **Why R1 never saw it:** R1's `restart worker` does not start dependencies, so R1 never showed
  this.
- **Classification:** it is part of the documented `stop` … `start` mechanism that §3.2 names,
  not an addition to it, and it is not a deviation. R3 uses the same mechanism and will show it
  again.

## 10. The customer's answer (`CONSENT_SETTLED` → `SETTLED`)

The owner opened the signed link from the one message on the phone and pressed APPROVE. A
read-only watch saw the request go `SENT` → `ANSWERED` between `19:54:04Z` and `19:54:20Z`, and
the case `RESOLVED` at `19:54:35Z`.

| predeclared | measured |
|---|---|
| one `approval_decisions` row: `APPROVE`, `LITERAL`, sender = the request's channel | `f165e76b-…`: `APPROVE`, parser `LITERAL`, raw text `yes` (the literal the web answer submits), `sender_matches_channel=True`, received `19:54:18.509Z` |
| one `inbound_replies` row; `customer-reply` inbox `PROCESSED` | reply `19f6737f-…` received `19:54:17.642Z`; inbox `customer-reply` `PROCESSED` at `19:54:18.466Z` |
| `APPROVAL_DECISION_RECORDED` by `CUSTOMER cus-tomas`, `HUMAN_APPROVAL` | audit 456, `CUSTOMER:cus-tomas`, `HUMAN_APPROVAL`; request `ANSWERED`, `decided=true` |
| **ten `REVALIDATION_CHECK` rows, all passed, fresh snapshot, after the decision** | audit 458–467, **10/10 passed**, snapshot instant `19:54:18.620195Z`, **112 ms after** the decision's `19:54:18.508668Z`; `revalidation.passed as_of 1168`, a domain-event position after the decision's |
| `RECOVERY_REVALIDATED`, `RECOVERY_APPLIED`, `RECOVERY_COMPLETED`, all `HUMAN_APPROVAL` | audit 468 (`outcome PROCEED`, `checks_passed 10`, case `RECONCILING`), 470 and 474, all **`HUMAN_APPROVAL`** `R-VISIBLE-ASK` |
| one `ORDER_AMEND`: `EXT-B` v1 → v2 `AMENDED` `rose-3`, claimed at `attempts == 1` while the production start is ahead | one `ORDER_AMEND` `DELIVERED` attempt 1, key `pp:amend:ea15d346-…:2cc16dbc-…:1`, `provider_ref` `amd-e4e69c87c303`, `replayed False`; check 6 read `SCHEDULED and start 2026-09-25T01:49:54Z`, ahead of `19:54:18Z` |
| the order system's store equal to the mirror (`ORDER_MIRROR_UPDATED`) | audit 473 `ORDER_MIRROR_UPDATED` `EXT-B` v2 `ol-b → rose-3`, from the order system's own event (`disposition APPLY`); store read directly: `EXT-A v2 AMENDED almond-4`, `EXT-B v2 AMENDED rose-3`, `EXT-C`…`EXT-F` v1 `ACCEPTED`, equal to the mirror |
| `pr-b` `RECOVERED`; case `RESOLVED`; `plan_approvals` **still 1** | `pr-b` `RECOVERED`; case `RESOLVED` v17; `plan_approvals` **1** |

The ten checks, as `pp case-status` prints them. All ten passed.

1. **Waiting.** The track and case are waiting: `track=WAITING_FOR_CUSTOMER case=WAITING`.
2. **Order.** The order state and version are unchanged: `ACCEPTED @ v1`.
3. **Pinned version.** The pinned recipe version is unchanged: `rv-raspberry-rose-2`.
4. **Constraints.** The constraint snapshot is unchanged: `53e025fc…` = `53e025fc…`.
5. **Substitute.** The substitute is still available: `3.200 ≥ 2.200`.
6. **Production task.** The task has not started and its start is ahead: `SCHEDULED`, start
   `2026-09-25T01:49:54Z`.
7. **Deadline.** The approval deadline has not passed: `19:54:18Z ≤ 2026-09-25T00:49:54Z`.
8. **Sender.** The sender is the order's approval channel (masked).
9. **Parser.** The decision came from the literal parser: `LITERAL`.
10. **Decision.** There is one unspent decision, bound to this plan: 1 decision for `ca815675-…`,
    option `2cc16dbc-…`.

**Human authority is preserved through completion:**

- the plan's authority is `HUMAN_APPROVAL` from `WORKER:maya` (audit 445 and 446);
- the customer's is `HUMAN_APPROVAL` from `CUSTOMER:cus-tomas` (audit 456);
- `pr-b`'s revalidation, application and completion (audit 468, 470 and 474) all carry
  `HUMAN_APPROVAL`;
- `pr-a`'s work is `CONSTRAINT`, as §3.1 requires.

**Every step after the restart point ran on the new instance:**

- `APPLY_RECOVERY`, `REQUEST_APPROVAL`, `FINALIZE_RECOVERY` and `MARK_APPROVAL_SENT` for the
  confirmation;
- `RECEIVE_CUSTOMER_REPLY`, `REVALIDATE_RECOVERY`, `APPLY_RECOVERY`, `RECONCILE_CASE` (`SKIPPED`)
  and `FINALIZE_RECOVERY` for the answer;
- both mirror processings;
- audit rows 447–475, each `SYSTEM:ef6428bb042b:1:9190c196`.

The worker log since the start names that one instance id and no other.

**Workflow retries, recorded apart from external effects:**

| layer | retries |
|---|---|
| external effects (outbox) | **none**: 3 rows, each `DELIVERED` at attempt 1 |
| Telegram | **one** `sendMessage`, HTTP 200, no retry |
| workflow steps | **one**: `FINALIZE_RECOVERY` for `pr-b` returned `RETRY_SCHEDULED` on attempt 1 at `19:54:19.263Z`, because the order system's echo was mirrored only at `.324Z`; attempt 2 `COMPLETED` at `19:54:20.444Z` |

That one step retry is the finalizer running ahead of the echo. It was recorded identically in R1
§9 and in [phase7-deployed-behavioral-proof.md](phase7-deployed-behavioral-proof.md). It is an
internal re-read and not an external duplicate: `EXT-B` has one amendment, one idempotency key and
one provider reference. It happened 2 min 14 s after the start, inside the new instance's
post-answer work. The start itself added no step retry: every step it consumed ran at attempt 1.

## 11. Exactly-once, untouched, privacy

**Exactly-once**, at the end:

- **Outbox:** exactly **3** rows, `ORDER_AMEND` ×2 and `MESSAGE_SEND` ×1. All `DELIVERED`, all
  at attempt 1, **3 distinct keys**. `EXT-B` has **one** logical amendment, key
  `pp:amend:ea15d346-…:2cc16dbc-…:1`.
- **Messages:** `sendMessage` exactly **+1** over the rehearsal (2 → 3), `api.telegram.org` 200s
  +1, non-200 0, **`getUpdates` 0**. The owner saw exactly one message.
- **Consent rows:** 1 request, 1 decision, 1 reply.
- **Plan approvals:** exactly one plan approval.
- **Cases:** exactly one.
- **The stop and start** added no effect, no step retry, no case and no plan approval. The only
  thing the start caused beyond the queued work was the no-op `migrate` run in §9.

**Untouched**, by the frozen reader:

| | `PLANNED` | `CONFIRMED` (stopped) | `CONFIRMED` (after start) | `SETTLED` |
|---|---|---|---|---|
| `unrelated_digest` | `feae96f8…` | **`9f7b29a0…`** | `9f7b29a0…` | **`9f7b29a0…`** |
| `ef_digest` | **`4819055d…`** | `4819055d…` | `4819055d…` | **`4819055d…`** |
| attribution audit/events/outbox/requests | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |

- `unrelated_digest` is **equal between `CONFIRMED` and `SETTLED`**, and every component digest
  matches. It is also equal across the start.
- `ef_digest` is equal from `PLANNED` to `SETTLED`.
- `EXT-C`…`EXT-F` are at v1 `ACCEPTED` in the mirror and in the order system's store.
- `pr-e`/`pr-f` are `UNAFFECTED` from `PLANNED` to `SETTLED`, with nothing attributed to them.
- `task-ol-e` is still `STARTED` and was never held.

**Privacy.** Nothing in the session's output carried a chat id, token, password or link:

- every census masked the address in-process, and its leak guard read `False` each time;
- every reader run passed through an in-container leak check reading `address=0`,
  `chatid_pattern=0`, `token_shaped=0` and `bot_token=0`.

Container logs at `SETTLED`, per container:

| container | token-shaped | unredacted query / path | address | chat-id pattern | bot token | this link (whole / payload / signature) |
|---|---|---|---|---|---|---|
| `caddy` | 0 | 0 / 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| `api` | 0 | 0 / 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| `worker` | 0 | 0 / 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| `mcp` | 0 | 0 / 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| `order-simulator` | 0 | 0 / 0 | 0 | 0 | 0 | 0 / 0 / 0 |

CloudWatch `/promisepatch/prod` since `19:47Z`, read from the operator machine:

- 165 events across 5 streams;
- **0** token-shaped strings, **0** chat-id patterns, **0** bot-token-shaped strings;
- **0** unredacted query or path forms (`approve=REDACTED` 2, `approval/REDACTED` 8);
- this rehearsal's link fingerprint absent.

## 12. Health, at the end

| | state |
|---|---|
| Host | `boot_id` `109dccdf-…` throughout: **no reboot** |
| Containers | all on `4529a802e34e` (`caddy` on `caddy:2.10-alpine`), 0 restarts. Only the worker's `StartedAt` moved, by the one stop/start. `migrate` re-ran once and exited 0 (§9) |
| `/healthz` / `/readyz` | `4529a802e34e`; ready, migrations at head, fixture anchor `19:49:54Z` |
| Files and certificate | `converge.sh` `09105b10…` and `channel.env` `c3a6e4de…` unchanged; certificate and key dated `2026-09-13 18:35`; the three Docker volumes present |
| Order simulator | `200` |
| Control plane | read at `19:55Z`, identical to entry: stack `UPDATE_COMPLETE` at `16:00:45Z`, 0 change sets; SSM `image-tag` v9, `compose` v14, `caddyfile` v13; instance, AMI, launch time, volume and RDS unchanged |

Smoke was not run. The known port-80 self-hairpin limitation applies unchanged.

The deployed world is left `RESOLVED` and pinned by its own effects, with nothing in flight and
nothing waiting on a person. Its `APPROVAL_DEADLINE` timer, due `00:49:54Z`, is for an answered
request.

## 13. What this does not prove

- **R2 is one rehearsal.** R3–R5 are unrun: a worker stopped across the answer, a restart after
  settlement, and a repeat of R1.
- **The stopped window was 1 min 56 s**: container `FinishedAt` `19:50:07.887Z` → `StartedAt`
  `19:52:03.581Z`. The confirmation committed 3.5 s into it. No timer was due in
  that window: the `PLAN_AUTO_ESCALATION` timer was cancelled by the confirmation itself. So R2
  proves that queued steps wait for and are taken by the next worker. It does not prove that a
  timer falling due while no worker runs fires late and exactly once.
- **The confirmation ran through the operator console only.** The browser session and MCP paths
  to a confirmation were not exercised with the worker down.
- No refusal path was exercised: `STALE`, `EXPIRED`, `UNAUTHORIZED`, `NOOP`, and any restore
  refusal.
- The `FINALIZE_RECOVERY` retry-ahead-of-echo is recorded, not changed.

## 14. R3

**R3 can proceed without a code change.** Before it can run, it needs:

- the owner's authorisation for its restore, confirmation, message and stop/start;
- the reader in the appendix of [g8-rehearsal-r1.md](g8-rehearsal-r1.md), byte-identical
  (`c9731c8f…`);
- the census run in `api` while no worker runs.

Expect `start worker` to re-run the no-op `migrate` again.
