# The demo world stops decaying, and no case pays for it

## What was wrong

`docs/demo-fixture-anchoring.md` measured this rather than reasoning about it, and nothing here
changes a word of it. Every instant in `promise_graph.examples.hollow_oak` is an offset from an
anchor the caller supplies; `pp reset-demo-state` with `--anchor` omitted resolves that anchor to
`now` for twenty-two hours of every day; and the `seed` service sits behind a compose profile so
it runs **once per instance**. The world's *today* is therefore the bootstrap day, for ever.

The decay is not that the demo goes quiet. Today's Valley Produce delivery is due an hour after
the anchor, so it stops being *today* at the next local midnight — and what takes its place
inside that day is **tomorrow's** Valley Produce delivery, which also carries raspberries. The
reading does not stop to ask. It resolves confidently to a delivery no promise is waiting on, and
every promise the exception reaches falls to `BLOCKED`. Both bands the product exists to show —
the one it repairs by itself and the one it must ask a customer about — are gone one day after the
seed, with nothing reporting an error. A day later still there is no raspberry delivery to name at
all. That is asserted, not described, by
`test_a_seeded_world_stops_telling_the_story_at_the_next_bakery_midnight`.

A seed is good for the rest of its own bakery day and no longer.

## The two options that do not work, and why

**Provisioning a fresh case for the current bakery day and leaving existing cases alone.** This is
the obvious answer and it is wrong twice over. The case is not what decayed — the *world* is, and a
new case read against a day-0 world reads exactly the four blocked bands above. And even if the
world were current, `promisepatch.domain.analysis`'s `_live_tracks_elsewhere` gives every promise
another live case already holds the `LINKED` state, so a second case opened beside a live first one
shows six linked tracks and no authority bands at all. Opening a case beside a live case is not an
additive operation in this system; it is a case that shows nothing.

**Re-anchoring only when no case has been touched within a stated window.** This is the naive fix
the brief warns about, wearing a clock. A window is a guess about whether a case matters, and the
guess is wrong in both directions: a judge reading quietly for four minutes leaves no row and looks
identical to an abandoned case, and a case somebody left open on Friday is still theirs on Monday.
Worse, the operation it guards is `reset_demo_state`, which truncates: being wrong destroys the
case rather than inconveniencing it. Nothing here needs a window, because "has anybody touched
this" is answerable exactly from rows.

## What is built instead

**The world is moved, not reloaded.** `promisepatch.fixtures.reanchor.reanchor_world` adds one
duration to every instant the fixture owns. Nothing is truncated, no id moves, no session is
signed out, the order mirror keeps its version numbers so it still matches the External Order
System, and every non-instant edit — an external order change that crossed as a webhook, say —
survives untouched, because no column holding a quantity is written at all.

* **The duration is measured, not remembered.** It is the difference between where today's Valley
  Produce delivery *is* in the durable rows and where a seed taken now would put it, read back
  through the fixture's own offset. A world already rolled, or seeded by an operator at an anchor
  nobody wrote down, lands in the same place as one that has not.
* **Which columns move is derived from the projection**, not listed. `shiftable()` projects the
  fixture and asks which columns really hold a `datetime`, so a table that gains a time is carried
  without anybody remembering to add it, and `test_every_instant_the_projection_writes_is_either_shifted_or_append_only`
  fails if one is ever neither shifted nor append-only.
* **Every column of a table moves in one statement.** `production_tasks` carries a `CHECK` that its
  scheduled start precedes its scheduled end; moving one of the pair and then the other leaves a
  row that breaks it in between. This was found by a test failing, not by reading the schema.
* **Two instants deliberately do not move.** `recipe_versions.authored_at` and
  `inventory_ledger.recorded_at` are append-only by `promisepatch.db.boundary.APPEND_ONLY_TABLES`,
  so an `UPDATE` on them fails as immutable whatever authorises it. Both are history, neither is
  read against the clock to decide a band, and leaving them is more truthful than pretending the
  recipes were authored this morning. `fixture_state.fixture_digest` is left alone for the same
  reason: it is the digest of the load this world descends from, and rewriting it would claim
  those two columns had moved when they had not. `anchor_at` and `loaded_at` are updated.

**The superseded case is concluded, never destroyed.** Before the world moves, the case
provisioning itself opened is handed to the domain's own bounded withdrawal. With no dispatched
effect and no production hold to reverse, it settles at `CANCELLED` with every track `WITHDRAWN` —
which is what releases those promises, since `WITHDRAWN` is terminal and a terminal track is not
one a later case has to link to. The row, its words, its tracks and its audit stay exactly where
they are, and a judge can still open it.

**Nothing moves if anything would be lost.** Four questions, asked of rows:

| what is checked | why it is fatal to a roll |
| --- | --- |
| any row in `outbox_messages` | an effect has reached a customer or the order system; the mirror and the simulator no longer match a fresh seed |
| any row in `inbound_replies` | a customer has answered something |
| any row in `approval_requests` or `approval_decisions` | an approval was asked for or given |
| any live case that is not the provisioned one | somebody else's case, whatever it says |

Any one of them and the run is `REFUSED`: the world stays exactly where it is and the reason is in
the log. A stale demo is a bad demo; a demo that ate somebody's work is a broken product, and P6.2
records what that costs.

## The precondition this rests on, stated rather than assumed

**The first three of those four questions are asked of the whole database, unscoped by case and
unscoped by time.** `_what_would_be_lost` calls `_any`, which is
`select(func.count()).select_from(model)` with no `WHERE` at all: not "on this case", not "since
the anchor", not "in the last day". One row in `outbox_messages`, one in `inbound_replies`, one in
`approval_requests` or one in `approval_decisions` — anywhere, from any case, of any age — and the
answer is `REFUSED`. Only the fourth question, the live-case one, is scoped to an identity.

**And no ordinary operation ever deletes those rows.** There is no `delete()` against any of the
four anywhere under `apps/backend/src/`. The only statement that removes them is `reset.py`'s
`TRUNCATE`, which is the destructive repair an operator chooses, not something the system does to
itself. `outbox_messages` in particular is a ledger of what went out; emptying it on a schedule
would be the wrong fix and is not one anybody should reach for on the strength of this paragraph.

Put together, the refusal is **monotone and permanent**. The four questions are not a check that a
world is currently busy; they are a check that it has *never* been used. The first customer
message, the first reply, the first approval asked for, and the roll stops for ever — not for a
day, not until the case concludes, not until the case is withdrawn. A withdrawal concludes a case
and leaves every one of those rows exactly where they are.

**The roll therefore survives only because the judge principal cannot write.** A judge arrives
holding `observer`, which [ADR-0013](adr/0013-read-only-observer-principal.md) admits to reads and
to nothing else, seeded with a password hash Argon2 cannot parse so no login can ever produce it,
and which [ADR-0016](adr/0016-a-judge-principal-stays-read-only.md) re-establishes on the stronger
ground that a `report` is a physical attestation about the one shared bakery. A read leaves no
outbox message, no reply and no approval. That, and only that, is why a world can be read by
visitor after visitor and still roll cleanly the next morning.

Two consequences follow, and neither is hypothetical:

* **Granting judges write authority would end this.** Not degrade it — end it. The first visitor
  who confirms a plan queues a customer message, and from that moment every roll on that host
  reports `REFUSED` for ever, and the world resumes decaying exactly as it did before this was
  built. Whatever else a per-visitor write principal would need, it would also need this
  mechanism replaced: an emptiness check over the whole database cannot coexist with visitors who
  fill it. That is a second reason to keep the principal read-only, and it is a *consequence* of
  ADR-0016 rather than an argument for it — the authority argument stands on its own and does not
  need this one.
* **Recording a demo against the deployed host with worker credentials freezes the world.** Signing
  in as `maya` or `jo` and driving the canonical conversation is exactly the thing the four
  questions refuse to move under, and it must be: those effects reached the External Order System
  and a customer. One recorded take, and the deployed world is pinned to whatever day it was on,
  until somebody runs the four-step repair below. This is not a defect to be fixed by loosening
  the check — it is the check working. Plan a recording session on the understanding that the
  repair follows it, and that the repair destroys the cases on the host.

**The case identity is derived from the world, not from the clock.** `report_command_id` and
`answer_command_id` are `uuid5` of the world's anchor, so two boots against one world produce one
case and a rolled world produces a new one. This is not the first thing that was written — keying
it to the bakery day was, and a test caught it: a roll would conclude the case and then recognise
its own new report as a redelivery of the one it had just cancelled, leaving a judge on a
`CANCELLED` case. The anchor was always the right key, because the thing being identified is the
world.

**It runs once per bakery day, not only at boot.** `worker._DemoCaseKeeper` checks before the loop
starts and again on the first idle cycle of each new bakery day — awaited from the loop's own task,
so it can never run a cycle concurrently with the loop. A boot-only check would leave a host that
is never restarted serving the bootstrap day's world for ever, which is the deployed situation
exactly.

## What a judge gets

Whatever day they arrive: the case at the top of the list is a case opened against a world
anchored to that day, with `EXT-A` auto-repairable, `EXT-B` awaiting a customer, `EXT-C` and
`EXT-D` with the owner, `EXT-E` and `EXT-F` untouched and counted, every deadline still ahead, and
**zero operational effects**. That is asserted through `GET /api/cases/{id}` as the observer
session the judge entry mints — the screen, not the row — at seeds **+1 day, +60 days and +400
days** in `apps/backend/tests/test_demo_world_roll.py`.

## The operator action this needs

**Nothing here touched the deployed host, and nothing here reaches it by itself.** The change is in
the backend image, so it arrives the way any release does:

```bash
./deploy/deploy.sh images config rollout smoke
```

`converge.sh` re-reads compose, the Caddyfile and `image-tag` from SSM at every boot, so no stack
update is needed. Leave `PP_DEPLOY_TLS_HOSTNAME` unset; set `PP_DEPLOY_DB_BACKUP_DAYS=1`.

**One further action is needed on this particular host, once.** The deployed database already holds
cases opened by hand and effects those cases dispatched, so the first roll after the release will
report `REFUSED` and leave the world alone — correctly, because it cannot tell that work from work
somebody still wants. The way out is the four-step repair already written down in
`docs/demo-fixture-anchoring.md`, *Bringing a running deployment back to the story*: reseed, reset
the External Order System, restart the worker, sign in again. It destroys the cases on the host,
which is why it is an operator's decision and not this code's. **After it, provisioning owns the
case, and the roll keeps the world current without anybody being asked again.**

If that repair is never taken, the deployment behaves exactly as it does today: a stale world, a
refusal in the log, and no case destroyed.

## Later: the repair this points at is now one command

**Recorded beside what is above rather than edited into it.** The roll is unchanged, its four
questions are unchanged, and the refusal is still monotone and permanent for the reasons stated
above — none of which this weakens.

What changed is only the *way out* it points at. Since 2026-09-23 the four-step repair in
`docs/demo-fixture-anchoring.md` is also `pp restore-demo-world --confirm destroy-and-restore`.
It is still destructive, still an operator's decision, and still the thing that has to follow a
recorded demo. See [demo-world-restore.md](demo-world-restore.md).
