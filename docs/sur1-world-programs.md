# The nine SUR-1 world programs

`SUR-1` was frozen as a document. Its nine scenarios state their worlds as English sentences —
*the strawberry line is therefore attested received: 6.0 kg* — and the execution harness could
compose a run, bind three arms and read four receivers, but it could not **set a scenario up**.
The preflight refused every scored run for that reason and named it.

This is that gap closed: nine executable world programs, frozen with their own hashes, verified
without driving an arm.

**No arm has been executed.** No `BASELINE`, `PROMISEPATCH` or `ABLATION` attempt has been driven
at any scenario, no model has been called, no evidence has been collected, no capture has been
written and no comparative result exists. The declaration carries that statement and a test
asserts it.

**One thing was run, and the freeze says so.** While a refusal message was being checked, the
realisation path executed once against the **local development** PostgreSQL: `C04`'s canonical
world was installed through the governed fixture load, and the local demo fixture was restored
immediately afterwards with `pp reset-demo-state`. No arm was driven at that world, no
order-system change was posted, nothing was read back from it and no capture exists. It is
recorded in the declaration as `realisation_exercised` rather than left out, because a freeze
whose honesty rests on a sentence that is slightly false is not a freeze.

## What a program may read, and why that is the whole argument

A program written while its scenario's expected answer was visible is not distinguishable from
one written **towards** it. "We did not look" is a promise. This is a mechanism.

`StipulatedFacts` (`scripts/sur1/bindings/programs.py`) is the only way a frozen scenario reaches
a builder. It exposes exactly:

| Field | What it is |
|---|---|
| `id`, `slug`, `title`, `dimension` | the scenario's own identity |
| `stipulated_facts` | the sentences that describe the world |
| `consent_facts` | the customer replies the scenario stipulates |
| `stale_after` | the world moving between a decision and an act |
| `duplicate_deliveries` | one provider message delivered more than once |
| `contention_groups` | a quantity that cannot serve every claim at once |

Every other key raises `ForbiddenFieldError`. Four of them say what a correct answer is and are
named in `scripts/sur1/preflight.py` as `FORBIDDEN_SCENARIO_FIELDS`: `ground_truth`, `the_point`,
`expected_report` and `ablation_target`. They stay in the manifest — removing one would edit a
frozen document — and nothing on the preparation path may name one.

Three separate things enforce that, and they fail in different ways on purpose:

1. **The view raises.** `facts["ground_truth"]` is a `ForbiddenFieldError`, not a `None` a
   program could branch on.
2. **The set rebuilds without them.** Delete every non-allowed key from all nine scenarios,
   rebuild the whole program set, and the program-set hash and all nine world digests are
   unchanged. If any program had read an answer, they would not be.
3. **The source is parsed.** `preflight.ground_truth_reachable()` walks the AST of every module
   on the preparation path and fails if one so much as names a forbidden field as a string, an
   attribute or a name. This is the structural regression: it bites the moment a program starts
   reading an answer, whether or not a test exercises that branch.

## The nine

Every program starts from a clean `hollow_oak()` and applies its steps in the order the frozen
document lists them. No program creates an entity the fixture does not already contain; the only
version that exists in a prepared world and not in the clean fixture is `rv-raspberry-charlotte-2`,
which `C03` stipulates as authored in advance and which the fixture's own
`with_charlotte_variant` produces.

| Scenario | Dimension | Initial steps | Armed events |
|---|---|---|---|
| `C01` | `auto_recovery` | strawberry line attested `RECEIVED` 6.0 | one reply on `tg:1002` |
| `C02` | `customer_approval` | strawberry line attested `RECEIVED` 6.0 | two replies on `tg:1002`, in order |
| `C03` | `no_substitution_blocked` | Charlotte variant authored; wedding refusal kept; receipt 6.0 | one reply |
| `C04` | `unaffected_promises` | mascarpone stock recorded unusable | none |
| `C05` | `pre_incident_external_change` | `ord-d` re-pinned externally to `rv-lemon-curd-1`; receipt 6.0 | one reply |
| `C06` | `stale_revalidation` | strawberry line attested `RECEIVED` 6.0 | one reply; the world moves −5.6 kg |
| `C07` | `duplicate_replay` | strawberry line attested `RECEIVED` 6.0 | one reply, delivered twice |
| `C08` | `already_started_work` | `ord-e` re-pinned externally to `rv-raspberry-lemon-2`; three assertions; receipt 6.0 | one reply |
| `C09` | `shortfall_contention` | strawberry line attested `SHORT`, 1.0 of 6.0 arrived | one reply; declared scarcity `g-strawberries` |

The arithmetic the contract states is what the ledger actually holds: 8.0 kg of strawberries for
every receipt scenario (2.0 on hand plus 6.0 arriving), 3.0 kg for `C09` (2.0 plus 1.0), and zero
mascarpone for `C04`. A test asserts each one off the prepared world rather than off the prose.

One piece of wording is the harness's and not the document's. Each program carries the incident
every arm reads through `get_incident`: the report and the scope answer are the contract's own
words, but the contract says only that the report is *ambiguous in scope* and never writes the
question down. `SCOPE_QUESTION` is therefore the harness's phrasing of that ambiguity, stated as a
module constant so it is visible as a choice, and it is one wording seen identically by all three
arms — which is the property that matters.

### Two kinds of step, and the difference matters

**A step that changes the world** — `AttestCommitmentLine`, `SpoilStock`, `AuthorVariant`,
`ExternalRepin` — projects one stipulated fact onto the graph.

**A step that asserts** — `RequireTaskState`, `RequireNoConstraint`, `RequireNoSubstitute`,
`RequireConstraint` — checks the fixture and writes nothing. `C08` stipulates that `task-ol-e` is
already started; starting work is a physical claim about a kitchen, and a setup that could write
`STARTED` would let this harness manufacture an attestation. So the fixture is the authority, the
program checks it, and a scenario whose stipulation has drifted away from the fixture refuses to
be prepared rather than being made true by the thing that measures it. The same rule as
[started-work-contract.md](started-work-contract.md), applied to preparation.

### An armed event is declared, never pre-delivered

Three frozen fields describe things that happen *during* an attempt and are conditional on what an
arm does: a customer's reply to an ask the arm has not sent, a second delivery of that reply, and
the world moving after a decision. Writing any of them into the starting state would be a world in
which somebody answered a question nobody asked, or a shortage an arm could see coming before the
`YES` it invalidates.

They are carried as `ArmedEvent` values — ordered, named, hashed, and part of the snapshot as
*due but not delivered*. `C09`'s contention is the exception in form only: the scarcity is realised
entirely by the starting quantity, and the group is declared so the snapshot states what the
frozen document states.

## The world snapshot and its digest

`scripts/sur1/bindings/worldsnapshot.py` renders one prepared scenario as a canonical payload and
hashes it. Schema version `1`.

It holds the observable starting state and nothing about what to do with it: orders with their
external versions and pinned items, customers and their channels, recorded constraints, promises,
every task's state and holder, recipe version lines, substitution policies, commitment lines with
their settlement, reservations, on-hand quantity per resource, the whole ledger in sequence, the
scenario's external changes, and the replies that are due.

Two properties make it worth hashing:

- **Arm-independent.** Nothing in the call chain takes an arm, a token, a budget or a model. There
  is no parameter by which two arms could be handed two snapshots.
- **Anchor-independent.** Every instant is rendered as whole seconds from the fixture anchor. The
  fixture is relative-time by design, so a run prepared at nine in the morning is the same world as
  one prepared at noon, and a digest that disagreed would be measuring the clock.

Nine scenarios produce nine distinct digests. Two independently built program sets produce the
same nine.

## The freeze

`docs/benchmarks/sur1-world-programs.v1.json`, program set `SUR-1-WORLD-PROGRAMS` v`1.0.0`, pinned
to manifest `5718340f…`. It carries three identities because three different things can move:

| Identity | What moves it |
|---|---|
| `program_set_sha` | a step reworded, reordered, retyped; an armed event changed |
| `world_digest` (per scenario) | the starting world those steps produce |
| `implementation_sha` | the source that computes either of the above |

The third exists because the first two are computed by code: a snapshot renderer that quietly
stopped including task states would leave nine digests looking stable while the thing they
describe had changed. It hashes the bytes of `programs.py`, `worldsnapshot.py`, `realisation.py`
and `setup.py`, with line endings normalised so a checkout style does not move it.

Recheck at any time, and never as part of a run:

```bash
uv run python -m scripts.sur1.bindings.declaration
```

A run that rewrote its own declaration when it disagreed with it would have no freeze at all, so
`--write` exists, is for the freeze itself, and is called by nothing in the harness.

## What the preflight now refuses

`world_programs` was one check and is now two.

- **`world_programs`** — every selected scenario has a program *and* that program builds the world
  it declares. Building it is the check: a program naming a version the fixture lacks raises while
  it is projected, and it has to raise before an attempt is bought rather than inside the
  preparation of the third arm's second scenario.
- **`world_program_freeze`** — the program set is exactly the contract's nine; nothing on the
  preparation path can name a field that says what a correct answer is; and the set hash, every
  program hash, every world digest, the snapshot schema version and the implementation hash all
  match the published declaration.

A scored run is refused if either fails, with every reason named. A third,
`event_blinding`, was added beside them when the firing path was wired; it is described in
[sur1-world-events.md](sur1-world-events.md).

## How a world is installed

`scripts/sur1/bindings/realisation.py`. The canonical world **is** the thing installed, not a
recipe for building something like it: the program's projected graph is handed to the product's own
governed fixture load, which projects it to rows and writes them in one audited transaction. There
is no second construction path, so the world an arm acts on cannot drift from the world the digest
describes.

That needed one additive change to `promisepatch.fixtures.reset.reset_demo_state`: optional
`snapshot` and `fixture_name` parameters, both defaulting to the demo fixture, so every existing
caller loads exactly what it loaded before and the `fixture_state` row says which world is actually
installed rather than always claiming the demo one.

The one thing that is not a fixture load is a pre-incident external change. The order system is a
separate application with its own record, rule `B6` turns on who committed an event, so `C05` and
`C08` post the operator change to the simulator's own surface and let it commit its own event.

## What was still open, and what closed it

**The armed events were not wired.** `realise` refused any program that carried one, which was
every program except `C04`. That is closed: each declared event now has an observable trigger, a
single action, a one-shot identity and a place in order, all derived from the frozen scenario
facts, and all nine programs realise. See [sur1-world-events.md](sur1-world-events.md) for the
event model, the trigger inventory, the lifecycle and what it leaves open — including the one
piece this record's own claim depends on, that a reply arrives on the harness transport for every
arm.

Only `implementation_sha` moved when that work landed. The program-set hash, all nine program
hashes and all nine world digests are byte-identical, and they are now pinned as literals in the
test as well as checked against the published document.

**The realisation path is still essentially unexercised against live systems.** It ran once, by
accident, for `C04` against the local development database, and that is still the whole of the
evidence that its fixture load works: no world has been read back out of PostgreSQL, no external
change has been posted to the order system, and no movement has been posted to a real ledger. The
programs are frozen on their canonical form, which is the form the freeze is about.

## Where the parts are

| Path | What it is |
|---|---|
| `scripts/sur1/bindings/programs.py` | the nine programs, the step vocabulary, the allowed-field view |
| `scripts/sur1/bindings/worldsnapshot.py` | the canonical snapshot and its digest |
| `scripts/sur1/bindings/realisation.py` | installing a canonical world in the live systems |
| `scripts/sur1/bindings/declaration.py` | the freeze, and the check that code and document agree |
| `scripts/sur1/bindings/setup.py` | the mechanism: what a step may reach, and the refusal |
| `scripts/sur1/bindings/events.py` | what each declared event observes, does and may do once |
| `scripts/sur1/bindings/worldsink.py` | the world's two powers, performed against the live systems |
| `scripts/sur1/preflight.py` | `world_programs`, `world_program_freeze` and `event_blinding` |
| `docs/benchmarks/sur1-world-programs.v1.json` | the frozen declaration |
| `scripts/tests/test_sur1_world_programs.py` | every proof above, and no arm |
