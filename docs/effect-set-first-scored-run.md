# The first scored run

**11 of 16.**

Taken on 15 September 2026 under the predeclared protocol
([`effect-set-run-protocol.md`](effect-set-run-protocol.md)), in a session that wrote no harness
code, against the frozen manifest `promisepatch-effect-sets` v1.0.0. Eleven scenarios matched
their frozen labels exactly. Five did not. Nothing was repaired, rerun or removed, and no
scenario was weakened, skipped, marked expected-to-fail or excluded.

| | |
|---|---|
| **Headline** | **11/16 exact effect-set matches** |
| Manifest | `promisepatch-effect-sets` v1.0.0 |
| **Manifest SHA** | `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` |
| Implementation SHA | `e81b5aa3af101847fdceb0f0af6cb515909d40b2`, working tree clean |
| Runner version | `1.0.0` |
| Immutable capture | [`docs/effect-sets/runs/20260915T163255509125+0000-scored.json`](effect-sets/runs/20260915T163255509125+0000-scored.json) |
| Console output | [`docs/effect-sets/runs/20260915T163255509125+0000-scored.log`](effect-sets/runs/20260915T163255509125+0000-scored.log) |
| Harness failures | 0 |
| Started / finished | `2026-09-15T16:32:55.509125+00:00` / `2026-09-15T16:35:22.926741+00:00` |

## The rule this was scored against

The locked roadmap's G8 addition:

> A scenario passes only on exact order-set equality at every declared checkpoint AND exact
> expected logical operational effects, including no unauthorized/duplicate effects. Missing,
> extra or misclassified orders/effects fail the entire scenario. Headline: **the first complete
> run against the original P5 labels, X/16 exact effect-set matches, whatever the result**.

The protocol's definition of a scored run, all three conditions of which held: the exact command
below with no scenario selection and no filter; all sixteen scenarios of the frozen manifest
executed; and invoked with intent to record, declared before return was pressed.

## The command, run once

```bash
uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py --scored
```

It exited `1`, because five scenarios failed. The capture records the argument vector as the
runner saw it: `["scripts/run_effect_sets.py", "--scored"]`.

**Environment.** Python 3.12.0 on Windows 10 (10.0.19045). The local disposable PostgreSQL from
`docker compose`, up and healthy; the `worker`, `api` and `mcp` containers not running, which is
the condition the protocol makes non-optional for the worker and which also keeps the suite's
own truncation from waiting on a held connection. The External Order System and the customer
channel are in-process fixtures, as every capture records: local replay is not proof of live
delivery. No model provider and no AWS credential was configured, and the capture records both
as `false`. Nothing reached a provider, AWS, a deployed host or the sealed holdouts.

## Per scenario

| | scenario | result |
|---|---|---|
| **S01** | One ingredient of one delivery did not arrive | **PASS** |
| **S02** | The whole delivery did not arrive | **PASS** |
| **S03** | A real physical exception that threatens nobody | **PASS** |
| **S04** | The substitute arrived and was unusable | **PASS** |
| **S05** | A recovery exists, is in stock, and the customer forbade it | **PASS** |
| **S06** | The customer said yes, then changed the order | **FAIL** |
| **S07** | The customer said yes, then the substitute was gone | **FAIL** |
| **S08** | A yes from the wrong person | **FAIL** |
| **S09** | Strawberries work | **PASS** |
| **S10** | The same yes, delivered twice | **PASS** |
| **S11** | Lena changed her cake before the delivery failed | **PASS** |
| **S12** | Ahmed changed his cake into the blast radius | **FAIL** |
| **S13** | Priya edited the order the plan was about | **FAIL** |
| **S14** | The cafe changed a standing order in the middle of it all | **PASS** |
| **S15** | The order system said yes and the worker died | **PASS** |
| **S16** | The worker restarted while the customer was thinking | **PASS** |

No scenario reached `HARNESS_FAILURE`. Every one of the sixteen executed to a verdict.

## Every diff, expected against observed

Each line is one `(order, effect kind)` pair at one declared checkpoint. Each of these five
scenarios fails **entirely** under the pass rule; there is no partial credit and none is claimed.

### S06 — the customer said yes, then changed the order

```
CONSENT_SETTLED/effects  ord-b/customer_message:  expected 2, observed 1
SETTLED/effects          ord-b/customer_message:  expected 2, observed 1
SETTLED/effects          ord-b/owner_escalation:  expected 1, observed 0
SETTLED/effects          ord-b/task_hold:         expected 1, observed 0
```

### S07 — the customer said yes, then the substitute was gone

```
SETTLED/effects  ord-b/owner_escalation:  expected 1, observed 0
SETTLED/effects  ord-b/task_hold:         expected 1, observed 0
```

### S08 — a yes from the wrong person

```
SETTLED/effects  ord-b/task_hold:  expected 1, observed 0
```

### S12 — Ahmed changed his cake into the blast radius

```
CONFIRMED/effects        ord-e/task_hold:  expected 1, observed 0
CONSENT_SETTLED/effects  ord-e/task_hold:  expected 1, observed 0
SETTLED/effects          ord-e/task_hold:  expected 1, observed 0
```

### S13 — Priya edited the order the plan was about

```
CONFIRMED/effects        ord-a/owner_escalation:  expected 1, observed 0
CONFIRMED/effects        ord-a/task_hold:         expected 1, observed 0
CONSENT_SETTLED/effects  ord-a/owner_escalation:  expected 1, observed 0
CONSENT_SETTLED/effects  ord-a/task_hold:         expected 1, observed 0
SETTLED/effects          ord-a/owner_escalation:  expected 1, observed 0
SETTLED/effects          ord-a/task_hold:         expected 1, observed 0
```

## What the shape of the failures is, and what it is not

Every difference in this run is an **effect**. Not one order is misclassified: all four
partitions match their frozen labels at every declared checkpoint in all sixteen scenarios,
including the five that failed. Every divergence is a count that is **lower** than the label —
a missing `task_hold`, a missing `owner_escalation`, a missing second `customer_message`. This
run produced no extra effect, no unauthorized effect and no duplicate effect anywhere in the
sixteen.

That is a description of the failures, not a defence of them. Under the pass rule a missing
effect fails the whole scenario exactly as an extra one would, and five scenarios failed.

The diffs above are the same ones published in [`effect-set-harness.md`](effect-set-harness.md)
before this run was taken, which is a fact about the harness reproducing, recorded here because
the protocol requires every diff to be published. It changes nothing about the count.

## What happens next, and what may not

Under the protocol and G8's correction process, resolution of these five is a separate, later
piece of work. Each candidate resolution — a corrected label under a separately versioned
manifest, or a change to the implementation — gets its own commit SHA and its own separately
published rerun, presented **beside** this headline and never in place of it.

- **11/16 is immutable.** It is never replaced by a repaired score, whatever a later run reaches.
- **The denominator is 16**, permanently: not the number that ran, not the number that produced a
  verdict, not the number wired at the time.
- **No failing scenario is removed**, weakened or marked expected-to-fail. All five stay in the
  suite, failing, and stay in the count.
- 16/16 is a **release condition** for a release candidate. That is a different sentence from this
  headline and it appears next to it, never over it.

## Disclosure

The labels and the suite are developer-authored, finite and public. This is not an independently
validated or held-out benchmark. Reproducibility makes these claims inspectable; it does not
prove universal correctness, real-world demand or return. The capture is committed and never
edited; this document references it by filename and by the implementation SHA it names.

The protocol's own status table recorded **"Scored runs so far: none"** and **"First-run headline
so far: none exists"**, and `effect-set-harness.md` records that no X/16 had been computed. Both
were true when written, in sessions that took no measurement. This run supersedes those two
sentences and nothing else in either document.

## Reproducing it

```bash
uv sync --frozen
uv run python scripts/run_effect_sets.py --check
uv run python scripts/bootstrap_local_env.py
docker compose up --detach --wait
docker compose stop worker
uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py --scored
```

No AWS credential, no model access, no messaging account and no hosted database. A rerun writes
its own capture beside this one; it does not touch this one.
