# The G8 head-of-line measurement

*Taken 2026-09-16. Nine runs, three arms, one invocation, one command. **Both delayed arms miss
the gate.** `H_representative = 1545.8 ms` and `H_treatment = 8173.4 ms` against a threshold of
`H ≤ 1000.0 ms` that was fixed before the harness existed and was not moved. §8 of the
predeclaration predicted exactly this, in writing, before any number existed, and its prediction is
quoted in full beside the result.*

*No scheduling correction was made and no production code was changed. Whether a fail obliges the
roadmap's conditional *"smallest scheduling correction"* is the owner's decision after reading this
document. No AWS resource was touched, no model was called, no manifest, fixture label or frozen
document was changed, and both holdouts stay sealed.*

---

## 1. What was run, and against what

| | |
|---|---|
| **protocol** | [g8-head-of-line-predeclaration.md](g8-head-of-line-predeclaration.md), as amended |
| **amendment commit** | **`7cb188c4ded0ade34b1c766d3fb6cb0905b65c5a`** — Amendment 1, the representative arm |
| **implementation SHA** | **`7cb188c4ded0ade34b1c766d3fb6cb0905b65c5a`**, recorded independently in all nine captures |
| **working tree** | clean, asserted by the harness and recorded per capture as `working_tree_clean: true` |
| **runner version** | `1.1.0` |
| **invocation id** | `d98a80eb-96f9-4098-9623-ea66ae5843e8` |
| **arms** | `control` 0 ms, `representative` 1 500 ms, `treatment` 8 000 ms |
| **runs** | 9, alternating `C R T C R T C R T`, three per arm |
| **model calls** | **0.** The provider is `FakeSemanticProvider` plus an injected sleep |
| **AWS calls** | **0** |

The amendment and the implementation carry the same SHA because the amendment was committed
complete — document, harness and tests together — before the harness was invoked at all. The
predeclaration's own rule is that a protocol is fixed before the run, and the git history shows the
order: `7cb188c` is the amendment, and this document is everything that came after it.

### The command, verbatim

```bash
uv run python scripts/with_local_env.py -- uv run python scripts/run_head_of_line.py
```

That is §7's one command, unchanged by Amendment 1. It performed nine runs where before the
amendment it would have performed six.

### The environment, read off the machine at run time

| | |
|---|---|
| platform | `Windows-10-10.0.19045-SP0` |
| Python | `3.12.0` |
| PostgreSQL | `PostgreSQL 16.15 on x86_64-pc-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit` |
| database | `127.0.0.1:55432/promisepatch` — the local `docker compose` PostgreSQL, on loopback |
| worker processes | 1 |
| order system | not used; `FakeEffectAdapter`, `fetch_order=None` |
| fixture | `hollow-oak`, reset before every run, 160 rows, digest `8c58aa87057d6c3f…` |

**Two disclosures about the environment**, neither of which §6 forbids and both of which are
recorded here rather than left to be found:

* The compose `api`, `mcp` and `worker` containers were **stopped**, which §6 requires. The
  `frontend` and `order-simulator` containers were **up and idle**. §6 names the three that must be
  down, and neither of the other two touches the database or the worker's step loop; the harness
  constructs its worker with `FakeEffectAdapter` and `fetch_order=None`, so no run could reach the
  simulator even had it wanted to.
* One untracked file, `REMAINING_WORK_ASSESSMENT.md`, was present in the working directory before
  the run and was **moved out of the repository** for its duration and put back afterwards, so that
  the tree the captures record was the clean `HEAD` §10's first void condition requires. Nothing
  tracked was moved, nothing was deleted, and no commit contains it.

---

## 2. The raw captures

Nine files, committed unedited, one per run, in the order they were written:

| # | arm | `D` | capture |
|---|---|---|---|
| 1 | `control` 1 | 0 ms | [`docs/head-of-line/runs/20260916T183405449190+0000-measurement-control-1.json`](head-of-line/runs/20260916T183405449190+0000-measurement-control-1.json) |
| 2 | `representative` 1 | 1 500 ms | [`docs/head-of-line/runs/20260916T183413812154+0000-measurement-representative-1.json`](head-of-line/runs/20260916T183413812154+0000-measurement-representative-1.json) |
| 3 | `treatment` 1 | 8 000 ms | [`docs/head-of-line/runs/20260916T183428485765+0000-measurement-treatment-1.json`](head-of-line/runs/20260916T183428485765+0000-measurement-treatment-1.json) |
| 4 | `control` 2 | 0 ms | [`docs/head-of-line/runs/20260916T183435743498+0000-measurement-control-2.json`](head-of-line/runs/20260916T183435743498+0000-measurement-control-2.json) |
| 5 | `representative` 2 | 1 500 ms | [`docs/head-of-line/runs/20260916T183444227015+0000-measurement-representative-2.json`](head-of-line/runs/20260916T183444227015+0000-measurement-representative-2.json) |
| 6 | `treatment` 2 | 8 000 ms | [`docs/head-of-line/runs/20260916T183459531143+0000-measurement-treatment-2.json`](head-of-line/runs/20260916T183459531143+0000-measurement-treatment-2.json) |
| 7 | `control` 3 | 0 ms | [`docs/head-of-line/runs/20260916T183506885041+0000-measurement-control-3.json`](head-of-line/runs/20260916T183506885041+0000-measurement-control-3.json) |
| 8 | `representative` 3 | 1 500 ms | [`docs/head-of-line/runs/20260916T183515229684+0000-measurement-representative-3.json`](head-of-line/runs/20260916T183515229684+0000-measurement-representative-3.json) |
| 9 | `treatment` 3 | 8 000 ms | [`docs/head-of-line/runs/20260916T183531551242+0000-measurement-treatment-3.json`](head-of-line/runs/20260916T183531551242+0000-measurement-treatment-3.json) |

The two files beside them labelled `smoke` are §12's throwaway run from the building session. §9
reads captures labelled `measurement` and no others, and this arithmetic did exactly that.

---

## 3. The void conditions, checked before any wait was computed

§10 permits a void only for a condition that makes the record untrustworthy, and only when it is
identified **before any wait has been computed or read**. All five were checked first, from the
captures' structural fields alone. **None fired.** No run failed, either: all nine stopped on
`all-tracked-settled` well inside the 120-second bound, and every capture's `failures` list is
empty.

| § | condition | what the captures show |
|---|---|---|
| 10.1 | tree not the clean `HEAD` | `working_tree_clean: true` and the same `implementation_sha` in all nine |
| 10.2 | a second worker touched the run | the preflight found the delayed case's first step `PENDING` with `attempts: 0` after its two quiet seconds, in all nine; and every `WORKFLOW_STEP_EXECUTED` row in each run carries that run's **single** worker identity |
| 10.3 | the arrangement did not hold | in all nine, the semantic step was `PENDING`, was the oldest claimable row, and all eight tracked rows were `PENDING` when `T0` was recorded |
| 10.4 | wrong number of provider calls, or the wrong hold | exactly **one** call in every run; every control hold exactly `0.0`; every delayed hold at or about its `D` — see below |
| 10.5 | a capture internally inconsistent | every tracked row is terminal and carries all three of §5's instants, and no `started_at` precedes its own `created_at` |

### The one judgment §10.4 required, and how it was made

The recorded holds:

| arm | run 1 | run 2 | run 3 |
|---|---|---|---|
| `representative`, `D` = 1 500 ms | 1 512.2 | **1 492.6** | 1 510.2 |
| `treatment`, `D` = 8 000 ms | 8 001.5 | 8 015.1 | 8 013.1 |

§10.4 voids a run for *"a hold materially shorter than `D`"*. It says **materially**, not
*shorter*, and leaves the word to judgment. One hold, `representative` run 2, is 7.4 ms short of
its `D` — **0.49 %** of it, and 0.74 % of the threshold. It sits inside the same ±15 ms scatter
every one of the other five delayed runs shows in the *other* direction, which is the resolution of
`asyncio.sleep` against a performance counter on this machine and not a delay that failed to
happen. **It is not materially shorter, and no run is voided.**

Two things about how that call was made, stated because the whole point of this protocol is that
nobody has to take them on trust. It was made **before any wait, median or `H` had been computed**
— the void check ran first, on structural fields only, exactly as §10 requires. And it could not
have changed a verdict in any case: 7.4 ms is smaller than the smallest margin in this document by
two orders of magnitude.

---

## 4. §9's arithmetic, worked

`wait_ms(r, i) = started_at − created_at` and `service_ms(r, i) = done_at − started_at`, both from
the database's own clock, written by production code into columns the product already keeps (§5).
No instant in this section came from the harness.

### 4.1 Every raw `wait_ms`, in milliseconds

Eight tracked items — each unrelated case's `BEGIN_INTERPRETATION` row — across nine runs. Nothing
is missing: every tracked row in every run was served and settled, so §10's `+infinity` rule and
its `0.0`-for-a-missing-control rule were implemented and never had anything to apply to.

| # | item | C r1 | C r2 | C r3 | **C med** | R r1 | R r2 | R r3 | **R med** | T r1 | T r2 | T r3 | **T med** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | the deck oven is down | 720.9 | 659.6 | 678.1 | **678.1** | 2195.1 | 2285.7 | 2212.0 | **2212.0** | 8670.7 | 8773.8 | 8729.7 | **8729.7** |
| 2 | the convection oven is down | 781.7 | 687.9 | 714.2 | **714.2** | 2260.0 | 2303.0 | 2252.0 | **2260.0** | 8722.7 | 8828.1 | 8760.7 | **8760.7** |
| 3 | the butter spoiled | 813.3 | 720.9 | 790.6 | **790.6** | 2300.4 | 2320.8 | 2286.2 | **2300.4** | 8750.8 | 8884.7 | 8784.6 | **8784.6** |
| 4 | the mascarpone spoiled | 856.1 | 736.7 | 844.5 | **844.5** | 2342.7 | 2357.8 | 2323.9 | **2342.7** | 8777.7 | 8944.5 | 8833.0 | **8833.0** |
| 5 | the lemon curd spoiled | 903.7 | 767.3 | 901.7 | **901.7** | 2395.5 | 2426.2 | 2361.3 | **2395.5** | 8802.8 | 8999.6 | 9078.5 | **8999.6** |
| 6 | the dark chocolate spoiled | 934.9 | 846.5 | 960.6 | **934.9** | 2467.0 | 2482.5 | 2379.9 | **2467.0** | 8832.6 | 9080.4 | 9171.6 | **9080.4** |
| 7 | the ladyfingers spoiled | 992.8 | 903.6 | 1022.8 | **992.8** | 2541.6 | 2535.7 | 2416.2 | **2535.7** | 8880.4 | 9156.3 | 9199.9 | **9156.3** |
| 8 | the cream in the walk-in went off | 1047.2 | 960.4 | 1098.7 | **1047.2** | 2713.7 | 2582.0 | 2453.3 | **2582.0** | 8912.5 | 9220.6 | 9227.5 | **9220.6** |

The control column rises down the table for the reason §9 predicted before any number existed:
*"simple queue position — item 8 waits for seven predecessors' service even when nothing is
delayed"*. Subtracting the control median is what removes it.

### 4.2 `added_ms` and `H`

```
added_ms_representative(i) = W_representative(i) - W_control(i)
added_ms_treatment(i)      = W_treatment(i)      - W_control(i)
```

| # | item | `W_control` | `W_representative` | **added** | `W_treatment` | **added** |
|---|---|---|---|---|---|---|
| 1 | the deck oven is down | 678.1 | 2212.0 | **1533.9** | 8729.7 | **8051.6** |
| 2 | the convection oven is down | 714.2 | 2260.0 | **1545.8** | 8760.7 | **8046.5** |
| 3 | the butter spoiled | 790.6 | 2300.4 | **1509.8** | 8784.6 | **7994.0** |
| 4 | the mascarpone spoiled | 844.5 | 2342.7 | **1498.2** | 8833.0 | **7988.5** |
| 5 | the lemon curd spoiled | 901.7 | 2395.5 | **1493.8** | 8999.6 | **8097.9** |
| 6 | the dark chocolate spoiled | 934.9 | 2467.0 | **1532.1** | 9080.4 | **8145.5** |
| 7 | the ladyfingers spoiled | 992.8 | 2535.7 | **1542.9** | 9156.3 | **8163.5** |
| 8 | the cream in the walk-in went off | 1047.2 | 2582.0 | **1534.8** | 9220.6 | **8173.4** |

```
H_representative = max{ 1533.9, 1545.8, 1509.8, 1498.2, 1493.8, 1532.1, 1542.9, 1534.8 }
                 = 1545.8 ms        (item 2, "the convection oven is down")

H_treatment      = max{ 8051.6, 8046.5, 7994.0, 7988.5, 8097.9, 8145.5, 8163.5, 8173.4 }
                 = 8173.4 ms        (item 8, "the cream in the walk-in went off")
```

---

## 5. The verdict, per arm, against the unchanged threshold

§8's threshold is `H ≤ 1000.0 ms`, taken from `IDLE_INTERVAL` — the worker's own constant for how
long ready work may reasonably sit. §8 was not edited by Amendment 1 and was not edited by this
session. No rounding was applied before the comparison.

| arm | `D` | what the arm is for | `H` | vs 1000.0 ms | **verdict** |
|---|---|---|---|---|---|
| `control` | 0 ms | establishes the baseline the other two are subtracted from | — | — | *baseline, not a result* |
| `representative` | 1 500 ms | answers whether this matters at a latency the real model has been recorded at | **1545.8 ms** | `1545.8 > 1000.0` | **FAIL** |
| `treatment` | 8 000 ms | isolates whether delay propagates one for one | **8173.4 ms** | `8173.4 > 1000.0` | **FAIL** |

### §8's prediction, quoted beside the fail

Written before the harness ran and before any instant existed:

> Reading `Worker.run_once` (§3), the five awaits are sequential and `_execute_one_step` holds the
> provider call inside the second of them. Nothing in that loop is concurrent, and nothing claims a
> second step while the first is in the provider. **The expected outcome of this measurement is
> therefore a fail**, with `H` near 8 000 ms.

And §14.4, restating it per arm, also before any number existed: the representative arm
**predicted fail, with `H_representative` near 1 500 ms**; the treatment arm **predicted fail, with
`H_treatment` near 8 000 ms`**.

**Both predictions hold, and they hold tightly.** `H_representative` is 45.8 ms above its injected
delay and `H_treatment` is 173.4 ms above its own — 3.1 % and 2.2 % respectively. The `added_ms`
column varies by 52.0 ms across the eight items in the representative arm and 184.9 ms in the
treatment arm, against delays of 1 500 and 8 000 ms. **Delay propagates one for one to every item
queued behind it**, which is the treatment arm's whole job, and the representative arm shows it
doing so at a latency the real model has actually been recorded at rather than at a chosen one.

### What the representative arm adds that the 8 000 ms arm could not

This is the reason Amendment 1 exists, and the result is what it was added to produce. The
treatment arm alone establishes that an 8-second hold costs unrelated work 8 seconds — true, and
uninformative about operation, because nothing in this product has ever taken 8 seconds. The
representative arm says the operational thing: **at 1 500 ms — rounded up from the two
`interpret_utterance` calls Nova 2 Lite actually answered on the deployed host, 1 487 ms and
1 444 ms — unrelated ready work waits about 1.5 seconds longer than it otherwise would, which is
over the worker's own definition of "promptly" by more than half a second.**

---

## 6. `service_ms`, published beside the gate and not gated

§5 publishes each item's own execution separately so that a reader can see it was not folded into
the gated number. Over all 24 tracked items per arm:

| arm | n | min | median | max |
|---|---|---|---|---|
| `control` | 24 | 11.8 ms | 16.1 ms | 26.0 ms |
| `representative` | 24 | 12.3 ms | 16.4 ms | 22.8 ms |
| `treatment` | 24 | 11.7 ms | 15.6 ms | 28.8 ms |

**Service time is flat across all three arms.** The items themselves did not get slower; they
waited longer. That is what makes the number in §4.2 queueing rather than execution, which is
exactly the distinction head-of-line blocking is about.

Corroborating it from the other side: in `representative` run 1, the delayed case's own
`INTERPRET_SEMANTICALLY` step was claimed at `18:34:10.954452` and settled at `18:34:12.562732` —
1 608.3 ms of service, into which the 1 512.2 ms hold fits with the step's ordinary work around it.
The delay went where §3 said it would.

---

## 7. What this result does and does not establish

§11 of the predeclaration listed eight things this measurement does not establish, before any
number existed. All eight stand, unamended, and the most load-bearing of them are worth repeating
now that a number exists to be over-read:

1. **It does not measure a real model's latency.** No Bedrock call was made in any of the nine
   runs. `D` is a chosen number, and the representative arm's 1 500 ms is *derived from* recorded
   calls, not *made by* one.
2. **It does not measure the deployed host.** One in-process worker against local PostgreSQL. The
   deployment is a container against RDS across a network. What carries over is the shape of the
   scheduling, which is the same code.
3. **It says nothing about more than one worker.** `FOR UPDATE SKIP LOCKED` means a second replica
   takes different rows. The measured configuration is the deployed one — one replica.
4. **It covers the worker's step loop only.** The orchestrator's `select_tool` call runs in a
   separate client process with no durable queue behind it.
5. **It is not a latency SLA.** Eight items, three runs an arm, one machine, one fixture.
6. **It does not establish that any correction is needed, or which one.**

To which this session adds one more, specific to the amendment:

7. **The representative arm's figure is a defensible reading of the evidence, not the only one.**
   §14.3 records the derivation that was available and was not taken — the 50-call benchmark's
   end-to-end p50 of 818 ms, and the 20 `interpret_utterance` calls behind it whose end-to-end
   median is 903.5 ms — and says plainly that taking it would have given roughly 900 ms and,
   under one-for-one propagation, would have predicted a pass. It was written down before the run
   for exactly this moment. **A reader who prefers that derivation should read this arm as saying
   that the added wait tracks `D`**, which the two arms together establish across a factor of five
   and change, **and substitute their own `D`.** The threshold would then be the only question, and
   the threshold is 1000.0 ms either way.

### What it does to the proof map

[g8-adversarial-proof-map.md](g8-adversarial-proof-map.md) §4 recorded this requirement
**UNPROVEN**, on the ground that *"no run capture, document, script or test records the
measurement"*. Nine run captures, a protocol, a harness, a test module and this document now do.
That audit document is **left unedited**, as this repository leaves audit records of their own
moment unedited; what it says was true when it was written, and this document is the thing that
answers it.

---

## 8. What was not done

* **No scheduling correction was made, and no production code was changed.** Nothing under
  `apps/backend/src/` differs by one byte from `7cb188c`. The roadmap's conditional —
  *"make the smallest scheduling correction only if observed responsiveness misses the gate"* — is
  now reached, on both arms, and **the decision is the owner's** after reading this. §11.6
  declined to design that correction before the measurement and this document declines to design it
  after.
* **No run was re-run, replaced, discarded or excluded.** All nine are published. There was no
  best-of and no seventh, eighth or tenth run.
* **No threshold moved.** §8 is byte-identical to what it was before Amendment 1 and before this
  measurement.
* **No manifest, fixture label or frozen document was changed.** The immutable 11/16 effect-set
  headline is untouched, and both holdouts stay sealed.
* **Nothing was deployed and no AWS resource was touched.** `aws_calls: 0` and `model_calls: 0` in
  every capture.
* **No test was weakened, skipped, xfailed or deselected.** `scripts/tests/test_run_head_of_line.py`
  gained three tests and two assertions with Amendment 1, and lost none.

**The owner's decision on that conditional is recorded separately, and this document is not edited by it:** [g8-head-of-line-disposition.md](g8-head-of-line-disposition.md) — the correction is declined.
