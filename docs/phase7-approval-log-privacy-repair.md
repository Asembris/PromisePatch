# Phase 7 — the approval-link log leak, repaired and re-proved on the deployment

The P1 recorded in [phase7-deployed-behavioral-proof.md](phase7-deployed-behavioral-proof.md) §9
is closed. The customer approval link is a possession credential, and its payload is URL-safe
base64 that carries the customer's Telegram chat id. Both URL forms it takes, `/?approve=<token>`
and `/api/customer/approval/<token>`, were written verbatim into the `api` and `caddy` logs and
shipped to CloudWatch. That broke ADR-0021's log clause, which says a log gets the channel kind
and nothing else.

This record covers the root cause, the fix and the local proof, then the release of
`4529a802e34e`. It goes on to one guarded restore and one real Telegram approval on the deployed
host, the log scan before and after the customer answered, and a read-only assessment of the
CloudWatch history.

The earlier record is history and is not edited. Its §9 stays true of `abbbd11006f7`, and this
document is the later truth beside it.

## 1. Entry

| | |
|---|---|
| HEAD / `origin/main` | `71ee4c963acc857ed94e1b0af26a1d39f33d1f2b`, equal |
| deployed | `abbbd11006f7` |
| tracked tree | clean; the eleven known untracked artifacts left untouched throughout |

## 2. Root cause: every logging boundary, traced before editing

Each boundary was measured with a **sentinel** token, never a real one. The sentinel is shaped
exactly like a minted link and verifies against nothing.

| boundary | writes the credential? | how |
|---|---|---|
| uvicorn access log (`uvicorn.access`, stdout → `awslogs`) | **yes, both forms** | the request line is `path?query`, verbatim |
| `api.unhandled_error` (structlog) | **yes, path form** | `path=request.url.path` on any 500 from the customer route |
| `api.request_invalid` (structlog) | yes, when a request carries an oversized token | `errors=str(error)` echoes the path parameter's `input` |
| stdlib `Handler.handleError` (stderr) | **yes, if a log stream ever fails** | prints the record's raw arguments and the exception in flight, bypassing every formatter |
| Caddy access log, `request.uri` | **yes, both forms** | |
| Caddy access log, `request.headers.Referer` | **yes, the page form** | every asset load and API call the approval page makes carries the page's full URL as Referer. This is why Caddy logged 9 query-form lines where the API logged 3 |
| Caddy access log, `resp_headers.Location` | **yes** | the `:80 → :443` redirect repeats the whole URI |
| Caddy error log (`http.log.error.log0`) | **yes** | a failed upstream (a 502 during a restart) logs `request.uri` and headers, through the **default** logger, which the site's `log` block never filtered |
| worker, mcp, order-simulator | no | the link lives in the outbox payload and the Telegram body; neither is logged |
| operator CLI, public API, rendered page | no | no read surface renders the outbox payload (already measured in §10 of the earlier record) |

The Caddy rows were measured against `caddy:2.10-alpine`, the deployed image, with the
deployed Caddyfile. That covered 9 probe shapes on both a live and a dead upstream: 16 of 45
log lines held the sentinel on the dead upstream and 9 of 38 on the live one.

The existing plaintext address scans read `0` because the chat id is base64 inside the token.
They were true of what they measured and blind to this.

## 3. The fix

The fix is the smallest one that covers every row above. **The token format, the link, the
signature, possession semantics and the consent protocol are unchanged.**

**Backend** (`b244e69`, `apps/backend/src/promisepatch/observability/logging.py`). Everything the
process logs is redacted *after* it is rendered, not field by field, so a log call added later
cannot forget to:

- `APPROVAL_LINK` matches `approve=<…>` and `approval/<…>`, keeping the prefix, and also the bare
  token shape `v1.<20+>.<20+>`. So the route stays readable
  (`"POST /api/customer/approval/REDACTED HTTP/1.1" 202`), while a version string such as
  `v1.2.3` is untouched.
- The formatter of every handler on the root, `uvicorn` and `uvicorn.access` loggers is wrapped,
  so the whole finished line is redacted: message, arguments, traceback and stack.
- The last structlog processor redacts the rendered JSON line.
- `logging.raiseExceptions = False` is the standard library's documented production setting. It
  removes the one path that bypasses every formatter.

The pattern is declared in `observability`, because that layer may not import
`domain.customer_link`. The tests assert it against the real minted link and the real route.

**TLS proxy** (`4529a80`, `deploy/compose/Caddyfile`):

- A `(redact)` snippet holds a `format filter`:
  - `request>uri` is redacted by the same pattern.
  - `request>headers>Referer` is deleted.
  - `resp_headers>Location` is deleted.
- The snippet is imported by **both** the site `log` and a `log default` block, so error lines
  are filtered too.
- `Referrer-Policy "strict-origin"` sends the origin alone, so the page's address never enters a
  Referer in the first place. It is not `no-referrer`: under that policy a browser sends
  `Origin: null` on a same-origin POST, and `auth._check_origin` would refuse every sign-in.
- A few comments were condensed to keep the file inside the 4096-byte SSM parameter: 3615 bytes
  as uploaded (CRLF), from 3827.

**Why no ADR.** Nothing about what a link proves, who may answer, or where an address is stored
changed. ADR-0021 already said a log gets the channel kind and nothing else, and this makes the
log surface do what it said. `raiseExceptions` and the referrer policy change what a log and a
browser *emit*, not what anything authorises.

## 4. Local validation

| check | result |
|---|---|
| `apps/backend/tests/test_log_redaction.py` (new, 17 tests) | pass |
| — its served test **against the unfixed module** | **fails**: token, payload and signature all present in the uvicorn access log (the chat id is not in plaintext, exactly as the P1 describes) |
| — the `handleError` path without the setting | prints the sentinel; with it, prints nothing |
| `scripts/tests/test_deployment_definition.py` (4 new Caddy checks, 148 total) | pass |
| Caddy, the committed file as uploaded (CRLF), live in `caddy:2.10-alpine` | **0** sentinel bytes in any line, dead and live upstream; `uri` kept as `/?case=abc&approve=REDACTED&x=1` |
| focused DB suites: `test_customer_link`, `test_customer_approval_link`, `test_customer_approval`, `test_disclosure`, `test_app`, plus the new file | exit 0 |
| `test_telegram_channel` | pass; two tests fail *only* under `with_local_env.py`, whose `host.env` sets `PP_ORDER_SYSTEM_BASE_URL`, and pass without it. Unrelated to this change |
| script suites that capture output or embed link shapes (`sur1_run`, `sur1_consent_ingress`, `dress_rehearsal`, `run_effect_sets`, `run_head_of_line`) | exit 0; no SUR-1 or effect-set file touched |
| Playwright `customer-approval.spec.ts` on a stack rebuilt from this tree | **7/7** |
| local container logs after that spec (5 containers) | token-shaped **0**; `api` access lines read `approval/REDACTED` |
| `ruff check .`, `ruff format --check .`, `mypy` (backend group, `evals scripts`), `lint-imports` | clean; 30 contracts kept |

The served test starts a real uvicorn in its own process, built the way `pp api` builds it, and
reads everything that process wrote to stdout and stderr. Every "absent" assertion is paired
with a "present" one, so a capture that caught nothing cannot pass.

The local env files were switched to the committed examples for the Playwright run and restored
byte-exact (sha256 verified).

**Not run:** the full backend suite (about an hour; GitHub CI is the regression authority, and
this was not pushed) and the `order-simulator` mypy group, which is unaffected.

## 5. The release

It went the way `abbbd11006f7` went, through the documented one-off, not `deploy.sh stack`.
[non-destructive-release.md](non-destructive-release.md) §10.1 is unchanged.

1. **`images`**: arm64 images built from `4529a802e34e` and pushed:
   `backend@sha256:5a57e788…`, `order-simulator@sha256:9c9d138d…`.
2. **`config`**. SSM was compared with the deployed commit first: `compose` and `caddyfile` were
   byte-equal to `abbbd11`. **The first attempt was a partial write**, run with
   `MSYS_NO_PATHCONV=1`: `git -C /d/PromisePatch` could not resolve the repository, so
   `image_tag` died inside a command substitution. By then `compose` (content unchanged) and
   `caddyfile` had been written, and the empty `image-tag` was refused by SSM. Nothing reads these
   until a boot, and none happened. Re-run with `MSYS2_ARG_CONV_EXCL=/promisepatch`: `compose` v14
   (content unchanged), `caddyfile` v13 (equal to HEAD), `image-tag` v9 `4529a802e34e`.
3. **A parameter-only change set** against the previously deployed template, with `ImageTag` set
   and the other 12 parameters `UsePreviousValue`:

   ```text
   Status: CREATE_COMPLETE  ExecutionStatus: AVAILABLE  Changes: []
   parameters that differ from live: ImageTag abbbd11006f7 -> 4529a802e34e
   ```

   Executed: `UPDATE_COMPLETE` at `2026-09-24T16:00:45Z`, stack-level events only.
4. **`rollout`**: the stack, SSM and the release all named `4529a802e34e`. The host was rebooted,
   not replaced, and served `4529a802e34e`.

| | before | after |
|---|---|---|
| Stack / `ImageTag` / change sets | `UPDATE_COMPLETE` `12:54:54Z` / `abbbd11006f7` / 0 | `UPDATE_COMPLETE` `16:00:45Z` / `4529a802e34e` / 0 |
| SSM `image-tag` / `/healthz` | `abbbd11006f7` | `4529a802e34e` |
| Instance / AMI / launch / volume / IMDSv2 | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z` / `vol-0f330aaa62e637ef6` / required | **identical** |
| RDS | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, available, private, encrypted | **identical** |
| Certificate | key and certificate dated `2026-09-13 18:35:30` | **same files** |
| Docker volumes | `caddy-config`, `caddy-data`, `order-simulator-data` | all present |
| `converge.sh` / `channel.env` | `09105b10…` / `c3a6e4de…` `0600 root` | **unchanged** |
| host `boot_id` | `fe436521-…` | `109dccdf-…`, the rollout reboot and the only one |
| containers | `abbbd11006f7` | `api`, `worker`, `mcp`, `order-simulator`, `migrate` on `4529a802e34e`; `caddy` unchanged image; 0 restarts; `migrate` exit 0, no upgrade |
| `/opt/promisepatch/Caddyfile` | no redaction | `import redact` ×2, regenerated from SSM by `converge.sh` |

No IAM policy was read, broadened or written. There was no `stack`, `infrastructure` or
`host-image` stage, no host replacement, no cloud-init reseed and no volume deletion. Host access
was `ssm:StartSession` with `AWS-StartNonInteractiveCommand` alone.

**Deployed sentinel probe**, from the operator machine, with the sentinel verifying against
nothing: `/?approve=` 200, `/?case=probe&approve=&x=1` 200, the path form GET 404 and POST 404,
`/healthz` with a sentinel Referer 200, and `:80` 308. On the host afterwards:

- The `caddy` and `api` logs hold **0** sentinel payload and **0** sentinel signature bytes.
- The lines are still there: `"GET /?approve=REDACTED HTTP/1.1" 200` and
  `"POST /api/customer/approval/REDACTED HTTP/1.1" 404`.
- `Referrer-Policy: strict-origin` is served.

## 6. Live re-verification — once

The owner authorised exactly one guarded restore, one plan confirmation and one real approval
request.

**The first attempt refused itself and wrote nothing.** The dry-run gate carried over from the
last proof demanded a literally empty outbox, and this morning's loop had left three *settled*
rows (`outbox=3 unsettled=0`). The command's own refusal is for `PENDING`/`IN_FLIGHT` rows only,
so the gate was narrowed to `unsettled=0` and run again. The dry run reported
`result: nothing was written`.

**Restore**, `16:07:33.346Z` → `16:07:38.179Z`:

```text
before:   fixture=hollow-oak cases=1 live=0 outbox=3 unsettled=0 requests=1 decisions=1 approvals=1 replies=1 audit=322 events=417 bound=True
after:    fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0 replies=0 audit=336 events=436 bound=True
anchor:   2026-09-24T16:07:35.139235+00:00
digest:   0721391143866980ac49d5a303db7a15b6bb8450bea79c135c68d304e970abb6
case:     98aa7036-8ac3-54d9-aa93-d6ac378ed33c   state: PLANNED   binding: restored   ledgers: grew only
```

The host was not rebooted and nothing was sent. The canonical partition gate held: `pr-a`
`AUTO_RECOVERABLE` `R-PREAPPROVED`, **`pr-b` `APPROVAL_REQUIRED` `R-VISIBLE-ASK`
`rose-2 → rose-3`, the only approval-required option**, `pr-c`/`pr-d` `BLOCKED` `R-NOSUB`, and
`pr-e`/`pr-f` `UNAFFECTED`.

**Plan confirmation**, 4.3 s after planning: `pp confirm-plan` on the operator console as `maya`.
`plan.approval.recorded channel=OPERATOR_CONSOLE`, then
`applying=1 awaiting_approval=1 escalated=2`. Audit 337 `PLAN_APPROVED` and 338
`PLAN_CONFIRMED` are both `HUMAN_APPROVAL`, actor `WORKER maya`.

**The one message**, dispatched by the worker's own cycle, nothing sent by hand:

- `sendMessage` 1, `worker.telegram.sent` 1, `api.telegram.org` responses 1 × 200 and 0 other,
  `getUpdates` 0.
- One `MESSAGE_SEND`, `DELIVERED`, attempts 1, key `pp:approval:32f5c8fc-…`,
  `provider_ref` `telegram:<id>:6`.
- The request `32f5c8fc-57f1-5599-824a-0db13dd4e558` is `OPT-89885F`, `SENT` at
  `16:07:46.209550Z`, with deadline `21:07:35Z`.
- `pr-a` applied under `CONSTRAINT`: `EXT-A` v1 → v2 `almond-4`.
- `pr-c`/`pr-d` were `ESCALATED` with their tasks `HELD`.

### Zero leak before the customer answered

The scan reads the new link out of the outbox inside the deployed `worker` and pipes each
container's log into it. It prints counts and the link's SHA-256 only; the link never reached
the host disk, the operator shell or this record.

| container | link (whole / payload / signature) | token-shaped | unredacted query / path | address |
|---|---|---|---|---|
| `caddy` | 0 / 0 / 0 | 0 | 0 / 0 | 0 |
| `api` | 0 / 0 / 0 | 0 | 0 / 0 | 0 |
| `worker` | 0 / 0 / 0 | 0 | 0 / 0 | 0 |
| `mcp` | 0 / 0 / 0 | 0 | 0 / 0 | 0 |
| `order-simulator` | 0 / 0 / 0 | 0 | 0 / 0 | 0 |

The new link is `sha256 e77b121c…`. It differs from this morning's spent link (`64010d10…`),
because a request id is a `uuid5` over a case id that each restore mints anew.

CloudWatch since the rollout, read from the operator machine: 184 events, **0** token-shaped
strings, **0** unredacted forms, and the new link absent.

Here the session stopped and asked the owner to open the link and press APPROVE.

### The customer's answer, and the chain

The owner opened the link on the phone and pressed APPROVE.

| step | evidence |
|---|---|
| `ANSWERED` | request `32f5c8fc-…` `ANSWERED`, `decided = true` |
| literal `APPROVE` | one `approval_decisions` row: `APPROVE`, parser `LITERAL`, raw text `yes`, sender kind `tg`, **sender equals the channel the request was sent to**, `provider_message_id` `link:…`; one `inbound_replies` row; the `customer-reply` inbox event `PROCESSED` |
| `HUMAN_APPROVAL` | audit 348 `APPROVAL_DECISION_RECORDED`, actor `CUSTOMER cus-tomas`, `HUMAN_APPROVAL`, `16:09:48.622Z` |
| revalidation `PROCEED` | audit 350–359: all ten `REVALIDATION_CHECK`s passed, on a fresh snapshot. The track was `WAITING_FOR_CUSTOMER`, `EXT-B` `ACCEPTED @ v1`, `rose-2`, the production start `22:07:35Z` still ahead, and the sender and the `LITERAL` parser were as the request required. Audit 360 `RECOVERY_REVALIDATED` carries `HUMAN_APPROVAL` |
| amendment | audit 362 `RECOVERY_APPLIED`, `HUMAN_APPROVAL`: one `ORDER_AMEND`, attempts 1, `amd-04b8aa33f113`. The order system's own store and event log show `EXT-B` v1 → **v2 `AMENDED` `ol-b=rv-raspberry-rose-3`**, delivered `16:09:49.141Z` |
| mirror convergence | the order-system webhook is `PROCESSED`; audit 365 `ORDER_MIRROR_UPDATED`; the mirror equals the store for all six orders |
| `RECOVERED` / `RESOLVED` | audit 366 `RECOVERY_COMPLETED`, `HUMAN_APPROVAL`; `pr-b` `RECOVERED`; case `RESOLVED` at `16:09:55.641Z` |

**No duplicate sends or effects:**

- `sendMessage` 1 over the worker's lifetime, `getUpdates` 0.
- Outbox rows 3 (`ORDER_AMEND` ×2, `MESSAGE_SEND` ×1), each at attempt 1, with 3 distinct keys.
- 1 decision, 1 reply and 1 request.
- `plan_approvals` stayed **1**: a customer's yes spends no worker approval.

**Nothing else moved:**

- `EXT-C`…`EXT-F` stayed at v1 with their original recipes.
- The digest over every promise, order, line, task and customer other than `pr-b`/`EXT-B` is
  identical before and after the answer (`ff5ca617…`).

The `APPROVAL_DEADLINE` timer is still unfired for `21:07:35Z`. The request it names is already
answered, and it was not waited for.

### Zero leak after the customer answered

These are the requests that actually carry the link: the page load, the page's reads and the
press.

- `api` access lines: `"GET /?approve=REDACTED HTTP/1.1" 200` (the customer's, plus the earlier
  sentinel), `"GET /api/customer/approval/REDACTED HTTP/1.1" 200` ×5 and
  `"POST /api/customer/approval/REDACTED HTTP/1.1" 202`.
- `caddy`: 3 `GET /?approve=REDACTED`, 6 `GET /api/customer/approval/REDACTED`,
  2 `POST /api/customer/approval/REDACTED`, and **0** `Referer` fields.

| container | link (whole / payload / signature) | token-shaped | unredacted query / path | address |
|---|---|---|---|---|
| `caddy` | 0 / 0 / 0 | 0 | 0 / 0 | 0 |
| `api` | 0 / 0 / 0 | 0 | 0 / 0 | 0 |
| `worker`, `mcp`, `order-simulator` | 0 / 0 / 0 | 0 | 0 / 0 | 0 |

CloudWatch since the rollout: 244 events, **0** token-shaped strings, 0 unredacted forms,
`approve=REDACTED` ×7 and `approval/REDACTED` ×16, and the new link absent.

## 7. Historical logs — read-only assessment

Nothing was deleted. `/promisepatch/prod` has 14-day retention and holds 25.8 MB. Every event of
every stream was read in memory: 121 streams, 218 172 events, back to the earliest retained event
at `2026-09-11T11:23:58Z`. Logs Insights (`logs:StartQuery`) is denied to the developer role, and
IAM was not broadened for it.

| | |
|---|---|
| token occurrences | 34 (query form 27, path form 7; Caddy 23, uvicorn access 11), in 4 streams, all written before this release |
| distinct tokens | **2** |
| token #1 `ce5d1eaa…` | 14 hits, `2026-09-22T17:40:04Z`–`17:40:12Z`: the first real web approval ([deployed-customer-channel.md](deployed-customer-channel.md) §11), answered |
| token #2 `64010d10…` | 20 hits, `2026-09-24T14:14:30Z`–`14:14:38Z`: this morning's proof, answered |

**Neither is actionable.** Both requests were answered, and both have since been removed by
restores: the database now holds exactly one request, `32f5c8fc-…`, whose link (`e77b121c…`)
appears nowhere in CloudWatch. A link opens one request id, and request ids are `uuid5` values
derived from a case id that each restore mints anew. So an old token can open only the closed
view, and a press through it names a request that does not exist. No token was printed, decoded
or used.

**What remains is disclosure, not a credential.** Each of the two old tokens still carries the
demo customer's chat id in base64, readable by anyone with read access to that log group until
retention removes it: by about 2026-10-06 for #1 and 2026-10-08 for #2.

The safest remediation is to let retention expire them. It needs no action and deletes nothing.
If the owner wants the lines gone sooner, the four streams can be deleted with
`logs:DeleteLogStream`. That is destructive, removes every other line in those streams too, and
was not done.

Rotating `PP_CUSTOMER_LINK_SECRET` would make the two tokens unverifiable as well. It is
unnecessary, since they open nothing, and was not done.

## 8. What this does not prove

- **No refusal path was exercised live.** `STALE`, `EXPIRED`, `UNAUTHORIZED` and `NOOP` remain
  proved only by their tests, as before. The deployed error path of the customer route (a 500)
  was not forced; it is proved by the subprocess test and, for Caddy, by the local
  `caddy:2.10-alpine` probe on a dead upstream.
- **Smoke was not re-run** after this release. Health, readiness, the served image and the
  customer route were each checked directly instead.
- **Local and remote CI have not run on these commits**, because nothing was pushed. The full
  backend suite was not run locally.
- **The redaction is a pattern.** A client that deliberately percent-encodes the parameter name
  (`%61pprove=`) would bypass the query-form prefix. That needs someone who already holds the
  link, and the bare-token alternative still catches the token itself unless its dots are
  encoded too. The Telegram message carries the link in plain form.
- **The token still carries the chat id.** The link format is unchanged, deliberately, because
  the fix is that no log keeps the token at all.

## 9. Phase 7

The approval-token log disclosure, the P1 that held Phase 7's closeout, is closed on the
deployment, and the real customer loop has been re-proved on the repaired image. The two historical
tokens are spent and not actionable. The disclosure they still carry expires with retention unless
the owner chooses to delete the streams sooner.
