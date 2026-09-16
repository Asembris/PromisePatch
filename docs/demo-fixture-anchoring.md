# The demo fixture's anchor, and why the deployed story decays

## The question

Three days after the deployed host was seeded, the canonical case no longer told the canonical
story: `EXT-A` read `NOT_REACHABLE` / untouched where it had read `AUTO_RECOVERABLE`, the
untouched count had gone from two to three, and `EXT-B`'s deadline read as a past time. The
engine is byte-identical across those commits. Only the clock moved.

The suspicion was that the fixture is anchored to a fixed date. **It is not.** What follows is
what the code actually does, established from the code, because the difference decides whether
the repair is a line of Python or an operator action on a running host.

## How the fixture's dates are set

Every instant in `promise_graph.examples.hollow_oak` is an offset from an `anchor` the caller
supplies — `Times.at(**offset)` and nothing else. `hollow_oak.ANCHOR`, the only absolute date in
the module, is a default used where a byte-stable hash is asserted; the behavioural tests vary
the anchor and `test_hollow_oak_matrix` runs the canonical matrix at three of them, one in 2027.

A reset chooses that anchor. `pp reset-demo-state` with `--anchor` omitted — which is how both
stacks seed, `deploy/compose/docker-compose.deploy.yml` running `["pp", "reset-demo-state"]`
with no argument — calls `promisepatch.fixtures.demo.resolve_demo_anchor(datetime.now(UTC),
settings.bakery_tz)`, and that returns **`now`** for twenty-two hours of every day.

So the fixture's dates are relative to the instant the seed ran. Relative to `now`, and `now`
only.

## What 122bebb fixed

`resolve_demo_anchor` is that commit. It does not make the anchor relative — the anchor was
already `datetime.now(UTC)`. It removes the two hours a day where `now` is an anchor the demo
cannot be driven from.

The fixture states its two Valley Produce deliveries an hour and twenty-three hours after the
anchor, and the canonical clarifying question — *the whole delivery, or just the raspberries?* —
is about **today's** one. Which bakery day an instant falls in is read from the real clock
(`promisepatch.domain.physical.bakery_day`), so an anchor within an hour of local midnight puts
both deliveries in one day, and an anchor within an hour of the day's end pushes today's
delivery into tomorrow. Either way the interpreter asks which commitment was meant, every option
carries the same words, and no answer resolves it.

122bebb reads the two offsets off the dataset rather than restating them, computes the window
they imply — the anchor's local time of day must be in `[01:00, 23:00)` — returns `now`
untouched inside it, and moves `now` by minutes, never hours, outside it. An operator who names
an anchor still gets exactly it. `apps/backend/tests/test_demo_anchor.py` walks the whole day at
five-minute steps and asserts the property directly.

All of that stands. Nothing here changes it.

## What actually decays

The seed is a point-in-time world, and it is written once. On the deployed host the `seed`
service sits behind a compose profile so `up -d` can never reach it, and the bootstrap's
`docker compose --env-file env/stack.env run --rm -T seed` is the only thing that starts it —
once per instance. That profile is not an accident: P6.2 records a reboot that re-ran an
unguarded seed and erased the very cases the deployment exists to prove outlive the host.

So the world's "today" is the day the instance was bootstrapped, for ever. A case opened later
says *today's raspberry delivery didn't arrive* into a world where that delivery is no longer
today. `_commitment_candidates` narrows on the word *today* against `bakery_day(now)`, and what
it finds depends only on how long ago the seed ran. Measured against the fixture, from a seed at
nine in the morning:

| when the case is opened | what *today's raspberry delivery* resolves to | the bands |
| --- | --- | --- |
| the same bakery day | `com-vp-today` | `pr-a` auto, `pr-b` consent, `pr-c`/`pr-d` blocked, `pr-e`/`pr-f` untouched |
| the next day | `com-vp-tomorrow`, silently | every reached promise `BLOCKED`; no auto band, no consent band |
| two days on | nothing — no raspberry delivery falls in the day | the reading stops to ask which delivery was meant, and both options carry the same words |

The middle row is the dangerous one, and it is why this was worth measuring rather than
reasoning about: tomorrow's Valley Produce delivery also carries raspberries, so the reading does
not fail. It resolves confidently to a delivery no promise is waiting on, and the two bands that
make this more than a workflow engine disappear without anything reporting an error. Which of
these three a particular screen shows depends on when its case was opened relative to the seed,
and that cannot be reconstructed from outside the host.

The decay is in the durable rows, not in the rule that wrote them.

## Blast radius of moving the anchor

Established before anything was changed, because a wrong answer here puts the published 11/16 at
risk.

* **The sixteen frozen scenarios do not use `resolve_demo_anchor`.** They seed through
  `apps/backend/tests/_intake_support.py`, whose `bakery_anchor` is its own now-relative rule —
  `max(now - 2h, local midnight + 1h)` — chosen so the delivery is an hour in the past and the
  day's work still ahead. Nothing in the demo anchor path can reach them.
* **`docs/effect-sets/scenarios.v1.json` holds no date that a run reads.** Its only date is the
  `authored_at` metadata field; its fixture note says each scenario starts from `hollow_oak()`
  at its own anchor.
* **`apps/backend/tests/_effect_sets.py` contains no date, no anchor and no clock.**
* **The ten-turn voice measurement did seed through this path** — `pp reset-demo-state` with the
  anchor deliberately omitted. That measurement is taken, published and not re-run; a change to
  the rule would change what a future re-seed produced, not what was recorded.

## What is proved instead

`resolve_demo_anchor` is date-independent, and that is now asserted rather than assumed.
`test_demo_anchor.py` walks every five-minute seed of a day sixty days out and of a day a year
out, and asserts at each one that the canonical partition holds — `pr-a` auto-repairable, `pr-b`
consent-required, `pr-c` and `pr-d` owner-blocked, `pr-e` and `pr-f` untouched — that every
customer promise is still ahead of the seed, and that today's delivery is today while tomorrow's
is not. One test seeds from the real clock at `now`, `now + 60 days` and `now + 365 days`, so a
run in November answers for November.

The band assertions resolve the commitment the way the reading does instead of pinning it, which
is what makes them discriminating: against a genuinely fixed anchor they fail with *0 raspberry
deliveries fall in the bakery day containing …*, which is the deployed symptom stated as a
failure. Pinning the commitment would not have caught it — classification alone survives a year
of drift.

## Bringing a running deployment back to the story

There is no fixture change that repairs seeded rows, and re-anchoring them in place is not on
offer: the cases already on the host reference the orders, promises and commitments that would
have to move under them. The repair is an operator action, and it is written here so the cost is
known before it is taken rather than after. **It is a decision for the project owner. Nothing in
this work performed it, and nothing in this work touched the deployed host.**

Four steps, in `/opt/promisepatch` on the instance:

1. `docker compose --env-file env/stack.env run --rm -T seed` — `pp reset-demo-state` with the
   anchor omitted, which reloads the Hollow Oak fixture at today's anchor.
2. `docker compose --env-file env/stack.env exec order-simulator python -c "import
   urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8100/admin/reset', method='POST'))"`
   — the External Order System keeps its own Docker volume and a PromisePatch reset does not
   reach it, so without this the order book still carries every amendment and operator edit the
   old cases made, against a mirror that has just been rebuilt at version 1. Run 1 of the voice
   measurement was spoiled by exactly this.
3. `docker compose --env-file env/stack.env restart worker` — `ensure_demo_case` runs at the
   worker's start and nowhere else, so the fresh canonical case appears only after the worker is
   restarted. It opens one because `cases` is empty again.
4. Sign in again. `resettable_tables()` is *every table minus the ledgers of record*, so
   `sessions` is truncated and every open session is signed out.

**What it destroys.** Step 1 truncates every table except `audit_events` and `domain_events`, so
the cases on the host go, and with them their tracks, statements, clarifications, approval
requests, inbound replies, effects, steps and the orders and promises they point at. The audit
and domain-event ledgers survive, which means the history of what those cases did is still
readable even though the cases are not. Step 2 discards the order system's accumulated state,
including any `S11`-shaped external edit somebody made by hand.

**`docker compose down -v` is not the way to do step 2.** It would also remove `caddy-data`,
which holds the Let's Encrypt certificate and account key, forcing a re-issue against Let's
Encrypt's rate limits for a demo that is about to be watched.

**When to take it.** Close to when the demo is watched. A seed is good for the rest of the bakery
day it was taken on and no longer, which is asserted by
`test_a_seeded_world_stops_telling_the_story_at_the_next_bakery_midnight`. Seeding the morning of
a recording is fine; seeding a week before it is the state this document was written about.
