# G8 deployed rehearsal R3 — the customer answers while no worker runs

Date: **2026-09-24**, host work between `20:24Z` and `20:32Z`. Entry at
`48cf10407c57e6211624e59face52f8885094eab`: `main` equal to `origin/main`, tracked tree clean, and
the eleven known untracked artefacts left as they were. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`.

This is rehearsal #3 of the five that [g8-rehearsal-preparation.md](g8-rehearsal-preparation.md)
§3 predeclared, run against the frozen release candidate `4529a802e34e`
([phase7-closeout.md](phase7-closeout.md)). R3's restart point is **across the customer's
answer**:

1. restore, confirm and deliver, as in R1;
2. once the case waits for the customer, `stop worker`;
3. the owner presses APPROVE on the signed link while no worker runs;
4. `start worker`.

It was judged against §3.1 and **R3's corrected row in §10.2** of that document, written before
any R3 spend. It was not judged against the superseded §3.2 expectation that a decision exists
while the worker is down. Nothing was redefined here.

## 1. Verdict

**R3: PASS.** Every §3.1 checkpoint, exactly-once, untouched, privacy and restart item holds, and so
does every §10.2 requirement:

- **While no worker ran**, the answer existed only as one durable `customer-reply` inbox row
  (`RECEIVED`). There was no reply, no decision, no authority row and no effect. Two snapshots
  65 s apart were identical.
- **After the start**, the new worker instance took that row exactly once. It wrote exactly one
  reply and one decision, and the request moved to `ANSWERED` under `HUMAN_APPROVAL`. The ten
  revalidation checks passed and gave `PROCEED`. `EXT-B` received one amendment, the mirror
  converged, `pr-b` ended `RECOVERED` and the case `RESOLVED`.

This counts as **3 of 5** on image `4529a802e34e`, after R1 ([g8-rehearsal-r1.md](g8-rehearsal-r1.md))
and R2 ([g8-rehearsal-r2.md](g8-rehearsal-r2.md)). No product code, test, deployment file,
infrastructure, IAM, SSM parameter or release was changed.

## 2. Authorisation, and what was spent

The owner authorised exactly:

- one guarded demo restore;
- one plan confirmation;
- one real Telegram approval message;
- stopping the worker only;
- the owner's own APPROVE while the worker was stopped;
- starting the worker again.

**Each was used once.** The press was the owner's own action on the phone. The owner opened the
signed link from the one message, pressed APPROVE once and reported:

> "i pressed approve once and got no message just thank you we have your answer at the top"

That is the web answer's acknowledgement, which confirms the answer was stored and nothing more. No
further Telegram message is expected, and none was sent. Nothing in the session opened, followed,
simulated or wrote that answer.

**Access and privacy.** Host access was `ssm:StartSession` with `AWS-StartNonInteractiveCommand`
alone. Every census ran in a read-only transaction. Nothing printed in this session carried a chat
id, a bot token, a password or the approval link.

## 3. The frozen evidence reader

- **Extraction:** the reader was extracted from the appendix of
  [g8-rehearsal-r1.md](g8-rehearsal-r1.md) at `HEAD` by the recorded
  `awk '/^```python$/{f=1;next} /^```$/{if(f){exit}} f'`.
- **Hash:** sha256 **`c9731c8f8dedfe15fbc6af0c2db6a8d5d19ca090d7863f3d2e945b18220b0dd4`**. The
  extraction is byte-identical to R2's copy, compared with `cmp`.
- **On the host:** the host printed the same sha256 before each of the six reads.
- **Edits:** never edited.

While the worker was down, the reader ran in `api`, which is the same image with the same env
files.

## 4. Timeline

| UTC | event |
|---|---|
| `20:24:12` | entry census: R2's case `75dd110e-…` `RESOLVED`, outbox 3 all `DELIVERED`, **0 `PENDING`/`IN_FLIGHT`**, one customer bound, worker `sendMessage` lifetime 3 |
| `20:26:52.888` → `20:26:57.695` | **restore** (the one) |
| `20:27:06.932` → `20:27:09.308` | **plan confirmation** in `worker` (the one), 12 s after planning |
| `20:27:10.420` | the one `MESSAGE_SEND` delivered; request `SENT` `20:27:10.602` |
| `20:27:23.201` | **worker stop** issued (the one); `worker.stop` `20:27:23.297`, container `FinishedAt` `20:27:23.607` |
| `20:28:31.492` | the owner's APPROVE stored as one `customer-reply` inbox row, `RECEIVED` |
| `20:29:02` → `20:30:13` | offline snapshots A and B, 65 s apart, identical |
| `20:30:55.722` | **worker start** issued (the one); `StartedAt` `20:30:58.991`, `worker.start` `20:31:00.940` |
| `20:31:00.972` → `20:31:03.064` | the new instance consumes the answer; case `RESOLVED` |
| `20:31:10` → `20:32` | settled evidence, CloudWatch scan, control plane |

- **The stopped window** was 3 min 35.4 s, from container `FinishedAt` `20:27:23.607` to
  `StartedAt` `20:30:58.991`.
- **The press** landed 67.9 s into that window.
- **The stored answer** waited 2 min 29.5 s for a worker.
- **The approval window** closes `2026-09-25T01:26:54Z`. The deadline check ran at `20:31:01Z`,
  about five hours inside it.
- **The finish** came well before the `22:00Z` bound.

## 5. Entry

| | measured |
|---|---|
| Stack | `promisepatch-prod` `UPDATE_COMPLETE`, last updated `16:00:45Z`, **0 change sets** |
| Image | `ImageTag`, `DeclaredImageTag` and SSM `image-tag` (v9) all `4529a802e34e`; SSM `compose` v14 and `caddyfile` v13 byte-equal to HEAD |
| Instance / volume / RDS | `i-087c742587f83d61d` `t4g.small` `ami-0fa4996c14e7d501e`, launched `2026-09-18T10:19:33Z`, IMDSv2 required, hop limit 2 / `vol-0f330aaa62e637ef6` encrypted / `db-U2JWQBTINX6W6GAB56EOTHOCSM` private, encrypted |
| Host | `boot_id` `109dccdf-b7fb-4882-8b28-c963b2f0f7b9`, up since `16:02:33` |
| Containers | all on `4529a802e34e` (`caddy:2.10-alpine`), 0 restarts; worker `ef6428bb042b`, instance `…:1:9190c196` (R2's post-start instance) |
| `/readyz` | ready; migrations at head `0009_human_plan_approval` |
| Provider | `telegram` in `api` and `worker`, bot token present (value not read) |
| Effects | **0 `PENDING`/`IN_FLIGHT`**; nothing waiting on a person |
| Binding | `cus-tomas` bound (address length 10), the other five at 4-character placeholders |
| Counters | worker `sendMessage` 3, `api.telegram.org` 200s 3, non-200 0, `getUpdates` 0 |
| Files | `converge.sh` `09105b10…`, `env/channel.env` `c3a6e4de…` |
| Logs | 0 token-shaped, 0 unredacted, 0 address and 0 chat-id lines in all five containers |

## 6. Restore, confirmation and delivery (`PLANNED` → `CONFIRMED`)

**The env union** was read on the host from `env/migrate.env`, passed with `exec -e` into
`worker`, then unset. No value was printed.

- **(a) Settings preflight:** all four `require_*` `ok`, `allow_fixture_reset=True`,
  `demo_session_enabled=True`, `provider=telegram`, giving `preflight=ok`.
- **(b) Dry run:** exit `0`, `binding: restored (would be carried across)`, `nothing was written`.
- **(c) Gate:** `restore_gate=ok`.

```text
action:   restored
before:   fixture=hollow-oak cases=1 live=0 outbox=3 unsettled=0 requests=1 decisions=1 approvals=1 replies=1 audit=475 events=595 bound=True
after:    fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=489 events=614 bound=True
anchor:   2026-09-24T20:26:54.718612+00:00
digest:   fcccc3707266a53b3d068af682716cd6d602d23fe0c04694fd8abbf13bd7df00
rows:     160
orders:   6 reset in the external order system
case:     7654d9d7-f535-57f5-839a-6764aee63bf3
state:    PLANNED
binding:  restored
ledgers:  grew only
result:   restored; no plan was confirmed and no message was sent
restore_exit=0
```

**The `PLANNED` checkpoint** (`partition_gate=ok`):

- **Partition:**
  - `pr-a` `AUTO_RECOVERABLE` `R-PREAPPROVED`;
  - **`pr-b` `APPROVAL_REQUIRED` `R-VISIBLE-ASK` `rose-2 → rose-3`, the only approval-required
    option**;
  - `pr-c` `BLOCKED` `R-NOSUB` (`NOSUB_CONSTRAINT`) and `pr-d` `BLOCKED` `R-NOSUB`
    (`NO_PREAUTHORED_VARIANT`);
  - `pr-e` and `pr-f` `UNAFFECTED` `R-UNREACH`.
- **Case:** `PLANNED` v7, plan `302b0932…`, one unfired `PLAN_AUTO_ESCALATION` timer.
- **Counters:** outbox, requests, decisions, `plan_approvals`, replies and inbox all 0.
- **Orders:** all six at v1.
- **Binding:** `_verify_destination` (a `getChat`, no message) gave
  `returned_id_matches_stored=True` and `chat_type=private`. The address is absent from
  `GET /api/cases` and `GET /api/cases/{id}` (12 414 bytes), and neither body has a
  `provider_ref` or `sender_identity` key.
- **Ledgers:** audit 475 → 489 (`seq` contiguous) and events 1190 → 1228. Only grew.
- **Nothing sent:** `sendMessage` 3 → 3.
- **Host:** same `boot_id`.
- **Reader at `PLANNED`:**
  - `unrelated_digest` `0c94965b…`;
  - **`ef_digest` `a0290acc96c0fc82366adc906681cb4d122179ea015b7f5ee3628a7e191fd7a0`**;
  - attribution `0/0/0/0`.

**The confirmation**, `pp confirm-plan --worker maya` in `worker`, command `85b703fe-…`:

- **Result:** `EXECUTING`, `applying 1`, `escalated 2`, `awaiting approval 1`.
- **Ledger:** audit 490 `PLAN_APPROVED` and 491 `PLAN_CONFIRMED`, both **`HUMAN_APPROVAL`**, actor
  `WORKER:maya`.
- **Plan approvals:** exactly one, `channel=OPERATOR_CONSOLE`.

**Delivery.** The running worker `…:1:9190c196` dispatched within 3 s, every step at attempt 1:

- **`pr-a`:** one `ORDER_AMEND` `DELIVERED` attempt 1 `amd-35254182fb63`; `EXT-A` v2 `almond-4`;
  `RECOVERED` under `CONSTRAINT`.
- **`pr-b`:** request `634b0a4e-d5db-54bd-8e5a-23b5cfdc51a7` `OPT-99FE4B`. One `MESSAGE_SEND`
  **`DELIVERED` at attempt 1**, key `pp:approval:634b0a4e-…`, `provider_ref` `telegram:<id>:9`
  persisted. `sendMessage` 3 → **4**, `api.telegram.org` **HTTP 200** 3 → 4, non-200 0,
  `getUpdates` 0.
- **`pr-c`/`pr-d`:** `ESCALATED`, with `task-ol-c`/`task-ol-d` `HELD`.
- **`task-ol-e`:** `STARTED`, never held.

**Reader at `CONFIRMED`:**

- `unrelated_digest` **`0eba6445cf4a29a01c965eb81536c1987764335c564789cde9d1c2dc5b4aa3da`**;
- `ef_digest` `a0290acc…`, unchanged;
- attribution `0/0/0/0`.

As in R2, the change since `PLANNED` is in `tasks` and `tracks` only. It is the protocol's own
escalation and hold of `pr-c`/`pr-d`.

## 7. The stop point

Before stopping, a gate required all of the following (`waiting_gate=ok`):

- case `WAITING`;
- 0 open steps, 0 failed steps and 0 unsettled effects;
- request `SENT` with a provider reference;
- `pr-b` `WAITING_FOR_CUSTOMER`;
- exactly one `MESSAGE_SEND` at attempt 1;
- `sendMessage` exactly 4.

**Before the stop:** worker container `ef6428bb042b` was `running`, `StartedAt`
`19:52:03.581Z`, instance `ef6428bb042b:1:9190c196`, with `pp worker` in the host process table
once.

**The stop**, `20:27:23.201Z`, by `docker compose --env-file env/stack.env stop worker`. Exit `0`,
returned at `20:27:23.842Z`.

```text
{"worker": "ef6428bb042b:1:9190c196", "event": "worker.stop", "level": "info", "timestamp": "2026-09-24T20:27:23.297222Z"}
```

| stop proof | measured |
|---|---|
| container state | `exited`, `running=false`, `pid 0`, `FinishedAt` `20:27:23.607Z`, exit 0 |
| `docker ps` running worker containers | 0 |
| `compose ps worker` | `exited`, `Exited (0)` |
| `docker top worker` | refused (not running) |
| host processes running `pp worker` | **1 → 0** |
| worker log after the stop | exactly one line, the `worker.stop` above |
| every other container | `StartedAt` unchanged |

**The stopped state, recorded before the press** (census in `api`, `20:27:25Z`):

| | measured |
|---|---|
| case | `7654d9d7-…` `WAITING` v12, owner attention set |
| tracks | `pr-a` `RECOVERED`; **`pr-b` `WAITING_FOR_CUSTOMER`**; `pr-c`/`pr-d` `ESCALATED`; `pr-e`/`pr-f` `UNAFFECTED` |
| request | `634b0a4e-…` **`SENT`**, `decided=False`, deadline `2026-09-25T01:26:54.718612Z` |
| timers / work | one `APPROVAL_DEADLINE` timer, due `01:26:54Z`, unclaimed and unfired; 11 steps, all `DONE` (`CONFIRM_PLAN` at 0, every other at 1); 0 open |
| outbox | 2 rows (`ORDER_AMEND` ×1 and `MESSAGE_SEND` ×1), both `DELIVERED` at attempt 1, 2 distinct keys, 0 unsettled |
| inbox | 1 row: the order system's `EXT-A` echo, `PROCESSED`; **no `customer-reply` row** |
| counts | requests 1, replies 0, decisions 0, `plan_approvals` 1; audit 500, events 1258 |
| orders | `EXT-A` v2 `AMENDED`; **`EXT-B` v1 `ACCEPTED` `rose-2`**; `EXT-C`…`EXT-F` v1 |
| reader | `unrelated_digest` `0eba6445…` = `CONFIRMED`; `ef_digest` `a0290acc…`; attribution 0/0/0/0 |
| worker identity | last instance `ef6428bb042b:1:9190c196`, stopped |

## 8. The owner's offline answer, and the state it left (§10.2)

After the stop, the session handed over to the owner and wrote nothing. A read-only watch in `api`
saw the owner's press land as a `customer-reply` inbox row at `20:28:31.492Z`. Five seconds later
it took snapshot A, and 65 s after A it took snapshot B. The worker was still stopped and 0
`pp worker` processes ran throughout.

| §10.2 requirement | snapshot A (`20:29:03Z`) and B (`20:30:13Z`) |
|---|---|
| exactly one `customer-reply` inbox row, `RECEIVED`, for this request's link message id | **one** row, `RECEIVED` `20:28:31.491719Z`, `processed=None`, `error=None`; `provider_event_id == link_message_id(request, channel)` **`True`** (compared in-container, not printed) |
| `inbound_replies` 0, `approval_decisions` 0 | **0** and **0** |
| request `SENT`, `decided=false`; track `WAITING_FOR_CUSTOMER`; case `WAITING` | `SENT`, `decided=False`; `pr-b` `WAITING_FOR_CUSTOMER`; case `WAITING` v12 |
| no `APPROVAL_DECISION_RECORDED`, no `REVALIDATION_CHECK`, so no `HUMAN_APPROVAL` row for the answer | audit `max` still **500**, events still **1258**: the ledger gained no row at all |
| no `RECOVERY_*`, no new outbox row | outbox still 2, 0 unsettled; steps still 11, all terminal |
| `EXT-B` still v1, mirror and order system | mirror `EXT-B` v1 `ACCEPTED` `rose-2` |
| `sendMessage` unchanged, `getUpdates` 0 | `sendMessage` **4**, 200s 4, non-200 0, `getUpdates` **0** |
| no re-anchor | fixture anchor `20:26:54.718612Z`, unchanged; `reanchor` 0 |
| unrelated digest equal to `CONFIRMED` | **`0eba6445…`**, every component equal; `ef_digest` `a0290acc…`; attribution 0/0/0/0 |
| two read-only snapshots ≥ 60 s apart, equal except `db_now` | diff of A against B: **empty** |

The worker log gained no line after `worker.stop`, and the logs held no token, address or link
material (§11).

## 9. The start, and the new instance consuming the answer once

**Before the start** (`20:30:54Z`), a gate re-checked that the worker was `exited` and that the
state was still inbox `RECEIVED`, request `SENT`, decisions 0, replies 0, case `WAITING`, 0 open
steps and 0 unsettled.

**The start**, `20:30:55.722Z`, by `docker compose --env-file env/stack.env start worker`, the
same mechanism as R2. Exit `0`, returned at `20:30:59.002Z`.

```text
{"action": "PRESENT", "case_id": "7654d9d7-f535-57f5-839a-6764aee63bf3", "state": null, "detail": "this world's case already exists; nothing was touched", "rolled": false, "event": "worker.demo_case", "level": "info", "timestamp": "2026-09-24T20:31:00.940202Z"}
{"worker": "ef6428bb042b:1:8593cc32", "event": "worker.start", "level": "info", "timestamp": "2026-09-24T20:31:00.940336Z"}
```

- **New instance: `ef6428bb042b:1:8593cc32`.** It is the same container, `StartedAt`
  `20:30:58.991Z`, `RestartCount` 0.
- **The start did not roll the world:** `worker.demo_case` reported `PRESENT` and
  `rolled: false`.
- **The expected `migrate` no-op recurred**, exactly as R2 §9 recorded. `depends_on:
  service_completed_successfully` started the exited `migrate` container at `20:30:56.167Z` →
  `20:30:58.206Z`, exit 0. It logged only the two alembic context lines and **0**
  `Running upgrade` lines. `/readyz` stays at head.
- **Errors:** 0 error-level lines from the stop to the end.

**The consumption path**, from the new instance's own log and the audit ledger:

| step | measured |
|---|---|
| inbox row taken once | `worker.inbox.processed` `customer-reply` → `PROCESSED` at `20:31:00.972Z`, by `…:8593cc32` |
| `RECEIVE_CUSTOMER_REPLY` once | attempt 1 `COMPLETED` `20:31:01.155Z` |
| one reply, one decision | reply `fa30b5f7-…` (its `received` keeps the stored `20:28:31.492Z`); decision `25c0be12-…` **`APPROVE`**, parser **`LITERAL`**, raw `yes`, **`sender_matches_channel=True`**, written `20:31:01.042Z` |
| request `ANSWERED`, `HUMAN_APPROVAL` | request `ANSWERED`, `decided=True`; audit 501 `APPROVAL_DECISION_RECORDED` **`CUSTOMER:cus-tomas` `HUMAN_APPROVAL`** |
| ten checks against a fresh snapshot | audit 503–512, **10/10 passed**, snapshot instant `20:31:01.207269Z`, after the decision; `revalidation.passed as_of 1268` |
| `PROCEED` | audit 513 `RECOVERY_REVALIDATED` `HUMAN_APPROVAL` `R-VISIBLE-ASK`, `outcome PROCEED`, `checks_passed 10`, case `RECONCILING` |
| one `EXT-B` amendment | audit 516 `RECOVERY_APPLIED` `HUMAN_APPROVAL`; one `ORDER_AMEND` `DELIVERED` **attempt 1**, key `pp:amend:26d51d4d-…:99fe4bd1-…:1`, `provider_ref` `amd-8db8fa393343`, `replayed False`; `EXT-B` `expected_version 1` → `external_version 2` |
| mirror converges | audit 518 `ORDER_MIRROR_UPDATED` `EXT-B` v2 `ol-b → rose-3` from the order system's own event (`disposition APPLY`); store read directly: `EXT-A v2 AMENDED almond-4`, `EXT-B v2 AMENDED rose-3`, `EXT-C`…`EXT-F` v1 `ACCEPTED`, equal to the mirror |
| `pr-b` `RECOVERED`, case `RESOLVED` | audit 519 `RECOVERY_COMPLETED` **`HUMAN_APPROVAL`**; `pr-b` `RECOVERED`; case `RESOLVED` v17 at `20:31:03.064Z`; `plan_approvals` **still 1** |

The ten checks, as `pp case-status` prints them. All ten passed.

1. **Waiting.** The track and case are waiting: `track=WAITING_FOR_CUSTOMER case=WAITING`.
2. **Order.** The order state and version are unchanged: `ACCEPTED @ v1`.
3. **Pinned version.** The pinned recipe version is unchanged: `rv-raspberry-rose-2`.
4. **Constraints.** The constraint snapshot is unchanged: `ee9962aa…` = `ee9962aa…`.
5. **Substitute.** The substitute is still available: `3.200 ≥ 2.200`.
6. **Production task.** The task has not started and its start is ahead: `SCHEDULED`, start
   `2026-09-25T02:26:54Z`.
7. **Deadline.** The approval deadline has not passed, judged at processing time:
   `20:31:01Z ≤ 2026-09-25T01:26:54Z`.
8. **Sender.** The sender is the order's approval channel (masked).
9. **Parser.** The decision came from the literal parser: `LITERAL`.
10. **Decision.** There is one unspent decision, bound to this plan: 1 decision for
    `634b0a4e-…`, option `99fe4bd1-…`.

**Every row after the start carries the new instance id:**

- audit 502–520 are all `SYSTEM:ef6428bb042b:1:8593cc32`, except 501, whose actor is the customer
  by design;
- no row carries the old instance `…:9190c196`, `api` or a foreign worker;
- the worker log since the start names that one instance id and no other.

**Human authority is preserved through completion:**

- the plan is `HUMAN_APPROVAL` from `WORKER:maya` (audit 490 and 491);
- the answer is `HUMAN_APPROVAL` from `CUSTOMER:cus-tomas` (audit 501);
- `pr-b`'s revalidation, application and completion (audit 513, 516 and 519) all carry
  `HUMAN_APPROVAL`;
- `pr-a` is `CONSTRAINT`, as §3.1 requires.

**Workflow retries, recorded apart from external effects:**

| layer | retries |
|---|---|
| external effects (outbox) | **none**: 3 rows, each `DELIVERED` at attempt 1 |
| Telegram | **one** `sendMessage`, HTTP 200, no retry; none after the stop |
| workflow steps | **one**: `FINALIZE_RECOVERY` for `pr-b` returned `RETRY_SCHEDULED` on attempt 1 at `20:31:01.882Z`, because the order system's echo was mirrored only at `.996Z`; attempt 2 `COMPLETED` at `20:31:03.138Z` |

That one retry is the finalizer running ahead of the echo, recorded identically in R1 §9 and
R2 §10. It is an internal re-read and not an external duplicate: `EXT-B` has one amendment, one
idempotency key and one provider reference. Every step the start consumed ran at attempt 1.

## 10. Exactly-once and untouched

**Exactly-once**, at the end:

- **Outbox:** exactly **3** rows, `ORDER_AMEND` ×2 and `MESSAGE_SEND` ×1. All `DELIVERED` at
  attempt 1, with **3 distinct keys**. `EXT-B` has **one** idempotency key,
  `pp:amend:26d51d4d-…:99fe4bd1-…:1`.
- **Messages:** `sendMessage` exactly **+1** over the rehearsal (3 → 4). `api.telegram.org` 200s
  also +1, non-200 0, **`getUpdates` 0**. The owner saw one message and the web page's
  acknowledgement, nothing more.
- **Consent rows:** 1 request, **1 reply, 1 decision**, and one inbox row for the answer, now
  `PROCESSED`.
- **Plan approvals:** exactly **one**.
- **Cases:** exactly **one**.
- **The stop and start:** they added no effect, no message, no decision, no case and no plan
  approval.

**Untouched**, by the frozen reader:

| | `PLANNED` | `CONFIRMED` | stopped, before press | offline, after press | `SETTLED` |
|---|---|---|---|---|---|
| `unrelated_digest` | `0c94965b…` | **`0eba6445…`** | `0eba6445…` | `0eba6445…` | **`0eba6445…`** |
| `ef_digest` | **`a0290acc…`** | `a0290acc…` | `a0290acc…` | `a0290acc…` | **`a0290acc…`** |
| attribution audit/events/outbox/requests | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |

- `unrelated_digest` is equal from `CONFIRMED` to `SETTLED` in every component, across the stop,
  the offline press and the start.
- `ef_digest` is equal from `PLANNED` to `SETTLED`.
- `EXT-C`…`EXT-F` are at v1 `ACCEPTED` in the mirror and in the order system's store.
- `pr-e`/`pr-f` are `UNAFFECTED` throughout, with nothing attributed to them.
- `task-ol-e` is still `STARTED` and was never held.

## 11. Privacy and health

**Privacy.** Nothing in the session's output carried a chat id, token, password or link:

- every census masked the address in-process, and its leak guard read `False` each time;
- every reader run passed an in-container leak check at `address=0`, `chatid_pattern=0`,
  `token_shaped=0` and `bot_token=0`.

Container logs at `SETTLED`: `caddy`, `api`, `worker`, `mcp` and `order-simulator` each show
0 token-shaped strings, 0 unredacted query or path forms, 0 addresses, 0 chat-id patterns and
0 bot tokens. This rehearsal's link (fingerprint sha256 `a3e612ef…`, taken inside the container)
occurs 0 times, whole, as payload or as signature.

CloudWatch `/promisepatch/prod` since `20:24Z`, read from the operator machine:

- 186 events across 5 streams;
- **0** token-shaped strings, **0** chat-id patterns, **0** bot-token-shaped strings;
- **0** unredacted query or path forms (`approve=REDACTED` 2, `approval/REDACTED` 44);
- this rehearsal's link fingerprint absent.

**Health, at the end.**

| | state |
|---|---|
| Host | `boot_id` `109dccdf-…` throughout: **no reboot** |
| Containers | all on `4529a802e34e` (`caddy:2.10-alpine`), 0 restarts. Only the worker's `StartedAt` moved, by the one stop/start. `migrate` re-ran once and exited 0 (§9) |
| `/healthz` / `/readyz` | `4529a802e34e`; ready, migrations at head `0009_human_plan_approval` |
| Files and certificate | `converge.sh` `09105b10…` and `channel.env` `c3a6e4de…` unchanged; certificate and key dated `2026-09-13 18:35`; the three Docker volumes present |
| Order simulator | `200` |
| Control plane | read after settlement, identical to entry: stack `UPDATE_COMPLETE` at `16:00:45Z`, 0 change sets; SSM `image-tag` v9, `compose` v14, `caddyfile` v13; instance, AMI, launch time, volume and RDS unchanged |

**Not run:** smoke was not run. The known port-80 self-hairpin limitation applies unchanged.

**Left behind:** the deployed world is left `RESOLVED`, pinned by its own effects, with nothing
in flight and nothing waiting on a person. Its `APPROVAL_DEADLINE` timer, due `01:26:54Z`, is for
an answered request.

## 12. What this does not prove

- **R3 is one rehearsal.** R4 and R5 are unrun: a restart after settlement, and a repeat of R1.
- **The approval arrived through the signed web link only.** No other answer transport was
  exercised, and Telegram inbound stays deliberately unbuilt.
- **No press was repeated while the worker was down.** The idempotent second-press property of
  `link_message_id` was not exercised live.
- **No refusal path was exercised:** `STALE`, `EXPIRED`, `UNAUTHORIZED`, `NOOP`, and any restore
  refusal. The deadline was judged at processing time, about five hours inside the window, so a
  late start that crosses the deadline is not proved here.
- **No timer fell due while no worker ran.** The only timer, `APPROVAL_DEADLINE`, was due hours
  later.
- **The `FINALIZE_RECOVERY` retry-ahead-of-echo is recorded, not changed.**

## 13. R4

**R4 can proceed without a code change.** Before it can run, it needs:

- the owner's fresh authorisation;
- the reader in the appendix of [g8-rehearsal-r1.md](g8-rehearsal-r1.md), byte-identical
  (`c9731c8f…`).

Expect `start worker`, if R4 uses it, to re-run the no-op `migrate` again.
