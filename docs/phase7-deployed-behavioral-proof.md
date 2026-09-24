# Phase 7 — the deployed release candidate, proved through the real customer loop

Date: **2026-09-24**. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything was
read and unchanged throughout.

[phase7-rc-deployment.md](phase7-rc-deployment.md) put `abbbd11006f7` on the host and section 8
there said what it did not prove: no amendment dispatched, no message sent, ADR-0026's
first-dispatch gate never reached. This record is section 9 of that document, performed. The
already-deployed release candidate was driven once through the whole customer loop — restore,
plan confirmation, one real Telegram message, a real customer's web approval, revalidation,
amendment, convergence — **without a release, a redeploy, an IAM change or a source edit**.

**The loop closed exactly as specified, and it exposed one P1 disclosure defect that is recorded
here and not repaired** (section 9): the approval link's possession token, whose payload encodes
the customer's Telegram chat id, is written verbatim into the `api` and `caddy` access logs,
which ship to CloudWatch.

The project owner authorised exactly four things: one guarded demo-world restore, confirming the
canonical plan, one real Telegram approval request to the bound canonical customer, and normal
worker execution of the amendment that followed. Each was used once. The customer's decision
was the project owner's own press on the phone; nothing in this session opened, followed,
simulated or wrote it.

## 1. Entry

| | value |
|---|---|
| HEAD / `origin/main` | `45974111cba9ad8aab73721e98c9b938ac718bfd`, equal; tracked tree clean; the eleven known untracked artefacts untouched |
| CI at HEAD | `pr` **success**, all 13 jobs green; `effect sets (expected red until 16/16)` **failure**, as expected |
| Stack | `promisepatch-prod`, `UPDATE_COMPLETE`, last updated `2026-09-24T12:54:54Z`, **0 change sets** |
| `ImageTag` / SSM `image-tag` / `/healthz` `image` | `abbbd11006f7` / `abbbd11006f7` / `abbbd11006f7` |
| Host | `i-087c742587f83d61d`, `t4g.small`, `ami-0fa4996c14e7d501e`, launched `2026-09-18T10:19:33Z`, IMDSv2 required, volume `vol-0f330aaa62e637ef6` |
| Host `boot_id` / `uptime -s` | `fe436521-2557-41e8-bd58-a41a3f099cea` / `2026-09-24 12:56:36` — the Phase 7 rollout reboot |
| RDS | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, not public, encrypted |
| Containers | `api`, `worker`, `mcp`, `order-simulator` on `…:abbbd11006f7`, `caddy` unchanged, `migrate` exited `0`; **0 restarts** each |
| `/readyz` | ready; migrations at head, `0009_human_plan_approval` |
| Provider | `telegram` in `api` and `worker`; bot token and link secret present (values not read) |
| World | one case, `eae07b11-…`, `RESOLVED` with owner attention — the Phase 7 restore's case, escalated `PLAN_UNCONFIRMED` at `13:09:12Z` |
| Effects | outbox **0**, `PENDING`/`IN_FLIGHT` **0**; requests, decisions, plan approvals, replies **0** |
| Worker log | `sendMessage` **0**, `getUpdates` **0** |

Every value above equals [phase7-rc-deployment.md](phase7-rc-deployment.md) section 7's
after-restore column.

## 2. How the host was reached

`ssm:StartSession` with `AWS-StartNonInteractiveCommand` alone, as before. Each script was
CRLF-stripped, gzipped and base64-encoded on the operator machine, decoded on the host and run as
root with stdin from `/dev/null`. The destructive script ran under `setsid -w` with its output
kept in a host file, so a dropped operator connection could not have killed it between the
restore and the confirmation and spent the ten-minute plan window.

Every database read ran in the deployed `worker`, inside a `READ ONLY` transaction, and masked
its output before printing: the stored address, any `telegram:`/`tg:` id and any URL. Each read
ended with a guard asserting the stored address was absent from everything it printed; the
guard read `False` every time. The `MESSAGE_SEND` payload, which carries the approval link, was
never printed — only its key names.

## 3. The restore — once, gated

The host-local env union of [demo-world-restore.md](demo-world-restore.md) §4:
`PP_MIGRATION_DATABASE_URL` and both demo passwords read out of `env/migrate.env` on the host,
`PP_ALLOW_FIXTURE_RESET=true` named explicitly. No credential entered the operator's shell.

A `--dry-run` ran first. The confirmed run was reachable only if it exited `0` and reported
`binding: restored`, `outbox=0 unsettled=0` and `fixture=hollow-oak`:

```text
action:   inspected
before:   fixture=hollow-oak cases=1 live=0 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=277 events=367 bound=True
binding:  restored (would be carried across)
dry_gate=ok
```

Then, once, `14:13:19.192Z` → `14:13:24.719Z`:

```text
pp restore-demo-world --confirm destroy-and-restore          -> exit 0
action:   restored
before:   fixture=hollow-oak cases=1 live=0 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=277 events=367 bound=True
after:    fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=291 events=386 bound=True
anchor:   2026-09-24T14:13:21.604905+00:00
local:    2026-09-24T15:13:21.604905+01:00 Africa/Tunis
digest:   66ace458d9c63be876b46b118a5a637f35454fbda9b3f4123a5f0afc32e11d33
rows:     160
orders:   6 reset in the external order system
case:     74fb298d-914c-5839-9a3c-acdfa0fd41f0
state:    PLANNED
binding:  restored
ledgers:  grew only
result:   restored; no plan was confirmed and no message was sent
```

The structured log records `cases_destroyed=1`, `provisioning=OPENED`, `rolled=False` and
`demo customer channel bound … audit_seq=291 … customer_id=cus-tomas` — no address.

| requirement | measured, by SQL and the order system's own API |
|---|---|
| fresh canonical `PLANNED` case | `74fb298d-…`, `PLANNED`, `needs_owner_attention = false`, the only case |
| binding restored | `cus-tomas` address length 10; the other five at their four-character placeholders |
| six orders reset to v1 | mirror: every order `external_version 1`, `ACCEPTED`, original recipe; order-system store: `EXT-A`…`EXT-F` all `v1 ACCEPTED`; order-system events since the load: **0** |
| canonical split (`pp case-status`) | `pr-a` `AUTO_RECOVERABLE` `R-PREAPPROVED`, `almond-3 → -4` (no approval); **`pr-b` `APPROVAL_REQUIRED` `R-VISIBLE-ASK`, `rose-2 → rose-3` (approval required) — the only one**; `pr-c` `BLOCKED` `NOSUB_CONSTRAINT`; `pr-d` `BLOCKED` `NO_PREAUTHORED_VARIANT`; `pr-e`, `pr-f` `UNAFFECTED` `NOT_REACHABLE` |
| ledgers only grew | `audit_events` 277 → 291, `seq` 1–291 contiguous; `domain_events` 367 → 386 |
| outbox and authority counters | outbox 0, requests 0, decisions 0, plan approvals 0, replies 0, inbox 0 |
| restore sent nothing | worker log `sendMessage` **0**, `worker.telegram.sent` **0**, effects dispatched **0** |
| no reboot | `boot_id` identical before and after |

The confirmation was gated on the case matching this split. The script refused to confirm
unless: the restore exited `0`, the binding was restored, the ledgers only grew, the after-census
was clean, there was exactly one case in `PLANNED`, exactly one `(approval required)` option
existed and it was `pr-b`'s `rose-2 → rose-3`, all six bands were canonical, and a 64-character
plan identity was read. Every condition held.

## 4. The plan confirmation — inside the window

The case reached `PLANNED` at `14:13:24.042Z`; §14.1's ten-minute window would have closed at
`14:23:24Z`. Confirmed **7.3 seconds** after planning, on the operator console, quoting the plan
identity `case-status` printed:

```text
pp confirm-plan --case 74fb298d-… --worker maya --plan 000759736f67…5c106c85913e1441 --command-id d0077bde-…
plan.approval.recorded      channel=OPERATOR_CONSOLE worker=maya
recovery.plan.confirmed     applying=1 awaiting_approval=1 escalated=2
state:     EXECUTING
accepted:  now
```

| | |
|---|---|
| exactly one customer approval, for `EXT-B` | `awaiting approval: 1`, track `29b19571-…` = `pr-b` / `EXT-B`; `approval_requests` **1** |
| the worker's approval | `plan_approvals` 1, `OPERATOR_CONSOLE`, `maya`, `14:13:31.321610Z`; audit 292 `PLAN_APPROVED` and 293 `PLAN_CONFIRMED`, both **`HUMAN_APPROVAL`**, actor `WORKER maya` |
| the escalations | `pr-c`, `pr-d` → `ESCALATED` to the owner; `task-ol-c`, `task-ol-d` → `HELD` |
| the plan timer | no `PLAN_AUTO_ESCALATION` remained; the only timer afterwards is the request's `APPROVAL_DEADLINE` |

`pr-a`'s pre-approved substitution then ran on the worker's own cycle, as the canonical partition
predicts: `ORDER_AMEND` `DELIVERED` at attempts 1, `amd-ce48a4d0143d`, `EXT-A` `v1 → v2`
`rv-raspberry-almond-4`, `pr-a` `RECOVERED`. Its authority is **`CONSTRAINT`** under
`R-PREAPPROVED` (audit 294, 299). It changes an order and messages nobody.

## 5. The one Telegram message

The durable worker dispatched on its own cycle. **Nothing was sent by hand.**

| requirement | evidence |
|---|---|
| Telegram 200 | `api.telegram.org` responses in the worker log: **1 × 200**, **0** non-200 |
| one `MESSAGE_SEND`, `DELIVERED` | one row, key `pp:approval:ce09acca-d4ed-5532-a63e-a4bf0b5ac838`, created `14:13:32.658Z`, delivered `14:13:33.190898Z` |
| attempts = 1 | `attempts 1`, `last_error null` |
| provider ref persisted | `telegram:<id>:5` on the outbox row and on the request (`provider_ref` present, message id `5`) |
| no duplicate send | `sendMessage` **1**, `worker.telegram.sent` **1**, `getUpdates` **0** over the worker's whole lifetime; `MESSAGE_SEND` rows 1; distinct idempotency keys = rows |
| the request | `ce09acca-…`, `OPT-E5EBFF`, `SENT` at `14:13:33.383595Z`, deadline `19:13:21.604905Z`, captured order v1, recipe `rv-raspberry-rose-2`, constraint hash `98bb654f260a…`, fingerprint `8da96797ab3b…` |
| the case | `PLANNED → EXECUTING → WAITING`; `pr-b` `WAITING_FOR_CUSTOMER` |

`pp case-status` now prints the request's reference as `telegram:***`, as ADR-0021 intends.

Here the session **stopped** and asked the project owner to open the signed link and press
APPROVE.

## 6. The customer's decision

The project owner opened the link in the delivered message on the phone and pressed **APPROVE**.
The `api` log shows the page's reads, then **one** `POST /api/customer/approval/<token>` answered
`202 Accepted` at `14:14:33.9Z` (`api.customer_approval.answered`, `stored: true`,
`phase: RECEIVED`), then the page's reads again.

| requirement | evidence |
|---|---|
| the same request became answered | `ce09acca-…`: `SENT → ANSWERED`, `decided = true` |
| exactly one decision | `approval_decisions` **1** |
| literal `APPROVE` | `decision APPROVE`, `parser LITERAL`, `raw_text yes`, received `14:14:34.651297Z` |
| possession, not identity | `provider_message_id` begins `link:` — `approvals.link_message_id(request, channel)`, independent of the answer |
| sender matched the channel asked | `sender_identity = customer_channel`: **true** (compared in SQL; neither value printed) |
| authority | audit 303 `APPROVAL_DECISION_RECORDED`, actor **`CUSTOMER cus-tomas`**, authority **`HUMAN_APPROVAL`**, `after: {decision: APPROVE, parser: LITERAL, request_state: ANSWERED}` |
| one reply, one inbox row | `inbound_replies` 1; `inbox_events` of source `customer-reply` **1**, `PROCESSED` |
| no worker approval spent | `plan_approvals` still **1** — a customer's yes spends no plan authority (ADR-0018) |
| Telegram inbound played no part | `getUpdates` **0** |

**A duplicate answer cannot overwrite it.** This is proved by what the database enforces, read
from the live catalogue, and **not** by a second live press, which was not made:

- `approval_decisions`: `UNIQUE (request_id)` and `UNIQUE (provider_message_id)`.
- `inbound_replies`: `UNIQUE (provider_message_id)`.
- `inbox_events`: `UNIQUE (source, provider_event_id)`.

The link's record id is derived from the request and the channel, never from the answer. So a
second press of either button proposes a key that already exists and writes nothing, and a
decline cannot be pressed on top of this approval.

## 7. Revalidation, on current data

`RECEIVE_CUSTOMER_REPLY` (`14:14:34.610Z` → `.651Z`) handed the stored text to the literal parser,
and `REVALIDATE_RECOVERY` then wrote **ten** `REVALIDATION_CHECK` audit rows (seq 305–314). Every
row is actor `SYSTEM`, authority `NONE`, because the checks are evidence and evidence authorises
nothing.

| # | check | expected | actual | |
|---|---|---|---|---|
| 1 | track and case are waiting | `track=WAITING_FOR_CUSTOMER case=WAITING` | same | pass |
| 2 | order state and version unchanged | `ACCEPTED\|AMENDED @ v1` | `ACCEPTED @ v1` | pass |
| 3 | pinned recipe version unchanged | `rv-raspberry-rose-2` | `rv-raspberry-rose-2` | pass |
| 4 | constraint snapshot unchanged | `98bb654f…dd23ca3` | `98bb654f…dd23ca3` | pass |
| 5 | substitute still available | `>= 2.200` | `3.200` | pass |
| 6 | production task not started and still ahead | `SCHEDULED\|HELD by 74fb298d-… and start > 2026-09-24T14:14:34.758916Z` | `SCHEDULED and start 2026-09-24T20:13:21.604905Z` | pass |
| 7 | approval deadline not passed | `now <= 2026-09-24T19:13:21.604905Z` | `2026-09-24T14:14:34.758916Z` | pass |
| 8 | sender is the order's approval channel | the request's channel | the same, via the same | pass |
| 9 | decision came from the literal parser | `LITERAL` | `LITERAL` | pass |
| 10 | one unspent decision, bound to this plan | one decision for `ce09acca-…` on track `29b19571-…` option `e5ebff4b-…` | `1 decision(s)` for the same three | pass |

Outcome **`PROCEED`**: audit 315 `RECOVERY_REVALIDATED`, `checks_passed: 10`, authority
**`HUMAN_APPROVAL`**, rule `R-VISIBLE-ASK`. Domain event 816 `track.revalidation_passed`.

**This was a re-read, not a replay.** The step's snapshot is `as_of 812`, which is the
`case.revalidation_ready` event written in the same transaction as the decision (events 808
`approval.reply_received`, 810 `approval.decided`, 812). The check instant, `14:14:34.758916Z`,
is **107.6 ms after** the decision instant `14:14:34.651297Z`. Checks 2–5 compare that fresh read
against what the request captured at `14:13:33Z`; check 6 reads the live task against the
database clock. Reality had not changed, so every check passed and the result is `PROCEED`.

## 8. The amendment, convergence and the final state

| requirement | evidence |
|---|---|
| applied under the customer's authority | audit 317 `RECOVERY_APPLIED` and the `APPLY_RECOVERY` step result both carry **`HUMAN_APPROVAL`**, rule `R-VISIBLE-ASK`, `rose-2 → rose-3` |
| **first dispatch before EXT-B's production start** (ADR-0026 passing live) | the `ORDER_AMEND` for `ol-b` was claimed at **attempts 1** and delivered at `14:14:35.155413Z`; `task-ol-b` starts `2026-09-24T20:13:21.604905Z`, **5 h 58 min ahead**; `last_error null`, so `refuse_if_production_started` let it through |
| one idempotency key | `pp:amend:29b19571-69c1-5029-98ed-c2c24a0713ae:e5ebff4b-627d-5943-b956-d110bd1748f7:1` — one outbox row; the order system's own event log holds **exactly one** event carrying that command key |
| the provider's answer | `amd-741ea23094da`, `EXT-B`, `ol-b`, `rv-raspberry-rose-3`, `previous_version 1`, `external_version 2`, `AMENDED`, `replayed false` |
| `EXT-B` v1 → v2 | order-system store: `EXT-B v2 AMENDED ol-b=rv-raspberry-rose-3`; event `order.updated` at `14:14:35.143393Z`, delivery `DELIVERED` |
| mirror converged | inbox `external-order-system` event `PROCESSED` `14:14:35.341Z`, audit 320 `ORDER_MIRROR_UPDATED`; mirror `EXT-B` **v2 `AMENDED`**, `ol-b → rv-raspberry-rose-3` |
| `pr-b` `RECOVERED` | `FINALIZE_RECOVERY` attempt 1 `RETRY_SCHEDULED` at `14:14:35.287Z` — the order system's echo had not arrived yet (it was mirrored at `.383Z`) — and attempt 2 `COMPLETED` at `14:14:36.500Z`; track **`RECOVERED`**; audit 321 `RECOVERY_COMPLETED`, **`HUMAN_APPROVAL`** |
| case `RESOLVED` | `WAITING → REVALIDATING → RECONCILING → RESOLVED` at `14:14:36.434238Z`; `RECONCILE_CASE` `SKIPPED` because the transition that settled the last track had already finished the case; `needs_owner_attention = true`, from `pr-c` and `pr-d` |
| completion authority | every row of `pr-b`'s recovery after the decision — 303, 315, 317, 321 — is **`HUMAN_APPROVAL`** |

The retried finalize is the designed wait for the order system to echo an amendment it has
accepted (the comment on `pp case-status`'s mirror line describes it), not a failure: one effect,
one attempt, one order-system event.

### Authority provenance, whole case

| seq | type | actor | authority | rule |
|---|---|---|---|---|
| 292 | `PLAN_APPROVED` | `WORKER maya` | `HUMAN_APPROVAL` | — |
| 293 | `PLAN_CONFIRMED` | `WORKER maya` | `HUMAN_APPROVAL` | — |
| 294 | `RECOVERY_APPLIED` (`pr-a`) | `SYSTEM` | `CONSTRAINT` | `R-PREAPPROVED` |
| 296 | `APPROVAL_REQUESTED` (`pr-b`) | `SYSTEM` | `CONSTRAINT` | `R-VISIBLE-ASK` |
| 299 | `RECOVERY_COMPLETED` (`pr-a`) | `SYSTEM` | `CONSTRAINT` | `R-PREAPPROVED` |
| 303 | `APPROVAL_DECISION_RECORDED` | `CUSTOMER cus-tomas` | `HUMAN_APPROVAL` | — |
| 315 | `RECOVERY_REVALIDATED` (`pr-b`) | `SYSTEM` | `HUMAN_APPROVAL` | `R-VISIBLE-ASK` |
| 317 | `RECOVERY_APPLIED` (`pr-b`) | `SYSTEM` | `HUMAN_APPROVAL` | `R-VISIBLE-ASK` |
| 321 | `RECOVERY_COMPLETED` (`pr-b`) | `SYSTEM` | `HUMAN_APPROVAL` | `R-VISIBLE-ASK` |

Every other row since the fixture load is `NONE`. The two human approvals are distinct in actor,
table and vocabulary: a worker's plan approval (`plan_approvals`, `OPERATOR_CONSOLE`) and a
customer's consent (`approval_decisions`, `LITERAL`).

### Unrelated promises and orders, unchanged

A SHA-256 digest over the following was taken after the message was sent and before the customer
answered, then again at the end:

- every track except `pr-b`'s;
- every order except `EXT-B`, with their lines and production tasks;
- the five other customers' channel rows.

| | digest |
|---|---|
| after dispatch, before the approval | `fa29e5515bc26b551c34f69ebbb4f30eb5cb7ea4cbf559b42771937b9aeb370e` |
| final | `fa29e5515bc26b551c34f69ebbb4f30eb5cb7ea4cbf559b42771937b9aeb370e` |

**Identical.** The order system's own store agrees: `EXT-C`, `EXT-D`, `EXT-E`, `EXT-F` are
`v1 ACCEPTED` with their original recipes. Its event log since the load holds exactly two
events, `EXT-A`'s pre-approved amendment and `EXT-B`'s approved one, and no other order moved.
`pr-e` and `pr-f` stayed `UNAFFECTED` throughout.
Five of six customers hold placeholders, so no dispatch could have reached a second person.

### Counts, before and after

| | before restore | after restore | after dispatch | final |
|---|---|---|---|---|
| cases | 1 | 1 | 1 | 1 |
| approval requests | 0 | 0 | 1 | 1 |
| approval decisions | 0 | 0 | 0 | **1** |
| plan approvals | 0 | 0 | 1 | 1 |
| inbound replies | 0 | 0 | 0 | 1 |
| inbox events | 0 | 0 | 1 | 3 |
| outbox rows | 0 | 0 | 2 | 3 |
| `MESSAGE_SEND` / `ORDER_AMEND` | 0 / 0 | 0 / 0 | 1 / 1 | **1** / 2 |
| provider attempts (sum) | 0 | 0 | 2 | 3 |
| distinct idempotency keys | 0 | 0 | 2 | 3 |
| Telegram `sendMessage` / HTTP 200 / `getUpdates` | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 0 | **1 / 1 / 0** |
| order-system amendment events | — | 0 | 1 | 2 |
| authority rows ≠ `NONE` since load | — | 0 | 5 | 9 (6 `HUMAN_APPROVAL`, 3 `CONSTRAINT`) |
| `audit_events` (`seq` 1–n, contiguous) | 277 | 291 | 302 | 322 |
| `domain_events` | 367 | 386 | 401 | 417 |

## 9. Finding — P1: the approval-link token reaches the access logs, and it encodes the chat id

Found in this session, while reading the `api` log for the customer's press. **Recorded, not
repaired**: no source was edited and no log was deleted.

The possession token minted by `promisepatch.domain.customer_link.mint` is
`v1.<payload>.<signature>`, where the payload is URL-safe base64 of
`v1 ␟ request_id ␟ channel` and the channel is `tg:<chat id>`. The page is reached at
`/?approve=<token>` and calls `/api/customer/approval/<token>`. Both the `api` container's HTTP
access log and Caddy's access log record the request line verbatim.

Measured on the host, in counts and booleans only:

| container | log driver | lines holding the `?approve=` form | lines holding the `/api/customer/approval/` form | distinct tokens | tokens whose payload decodes to the stored address |
|---|---|---|---|---|---|
| `api` | `awslogs` | 3 | 4 | 1 | **1** |
| `caddy` | `awslogs` | 9 | 4 | 1 | **1** |
| `worker`, `mcp`, `order-simulator` | `awslogs` | 0 | 0 | 0 | 0 |

Two consequences:

- **ADR-0021 is broken on the log surface.** A log should get the channel kind and nothing else.
  A plaintext search for the stored address in all five logs finds **0** lines, because the id
  is base64-encoded. That is also why [phase7-rc-deployment.md](phase7-rc-deployment.md) §5 and
  the section 8 scan of this run both read `0` without being wrong about what they measured.
- **The token is the consent door.** Consent comes only through the signed link, and possession
  of the link is what the protocol checks. So until a customer answers, anyone who can read
  those CloudWatch log groups holds the one credential that could answer on the customer's
  behalf. Check 8 would pass, because the sender identity is taken from the signature.

For **this** request the token is spent: the request is `ANSWERED`, `decided = true`, and the
unique constraints of section 6 make a second answer write nothing. Its deadline is
`19:13:21Z` today. The earlier deliveries of 2026-09-22 and later went through the same
routes, so their tokens are very likely in CloudWatch too. **That is an inference and was not
measured.**

**This session also disclosed one instance.** A masking pattern written here covered the
`/api/customer/approval/<token>` form but not the `?approve=<token>` form. So three `api`
access-log lines carrying this request's token were printed into the operator's session
transcript. The token was not repeated, decoded or copied anywhere else, including this
document. It is the same spent token described above.

Closing it is a code-and-deployment change, so it is outside this work: redact or drop the query
string and the path token in both access logs, and consider a token payload that does not carry
the channel. The CloudWatch lines already written stay until the owner decides otherwise.

## 10. Health, smoke and the infrastructure

**On the host**, `scripts/deployment_smoke.py` inside the deployed `worker`, with the bearer read
from `env/mcp.env` on the host: **11/12**. `deployed-image` `abbbd11006f7`, `tls-and-readiness`,
`mcp-requires-bearer` `401`, `origin-refused` `403`, `host-refused` `421`,
`webhook-rejects-unsigned`, `protocol-revision` `2025-11-25`, `spa-at-root`, `deep-link`,
`unknown-api-path`, `internal-not-published` all pass. The one failure is `http-redirects`,
`ConnectTimeout`. That is the host's own port-80 self-hairpin recorded in
[phase7-rc-deployment.md](phase7-rc-deployment.md) §6, which the operator machine passes. It was
not chased. **Not claimed as 12/12.**

**Public payloads**, through the observer session the judge entry mints: `GET /api/cases` (298
bytes) and `GET /api/cases/{id}` (15 910 bytes) are both `200`, and the stored address is absent
from both. There is no `sender_identity` key and no `telegram:`/`tg:` form of the id. The
approval URL is absent. The detail payload now carries `provider_ref` keys (there are effects to
describe) with masked values. **Container logs**: the plaintext address, the bot token and any
`telegram:<digits>:` / `tg:<digits>` / `chat_id=<digits>` pattern occur in **0** lines of `api`,
`worker`, `mcp`, `caddy` and `order-simulator`. The encoded form is section 9.

| | before | after |
|---|---|---|
| Stack / last updated / change sets | `UPDATE_COMPLETE` / `2026-09-24T12:54:54Z` / 0 | **identical** |
| `ImageTag` / SSM `image-tag` / `/healthz` | `abbbd11006f7` ×3 | **identical** |
| Instance / AMI / launch / volume | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z` / `vol-0f330aaa62e637ef6` | **identical** |
| RDS | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, private, encrypted | **identical** |
| Host `boot_id` | `fe436521-…` | **identical — no reboot** |
| `api` process `boot_id` | `ea124d58-…` | **identical — no restart** |
| Container restarts | 0 each | **0 each** |

No AWS resource was created, updated or deleted; no SSM parameter written; no IAM policy read,
broadened or written; no release, redeploy, host image, worktree or temporary clone.

## 11. Stale consent and the re-ask: deferred, and why

**Not exercised live.** No safe normal-product path existed to make this case's approval stale
**before** its amendment committed. The decision (`14:14:34.651Z`), the ten checks (`.759Z`)
and the committed amendment (`14:14:35.019Z`) fell within **367 ms** on one worker. Anything
that could have landed inside that interval would have needed a hand-timed external change,
which is staging rather than measuring and was ruled out. Nothing was changed to provoke a
refusal, and no second destructive world was created. The case is now `RESOLVED`, so the
question no longer exists for it.

`STALE`, `EXPIRED`, `UNAUTHORIZED` and `NOOP`, the re-ask of ADR-0022, the re-plan of ADR-0023,
the answer-time revalidation of ADR-0025 and ADR-0026's refusal branch therefore remain proved
by the deterministic Phase 6 and Phase 7 evidence only: [phase7-local-rc-correctness.md](phase7-local-rc-correctness.md),
[phase7-local-rc-final.md](phase7-local-rc-final.md) and the tests they cite. What ran live here is
ADR-0026's **passing** branch — a first dispatch at attempts 1 with the production start ahead.

## 12. What this does not prove

- **It is not one of G8's five deployed rehearsals.** The roadmap requires each to include a
  worker restart; none was made here.
- **No refusal path ran live** (section 11), and no live duplicate press was made (section 6's
  proof is the catalogue's constraints).
- **ADR-0025's silent sibling** needs the two-customer world on the host, which is a separate
  authorisation.
- **Remote CI has not run on this record.** It is documentation only and was not pushed.
- **The restore is still not runnable as shipped.** The env union of
  [demo-world-restore.md](demo-world-restore.md) §4 remains a defect recorded unfixed, and so does
  [phase7-rc-deployment.md](phase7-rc-deployment.md) §3's start-up-roll finding.
- **The world decays from its `14:13:21Z` anchor.** Now that an approval request and outbox rows
  exist, the non-destructive roll is refused again, so the next repair is destructive.

## 13. Phase 7 closeout scope

Proved live on `abbbd11006f7` by this record:

- guarded restore with the binding carried;
- plan confirmation inside the window;
- one real Telegram delivery;
- a real web approval;
- ten revalidation checks on a fresh read returning `PROCEED`;
- ADR-0026's first-dispatch gate passing;
- `EXT-B` `v1 → v2` with the mirror converged;
- `pr-b` `RECOVERED`, the case `RESOLVED`;
- `HUMAN_APPROVAL` provenance end to end;
- unrelated state digest-identical.

Still owed before Phase 7 can be called closed on the deployment:

1. **The section 9 P1**, fixed in code and carried to the host by an authorised release, with the
   access logs re-measured for both token forms.
2. **Remote CI** on whatever release SHA carries that fix.
3. The owner's decision on the CloudWatch lines already holding tokens.

Carried forward and **not** Phase 7 scope:

- the restore env-union defect;
- the start-up-roll finding;
- live stale/re-ask and ADR-0025 proof;
- G8's five rehearsals with worker restarts.
