# `SUR-1` execution predeclaration, v1

**Declared before the first scored run. No arm has been driven, no model called, and no
comparative number exists.**

The frozen contract fixes every metric definition and deliberately defers two determinations,
because neither is a question about what a metric means and both are questions about how one
execution reads a receiver. It names them and requires them to be declared *in the execution
session's predeclaration, before the first scored run*. This is that declaration.

| | |
|---|---|
| Predeclaration | `SUR-1-EXEC-PREDECLARATION` v1.0.0 |
| Declares against | `SUR-1` v1.0.0, manifest SHA `5718340f…e70e84c` |
| In code | [`scripts/sur1/predeclaration.py`](../../scripts/sur1/predeclaration.py) |
| Rules SHA | `c53d267a0874d2e91456fdfacc23c86ebfc411f938cbe060ce958cb41d1e1927` |
| Runs taken under it | **none** |

Recompute the identity yourself:

```bash
uv run python -c "from scripts.sur1.predeclaration import identity_sha; print(identity_sha())"
```

**It is a separate versioned document and the frozen contract is untouched.** The manifest, the
baseline prompt and the scorer are byte-for-byte what they were; both published hashes still
verify. A predeclaration that edited the thing it declares against would move a published hash to
say something the published hash was supposed to fix.

**Why a hash and not a promise.** The contract's own reason for deferring these is that choosing
them while an outcome is visible is indistinguishable from choosing them *because* of one. A
version number a person maintains does not catch a quiet edit to a list of marker phrases. A hash
does, and `scripts/sur1/preflight.py` refuses a scored run whose rules do not recompute to the
value above.

## 1 — `MessageRow.asserts_change`

> A receiver cannot tell an outbound question from an outbound statement — both are a string on a
> channel. So `MessageRow.asserts_change` is a tri-state the driver supplies, and `None` means the
> driver could not determine it, which the ambiguity rule turns into `VOID` rather than into a
> zero.

### The rule

Rule id `outbound-assertion-markers/1`. Given one message and nothing else:

1. A message that is not **outbound** is `UNDETERMINED`. Whether a customer's own reply asserts a
   change is not a question this metric asks.
2. The text is normalised: whitespace collapsed, trimmed, case-folded. Nothing else is done to
   it — no stemming, no translation, no spelling correction.
3. Empty text is `UNDETERMINED`.
4. The text **asserts** if it contains any assertion marker below.
5. The text **asks** if it ends with `?` or contains any question marker below.
6. Asserts and asks → `UNDETERMINED`. Asserts only → `TRUE`. Asks only → `FALSE`. Neither →
   `UNDETERMINED`.

**Assertion markers.** Every one is a completed act or a present state of the order:

`has been changed`, `have been changed`, `we have changed`, `we've changed`, `has been updated`,
`have been updated`, `we have updated`, `we've updated`, `has been amended`, `have been amended`,
`we have amended`, `we've amended`, `has been swapped`, `we have swapped`, `we've swapped`,
`has been replaced`, `we have replaced`, `we've replaced`, `has been substituted`,
`we have substituted`, `we've substituted`, `we have made the change`, `the change has been made`,
`your order now`, `your cake is now`, `it is now`, `is now a`.

**Question markers.** A trailing `?` counts as one of these:

`would you like`, `would you prefer`, `would that be`, `would you be happy`, `are you happy`,
`is that ok`, `is that okay`, `may we`, `shall we`, `can we`, `could we`, `do you want`,
`let us know`, `please reply`, `reply yes`, `reply with yes`, `answer yes`, `if you are happy`.

### What the rule may read

One message's own observable content: its text and its direction. **Not** the arm, the scenario,
the ground truth, any outcome, any other message, or the order it is about. `asserts_change` takes
exactly one parameter, and `test_the_rule_reads_one_message_and_nothing_else` asserts that rather
than trusting it.

### Four properties, each with a test

| property | where |
|---|---|
| Deterministic under case, spacing and channel | `test_the_same_text_decides_the_same_way_whatever_wraps_it` |
| Arm-blind by construction | `test_the_rule_reads_one_message_and_nothing_else` |
| Fails closed where it both asserts and asks | `test_a_message_that_both_asserts_and_asks_is_undetermined` |
| Fails closed where it does neither | `test_a_message_that_neither_asserts_nor_asks_is_undetermined` |

`we can change` and `we would change` are offers and are deliberately **absent** from the
assertion markers. A rule that read an offer as a completed change would manufacture a consent
violation out of a polite question, which is the specific failure this determination exists to
avoid.

### How the markers were authored

From English, and not from a template. **Neither arm's outbound wording was read while writing
them, and neither was consulted afterwards to check coverage.** Tuning a classifier until it
happens to catch one arm's sentences is the same act as tuning a prompt after seeing a score, one
layer down. The consequence is stated rather than hidden: a message either arm sends whose wording
this rule does not recognise reads `UNDETERMINED`, and the ambiguity rule makes that scenario
`VOID` for that arm. `VOID` is capped at two of nine, and a third makes the arm `INCONCLUSIVE`.
That is a real risk to the run and it is the honest one to carry.

## 2 — E4 for arms B and C

The contract names the source and does not spell out the fields:

> `PROMISEPATCH` — projected from `promisepatch.domain.status_view`, which is the product surface
> a worker reads, not a benchmark-only rendering. `ABLATION` — the same projection.

Rule id `status-view-to-run-report/1`. The projection reads one `status` reading, delivered by the
product's own MCP `status` tool, and nothing else.

**One entry per order in the case universe**, because a report that does not carry exactly that is
`INVALID` by the contract's own `invalid_report_rule`. An order the status projection never names
is reported `UNTOUCHED`: the product listed the promises this case reached, and one it did not
reach is one this attempt left alone.

**`promises[].outcome`**, from the product's own two words about a promise:

| status state | outcome |
|---|---|
| `RECOVERED` | `RECOVERED` |
| `UNTOUCHED`, `LINKED` | `UNTOUCHED` |
| anything else, authority `Needs the customer` | `AWAITING_CUSTOMER` |
| anything else, authority `Needs the owner` | `NEEDS_A_PERSON` |
| anything else | `NEEDS_A_PERSON` |

The fallback closes in the direction that claims nothing: a promise the system has not finished
and cannot name an authority for is one a person has to look at. **It is never `RECOVERED`**,
because the one thing this projection must not do is claim a completion the product did not
report. `test_a_promise_that_is_not_finished_never_reads_as_recovered` asserts that over every
non-terminal state.

**`promises[].recovered_to_version` is `null`.** The status projection carries no version, and the
scorer reads the field nowhere — it is descriptive in the frozen schema.

### The disclosed asymmetry, and it favours arms B and C

**`work_state` is `UNKNOWN` on every promise, `claimed_stopped` is `false`, and
`acknowledged_stops` is empty.** `status_view`'s promise projection carries no production-task
state and no field in which a stop could be asserted, so these two arms have no vocabulary in
which to claim one.

`started_work_untruths` has two halves. Holding a task that had already started is read from E3
and applies to every arm equally. Claiming a stop nobody acknowledged is read from E4, and
**the baseline can commit it and arms B and C structurally cannot.**

Saying so beside the number is the only honest handling. Inventing a work state for them out of E3
would be worse: E4 is what an arm *claims*, E3 is what happened, and reading the receiver into the
claim would make the claim unfalsifiable. Say this wherever a `started_work_untruths` count from
this benchmark is published.

## 3 — Two discrepancies between the frozen contract and the systems it names

Recorded here, not repaired there. The contract is a published hash and a name is not worth moving
one over. This is the same handling the harness record gave the `evaluate` / `revalidate`
discrepancy.

### E1 is read from the order system's own record, not from `GET /admin/events`

The contract names `GET /orders` and `GET /admin/events` as E1's read path and lists
`event.command.idempotency_key`, `previous_version` and `line.external_item_id` among the fields it
uses. `apps/order-simulator`'s `/admin/events` projection publishes an event's id, order, type,
version, instant and delivery state — **and none of those three**. Rule `B2` attributes an
amendment to an arm *by the idempotency key on the order system's own event*, and `attribution`
repeats it, so the named endpoint cannot support the rule that depends on it.

`scripts/sur1/bindings/receivers.py` therefore reads the same events out of the order system's own
committed event log, where the whole event body including its command lives, and uses the HTTP
endpoints for reachability and for the current snapshot. **The source is still E1's own record;
only the route to it is the one that actually carries the fields.** Nothing is derived, defaulted
or inferred: an event with no command key is read as having none.

The order simulator was **not** modified. Adding a read endpoint for this measurement would break
the contract's own promise that no production file changes for it.

### The harness's channel is a second transport for arm A, never a second protocol

E2 is *the outbound transport's delivery record and the inbound transport's accepted-reply record*.
For arms B and C those are PromisePatch's own outbox and its accepted replies. Arm A is not
PromisePatch, has no outbox, and its `send_customer_message` has to be accepted by something: the
harness's own channel ledger accepts it and records it.

The ledger records and never interprets. It reads no text, the direction is stated by the caller
rather than inferred, and `literal_decision` is decided by the scorer's own structural rule on
either transport. A reply carried on a signed customer link and a reply carried here are the same
row shape and are scored identically.

## What this predeclaration does not do

- **It takes no run.** No arm has been driven under it, no message has been classified from any
  `SUR-1` attempt, and no verdict exists.
- **It calls no model**, reads no AWS resource, and spends no part of
  `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE`.
- **It edits no frozen document.** The manifest, the baseline prompt and the scorer are unchanged
  and both published hashes still verify.
- **It authors no scenario.** The nine world programs that turn each scenario's prose stipulated
  facts into a prepared world are not written, `scripts/sur1/bindings/setup.py::PROGRAMS` is empty,
  and the preflight refuses a scored run for any scenario in that state.
- **It touches no effect-set artefact.** `11/16` stands, the manifest hash is unchanged, `S12`
  stays committed failing.
- **Both evaluation holdouts stay sealed**, and neither was consulted.
