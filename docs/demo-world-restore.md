# The demo repair becomes one command, and refuses before it destroys

## What this closes

The repair existed and worked. It did not exist as anything a person could run.

[demo-fixture-anchoring.md](demo-fixture-anchoring.md) wrote it down as four operator steps;
[deployed-customer-channel.md](deployed-customer-channel.md) section 10 records those four steps
being taken on the deployed host, with the world nine days stale, and the canonical partition
coming back. [demo-world-roll.md](demo-world-roll.md) explains why the automatic roll cannot do
this job: the roll's four questions are asked of the whole database, unscoped, so the **first**
customer message, reply or approval request pins that world for ever. The destructive repair is
the documented way out of exactly that state, and it is an operator's decision because it costs
every case on the deployment.

Two things made it dangerous, and neither is an individual step.

**The order is load-bearing and lived only in prose.** Step 1 truncates `customers`, so a demo
customer bound to a real chat before it is erased by it — section 9.5 records that as the
ordering fact, discovered by reasoning rather than by losing a binding, and the ordering it
implies is *reseed, then bind, then propose*. An operator who remembers three of the four steps
gets a demo that reaches nobody, and nothing reports an error.

**The External Order System keeps its own store.** A PromisePatch reset does not reach it. Skip
step 2 and the order book still carries every amendment the destroyed cases made, against a
mirror that has just been rebuilt at version 1. Run 1 of the voice measurement was spoiled by
exactly that.

`pp restore-demo-world` is those four steps, sequenced once, with the preconditions asked of rows
before anything is destroyed.

## The command

```bash
pp restore-demo-world --confirm destroy-and-restore
```

```bash
pp restore-demo-world --dry-run
```

**The confirmation is a value, not a flag.** `--confirm` with nothing after it is one keystroke
from `--dry-run`, and what is on the other side of it is a `TRUNCATE` that takes every case,
effect, approval request, reply and session on the deployment. `--dry-run` asks every
precondition, reports the census, and writes nothing at all.

Exit codes distinguish the refusals, because an operator scripting this needs to tell *not the
demo world* from *could not rebind*:

| code | meaning |
|---|---|
| `0` | restored, or inspected under `--dry-run` |
| `1` | not confirmed, or a step failed |
| `2` | this database is not a canonical demo world |
| `3` | a bound destination could not be carried across |

## What it refuses, and when

Every refusal below is raised **before the first destructive statement**. That is a property of
the sequence rather than of the order somebody happened to write two calls in, and it is what
makes a refusal free.

| refused | why |
|---|---|
| the confirmation is absent or does not match | a destructive command should cost a sentence |
| `PP_ALLOW_FIXTURE_RESET` is not true | the existing opt-in still governs; this is a reset with three more steps |
| `PP_DEMO_SESSION_ENABLED` is not true | provisioning is gated on it, so a restore here would leave an empty list |
| no order system is configured | step 2 is not optional, and discovering that after step 1 is too late |
| `fixture_state` holds no fixture, or holds one by another name | a stated variant of the demo world is not the demo world |
| the customer set is not the fixture's own | a missing customer, an extra one — a world this did not create |
| a customer carries a channel kind the fixture does not ship | the same |
| a customer **other than** the canonical one carries a bound address | that binding is somebody else's, and overwriting it would decide on their behalf that it did not matter |
| any outbox row is `PENDING` or `IN_FLIGHT` | an effect a dispatcher is about to send, against a world that is about to stop existing |
| the External Order System does not answer `/healthz` | its order book cannot be reset, so nothing here is reset either |
| a bound destination cannot be re-verified | a reset would erase a destination it could not put back |

A `DELIVERED` or `FAILED` outbox row is **not** a refusal. The repair exists *for* a world that
has been used; those rows are history, the ledgers keep the record of them, and refusing on them
would refuse the only case this command is for.

## The binding, carried rather than stored

The canonical demo customer's destination — the one the seeded case's single `APPROVAL_REQUIRED`
band belongs to — is read out of the `customers` row before the truncate, held in memory for the
length of one call, and written back after provisioning through
`promisepatch.fixtures.channel_binding.bind_demo_customer_channel`: the one binding mechanism
there is. **No second mechanism, no new persistence, no file.**

**It is re-verified first.** The address is confirmed with the provider's own `getMe` / `getChat`
— the two reads `pp channel bind-demo-customer` makes, and no `sendMessage` — *before* the reset
runs, so a destination that cannot be confirmed refuses with the world untouched rather than
leaving one that reaches nobody. What reaches the rebind is a `VerifiedDestination` carrying the
id the provider echoed back, which is the same type invariant a first binding is held to.

**It never leaves the process.** ADR-0021 is why that is worth engineering rather than
remembering: a ten-digit chat id identifies a real person. The address is absent from the
outcome, from the census, from every refusal message — including the one that reports a failed
verification, which repeats only the *type* of the provider's error, never its text — and from
`PreservedBinding.__repr__`, so an unhandled exception between the read and the rebind cannot
publish it into a terminal, a log or a Session Manager transcript either. The command reports
`binding: restored` or `binding: none-held`, and nothing finer.

A structural test asserts there is nowhere for an address to be: no field of `RestoreOutcome` or
`Census` is named for one.

## The order, which is the whole point

1. **Reseed** the operational world at `resolve_demo_anchor(now)` — the anchor an operator
   omitting `--anchor` already gets. No clock is moved by hand.
2. **Reset the External Order System** through its own `POST /admin/reset`. Never a volume:
   `docker compose down -v` would take `caddy-data`, the Let's Encrypt certificate and account
   key with it.
3. **Provision** the canonical case through `provisioning.ensure_demo_case` — the same call the
   worker makes at start, driven by the deployment's own worker wiring, so the case a judge lands
   on is not built by a second wiring nobody deployed.
4. **Rebind** the preserved destination, if one was held.

A second run is **outcome-idempotent**: it destroys the world the first left, reseeds at a fresh
anchor and provisions the same canonical partition again. The case it removes is the case it
opened.

## What it never does

* It confirms no plan.
* It creates no approval request and no approval decision.
* It records no consent and mints no authority. The case it leaves is `PLANNED`: the point at
  which a person has yet to say yes.
* It sends no customer message.
* It touches no volume, no container and no infrastructure.
* It edits no timestamp.
* It weakens nothing. `provisioning._what_would_be_lost` and the world roll are untouched and
  unreachable from here — a world this has just reseeded tells the story by construction, so
  provisioning finds nothing to roll and reports `rolled: false`.

## Where it lives, and why there

`promisepatch.demo_restore` sits between `promisepatch.integrations` and
`promisepatch.provisioning` in the import-linter layering contract, so it **cannot** import an
adapter or a Bot API client. Both of the things it needs from above are injected the way
`provisioning` already takes its `Cycles`: the worker that runs cycles, and the verifier that
confirms a destination. The CLI supplies both.

The order-system admin call is an ordinary HTTP client rather than `OrderSystemClient`, whose
own docstring says *two calls, and nothing else*: a demo reset is not a governed order
operation, and widening the production boundary to carry one would have been the wrong trade.
That client is injectable, which is what lets the backend suite run the real simulator as a
second ASGI application instead of skipping the step-2 assertion wherever nothing is listening
on a socket.

## The local proof

Taken on **2026-09-23**, against the local Docker stack — PostgreSQL, the order simulator, the
API, the MCP server and the frontend — through the real CLI, with
`PP_CUSTOMER_CHANNEL_PROVIDER=fake`, which is what CI, every test and the local stack use.
**No AWS call, no deployment, no Session Manager, and no Telegram request of any kind.**

### Refused, then inspected, then run

```text
pp restore-demo-world                            -> exit 1
this destroys every case, effect and session on this deployment;
pass --confirm destroy-and-restore to say so.

pp restore-demo-world --dry-run                  -> exit 0
action:   inspected
before:   fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0
          approvals=0 replies=0 audit=176825 events=227944 bound=False
binding:  none-held (would be carried across)
result:   nothing was written
```

### The restore

```text
pp restore-demo-world --confirm destroy-and-restore    -> exit 0
action:   restored
before:   ... cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0
          replies=0 audit=176825 events=227944 bound=False
after:    ... cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0 approvals=0
          replies=0 audit=176838 events=227962 bound=False
anchor:   2026-09-23T11:36:47.508174+00:00 (12:36:47+01:00 Africa/Tunis)
digest:   21f64e8bb43f29635692b48c8bd09801823f71594995a41c508490acfc698e48
rows:     160
orders:   6 reset in the external order system
case:     c79425d0-4fef-5a3e-a174-28a66edbfc8f
state:    PLANNED
binding:  none-held
ledgers:  grew only
result:   restored; no plan was confirmed and no message was sent
```

**The ledgers only grew**: `audit_events` 176 825 → 176 838, `domain_events` 227 944 → 227 962.
Neither is in `resettable_tables()` and both are refused truncation by trigger regardless.

**Every authority counter is zero after**: `approval_requests` 0, `approval_decisions` 0,
`plan_approvals` 0, `inbound_replies` 0, and the outbox is empty — nothing was queued, so nothing
could have been sent.

### The canonical partition, from `pp case-status`

| promise | order | band | option |
|---|---|---|---|
| `pr-a` | `EXT-A` Priya Nair | `AUTO_RECOVERABLE` via `R-PREAPPROVED (PREAPPROVAL_COVERS)` | `rv-raspberry-almond-3 -> rv-raspberry-almond-4` (no approval) |
| `pr-b` | `EXT-B` Tomas Lindqvist | **`APPROVAL_REQUIRED`** via `R-VISIBLE-ASK (VISIBLE_CHANGE_ASK)` | `rv-raspberry-rose-2 -> rv-raspberry-rose-3` (**approval required**), window closes `2026-09-23T16:36:47Z` — **exactly one** |
| `pr-c` | `EXT-C` Okafor-Reyes | `BLOCKED` via `R-NOSUB (NOSUB_CONSTRAINT)` | none — owner |
| `pr-d` | `EXT-D` Lena Fischer | `BLOCKED` via `R-NOSUB (NO_PREAUTHORED_VARIANT)` | none — owner |
| `pr-e` | `EXT-E` Ahmed Bouazizi | `UNAFFECTED` via `R-UNREACH (NOT_REACHABLE)` | none |
| `pr-f` | `EXT-F` Cafe Marlow | `UNAFFECTED` via `R-UNREACH (NOT_REACHABLE)` | none |

### Local health, after

`api` and `mcp` restarted and healthy; `GET /readyz` reports `ready`, migrations at
`0009_human_plan_approval`, and the fixture it names is the one the restore wrote —
`hollow-oak`, anchor `2026-09-23T11:36:47.508174Z`, digest `21f64e8b…698e48`. The order
simulator reports `seeded: true`.

### The suite

Run sequentially, no xdist, against the local PostgreSQL:

| suite | result |
|---|---|
| `test_demo_restore.py` (guards, refusals, topology) | 34 passed |
| `test_demo_restore_command.py` (end to end, CLI surface) | 22 passed |
| the related set — the two above plus `test_database_safety`, `test_database_protections`, `test_demo_world_roll`, `test_demo_case_provisioning`, `test_channel_binding`, `test_channel_check`, `test_demo_anchor`, `test_fixture_round_trip`, `test_cli` | **316 passed** |
| `ruff check .` / `ruff format --check .` | clean, 577 files |
| `mypy packages/promise-graph packages/order-contract apps/backend` | clean, 291 files |
| `lint-imports` | 30 contracts kept, 0 broken |

**`test_demo_world_roll.py` is unchanged and green.** Nothing here loosened a guard it asserts.

Every end-to-end test restores from a world the roll can never move again — a case opened, a
plan confirmed, an approval asked for, effects dispatched — arranged by driving the ordinary
path rather than by writing rows, because a hand-built arrangement would prove the command works
on states the product cannot reach. The bands are read back through `GET /api/cases/{id}` as the
observer session the judge entry mints: the screen, not the row.

**One safety test was strengthened.** `test_database_safety.py`'s scan for destructive suite
modules knew one function name. `restore_demo_world` truncates through three more steps and
resolves its own migration connection from the settings it is handed, so a module driving it is
exactly as destructive as one calling the reset directly and would have been invisible. Both
names are scanned now.

## What this does not prove

* **No deployed host was touched.** Nothing here ran against AWS, and the command has never been
  run on the deployed stack.
* **The binding-restore path has never met Telegram.** It is proved against a stub verifier in
  tests; the real `getMe` / `getChat` pair has never been driven through this command. The local
  stack runs the fake provider and holds no real chat id, so the path this exercised is
  `binding: none-held`.
* **No message was sent, so nothing here says a restored binding can still be reached.** That is
  a claim only a deployed run can make.
* The deployed image does not carry this command. It arrives the way any release does.

## What a deployed proof must show

1. The command reaches the deployed host in an ordinary release, and
   `pp restore-demo-world --dry-run` inside the deployed container reports the live census
   without writing anything.
2. A **bound** run: the deployed demo customer is bound to the real chat, the restore carries it
   across, and `pp channel check` afterwards still reaches that chat — with the chat id appearing
   in no output, no log line and no Session Manager transcript.
3. `binding: restored`, and exactly one `customers` row moved.
4. The ledgers grew and nothing else did: `audit_events` and `domain_events` up, every authority
   counter back to `0`, the outbox empty.
5. The canonical partition, read from the deployed `pp case-status` and from the deployed SPA.
6. The infrastructure unmoved: no reboot, no host replacement, no stack update, no volume
   removed, the RDS instance and the certificate untouched.
7. That the restore sent nothing — zero `sendMessage` lines in the deployed worker log across the
   whole run.

---

## The deployed proof

Date: **2026-09-23**. Identity
`arn:aws:sts::265243686715:assumed-role/PromisePatchDeveloperRole/PromisePatchLocalDevelopment`,
account `265243686715`, region `us-east-1`, profile `promisepatch`, verified before anything
mutated and unchanged throughout.

**`pp restore-demo-world --confirm destroy-and-restore` was run once on the deployed host, it
carried the real Telegram binding across, and it sent nothing.** Every item of *What a deployed
proof must show* above is now answered. The sections before this one are left exactly as written;
this records the later truth beside them.

It cost the one deployed case — the `RESOLVED` case of
[deployed-customer-channel.md](deployed-customer-channel.md) section 11 — which the project owner
authorised losing.

### 1. Entry

| | value |
|---|---|
| HEAD / tree / `origin/main` | `931a296decad`, tracked tree clean, equal to `origin/main` |
| CI on that commit | 13 `success`, 1 `failure`: `effect sets (expected red until 16/16)` |
| Stack / status / last updated | `promisepatch-prod`, `UPDATE_COMPLETE`, `2026-09-22T19:32:21Z`, no change sets |
| `ImageTag` / SSM `image-tag` / `/healthz` | all `4cfb74de7cc2` |
| Host / AMI / launch / volume | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z` / `vol-0f330aaa62e637ef6` |
| Host kernel `boot_id` / `uptime -s` | `79430d36-ba6e-4f08-bfbd-bc2c73f82d69` / `2026-09-22 19:44:22` |
| RDS | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, private, encrypted, created `2026-09-11T11:19:51Z` |
| Migration | `0009_human_plan_approval`, at head |
| Fixture | `hollow-oak`, anchor `2026-09-22T16:47:06.452592Z`, digest `3a33a523...59e89d` |
| Cases | 1 — `a3810ae5-...`, `RESOLVED` |
| Outbox | 3 rows, all `DELIVERED`; **0 `PENDING`, 0 `IN_FLIGHT`** |
| requests / decisions / approvals / replies | 1 / 1 / 1 / 1 |
| `audit_events` / `domain_events` | 219 / 279 |
| Customers | 6 `telegram`; `cus-tomas` address length 10 (**bound**), the other five length 4 |
| Deployed runtime provider | `pp channel check` inside `worker`: `provider: telegram` |

### 2. The release, and the path that is still closed

**`deploy.sh stack` refused this release, live**, which is section 10.1 of
[non-destructive-release.md](non-destructive-release.md) happening rather than being predicted:

```text
=== stack (application release)
  release 931a296decad, host image ami-0fa4996c14e7d501e (unchanged), seed false
  preserving 10 infrastructure parameters as the stack declares them
error: this release would replace or remove: ElasticIpAssociation  Host.
```

The change set was deleted unexecuted; the stack stayed `UPDATE_COMPLETE` at
`2026-09-22T19:32:21Z` with zero change sets, and the host kept serving `4cfb74de7cc2`. **That
refusal is correct and was not relaxed.** The deployed template was read back and holds **zero**
occurrences of `channel.env`, which is why its `Host.UserData` differs from this checkout's.

Because `stage_rollout` calls `require_image_declarations_agree` and `stage_smoke` dies when the
stack and SSM disagree, the ordinary path is closed end to end — so HEAD was carried the way
`4cfb74de7cc2` was, **with the project owner's explicit authorisation**: `images` then `config`
then a parameter-only change set against the **previously deployed** template, then `rollout` and
`smoke`.

In that deployed template `ImageTag` is referenced by **no resource** — only by the
`DeclaredImageTag` output — and the change set was required to prove it before executing:

```text
Status: CREATE_COMPLETE   ExecutionStatus: AVAILABLE   ChangeCount: 0   Changes: []
```

**This remains a documented one-off and not a release path.** The gap of
[non-destructive-release.md](non-destructive-release.md) section 10.1 is unchanged: the stack's
recorded template can still only be moved by replacing the host.

After it: `/healthz` `image` `931a296decad`, all five services on `931a296decad`, migration still
`0009_human_plan_approval`, **the fixture not reseeded** (anchor still `2026-09-22T16:47:06Z`),
provider still `telegram`, instance id / AMI / launch time / EBS volume unchanged, RDS unchanged.
New host `boot_id` `8f030425-e01f-4d26-9f85-fce49cb82676`, `uptime -s` `2026-09-23 12:54:41` —
the ordinary rollout reboot.

### 3. Deployment smoke: 9/12 from the operator machine, and why the three are not the deployment

Smoke reported **9 passed, 3 failed** — `mcp-requires-bearer`, `origin-refused`, `host-refused`,
each `ReadTimeout` — identically before and after the restore. **The deployment answers all three
correctly.** Three independent measurements say so:

| measurement | result |
|---|---|
| Caddy's own access log | `401` in `0.0025 s` (12-byte body), `403` in `0.0042 s` (21-byte body) |
| `curl` from the operator machine | `401`, `403`, `421` in ~`0.58 s` each — with curl exit `56`, a **receive** failure |
| `curl` **on the host**, `--resolve` to local Caddy | `401`, `403`, `421` in ~`0.02 s`, and the 401 body arrives whole |

The 19- and 42-second gaps between Caddy's log entries are exactly the client's 20-second read
timeouts. The three checks are the ones expecting a **small non-2xx** body, and this operator
machine runs a TLS-intercepting antivirus proxy — the same one `AWS_CA_BUNDLE` exists for here.
So the failures are a property of the path between this machine and the deployment, not of the
deployment. **This is recorded rather than worked around, and smoke is not claimed as 12/12.**

### 4. A finding: no deployed container can run the command as shipped

The first `--confirm destroy-and-restore` **refused, and destroyed nothing**:

```text
EXIT=1
PP_DEMO_WORKER_PASSWORD is not configured; set it before seeding the demo logins.
```

`require_demo_worker_password()` is the **first statement of `_reseed`**, before the engine is
built and long before `reset_demo_state` truncates — so this is the command failing closed, and
the census taken immediately afterwards was identical in every field to the one before it.

The cause is a real gap between what the command needs and how the deployment is provisioned:

| env file | services | holds |
|---|---|---|
| `env/migrate.env` | `migrate`, `seed` | `PP_MIGRATION_DATABASE_URL`, `PP_ALLOW_FIXTURE_RESET`, `PP_DEMO_WORKER_PASSWORD`, `PP_DEMO_OWNER_PASSWORD` |
| `env/api.env` + `env/channel.env` | `api`, `worker` | `PP_DATABASE_URL`, `PP_ORDER_SYSTEM_BASE_URL`, `PP_DEMO_SESSION_ENABLED`, the channel |

`restore_demo_world` needs the **union**, and **no deployed container holds it**. The run was
taken in `worker` — the deployment's own wiring, which is what step 3 requires — with the missing
settings supplied on the host from `env/migrate.env`, read there so no credential entered the
operator's shell or the Session Manager transcript. `PP_ALLOW_FIXTURE_RESET` was named
deliberately, which is the opt-in behaving as designed rather than a weakened guard.

**This is a defect recorded, not fixed.** Closing it is a change to the deployment definition and
belongs to whoever opens that gate.

### 5. The dry run

```text
pp restore-demo-world --dry-run                              -> exit 0
action:   inspected
before:   fixture=hollow-oak cases=1 live=0 outbox=3 unsettled=0 requests=1 decisions=1
          approvals=1 replies=1 audit=219 events=279 bound=True
binding:  restored (would be carried across)
result:   nothing was written
```

Its census matches an independent SQL census of the same database in every field. `binding:
restored` here is not a guess: `_reverified` runs **before** the dry run returns, so a live
`getMe` and `getChat` had already confirmed the bound destination. Re-read afterwards, the anchor,
the digest, the case, every counter and every customer were unchanged — **nothing was written.**

Run first without the opt-in, the deployed worker answered
`fixture resets are disabled; set PP_ALLOW_FIXTURE_RESET=true to enable one.`

### 6. The restore

```text
pp restore-demo-world --confirm destroy-and-restore          -> exit 0
action:   restored
before:   fixture=hollow-oak cases=1 live=0 outbox=3 unsettled=0 requests=1 decisions=1
          approvals=1 replies=1 audit=219 events=279 bound=True
after:    fixture=hollow-oak cases=1 live=1 outbox=0 unsettled=0 requests=0 decisions=0
          approvals=0 replies=0 audit=233 events=298 bound=True
anchor:   2026-09-23T13:06:37.034903+00:00
local:    2026-09-23T14:06:37.034903+01:00 Africa/Tunis
digest:   44dbd7666b0d7c5f6ae5c28f41afb61a566957e982bf603899be0c66e8ccdc41
rows:     160
orders:   6 reset in the external order system
case:     5b825f1b-3adb-5c53-bc68-2d5d34a43af0
state:    PLANNED
binding:  restored
ledgers:  grew only
result:   restored; no plan was confirmed and no message was sent
```

The structured log records `cases_destroyed=1`, `provisioning=OPENED`, `rolled=False` and
`demo customer channel bound ... audit_seq=233 ... customer_id=cus-tomas` — no address.

**Verified independently, by SQL against the same database:**

* Fixture `hollow-oak` at `2026-09-23T13:06:37.034903Z`, digest `44dbd766...ccdc41` — **a fresh
  current anchor**, chosen by `resolve_demo_anchor` with `--anchor` omitted. Tunis local time was
  14:06, inside the `[01:00, 23:00)` window, so `now` was returned untouched and no clock moved.
* **One** case, `5b825f1b-...`, `PLANNED`.
* **The ledgers only grew**: `audit_events` 219 to 233, `domain_events` 279 to 298. `min(seq)` is
  `1` and `max(seq)` is `233` over 233 rows — contiguous from the beginning, so neither ledger was
  truncated or restarted.
* Outbox **0**. `approval_requests` **0**, `approval_decisions` **0**, `plan_approvals` **0**,
  `inbound_replies` **0**.
* Customers: **exactly one** bound — `cus-tomas`, address length 10 — and the other five back at
  the fixture's own four-character placeholders.
* The External Order System answers `seeded: true`, and every mirror in the new case reads
  **external version 1**, which is step 2 having reached its own store.

### 7. The binding, carried across and still reaching the same private chat

Proved through the product's own verifier — `promisepatch.cli._verify_destination`, which is what
the restore itself calls and what `pp channel check --chat-id` runs — executed **inside the
deployed `worker`**, the process that would send. The address was read from its own row, used,
and never printed: only booleans left the process.

```text
stored_address_length=10
verifier_success=True
returned_id_matches_stored=True
chat_type=private
chat_type_is_private=True
bot_username=PromisePatchDemoBot
messages_sent_by_this_check=0
```

And through the check path itself, the id handed to it inside the container:

```text
pp channel check --chat-id <never printed>          -> exit 0
channel:  telegram
bot:      @PromisePatchDemoBot (id ...)
chat:     private (id not echoed)
provider: telegram
result:   reachable; no message was sent
```

**The address reached no output, no log and no transcript.** Measured rather than asserted: the
stored address does not occur in `GET /api/cases/{id}` (11 837 bytes) or in `GET /api/cases`,
computed in-process so the comparison never carried the value out; and `api`, `worker` and `mcp`
container logs hold **zero** lines matching `telegram:[0-9]+:` or `tg:[0-9]+`. The seven-or-more
digit runs visible in the public case payload were each located by key path and sit inside a
64-character hex `plan_id` or `fingerprint`, or a 36-character UUID `track_id` — coincidental
digit substrings of digests. The payload carries no `provider_ref`, no `sender_identity` and no
address field at all.

### 8. It sent nothing

**Zero across the whole run.** The deployed `worker` container's log, read over its entire
lifetime and again after both post-checks:

| counter | before restore | after restore and both post-checks |
|---|---|---|
| `sendMessage` | 0 | **0** |
| `worker.telegram.sent` | 0 | **0** |
| `MESSAGE_SEND` dispatch | 0 | **0** |

No plan was confirmed, no approval request or decision was created, and the case the restore left
is `PLANNED` — the point at which a person has yet to say yes.

### 9. The canonical partition

From the deployed `pp case-status` on `5b825f1b-...`, exception `SUPPLY_NOT_RECEIVED`:

| promise | order | band | option |
|---|---|---|---|
| `pr-a` | `EXT-A` Priya Nair | `AUTO_RECOVERABLE` via `R-PREAPPROVED (PREAPPROVAL_COVERS)` | `rv-raspberry-almond-3 -> rv-raspberry-almond-4` (no approval) |
| `pr-b` | `EXT-B` Tomas Lindqvist | **`APPROVAL_REQUIRED`** via `R-VISIBLE-ASK (VISIBLE_CHANGE_ASK)` | `rv-raspberry-rose-2 -> rv-raspberry-rose-3` (**approval required**), window closes `2026-09-23T18:06:37Z` — **exactly one** |
| `pr-c` | `EXT-C` Okafor-Reyes | `BLOCKED` via `R-NOSUB (NOSUB_CONSTRAINT)` | none — owner |
| `pr-d` | `EXT-D` Lena Fischer | `BLOCKED` via `R-NOSUB (NO_PREAUTHORED_VARIANT)` | none — owner |
| `pr-e` | `EXT-E` Ahmed Bouazizi | `UNAFFECTED` via `R-UNREACH (NOT_REACHABLE)` | none |
| `pr-f` | `EXT-F` Cafe Marlow | `UNAFFECTED` via `R-UNREACH (NOT_REACHABLE)` | none |

**And from the deployed SPA**, entered through the judge's read-only observer session, which
reports `role: observer`, `may_report: false` and tells the reader *"You are looking at this case.
Changing it is the bakery's to do."* It renders the same partition in the product's own words —
EXT-A *covered by a standing preference*, EXT-B *needs the customer ... by 2026-09-23 18:06
(UTC)*, EXT-C and EXT-D *needs the owner*, EXT-E and EXT-F *left alone* — above
`WAITING FOR YOUR YES`. No authority was changed to read it.

### 10. The infrastructure did not move

| | before release | after restore |
|---|---|---|
| Host instance / AMI / launch / volume | `i-087c742587f83d61d` / `ami-0fa4996c14e7d501e` / `2026-09-18T10:19:33Z` / `vol-0f330aaa62e637ef6` | **identical** |
| RDS | `db-U2JWQBTINX6W6GAB56EOTHOCSM`, `available`, private, encrypted | **identical** |
| Stack status / last updated | `UPDATE_COMPLETE` / `2026-09-22T19:32:21Z` | `UPDATE_COMPLETE` / `2026-09-23T12:52:06Z` — the release, **unmoved by the restore** |
| Change sets | none | none |
| Host `boot_id` | `79430d36-...` | `8f030425-...` at the **rollout**, and **unchanged across the restore** |

**The restore rebooted nothing**: the host `boot_id` and `uptime -s` (`2026-09-23 12:54:41`) are
the same immediately before and immediately after it. All three Docker volumes survive —
`promisepatch_caddy-data` still holds the Let's Encrypt certificate, its private key and the ACME
account key, so no certificate was re-ordered. `converge.sh` on the host is unchanged
(`09105b10...`). **No IAM policy was read, broadened or written**, and `ssm:SendCommand` is still
not granted and was not used: `ssm:StartSession` with `AWS-StartNonInteractiveCommand` was the
whole of the host access.

### 11. What this still does not prove

* **No refusal path was exercised live.** Nothing was arranged to make the restore refuse on a
  moved topology, a second bound customer, a `PENDING` outbox row or an unreachable order system.
  Those remain proved only by their tests. The two refusals this run *did* take —
  `PP_ALLOW_FIXTURE_RESET` absent, and `PP_DEMO_WORKER_PASSWORD` absent — were both free and both
  left the world untouched, but neither is one of the documented preconditions.
* **No message was sent**, so nothing here says a restored binding will carry a real approval
  through to a phone. It says the destination is one Telegram still confirms, and that the id the
  provider echoed back equals the id in the row.
* **The operator machine cannot read three of the twelve smoke checks.** Section 3 proves the
  deployment answers them; it does not make this machine a vantage from which smoke is 12/12.
* **The command is still not runnable as shipped on this deployment.** Section 4 is a defect
  recorded unfixed.
* CloudWatch still holds the log lines written before the redaction of
  [customer-disclosure-hardening.md](customer-disclosure-hardening.md); nothing here changed that.
