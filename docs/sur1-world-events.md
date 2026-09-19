# The SUR-1 armed events, and what makes each one fire

[sur1-world-programs.md](sur1-world-programs.md) closed one gap and named the next one exactly:

> **The armed events are not wired.** `realise` refuses any program that carries one, which is
> every program except `C04`.

This is that gap closed. Eight of the nine scenarios owe the world something that happens
*during* an attempt — a customer reply to an ask nobody has sent yet, that reply delivered twice
by the provider, the strawberry stock moving after a decision about it. Each of those is now a
declared event with an observable trigger, a single action, a one-shot identity and a place in
order, derived from the frozen scenario facts alone.

**No arm has been executed.** No `BASELINE`, `PROMISEPATCH` or `ABLATION` attempt has been
driven, no model has been called, no scorer has been run, no evidence has been collected and no
comparative result exists. Every proof below is taken from a controlled observation — a count of
outbound messages per channel address, handed to the arming directly.

**Nothing new has been run against a live system.** The realisation path's one exercise is still
the accidental `C04` fixture load recorded in
[sur1-world-programs.md](sur1-world-programs.md); no reply has been delivered to a live channel
and no movement has been posted to a live ledger.

## The event model

Each armed event declares five things and reads nothing else.

| | What it is | Where it comes from |
|---|---|---|
| **identity** | `C06:reply:1`, `C06:stock:1` — scenario, kind, ordinal | derived from the program's declared order |
| **trigger** | the observable condition that makes it due | one of exactly two forms, below |
| **action** | the one thing the world does | deliver a message, or post a movement |
| **one-shot identity** | the event id, and for a movement the ledger's `source_id` | firing is guarded twice |
| **order** | its index among the program's declared events | the frozen document's own order |

### A trigger reads two facts and no others

`Observation` is the whole of what a trigger is given: how many outbound messages have reached
each channel address since the attempt began, and which declared events have already completed.
There is no arm in it, no expected disposition, no scorer reading, no budget and no clock — so a
trigger cannot consult one even by mistake. There is no `sleep`, no timeout and no polling
interval anywhere on the firing path.

There are two trigger forms, and a declared event that fits neither **refuses** rather than being
approximated:

- **`ask_reaches_channel(channel, ordinal)`** — the *n*-th outbound message has reached that
  address. Ordinal rather than a boolean, because `C02` owes two replies on one channel and the
  second is due only when a second ask arrives. That is what keeps them in the frozen order
  without either event knowing about the other.
- **`event_completed(after)`** — an earlier declared event of the same scenario has finished.
  This is how *the world moves after the decision* is expressed without the world deciding
  anything: the decision became observable when the reply carrying it was delivered.

### Why the ask count is arm-blind

The count is taken from the channel record, which unions the product's own `outbox_messages`,
the accepted-reply record and the harness's own transport. An arm that **is** PromisePatch and an
arm that is not both reach a customer by putting a message on a channel, and the world answers
the message rather than the sender. `LiveScenarioWorld.invoke` takes a name and arguments; there
is no parameter an arm identity could arrive in, and `settle()` takes none at all.

That is what makes *the same program and the same observable sequence produce the same mutations
for every arm* a property of the code rather than a claim about three setups. A test drives two
armings through one sequence and asserts the same sink calls and the same log digest.

## The nine, and what fires them

| Scenario | Declared events | Trigger | Action | Fires |
|---|---|---|---|---|
| `C01` | `C01:reply:1` | 1st ask on `tg:1002` | deliver `YES` for `ord-b` | once |
| `C02` | `C02:reply:1`, `C02:reply:2` | 1st ask, then 2nd ask on `tg:1002` | deliver `Strawberries work.`, then `YES` | once each, in that order |
| `C03` | `C03:reply:1` | 1st ask on `tg:1002` | deliver `YES` | once |
| `C04` | none | — | — | nothing, and that is frozen |
| `C05` | `C05:reply:1` | 1st ask on `tg:1002` | deliver `YES` | once |
| `C06` | `C06:reply:1`, `C06:stock:1` | 1st ask; then `C06:reply:1` completing | deliver `YES`; post −5.6 kg of `res-strawberries` under `sur1:counter-sales:ord-b` | once each, reply first |
| `C07` | `C07:reply:1` | 1st ask on `tg:1002` | deliver `YES` **twice** under one `message_id` | one event, two deliveries |
| `C08` | `C08:reply:1` | 1st ask on `tg:1002` | deliver `YES` | once |
| `C09` | `C09:reply:1`, plus `scarcity g-strawberries` | 1st ask on `tg:1002` | deliver `YES` | reply once; the scarcity fires nothing |

**`C04` is eventless and stays that way.** The frozen document gives it no `consent_facts`,
no `stale_after`, no `duplicate_deliveries` and no `contention_groups`. Inventing one would be a
different scenario.

**`C07` is one message identity delivered twice, not two replies.** The provider redelivers; it
does not mint a new message. The event fires once and performs two deliveries under
`sur1-reply-C07-1`, and an arm that produces two effects from it has done something the world
did not.

**`C09`'s scarcity is a quantity, not a rule.** 3.0 kg of strawberries against a 2.4 kg claim and
a 2.2 kg claim is already true of the starting ledger, so nothing has to happen during the
attempt. It is declared so the snapshot states what the frozen document states, and it is the
only declared thing in the whole set that fires nothing.

**The external changes are pre-incident and are not events.** `C05` and `C08` re-pin an order
line in the order system *before any exception is reported*, so they are installed as steps
during realisation, in the order system's own record, with its own version bump. The frozen
contract stipulates no post-incident external change, and none is invented.

## The realisation lifecycle

`realise()` returns a `Realisation` whose state is `READY`, or it raises. There is nothing in
between and no partly-prepared world a run could proceed from.

1. **Plan.** The firing plan is derived from what the program declares. A declared event that
   must happen and that no trigger can honestly observe raises here — *before* anything is
   written, because a world that installed perfectly and then owed an impossible reply is worse
   than one that refused.
2. **Check the starting world.** The digest of the graph about to be installed is compared with
   the frozen declaration's own `world_digest` for that scenario. A program that has drifted away
   from the freeze refuses rather than installing a world nobody declared.
3. **Install.** The canonical graph goes through the product's own governed fixture load, in one
   audited transaction.
4. **Cross.** Each pre-incident external change is posted to the order system's own surface.
5. **Arm.** The plan becomes a live `Arming`, carried on the receipt.

Only then is `READY` returned. A refusal at any stage never reports `READY`, and a program that
declares events with no sink to perform them is refused **before** step 3 — proved by asserting
the installer was never called.

Step 2 is deliberately a check of the object about to be written, not a read-back of the
committed rows. Reading a canonical snapshot back out of PostgreSQL is a separate surface with
its own schema, and the freeze is about the canonical form. That remains unbuilt and is named
under *What is still open*.

## Reset and isolation

- **Each attempt starts clean.** `LiveScenarioWorld.prepare` clears the channel, forgets the
  worker surface, mints a new run identity and takes a **fresh** `Arming` from `realise`. Nothing
  is reused.
- **Nothing leaks between scenarios.** Every event id is prefixed with its own scenario, and two
  armings share no object. A test drives `C02` to completion and asserts a freshly realised `C06`
  has an empty log and a full pending list.
- **A retry begins from a fresh world.** Realising one scenario twice produces two distinct
  armings with the same world digest, and the first one's fired state does not reach the second.
- **An event fires once.** Pumping six times with a satisfied trigger fires each event exactly
  once. For the stock movement there is a second, independent guard: `uq_inventory_ledger_source`
  refuses a repeat of `sur1:counter-sales:ord-b` in PostgreSQL, which a crashed process's lost
  memory cannot defeat.
- **A failure fails closed.** An action that raises marks the whole arming `FAILED` and every
  later pump refuses. What did happen is kept — the reply really was delivered, and a failure
  that unsaid it would be an undo.
- **A reset clears everything.** `Arming.reset()` empties the fired log, restores the full
  pending list and returns the state to `ARMED`, including from `FAILED`.

## The structural guard

`preflight.event_blinding()` is a new refusal beside `blinding()`, and it makes the same argument
about the firing path that `blinding()` makes about the scoring path — for a sharper reason. A
world whose events fired differently depending on which arm was driving would make every later
number a comparison between three different worlds, and the failure would be invisible in all of
them.

Three structural facts, read from the syntax rather than from behaviour:

1. `Observation` — the whole of what a trigger may read — carries no field an arm label could
   travel in;
2. neither `events.py` nor `worldsink.py` names `ground_truth`, `the_point`, `expected_report`,
   `ablation_target`, `BASELINE`, `PROMISEPATCH`, `ABLATION`, `arm`, `arm_label`, `label`,
   `system` or `adapter` **as code** — a literal, an attribute or a name;
3. neither can import the scorer at all.

It matches on exact names in the syntax, never on substrings of prose: a module that explains in
its docstring why a trigger must not consult an arm is doing the right thing. A test writes four
offending files and asserts each is caught, so a pass means the guard looked.

Both modules are also in `IMPLEMENTATION_MODULES`, so `ground_truth_reachable()` walks them too.

## What moved in the freeze, and what did not

| Identity | Before | After |
|---|---|---|
| `SUR-1` `manifest_sha` | `5718340f…` | **unchanged** |
| `program_set_sha` | `88db566c…` | **unchanged** |
| every `program_sha` (nine) | — | **unchanged** |
| every `world_digest` (nine) | — | **unchanged** |
| `snapshot_schema_version` | `1` | **unchanged** |
| `implementation_sha` | `b3240cd1…` | **moved** |

Only `implementation_sha` moved, and moving is what it exists to do: it hashes the source that
computes the other two, and `events.py`, `worldsink.py` and a rewritten `realisation.py` are now
part of that source. Nothing a program declares changed, and no starting world changed — which is
why the scientific claim the freeze carries is untouched.

The nine starting worlds and the set hash are now **pinned as literals** in
`scripts/tests/test_sur1_world_programs.py`. `declaration.differences()` compares the code with
the published document, which catches one of them moving and not both; the literals are the other
half, so a later session that changed a world and re-froze the declaration to match still fails.

## What is still open

**The realisation path is still essentially unexercised against live systems.** It has been
proved end to end against a fake installer and a recording sink, and its channel half has been
proved through the world's own `invoke` with the harness transport. But no world has been
installed for this work, no external change has been posted to the order system, and no movement
has been posted to a real `inventory_ledger`. The `LedgerWriter` insert in particular has never
run.

**The starting world is not read back out of the database.** Step 2 checks the object about to be
installed. A row-level readback that re-derived the canonical snapshot from PostgreSQL would be a
stronger check and is a separate piece of work.

**A reply arrives on the harness transport, for every arm.** That is what makes the trigger and
the delivery arm-blind, and it is a transport rather than a second protocol — nothing in it is
read as a decision. Whether the `PROMISEPATCH` arm additionally needs the reply to arrive through
the product's own signed-possession-link path, so its consent protocol parses the words it
actually parses in production, is a real question this work does **not** answer. It is the next
thing to settle before a scored run, and it is not settled here.

**No arm has been driven.** Firing an event during a real attempt, with a real model on the other
side of the channel, has not happened and is not what this work did.

## Where the parts are

| Path | What it is |
|---|---|
| `scripts/sur1/bindings/events.py` | the event model: triggers, actions, the plan, the arming |
| `scripts/sur1/bindings/worldsink.py` | the world's two powers, performed against the live systems |
| `scripts/sur1/bindings/realisation.py` | the realisation lifecycle and its refusals |
| `scripts/sur1/bindings/world.py` | `settle()`, on the ordinary action path |
| `scripts/sur1/preflight.py` | `event_blinding` |
| `scripts/tests/test_sur1_world_events.py` | the event model and the lifecycle, with no arm |
| `scripts/tests/test_sur1_live_bindings.py` | an ask on the channel delivering a scenario's reply |
