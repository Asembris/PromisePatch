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
