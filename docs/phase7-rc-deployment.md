# Phase 7 — the release candidate, deployed

Date: 2026-09-24. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything was
read and unchanged throughout.

The release candidate closed locally in [phase7-local-rc-final.md](phase7-local-rc-final.md) is
now what the deployed host serves. **Nothing was pushed.** Remote CI has not run on `abbbd11` or on
this record: that is deliberately deferred to the project owner's push, and it is still owed.

The project owner authorised three things and nothing else: deploying `abbbd11`, the
parameter-only `ImageTag` change set executed only on an empty change list, and exactly one
destructive demo-world restore after the release. Each was used once.

## 1. Entry

| | value |
|---|---|
| HEAD | `abbbd11006f756a772c672da6147dc719cb5e56d`, one commit ahead of `origin/main` (`a864abd`), tracked tree clean, the eleven known untracked artefacts untouched |
| Deployed before | `931a296decad` — stack parameter, SSM `image-tag`, `/healthz` and all five containers agreed |
| `deploy/` and `docker/` since `931a296` | **unchanged**; SSM `compose` and `caddyfile` byte-identical to HEAD's files |
| Migrations since `931a296` | none; head is still `0009_human_plan_approval` |

## 2. The local RC gate, before any AWS mutation

`promisepatch-backend:local`, `promisepatch-frontend:local` and
`promisepatch-order-simulator:local` were rebuilt from `abbbd11`, the whole stack recreated with
`docker compose up --detach --wait --force-recreate` (as CI does), and the three specs run:

| spec | result |
|---|---|
| `customer-approval.spec.ts` | 7 passed |
| `judge-journey.spec.ts` | 10 passed |
| `responsive.spec.ts` | 18 passed |
| **total** | **35 passed, 0 failed, 0 retried** |

**One thing had to change first, and it was not source.** The first attempt failed 2 and did not
run 26: `POST /api/auth/demo-session` answered `404 this deployment does not serve demo sessions`.
The operator's gitignored `docker/env/api.env` and `mcp.env` were configured for the SUR-1 scored
path (`PP_DEMO_SESSION_ENABLED=false`, `PP_LLM_PROVIDER=bedrock`, a link base on `45173`), which
is not the stack CI generates from the committed examples. Those three keys were set to the
committed examples' values for the run, and both files were then restored byte-for-byte from a
backup (verified by SHA-256) and the services recreated on them. No test, spec or product file
was edited.

## 3. The deployed history, read before the reset

Read-only, inside a `READ ONLY` transaction, from the deployed `worker` over
`ssm:StartSession`. No customer address was printed — only its length.

### `PLAN_UNCONFIRMED` — confirmed

Phase 6 session 2 inferred from its shape that the 2026-09-23 restore case had escalated because
nobody confirmed its plan. The rows say so directly:

| | row |
|---|---|
| case | `5b825f1b-3adb-5c53-bc68-2d5d34a43af0`, `PLANNED` at `13:06:39Z` |
| timer | `PLAN_AUTO_ESCALATION` due `13:16:39.321Z`, fired `13:16:40.326Z` |
| step | `ESCALATE_PLAN` `DONE`: `{"reason": "PLAN_UNCONFIRMED", "outcome": "ESCALATED", "tasks_held": 4}` over the four live tracks |
| audit `234` | `PLAN_AUTO_ESCALATED`, actor `SYSTEM`, authority **`NONE`**, `after.reason = PLAN_UNCONFIRMED` |
| events `602–608` | four `track.escalated`, each `reason: PLAN_UNCONFIRMED` (`R-VISIBLE-ASK`, `R-NOSUB` ×2, `R-PREAPPROVED`) |
| then | `RECONCILE_CASE` → `RESOLVED`, `needs_owner_attention = true` |
| effects | outbox 0, requests 0, decisions 0, plan approvals 0, replies 0 |

§14.1's ten-minute plan window closed unconfirmed, every live track was handed to the owner, and
nothing was sent or changed. **The hypothesis is confirmed, not merely consistent.**

### Two more things the history held

- **The demo world rolled itself at `2026-09-23T23:00Z`** (`fixture.reanchored`, anchor
  `2026-09-24T00:00Z`), which is [demo-world-roll.md](demo-world-roll.md) doing its job on a world
  nothing pinned. It opened a second case, `f02697c0-…`, which escalated `PLAN_UNCONFIRMED` the
  same way at `23:10:04Z` (audit `251`).
- **The rollout's own worker start rolled the world again** (`fixture.reanchored` at
  `2026-09-24T12:57:01Z`), and the case it opened, `8c652643-…`, **stopped at
  `NEEDS_HUMAN_INTERPRETATION`, reason `NO_OPEN_COMMITMENT`** — the worker logged
  `provisioning.demo_case.stopped … no answerable question was reached`, `rolled: true`. The two
  earlier cases had each settled a raspberry commitment line `NOT_RECEIVED`, and the roll
  re-anchors a world it does not reseed, so no open raspberry commitment was left to answer. That
  diagnosis is inferred from those rows and has not been reproduced locally. **Recorded, not
  fixed.** The restore below destroyed that case as designed; its ledger rows (audit `256–259`,
  events `672–678`) survive.

### State recorded before the release

| | value |
|---|---|
| Stack | `promisepatch-prod`, `UPDATE_COMPLETE`, last updated `2026-09-23T12:52:06Z`, no change sets |
| Host | `i-087c742587f83d61d`, `t4g.small`, AMI `ami-0fa4996c14e7d501e`, launched `2026-09-18T10:19:33Z`, IMDSv2 required, hop limit 2 |
| Volume | `vol-0f330aaa62e637ef6`, 30 GiB, encrypted, created `2026-09-13T18:33:34Z` |
| RDS | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, private, encrypted, created `2026-09-11T11:19:51Z` |
| Host `boot_id` / `uptime -s` | `8f030425-e01f-4d26-9f85-fce49cb82676` / `2026-09-23 12:54:41` |
| Fixture | `hollow-oak`, anchor `2026-09-24T00:00:00Z`, digest `44dbd766…ccdc41` |
| Provider | `telegram` in `worker`; bot token and link secret present (values not read) |
| Binding | `cus-tomas` address length 10 (bound); the other five length 4 |
| Counters | outbox 0 (0 unsettled), requests 0, decisions 0, plan approvals 0, replies 0 |
| Ledgers | `audit_events` 254 (`seq` 1–254), `domain_events` 334 |
| Certificate | Let's Encrypt key and certificate files dated `2026-09-13 18:35` |

## 4. The release

`deploy.sh stack` cannot carry this release; [non-destructive-release.md](non-destructive-release.md)
§10.1 is unchanged. It went the way `931a296decad` went.

1. **`deploy.sh images`** — preflight 9/9, both arm64 images pushed at `abbbd11006f7`:
   `backend@sha256:595bcb5e…`, `order-simulator@sha256:06a36105…`.
2. **`deploy.sh config`** — run only after comparing SSM with HEAD. `compose` and `caddyfile` were
   rewritten with **identical content** (re-read and compared after); `image-tag` moved
   `931a296decad` → `abbbd11006f7`.
3. **The parameter-only change set**, `--use-previous-template`, `ImageTag=abbbd11006f7` and
   every other parameter `UsePreviousValue=true`. In the deployed template (40 365 bytes, zero
   `channel.env`) `ImageTag` is referenced only by the `DeclaredImageTag` output. Inspected before
   execution:

   ```text
   Status: CREATE_COMPLETE  ExecutionStatus: AVAILABLE  ChangeCount: 0  Changes: []
   ```

   Every parameter except `ImageTag` read back equal to the live value (`HostAmiId`
   `ami-0fa4996c14e7d501e`, `SeedDemoFixtureOnFirstBoot` `false`). Executed: `UPDATE_COMPLETE` at
   `2026-09-24T12:54:54Z`, **stack-level events only, no resource event**, instance id, AMI and
   launch time unchanged.
4. **`deploy.sh rollout`** — the stack, SSM and the release all named `abbbd11006f7`; the host
   was rebooted, not replaced, and served `abbbd11006f7`.

### After the rollout, measured on the host

| | result |
|---|---|
| `/healthz` | `image: abbbd11006f7` |
| containers | `api`, `worker`, `mcp`, `order-simulator` and `migrate` all on `…:abbbd11006f7`; `caddy` unchanged; **0 restarts** each; `migrate` exited `0` with no `Running upgrade` |
| `/readyz` | migrations at head, `0009_human_plan_approval` |
| provider | `telegram` in `api` and `worker`; bot token and link secret present; link base `https://184.194.40.87.sslip.io` |
| `pp channel check` in `worker` | `@PromisePatchDemoBot`, `provider: telegram`, `reachable; no message was sent` (`getMe` only) |
| forged approval link | **`404 LINK_NOT_FOUND`** |
| `converge.sh` / `channel.env` | `09105b10…` / `c3a6e4de…`, both unchanged; `channel.env` still `0600 root` |
| host `boot_id` | `fe436521-2557-41e8-bd58-a41a3f099cea`, `uptime -s` `2026-09-24 12:56:36` — the rollout reboot, and the only one |

## 5. The restore — once

Run in the deployed `worker` with the host-local env union of
[demo-world-restore.md](demo-world-restore.md) §4: `PP_MIGRATION_DATABASE_URL` and both demo
passwords read out of `env/migrate.env` on the host, `PP_ALLOW_FIXTURE_RESET=true` named
explicitly. No credential and no chat id entered the operator's shell or the transcript.

**It was gated.** A `--dry-run` ran first, and the confirmed run was reachable only if it exited
`0`, reported `binding: restored`, `unsettled=0` and `fixture=hollow-oak`:

```text
before:   fixture=hollow-oak cases=3 live=1 outbox=0 unsettled=0 requests=0 decisions=0
          approvals=0 replies=0 audit=259 events=339 bound=True
binding:  restored (would be carried across)
```

Then, once:

```text
pp restore-demo-world --confirm destroy-and-restore          -> exit 0
action:   restored
after:    fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0
          approvals=0 replies=0 audit=273 events=358 bound=True
anchor:   2026-09-24T12:59:09.020144+00:00
digest:   24b35429de2a82c93d105257c66f526d1fd27bf9e022c557519de9f192fd33a1
rows:     160
orders:   6 reset in the external order system
case:     eae07b11-cbc4-551e-bb1b-c7df0e8bb7ff
state:    PLANNED
binding:  restored
ledgers:  grew only
result:   restored; no plan was confirmed and no message was sent
```

Verified independently by SQL against the same database:

| requirement | measured |
|---|---|
| fresh anchor | `2026-09-24T12:59:09.020144Z`, new digest `24b35429…fd33a1` |
| one canonical `PLANNED` case | `eae07b11-…`, `PLANNED`, `needs_owner_attention = false` |
| canonical partition (`pp case-status`) | `pr-a` `AUTO_RECOVERABLE` `R-PREAPPROVED`, `rv-raspberry-almond-3 → -4` (no approval); **`pr-b` `APPROVAL_REQUIRED` `R-VISIBLE-ASK`, `rv-raspberry-rose-2 → -3`, window closes `2026-09-24T17:59:09Z` — exactly one**; `pr-c` `BLOCKED` `NOSUB_CONSTRAINT`; `pr-d` `BLOCKED` `NO_PREAUTHORED_VARIANT`; `pr-e`, `pr-f` `UNAFFECTED` `NOT_REACHABLE` |
| order system reset | `6 reset`; every order `external_version = 1`; simulator `/healthz` 200 |
| ledgers only grew | `audit_events` 259 → 273 (`seq` 1–273, contiguous); `domain_events` 339 → 358 |
| outbox and authority counters | outbox 0, requests 0, decisions 0, plan approvals 0, replies 0 |
| exactly one customer bound | `cus-tomas` length 10; the other five length 4 |
| binding still reaches the same chat | `_verify_destination` in `worker`: `verifier_success=True`, `returned_id_matches_stored=True`, `chat_type=private`, `@PromisePatchDemoBot` |
| nothing sent | `worker` log: `sendMessage` **0**, `worker.telegram.sent` **0**, `MESSAGE_SEND` **0**, before, after and at the end |
| address stays in the database | absent from `GET /api/cases` and `GET /api/cases/{id}` (12 414 bytes, observer session, compared in-process); no `provider_ref` or `sender_identity` key; **0** lines holding the address or a `telegram:<digits>:` / `tg:<digits>` pattern in `api`, `worker` or `mcp` logs |
| no reboot | `boot_id` `fe436521-…` immediately before and after |

No plan was confirmed and no customer message was sent.

## 6. Smoke, from the host and from here

**From the host**, `scripts/deployment_smoke.py` run inside the deployed `worker` image with the
bearer read from `env/mcp.env` on the host: **11/12**. The three checks this operator machine
cannot read — `mcp-requires-bearer` `401`, `origin-refused` `403`, `host-refused` `421` — all
pass there, as does `deployed-image` (`abbbd11006f7`). The one failure is `http-redirects`,
`ConnectTimeout`: from inside the host, a request to the host's own public address on port 80
never connects, while the same hairpin on 443 answers in 31 ms. Port 80 itself is fine — local
Caddy answers `308` to `https://…/readyz` in 1.7 ms, the security group admits `80/tcp` from
`0.0.0.0/0`, and from this machine it answers `308`.

**From this operator machine**, `deploy.sh smoke`: **8/12**, `http-redirects` passing. The two
failures (`mcp-requires-bearer`, `host-refused`) are the known `ReadTimeout` of this machine's
TLS-intercepting proxy; `origin-refused` and `protocol-revision` were skipped because the bearer
was deliberately not pulled into this shell.

**Every one of the twelve checks passes from at least one vantage. Neither vantage is 12/12 on
its own, and this record does not claim 12/12.**

## 7. The infrastructure did not move

| | before release | after restore |
|---|---|---|
| Instance / AMI / launch | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z` | **identical** |
| Volume | `vol-0f330aaa62e637ef6`, encrypted, `in-use` | **identical** |
| RDS | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, private, encrypted | **identical** |
| Docker volumes | `caddy-config`, `caddy-data`, `order-simulator-data` | **all three present** |
| Certificate | key and certificate dated `2026-09-13 18:35` | **same files**; nothing re-ordered |
| Stack | `UPDATE_COMPLETE`, `2026-09-23T12:52:06Z`, `ImageTag` `931a296decad` | `UPDATE_COMPLETE`, `2026-09-24T12:54:54Z`, `ImageTag` `abbbd11006f7`, **no change sets** |
| SSM `image-tag` | `931a296decad` | `abbbd11006f7` |
| Host `boot_id` | `8f030425-…` | `fe436521-…` at the **rollout**, unchanged across the restore |

No IAM policy was read, broadened or written; no infrastructure stage, `host-image`, host
replacement, cloud-init reseed or volume deletion was used. Host access was
`ssm:StartSession` with `AWS-StartNonInteractiveCommand` alone.

## 8. What this does not prove

- **Remote CI has not run** on `abbbd11` or on this record. Nothing was pushed; the owner's push
  is where it runs, and it is owed.
- **The Phase 7 behaviour is not exercised live.** ADR-0025 and ADR-0026 are proved locally only.
  The canonical demo asks one customer, so it cannot reach ADR-0025, and no amendment was
  dispatched here, so ADR-0026's first-dispatch gate was not reached either.
- **No refusal path was exercised live** — not the restore's preconditions and not
  `STALE` / `EXPIRED` / `UNAUTHORIZED` / `NOOP`.
- **No message was sent.** The restored binding is one Telegram still confirms; nothing here says a
  new approval would reach the phone.
- **The restored case is transient by design, and that was measured.** §14.1's ten-minute plan
  window opened at `12:59:11Z`. Read again at `13:09:37Z`: the `PLAN_AUTO_ESCALATION` timer (due
  `13:09:11.553Z`) fired at `13:09:12.071Z`, audit `274` is `PLAN_AUTO_ESCALATED` by `SYSTEM` with
  authority `NONE`, four `track.escalated` events carry `PLAN_UNCONFIRMED`, and `eae07b11-…` is
  `RESOLVED` with owner attention — section 3's history reproduced live on `abbbd11006f7`.
  Outbox, requests, decisions, plan approvals and replies all still `0`, one customer bound,
  `sendMessage` `0`, `boot_id` unchanged. So the deployed demo world now shows a handed-over case,
  not a `PLANNED` one. A live behavioural proof needs its own authorised restore, followed
  within ten minutes by a confirmation.
- **The restore is still not runnable as shipped**: the env union of
  [demo-world-restore.md](demo-world-restore.md) §4 is still a defect recorded unfixed.
- **The start-up roll finding** of section 3 (`NO_OPEN_COMMITMENT`) is recorded, not reproduced
  locally and not fixed.

## 9. Next behavioural proof

One owner-authorised session on the deployed host, in this order: a fresh
`pp restore-demo-world`, then **within the ten-minute plan window** one worker plan confirmation
on the operator console, then one Telegram approval to the bound chat, then the customer's
`APPROVE` through the signed web link. What it should show is ten `REVALIDATION_CHECK` rows against
a fresh snapshot, then `APPLY_RECOVERY`, with the amendment's first dispatch claimed at
`attempts == 1` while `EXT-B`'s production start is still ahead (ADR-0026's gate passing live).
`EXT-B` should go to `AMENDED @ v2`, `pr-b` should settle `RECOVERED`, the case should reach
`RESOLVED`, and `plan_approvals` should equal 1. ADR-0025's silent-sibling behaviour needs the
two-customer Proof C world on the host. That is a separate authorisation and not part of this
proof.
