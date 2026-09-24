# Phase 7 closeout — the release candidate, audited and frozen

Date: 2026-09-24, audited between `16:45Z` and `16:57Z`. Entry at
`da7ceca429d379d80a911bfaddd84789599448ac`: `main` equal to `origin/main`, tracked tree clean, and
the eleven known untracked artefacts left as they were. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, verified before anything was read.

This is a read-only audit of the deployed release candidate and of the Phase 7 records, and the
decision it supports. **Nothing was changed.** That covers source, tests, releases, redeploys,
restores, change sets, SSM parameters, IAM, logs, customer messages, SUR-1 and effect-set
artefacts, worktrees and clones. Against AWS it used Describe, Get and List calls from the operator
machine. On the host it used `ssm:StartSession` with `AWS-StartNonInteractiveCommand` for two
read-only scripts, and every database read ran in a read-only transaction.

The Phase 7 records are history and are not edited:
[phase7-local-rc-correctness.md](phase7-local-rc-correctness.md),
[phase7-local-rc-final.md](phase7-local-rc-final.md),
[phase7-rc-deployment.md](phase7-rc-deployment.md),
[phase7-deployed-behavioral-proof.md](phase7-deployed-behavioral-proof.md) and
[phase7-approval-log-privacy-repair.md](phase7-approval-log-privacy-repair.md). Where this audit
re-measured something they state, the new reading is recorded here beside them.

## 1. Verdict

**Phase 7 is closed.** No known P0 or P1 remains. The release candidate is frozen at deployed code
SHA **`4529a802e34e`**. G8 stays open, separately (section 8).

## 2. CI

| workflow | run | SHA | result |
|---|---|---|---|
| `pr` | `36026681252`, push, attempt 1 | `da7ceca` | **success**: 13 of 13 jobs green |
| `effect sets (expected red until 16/16)` | `36026681236`, push | `da7ceca` | failure, as expected |

The 13 green jobs are:

- order contract + order system;
- semantic boundary, and semantic evaluation;
- ruff, mypy and import-linter;
- mcp protocol;
- pytest + coverage, and the Hypothesis CI profile;
- frontend;
- **backend + postgres** (`16:20:37Z` → `16:35:51Z`);
- **whole-stack browser**;
- gitleaks.

`b244e69` and `4529a80` have no CI run of their own. They reached `origin/main` together with
`da7ceca`, so `pr` ran once, at `da7ceca`. That run tested the release's code. `4529a80` and
`da7ceca` differ only in `CLAUDE.md` and the privacy-repair record, and these trees are
byte-identical between the two:

- `apps`, `packages`, `deploy`, `docker`, `scripts`, `evals` and `.github`;
- `pyproject.toml` and `uv.lock`.

CI was read through the public GitHub REST API, with no credential.

## 3. The deployed state, measured

### Control plane

Read from the operator machine with Describe, Get and List calls only. Nothing here differs from
what [phase7-approval-log-privacy-repair.md](phase7-approval-log-privacy-repair.md) recorded in §5
and §7.

| | measured |
|---|---|
| Stack | `promisepatch-prod`, `UPDATE_COMPLETE`, last updated `2026-09-24T16:00:45Z`. The six latest events are all `AWS::CloudFormation::Stack`: the `16:00:45Z` and `12:54:54Z` parameter-only updates, and nothing after them. **0 change sets.** `DriftInformation` reads `NOT_CHECKED` |
| Image tag | `ImageTag` parameter, `DeclaredImageTag` output and SSM `image-tag` (v9) all read `4529a802e34e` |
| SSM `compose` (v14) and `caddyfile` (v13) | byte-equal to `deploy/compose/docker-compose.deploy.yml` and `deploy/compose/Caddyfile` at HEAD, line endings normalised |
| Instance | `i-087c742587f83d61d`, running, `t4g.small`, `ami-0fa4996c14e7d501e`, launched `2026-09-18T10:19:33Z`, IMDSv2 required, hop limit 2 |
| Volume | `vol-0f330aaa62e637ef6`, `in-use` on that instance, 30 GiB, encrypted, created `2026-09-13T18:33:34Z` |
| RDS | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, not public, encrypted, PostgreSQL 16.13, created `2026-09-11T11:19:51Z` |
| Log group | `/promisepatch/prod`, 14-day retention, 25.8 MB |

### Host

Read between `16:49:28Z` and `16:49:47Z`.

| | measured |
|---|---|
| host `boot_id` / `uptime -s` | `109dccdf-b7fb-4882-8b28-c963b2f0f7b9` / `2026-09-24 16:02:33`: the `4529a802e34e` rollout reboot. **No reboot since**, and the same at the end of the read |
| `api` process `boot_id` (`/healthz`) | `3e90146d-1484-40e9-8ab8-02cda046a664`, the one the privacy repair's live proof read. **No restart since** |
| `/healthz` | `image: 4529a802e34e` |
| `/readyz` | ready; database reachable as `promisepatch_app`; migrations at head, `0009_human_plan_approval`; fixture `hollow-oak`, anchor `16:07:35.139235Z`, digest `07213911…70abb6`, which is the privacy repair's restore |
| containers | `api` (healthy), `worker`, `mcp` and `order-simulator` (healthy) on `…:4529a802e34e`; `caddy` on `caddy:2.10-alpine`; `migrate` exited `0`. All started between `16:02:54Z` and `16:03:04Z`, **0 restarts** each, all logging to `awslogs` |
| Docker volumes | `caddy-config`, `caddy-data`, `order-simulator-data` |
| `converge.sh` / `channel.env` | `09105b10…` / `c3a6e4de…`, `0600 root`: both unchanged |
| `Caddyfile` | 3614 bytes; `import redact` twice; `Referrer-Policy` present |
| certificate | `.crt` and `.key` dated `2026-09-13 18:35:30`, so **no certificate was re-issued**. Caddy's `.json` metadata file for the certificate was last written `2026-09-24 14:47:07`. That is recorded, and its cause was not investigated |
| customer channel | provider `telegram` in `api` and `worker`; bot token, link secret and link base present (values not read) |
| worker log since start | `sendMessage` 1, `worker.telegram.sent` 1, `api.telegram.org` 1 × 200 and 0 of anything else, **`getUpdates` 0**, effects dispatched 3 |

### Database

Every read ran in a read-only transaction and its output was masked. The address guard read
`False`.

| | measured |
|---|---|
| cases | one: `98aa7036-…`, `RESOLVED`, owner attention from `pr-c` and `pr-d`, last updated `16:09:55.640757Z` |
| outbox | 3 rows (`ORDER_AMEND` ×2, `MESSAGE_SEND` ×1), all `DELIVERED` at attempt 1, 3 distinct keys. **0 `PENDING` or `IN_FLIGHT`** |
| steps and inbox | 15 steps `DONE`. 1 `SKIPPED`: the reconcile, which found `pr-b` still `APPLYING`; the finalize that then settled `pr-b` finished the case (ADR-0025 §2). 3 inbox rows, all `PROCESSED` |
| timers | one unfired: the answered request's `APPROVAL_DEADLINE`, due `21:07:35Z`. For a decided request it is §11.5's `TIMER_NOOP` and is skipped (`approvals._expire`, `apps/backend/src/promisepatch/domain/approvals.py:1021`) |
| authority tables | `plan_approvals` 1, `approval_decisions` 1, `inbound_replies` 1, `approval_requests` 1 (`ANSWERED`) |
| ledgers | `audit_events` 367, `seq` 1–367 contiguous; `domain_events` 467. The last row of each is `16:09:55.640757Z`, the loop's own completion. **Nothing has been written since** |
| binding | `cus-tomas` address length 10; the other five at their four-character placeholders |

**Nothing is pending or in flight that needs a person.** The world will decay from its `16:07:35Z`
anchor, and the one timer still due changes nothing when it fires.

## 4. Smoke, once, from the host

`scripts/deployment_smoke.py` ran once, at HEAD and unmodified, inside the deployed `worker`. The
bearer was read from `env/mcp.env` on the host, with `PP_EXPECTED_IMAGE_TAG=4529a802e34e`. It
scored **11/12**:

| check | on the host |
|---|---|
| `tls-and-readiness` | passed; certificate verified, schema at head |
| `http-redirects` | **failed**, `ConnectTimeout` |
| `mcp-requires-bearer` | passed, `401` |
| `origin-refused` | passed, `403` |
| `host-refused` | passed, `421` |
| `webhook-rejects-unsigned` | passed, `401` |
| `protocol-revision` | passed, `2025-11-25` |
| `spa-at-root` | passed |
| `deep-link` | passed, `200` |
| `unknown-api-path` | passed, `404` JSON |
| `internal-not-published` | passed, `404` |
| `deployed-image` | passed, `4529a802e34e` |

**The one failure is a limitation of where the check ran from, not a product failure.** From inside
the host, a request to its own public address on port 80 never connects.
[phase7-rc-deployment.md](phase7-rc-deployment.md) §6 recorded this hairpin, and it was not chased.
One probe of `http://184.194.40.87.sslip.io/readyz` from the operator machine answered `308` to
`https://…/readyz` in 0.31 s.

The operator machine has the opposite gap. Its TLS-intercepting proxy truncates small non-2xx
bodies, so the three MCP refusals time out from there, and all three passed on the host. So every
check passes from at least one vantage, **no single vantage gives 12/12, and this record does not
claim 12/12.**

## 5. Privacy re-check

Nothing sensitive was printed. Only counts and 8-hex fingerprint prefixes were read out: no token,
no token part, no URL carrying one, no chat id and no bot token. For the counts, the current link
was read from the outbox inside `worker`. The address and the bot token were read into host shell
variables and unset afterwards.

### Container logs, read after the smoke

| container | lines | token-shaped | unredacted `?approve=` / `/approval/` | current link (whole / payload / signature) | address | bot token | chat-id shapes | error-level lines |
|---|---|---|---|---|---|---|---|---|
| `caddy` | 58 | 0 | 0 / 0 | 0 / 0 / 0 | 0 | 0 | 0 | 0 |
| `api` | 562 | 0 | 0 / 0 | 0 / 0 / 0 | 0 | 0 | 0 | 0 |
| `worker` | 28 | 0 | 0 / 0 | 0 / 0 / 0 | 0 | 0 | 0 | 0 |
| `mcp` | 13 | 0 | 0 / 0 | 0 / 0 / 0 | 0 | 0 | 0 | 0 |
| `order-simulator` | 11 | 0 | 0 / 0 | 0 / 0 / 0 | 0 | 0 | 0 | 0 |

Caddy logged **0** `Referer` fields and **0** `Location` fields. The request lines are still there,
with the credential removed:

- `api`, the customer's page load: `GET /?approve=REDACTED` 200 ×2.
- `api`, the privacy repair's sentinel: `GET /?case=probe&approve=REDACTED&x=1` 200.
- `api`, the page's reads: `GET /api/customer/approval/REDACTED` 200 ×5, and 404 ×1.
- `api`, the customer's press: `POST /api/customer/approval/REDACTED` 202, plus the sentinel's 404.
- `caddy`: 4 query-form and 8 path-form request lines, all reading `REDACTED`.

### CloudWatch, every retained event

Every event of every stream in `/promisepatch/prod` was read with `get_log_events` and scanned in
memory. That is 121 streams and 218 640 events, back to the earliest retained event at
`2026-09-11T11:23:58Z`. The boundary is the `4529a802e34e` stack update at `16:00:45Z`.

| | before the boundary | since the boundary |
|---|---|---|
| events | 217 904 | 736 |
| token-shaped strings | 34 | **0** |
| unredacted `approve=` | 20 | **0** |
| unredacted `approval/` | 46 | **0** |
| `Referer` fields | 264 | **0** |
| chat-id shapes (`telegram:<digits>:`, `tg:<digits>`, `chat_id=<digits>`) | 2 | **0** |
| bot-token shapes | 0 | **0** |
| `approve=REDACTED` / `approval/REDACTED` | 0 / 0 | 7 / 16 |

Every pre-boundary occurrence of the token, the unredacted forms and `Referer` ends at `14:14:38Z`,
the morning proof on `abbbd11006f7`.

**Across all retained history there are exactly 2 distinct tokens**, and they are the two
fingerprints the privacy repair recorded:

- `ce5d1eaa…`: 14 hits, from `2026-09-22T17:40:04Z` to `17:40:12Z`;
- `64010d10…`: 20 hits, from `2026-09-24T14:14:30Z` to `14:14:38Z`.

No token appears after the boundary. The current link, `e77b121c…`, is in no container log and no
CloudWatch event.

The two chat-id-shaped lines were last written at `2026-09-22T16:57:41Z`. They predate the
ADR-0021 redaction, and [customer-disclosure-hardening.md](customer-disclosure-hardening.md)
already records that CloudWatch keeps such lines. They are counted here, not read.

### The two historical tokens

Both are spent and cannot act, re-read today:

- The database holds exactly one approval request, `32f5c8fc-…`, which is `ANSWERED` and decided.
- Neither historical token's request exists any more.
- A request id is a `uuid5` over a case id, and each restore mints a new case id. So an old token
  opens only the closed view, and a press through it names a request that does not exist.

They remain subject to normal 14-day retention and expire by about 2026-10-06 (the first token and
the two chat-id lines) and 2026-10-08 (the second). No token was printed, decoded or used, no log
was deleted, and `PP_CUSTOMER_LINK_SECRET` was not rotated. The owner's instruction for this
closeout was to leave them to normal retention. That settles the third item
[phase7-deployed-behavioral-proof.md](phase7-deployed-behavioral-proof.md) §13 left owed.

One more reading, which is not a finding. The step ledger keeps the customer's channel address
whole, as the audit ledger does:

- `MARK_APPROVAL_SENT`'s result carries the request's `provider_ref`;
- check 8's stored evidence carries both identities it compared.

`_revalidation_check` in `domain/analysis.py` documents this as deliberate: the stored row is not
edited. It is the database, and no read surface projects it unmasked. The single projection masks
check 8 and every `provider_ref` it renders (ADR-0021 §4).

## 6. Evidence reconciliation

Each claim was checked against the rows, the code or CI, not taken from the record's summary.

| # | requirement | the record | cross-checked here | holds |
|---|---|---|---|---|
| 1 | local correctness closure | local-rc-correctness §1–3: execution freshness `cb96beb`, authority provenance `48f2feb`, network uncertainty `2853b85`. local-rc-final §5: "No known local P0 or P1 remains" | every cited test module and named test exists at HEAD; `pr` is green at `da7ceca`, which has the same code | yes |
| 2 | silent sibling, ADR-0025 | local-rc-final §1, `c7ac7bf`. `test_silent_sibling.py` failed 6 tests at `fe0cf80`, and 14 pass after the fix | 13 test functions, one parametrised over both claim orders; `backend + postgres` green | yes, locally. The one-customer canonical demo cannot reach it, and there is no live proof |
| 3 | execution and first-dispatch freshness, ADR-0024 and ADR-0026 | local-rc-correctness §1 and local-rc-final §2, `cb96beb` and `2742f88`. `test_execution_freshness.py`, 8 tests | re-read live: `EXT-B`'s `ORDER_AMEND` delivered at attempt 1, `last_error` null, at `16:09:49.15Z`, while `task-ol-b` starts at `22:07:35Z`. ADR-0026's gate passed with the start 5 h 58 min ahead | the passing branch, live. The refusal branch is proved locally only |
| 4 | authority provenance | local-rc-correctness §2, `48f2feb`, `test_authority_provenance.py` | re-read live: audit 362 `RECOVERY_APPLIED` and 366 `RECOVERY_COMPLETED` are both `HUMAN_APPROVAL` under `R-VISIBLE-ASK`. `pr-a`'s 339 and 344 are `CONSTRAINT` under `R-PREAPPROVED` | yes |
| 5 | network uncertainty | local-rc-correctness §3, `2853b85`. `test_customer_answer_uncertainty.py` and `customerApproval.test.tsx` | the test module and the page code are present at HEAD; `frontend` and `whole-stack browser` green | yes, locally. No lost response was forced live |
| 6 | exact-RC deployment with `Changes: []` | privacy repair §5: a parameter-only change set, `Changes: []`, `UPDATE_COMPLETE` at `16:00:45Z` | the executed change set cannot be re-read, but its consequence can: stack-level events only, 0 change sets, instance, AMI, launch time, volume and RDS unchanged, and `ImageTag`, SSM, `/healthz` and every container at `4529a802e34e` | yes |
| 7 | real Telegram message → signed link → APPROVE | privacy repair §6 | the message: one `MESSAGE_SEND` `DELIVERED` at attempt 1, `provider_ref` `telegram:<id>:6`; worker `sendMessage` 1, one HTTP 200, `getUpdates` 0 | yes |
| | | | the answer: decision `APPROVE`, parser `LITERAL`, raw `yes`; `provider_message_id` `link:…`; the sender equals the request's channel | |
| | | | the record: one reply, one `customer-reply` inbox row `PROCESSED`, and audit 348 by `CUSTOMER cus-tomas` under `HUMAN_APPROVAL` | |
| 8 | ten-check revalidation | privacy repair §6, audit 350–359 | re-read: ten `REVALIDATION_CHECK` rows, all `passed: true`, at `16:09:48.729921Z`, which is 107.8 ms after the decision at `.622150Z`. Check 4 equals the captured hash `21c4cbe8…`; check 6's start, `22:07:35Z`, was ahead. Audit 360 `RECOVERY_REVALIDATED` is `HUMAN_APPROVAL` | yes |
| 9 | v1 → v2 amendment and mirror convergence | privacy repair §6 | the order system's own store: `EXT-B v2 AMENDED ol-b=rv-raspberry-rose-3`, its event at `16:09:49.141Z` `DELIVERED`, with a command key equal to the outbox key | yes |
| | | | the mirror: `EXT-B` v2 `AMENDED` `rose-3`; audit 365 `ORDER_MIRROR_UPDATED`; `pr-b` `RECOVERED` | |
| 10 | `HUMAN_APPROVAL` through completion | privacy repair §6 | 337 and 338 by `WORKER maya`, 348 by `CUSTOMER cus-tomas`, 360, 362 and 366 by `SYSTEM`: all `HUMAN_APPROVAL`. `plan_approvals` is still 1 | yes |
| 11 | unrelated promises and orders untouched | privacy repair §6, digest `ff5ca617…` | recomputed today with the same reader, over every track, order, line, task and customer other than `pr-b` / `EXT-B`: **`ff5ca617f4d31bb1a4805e010b877adc1b3d51c27f373ba0a7977eacff0daa15`, identical** | yes |
| | | | in both the order system's store and the mirror, `EXT-C` to `EXT-F` are at v1. The order system's event log since the load holds exactly two events, `EXT-A`'s pre-approved amendment and `EXT-B`'s. `pr-e` and `pr-f` are `UNAFFECTED` and were never asked | |
| 12 | approval-token logging P1 fixed and re-verified live | privacy repair §3–§7, `b244e69`, `4529a80` | section 5: no token, no unredacted form and no identifier in any container log, or in any CloudWatch event since the release | yes |
| 13 | final remote CI green | — | section 2 | yes |

[phase7-deployed-behavioral-proof.md](phase7-deployed-behavioral-proof.md) §13 left three things
owed before Phase 7 could close on the deployment. All three are now met:

1. The P1 is fixed, released and re-measured: the privacy repair, and section 5 here.
2. Remote CI is green on the release carrying the fix: section 2.
3. The CloudWatch lines are left to normal retention: section 5.

## 7. What remains, and whether any of it blocks Phase 7

**None of it blocks Phase 7.** None is an authority breach: nothing is applied without its own
authority, and no customer's answer reaches another customer's order. Every item below was already
recorded somewhere before this closeout; none is new.

Product behaviour. Each item is disclosed, rated P2 or a residual, and proved locally:

- **ADR-0026's irreducible window.** A dispatcher can die after committing an amendment's first
  claim and before calling the provider. If it then stays down past the production start, the
  amendment is still delivered late, once, under the same key (local-rc-final §5).
- **Substitute allocation reads the clock** on automatic tracks, and those tracks do not re-run
  allocation at apply (ADR-0024, Consequences).
- **Check 5 counts only siblings already `RECOVERED`.** Two approved tracks sharing one scarce
  substitute could both pass. It was not reproduced, and no authored world has such a pair.
  ADR-0025 narrows it. P2 (local-rc-final §5).
- **An answer read while the case is `PLANNED`** waits for the worker's confirmation or the armed
  ten-minute escalation. The wait is bounded and the answer cannot be lost (ADR-0025).
- **Phase 6's P2s**, from [phase6-closeout.md](phase6-closeout.md) §8:
  - the plan identity moves when a sibling settles during `PLANNED`, which costs one re-read;
  - the `PLANNED` next-action wording at a re-planned case;
  - session 2's finding 8, reachable only through a broken persisted reply chain;
  - the frozen G7 wording of `explanations.CONSENT_AUTHORITY`, which reaches no runtime surface.

What has not been shown live. These are gaps in the live evidence, not defects:

- **No refusal path has run live.** That covers `STALE`, `EXPIRED`, `UNAUTHORIZED` and `NOOP`,
  ADR-0022's re-ask, ADR-0023's re-plan, ADR-0025's silent sibling, ADR-0026's refusal branch and
  the page's network-uncertainty behaviour. Each is proved by tests that ran green in CI. G8 asks
  for a live stale refusal.
- **No live duplicate press was made.** The proof is the unique constraints, read from the live
  catalogue (behavioural proof §6).

Operations and demo tooling:

- **The restore cannot run as shipped.** No deployed container holds every setting
  `pp restore-demo-world` needs, so each run had them supplied on the host
  ([demo-world-restore.md](demo-world-restore.md) §4). Recorded, not fixed. P2, and it matters to
  G8.
- **The start-up world roll.** A worker start re-anchors a world it does not reseed, and it once
  opened a case that stopped at `NEEDS_HUMAN_INTERPRETATION` with reason `NO_OPEN_COMMITMENT`
  ([phase7-rc-deployment.md](phase7-rc-deployment.md) §3). That diagnosis is inferred from the
  rows, and it has not been reproduced or fixed. P2, and it matters to G8.
- **The deployed world decays** from its `16:07:35Z` anchor. The non-destructive roll is refused
  while requests and outbox rows exist, so the next repair is destructive (behavioural proof §12).
- **`deploy.sh stack` cannot carry a release**
  ([non-destructive-release.md](non-destructive-release.md) §10.1). Each Phase 7 release went
  through the owner-authorised parameter-only change set, which is a documented one-off, not a
  release path.

Privacy, each disclosed:

- **Two spent tokens, and two pre-ADR-0021 chat-id lines, stay in CloudWatch** until 14-day
  retention removes them (section 5).
- **The redaction is a pattern match.** Someone who already holds a link could percent-encode the
  parameter name and get past the query-form prefix (privacy repair §8).
- **The token payload still carries the chat id.** The link format was left unchanged on purpose.
- **The Bot API has no idempotency key.** A retry in the uncertain window can duplicate a message,
  but never an effect ([customer-message-transport.md](customer-message-transport.md)).

Environment. These are vantage limitations, not product failures:

- **Smoke is not 12/12 from any one vantage** (section 4).
- **The twelve `test_mcp_protocol.py` refusals time out on the operator machine**, behind the same
  TLS proxy. CI is the authority for them, and its `mcp protocol` job is green.

## 8. The phase boundary

**Phase 7** covered the release candidate's local correctness (ADR-0024 to ADR-0026), its
deployment, the deployed behavioural proof through the real customer loop, the approval-log privacy
repair and its re-proof, and this freeze. Each is closed above.

**G8**, the roadmap's release-proof gate, **stays open.** Its central requirement is five complete
deployed rehearsals from clean fixtures, each with real customer transport and a worker restart.
None has been done. The behavioural proof and the privacy re-proof each made no worker restart,
and neither counts as one of the five (behavioural proof §12). G8 also asks for:

- a live refusal of an approved stale plan;
- the effect sets at 16/16 on the release candidate, beside the immutable `11/16` headline;
- the gate's remaining items, as `new_roadmap.md` lists them.

What Phase 7 proved is evidence G8 can cite, not a G8 rehearsal.

An open G8 does not reopen Phase 7. If G8 finds a defect in the frozen release candidate, the
defect is recorded beside this document as a later finding and repaired under G8, through a new
release that supersedes `4529a802e34e` on its own record.

## 9. Next scope: G8

In this order, one gate at a time. Anything that touches the deployment needs the owner's
authorisation.

1. **Harden the rehearsal first.** Every rehearsal restores a clean fixture and restarts a worker,
   so two recorded defects stand in the way:
   - the restore env-union defect ([demo-world-restore.md](demo-world-restore.md) §4), so that
     `pp restore-demo-world` runs as shipped from a deployed container;
   - the start-up world roll ([phase7-rc-deployment.md](phase7-rc-deployment.md) §3). Reproduce it
     locally, then decide the fix, because a rehearsal's worker restart is exactly what triggers
     it.

   Both are code changes. Each ends in a new release with `pr` green on its exact SHA, carried the
   same owner-authorised way.
2. **Predeclare the rehearsal protocol:** the clean-fixture step, the worker-restart point, the
   effect and outcome invariants each rehearsal must meet, the zero-effect check on untouched
   orders, and that failures and repairs are kept. Waiting for consent is one natural restart
   point: it is the shape of effect-set scenario 16.
3. **Run five deployed rehearsals.** Each goes:
   1. guarded restore;
   2. plan confirmation inside the ten-minute window;
   3. one real Telegram approval;
   4. a worker restart at the declared point;
   5. the customer's web answer;
   6. revalidation, amendment and convergence.

   Measure the invariants for each one.
4. **Show G8's live refusal:** an approved stale plan refusing a mutation after an explicit,
   operator-declared change to an external order or stock. It is the first live `STALE`.
5. **Close G8's other items** as the roadmap lists them.

## 10. What this closeout does not say

- **It ran no new loop and sent nothing.** Its live evidence is the records', plus today's
  re-reading of the rows those runs left.
- **It exercised no refusal path live.**
- **It did not re-read the public API payload.** The read projection is the same code measured
  publicly on `abbbd11006f7`: between the two release candidates only `logging.py`, its test and
  the Caddyfile changed.
- **It did not start CloudFormation drift detection**, so drift reads `NOT_CHECKED`. Drift was
  judged from resource identities, stack events and parameters instead.
- **It did not run the full backend suite locally.** The `pr` run in section 2 is the authority.
- **It did not investigate the certificate metadata write at `14:47:07`.** The certificate and key
  themselves are unchanged.
