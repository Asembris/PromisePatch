# Bridge release revalidation 2026 10 02

The ADR-0028 release is deployed and its revalidation is complete. Product release:
`740a062838e0ea2620499abed27d653c42fc05f7`; image: `740a062838e0`. It carries `caf8064` (preserved
ledger evidence scoped to the current case incarnation) and the simulated Alexa+ via MCP bridge
(`ad64eab`), plus the deployment wiring ADR-0028 left to this release. This is an additive record.
Every earlier release, rehearsal, run and capture stays as written, including the immutable v1
**11/16** headline and the earlier v2 results.

Raw captures: [bridge-release-20261002-740a062838e0](rehearsals/runs/bridge-release-20261002-740a062838e0/),
with `capture-integrity.json` over every file and `* -text` so the bytes stay as captured.

## Release and CI

| | |
|---|---|
| Starting point | `origin/main` = `ad64eab`, tracked tree clean, eleven historical untracked artefacts untouched |
| Release-prep commit | `740a062` `build(deploy): wire the simulated Alexa+ bridge to the deployed MCP endpoint` |
| CI | [`pr` run 36925136266](https://github.com/Asembris/PromisePatch/actions/runs/36925136266): **13/13 green on the exact SHA**, `whole-stack browser` included. The v1 effect-set workflow stays red as intended and was not touched |
| Identity | `arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`, checked before work, before deployment, on resumption and at the end |

**The wiring is compose-only**, delivered through the SSM `compose` parameter that `converge.sh`
already reads at every boot. No template, `UserData`, host env file, IAM or infrastructure changed.

- `api` gets `PP_ORCHESTRATOR_MCP_URL=http://mcp:8001/mcp`, and reads `env/mcp.env` before
  `env/api.env`. That gives it the bearer the host decrypted at bootstrap, and `api.env` still wins
  every shared key. All three shared keys were proved byte-equal on the host before the change.
- `mcp` gets `PP_MCP_ALLOWED_HOSTS=${TLS_HOSTNAME},mcp:8001`: the host's previous value exactly,
  plus the one internal Host. Nothing wider.
- **Disclosed:** an existing test requires `worker` to read the same env files as `api`, so the
  worker now also holds the MCP bearer. It already held the database credential and the internal
  service token, which are strictly stronger. `PP_ORCHESTRATOR_MCP_URL` reaches only `api`.
- Two new static tests pin the URL to the `mcp` service's name, port and `MCP_PATH`, the exact
  two-entry host list, the env-file order and the bearer's absence from the composition. Both
  mutations were caught (`mcp:*`, and a swapped file order). The rendered composition was checked
  with `docker compose config`. The compose file is 4082 of 4096 bytes in the CRLF checkout,
  after shortening comments.

## Deployment

The documented path from [post-intake-release.md](post-intake-release.md) was used, with no
destructive or new infrastructure step.

1. `deploy.sh images` pushed both arm64 images. The tag was absent from both repositories before.
   - Backend: `sha256:a95740138de6d47b622a16152109192b8ecaccc58c137290355c310dcf4f87a0`.
   - Simulator: `sha256:b1c39dc334bfb0c701600306a6291cb98110200bb36b7180363ef1e13726255b`.
2. `deploy.sh stack` reproduced the template gap of
   [non-destructive-release.md](non-destructive-release.md) §10.1: `Host` and `ElasticIpAssociation`
   conditional. It refused and deleted its change set unexecuted.
3. `deploy.sh config`: SSM `compose` v15 → v16 (byte-equal to HEAD), `caddyfile` v14 → v15
   (content unchanged), `image-tag` v10 → v11.
4. A parameter-only change set, `bridge-release-740a062838e0`, against the previous template:
   `Changes: []`. Only `ImageTag` moved, `283f63f2845f` → `740a062838e0`. All twelve other
   parameters stayed at their live values, and the seed stayed `false`. Executed at 21:22:27Z.
   The stack events show stack-level rows only, and zero change sets remain.
5. `deploy.sh rollout` rebooted the existing host onto `740a062838e0` at 21:24Z.

| | before | after |
|---|---|---|
| ImageTag / DeclaredImageTag / SSM tag / `/healthz` | `283f63f2845f` | `740a062838e0` |
| Instance / AMI / launch time / address | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / 2026-09-18T10:19:33Z / `184.194.40.87` | unchanged |
| RDS | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, PostgreSQL 16.13, available | unchanged, no pending modifications |
| Migration | `0010_condition_clarification` | unchanged |
| Fixture across the rollout | anchor/loaded-at `2026-09-30T20:54:00.016517Z`, digest `033f5032…` | identical: no reseed |
| `converge.sh` / Caddyfile on host | `09105b10…` / `2336f25a…` | unchanged |

**Health.** `/healthz` reports `740a062838e0`. Readiness is `ready`, the database is reachable as
`promisepatch_app`, and migrations are at head. All five containers run the new image with zero
restarts and zero error lines. Smoke is **9/12** from this workstation: the three small-body refusals
time out in the local TLS interceptor, as documented. Run on the host through Caddy, those three
answer `401`, `403` and `421` in about 20 ms. **12/12 is not claimed from here.**

## Bridge verification

- **In-network.** An MCP `initialize` from inside `api` to `http://mcp:8001/mcp` returns **200**,
  protocol `2025-11-25`. Without the bearer it gets `401`, and with a foreign Host `421`. `mcp.start`
  logs the two allowed hosts.
- **Refusals through Caddy:**

  | Request | Result |
  |---|---|
  | Unauthenticated | `401 UNAUTHENTICATED` |
  | Observer, no CSRF | `403 CSRF_TOKEN_INVALID` |
  | Observer, with CSRF | **`403 NOT_THE_SURFACE_WORKER`**, logged `simulated_alexa.refused role=observer` |
  | An extra `actor` field | `422` (`extra_forbidden`) |

  No MCP request followed the observer refusal (last `mcp` request 21:27:28Z, refusal 21:28:35Z).
  The owner and other-worker refusals are proved by the CI tests, not live: this session does not
  sign in with passwords.
- **A real Bedrock turn.** The project owner, signed in as Maya, asked the panel for the status of
  case `d1457010…` at 21:42Z.
  - `semantic.answered`: `provider: bedrock`, `us.amazon.nova-2-lite-v1:0`, 1 attempt, 1816/27
    tokens, 1353 ms.
  - `simulated_alexa.turn`: `hydrated: true`, `selected: STATUS`, `calls: ["status"]`.
  - `mcp` logged `POST /mcp` from `172.29.0.2`, which is `api`, and two `mcp.tool.status` events:
    the hydration read and the turn's own read.
- **Secrets.** The MCP bearer, internal token and session secret appear 0 times in all five
  containers' logs, 0 times in the bridge responses, and in 0 files under the served `/app`. `mcp`
  names its caller `bearer:<sha256[:12]>`, as it always has.

## Release checks

**v2 release condition: 16/16, taken once** at 21:29:44Z–21:32:08Z against the unchanged v2
manifest (`77286e77…b0dd`, runner 1.1.0). S01–S16 PASS, exit 0, `implementation_sha` equal to the
release.
- [Capture](effect-sets/runs-v2/20261001T212944152974+0000-scored.json), sha256 `16730170…9ecd80`.
- [Console log](effect-sets/runs-v2/20261001T212944152974+0000-scored.log), sha256 `3de6e402…ad0c26`.

`working_tree_dirty=true` again, caused only by the eleven untracked artefacts. Nothing was rerun.
The local `api`, `worker` and `mcp` were stopped for the run and started afterwards.

**Demo contract: PASS, 47 assertions, exit 0** (runner 1.0.1, `scripts/demo_contract.py` sha256
`6d75a577…04326c`).
- Local images were rebuilt from the release tree. The build reproduced the existing image ids
  exactly.
- `api` and `worker` ran with fake model and channel providers through a scratch, uncommitted
  override, per the runbook.
- Restore: anchor `2026-10-02T08:14:37Z`, case `6c5eb9b0…`.
- The project owner confirmed once with `pp confirm-plan` (`OPERATOR_CONSOLE`, 08:18:25Z).
- One real `docker compose restart worker`.

As last cycle, the console path skips the runner's two browser-only assertions, so the browser
path's 49 is not claimed. This is local and fake-provider. The live deployed funnel is proved by the
rehearsals.

## R1–R5 on `740a062838e0`

The protocol, timing rules and §10.2 R3 row of
[g8-rehearsal-preparation.md](g8-rehearsal-preparation.md) were followed unchanged, with the frozen
reader whose sha256 `c9731c8f8dedfe15fbc6af0c2db6a8d5d19ca090d7863f3d2e945b18220b0dd4` the host
printed before every read.

- Every restore passed the env-union settings preflight, a dry run and the three-condition gate
  before its one confirmed run.
- Every restore carried the Telegram binding across and re-verified it (`private`, id matches, no
  message sent).
- Plan approval used the human browser channel (`BROWSER_SESSION`, the "Yes, go ahead" control),
  as in the post-intake cycle, rather than the protocol table's `OPERATOR_CONSOLE`.

Every PASS reached the same end state:

- One plan approval, one request, one `APPROVE` decision from the `LITERAL` parser with sender
  match 1, and one reply.
- **Ten revalidation checks, all passed and all written after the decision.**
- EXT-A and EXT-B at v2 on `almond-4` and `rose-3`, the store equal to the mirror.
- EXT-C to EXT-F at v1 in both the mirror and the store.
- The outbox exactly 3 rows (two `ORDER_AMEND`, one `MESSAGE_SEND`), all `DELIVERED` at attempt 1,
  with 3 distinct keys.
- Case `RESOLVED`; `task-ol-e` `STARTED` and never held.
- The unrelated digest equal from `CONFIRMED` to `SETTLED`, the `pr-e`/`pr-f` digest equal from
  `PLANNED` to `SETTLED`, and attribution counts 0/0/0/0.
- Container-log privacy 0 on every term.

The project owner confirmed exactly one new Telegram message per counted run.

All times are UTC on 2026-10-02.

| Run | Case | Confirmation | Restart point | Customer decision | Verdict |
|---|---|---|---|---|---|
| R1 attempt 1 | `3dbedd71…` | approval only, 08:36:38 | not reached | none | **VOID**, see below |
| R1 attempt 2 | `8aa0cc6e…` | 08:43:56 | `restart` 08:44:44, `…3715595f` → `…661b94ef`; identical immediately and after 95 s | 08:46:58, checks by the new instance | **PASS** |
| R2 | `0dbcde18…` | 08:52:42 with the worker stopped: steps `PENDING` at attempt 0, no effect | stop 08:50:55 → start 08:53:26, `…c3897965` dispatched everything at attempt 1 | 08:55:22 | **PASS** |
| R3 | `ba6f1754…` | 08:58:02 | stop 08:58:31; APPROVE stored as one `RECEIVED` inbox row, snapshots 65 s apart identical; start 09:01:55 | 09:02:00, after start, by `…06da4bb8` | **PASS** |
| R4 attempt 1 | `b2d506a4…` | 09:03:58 | `restart` after `RESOLVED` 09:05:05: wrote nothing | 09:04:05 | **not counted**: `CONFIRMED` digest never read |
| R4 attempt 2 | `19defd69…` | 09:08:30 | `restart` after `RESOLVED` 09:10:04, `…d9eb5326` → `…06e071ca`: wrote nothing, ledgers 1099/2610 unchanged | 09:09:12 | **PASS** |
| R5 | `b1777b99…` | 09:12:54 | `restart` 09:13:28, `…06e071ca` → `…f91fd290`; identical immediately and after 95 s | 09:15:44, checks by the new instance | **PASS** |

**R1 attempt 1, VOID.** The owner pressed "Approve this plan" in the Simulated Alexa+ panel. That
control only records an approval (ADR-0028 decision 10). This session then had the owner say
"Yes, confirm the plan" over the bridge.
- Bedrock chose `CONFIRM`, and the server blocked it with `NEEDS_THE_WORKERS_YES`: "the plan" is
  not in the closed `AFFIRMATIONS` set, which must span the whole turn.
- That is the designed fail-safe and the session's own wrong phrase, **not a product defect**.
- The case auto-escalated at 08:40:37Z: no message, no outbox row, no order write, `pr-e`/`pr-f`
  untouched.

**R4 attempt 1, not counted.** This session told the owner to answer immediately, so the protocol's
`CONFIRMED`-to-`SETTLED` digest comparison was never measured. Everything that was measured held,
including a restart that wrote nothing. R4 was rerun in full.

**Telegram.** `sendMessage` totals 6 for the whole session, one per counted run plus R4 attempt 1.
That equals the six messages the owner confirmed one by one. `getUpdates` is 0. No provider-level
exactly-once guarantee is claimed.

**Durable execution.** `FINALIZE_RECOVERY` retried while it waited for the order system's echo, as
historically documented. No external effect was repeated.

## Privacy, end to end

- **Container logs** since the deployment at 21:24Z, 9,498 lines: customer address 0, bot token 0,
  link secret 0, MCP bearer 0, internal token 0, token-shaped strings 0, unredacted
  `approve=`/`approval/` 0.
- **CloudWatch**, all six streams of `/promisepatch/prod` from 21:24Z, 9,508 events: token-shaped 0,
  unredacted query/path 0.
  - Every digit run and token-like string was reduced on the workstation to a truncated sha256 and
    compared on the host against the address, its digits and the four secrets: **0 matches**.
  - A positive control found two real worker ids and rejected an invented one.
  - A first control set was invalid (strings that never appear in log lines) and is preserved as
    such.
- The address never left the database. Snapshots and the reader printed only its length and leak
  guards, which read `False` every time.

## Limitations and anomalies

- Workstation smoke is 9/12; the three refusals were proved on the host.
- The owner and other-worker bridge refusals are proved in CI, not live.
- The bridge's live turn used `status`. No live `confirm` was spent through the bridge, and R1
  attempt 1 shows the server refusing a non-allowlisted yes.
- The session's AWS credentials expired once, between the R2 restore and the worker stop. The owner
  re-authenticated and the stop ran before any confirmation; nothing happened in between.
- The failed attempts' raw output, such as the expired-credential message and a first wrong-key
  store comparison, lives in the session transcript where a later capture overwrote the file. The
  corrected captures are preserved, and nothing is invented.
- The status lines of `ADR-0028`, `CLAUDE.md` and `README.md` were brought up to this release in
  the same docs-only commit as this record. No product or runtime file changed.

## Verdict

All ADR-0028 release obligations are complete within the scopes above: a new release SHA with
`pr` 13/13 green, a non-destructive deployment of that exact image, live bridge verification, five
passing deployed rehearsals, the v2 16/16 re-take and a demo-contract PASS. No product defect was
found. The product can be frozen at `740a062838e0ea2620499abed27d653c42fc05f7` / `740a062838e0`.
Any later change to a deployable product path voids that freeze.
