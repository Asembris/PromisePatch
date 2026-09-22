# The deployed customer channel, and why it could not be switched on

Date: 2026-09-21
Status: **the release is performed and verified. The Telegram delivery it was for did not
happen, and nothing was sent.** A structural blocker was found, is recorded in full in section
3, and the correction in section 4 is **committed and deliberately not applied**. No message has
reached anybody, no chat id has been bound anywhere, and the deployed customer channel is still
the fake provider.

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
