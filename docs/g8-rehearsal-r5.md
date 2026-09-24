# G8 deployed rehearsal R5 — the R1 restart repeated, for reproducibility

Date: **2026-09-24**, host work between `20:54Z` and `21:00Z`. Entry at
`e79288d352f666d32acf7da3ab00597adfa7097b`: `main` equal to `origin/main`, tracked tree clean, and
the eleven known untracked artefacts left as they were. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`.

This is rehearsal #5, the last of the five that
[g8-rehearsal-preparation.md](g8-rehearsal-preparation.md) §3 predeclared. It ran against the frozen
release candidate `4529a802e34e` ([phase7-closeout.md](phase7-closeout.md)). R5 is a **deliberate
repeat of R1** ([g8-rehearsal-r1.md](g8-rehearsal-r1.md)): the same restart point, **while the case
waits for the customer's answer** (`S16`), and the same mechanism. It was judged against §3.1 and
R5's row in §3.2, unchanged: "as R1 … the canonical shape repeated exactly, for repeatability". §10's
amendment touches R3 only. Nothing was redefined here.

## 1. Verdict

**R5: PASS.** It counts as **5 of 5** on image `4529a802e34e`. Every §3.1 checkpoint,
exactly-once, untouched, privacy and restart item holds, and R5 reproduces R1 on every semantic
invariant compared in section 10. No timestamp or identifier was required to match.

- **The restart wrote nothing.** It was taken while `pr-b` waited for the customer. The pre →
  post snapshot diff, over 90 s of the new instance's cycles, is empty: no re-anchor, and no new
  row, request, message, decision, effect or step attempt.
- **The owner's real APPROVE** was then revalidated and applied exactly once, all by the new
  instance: ten passed checks, `PROCEED`, one `EXT-B` amendment with one key, the mirror converged,
  `pr-b` `RECOVERED`, case `RESOLVED`, under `HUMAN_APPROVAL` throughout.

No product code, test, deployment file, infrastructure, IAM, SSM parameter or release was changed.

## 2. Authorisation, and what was spent

The owner authorised exactly:

- one guarded restore;
- one plan confirmation;
- one real Telegram approval message;
- one worker restart while waiting for customer approval;
- the owner's own real APPROVE after the restart.

**Each was used once.** The session stopped at the post-restart checkpoint and asked for the
answer. The owner opened the signed link from the one message on the phone, pressed APPROVE, and
reported "approved, exactly one message seen". Nothing in the session opened, followed, simulated
or wrote that answer.

Host access was `ssm:StartSession` with `AWS-StartNonInteractiveCommand` alone. Every census ran
in a read-only transaction. Nothing printed in this session carried a chat id, a bot token, a
password or the approval link.

## 3. The frozen evidence reader

The reader was extracted byte for byte from the committed appendix of
[g8-rehearsal-r1.md](g8-rehearsal-r1.md) and was not modified.

| | |
|---|---|
| **sha256** | **`c9731c8f8dedfe15fbc6af0c2db6a8d5d19ca090d7863f3d2e945b18220b0dd4`**, equal to R1's |
| local check | byte-identical to R1's own frozen file |
| verified on the host | the same sha256 printed by the host before every one of the six reads |

It was not reproduced here. The appendix of R1 stays the only copy.

## 4. Timeline

| UTC | event |
|---|---|
| `20:54:05` | entry census: R4's case `43b75690-…` `RESOLVED`, outbox 3, 0 unsettled, one customer bound, `sendMessage` lifetime 5 |
| `20:54:51.603` → `20:54:56.445` | **restore** (the one) |
| `20:55:05.923` → `20:55:08.298` | **plan confirmation** (the one), 10 s after planning |
| `20:55:09.063` | the one `MESSAGE_SEND` delivered; request `SENT` at `.257` |
| `20:55:53` | pre-restart snapshot |
| `20:55:56.769` | **worker restart** (the one) |
| `20:55:59.635` | new instance `worker.start` |
| `20:57:29` | post-restart snapshot, after 90 s of the new instance's cycles |
| `20:57:3x` | control plane re-read, identical to entry; the session stops and asks for the answer |
| `20:58:38.634` | the owner's APPROVE arrives (`inbound_replies`) |
| `20:58:40.580` | `RECOVERY_COMPLETED`; case `RESOLVED` |
| `20:59:30` → `21:00` | settled evidence, CloudWatch scan, store and control plane |

The approval window closes at `2026-09-25T01:54:53Z`.

## 5. Entry

| | measured |
|---|---|
| Stack | `promisepatch-prod` `UPDATE_COMPLETE`, last updated `16:00:45Z`, **0 change sets** |
| Image | `ImageTag`, `DeclaredImageTag` and SSM `image-tag` (v9) all `4529a802e34e`; SSM `compose` v14 and `caddyfile` v13 byte-equal to HEAD |
| Instance / volume / RDS | `i-087c742587f83d61d` `t4g.small` `ami-0fa4996c14e7d501e`, launched `2026-09-18T10:19:33Z`, IMDSv2 required, hop limit 2 / `vol-0f330aaa62e637ef6` encrypted / `db-U2JWQBTINX6W6GAB56EOTHOCSM` private, encrypted |
| Host | `boot_id` `109dccdf-b7fb-4882-8b28-c963b2f0f7b9`, up since `16:02:33` |
| Containers | `api`, `worker`, `mcp` and `migrate` on `backend:4529a802e34e`; `order-simulator` on `order-simulator:4529a802e34e`; `caddy:2.10-alpine`; 0 restarts |
| `/readyz` | ready; migrations at head `0009_human_plan_approval` |
| Provider | `telegram` in `api` and `worker`, bot token present (value not read) |
| Effects | outbox 3, all `DELIVERED`, **0 `PENDING`/`IN_FLIGHT`** |
| Binding | `cus-tomas` bound (address length 10), the other five at 4-character placeholders |
| Files | `converge.sh` `09105b10…`, `env/channel.env` `c3a6e4de…` |
| Logs | 0 token-shaped, 0 unredacted, 0 address and 0 chat-id lines in all five containers |

## 6. Restore, confirmation and delivery (`PLANNED` → `CONFIRMED`)

**Restore gate.** The env union was read on the host from `env/migrate.env`, passed with `exec -e`
and unset. No value was printed.

- Settings preflight under the union: all four `require_*` `ok`; `allow_fixture_reset=True`,
  `demo_session_enabled=True`, `provider=telegram`; `preflight=ok`.
- Dry run: exit `0`, `binding: restored (would be carried across)`, `unsettled=0`,
  `fixture=hollow-oak`. `restore_gate=ok`.

```text
action:   restored
before:   fixture=hollow-oak cases=1 live=0 outbox=3 unsettled=0 requests=1 decisions=1 approvals=1 replies=1 audit=565 events=695 bound=True
after:    fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=579 events=714 bound=True
anchor:   2026-09-24T20:54:53.431361+00:00
digest:   850c7ceafa068a9f5dc8da5f0fcb4d7f13e4f77937b61b4e626e78c8bbcbebe4
orders:   6 reset in the external order system
case:     714aafc6-df32-5f59-a7ac-c6a086620e9a
state:    PLANNED
binding:  restored
ledgers:  grew only
restore_exit=0
```

**The `PLANNED` checkpoint**, gated automatically before the confirmation:

- **Partition:** `pr-a` `AUTO_RECOVERABLE` `R-PREAPPROVED`. **`pr-b` `APPROVAL_REQUIRED`
  `R-VISIBLE-ASK` `rose-2 → rose-3`** is the only approval-required option. `pr-c` is `BLOCKED`
  `R-NOSUB` (`NOSUB_CONSTRAINT`) and `pr-d` is `BLOCKED` `R-NOSUB` (`NO_PREAUTHORED_VARIANT`).
  `pr-e` and `pr-f` are `UNAFFECTED` `R-UNREACH`. `partition_gate=ok`.
- **Case:** `714aafc6-…` `PLANNED` v7, the only case, with one unfired `PLAN_AUTO_ESCALATION` due
  `21:04:55Z`.
- **Counters:** outbox, requests, decisions, `plan_approvals`, replies and inbox all 0.
- **Orders and tasks:** all six orders at v1 in the mirror and in the order system. `task-ol-e`
  is `STARTED`, the other five `SCHEDULED`.
- **Binding:** exactly one customer bound. A `getChat`, with no message sent, gave
  `returned_id_matches_stored=True`, `chat_type=private` and `@PromisePatchDemoBot`. The address is
  absent from `GET /api/cases` and `GET /api/cases/{id}` (12 414 bytes), and neither body has a
  `provider_ref` or `sender_identity` key.
- **Ledgers:** audit 565 → 579, events 1390 → 1428. Only grew.
- **Nothing sent:** `sendMessage` 5 → 5, `api.telegram.org` 200s 5 → 5. Host: same `boot_id`.
- **Reader at `PLANNED`:** `unrelated_digest` `14a936eb…`, **`ef_digest` `be01fc89…`**, and every
  attribution count `0`.

**The confirmation.** `pp confirm-plan --worker maya` ran in `worker` on the operator console, with
command id `b1a4bbdb-…`. It reported `applying 1`, `escalated 2` and `awaiting approval 1`, and the
case went `EXECUTING`. The worker's own cycle dispatched both effects within 1.2 s, and the case
was `WAITING` at the first 3 s poll. Nothing was sent by hand.

| predeclared | measured |
|---|---|
| `plan_approvals` 1, `OPERATOR_CONSOLE` | 1, `channel=OPERATOR_CONSOLE`, `by=maya`, plan `50b086c5…`, at `20:55:07.872Z` |
| `PLAN_APPROVED`, `PLAN_CONFIRMED` `HUMAN_APPROVAL`, `WORKER maya` | audit 580 and 581, both `HUMAN_APPROVAL`, `WORKER:maya` |
| `pr-a` applied under `CONSTRAINT` | audit 582 `RECOVERY_APPLIED` `CONSTRAINT` `R-PREAPPROVED`; one `ORDER_AMEND` `DELIVERED` attempt 1, key `pp:amend:b0dff72f-…:e436294f-…:1`; `EXT-A` v1 → v2 `AMENDED` `almond-4`; audit 586 `ORDER_MIRROR_UPDATED`; audit 587 `RECOVERY_COMPLETED`; `pr-a` `RECOVERED` |
| `pr-b` `WAITING_FOR_CUSTOMER`, one request `SENT` | request `ff8d54a7-d021-5801-9d87-25ad19172048` `OPT-6A4930`, `SENT` `20:55:09.257Z`, deadline `2026-09-25T01:54:53Z` |
| one `MESSAGE_SEND` `DELIVERED` at attempt 1 | `DELIVERED` attempt 1, key `pp:approval:ff8d54a7-…`, `provider_ref` `telegram:<id>:11` persisted |
| `sendMessage` +1, HTTP 200 | `sendMessage` 5 → **6**, `worker.telegram.sent` 5 → 6, `api.telegram.org` 200s 5 → **6**, non-200 **0**, `getUpdates` **0** |
| `pr-c`/`pr-d` `ESCALATED`, tasks `HELD` | both `ESCALATED`; `task-ol-c` and `task-ol-d` `HELD` |
| `task-ol-e` `STARTED`, never held; case `WAITING` | `task-ol-e` `STARTED`, not held; case `WAITING` v12 |

The confirmation cancelled `PLAN_AUTO_ESCALATION`. The only timer is now `APPROVAL_DEADLINE`.

**Reader at `CONFIRMED`:**

- `unrelated_digest` **`31d8ea4b5a70908c1844609a06fab7ba727ab00156beee63dcfd3d6ead4f4525`**;
- `ef_digest` `be01fc89…`, unchanged since `PLANNED`;
- attribution `0/0/0/0`.

The change in `unrelated_digest` since `PLANNED` is the protocol's own `CONFIRMED` work: the
`pr-c`/`pr-d` tracks escalated and their tasks held.

## 7. The R5 restart

**Before** (`20:55:53Z`):

- **Case, tracks and request:**
  - case `714aafc6-…` `WAITING` v12;
  - `pr-a` `RECOVERED`, `pr-b` `WAITING_FOR_CUSTOMER` with a request, `pr-c`/`pr-d` `ESCALATED`,
    `pr-e`/`pr-f` `UNAFFECTED`;
  - request `SENT`, `decided=False`.
- **Timer:** one `APPROVAL_DEADLINE` due `2026-09-25T01:54:53Z`, unclaimed.
- **Steps:** eleven, all `DONE`, each at attempt 1, except `CONFIRM_PLAN` at 0 (inline).
- **Counts:** outbox 2, both `DELIVERED` at attempt 1 with 2 distinct keys, 0 unsettled; inbox 1
  (`external-order-system` `PROCESSED`); requests 1, decisions 0, replies 0, `plan_approvals` 1.
- **Ledgers:** `audit_max` 590, `events_max` 1458.
- **Reader:** `unrelated_digest` `31d8ea4b…`, `ef_digest` `be01fc89…`, attribution `0/0/0/0`.
- **Worker:** container `ef6428bb042b`, `StartedAt` `20:44:58.14Z`, instance `ef6428bb042b:1:02d04fb6`,
  `RestartCount` 0, image `backend:4529a802e34e`.
- **Counters:** `sendMessage` 6, `worker.start` 6, `worker.stop` 5, `getUpdates` 0.

**The restart**, `20:55:56.769Z`, by the same documented mechanism as R1,
`docker compose --env-file env/stack.env restart worker`. It exited `0` and returned at
`20:55:57.786Z`, and the script's gate had checked the restart point before issuing it. Only the
worker was touched.

```text
{"worker": "ef6428bb042b:1:02d04fb6", "event": "worker.stop", "level": "info", "timestamp": "2026-09-24T20:55:56.864873Z"}
{"action": "PRESENT", "case_id": "714aafc6-df32-5f59-a7ac-c6a086620e9a", "state": null, "detail": "this world's case already exists; nothing was touched", "rolled": false, "event": "worker.demo_case", "level": "info", "timestamp": "2026-09-24T20:55:59.635172Z"}
{"worker": "ef6428bb042b:1:18da2a65", "event": "worker.start", "level": "info", "timestamp": "2026-09-24T20:55:59.635307Z"}
```

The worker's `StartedAt` moved to `20:55:57.772Z`, and the new instance id is
**`ef6428bb042b:1:18da2a65`**. The container is the same, and `RestartCount` stays 0, as the
documented mechanism keeps it. No error-level line appeared. Every other container kept its
`StartedAt`.

**After**, `20:57:29Z`, following 90 s of the new instance's cycles and before any customer
answer. The snapshot diff of every field below is **empty** (`NO DIFFERENCE`):

- fixture: anchor `20:54:53.431361Z`, digest `850c7cea…`, so **no re-anchor**;
- case, tracks, request and the `APPROVAL_DEADLINE` timer;
- all eleven steps and their attempts;
- counts, the outbox rows, inbox, plan approvals and replies;
- orders, tasks, commitment lines and customers.

The waiting request, its deadline timer and its delivered message all survived. The restart
itself wrote nothing:

| post-restart invariant | measured |
|---|---|
| same case and request survive | case `714aafc6-…` `WAITING` v12; request `ff8d54a7-…` `SENT`, `decided=False` |
| no re-anchor | anchor and fixture digest identical; `worker.demo_case` `PRESENT`, `rolled: false` |
| no new request, message, decision or effect | requests 1, `MESSAGE_SEND` 1, decisions 0, outbox 2 |
| no new ledger row | **0 new audit rows**, `audit_max` still 590; **0 new domain events**, `events_max` still 1458 |
| binding unchanged | exactly one customer bound, address length 10 |
| pending timer and work survive | `APPROVAL_DEADLINE` unchanged and unclaimed; the request still awaits its answer |
| no duplicate dispatch | every step at its pre-restart attempt; `sendMessage` still 6, `getUpdates` 0 |
| unrelated digest unchanged | reader post-restart equals pre-restart: `31d8ea4b…` and `be01fc89…`, attribution `0/0/0/0` |
| infrastructure unchanged | same `boot_id`; control plane re-read at `20:57Z` identical to entry: stack, change sets, SSM versions, instance, volume and RDS |

## 8. The customer's answer (`CONSENT_SETTLED` → `SETTLED`)

After the checkpoint above was proved, the session stopped and asked the owner to answer. A
read-only watch saw the request go `SENT` → `ANSWERED` between `20:58:34Z` and `20:58:50Z`.

| predeclared | measured |
|---|---|
| one `approval_decisions` row: `APPROVE`, `LITERAL`, sender = the request's channel | `1bab631c-…`: `APPROVE`, parser `LITERAL`, raw text `yes` (the literal the web answer submits), `sender_matches_channel=True`, received `20:58:38.717Z` |
| one `inbound_replies` row; `customer-reply` inbox `PROCESSED` | reply `9a8f72a0-…` received `20:58:38.634Z`; inbox `customer-reply` `PROCESSED` at `20:58:38.638Z` |
| `APPROVAL_DECISION_RECORDED` by `CUSTOMER cus-tomas`, `HUMAN_APPROVAL` | audit 591, `CUSTOMER:cus-tomas`, `HUMAN_APPROVAL`; request `ANSWERED`, `decided=true` |
| **ten `REVALIDATION_CHECK` rows, all passed, fresh snapshot, after the decision** | audit 593–602, **10/10 passed**, snapshot instant `20:58:38.848993Z`, **131 ms after** the decision; `revalidation.passed as_of 1468`, past the `events_max` 1458 held across the restart |
| `RECOVERY_REVALIDATED`, `RECOVERY_APPLIED`, `RECOVERY_COMPLETED`, all `HUMAN_APPROVAL` | audit 603 (`outcome PROCEED`, `checks_passed 10`), 605 and 609, all **`HUMAN_APPROVAL`** `R-VISIBLE-ASK` |
| one `ORDER_AMEND`: `EXT-B` v1 → v2 `AMENDED` `rose-3`, claimed at `attempts == 1` while the production start is ahead | one `ORDER_AMEND` `DELIVERED` attempt 1, key `pp:amend:b41af2dc-…:6a493050-…:1`, `provider_ref` `amd-5d6b314a4e22`, `replayed False`; check 6 read `SCHEDULED and start 2026-09-25T02:54:53Z`, ahead of `20:58:38Z` |
| the order system's store equal to the mirror (`ORDER_MIRROR_UPDATED`) | audit 608 `ORDER_MIRROR_UPDATED` `EXT-B` v2 `ol-b → rose-3`, from the order system's own event (`disposition APPLY`); store read directly: `EXT-A v2 AMENDED almond-4`, `EXT-B v2 AMENDED rose-3`, `EXT-C`…`EXT-F` v1 `ACCEPTED`, equal to the mirror |
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
- audit rows 592–610, each `SYSTEM:ef6428bb042b:1:18da2a65`.

No row after the restart carries the old instance id or a foreign worker. In the worker log since
the restart, the old id appears once, on its own `worker.stop`.

**Workflow retries and external-effect attempts, recorded separately:**

| | count |
|---|---|
| External-effect attempts | all three outbox rows `DELIVERED` at **attempt 1**, 3 distinct keys; one `EXT-B` idempotency key, used once |
| Workflow step retries, before the restart | none; eleven steps at attempt 1, `CONFIRM_PLAN` at 0 (inline) |
| Workflow step retries, caused by the restart | **none**; the post-restart diff is empty |
| Workflow step retries, after the answer | one: `FINALIZE_RECOVERY` for `pr-b` returned `RETRY_SCHEDULED` on attempt 1 at `20:58:39.452Z`, because the order system's echo was mirrored at `.524Z`; attempt 2 `COMPLETED` at `20:58:40.580Z` |

The finalizer running ahead of the echo is the same behaviour R1 recorded (attempt 2), and R4
recorded it too (attempt 3). It is a workflow re-read, not an effect retry: the amendment it waits
on was dispatched once.

## 9. Exactly-once, untouched, privacy

**Exactly-once**, at the end:

- **Outbox:** exactly **3** rows, `ORDER_AMEND` ×2 and `MESSAGE_SEND` ×1. All `DELIVERED`, all
  at attempt 1, **3 distinct keys**.
- **Messages:** `sendMessage` exactly **+1** over the rehearsal (5 → 6), `api.telegram.org` 200s
  +1, non-200 0, **`getUpdates` 0**. The owner saw exactly one message.
- **Consent rows:** 1 request, 1 decision, 1 reply.
- **Cases:** exactly one. `plan_approvals` is 1: the customer's yes spent no worker approval.
- **The restart** added no effect, no step retry, no case and no plan approval.

**Untouched**, by the frozen reader:

| | `PLANNED` | `CONFIRMED` | pre-restart | post-restart | `SETTLED` |
|---|---|---|---|---|---|
| `unrelated_digest` | `14a936eb…` | **`31d8ea4b…`** | `31d8ea4b…` | `31d8ea4b…` | **`31d8ea4b…`** |
| `ef_digest` | **`be01fc89…`** | `be01fc89…` | `be01fc89…` | `be01fc89…` | **`be01fc89…`** |
| attribution audit/events/outbox/requests | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |

- `unrelated_digest` is **equal between `CONFIRMED` and `SETTLED`**.
- `ef_digest` is **equal between `PLANNED` and `SETTLED`**.
- `EXT-C`…`EXT-F` are at v1 `ACCEPTED` in the mirror and in the order system's store.
- `pr-e`/`pr-f` are `UNAFFECTED` from `PLANNED` to `SETTLED`, with nothing attributed to them.
- `task-ol-e` is still `STARTED` and was never held.

**Privacy.** Nothing in the session's output carried a chat id, token, password or link:

- every census masked the address in-process, and its leak guard read `False` each time;
- every reader run passed through an in-container leak check reading `address=0`,
  `chatid_pattern=0`, `token_shaped=0` and `bot_token=0`.

Container logs at `SETTLED`: `caddy`, `api`, `worker`, `mcp` and `order-simulator` each show 0
token-shaped strings, 0 unredacted query or path forms, 0 addresses, 0 chat-id patterns and 0 bot
tokens. This rehearsal's link, fingerprinted in the container as sha256 `f6415e1d…`, occurs 0 times
anywhere, whole, as payload or as signature.

CloudWatch `/promisepatch/prod` since `20:54Z`, read from the operator machine:

- 139 events across 4 streams;
- **0** token-shaped strings, **0** chat-id patterns, **0** bot-token-shaped strings;
- **0** unredacted query or path forms (`approve=REDACTED` 6, `approval/REDACTED` 8);
- this rehearsal's link fingerprint absent.

## 10. Reproducibility: R5 against R1

The comparison is on semantic invariants. Timestamps, UUIDs, idempotency-key UUIDs, instance ids,
Telegram message numbers and absolute ledger positions differ by construction and were not
required to match.

| invariant | R1 | R5 | same |
|---|---|---|---|
| restart point | case `WAITING`, `pr-b` `WAITING_FOR_CUSTOMER`, request `SENT` `decided=False`, one unclaimed `APPROVAL_DEADLINE` | identical | yes |
| steps at the restart point | eleven, all `DONE` at attempt 1, `CONFIRM_PLAN` at 0 | identical | yes |
| restart mechanism | `compose restart worker`; same container, `RestartCount` 0, new instance id | identical | yes |
| start-up behaviour | `worker.demo_case` `PRESENT`, `rolled: false`; 0 error lines | identical | yes |
| no re-anchor | anchor and digest unchanged across the restart | identical | yes |
| restart writes | pre → post diff empty after 90 s; 0 audit rows, 0 domain events | identical | yes |
| message count | exactly one `MESSAGE_SEND`, attempt 1; `sendMessage` +1; `getUpdates` 0; owner saw one | identical | yes |
| consent rows | 1 request, 1 reply, 1 decision `APPROVE` `LITERAL` `yes`, sender matches | identical | yes |
| authority path | `PLAN_APPROVED`/`PLAN_CONFIRMED` `HUMAN_APPROVAL` by `WORKER maya`; `pr-a` under `CONSTRAINT`; decision by `CUSTOMER cus-tomas`; revalidated, applied, completed under `HUMAN_APPROVAL` `R-VISIBLE-ASK`; `plan_approvals` stays 1 | identical | yes |
| revalidation | 10 checks, 10 passed, fresh snapshot after the decision, `PROCEED` | identical (R1 129 ms after the decision, R5 131 ms) | yes |
| who ran the post-answer work | every row after the restart on the new instance; no foreign worker | identical | yes |
| amendment and idempotency | `EXT-A` and `EXT-B` each one `ORDER_AMEND`, attempt 1, one key each, `replayed False`; v1 → v2 `AMENDED` | identical | yes |
| mirror convergence | `ORDER_MIRROR_UPDATED` from the order system's own event; store equal to mirror | identical | yes |
| workflow retry | `FINALIZE_RECOVERY` `pr-b` attempt 2 after the echo race | identical | yes |
| final state | `pr-a`/`pr-b` `RECOVERED`, `pr-c`/`pr-d` `ESCALATED` with tasks `HELD`, `pr-e`/`pr-f` `UNAFFECTED`, case `RESOLVED` v17, outbox 3 at attempt 1 | identical | yes |
| untouched state | `unrelated_digest` equal `CONFIRMED` → `SETTLED`; `ef_digest` equal `PLANNED` → `SETTLED`; attribution 0/0/0/0 at all five readings; `EXT-C`…`EXT-F` v1 in mirror and store | identical | yes |
| privacy | 0 addresses, chat ids, tokens or unredacted links in five container logs and in CloudWatch | identical | yes |
| infrastructure | same `boot_id`; control plane identical to entry | identical | yes |

**Every compared invariant matches.** The digests themselves differ between the two runs
(`bcf8743e…` in R1, `31d8ea4b…` in R5). This is expected, and the protocol never compares them
across runs: each restore installs the world at a fresh anchor, so due dates and timestamps inside
the unrelated rows move. The protocol's untouched comparisons are within a run, and within R5 they
hold exactly as they held within R1.

## 11. Health, at the end

| | state |
|---|---|
| Host | `boot_id` `109dccdf-…` throughout: **no reboot** |
| Containers | all on `4529a802e34e` (`caddy` on `caddy:2.10-alpine`), 0 restarts; only the worker's `StartedAt` moved, by the one restart |
| `/healthz` / `/readyz` | `4529a802e34e`; ready, migrations at head, fixture anchor `20:54:53Z` |
| Files and certificate | `converge.sh` `09105b10…` and `channel.env` `c3a6e4de…` unchanged; certificate and key dated `2026-09-13 18:35`; the three Docker volumes present |
| Order simulator | `200` |
| Control plane | re-read at the end, identical to entry apart from the log group's growing byte count: stack `UPDATE_COMPLETE` at `16:00:45Z`, 0 change sets; SSM `image-tag` v9, `compose` v14, `caddyfile` v13; instance, AMI, launch time, volume and RDS unchanged |

Smoke was not run. The known port-80 self-hairpin limitation applies unchanged.

The deployed world is left `RESOLVED` and pinned by its own effects, with nothing in flight and
nothing waiting on a person. Its `APPROVAL_DEADLINE` timer, due `01:54:53Z`, belongs to an answered
request.

## 12. What this does not prove

- **Two runs are not a reliability rate.** R1 and R5 agreeing shows the canonical shape
  reproduces. It is demo readiness, not a production percentage.
- **The restart was a restart, not a stop**, as in R1. No answer, timer or effect was due while
  the worker restarted. Queued work surviving a stopped worker is R2's and R3's evidence, not
  R5's.
- **No refusal path was exercised live**: `STALE`, `EXPIRED`, `UNAUTHORIZED`, `NOOP`, and any
  restore refusal. No drift was manufactured.
- The `FINALIZE_RECOVERY` retry-ahead-of-echo is recorded, not changed.

## 13. The rehearsal series, and what G8 still needs

**All five predeclared deployed rehearsals have now passed** on `4529a802e34e`: R1
([g8-rehearsal-r1.md](g8-rehearsal-r1.md)), R2 ([g8-rehearsal-r2.md](g8-rehearsal-r2.md)), R3
([g8-rehearsal-r3.md](g8-rehearsal-r3.md)), R4 ([g8-rehearsal-r4.md](g8-rehearsal-r4.md)) and R5.
None failed, none was voided and none was repaired and rerun. That satisfies G8's "five complete
deployed rehearsals" item.

**G8 itself stays open.** Its other items are separate from the rehearsals and unaffected by
them. Among them are the first live `STALE` refusal
([phase7-closeout.md](phase7-closeout.md) §9 item 4) and the effect-set release condition of
`16/16`, with the headline `11/16` immutable. `new_roadmap.md` lists the rest.
