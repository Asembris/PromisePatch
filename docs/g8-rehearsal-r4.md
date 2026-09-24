# G8 deployed rehearsal R4 — the worker restarts after the case is resolved

Date: **2026-09-24**, host work between `20:40Z` and `20:48Z`. Entry at
`69079ad2f8f7afda53ca5e8c71f2a9bffa24e67c`: `main` equal to `origin/main`, tracked tree clean, and
the eleven known untracked artefacts left as they were. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`.

This is rehearsal #4 of the five that [g8-rehearsal-preparation.md](g8-rehearsal-preparation.md)
§3 predeclared, run against the frozen release candidate `4529a802e34e`
([phase7-closeout.md](phase7-closeout.md)). R4's restart point is **after settlement**:

1. restore, confirm and deliver, as in R1;
2. the owner presses APPROVE while the worker runs, and the loop runs to `RESOLVED`;
3. `restart worker`.

It was judged against §3.1 and R4's row in §3.2, unchanged: "a restart of a finished, pinned
world writes nothing: `PRESENT`/`REFUSED`, no new case, no effect". §10's amendment touches R3
only. Nothing was redefined here.

## 1. Verdict

**R4: PASS.** Every §3.1 checkpoint, exactly-once, untouched, privacy and restart item holds, and so
does R4's row:

- **Before the restart**, the full loop settled once. There was one literal `APPROVE` under
  `HUMAN_APPROVAL`, ten passed checks and `PROCEED`. `EXT-B` received one amendment with one key,
  the mirror converged, `pr-b` ended `RECOVERED` and the case `RESOLVED`.
- **The restart wrote nothing.** The new instance `…:02d04fb6` logged `worker.demo_case`
  `PRESENT` with `rolled: false`. The stability record was byte-identical in three readings:
  immediately before the restart, 13 s after it, and 83 s after it. Those readings cover the
  census, every audit and event row since the rehearsal base, the frozen reader's output, the
  order system's own store and the message counters. `audit_max` stayed 565 and `events_max` 1390.
  There was no Telegram send, amendment, request, decision, reply, case, re-anchor or
  error-level line.

This counts as **4 of 5** on image `4529a802e34e`, after R1 ([g8-rehearsal-r1.md](g8-rehearsal-r1.md)),
R2 ([g8-rehearsal-r2.md](g8-rehearsal-r2.md)) and R3 ([g8-rehearsal-r3.md](g8-rehearsal-r3.md)). No
product code, test, deployment file, infrastructure, IAM, SSM parameter or release was changed.

## 2. Authorisation, and what was spent

The owner authorised exactly:

- one guarded demo restore;
- one plan confirmation;
- one real Telegram approval message;
- the owner's own APPROVE;
- one worker restart, only after the case was `RESOLVED`.

**Each was used once.** The press was the owner's own action on the phone. The owner opened the
signed link from the one message, pressed APPROVE and reported:

> "i clicked on approve and did nothing else"

Nothing in the session opened, followed, simulated or wrote that answer. The restart was gated in
the same script that issued it:

- the case had to be `RESOLVED`, `pr-b` `RECOVERED` and the request `ANSWERED`;
- there had to be 0 open steps and 0 unsettled effects;
- a fresh stability record had to equal the settled one taken 35 s earlier.

All of these held (`gate=ok`).

**Access and privacy.** Host access was `ssm:StartSession` with `AWS-StartNonInteractiveCommand`
alone. Every census ran in a read-only transaction. Nothing printed in this session carried a chat
id, a bot token, a password or the approval link.

## 3. The frozen evidence reader

- **Extraction:** the reader was extracted from the appendix of
  [g8-rehearsal-r1.md](g8-rehearsal-r1.md) at `HEAD`: lines 385–523, the bytes between the
  `python` fences, with LF endings.
- **Hash:** sha256 **`c9731c8f8dedfe15fbc6af0c2db6a8d5d19ca090d7863f3d2e945b18220b0dd4`**. The
  extraction is byte-identical to R3's copy, compared with `cmp`.
- **On the host:** the host printed the same sha256 before every read, eight in all: entry,
  `PLANNED`, `CONFIRMED`, `SETTLED`, the restart gate, snapshots A and B, and the post-restart
  detail.
- **Edits:** never edited.

## 4. Timeline

| UTC | event |
|---|---|
| `20:40:11` | entry census: R3's case `7654d9d7-…` `RESOLVED`, outbox 3 all `DELIVERED`, **0 `PENDING`/`IN_FLIGHT`**, one customer bound, worker `sendMessage` lifetime 4 |
| `20:41:15.131` → `20:41:19.908` | **restore** (the one) |
| `20:41:29.158` → `20:41:31.501` | **plan confirmation** in `worker` (the one), 12 s after planning |
| `20:41:32.337` | the one `MESSAGE_SEND` delivered; request `SENT` `20:41:32.548` |
| `20:43:40.117` | the owner's APPROVE stored as one `customer-reply` inbox row |
| `20:43:40.345` → `20:43:47.502` | the running instance `…:8593cc32` consumes it; case `RESOLVED` |
| `20:44:17` | settled checkpoint and the pre-restart stability record |
| `20:44:52` | restart gate re-read: identical, `gate=ok` |
| `20:44:57.156` | **worker restart** issued (the one); `worker.stop` `20:44:57.258`, `FinishedAt` `20:44:57.586`, `StartedAt` `20:44:58.144`, `worker.start` `20:44:59.991` |
| `20:45:10.867` | post-restart snapshot A |
| `20:46:20.058` | post-restart snapshot B, 69.2 s after A |
| `20:47:28` | CloudWatch scan and control plane |

- **The restart** took 558 ms of downtime, from `FinishedAt` to `StartedAt`, on the same
  container `ef6428bb042b`.
- **The case** had been `RESOLVED` for 69.7 s when the restart was issued.
- **The approval window** closes `2026-09-25T01:41:16Z`. The deadline check ran at `20:43:40Z`.
- **The finish** came well before the `22:00Z` bound.

## 5. Entry

| | measured |
|---|---|
| Stack | `promisepatch-prod` `UPDATE_COMPLETE`, last updated `16:00:45Z`, **0 change sets** |
| Image | `ImageTag`, `DeclaredImageTag` and SSM `image-tag` (v9) all `4529a802e34e`; SSM `compose` v14 and `caddyfile` v13 byte-equal to HEAD |
| Instance / volume / RDS | `i-087c742587f83d61d` `t4g.small` `ami-0fa4996c14e7d501e`, launched `2026-09-18T10:19:33Z`, IMDSv2 required, hop limit 2 / `vol-0f330aaa62e637ef6` encrypted / `db-U2JWQBTINX6W6GAB56EOTHOCSM` private, encrypted |
| Host | `boot_id` `109dccdf-b7fb-4882-8b28-c963b2f0f7b9`, up since `16:02:33` |
| Containers | all on `4529a802e34e` (`caddy:2.10-alpine`), 0 restarts; worker `ef6428bb042b`, instance `…:1:8593cc32` (R3's post-start instance) |
| `/readyz` | ready; migrations at head `0009_human_plan_approval` |
| Provider | `telegram` in `api` and `worker`, bot token present (value not read) |
| Effects | **0 `PENDING`/`IN_FLIGHT`**; nothing waiting on a person |
| Binding | `cus-tomas` bound (address length 10), the other five at 4-character placeholders |
| Counters | worker `sendMessage` 4, `api.telegram.org` 200s 4, non-200 0, `getUpdates` 0 |
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
before:   fixture=hollow-oak cases=1 live=0 outbox=3 unsettled=0 requests=1 decisions=1 approvals=1 replies=1 audit=520 events=645 bound=True
after:    fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=534 events=664 bound=True
anchor:   2026-09-24T20:41:16.929575+00:00
digest:   caca0e4f69b1b7f0e4d2f112eb5ada1d8cc951ddc0db5f4f4e566840ca70ed8f
rows:     160
orders:   6 reset in the external order system
case:     43b75690-c5b2-50ca-8fd0-08df353bc170
state:    PLANNED
binding:  restored
ledgers:  grew only
result:   restored; no plan was confirmed and no message was sent
restore_exit=0
```

**`PLANNED`**, checked by `pp case-status` and SQL (`partition_gate=ok`):

- `pr-a` `AUTO_RECOVERABLE` `R-PREAPPROVED` `almond-3 → -4` (no approval);
- **`pr-b` `APPROVAL_REQUIRED` `R-VISIBLE-ASK` `rose-2 → -3`, the only approval-required option**;
- `pr-c` `BLOCKED` `NOSUB_CONSTRAINT`, `pr-d` `BLOCKED` `NO_PREAUTHORED_VARIANT`;
- `pr-e`/`pr-f` `UNAFFECTED` `R-UNREACH`.

The rest of the `PLANNED` state:

- one unfired `PLAN_AUTO_ESCALATION` timer due `20:51:19Z`;
- outbox, requests, decisions, `plan_approvals`, replies and inbox all 0;
- all six orders v1;
- tasks: `task-ol-e` `STARTED`, the other five `SCHEDULED`;
- audit 520 → 534, contiguous;
- `sendMessage` still 4.

The binding re-verified through `_verify_destination`: `returned_id_matches_stored=True`,
`chat_type=private`, `@PromisePatchDemoBot`, no message. The public `GET /api/cases` and
`GET /api/cases/{id}` carried no address. The order simulator answered `200`.

**`CONFIRMED`** (`waiting_gate=ok`). `pp confirm-plan --worker maya` in `worker` with the read-out
`plan_id` (`89daf997…`) gave `EXECUTING`, applying 1, escalated 2, awaiting approval 1, and exit
`0`:

- `plan_approvals` 1, `OPERATOR_CONSOLE`; audit 535 `PLAN_APPROVED` and 536 `PLAN_CONFIRMED`, both
  `HUMAN_APPROVAL`, actor `WORKER maya`;
- `pr-a` applied under `CONSTRAINT`: one `ORDER_AMEND` `DELIVERED` at attempt 1, `EXT-A` v1 → v2
  `almond-4`, the mirror converged (audit 543), `pr-a` `RECOVERED`;
- `pr-b` `WAITING_FOR_CUSTOMER`, request `8ab6cdf8-…` `SENT`, `provider_ref=True`;
- `pr-c`/`pr-d` `ESCALATED`, `task-ol-c`/`task-ol-d` `HELD`; **`task-ol-e` still `STARTED`, not
  held**; case `WAITING`;
- **one `MESSAGE_SEND` `DELIVERED` at attempt 1**, key `pp:approval:8ab6cdf8-…`; Telegram answered
  `HTTP/1.1 200 OK`; `sendMessage` 4 → **5** (+1), `api.telegram.org` non-200 0, `getUpdates` 0;
- the unrelated digest `a132b8dc…`.

Every step after the confirmation was executed by the running instance `…:8593cc32`.

## 7. The customer's answer, and the settled state before the restart

The owner's press arrived while the worker ran. The running instance took the inbox row within
228 ms and carried it through:

| audit / event | row |
|---|---|
| inbox | `customer-reply` `RECEIVED` `20:43:40.117` → `PROCESSED` `20:43:40.345`, by `…:8593cc32` |
| audit 546 | `APPROVAL_DECISION_RECORDED` by `CUSTOMER cus-tomas`, **`HUMAN_APPROVAL`**: `APPROVE`, parser `LITERAL`, request `ANSWERED` |
| audit 548–557 | ten `REVALIDATION_CHECK`, **all `passed: true`**, against a fresh snapshot (`as_of` 1368), written after the decision |
| audit 558 | `RECOVERY_REVALIDATED` `HUMAN_APPROVAL`, **`outcome: PROCEED`**, `checks_passed: 10` |
| audit 561 | `RECOVERY_APPLIED` `HUMAN_APPROVAL` `rose-2 → rose-3`, key `pp:amend:a636ca47-…:21eaefde-…:1` |
| outbox | one `ORDER_AMEND` `DELIVERED` at **attempt 1**, `EXT-B` `expected_version 1` → `external_version 2`, `replayed False`, ref `amd-f780c2ff1b1d` |
| audit 563 | `ORDER_MIRROR_UPDATED`: `ol-b` `rose-3`, `AMENDED`, v2 |
| audit 564 | `RECOVERY_COMPLETED` `HUMAN_APPROVAL`, `pr-b` `RECOVERED` |
| events 1386–1390 | `track.recovered`, **`case.resolved`** `20:43:47.502` |

The ten checks, in `pp case-status` form:

1. track `WAITING_FOR_CUSTOMER`, case `WAITING`;
2. `ACCEPTED @ v1`;
3. `rv-raspberry-rose-2`;
4. constraint snapshot `14fdbf01…` unchanged;
5. substitute `3.200 ≥ 2.200`;
6. `SCHEDULED` and start `2026-09-25T02:41:16Z`, ahead;
7. `now` `20:43:40Z` ≤ deadline `01:41:16Z`;
8. sender `tg:***` is the approval channel;
9. `LITERAL`;
10. one unspent decision for this request, track and option.

**The settled state recorded before the restart** (`20:44:17Z`):

| | state |
|---|---|
| case | `43b75690-…` `RESOLVED` v17, attention (the two `BLOCKED` tracks) |
| tracks | `pr-a` `RECOVERED`, `pr-b` `RECOVERED`, `pr-c`/`pr-d` `ESCALATED`, `pr-e`/`pr-f` `UNAFFECTED` |
| request | `8ab6cdf8-…` `ANSWERED`, `decided=True`; 1 decision, 1 reply |
| outbox | exactly 3, all `DELIVERED` at attempt 1, 3 distinct keys: `ORDER_AMEND` `EXT-A`, `MESSAGE_SEND`, `ORDER_AMEND` `EXT-B`; **0 unsettled** |
| inbox | 3, all `PROCESSED`: two `external-order-system`, one `customer-reply` |
| timers | one `APPROVAL_DEADLINE` for the answered request, due `2026-09-25T01:41:16Z`, unclaimed and unfired |
| steps | 16, 0 open, 0 failed; attempts all 1 except `CONFIRM_PLAN` 0 (inline), `RECONCILE_CASE` `SKIPPED`, and `FINALIZE_RECOVERY` 2 for `pr-a` and 3 for `pr-b` |
| orders | mirror and order-system store equal: `EXT-A` v2 `AMENDED` `almond-4`, `EXT-B` v2 `AMENDED` `rose-3`, `EXT-C`–`EXT-F` v1 `ACCEPTED` |
| tasks | `task-ol-a`/`-b`/`-f` `SCHEDULED`, `task-ol-c`/`-d` `HELD`, `task-ol-e` `STARTED` never held |
| counts | `audit_max` 565, `events_max` 1390, `plan_approvals` **still 1**, cases 1 |
| digests | unrelated `a132b8dc4f99731233274dac40231f9aadbfa2d7e097df2f12b32bded7fcec18`, **equal to `CONFIRMED`**; `pr-e`/`pr-f` `adfa6ac1…` equal to `PLANNED`; attributed audit, events, outbox and requests all 0 |
| messages | `sendMessage` 5, `worker.telegram.sent` 5, `api.telegram.org` 5 all 200, `getUpdates` 0 |
| worker | container `ef6428bb042b`, `StartedAt` `20:30:58.991`, instance `…:1:8593cc32`, pid 146374 |
| errors | 0 error-level lines in the worker log since the confirmation |

The stability record is 183 lines, sha256 prefix **`667054e56208f888`**.

**The `FINALIZE_RECOVERY` retries are not effect retries.** Each `RETRY_SCHEDULED` waits for the
order system's own echo to reach the mirror before settling the track. That is the echo race R2
and R3 also recorded. Both `ORDER_AMEND` rows stay at attempt 1, and each key appears exactly once.

## 8. The restart

The restart was taken by the documented mechanism,
`docker compose --env-file env/stack.env restart worker`. It touched the worker only.

```text
restart_issued=2026-09-24T20:44:57.156Z
 Container promisepatch-worker-1  Restarting
 Container promisepatch-worker-1  Started
restart_exit=0 restart_returned=2026-09-24T20:44:58.159Z
{"worker": "ef6428bb042b:1:8593cc32", "event": "worker.stop", "timestamp": "2026-09-24T20:44:57.257778Z"}
{"action": "PRESENT", "case_id": "43b75690-c5b2-50ca-8fd0-08df353bc170", "state": null, "detail": "this world's case already exists; nothing was touched", "rolled": false, "event": "worker.demo_case", "timestamp": "2026-09-24T20:44:59.990596Z"}
{"worker": "ef6428bb042b:1:02d04fb6", "event": "worker.start", "timestamp": "2026-09-24T20:44:59.990728Z"}
```

| | before | after |
|---|---|---|
| container | `ef6428bb042b` | `ef6428bb042b` (same) |
| `StartedAt` | `20:30:58.991` | **`20:44:58.144`** |
| pid | 146374 | **158352** |
| instance | `…:1:8593cc32` | **`…:1:02d04fb6`** |
| `RestartCount` | 0 | 0 (a requested restart, not a crash) |
| image | `4529a802e34e` | `4529a802e34e` |
| `migrate` container | `StartedAt` `20:30:56.167`, exit 0 | **unchanged**; 0 `Running upgrade` lines since the restart |

**`migrate` did not run.** `compose restart` restarts the named service alone, unlike R2 and R3's
`start`, which re-ran the no-op `migrate`. The other five containers kept their `StartedAt` and
restart counts.

## 9. After the restart: two snapshots

Each snapshot re-read the full stability record: the census, every audit and event row since the
rehearsal base, every revalidation row, the frozen reader, the order store, the message counters and
the case list. `db_now` was excluded.

| reading | at | lines | sha256 prefix | diff |
|---|---|---|---|---|
| settled (pre-restart) | `20:44:17Z` | 183 | `667054e56208f888` | — |
| restart gate | `20:44:52Z` | 183 | equal | vs settled: **empty** |
| snapshot A | `20:45:10.867Z` | 183 | `667054e56208f888` | vs settled: **empty** (`diff` exit 0) |
| snapshot B | `20:46:20.058Z` | 183 | `667054e56208f888` | vs A: **empty**; vs settled: **empty** |

Snapshot B was taken 69.2 s after A and 83 s after the restart. Checked item by item against the
R4 stability requirements:

| requirement | evidence at snapshot B |
|---|---|
| case stays `RESOLVED` | `43b75690-…` `RESOLVED` v17, the same version |
| `pr-b` stays `RECOVERED` | `RECOVERED`; `pr-a` `RECOVERED`; no settled track reopened, all six track rows identical |
| no request, decision or reply duplicate | requests 1, decisions 1, replies 1, inbox 3 all `PROCESSED` |
| no Telegram resend | `sendMessage` 5, `worker.telegram.sent` 5, `api.telegram.org` 5, `getUpdates` 0; `MESSAGE_SEND` 1 at attempt 1 |
| no amendment replay | `order_amend` 2, both at attempt 1; no new `workflow.effect.delivered` or `worker.order_system.amended` line |
| no new external effect or key | outbox 3, `distinct_keys` 3; the `EXT-B` key `pp:amend:a636ca47-…:21eaefde-…:1` still appears once |
| mirror and order state unchanged | mirror and store both `EXT-A`/`EXT-B` v2 `AMENDED`, `EXT-C`–`EXT-F` v1 `ACCEPTED` |
| unrelated digests unchanged | unrelated `a132b8dc…`, `pr-e`/`pr-f` `adfa6ac1…`, every sub-digest equal; attributed rows 0 |
| no re-anchor or extra case | fixture anchor `20:41:16.929575Z`, digest `caca0e4f…` unchanged; cases 1; `reanchor` 0 in the worker log; `/readyz` anchor unchanged |
| no row written at all | `audit_max` 565, `events_max` 1390, steps 16, timers 1 |
| binding unchanged | `cus-tomas` bound, length 10, re-verified (`returned_id_matches_stored=True`, `chat_type=private`, no message); five placeholders |
| infrastructure unchanged | see §11 |

The worker log since the restart holds exactly three lines, `worker.stop`, `worker.demo_case`
and `worker.start`, with 0 error-level lines. The new instance id appears exactly once, on its own
`worker.start`. **No step, effect or timer ran after the restart**, so there is nothing a new
instance could have executed.

**No timer fired and no no-op occurred after settlement.** The one remaining timer,
`APPROVAL_DEADLINE` for the answered request, is due `2026-09-25T01:41:16Z`, outside this
rehearsal. It stayed unclaimed through both snapshots. What it does when it falls due is not
observed here.

## 10. Exactly-once, untouched, privacy

**Exactly-once over the rehearsal.** This rehearsal wrote:

- outbox exactly 3, all `DELIVERED` at attempt 1, with 3 distinct keys;
- `sendMessage` exactly +1 (4 → 5), `getUpdates` 0;
- 1 request, 1 decision and 1 reply;
- exactly one case;
- `plan_approvals` 1.

**The restart added nothing**: no effect, step retry, case, plan approval or row.

**Untouched.** Both the mirror and the order system hold `EXT-C` to `EXT-F` at v1 `ACCEPTED`.
`pr-e` and `pr-f` stay `UNAFFECTED`, with 0 audit rows, events, outbox rows and requests attributed
to them. The unrelated digest is equal at `CONFIRMED`, `SETTLED`, snapshot A and snapshot B.

**Privacy.** The five container logs were scanned at entry, after dispatch, at settlement and after
the restart. Every scan found:

- 0 token-shaped strings;
- 0 unredacted query or path forms;
- 0 address lines, 0 chat-id patterns and 0 bot-token shapes;
- this rehearsal's link, fingerprint `1a2e72ce…`, present 0 times whole, as payload or as
  signature.

The redacted forms are present in both `caddy` and `api`, as designed.

CloudWatch `/promisepatch/prod` since `20:40Z`, read from the operator machine: 164 events across
4 streams, 0 token-shaped, 0 chat-id, 0 bot-token, 0 unredacted; `approve=REDACTED` 8,
`approval/REDACTED` 14.

The public case detail after settlement carries a `provider_ref` key with the ADR-0021 masked value
`telegram:***`, and `address_present=False`. At `PLANNED` the key was absent only because no effect
existed yet.

## 11. Health and infrastructure, at the end

| | state |
|---|---|
| `/healthz` / `/readyz` | `4529a802e34e`; ready; migrations at head; fixture anchor `20:41:16Z` |
| containers | all on `4529a802e34e` (`caddy:2.10-alpine`), 0 restarts; only the worker's `StartedAt` moved |
| host | `boot_id` `109dccdf-…` throughout: **no reboot**; `converge.sh` `09105b10…` and `channel.env` `c3a6e4de…` unchanged; certificate and key dated `2026-09-13 18:35`; all three Docker volumes present |
| control plane at `20:47Z` | stack `UPDATE_COMPLETE` `16:00:45Z`, 0 change sets; SSM `image-tag` v9, `compose` v14 and `caddyfile` v13 unchanged; instance, AMI, launch time, IMDSv2, volume and RDS identical to entry |

Smoke was not re-run. The known port-80 self-hairpin limitation applies unchanged
([phase7-closeout.md](phase7-closeout.md) §4).

## 12. What this does not prove

- **The restart was taken on a settled world.** R4 proves that a settled world stays settled. It
  does not re-prove resumption, which is R1–R3's.
- **The `APPROVAL_DEADLINE` timer for an answered request** was not observed firing. It falls due at
  `01:41Z`, after this rehearsal.
- **No refusal path** was exercised live, and no drift was manufactured.
- **The press arrived while the worker ran.** This rehearsal adds nothing to R3's stopped-worker
  answer.

## 13. Next

**R5**: the repeat of R1's restart point, while waiting for consent, on `4529a802e34e`. It needs the
owner's fresh authorisation for its restore, plan confirmation, one real approval message and its
restart, and it uses the frozen reader `c9731c8f…`. Nothing from R4 blocks it. The world is left
settled: nothing is in flight and nothing waits on a person.
