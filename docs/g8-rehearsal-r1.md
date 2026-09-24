# G8 deployed rehearsal R1 — restart while waiting for the customer

Date: **2026-09-24**, host work between `19:13Z` and `19:27Z`. Entry at
`9198f427428c1d0b2fbd9094521b96b8467b9eaa`: `main` equal to `origin/main`, tracked tree clean, and
the eleven known untracked artefacts left as they were. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`.

This is rehearsal #1 of the five that [g8-rehearsal-preparation.md](g8-rehearsal-preparation.md)
§3 predeclared, run against the frozen release candidate `4529a802e34e`
([phase7-closeout.md](phase7-closeout.md)). R1's restart point is **while the case waits for the
customer's answer** (`S16`). The pass/fail contract is §3.1 of that document, unchanged. It was
not redefined here.

## 1. Verdict

**R1: PASS.** Every checkpoint, exactly-once, untouched, privacy and restart item in §3.1 holds.
It counts as **1 of 5** on image `4529a802e34e`. No product code, test, deployment file,
infrastructure, IAM, SSM parameter or release was changed.

## 2. Authorisation, and what was spent

The owner authorised exactly:

- one guarded restore;
- one plan confirmation;
- one real Telegram approval message;
- one worker restart at the R1 checkpoint.

**Each was used once.** The customer's press was the owner's own action on the phone: the owner
opened the signed link from the one message and pressed APPROVE, and reported "approved, exactly
one message seen". Nothing in the session opened, followed, simulated or wrote that answer.

Host access was `ssm:StartSession` with `AWS-StartNonInteractiveCommand` alone. Every census ran
in a read-only transaction. Nothing printed in this session carried a chat id, a bot token, a
password or the approval link.

## 3. The frozen evidence reader

§3.1 step 2 requires one reader, fixed before rehearsal #1. The phase 7 reader (`ppev.py`) did not
satisfy it. Its digest excluded only `pr-b`/`EXT-B`, while the protocol excludes `pr-a`/`EXT-A`
as well, and it did not include the External Order System's own store. A new reader, `g8ev.py`,
was written for the protocol's scope. It was exercised read-only twice on the pre-rehearsal world,
at `19:13Z` and `19:16Z`, and produced byte-identical digests both times. It was then frozen.

| | |
|---|---|
| **sha256** | **`c9731c8f8dedfe15fbc6af0c2db6a8d5d19ca090d7863f3d2e945b18220b0dd4`** (LF line endings) |
| frozen at | `2026-09-24T19:16Z`, before the restore |
| verified on the host | the same sha256 printed by the host before every read |
| edited after R1 began | **never** |

It prints three things:

- `unrelated_digest`, over `ord-c`…`ord-f`: orders, lines, constraints, promises, tracks, tasks,
  reservations and customers, plus the order system's own store for those orders;
- `ef_digest`, the same over `ord-e`/`ord-f` only;
- four structural attribution counts for `pr-e`/`pr-f` since the fixture loaded. These are audit
  rows on their tracks, domain events whose `entity_refs` name any of their ids, outbox payloads
  naming them, and approval requests on their promises.

The reader is reproduced byte for byte in the appendix. R2–R5 must use exactly those bytes.

The shell wrapper around the reader was changed before R1, and only in how it displays results.
Its nine-digit mask had been mangling hex digests, so the reader's output now gets a hex-safe mask
plus an in-container leak check. The reader itself did not change.

## 4. Timeline

| UTC | event |
|---|---|
| `19:13:28` | entry census: case `87590614-…` `RESOLVED`, outbox 0, 0 `PENDING`/`IN_FLIGHT`, one customer bound, `sendMessage` lifetime 1 |
| `19:16` | reader frozen, `c9731c8f…` |
| `19:16:59` → `19:17:04.706` | **restore** (the one) |
| `19:17:14.139` → `19:17:16.439` | **plan confirmation** (the one), 10 s after planning |
| `19:17:17.323` | the one `MESSAGE_SEND` delivered; request `SENT` at `.512` |
| `19:18:58` | pre-restart snapshot |
| `19:19:01.308` | **worker restart** (the one) |
| `19:19:04.280` | new instance `worker.start` |
| `19:20:34` | post-restart snapshot, after 90 s of the new instance's cycles |
| `19:22:01` | read-only check: still `SENT`, 0 decisions |
| `19:24:53.648` | the owner's APPROVE arrives (`inbound_replies`) |
| `19:24:56.553` | `RECOVERY_COMPLETED`; case `RESOLVED` |
| `19:25:36` → `19:26:48` | settled evidence, CloudWatch scan, store and control plane |

It finished at `19:27Z`, well before the `22:00Z` bound. The approval window closed at
`2026-09-25T00:17:01Z`.

## 5. Entry (step 0)

| | measured |
|---|---|
| Stack | `promisepatch-prod` `UPDATE_COMPLETE`, last updated `16:00:45Z`, **0 change sets** |
| Image | `ImageTag`, `DeclaredImageTag` and SSM `image-tag` (v9) all `4529a802e34e`; SSM `compose` v14 and `caddyfile` v13 byte-equal to HEAD |
| Instance / volume / RDS | `i-087c742587f83d61d` `t4g.small` `ami-0fa4996c14e7d501e`, launched `2026-09-18T10:19:33Z`, IMDSv2 required, hop limit 2 / `vol-0f330aaa62e637ef6` encrypted / `db-U2JWQBTINX6W6GAB56EOTHOCSM` private, encrypted |
| Host | `boot_id` `109dccdf-b7fb-4882-8b28-c963b2f0f7b9`, up since `16:02:33` |
| Containers | `api`, `worker`, `mcp` and `migrate` on `backend:4529a802e34e`; `order-simulator` on `order-simulator:4529a802e34e`; `caddy:2.10-alpine`; 0 restarts |
| `/readyz` | ready; migrations at head `0009_human_plan_approval` |
| Provider | `telegram` in `api` and `worker`, bot token present (value not read) |
| Effects | outbox 0, **0 `PENDING`/`IN_FLIGHT`**; requests, decisions, `plan_approvals` and replies 0 |
| Binding | `cus-tomas` bound (address length 10), the other five at 4-character placeholders |
| Files | `converge.sh` `09105b10…`, `env/channel.env` `c3a6e4de…` |

## 6. Step 1 — guarded restore

The env union was read on the host from `env/migrate.env`, passed with `exec -e` and unset. No
value was printed.

- **(a) Settings preflight under the union:** all four `require_*` `ok`;
  `allow_fixture_reset=True`, `demo_session_enabled=True`, `provider=telegram`;
  `preflight=ok`.
- **(b) Dry run:** exit `0`.
- **(c) Dry-run content:** `binding: restored`, `unsettled=0`, `fixture=hollow-oak`.
  `restore_gate=ok`.

```text
action:   restored
before:   fixture=hollow-oak cases=1 live=0 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=385 events=495 bound=True
after:    fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=399 events=514 bound=True
anchor:   2026-09-24T19:17:01.628589+00:00
local:    2026-09-24T20:17:01.628589+01:00 Africa/Tunis
digest:   9f5b9bee1231dcae95ca6f9e959829da479180db5e3d0ec6b0607ebd2fcb725d
orders:   6 reset in the external order system
case:     e66069d7-fd57-580c-a780-f77b3d64ad20
state:    PLANNED
binding:  restored
ledgers:  grew only
restore_exit=0
```

**The `PLANNED` checkpoint**, gated automatically before the confirmation and confirmed by census:

- **Partition:**
  - `pr-a` `AUTO_RECOVERABLE` `R-PREAPPROVED` `almond-3 → -4`, no approval;
  - **`pr-b` `APPROVAL_REQUIRED` `R-VISIBLE-ASK` `rose-2 → rose-3`, the only approval-required
    option**;
  - `pr-c` `BLOCKED` `R-NOSUB` (`NOSUB_CONSTRAINT`) and `pr-d` `BLOCKED` `R-NOSUB`
    (`NO_PREAUTHORED_VARIANT`);
  - `pr-e` and `pr-f` `UNAFFECTED` `R-UNREACH`.
- **Case:** `e66069d7-…` `PLANNED` v7, the only case, with one unfired `PLAN_AUTO_ESCALATION` due
  `19:27:04Z`.
- **Counters:** outbox, requests, decisions, `plan_approvals`, replies and inbox all 0.
- **Orders:** all six at v1 in the mirror and in the order system.
- **Tasks:** `task-ol-e` `STARTED`, the other five `SCHEDULED`.
- **Binding:** exactly one customer bound. `_verify_destination` (a `getChat`, no message) gave
  `returned_id_matches_stored=True`, `chat_type=private` and `@PromisePatchDemoBot`. The address
  is absent from `GET /api/cases` and `GET /api/cases/{id}` (12 414 bytes), and neither body has
  a `provider_ref` or `sender_identity` key.
- **Ledgers:** audit 385 → 399 and events 990 → 1028. Only grew.
- **Nothing sent:** `sendMessage` 1 → 1, `api.telegram.org` 200s 1 → 1.
- **Host:** same `boot_id`.
- **Reader at `PLANNED`:** `unrelated_digest` `057a55d1…`, **`ef_digest` `22982845…`**, and every
  attribution count `0`.

## 7. Step 2 — plan confirmation and the one message (`CONFIRMED`)

`pp confirm-plan --worker maya` ran in `worker` on the operator console, with command id
`5ae75ca5-…`. It reported `applying 1`, `escalated 2` and `awaiting approval 1`, and the case went
`EXECUTING`. The worker's own cycle dispatched both effects within 1.3 s. Nothing was sent by hand.

| predeclared | measured |
|---|---|
| `plan_approvals` 1, `OPERATOR_CONSOLE` | 1, `channel=OPERATOR_CONSOLE`, `by=maya`, plan `e194fcc0…`, at `19:17:16.000Z` |
| `PLAN_APPROVED`, `PLAN_CONFIRMED` `HUMAN_APPROVAL`, `WORKER maya` | audit 400 and 401, both `HUMAN_APPROVAL`, `WORKER:maya` |
| `pr-a` applied under `CONSTRAINT` | audit 402 `RECOVERY_APPLIED` `CONSTRAINT` `R-PREAPPROVED`; one `ORDER_AMEND` `DELIVERED` attempt 1, key `pp:amend:0482951b-…:d2fe0b6e-…:1`; `EXT-A` v1 → v2 `AMENDED` `almond-4`; audit 406 `ORDER_MIRROR_UPDATED`; audit 407 `RECOVERY_COMPLETED`; `pr-a` `RECOVERED` |
| `pr-b` `WAITING_FOR_CUSTOMER`, one request `SENT` | request `e6588e71-c683-596c-8609-aebbf4384b97` `OPT-F541EB`, `SENT` `19:17:17.512Z`, deadline `2026-09-25T00:17:01Z` |
| one `MESSAGE_SEND` `DELIVERED` at attempt 1 | `DELIVERED` attempt 1, key `pp:approval:e6588e71-…`, `provider_ref` `telegram:<id>:7` persisted |
| `sendMessage` +1 | `sendMessage` 1 → **2**, `worker.telegram.sent` 1 → 2, `api.telegram.org` 200s 1 → **2**, non-200 **0**, `getUpdates` **0** |
| `pr-c`/`pr-d` `ESCALATED`, tasks `HELD` | both `ESCALATED`; `task-ol-c` and `task-ol-d` `HELD` |
| `task-ol-e` `STARTED`, never held; case `WAITING` | `task-ol-e` `STARTED`, not held; case `WAITING` v12 |

**Reader at `CONFIRMED`:**

- `unrelated_digest` **`bcf8743edd311ca111137c3c6505dbb2a53aa054bb598fd53a2f7cbe7bdc5098`**;
- `ef_digest` `22982845…`, unchanged since `PLANNED`;
- attribution `0/0/0/0`.

The change in `unrelated_digest` since `PLANNED` is the protocol's own `CONFIRMED` work: the
`pr-c`/`pr-d` tracks escalated and their tasks held.

**The approval link** was never seen by the session. It is fingerprinted inside the container as
sha256 `edc3d685…`. It occurred 0 times, whole, as payload or as signature, in any of the five
container logs.

## 8. The R1 restart

**Before** (`19:18:58Z`):

- **Case, tracks and request:**
  - case `e66069d7-…` `WAITING` v12;
  - `pr-a` `RECOVERED`, `pr-b` `WAITING_FOR_CUSTOMER` with a request, `pr-c`/`pr-d` `ESCALATED`,
    `pr-e`/`pr-f` `UNAFFECTED`;
  - request `SENT`, `decided=False`.
- **Timer:** one `APPROVAL_DEADLINE` due `2026-09-25T00:17:01Z`, unclaimed.
- **Steps:** eleven, all `DONE`, each at attempt 1, except `CONFIRM_PLAN` at 0 (inline).
- **Counts:** outbox 2, both `DELIVERED` at attempt 1 with 2 distinct keys, 0 unsettled; inbox 1
  (`external-order-system` `PROCESSED`); requests 1, decisions 0, replies 0, `plan_approvals` 1.
- **Ledgers:** `audit_max` 410, `events_max` 1058.
- **Reader:** `unrelated_digest` `bcf8743e…`, `ef_digest` `22982845…`.
- **Worker:** container `ef6428bb042b`, `StartedAt` `17:33:56.63Z`, instance `ef6428bb042b:1:1e096e25`,
  `RestartCount` 0, image `backend:4529a802e34e`.
- **Counters:** `sendMessage` 2, `worker.start` 2, `worker.stop` 1, `getUpdates` 0.

**The restart**, `19:19:01.308Z`, by the documented
`docker compose --env-file env/stack.env restart worker`. Exit `0`, returned at `19:19:02.373Z`.
Only the worker was touched.

```text
{"worker": "ef6428bb042b:1:1e096e25", "event": "worker.stop", "timestamp": "2026-09-24T19:19:01.407809Z"}
{"action": "PRESENT", "case_id": "e66069d7-fd57-580c-a780-f77b3d64ad20", "state": null, "detail": "this world's case already exists; nothing was touched", "rolled": false, "event": "worker.demo_case", "timestamp": "2026-09-24T19:19:04.280118Z"}
{"worker": "ef6428bb042b:1:4ccc1ebc", "event": "worker.start", "timestamp": "2026-09-24T19:19:04.280251Z"}
```

The worker's `StartedAt` moved to `19:19:02.362Z`, and the new instance id is
**`ef6428bb042b:1:4ccc1ebc`**. The container is the same, and `RestartCount` stays 0, as the
documented mechanism keeps it. No error-level line appeared. Every other container kept its
`StartedAt`.

**After**, `19:20:34Z`, following 90 s of the new instance's cycles and before any customer
answer. The snapshot diff of every field below is **empty**:

- fixture: anchor `19:17:01.628589Z`, digest `9f5b9bee…`, so **no re-anchor**;
- case, tracks, request and the `APPROVAL_DEADLINE` timer;
- all eleven steps and their attempts;
- counts, the outbox rows, inbox, plan approvals and replies;
- orders, tasks, commitment lines and customers.

The state being carried is durable: a waiting request, its deadline timer and its delivered
message all survived. The restart itself wrote nothing:

- **0 new audit rows**; `audit_max` still 410;
- **0 new domain events**; `events_max` still 1058;
- no new request, message, decision or effect;
- no dispatch and no step retry;
- `sendMessage` still 2, `getUpdates` 0.

The binding is unchanged: exactly one customer bound, address length 10. The reader post-restart
equals pre-restart: `unrelated_digest` `bcf8743e…` and `ef_digest` `22982845…`. The host
`boot_id` is unchanged. The control plane read at `19:21Z` is identical to entry: stack, change
sets, SSM versions, instance, volume and RDS.

## 9. The customer's answer (`CONSENT_SETTLED` → `SETTLED`)

The owner opened the signed link from the one message on the phone and pressed APPROVE. A
read-only watch saw the request go `SENT` → `ANSWERED` between `19:24:39Z` and `19:24:55Z`.

| predeclared | measured |
|---|---|
| one `approval_decisions` row: `APPROVE`, `LITERAL`, sender = the request's channel | `0fb9ddd7-…`: `APPROVE`, parser `LITERAL`, raw text `yes` (the literal the web answer submits), `sender_matches_channel=True`, received `19:24:54.522Z` |
| one `inbound_replies` row; `customer-reply` inbox `PROCESSED` | reply `3334fbdc-…` received `19:24:53.648Z`; inbox `customer-reply` `PROCESSED` at `19:24:54.445Z` |
| `APPROVAL_DECISION_RECORDED` by `CUSTOMER cus-tomas`, `HUMAN_APPROVAL` | audit 411, `CUSTOMER:cus-tomas`, `HUMAN_APPROVAL`; request `ANSWERED`, `decided=true` |
| **ten `REVALIDATION_CHECK` rows, all passed, fresh snapshot, after the decision** | audit 413–422, **10/10 passed**, snapshot instant `19:24:54.651461Z`, **129 ms after** the decision's `19:24:54.522307Z`; `revalidation.passed as_of 1068`, a domain-event position after the decision's |
| `RECOVERY_REVALIDATED`, `RECOVERY_APPLIED`, `RECOVERY_COMPLETED`, all `HUMAN_APPROVAL` | audit 423 (`outcome PROCEED`, `checks_passed 10`), 425 and 429, all **`HUMAN_APPROVAL`** `R-VISIBLE-ASK` |
| one `ORDER_AMEND`: `EXT-B` v1 → v2 `AMENDED` `rose-3`, claimed at `attempts == 1` while the production start is ahead | one `ORDER_AMEND` `DELIVERED` attempt 1, key `pp:amend:033a70f2-…:f541eba3-…:1`, `provider_ref` `amd-4cc7b479d2a9`, `replayed False`; check 6 read `SCHEDULED and start 2026-09-25T01:17:01Z`, ahead of `19:24:54Z` |
| the order system's store equal to the mirror (`ORDER_MIRROR_UPDATED`) | audit 428 `ORDER_MIRROR_UPDATED` `EXT-B` v2 `ol-b → rose-3`, from the order system's own event (`disposition APPLY`); store read directly: `EXT-A v2 AMENDED almond-4`, `EXT-B v2 AMENDED rose-3`, `EXT-C`…`EXT-F` v1 `ACCEPTED`, equal to the mirror |
| `pr-b` `RECOVERED`; case `RESOLVED`; `plan_approvals` **still 1** | `pr-b` `RECOVERED`; case `RESOLVED` v17; `plan_approvals` **1** |

The ten checks, as `pp case-status` prints them:

1. the track and case are waiting;
2. the order is `ACCEPTED @ v1`;
3. the pinned version is `rose-2`;
4. the constraint hash is unchanged;
5. the substitute is available (3.200 ≥ 2.200);
6. the task is `SCHEDULED` and its start is ahead;
7. the deadline has not passed;
8. the sender is the order's channel (masked);
9. the decision came from `LITERAL`;
10. there is one unspent decision, bound to this plan.

**Every step after the restart point ran on the new instance**:

- `RECEIVE_CUSTOMER_REPLY`, `REVALIDATE_RECOVERY`, `APPLY_RECOVERY`, `RECONCILE_CASE` (`SKIPPED`)
  and `FINALIZE_RECOVERY`;
- the mirror processing;
- audit rows 412–430, each `SYSTEM:ef6428bb042b:1:4ccc1ebc`.

No row carries the old instance id or a foreign worker.

**One recorded observation, and not a deviation.** `FINALIZE_RECOVERY` for `pr-b` returned
`RETRY_SCHEDULED` on attempt 1 at `19:24:55.430Z`. The order system's echo was not mirrored until
`.452Z`. Attempt 2 `COMPLETED` at `19:24:56.553Z`.

- This is the finalizer running ahead of the echo, recorded identically on the previous deployed
  loop ([phase7-deployed-behavioral-proof.md](phase7-deployed-behavioral-proof.md), `pr-b`
  `RECOVERED` row).
- It happened 5 min 54 s after the restart, inside the new instance's own post-answer work.
- The restart itself added no step retry: the post-restart diff is empty.

The protocol's attempt-1 requirement is on the outbox effects, and all three are at attempt 1.

## 10. Exactly-once, untouched, privacy

**Exactly-once**, at the end:

- **Outbox:** exactly **3** rows, `ORDER_AMEND` ×2 and `MESSAGE_SEND` ×1. All `DELIVERED`, all
  at attempt 1, **3 distinct keys**.
- **Messages:** `sendMessage` exactly **+1** over the rehearsal (1 → 2), `api.telegram.org`
  200s +1, non-200 0, **`getUpdates` 0**. The owner saw exactly one message.
- **Consent rows:** 1 request, 1 decision, 1 reply.
- **Cases:** exactly one.
- **The restart** added no effect, no step retry, no case and no plan approval.

**Untouched**, by the frozen reader:

| | `PLANNED` | `CONFIRMED` | pre-restart | post-restart | `SETTLED` |
|---|---|---|---|---|---|
| `unrelated_digest` | `057a55d1…` | **`bcf8743e…`** | `bcf8743e…` | `bcf8743e…` | **`bcf8743e…`** |
| `ef_digest` | **`22982845…`** | `22982845…` | `22982845…` | `22982845…` | **`22982845…`** |
| attribution audit/events/outbox/requests | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |

- `unrelated_digest` is **equal between `CONFIRMED` and `SETTLED`**, and every component digest
  matches.
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

CloudWatch `/promisepatch/prod` since `19:16Z`, read from the operator machine:

- 178 events across 4 streams;
- **0** token-shaped strings, **0** chat-id patterns, **0** bot-token-shaped strings;
- **0** unredacted query or path forms (`approve=REDACTED` 2, `approval/REDACTED` 8);
- this rehearsal's link fingerprint absent.

## 11. Health, at the end

| | state |
|---|---|
| Host | `boot_id` `109dccdf-…` throughout: **no reboot** |
| Containers | all on `4529a802e34e` (`caddy` on `caddy:2.10-alpine`), 0 restarts; only the worker's `StartedAt` moved, by the one restart |
| `/healthz` / `/readyz` | `4529a802e34e`; ready, migrations at head, fixture anchor `19:17:01Z` |
| Files and certificate | `converge.sh` `09105b10…` and `channel.env` `c3a6e4de…` unchanged; certificate and key dated `2026-09-13 18:35`; the three Docker volumes present |
| Order simulator | `200` |
| Control plane | stack `UPDATE_COMPLETE` at `16:00:45Z`, 0 change sets; SSM `image-tag` v9, `compose` v14, `caddyfile` v13; instance, AMI, launch time, volume and RDS identical to entry |

Smoke was not run. The known port-80 self-hairpin limitation applies unchanged.

The deployed world is left `RESOLVED` and pinned by its own effects, with nothing in flight and
nothing waiting on a person. Its `APPROVAL_DEADLINE` timer, due `00:17:01Z`, is for an answered
request.

## 12. What this does not prove

- **R1 is one rehearsal.** R2–R5 are unrun: a worker stopped across the confirmation, a worker
  stopped across the answer, a restart after settlement, and a repeat of R1.
- **The restart was a restart, not a stop.** For the whole restart, from the stop to the next
  instance's first cycle, no customer answer, timer or effect was due. So R1 proves that the
  waiting state is durable, not that work queued while no worker runs is picked up. That is
  R2/R3.
- No refusal path was exercised: `STALE`, `EXPIRED`, `UNAUTHORIZED`, `NOOP`, and any restore
  refusal.
- The `FINALIZE_RECOVERY` retry-ahead-of-echo is recorded, not changed. It is the same behaviour
  as the previous loop.

## 13. R2

**R2 can proceed without a code change.** Before it can run, it needs:

- the owner's authorisation for its restore, confirmation, message and stop/start;
- the reader in the appendix, byte-identical (`c9731c8f…`);
- the census run in `api` while no worker runs.

## Appendix — the frozen reader `g8ev.py`

sha256 `c9731c8f8dedfe15fbc6af0c2db6a8d5d19ca090d7863f3d2e945b18220b0dd4`, over the bytes between
the fences with LF line endings and a final newline.

```python
"""G8 rehearsal untouched-state evidence reader. FROZEN before rehearsal R1; never edited after.

Read-only. Runs inside a deployed backend container (worker, or api while the worker is down):
one READ ONLY transaction against the database, and GETs only against the External Order
System. Prints digests and counts, never an address, a token or a URL.

Scope (docs/g8-rehearsal-preparation.md section 3.1, step 2): every promise, order, line,
constraint, task, reservation and customer OUTSIDE pr-a/EXT-A and pr-b/EXT-B, plus the order
system's own store for those orders.

  unrelated_digest   over ord-c..ord-f (the protocol's digest; compared CONFIRMED -> SETTLED)
  ef_digest          over ord-e and ord-f only (UNAFFECTED; compared PLANNED -> SETTLED)
  attributed_*       structural attribution to pr-e/pr-f since the fixture loaded:
                     audit rows on their tracks, domain events whose entity_refs name any of
                     their promise/order/line/task/customer ids, outbox rows whose payload names
                     them, approval requests on their promises. All must be 0.
"""

import asyncio
import hashlib
import json
import os
import urllib.request

import asyncpg

URL = os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
ORDER_SYSTEM = "http://order-simulator:8100"
EXCLUDED_EXTERNAL = ("EXT-A", "EXT-B")
EF_ORDERS = ("ord-e", "ord-f")


def canon(value):
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canon(value).encode()).hexdigest()


async def components(c, order_ids):
    rows = lambda q: c.fetch(q, order_ids)  # noqa: E731
    return {
        "orders": [dict(r) for r in await rows(
            "select id, external_id, external_version, customer_id, due_at, state, mirror_source_event_id, updated_at"
            " from orders where id = any($1::text[]) order by id")],
        "lines": [dict(r) for r in await rows(
            "select id, order_id, recipe_version_id, quantity, customization_note"
            " from order_lines where order_id = any($1::text[]) order by id")],
        "constraints": [dict(r) for r in await rows(
            "select id, order_id, kind, resource_id, substitute_resource_id, recorded_by, recorded_at"
            " from order_constraints where order_id = any($1::text[]) order by id")],
        "promises": [dict(r) for r in await rows(
            "select id, order_id, due_at, current_classification, current_track_state, current_case_id, current_track_id"
            " from promises where order_id = any($1::text[]) order by id")],
        "tracks": [dict(r) for r in await rows(
            "select t.id, t.case_id, t.promise_id, t.state, t.classification, t.rule_id, t.reason_detail,"
            " t.approval_request_id from tracks t join promises p on p.id = t.promise_id"
            " where p.order_id = any($1::text[]) order by t.promise_id, t.id")],
        "tasks": [dict(r) for r in await rows(
            "select t.id, t.order_line_id, t.state, t.scheduled_start, t.scheduled_end, t.equipment_id, t.held_by_case_id"
            " from production_tasks t join order_lines l on l.id = t.order_line_id"
            " where l.order_id = any($1::text[]) order by t.id")],
        "reservations": [dict(r) for r in await rows(
            "select r.id, r.order_line_id, r.resource_id, r.quantity, r.source_recipe_version_id"
            " from reservations r join order_lines l on l.id = r.order_line_id"
            " where l.order_id = any($1::text[]) order by r.id")],
        "customers": [dict(r) for r in await rows(
            "select cu.id, cu.name, cu.approval_channel_kind, md5(cu.approval_channel_address) h"
            " from customers cu where cu.id in (select customer_id from orders where id = any($1::text[])) order by cu.id")],
    }


def order_system_store(external_ids):
    with urllib.request.urlopen(ORDER_SYSTEM + "/orders", timeout=15) as response:
        body = json.load(response)
    return sorted(
        (o for o in body.get("orders", []) if o.get("external_id") in external_ids),
        key=lambda o: o.get("external_id"),
    )


async def main():
    c = await asyncpg.connect(URL)
    await c.execute("set search_path to promisepatch")
    tx = c.transaction(readonly=True)
    await tx.start()
    try:
        print(f"db_now={(await c.fetchval('select now()')).isoformat()}")
        loaded = await c.fetchval("select loaded_at from fixture_state limit 1")
        unrelated_ids = [r["id"] for r in await c.fetch(
            "select id from orders where external_id <> all($1::text[]) order by id", list(EXCLUDED_EXTERNAL))]
        ext = {r["id"]: r["external_id"] for r in await c.fetch("select id, external_id from orders")}
        print(f"unrelated_orders={','.join(unrelated_ids)}")
        unrelated = await components(c, unrelated_ids)
        ef = await components(c, list(EF_ORDERS))

        ef_ids = set(EF_ORDERS)
        ef_ids |= {r["id"] for r in ef["lines"]} | {r["id"] for r in ef["promises"]}
        ef_ids |= {r["id"] for r in ef["tasks"]} | {r["id"] for r in ef["customers"]}
        ef_ids |= {ext[o] for o in EF_ORDERS}
        ef_tracks = [str(r["id"]) for r in ef["tracks"]]
        ef_promises = [r["id"] for r in ef["promises"]]
        attributed_audit = await c.fetchval(
            "select count(*) from audit_events where occurred_at >= $1 and track_id::text = any($2::text[])",
            loaded, ef_tracks)
        attributed_events = 0
        for r in await c.fetch("select entity_refs from domain_events where occurred_at >= $1", loaded):
            refs = r["entity_refs"]
            refs = json.loads(refs) if isinstance(refs, str) else (refs or [])
            if any(isinstance(ref, dict) and str(ref.get("id")) in ef_ids | set(ef_tracks) for ref in refs):
                attributed_events += 1
        attributed_outbox = 0
        for r in await c.fetch("select payload from outbox_messages"):
            payload = r["payload"] if isinstance(r["payload"], str) else canon(r["payload"])
            if any(f'"{i}"' in payload for i in ef_ids):
                attributed_outbox += 1
        attributed_requests = await c.fetchval(
            "select count(*) from approval_requests where promise_id = any($1::text[])", ef_promises)
    finally:
        await tx.rollback()
        await c.close()

    unrelated["order_system"] = order_system_store({ext[o] for o in unrelated_ids})
    ef["order_system"] = order_system_store({ext[o] for o in EF_ORDERS})

    for name in sorted(unrelated):
        print(f"unrelated.{name}={digest(unrelated[name])[:16]} n={len(unrelated[name])}")
    print(f"unrelated_digest={digest(unrelated)}")
    print(f"ef_digest={digest(ef)}")
    print("versions mirror=" + canon([(r["external_id"], r["external_version"], r["state"]) for r in unrelated["orders"]])
          + " store=" + canon([(o.get("external_id"), o.get("version"), o.get("state")) for o in unrelated["order_system"]]))
    print("ef_tracks=" + canon([(r["promise_id"], r["state"], r["classification"]) for r in ef["tracks"]])
          + " ef_tasks=" + canon([(r["id"], r["state"], r["held_by_case_id"] is not None) for r in ef["tasks"]]))
    print(f"attributed_audit={attributed_audit} attributed_events={attributed_events}"
          f" attributed_outbox={attributed_outbox} attributed_requests={attributed_requests}")


asyncio.run(main())
```
