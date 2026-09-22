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

---

## 8. The migration performed, and the transport switched on

Date: 2026-09-22. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything
mutated and unchanged throughout.

**The deployed worker and API now run `PP_CUSTOMER_CHANNEL_PROVIDER=telegram`, and still nothing
has been sent.** The host was not replaced, not rebooted and not re-provisioned. Its four cases,
its fixture and its database are byte-for-byte where they were.

Sections 3, 6 and 7 are left exactly as written. This section records the later truth beside
them rather than inside them.

### 8.1 The one claim in sections 6 and 7.5 that was too strong

Section 7.5 step 4 concluded:

> *So the turn-on needs a **replaced instance**, which is section 6 step 2.*

That is now falsified, and the correction is worth stating precisely because the reasoning
around it was right. `converge.sh` on this instance is still the stale one, and a *release*
still cannot fix that — every word of section 3 about the two configuration layers holds. What
section 3's fourth bullet got wrong was a fact about the operator machine, not about the
deployment:

> *`ssm:StartSession` is granted, but the Session Manager plugin is not installed on the operator
> machine, and reaching the host that way would mean typing a live bot credential into an
> interactive shell.*

The plugin is installed now — `session-manager-plugin` 1.2.835.0 — and the second half was a
false constraint. **Nothing had to be typed in.** The channel block in `converge.sh` reads every
value from SSM using the *instance* role; reproducing that block on the host reads them the same
way. The credential never entered the operator's shell, never appeared in an argument, and was
never printed. `ssm:SendCommand` is still not granted and was not used; `ssm:StartSession` with
`AWS-StartNonInteractiveCommand` is the whole of the access, and **no IAM policy was broadened.**

So a replaced instance is what the *committed* correction needs in order to own this setting. It
was never what *switching the transport on* needed.

### 8.2 The state before, recorded before anything mutated

| | value |
|---|---|
| HEAD / tree / `origin/main` | `f35d1afe4ab3`, tracked tree clean, equal to `origin/main` |
| CI on `d532db93` | 13 `success`, 1 failure: `effect sets (expected red until 16/16)` |
| Host instance / AMI / launch | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z` |
| Host kernel `boot_id` / uptime since | `eb889c14-2aa2-462a-a0c6-e73ff8886014` / `2026-09-21 19:30:20` |
| RDS `DbiResourceId` | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, private, encrypted |
| Stack status / last updated | `UPDATE_COMPLETE` / `2026-09-21T19:28:32Z`, no change sets |
| `/healthz` image / process `boot_id` | `aeb46d2bdb7f` / `bad27044-bbef-4528-a137-d44956dc2129` |
| Fixture `loaded_at` / `anchor_at` / digest | `...148240Z` / `...020039Z` / `f6cb717c...d81be4` |
| Cases | 4, payload digest `0754fcde7c4e...c97fe1` |
| Outbox | 2 rows, **both `DELIVERED`**, newest `2026-09-13T18:36:46Z` |
| Approvals | `approval_requests` 1, `approval_decisions` 0, `plan_approvals` 0 |
| Customers | 6, all `approval_channel_kind=telegram`, **every address 4 characters** |
| `env/channel.env` | absent |
| Host `converge.sh` | `45f5145e...188a`, **zero** channel references |
| `env/api.env` | carries **no** channel setting |
| SSM `compose` | version 8, **zero** `channel.env` occurrences |
| Forged approval `GET` | `503 CUSTOMER_LINKS_NOT_CONFIGURED` |

Two of those rows are the reason this was safe to do at all. **The outbox held no `PENDING` and
no `IN_FLIGHT` row**, so switching the provider and restarting the worker had nothing queued to
flush. And **every customer address is four characters**, so no row carries a real chat id and no
dispatch could have reached a person even if one had been queued.

### 8.3 The migration, exactly

Three steps, each through `ssm:StartSession` with `AWS-StartNonInteractiveCommand`, the script
base64'd so nothing depended on quoting, and every command run as `sudo bash` because
`/opt/promisepatch` is `root`-owned.

**One.** The committed channel block from `converge.sh`, reproduced verbatim on the host — the
same `param` helper, the same `fake` default, the same `https://$TLS_HOSTNAME` derivation, the
same `umask 0077`, and the same two guards that write a secret only when it exists:

```text
CHANNEL_PROVIDER="$(param customer-channel-provider 2>/dev/null || true)"
if [ -z "$CHANNEL_PROVIDER" ]; then CHANNEL_PROVIDER=fake; fi
BOT_TOKEN="$(param telegram-bot-token 2>/dev/null || true)"
LINK_SECRET="$(param customer-link-secret 2>/dev/null || true)"
umask 0077
{
  echo "PP_CUSTOMER_CHANNEL_PROVIDER=$CHANNEL_PROVIDER"
  echo "PP_CUSTOMER_LINK_BASE_URL=https://$TLS_HOSTNAME"
  if [ -n "$BOT_TOKEN" ]; then echo "PP_TELEGRAM_BOT_TOKEN=$BOT_TOKEN"; fi
  if [ -n "$LINK_SECRET" ]; then echo "PP_CUSTOMER_LINK_SECRET=$LINK_SECRET"; fi
} > env/channel.env
umask 0022
```

Result: `-rw------- root root`, 232 bytes, four keys, both secrets present. The identity that
read them is
`arn:aws:sts::265243686715:assumed-role/PromisePatchInstanceRole/i-087c742587f83d61d` — the
host, using its own instance role, which is the whole point. Only the two non-secret values were
ever echoed back.

**Two.** The committed composition uploaded to SSM, because the host's `docker-compose.yml` is
derived from that parameter at every boot and writing only the file would have been undone by
the next one. This is exactly the call `stage_config` makes for `compose`: same name, same
`String` type, same `--overwrite`.

```text
/promisepatch/prod/compose   version 8 -> 9, 4072 chars, 2 occurrences of channel.env
```

**`deploy.sh config` was deliberately not used, and this is a trap worth naming.** That stage
also writes `image-tag` from `$(image_tag)`, which is `git rev-parse --short=12 HEAD` — today
`f35d1afe4ab3`, a **docs-only commit for which no image was ever built**. Running it would have
pointed the parameter the host converges on at an image that does not exist, and the next boot
would have failed to pull. `caddyfile` was compared and is byte-identical to the committed one,
so it was not written either. One parameter moved; the other two were left alone on purpose.

**Three.** The composition fetched on the host the way `converge.sh` fetches it, then `api` and
`worker` recreated — and nothing else:

```text
param compose > docker-compose.yml        4051 -> 4073 bytes, 2 channel.env occurrences
docker compose --env-file env/stack.env up -d api worker
```

Before that third step the candidate was validated *on the host*: `docker compose config`
answered `OK` under the host's Compose v2.32.4, which is the version that matters because the
optional-`env_file` form needs 2.24 or newer. The resolved configuration was then checked
key-by-key, and it places the four channel settings in `api` and `worker` and in **no other
service** — `caddy`, `mcp`, `migrate` and `order-simulator` all resolve to none of them, which is
the live counterpart of the test section 4 calls load-bearing.

`migrate` ran once, as its `service_completed_successfully` dependency requires, exited `0`, and
logged no `Running upgrade` line: the database was already at `0009_human_plan_approval` and the
`alembic upgrade head` was the no-op it is designed to be.

### 8.4 The activation, proved

**The deployed processes state their own configuration.** `pp channel check` was run inside the
deployed `worker` and the deployed `api` containers — `getMe` only, no `--chat-id`, and the
preflight has no `sendMessage` in it at all:

```text
channel:  telegram
api:      https://api.telegram.org
bot:      @PromisePatchDemoBot (id 8519260202)
chat:     not checked
provider: telegram
result:   reachable; no message was sent
```

`provider: telegram` is the line that has never appeared from a deployed process before. In
section 7.6 the same command printed `provider: fake`, because it was the operator's shell
answering. This is the worker.

**The runtime's own answer to a forged link changed.** This is the measurement section 7.4
established as stronger than reading the composition and reasoning about it:

```text
GET /api/customer/approval/not-a-real-token
before  503 {"error":{"code":"CUSTOMER_LINKS_NOT_CONFIGURED", ...}}
after   404 {"error":{"code":"LINK_NOT_FOUND", ...}}
```

`_possession` raises `UNCONFIGURED` only when `settings.customer_link_secret is None`. A `404` is
the API saying it holds the secret, minted no link for that token, and refused it on the merits.
`pp runtime-identity` in the worker agrees:
`customer_link_base_url: https://184.194.40.87.sslip.io`.

Deployment smoke: **12/12 passed, 0 failed, 0 skipped**, including `deployed-image`, which still
reports `aeb46d2bdb7f`. `api` is `healthy` with `RestartCount 0`; `worker` is running with
`RestartCount 0` and logged one clean `worker.start`.

### 8.5 Nothing was sent, and nothing was created

| | before | after |
|---|---|---|
| `outbox_messages` | 2, both `DELIVERED` | **2, both `DELIVERED`** |
| newest outbox `created_at` | `2026-09-13T18:36:46Z` | unchanged |
| rows with a `provider_ref` | 2 | 2 |
| `approval_requests` / `approval_decisions` / `plan_approvals` | 1 / 0 / 0 | **1 / 0 / 0** |
| customers with a real chat id | 0 (all addresses 4 chars) | **0, all six unchanged** |
| dispatch or `sendMessage` lines in `api` + `worker` logs | — | **0** |

`bind-demo-customer` was not run, no chat id was used, no proposal was triggered, nothing was
approved or declined, and `sendMessage` remains uncalled from this repository.

### 8.6 Data and infrastructure, preserved

| | before | after |
|---|---|---|
| Host instance / AMI / launch time | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z` | **all three unchanged** |
| Host kernel `boot_id` | `eb889c14-2aa2-462a-a0c6-e73ff8886014` | **identical — no reboot** |
| Host uptime since | `2026-09-21 19:30:20` | **identical** |
| `caddy` / `mcp` / `order-simulator` | up 20 hours | **still up 20 hours, untouched** |
| RDS `DbiResourceId` | `db-U2JWQBTINX6W6GAB56EOTHOCSM` | unchanged, `available`, private, encrypted |
| Stack status / last updated | `UPDATE_COMPLETE` / `2026-09-21T19:28:32Z` | **unchanged — no stack update** |
| Change sets | none | none |
| `ImageTag` / `HostAmiId` / `SeedDemoFixtureOnFirstBoot` | `aeb46d2bdb7f` / `ami-0fa4996c14e7d501e` / `false` | unchanged |
| Migration | `0009_human_plan_approval` | unchanged, at head |
| Fixture `loaded_at` / `anchor_at` / digest | `...148240Z` / `...020039Z` / `f6cb717c...` | **all unchanged** |
| Cases | 4, digest `0754fcde7c4e...c97fe1` | **4, digest identical** |

The host kernel `boot_id` is the load-bearing row: it changes only on a real reboot, and it did
not move. The `/healthz` `boot_id` *did* change, from `bad27044...` to `b0124ede...`, and that is
correct — `health.py` says it "changes on every process start", so it reports the API restart
that was the point of the exercise and says nothing about the host.

**`infrastructure` was not run. `host-image` was not run. No host was replaced or rebooted. No
IAM policy was broadened, read or written.** The only AWS mutation in this entire session is the
single `compose` parameter going from version 8 to version 9.

### 8.7 What is still not done, and one honest limitation

- **No message was sent**, and `sendMessage` has still never been called from this repository.
- **No chat id is bound anywhere.** Every deployed customer still carries a placeholder.
- The deployed transport is switched on and **reaches nobody**, because there is no destination.
- **The host's `converge.sh` is still the stale one**, unchanged at `45f5145e...188a`. It was
  deliberately not rewritten: replacing it is instance state, and this work reproduced only the
  migration's effect, not its owner.
- **So `env/channel.env` is hand-written, not derived.** Nothing deletes it, and `converge.sh`
  writes `docker-compose.yml`, `Caddyfile` and `env/stack.env` only, so the activation is
  expected to survive a reboot — **but that expectation was reasoned, not measured**, because
  this work was not authorised to reboot and did not. The real consequence is refresh rather than
  survival: if the bot token is rotated in SSM, this instance keeps the old one until the
  migration is re-run or the host is replaced with one carrying the committed `converge.sh`.
- Two files predating this session sit in `/opt/promisepatch` — `check_state.py` and a 0-byte
  `check_state.pynsha256sum`, both dated 2026-09-21. They are referenced by nothing and were
  **left exactly where they were.** `docker-compose.yml.pre-channel` is this session's own copy
  of the version-8 composition, kept beside it deliberately.

### 8.8 The next step, for whoever takes the first real delivery

The transport is on. What remains is a destination and then a proposal, in that order:

1. `pp channel bind-demo-customer --chat-id <numeric-id>` **run on the host**, through the same
   Session Manager path used here, because the deployed PostgreSQL is private and reachable only
   from the host's security group. It verifies the chat against Telegram before it writes and
   echoes no chat id. A chat id goes stale 24 hours after the customer last messages the bot, so
   re-message the bot immediately before binding.
2. One proposal through the ordinary workflow, and the approval it queues, which the real adapter
   will then dispatch to a real device — the first `sendMessage` this repository has ever made.

Neither was performed here, and neither is authorised by this document.

## 9. The first real delivery attempted, and the world that could not host it

Date: 2026-09-22, after section 8 and in a separate session. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything was
read and unchanged throughout.

**Nothing was sent, nothing was bound, and nothing was written anywhere.** The transport section 8
switched on is live and correct; the destination was verified against Telegram; and the delivery
still did not happen, because **the deployed demo world is nine days past its anchor and no longer
contains a promise a customer can be asked about.** That is a property of the seeded data, not a
defect in any code path, and the repair for it is destructive and an operator's to choose.

Section 8.8 is answered here: its step 2 cannot be taken, and its step 1 must not be taken before
the repair, for the reason in section 9.5.

### 9.1 Entry, and the live state measured before anything

| | value |
|---|---|
| HEAD / tree / `origin/main` | `37ca23a76260`, tracked tree clean, equal to `origin/main` |
| CI on `d532db93` | 13 `success`, 1 failure: `effect sets (expected red until 16/16)` |
| Stack status / last updated | `UPDATE_COMPLETE` / `2026-09-21T19:28:32Z`, unchanged, no change sets |
| `ImageTag` / `HostAmiId` / `SeedDemoFixtureOnFirstBoot` | `aeb46d2bdb7f` / `ami-0fa4996c14e7d501e` / `false` |
| Host instance / AMI / launch | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z`, `running` |
| Host kernel `boot_id` / uptime since | `eb889c14-2aa2-462a-a0c6-e73ff8886014` / `2026-09-21 19:30:20` |
| `/healthz` image / process `boot_id` | `aeb46d2bdb7f` / `b0124ede-182c-4210-9604-74e4d69d6291` |
| `api` / `worker` | `healthy` and `running`, `RestartCount` **0** on both |
| Deployed runtime provider | `pp channel check` **inside `worker`**: `provider: telegram`, `getMe` reachable, no message sent |
| Forged approval `GET` | `404 LINK_NOT_FOUND` — the API holds the link secret and refused on the merits |
| Fixture | `hollow-oak`, `anchor_at` `2026-09-13T18:35:32.020039Z`, digest `f6cb717c...d81be4` |
| Cases | 4 — one `PLANNED`, two `RESOLVED`, one `NEEDS_HUMAN_INTERPRETATION` |
| Outbox | 2 rows, **both `DELIVERED`**, 2 carrying a `provider_ref`, newest `2026-09-13T18:36:46Z` |
| `approval_requests` / `approval_decisions` / `plan_approvals` | 1 / 0 / 0 |
| Customers | 6, all `telegram`, **every address 4 characters** |

**No `PENDING` and no `IN_FLIGHT` outbox row exists**, so nothing was queued that a restart or a
provider switch could have flushed at a person. Every one of those rows is identical to sections
8.2 and 8.5, which is the point: the host has not moved since the migration.

### 9.2 The destination is ready, and that is proved

`pp channel check --chat-id` was run against the chat the operator holds, with the bot credential
the deployment stores. `getMe` and `getChat` only; the preflight contains no `sendMessage` and no
inbound path of any kind.

```text
channel:  telegram
bot:      @PromisePatchDemoBot (id 8519260202)
chat:     <not echoed> (private)
provider: telegram
result:   reachable; no message was sent
```

The id Telegram returned is **equal to the id asked about** and the chat is **`private`** — both
checked by comparison rather than by eye, because the id itself is a real person's identifier and
is not printed, logged or committed. It was read from gitignored local state, so **no `getUpdates`
call was needed or made**, and the id never entered an AWS API call, a Session Manager parameter
or this repository.

So the half of the delivery that section 8.7 called *"reaches nobody, because there is no
destination"* now has a verified destination waiting. It is still not bound, for the reason in
9.5.

### 9.3 No deployed case can produce an approval proposal

The four cases were read, and only one is in a state a confirmation could act on.

| case | state | can it propose? |
|---|---|---|
| `637b8f53-0b07-5c75-82ec-96ebd13fa8da` | `PLANNED` | **no** — see below |
| `744f5f78-0059-5d40-a15b-37a0d87199bf` | `RESOLVED` | no, settled |
| `7e6319bc-ed3b-5df5-ac46-5f96dbaa13a5` | `RESOLVED` | no, settled |
| `e66c5060-fddd-5724-b846-6c75af70e462` | `NEEDS_HUMAN_INTERPRETATION` | no, and unrecoverable without a reset |

`pp case-status` on the one `PLANNED` case reports an exception of category `STOCK_UNUSABLE`
grounded on `res-heavy-cream` — **not** the canonical raspberry incident — and six tracks of which
five are `UNAFFECTED via R-UNREACH (NOT_REACHABLE)` and one, `pr-e`, is `BLOCKED via R-UNKNOWN
(NO_CONSTRAINT_SNAPSHOT)`. **Every one of the six prints `no recovery option`.** `pr-b` — Tomas
Lindqvist on `EXT-B`, the customer `bind-demo-customer` derives and the only promise in the demo
whose recovery waits on a person — is one of the five unreachable ones.

A confirmation of that plan would therefore raise **zero** customer approval requests. It would
escalate `pr-e` to the owner and spend a human approval to do it, which is a write with no
delivery at the end of it, so it was not performed.

### 9.4 And no fresh exception could either, because the world is stale

The obvious next thought — report a new exception through the ordinary intake path, which alters
no timestamp and reseeds nothing — was checked before it was acted on, against the engine rather
than by argument. `promise_graph` is pure and takes `now` explicitly, so the question is directly
computable: load the committed fixture at **the deployed anchor** and classify every promise at
**today's clock**.

| exception | at its own anchor | today |
|---|---|---|
| `raspberry_only` | `APPROVAL_REQUIRED` 1 (`pr-b`, 1 valid option), `BLOCKED` 2, `UNAFFECTED` 3 | **`BLOCKED` 4, `UNAFFECTED` 2** |
| `whole_delivery` | `APPROVAL_REQUIRED` 1 (`pr-b`, 1 valid option), `BLOCKED` 2, `UNAFFECTED` 3 | **`BLOCKED` 4, `UNAFFECTED` 2** |
| `cream_unusable` | `UNAFFECTED` 6 | `UNAFFECTED` 6 |
| `deck_oven_down` | `AUTO_RECOVERABLE` 2, `BLOCKED` 1, `UNAFFECTED` 3 | **`UNAFFECTED` 6** |

**At today's clock the deployed world yields no `APPROVAL_REQUIRED` band from any exception it can
express.** The raspberry incident that used to ask a customer now fails closed to `BLOCKED` on four
promises and reaches nobody, which is the invariant working: unknown or expired state goes to the
owner, never to a customer. This is the decay [demo-world-roll.md](demo-world-roll.md) measures —
*"a seed is good for the rest of its own bakery day and no longer"* — observed nine days in.

So there was no case to select and no case to make. The instruction under which this work ran said
to stop rather than to force eligibility, and stopping is also what the product's own rules
require: making a customer reachable again means moving the world, and moving the world is the
operation in 9.5.

### 9.5 Why the binding was **not** performed, though it was authorised

`pp channel bind-demo-customer` was authorised for this work and was deliberately not run. The
reason is an ordering fact that was not visible when that step was written:

- **The non-destructive repair is permanently refused on this host.** `reanchor.reanchor_world`
  moves the world without truncating anything, and it refuses outright if *any* row exists in
  `outbox_messages`, `inbound_replies`, `approval_requests` or `approval_decisions` — unscoped by
  case and unscoped by time. This deployment holds 2 outbox rows and 1 approval request from
  2026-09-13. [demo-world-roll.md](demo-world-roll.md) states that this refusal is **monotone and
  permanent**, and that the only statement which removes those rows is the reset's `TRUNCATE`.
- **The destructive repair erases a binding.** `pp reset-demo-state` truncates the domain rows
  PromisePatch owns, which returns the demo customer to the fixture's own committed address. The
  binding module says as much about itself, and a binding taken now would be gone the moment the
  world is made current.

Binding first would therefore have written a real person's chat id into a row that the very next
required step deletes, and would have spent the operator's live chat window to do it. The
destination was verified instead — which proves the same reachability and writes nothing.

### 9.6 Nothing was written, anywhere

| | before | after |
|---|---|---|
| `outbox_messages` | 2, both `DELIVERED` | **2, both `DELIVERED`**, newest `2026-09-13T18:36:46Z` |
| rows with a `provider_ref` | 2 | 2 |
| `approval_requests` / `approval_decisions` / `plan_approvals` | 1 / 0 / 0 | **1 / 0 / 0** |
| cases | 4, `id:state` digest `29b37014d418b0f0aea8e5f55eef54ce` | **4, digest identical** |
| customers with a real chat id | 0, all six addresses 4 characters | **0, all six unchanged** |
| fixture `anchor_at` / digest | `...020039Z` / `f6cb717c...d81be4` | unchanged |
| `sendMessage` or dispatch lines in `api` + `worker` logs | — | **0** |
| `api` / `worker` `RestartCount` | 0 / 0 | **0 / 0** |
| Host kernel `boot_id` | `eb889c14...` | **identical — no reboot** |
| Stack status / change sets | `UPDATE_COMPLETE` / none | unchanged / none |

**No AWS resource was created, updated or deleted.** No SSM parameter was written — not even
`compose`, which section 8 moved. No release was run, no host was replaced or rebooted, no IAM
policy was read, broadened or written. Every host command went through `ssm:StartSession` with
`AWS-StartNonInteractiveCommand` and every one of them was a read. `sendMessage` has still never
been called from this repository.

### 9.7 The next step, in the order it has to happen

The transport is on and a verified private chat is waiting. What is missing is a world with a
customer in it, and the repair for that destroys the four deployed cases. **That is an operator's
decision and is not authorised by this document.** When somebody takes it, the order is not
negotiable:

1. **Decide to lose the four deployed cases.** Two are `RESOLVED`, one is
   `NEEDS_HUMAN_INTERPRETATION`, and the `PLANNED` one shows no authority band. The repair is the
   four-step one in [demo-fixture-anchoring.md](demo-fixture-anchoring.md), *Bringing a running
   deployment back to the story*: reseed, reset the External Order System, restart the worker,
   sign in again.
2. **Re-message the bot from the phone**, because the repair invalidates nothing about Telegram
   but the operator's chat window is what `getChat` verifies against.
3. **`pp channel bind-demo-customer --chat-id <numeric-id>`, on the host, after the reseed.**
   Before it, the reseed erases it.
4. **One proposal through the ordinary workflow** on the case provisioning opens against the fresh
   world, whose `EXT-B` band is the one waiting on a customer — and the approval it queues is
   dispatched by the real adapter to a real device.

Step 4 is still the first `sendMessage` this repository has ever made, and it is still unmade.

## 10. The world repaired, the destination bound, and the first message delivered

Date: 2026-09-22, after section 9 and in a separate session. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything
mutated and unchanged throughout.

**One real approval message was dispatched to a real phone and Telegram accepted it.** That is
the first `sendMessage` this repository has ever made, and it closes section 9.7 step 4 and
section 8.8 step 2. It cost the four deployed cases, which the operator authorised losing.

Sections 3, 6, 7, 8 and 9 are left exactly as written. This section records the later truth
beside them rather than inside them.

### 10.1 Entry

| | value |
|---|---|
| HEAD / tree / `origin/main` | `d4ef1beb7c37`, tracked tree clean, equal to `origin/main` |
| Stack status / last updated | `UPDATE_COMPLETE` / `2026-09-21T19:28:32Z`, no change sets |
| `ImageTag` / `HostAmiId` / `SeedDemoFixtureOnFirstBoot` | `aeb46d2bdb7f` / `ami-0fa4996c14e7d501e` / `false` |
| Host instance / AMI / launch | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z`, `running` |
| Host kernel `boot_id` / uptime since | `eb889c14-2aa2-462a-a0c6-e73ff8886014` / `2026-09-21 19:30:20` |
| RDS | `promisepatch-prod`, `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, private, encrypted |
| `/healthz` image / process `boot_id` | `aeb46d2bdb7f` / `b0124ede-182c-4210-9604-74e4d69d6291` |
| Deployed runtime provider | `pp channel check` **inside `worker`**: `provider: telegram` |
| Forged approval `GET` | `404 LINK_NOT_FOUND` |
| Fixture | `hollow-oak`, `anchor_at` `2026-09-13T18:35:32.020039Z`, digest `f6cb717c...d81be4` |
| Cases | 4 -- one `PLANNED`, two `RESOLVED`, one `NEEDS_HUMAN_INTERPRETATION` |
| Outbox | 2 rows, **both `DELIVERED`**, both carrying a `provider_ref` |
| `approval_requests` / `approval_decisions` / `plan_approvals` / `inbound_replies` | 1 / 0 / 0 / 0 |
| Customers | 6, all `telegram`, **every address 4 characters** |
| `audit_events` / `domain_events` | 173 / 227 |
| Migration | `0009_human_plan_approval`, at head |

**No `PENDING` and no `IN_FLIGHT` outbox row existed**, so the repair had nothing queued that a
restart could have flushed at a person. Every row above is identical to section 9.1.

### 10.2 The destructive repair, exactly the four documented steps

Run in `/opt/promisepatch` through `ssm:StartSession` with `AWS-StartNonInteractiveCommand`, the
payload base64 encoded and executed from a file rather than from stdin. **`ssm:SendCommand` is
still not granted and was not used. No IAM policy was read, broadened or written.**

| step | command | result |
|---|---|---|
| 1 | `docker compose --env-file env/stack.env run --rm -T seed` | `hollow-oak`, anchor `2026-09-22T16:47:06.452592Z`, digest `3a33a523...59e89d`, 160 rows, audit seq 174 |
| 2 | `exec order-simulator ... POST /admin/reset` | `200 {"reset":true,"orders":6}` |
| 3 | `docker compose --env-file env/stack.env restart worker` | `provisioning.demo_case.opened`, `a3810ae5-6337-559b-8b97-47023bc0094c`, `PLANNED`, `rolled: false` |
| 4 | re-authenticate | `sessions` is truncated by step 1; the evidence below is read through the host rather than a browser session, so no sign-in was needed |

The anchor was **omitted**, so `resolve_demo_anchor` chose `now`. Local Tunis time was 17:47,
inside the `[01:00, 23:00)` window `122bebb` exists to keep the seed out of, so `now` was
returned untouched and no clock was moved by hand.

**`docker compose down -v` was not used**, so `caddy-data` and the Let's Encrypt certificate were
never at risk. No volume was removed, no host was replaced, no cloud-init reseed was triggered,
and no timestamp was edited.

### 10.3 The repair, proved

**The world is current.** `fixture_state` reads `hollow-oak` at `2026-09-22T16:47:06.452592Z`,
nine days forward of where section 9 found it, with a new digest `3a33a523...59e89d`.

**The canonical partition is restored**, read from `pp case-status` on the provisioned case --
exception `SUPPLY_NOT_RECEIVED`, plan `0fbe85e5db31...025649`:

| promise | band | option |
|---|---|---|
| `pr-a` / `EXT-A` Priya Nair | `AUTO_RECOVERABLE` via `R-PREAPPROVED (PREAPPROVAL_COVERS)` | `rv-raspberry-almond-3 -> rv-raspberry-almond-4` (no approval) |
| `pr-b` / `EXT-B` Tomas Lindqvist | **`APPROVAL_REQUIRED`** via `R-VISIBLE-ASK (VISIBLE_CHANGE_ASK)` | `rv-raspberry-rose-2 -> rv-raspberry-rose-3` (**approval required**), window closes `2026-09-22T21:47:06Z` |
| `pr-c` / `EXT-C` Okafor-Reyes | `BLOCKED` via `R-NOSUB (NOSUB_CONSTRAINT)` | none -- owner |
| `pr-d` / `EXT-D` Lena Fischer | `BLOCKED` via `R-NOSUB (NO_PREAUTHORED_VARIANT)` | none -- owner |
| `pr-e` / `EXT-E` Ahmed Bouazizi | `UNAFFECTED` via `R-UNREACH (NOT_REACHABLE)` | none |
| `pr-f` / `EXT-F` Cafe Marlow | `UNAFFECTED` via `R-UNREACH (NOT_REACHABLE)` | none |

That is the partition section 9.4 computed as unreachable at the old anchor, now reachable
again, and `pr-b` carries exactly **one valid option**.

**The ledgers of record survived the `TRUNCATE`.** `audit_events` went 173 to 186 and
`domain_events` 227 to 245 across the repair: both only ever grew. The reset's own audit row is
seq 174, appended rather than restarting at 1, which is what says the ledger was not among the
`resettable_tables()`.

**The infrastructure did not move.** RDS `db-U2JWQBTINX6W6GAB56EOTHOCSM` is `available`, private
and encrypted, created `2026-09-11T11:19:51Z`. The stack is `UPDATE_COMPLETE` at
`2026-09-21T19:28:32Z` with no change sets. The host kernel `boot_id` is still
`eb889c14-2aa2-462a-a0c6-e73ff8886014` and `uptime -s` still `2026-09-21 19:30:20` -- **no
reboot**. `api` never restarted at all: its process `boot_id` is still `b0124ede-...`, and
`caddy`, `mcp` and `order-simulator` were untouched. `api` and `worker` both hold
`RestartCount 0`. Migration unchanged at `0009_human_plan_approval`.

**The transport survived the repair**: `pp channel check` inside the deployed `worker` still
answers `provider: telegram`, and a forged approval token still answers `404 LINK_NOT_FOUND`.

**The repair sent nothing.** After all four steps the outbox held **0** rows,
`approval_requests` **0**, `approval_decisions` **0**, `plan_approvals` **0**, `inbound_replies`
**0**, and the worker log carried **zero** `sendMessage` lines. The reset returned all six
customers to the fixture's own four-character placeholders, which is section 9.5's ordering fact
observed: a binding taken before the repair would have been erased by it.

### 10.4 The destination, verified and then bound

`pp channel check --chat-id` was run **inside the deployed `worker`**, so the process that would
send is the process that proved it could reach. `getMe` and `getChat` only; the preflight
contains no `sendMessage`.

```text
channel:  telegram
bot:      @PromisePatchDemoBot (id 8519260202)
chat:     <not echoed>
provider: telegram
result:   reachable; no message was sent
returned_id_matches_requested: YES
chat_type: private
```

The id Telegram returned is **equal to the id asked about** and the chat is **`private`**, both
established by comparison inside the host payload rather than by printing. The id was read from
gitignored operator-local state; **no `getUpdates` call was made**, then or ever.

Then, on the host, through the product's own command and **no manual SQL**:

```text
pp channel bind-demo-customer --chat-id <not echoed>

channel:  telegram
customer: cus-tomas
bot:      @PromisePatchDemoBot (id 8519260202)
chat:     private (id not echoed)
action:   bound
audit:    seq 187
result:   bound; no message was sent
```

**Exactly one row moved.** Read immediately before and immediately after, the six customers are:

| customer | before | after |
|---|---|---|
| `cus-tomas` | `telegram`, address length 4 | `telegram`, address length 10 |
| `cus-ahmed`, `cus-cafe-marlow`, `cus-lena`, `cus-okafor-reyes`, `cus-priya` | `telegram`, length 4 | **unchanged, length 4** |

The bound length equals the length of the id held in operator-local state. Addresses are compared
by length rather than by value throughout this section, for the reason `channel_binding` gives: a
chat id identifies a real person and belongs only in the row it addresses.

### 10.5 One proposal, through the ordinary workflow

Counts immediately before: outbox **0**, `approval_requests` **0**, `approval_decisions` **0**,
`plan_approvals` **0**, `inbound_replies` **0**, one case at `PLANNED`.

One confirmation, on the operator console -- one of the two channels where this system takes a
human's word for a plan -- quoting the plan identity `case-status` printed:

```text
pp confirm-plan --case a3810ae5-... --worker maya --plan 0fbe85e5db31...025649

plan.approval.recorded      channel=OPERATOR_CONSOLE worker=maya
recovery.plan.confirmed     applying=1 awaiting_approval=1 escalated=2
state:     EXECUTING
```

**`awaiting approval: 1`** is the whole point: one customer, `pr-b`, and nobody else. The two
escalations are `pr-c` and `pr-d` going to the owner, and the one application is `pr-a`'s
pre-approved substitution, which asks nobody. **Telegram's `sendMessage` was never called by
hand** -- the durable worker dispatched it on its own cycle.

### 10.6 The delivery, proved

```text
POST https://api.telegram.org/bot***/sendMessage  HTTP/1.1 200 OK
worker.telegram.sent  status=DELIVERED  provider_ref=telegram:<redacted>:3  attempt_error=null
worker.effect.dispatched  kind=MESSAGE_SEND  attempt=1  status=DELIVERED
```

| claim | evidence |
|---|---|
| exactly one approval request | `approval_requests` 1, `pr-b`, state `SENT` |
| exactly one customer message | `MESSAGE_SEND` outbox rows **1** |
| Telegram accepted it | `HTTP/1.1 200 OK`; non-200 responses from `api.telegram.org`: **0** |
| `provider_ref` persisted | `telegram:<redacted>:3` on the row |
| the outbox settled | `MESSAGE_SEND` state `DELIVERED` |
| no duplicate, no retry | `sendMessage` calls in the worker's **entire** log history: **1**; `worker.telegram.sent` events: **1**; `attempts` summed across `MESSAGE_SEND`: **1**; distinct `idempotency_key` count equal to row count |
| the case moved as it should | `PLANNED` to `EXECUTING` to `WAITING` |

The second outbox row is `ORDER_AMEND`, `DELIVERED`, `attempts 1`, `provider_ref
amd-40e195e65abe`: `pr-a`'s pre-approved substitution reaching the External Order System. It is
an order amendment, not a message, and it reaches no person. Two outbox rows and **one** message
is the canonical partition behaving exactly as section 10.3 predicts.

**Unrelated state is unchanged.** Five of the six customers still carry four-character
placeholders, so no dispatch could have reached a second person. There is one case on the host
and it is the provisioned one. `plan_approvals` is 1 -- the confirmation that was spent -- and
`approval_decisions` is **0**.

**The operator confirmed on the device that exactly one PromisePatch message arrived.** Nothing
in this session opened the approval link, clicked it, approved or declined.

### 10.7 A spoken `YES` on Telegram reached nothing, and that is now measured

The operator replied `YES` in the Telegram chat after receiving the message. This is the first
time that has ever been possible, and it is worth recording because it tests an invariant that
until now was only asserted from the absence of code.

| | value after the reply |
|---|---|
| `inbound_replies` | **0** |
| `approval_decisions` | **0** |
| `approval_requests` | **1, `pr-b`, still `SENT`** |
| case state | **`WAITING`**, unchanged |
| `getUpdates` calls in the worker's entire log history | **0** |

**The reply reached nothing at all.** `customer-message-transport.md` says Telegram inbound stays
unbuilt deliberately, because a second route for the word `YES` would be a second consent parser;
the customer answers on the web, through the signed possession link the outbound message carries.
That is now an observation rather than a design statement: a literal `YES` typed into the bot's
own chat did not become consent, did not create an inbound row, and did not move the approval
request off `SENT`. The consent protocol is exactly where it was, still waiting on the link.

### 10.8 What was not done, and two honest limitations

- **Nothing was approved or declined.** The approval link was not opened, clicked or followed by
  this session, and `approval_decisions` is `0`.
- **No second proposal was triggered**, and no message was sent by hand at any point.
- **No AWS resource was created, updated or deleted.** No SSM parameter was written, no release
  was run, no change set was built, no stack was updated, no host was replaced or rebooted, and
  no IAM policy was read, broadened or written. Every host command went through
  `ssm:StartSession`.
- **The four previously deployed cases are gone**, with their tracks, statements, approval
  request, outbox rows, orders and promises. Their history remains readable in `audit_events` and
  `domain_events`, which only grew. This was authorised explicitly before step 1 ran.
- **The worker logs the chat id in plaintext.** `worker.telegram.sent` carries `chat_id` as a
  structured field and `provider_ref` embeds it, and the deployed compose uses the `awslogs`
  driver, so a real person's Telegram identifier now sits in CloudWatch Logs. Nothing in this
  repository records it -- `channel_binding` is careful to keep it out of both ledgers, and this
  document redacts it -- but the log line is a gap in that care and is recorded here rather than
  quietly fixed, because changing an observability field is a code change and this work was
  scoped to docs.
- **The host's `converge.sh` is still the stale one**, unchanged at `45f5145e...188a`, so
  `env/channel.env` remains hand-written rather than derived. Section 8.7's consequence is
  unchanged: a rotated bot token would not be picked up until the migration is re-run or the host
  is replaced.
- **The world decays again from its new anchor.** This seed is good for the rest of the Tunis
  bakery day of 2026-09-22 and no longer. `demo-world-roll.md`'s non-destructive roll is now
  **refused again on this host** -- one outbox row, one approval request -- so the next repair is
  the destructive one again, and it will erase this binding along with everything else.

### 10.9 The next step

The approval request is open and waiting, and the only thing that can answer it is the customer
opening the signed link the message carries and choosing on the web. Nobody has done so.

1. **On the phone, open the link in the delivered message** and either approve the single option
   -- `rv-raspberry-rose-2 -> rv-raspberry-rose-3` -- or decline it. The window closes
   `2026-09-22T21:47:06Z`; after that the request expires and the promise falls to the owner.
2. The worker then executes the recovery the decision authorises, `pr-b`'s track settles, and the
   case leaves `WAITING`. `pp case-status --case a3810ae5-...` on the host is how to watch it.
3. Nothing else needs doing first. The transport, the destination and the world are all in place.

## 11. The customer answered on the web, and the recovery it authorised was applied

Date: 2026-09-22, after section 10 and in a separate session. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything was
read and unchanged throughout.

**A real customer opened the signed link in the message section 10 delivered, chose APPROVE on
the web page, and PromisePatch revalidated that consent against current truth before applying
it.** That closes section 10.9 and completes the first real customer-authority loop this
repository has ever run end to end. No second proposal was made, no second message was sent, and
`sendMessage` has still been called exactly once in this deployment's history.

Sections 3 and 6 through 10 are left exactly as written. This section records the later truth
beside them.

### 11.1 Entry, and the state measured before the customer acted

| | value |
|---|---|
| HEAD / tree / `origin/main` | `b2e813fccba1`, tracked tree clean, equal to `origin/main` |
| Stack status / last updated / change sets | `UPDATE_COMPLETE` / `2026-09-21T19:28:32Z` / none |
| `ImageTag` / `HostAmiId` / `SeedDemoFixtureOnFirstBoot` | `aeb46d2bdb7f` / `ami-0fa4996c14e7d501e` / `false` |
| Host instance / AMI / launch | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z` |
| Host kernel `boot_id` / uptime since | `eb889c14-2aa2-462a-a0c6-e73ff8886014` / `2026-09-21 19:30:20` |
| RDS | `promisepatch-prod`, `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, private, encrypted |
| `/healthz` image / process `boot_id` | `aeb46d2bdb7f` / `b0124ede-182c-4210-9604-74e4d69d6291` |
| Containers | five running; `RestartCount` **0** on `api`, `worker`, `caddy`, `mcp` |
| Deployed runtime provider | `pp channel check` **inside `worker`**: `provider: telegram` |
| Forged approval `GET` | `404 LINK_NOT_FOUND` |
| Case | `a3810ae5-6337-559b-8b97-47023bc0094c`, **`WAITING`** |
| Approval request | `e9832010-...` (`OPT-4D3FFD`), **`SENT`**, deadline `2026-09-22T21:47:06.452592Z`, replies 0 |
| `approval_decisions` / `inbound_replies` | **0 / 0** |
| `approval_requests` / `plan_approvals` | 1 / 1 |
| Outbox | 2 rows: `MESSAGE_SEND` `DELIVERED` attempts 1, `ORDER_AMEND` `DELIVERED` attempts 1 |
| `sendMessage` / `getUpdates` calls in the worker's entire log history | **1 / 0** |
| `audit_events` / `domain_events` | 198 / 261 |
| Fixture | `hollow-oak`, anchor `2026-09-22T16:47:06.452592Z`, digest `3a33a523...59e89d` |
| Customers | 6; only `cus-tomas` bound (address length 10), the other five 4-character placeholders |

**The request was live, and that was established rather than assumed.** The *database's* clock
read `2026-09-22T17:36:12Z` against a deadline of `21:47:06Z`. The API answered a forged token
`404` rather than `503`, so it holds the link secret; neither `api` nor `worker` had restarted
since the message was minted, so the secret that verifies is the secret that signed.

The revalidation inputs the request captured at send time, recorded before they could be
compared: order version **1**, recipe `rv-raspberry-rose-2`, constraint hash `3841dc04...5a87c`,
track fingerprint `b8a8096a...8523a`. Live at that moment: `EXT-B` version **1** `ACCEPTED`,
`ol-b` pinned to `rv-raspberry-rose-2`, `task-ol-b` `SCHEDULED` starting `22:47:06Z`.

### 11.2 The customer's decision, proved from system state

The operator opened the link in the delivered message on the phone and chose **APPROVE**.
Nothing in this session opened, clicked or followed that link, and no link was minted here.

| claim | evidence |
|---|---|
| exactly one decision exists | `approval_decisions` **1** |
| it belongs to the existing request | `request_id` `e9832010-58df-576b-bcb6-708106ade78c`, the `SENT` row from section 10 |
| the decision is an approval | `decision` **`APPROVE`** |
| it came from the literal parser | `parser` **`LITERAL`**, `raw_text` `yes` |
| possession, not identity, carried it | `provider_message_id` `link:69c047c7-...`, the id `approvals.link_message_id` derives from *request and channel* -- so a second press of either button proposes an id the database already holds and writes nothing |
| the sender matched the channel asked | `sender_identity` equals the request's `customer_channel`, server-derived from the link's signature and never from a request body |
| the request moved off `SENT` | state **`ANSWERED`**, `decided = true`, `replies 1` |
| Telegram inbound played no part | `getUpdates` calls **0**; the reply arrived as an `inbox_events` row of source `customer-reply` with `transport: customer-link` |
| no plan authority was spent | `plan_approvals` **1**, unchanged -- the customer's yes spent no worker approval, which is the separation of ADR-0018 holding |

The signature, possession and expiry checks were honoured by construction: `_possession` refuses
a token that does not verify before any handler runs, and an unverifiable one is `404` whatever
the reason -- forged, malformed or never-existed alike.

### 11.3 The worker revalidated against current truth, and that is the load-bearing evidence

`REVALIDATE_RECOVERY` ran on the durable worker and wrote **ten** `REVALIDATION_CHECK` audit
rows, each carrying the two values it compared. Every row's `authority` is `NONE` and its actor
is `SYSTEM`: the checks are evidence, and evidence authorises nothing.

| # | check | expected | actual | |
|---|---|---|---|---|
| 1 | track and case are waiting | `track=WAITING_FOR_CUSTOMER case=WAITING` | same | pass |
| 2 | order state and version unchanged | `ACCEPTED or AMENDED @ v1` | `ACCEPTED @ v1` | pass |
| 3 | pinned recipe version unchanged | `rv-raspberry-rose-2` | `rv-raspberry-rose-2` | pass |
| 4 | constraint snapshot unchanged | `3841dc04...5a87c` | `3841dc04...5a87c` | pass |
| 5 | substitute still available | `>= 2.200` | `3.200` | pass |
| 6 | production task not started and still ahead | `SCHEDULED or HELD by a3810ae5-... and start > 2026-09-22T17:40:10.652625Z` | `SCHEDULED and start 2026-09-22T22:47:06.452592Z` | pass |
| 7 | approval deadline not passed | `now <= 2026-09-22T21:47:06.452592Z` | `2026-09-22T17:40:10.652625Z` | pass |
| 8 | sender is the order's approval channel | the request's channel | the same, `via` the same | pass |
| 9 | decision came from the literal parser | `LITERAL` | `LITERAL` | pass |
| 10 | one unspent decision, bound to this plan | one decision for `e9832010-...` on track `f8c0e808-...` option `4d3ffd00-...` | `1 decision(s)` for the same three | pass |

Outcome **`PROCEED`**.

**This is a re-read, not a replay of the plan.** `_revalidate` calls
`analysis.fresh_snapshot(connection)` -- never the snapshot planning or the approval used -- and
checks 2, 3, 4 and 5 are that fresh snapshot being compared against what the request captured
when it was sent. Check 6 reads the live production task and compares its start to the current
clock; check 7 compares the deadline to the *database's* clock rather than to whether a timer
has run. The snapshot instant, `17:40:10.652625Z`, is later than the decision instant,
`17:40:10.544403Z`, which is what says the world was read after the customer spoke and not
before.

**No drift was manufactured.** Nothing was amended, re-pinned, consumed or started in order to
provoke a refusal; the world was left exactly as the customer found it, and it happened still to
be true. The refusal paths therefore remain unexercised live, and that is stated rather than
implied.

### 11.4 The recovery, applied

`REVALIDATE_RECOVERY` enqueued `APPLY_RECOVERY` -- the same crash-safe saga an automatic track
uses, under the same stable idempotency key. Only the authorisation differed.

```text
effect ORDER_AMEND DELIVERED (attempt 1, ref amd-e735e9398046)
  key pp:amend:f8c0e808-...:4d3ffd00-...:1
  provider reported: external_order_id EXT-B, external_line_id ol-b,
    item_id rv-raspberry-rose-3, previous_version 1, external_version 2,
    state AMENDED, replayed False
```

| claim | evidence |
|---|---|
| only the authorised substitution executed | one new effect, keyed to pr-b's track and to option `4d3ffd00-...` = `OPT-4D3FFD`, the option the request named |
| the durable effect settled | `ORDER_AMEND` `DELIVERED`, **attempts 1** |
| the provider reference persisted | `amd-e735e9398046`, and `replayed False` |
| pr-b settled | track `WAITING_FOR_CUSTOMER` to **`RECOVERED`**; `ol-b` `rv-raspberry-rose-2` to **`rv-raspberry-rose-3`**; `EXT-B` `ACCEPTED @ v1` to **`AMENDED @ v2`** |
| the case left `WAITING` | `WAITING` to **`RESOLVED`** |
| no duplicate effect | 3 outbox rows, **3 distinct idempotency keys** |
| no second message | `MESSAGE_SEND` rows **1**; `sendMessage` calls in the worker's entire log history **1** |

The step ledger records the whole path: `RECEIVE_CUSTOMER_REPLY` `DONE`, `REVALIDATE_RECOVERY`
`DONE`, `APPLY_RECOVERY` `DONE` (now 2, one per recovered track), `FINALIZE_RECOVERY` `DONE`
(2), `RECONCILE_CASE` `SKIPPED` -- skipped because the transition that settled the last
non-terminal track had already finished the case.

### 11.5 Unrelated state, unchanged

| promise | before | after |
|---|---|---|
| `pr-a` / `EXT-A` | `RECOVERED`, `AMENDED @ v2`, `amd-40e195e65abe` | **identical** |
| `pr-c` / `EXT-C` | `ESCALATED` to the owner, `ACCEPTED @ v1` | **identical** |
| `pr-d` / `EXT-D` | `ESCALATED` to the owner, `ACCEPTED @ v1` | **identical** |
| `pr-e` / `EXT-E` | `UNAFFECTED`, `ACCEPTED @ v1` | **identical** |
| `pr-f` / `EXT-F` | `UNAFFECTED`, `ACCEPTED @ v1` | **identical** |

The five unrelated tracks and their five orders hash to
`512375621d0065fbff83be4b5c3636bbc08a501f5052d8af668d52dee6ed72c0` before and after -- computed
over the same rows on both sides, so the equality is a comparison rather than a restatement.
Five of the six customers still carry four-character placeholders, so no dispatch could have
reached a second person. `plan_approvals` is still 1 and `approval_requests` is still 1.

Both ledgers only grew: `audit_events` 198 to 218, `domain_events` 261 to 277.

### 11.6 The deployment, unmoved

Deployment smoke: **12/12 passed, 0 failed, 0 skipped**, including `deployed-image`, which still
reports `aeb46d2bdb7f`, and the five refusal checks.

| | before | after |
|---|---|---|
| Stack status / last updated / change sets | `UPDATE_COMPLETE` / `2026-09-21T19:28:32Z` / none | **all unchanged** |
| Host instance / AMI / launch time | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z` | **all unchanged** |
| Host kernel `boot_id` / uptime since | `eb889c14-...` / `2026-09-21 19:30:20` | **identical -- no reboot** |
| `/healthz` process `boot_id` | `b0124ede-...` | **identical -- `api` never restarted** |
| RDS `DbiResourceId` / status / access | `db-U2JWQBTINX6W6GAB56EOTHOCSM` / `available` / private, encrypted | unchanged |
| Container `RestartCount` | 0 on `api`, `worker`, `caddy`, `mcp` | **0 on all four** |
| Fixture name / anchor / digest | `hollow-oak` / `...16:47:06.452592Z` / `3a33a523...59e89d` | **all unchanged** |

**No AWS resource was created, updated or deleted.** No SSM parameter was written, no release was
run, no change set was built, no stack was updated, no host was replaced or rebooted, and no IAM
policy was broadened. Every host command went through `ssm:StartSession` with
`AWS-StartNonInteractiveCommand`, and every one of them was a read. `ssm:SendCommand` is still
not granted and was not used.

### 11.7 What was not done, and the honest limitations

- **No second proposal was made and no second message was sent.** `sendMessage` has been called
  exactly once in this deployment's history, and that call was section 10's.
- **No refusal path was exercised live.** The world did not move between the message and the
  answer, so `STALE`, `EXPIRED`, `UNAUTHORIZED` and `NOOP` remain proved only by their tests.
  Manufacturing drift to demonstrate one was out of scope, and inventing a stale world in order
  to watch a refusal would have been staging rather than measuring.
- **The chat id reaches the operator read surface, not only the logs.** Section 10.8 recorded
  `worker.telegram.sent` carrying `chat_id` into CloudWatch. `pp case-status` prints the same
  identifier inside the approval request's `provider_ref` (`telegram:<id>:<msg>`), and the
  decision and reply rows carry it as `sender_identity`. So reading a case out loud discloses a
  real person's Telegram identifier. It is masked everywhere in this document and was masked in
  every read after the first. It is recorded rather than fixed, because this work was scoped to
  docs and the defect blocks no correctness.
- **The host's `converge.sh` is still the stale one**, unchanged, so `env/channel.env` remains
  hand-written rather than derived. Section 8.7's consequence is unchanged.
- **The world still decays from its 2026-09-22 anchor**, and the non-destructive roll is still
  refused on this host. The next repair is the destructive one and will erase the binding.

### 11.8 What this closes

Section 10.9 is answered in full: the link was opened, the single option was approved, the worker
executed the recovery that decision authorised, pr-b settled, and the case left `WAITING`. The
loop from a spoken physical exception, through a worker's plan confirmation, to a real customer's
web decision, through ten revalidation checks, to an amendment on the external order system, has
now run once end to end against a real phone and a real deployment.

## 12. The two defects that loop exposed, closed and deployed

Date: 2026-09-22, after section 11 and in a separate session. Recorded here as later truth;
sections 3 and 6 through 11 stand exactly as written.

The loop above ran against a message that told the customer to do something impossible, and a
system that read their Telegram chat id out on five surfaces. Both are now closed in the
deployed build, at `4cfb74de7cc2`, with smoke `12/12` and every count in section 11.5 unchanged.

- **Section 10.7's measurement became a product change.** The `YES` that reached nothing did so
  because `CONSENT_INSTRUCTION` invited it. Per
  [ADR-0021](adr/0021-a-customer-answers-on-the-web-and-their-address-stays-in-the-database.md)
  the message now names the signed link, which is the only door that opens. Telegram inbound is
  still unbuilt, and this makes it less likely to be wanted rather than more.
- **Sections 10.8 and 11.7 understated the disclosure.** They named the worker log and
  `pp case-status`. An audit found three more, two of them public: the `GET /api/cases/{id}`
  response and the deployed SPA's evidence drawer both rendered `provider_ref` verbatim, so
  anyone holding a case id could read a real customer's Telegram identifier off
  `https://184.194.40.87.sslip.io`. All five are masked at the boundary; every durable row still
  holds the address whole.
- **Section 8.7's remaining limitation is closed.** The host's `converge.sh` is now the committed
  one, installed through `ssm:StartSession` without replacing the host, reseeding anything,
  touching IAM or passing a secret through an operator's shell. The release's own reboot
  exercised it: `env/channel.env` was regenerated from SSM by the instance role fourteen seconds
  after boot, byte-identical to the hand-written file it replaced. A rotated bot token would now
  be picked up at the next boot.

Two limitations from section 11.7 are **not** closed and are restated rather than quietly
dropped: no refusal path has been exercised live, and CloudWatch still holds the log lines
written before the redaction — redacting an emitter does not rewrite history.

The full record, including why `deploy.sh stack` refused this release and what carried it
instead, is in [`customer-disclosure-hardening.md`](customer-disclosure-hardening.md).
