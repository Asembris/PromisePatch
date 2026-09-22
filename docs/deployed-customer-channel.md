# The deployed customer channel, and why it could not be switched on

Date: 2026-09-21
Status: **the release is performed and verified. The Telegram delivery it was for did not
happen, and nothing was sent.** A structural blocker was found, is recorded in full in section
3, and the correction in section 4 is **committed and deliberately not applied**. No message has
reached anybody, no chat id has been bound anywhere, and the deployed customer channel is still
the fake provider.

> **Extended on 2026-09-22 by [section 7](#7-the-turn-on-attempted-again-and-measured).** The
> status line above is left as written. A second attempt at the turn-on read the live state,
> found that the three SSM parameters section 5 says do not exist have since been created, and
> **measured** — rather than inferred — that the deployed processes still load no channel
> configuration at all. The blocker of section 3 is unchanged and is now the only thing left.
> No AWS resource was created, updated or deleted while section 7 was written.

This closes nothing in [customer-message-transport.md](customer-message-transport.md) section
*What is not proven*. Every line of that list is still true.

## 1. What this set out to do

Deploy the current candidate, switch the deployed worker's customer transport to Telegram, bind
the canonical demo customer to a verified private chat, and put exactly one real approval
message on a phone through the ordinary product workflow.

The first of those was done. The rest was refused, for the reason in section 3.

## 2. The release, performed

An ordinary application release at `aeb46d2bdb7f`, through the existing non-destructive path:
`images` → `config` → `stack` → `rollout` → `smoke`. Nothing else was run. `infrastructure` and
`host-image` were not run and were never going to be.

| | Before | After |
|---|---|---|
| Stack `ImageTag` | `b62779d6e975` | `aeb46d2bdb7f` |
| SSM `image-tag` | `b62779d6e975` | `aeb46d2bdb7f` |
| `/healthz` `image` | `b62779d6e975` | `aeb46d2bdb7f` |
| Migration | `0008_observer_worker_role` | `0009_human_plan_approval` |
| Host instance | `i-087c742587f83d61d` | `i-087c742587f83d61d` |
| Host AMI | `ami-0fa4996c14e7d501e` | `ami-0fa4996c14e7d501e` |
| `SeedDemoFixtureOnFirstBoot` | `false` | `false` |
| Fixture anchor | `2026-09-13T18:35:32.020039Z` | `2026-09-13T18:35:32.020039Z` |
| Fixture digest | `f6cb717c5915…d81be4` | `f6cb717c5915…d81be4` |
| Cases | 4 | 4, same ids, same states |

The change set was read before it ran and **replaced and removed nothing** — `stage_stack`'s own
guard printed exactly that and then executed the plan it had read. `0009` is additive on the
upgrade path: one `create_table`, its triggers and its grants. The unchanged fixture anchor and
digest are what say no reseed happened; the four case ids are what say it independently.

Deployment smoke: **12/12 passed, 0 failed, 0 skipped**, including `deployed-image`, which
compares what the host serves with what the stack declares.

The database was not touched beyond that migration. RDS `promisepatch-prod` is `available`,
`PubliclyAccessible: false`, `StorageEncrypted: true`, and no RDS parameter was submitted by the
release — every infrastructure parameter was read back off the live stack, which is
`create_stack_change_set`'s existing behaviour and is asserted by
[non-destructive-release.md](non-destructive-release.md) section 8.

## 3. Why Telegram could not be switched on

The four settings a deployed process needs in order to contact a customer are
`PP_CUSTOMER_CHANNEL_PROVIDER`, `PP_TELEGRAM_BOT_TOKEN`, `PP_CUSTOMER_LINK_SECRET` and
`PP_CUSTOMER_LINK_BASE_URL`. On the deployed host all four would have to arrive through
`/opt/promisepatch/env/api.env`, and **that file is written once, by cloud-init, on an
instance's first boot, and not again.** The bootstrap says so about itself, in its own first
comment:

> *This provisioning script runs once, on this instance's first boot, and not again. cloud-init's
> scripts-user module is once-per-instance*

Everything a release can move lives in the other layer — `converge.sh`, which the systemd unit
runs at every boot and which re-reads the composition, the Caddyfile and the image tag from
SSM. And `converge.sh` **rewrites no `env/*.env` file at all.** So the deployment had two
configuration layers and the customer transport was in the wrong one.

That leaves four ways in, and every one of them is closed:

- **A release cannot carry it.** `stage_stack` refuses any change set CloudFormation answers
  `True`, `Conditional` or `Remove` on, and a template whose `UserData` differs from the
  deployed one is answered `Replacement: Conditional` on the `Host`. The template has no way
  into a deployed stack through a release, and must not have one.
- **`infrastructure` can carry it, and is not a release.** It refuses to execute until the
  operator types back the id of the instance its plan may replace. That is a destructive
  confirmation, and this work was explicitly not authorised to give one.
- **Even that would not take effect.** `converge.sh` is written *by* `UserData`, so a corrected
  `converge.sh` reaches a host only when that host first boots. Applying this correction to the
  running instance is therefore not merely gated on a destructive confirmation — it requires the
  instance to be replaced, which is the one thing a deployment holding four real cases must not
  need in order to change a setting.
- **The file cannot be written out of band.** `PromisePatchDeveloperRole` holds no
  `ssm:SendCommand` — confirmed by `iam:SimulatePrincipalPolicy`, which answers `implicitDeny`,
  and by the policy document, which has no such statement. `ssm:StartSession` is granted, but
  the Session Manager plugin is not installed on the operator machine, and reaching the host
  that way would mean typing a live bot credential into an interactive shell and writing it into
  a file the repository does not own and the next instance would not have.

**The same wall stops the binding.** `pp channel bind-demo-customer` opens a database
connection, and the deployed PostgreSQL is private and reachable only from the host's security
group. Binding the deployed demo customer means running the command *on the host*, which needs
the same host-execution path that does not exist. So the binding was not attempted either, and
no deployed row carries a real chat id.

Nothing here is a weakened invariant, and nothing was worked around. It is a gap between what
`customer-message-transport.md` documented as *"two variables on the worker and a recreate"* —
which is true of the local stack, whose `docker/env/api.env` is an ordinary file — and what a
deployment whose env files are provisioning artefacts can actually do.

## 4. The correction, committed and not applied

The smallest change that puts the customer transport in the layer a release can reach. It moves
no authority, adds no table, changes no check and creates nothing that can authorise anything.

**`converge.sh` writes `env/channel.env` at every boot**, from three optional SSM parameters plus
the name this deployment's certificate is already issued for:

```text
PP_CUSTOMER_CHANNEL_PROVIDER   <- /promisepatch/<env>/customer-channel-provider, or `fake`
PP_CUSTOMER_LINK_BASE_URL      <- https://<TlsHostname>, derived rather than configured
PP_TELEGRAM_BOT_TOKEN          <- /promisepatch/<env>/telegram-bot-token, when it exists
PP_CUSTOMER_LINK_SECRET        <- /promisepatch/<env>/customer-link-secret, when it exists
```

**The two secrets are written only when they exist, never as empty values**, and that is the
detail most worth stating. `PP_TELEGRAM_BOT_TOKEN=` parses as `SecretStr('')` rather than as
`None`, so a worker selected for Telegram would build an adapter around an empty credential
instead of refusing to start — defeating precisely the refusal that exists so a deployment
cannot believe it is contacting customers while reaching nobody. `PP_CUSTOMER_LINK_SECRET=` is
worse: `customer_links_configured` would answer true and every approval link would be signed
with nothing at all.

**`api` and `worker` load `env/channel.env` beside `env/api.env`.** The worker dispatches the
message; the API verifies the link the customer opens. `mcp`, `migrate`, `seed` and
`order-simulator` do not get it, and a test asserts they do not: a bot credential in the MCP
process is the kind of thing an import-linter contract cannot see.

**They load it as an optional file, and that is load-bearing.** The composition is release
state: `stage_config` uploads it on every release and the host reads it at the next boot.
`converge.sh` is instance state: it is written by `UserData`, which cloud-init runs once per
instance. Between a release carrying this composition and the host replacement that carries the
matching `converge.sh`, a running deployment has the new file and the old script — and a
*required* `env_file` that is missing is fatal to `docker compose up`, which runs under
`set -e`. Requiring it would have meant an ordinary `deploy.sh all` stopping the live stack and
leaving it down, which is the same cross-layer coupling this section exists to remove, pointing
the other way. Absent, `api` and `worker` fall back to their own default: the fake provider,
which reaches nobody.

**`deploy.sh channel` selects the transport, and is deliberately unreachable from `all`.**
Selecting Telegram points this bakery at a real phone, so it is an operation somebody names,
exactly like `host-image`. It refuses `telegram` when no credential is stored — because the
worker's refusal-to-start is right in the process and the wrong place to discover it, a
deployment being one reboot from having no worker at all — and it stores the credential
`--no-overwrite`, so a re-run cannot rotate a live token out from under a running worker.
`customer-link-secret` joins the secrets `stage_secrets` generates.

The composition grew for the two `env_file` entries and gave back 62 bytes by compressing one
header comment, so the uploaded parameter went from 4052 to **4074 bytes against the 4096-byte
standard-tier cap** — 22 bytes of headroom where there were 44, measured with the CRLF line
endings of the checkout deploys are run from. `stage_config` refuses to upload a file over the
cap, so the next edit that does not fit fails loudly at deploy time rather than in SSM.

Eleven tests hold it, in
[`test_deployment_definition.py`](../scripts/tests/test_deployment_definition.py). The
load-bearing one is `test_the_customer_transport_is_configured_where_a_release_can_reach_it`,
which asserts both halves: that `converge.sh` writes the channel settings, and that the
once-per-instance bootstrap does **not** — because two layers writing the same setting would
leave `env_file` order deciding which deployment is contacting customers.

One harness fix came with it. `_run_stage` read its call log unconditionally and crashed when a
stage refused before making any AWS call; no stage had ever done that before. It now reads the
log as empty, which lets a test assert *this refusal made no AWS call at all* — a stronger claim
than the harness could previously express.

## 5. What was not done, stated plainly

- **No message was sent.** `sendMessage` has still never been called from this repository, live
  or otherwise. No notification reached any device.
- **No chat id was bound anywhere**, on the deployment or locally in this work. No approval
  request has ever carried a real destination.
- **No deployed process has `PP_CUSTOMER_CHANNEL_PROVIDER=telegram`.** The deployed worker runs
  the fake provider, exactly as it did before this release.
- **The deployed `PP_CUSTOMER_LINK_BASE_URL` is still unset**, so the deployed build mints no
  approval link at all — `customer_links_configured` is both-or-neither and neither half is
  configured.
- **The correction in section 4 has never run anywhere.** It is asserted on disk and has not
  been applied to the deployment, to a host, or to any SSM parameter. No parameter named in it
  exists: `customer-channel-provider`, `telegram-bot-token` and `customer-link-secret` were all
  deliberately left uncreated, because creating them would spread a credential into a new store
  to be read by a code path no running host has.
- **No AWS resource was created, replaced or deleted**, and no IAM policy was broadened. The
  only mutations were the ones an application release makes: two ECR images pushed under a new
  tag, three SSM parameters overwritten (`compose`, `caddyfile`, `image-tag`), one stack update
  that changed one parameter, and one host reboot.

## 6. What a live turn-on would take, when somebody names it

Stated so the next attempt does not rediscover section 3. **None of this was performed.**

1. `deploy.sh infrastructure`, confirmed against `i-087c742587f83d61d`, to carry the corrected
   template. It preserves the release, the host image and the database, and forces the seed off.
2. A host replacement, because `converge.sh` is written by `UserData` and a corrected one
   reaches a host only at its first boot. With `SeedDemoFixtureOnFirstBoot=false` the database
   outlives it and the cases survive — but the certificate is ordered again, and Let's Encrypt
   allows five duplicates a week for this name.
3. `deploy.sh channel` with `PP_DEPLOY_CUSTOMER_CHANNEL_PROVIDER=telegram` and
   `PP_DEPLOY_TELEGRAM_BOT_TOKEN`, then `rollout`.
4. A host-execution path for `pp channel bind-demo-customer`, which the developer role does not
   currently have. Either `ssm:SendCommand` — a grant the account owner makes, not a session —
   or the Session Manager plugin on the operator machine.
5. Only then a real proposal through the ordinary workflow, and the delivery it was for.

Steps 1, 2 and 4 are each a decision with a cost outside this repository. That is why this
document ends here rather than with a message on a phone.

---

## 7. The turn-on attempted again, and measured

Date: 2026-09-22. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything
else ran and unchanged throughout.

**Nothing was mutated.** No AWS resource was created, updated or deleted; no change set was
built; no stack was updated; no instance was rebooted or replaced; no fixture was reset; no IAM
was broadened; no chat id was bound; and no message was sent. Every AWS call below is a read,
and every application call is a `GET` or the read-only observer session of ADR-0013.

### 7.1 Entry

HEAD `d532db93ce07`, tracked tree clean, `main` equal to `origin/main`. The `pr` workflow is
green on that exact commit — 13 of 14 checks `success`, the fourteenth being
`effect sets (expected red until 16/16)`, which is the red this repository expects.

### 7.2 One claim in section 5 that is no longer true

Section 5 said, and is left as written because it was true when written:

> *No parameter it names exists: `customer-channel-provider`, `telegram-bot-token` and
> `customer-link-secret` were all deliberately left uncreated.*

All three exist now. They were created on 2026-09-21, after section 5 was written, by the
`channel` stage this document's section 4 added — which is also where commit `741ccb3` comes
from: *"ssm refuses tags with overwrite, so tag the provider on create"* is a defect found by
running that stage against the real SSM API, and `stage_channel`'s own comment records it.

| parameter | type | created | value |
|---|---|---|---|
| `/promisepatch/prod/customer-link-secret` | `SecureString` | 2026-09-21T19:29:02Z | present, not read out |
| `/promisepatch/prod/telegram-bot-token` | `SecureString` | 2026-09-21T19:29:53Z | present, not read out |
| `/promisepatch/prod/customer-channel-provider` | `String` | 2026-09-21T19:31:32Z | `telegram` |

`ssm:ListTagsForResource` is **not** granted to the developer role, so the tags were not read
and **IAM was not broadened to read them**. The names, types and timestamps are the evidence.

The fourth setting, `PP_CUSTOMER_LINK_BASE_URL`, is deliberately not a parameter: `converge.sh`
derives it as `https://$TLS_HOSTNAME`, and the stack's `TlsHostname` output is
`184.194.40.87.sslip.io`. So the base URL this deployment would mint links against is
`https://184.194.40.87.sslip.io` — HTTPS, and the name its certificate is already issued for.

### 7.3 The live state, read before anything and again after

Identical in every field. Nothing between the two reads mutated anything, and the second read
is what says so rather than the absence of a mutating call.

| | before | after |
|---|---|---|
| stack status / last updated | `UPDATE_COMPLETE` / `2026-09-21T19:28:32Z` | unchanged |
| `ImageTag` / `HostAmiId` / `SeedDemoFixtureOnFirstBoot` | `aeb46d2bdb7f` / `ami-0fa4996c14e7d501e` / `false` | unchanged |
| `HostInstanceId` | `i-087c742587f83d61d` | `i-087c742587f83d61d` |
| EC2 `ImageId` / state / launch time | `ami-0fa4996c14e7d501e` / `running` / `2026-09-18T10:19:33Z` | unchanged |
| RDS `DbiResourceId` / status / created | `db-U2JWQBTINX6W6GAB56EOTHOCSM` / `available` / `2026-09-11T11:19:51Z` | unchanged |
| SSM `image-tag` | `aeb46d2bdb7f` | `aeb46d2bdb7f` |
| `/healthz` `image` / `boot_id` | `aeb46d2bdb7f` / `bad27044-…` | unchanged, **same `boot_id`** |
| migration | `0009_human_plan_approval`, at head | unchanged |
| fixture `loaded_at` / `anchor_at` / digest | `2026-09-13T18:35:32.148240Z` / `…020039Z` / `f6cb717c…` | unchanged |
| cases | 4 | **4, and the payload is byte-identical** |
| change sets on the stack | none | none |

The unchanged `boot_id` is the load-bearing one: it says the host was not restarted, which no
comparison of stack parameters could say on its own. The case list was fetched twice through
`POST /api/auth/demo-session` and hashed; both reads are `2633a37fa759b21ade5c08b5…`.

### 7.4 The deployed runtime loads no channel configuration, and that is now measured

Section 5 asserted this from the definition. It is now observed, by one `GET` that writes
nothing, decides nothing and sends nothing:

```text
GET /api/customer/approval/not-a-real-token
503 {"error":{"code":"CUSTOMER_LINKS_NOT_CONFIGURED", ...}}
```

`_possession` in [`routers/customer.py`](../apps/backend/src/promisepatch/api/routers/customer.py)
raises `UNCONFIGURED` only when `settings.customer_link_secret is None`; a *configured* process
answers a forged token `404 LINK_NOT_FOUND` instead. So the deployed API holds no
`PP_CUSTOMER_LINK_SECRET`, which means `env/channel.env` did not reach it — and `api` and
`worker` name the same two `env_file` entries, so the worker is on the fake provider for the
same reason. **A `503` here is the runtime stating its own configuration**, which is a stronger
claim than reading the composition and reasoning about it.

The stack's deployed template was read back and contains **zero** occurrences of `channel.env`
or `customer-channel-provider`. The correction of section 4 has still never reached the stack,
let alone the host.

### 7.5 Why it still cannot be switched on

Unchanged from section 3, and now with the middle step measured rather than argued:

1. SSM says `telegram` and holds both secrets. **Nothing on the host reads them**, because
   `env/channel.env` is written only by `converge.sh`.
2. `converge.sh` is written by `UserData`, which cloud-init runs once per instance. Instance
   `i-087c742587f83d61d` has existed since 2026-09-13, so its `converge.sh` predates the channel
   block entirely. Section 7.4 is that fact showing up in the runtime.
3. `infrastructure` would carry the corrected template, and a `UserData` change is answered
   `Replacement: Conditional` — which this repository has twice observed resolving to an
   **in-place** stop/start that "leaves the instance id alone and the files on its disk
   untouched", in the `Host` resource's own comment and in
   [non-destructive-release.md](non-destructive-release.md) section 11.4. An in-place update
   does not re-run cloud-init, so it would restart the live deployment and leave `converge.sh`
   exactly as stale as it is now.
4. So the turn-on needs a **replaced instance**, which is section 6 step 2 and is the one thing
   this session was not authorised to do: `host-image` was excluded by name, and the only other
   way to force a replacement is renaming the `Host` logical resource — an `Add` of a new
   logical id plus a `Remove`, which is outside `INFRASTRUCTURE_MAY_REPLACE` and which
   `stage_infrastructure` refuses outright rather than accepting an instance id for.

Neither route was taken and no change set was built, so **`infrastructure` is still unrun
against this stack and no claim is made here about what it would propose.** Section 7.3's
"after" column is what says the deployment is where it was.

### 7.6 The Telegram preflight, run against the credential the deployment stores

`pp channel check` — `getMe` only, no `--chat-id`, no `sendMessage` — was run against the
**SSM-stored** credential rather than the developer one, because the question worth answering is
whether the token this deployment would send with is a working bot. The two turned out to be the
same credential, compared by equality and never printed.

```text
channel:  telegram
api:      https://api.telegram.org
bot:      @PromisePatchDemoBot (id 8519260202)
chat:     not checked
provider: fake
result:   reachable; no message was sent
```

`provider: fake` is the *local* shell's provider, which the command prints beside its answer for
exactly this reason: **a working credential is not a switched-on transport.** No chat was
checked, so nothing here touches a customer or a destination.

### 7.7 What was not done, stated plainly

- **No message was sent.** `sendMessage` remains uncalled from this repository, live or
  otherwise.
- **No chat id was bound**, and `bind-demo-customer` was not run.
- **No proposal was triggered**, nothing was approved or declined, and no outbox row, approval
  request or audit row was created by anything in this session.
- **No deployed process has `PP_CUSTOMER_CHANNEL_PROVIDER=telegram`**, and section 7.4 is the
  measurement that says so rather than an assumption.
- **`infrastructure` was not run**, not even to build and delete a plan. **`host-image` was not
  run.** **No host was replaced or restarted.**
- **No IAM policy was broadened**, including the `ssm:ListTagsForResource` denial of 7.2, which
  was recorded and left in place.
- The step that remains is section 6 step 2, unchanged: a replaced instance, which orders the
  certificate again against Let's Encrypt's five-duplicates-a-week limit for this name, and
  which the database and its four cases survive because `SeedDemoFixtureOnFirstBoot` is `false`.
