# `SUR-1` execution revision `v3`: one database target, gated before the run is bought

**Neither published scored run is superseded, replaced, reinterpreted or re-run by anything in
this document.** `20260919T2020Z-scored` stands published, immutable and **inconclusive**.
`20260920T1100Z-scored-corrected` stands published, immutable and **incomplete** — all 27 of its
attempts failed in preparation, it reached no model and it spent nothing. Any run taken under this
revision is a *corrected execution beside both* and must be published as such. There are now two
prior runs and a third would be the third; none of them replaces another.

This is the disclosure `sur1-phase3-closeout.md` §8 requires before a change beneath
`scripts/sur1/` may be made: a named defect, a statement of what moved and in which direction, and
the re-frozen identity that covers the changed bytes. **No run was taken to produce it, no model
was called, no scorer ran, no AWS resource was touched, nothing was deployed and no holdout was
opened.**

| | |
|---|---|
| Revision | `v3` |
| Supersedes | **nothing** |
| Corrects | the measurement system only |
| Prior run preserved | `20260919T2020Z-scored`, INCONCLUSIVE, 24 `HARNESS_FAILURE` / 1 `INVALID` / 2 `SAFE_AND_COMPLETE` |
| Prior run preserved | `20260920T1100Z-scored-corrected`, INCOMPLETE, 27 `HARNESS_FAILURE`, 0 model calls |
| Prior run trees | both byte-identical at this revision — see §6 |
| `DRIVER_VERSION` | `1.1.1` → **`1.2.0`** |
| `implementation_sha` | `cb1686bf…` → **`c93b38a71296ba13744a7f0738394feaf3f2ae09ca61a939afa1ca3269e545f7`** |
| Frozen benchmark elements | **all unchanged** — see §5 |
| Scored preflight | 17 checks → **18** |

## 1. Why the second run measured nothing

The governed fixture load resolved its own database connection, inside the write, from
`promisepatch.config.get_settings()`. `pydantic-settings` falls back to `.env` in the working
directory, and this repository's `.env` points `PP_MIGRATION_DATABASE_URL` at a hosted Supabase
instance. The receivers resolved theirs from `SUR1_DATABASE_URL`, which was correct and local
throughout. Nothing joined the two.

All 27 attempts raised `PreparationError` inside `realisation._write` and were classified
`HARNESS_FAILURE`. The full record, with the verbatim refusal, is
[`sur1-corrected-scored-run-refusal.md`](../sur1-corrected-scored-run-refusal.md); nothing in it
is revised here.

**The hosted database was never opened.** The refusal is raised before `build_engine` is called,
so no connection was made to it and `reset_demo_state` — a `TRUNCATE` across forty-two tables —
never ran against it. That is the guard working, and this revision keeps it.

## 2. What the defect actually was

**It was not the invocation.** The refusal record attributed the run to an operator fault: it was
driven without `scripts/with_local_env.py`, and the error message names that remedy. That
attribution is true about the *proximate* cause and is the wrong place to stop, for the same
reason `v2` §2.2 corrected an attribution: a measurement system whose correctness depends on the
operator remembering a wrapper script has a defect, and the wrapper is not it.

**The defect is split resolution with no gate.** Two facts, and either alone would have been
harmless:

1. **The fixture load resolved its own target, at the moment of the write.** The value the
   preflight could have checked and the value the load used were two different lookups, taken
   minutes apart, against whatever the working directory held at each moment.
2. **No preflight question compared them.** `backend_build` comes closest and does not cover it:
   it asks the running API for its migration revision and checks the *signature* of the governed
   fixture load. It never resolves the load's connection string and never compares it with
   `SUR1_DATABASE_URL`.

This is structurally the same shape as the `v1` defect that `v2` §3.1 corrected, and as the `v2`
resume defect that `sur1-revision-v2-live-validation.md` corrected: the questions that were asked
were about reachability and capability, and the one question that would have refused the run early
was not asked at all.

## 3. The correction

### 3.1 The load is handed its database and resolves nothing

`scripts/sur1/bindings/database.py` is new and is the only place that says which database a run
installs into and reads out of. It parses connection strings into a `DatabaseIdentity` — backend,
host, port, database name, and **never a credential** — and it resolves the load's connection
once, in `installer_target()`.

`scripts/sur1/run.build` calls it before the preflight and puts the result on the world.
`LiveScenarioWorld.prepare` puts it on `WorldHandles`. `realisation.realise` builds the
`LiveInstaller` out of it. `realisation._write` **receives** it: `require_migration_database_url`
appears nowhere on that path any more, there is no second place a load could look one up, and a
load handed no target refuses rather than finding one. A test asserts that by parsing the module
rather than by reading it.

**Two credentials at one database is not a contradiction and is the normal case.** The load is the
owner's `TRUNCATE` inside one governed transaction and connects as the migration role; the
receivers only read and connect as the least-privileged application role. What is compared is the
server and the database on it, so `postgresql+asyncpg://promisepatch@…/promisepatch` and
`postgresql://promisepatch_app@…/promisepatch` are one database, and a check that called them
different would refuse every correct run. The DBAPI suffix is recorded and deliberately not
compared, because the load goes through SQLAlchemy and the receivers hand a bare DSN to `asyncpg`.

**There is deliberately no `SUR1_MIGRATION_DATABASE_URL`.** An override would be a way to make the
new check agree while every other product setting the load reads — the demo staff passwords it
seeds, the reset permission it checks — still came from a different file. That is the same defect
wearing a different hat. The one supported way to point this harness at the local stack remains
loading the local environment, which moves all of them together. Correctness does not depend on
it: without it the run is now **refused**, which §4 shows.

### 3.2 The gate, before authorisation

`database_identity` is added to `REQUIRED_CHECKS`, which is now **eighteen**. It compares three
readings, because two agreeing proves nothing if the third names somewhere else:

- what the run is configured for — `SUR1_DATABASE_URL` on the `BindingConfig`;
- what this world's receivers will actually read — `world.database.url`;
- what this world's fixture load will actually write to — `world.installer`.

A mismatch fails. A malformed or unrecognised URL fails, because *unknown* is the one answer a
gate may not treat as agreement. A world carrying no installer target fails. A migration URL that
could not be resolved at all is carried as a fault and reported here rather than raised during
assembly, because `build` reaches nothing and refuses nothing and the preflight is what says no.

**It opens nothing.** Every value is parsed from a string or read from settings. That is what
makes it a gate: `require` raises before `authorise` mints anything, before `drive` opens a run
directory, before a fixture is loaded, before a connection is dialled and before a model is
reached. A test replaces `socket.socket`, `socket.create_connection` and `socket.getaddrinfo` with
functions that fail the test, and the check still answers.

### 3.3 The load keeps its own refusal

`_write` still compares its target with the receivers' database and still calls
`ensure_reset_allowed`. Neither is redundant with the preflight. The preflight gates *a scored
run*; these gate *this write*, including on a development path that never went through a preflight
at all. A destructive write with one guard is a destructive write with one guard.
`PP_ALLOW_FIXTURE_RESET` remains the product's own statement by whoever configured the deployment,
and is what makes a hosted or otherwise non-local target fail safe rather than fail agreeably.

## 4. Reproduced, and corrected, against this machine's real configuration

Read-only. No connection was opened by either invocation.

```text
$ SUR1_DATABASE_URL=postgresql://promisepatch_app@127.0.0.1:55432/promisepatch \
    uv run python -c "<resolve both ends and ask database_identity>"
installer resolves -> postgresql://aws-1-eu-west-1.pooler.supabase.com:5432/postgres
receivers resolve  -> postgresql://127.0.0.1:55432/promisepatch
database_identity passed: False
```

The same command through `scripts/with_local_env.py`:

```text
installer resolves -> postgresql://127.0.0.1:55432/promisepatch
receivers resolve  -> postgresql://127.0.0.1:55432/promisepatch
database_identity passed: True
```

The first is the exact configuration `20260920T1100Z-scored-corrected` was driven under, asked
**before** the run rather than at the twenty-seventh write. The wrapper is a convenience that
makes the answer right; the gate is what makes a wrong answer refuse.

### 4.1 One explicit local target, proved at a non-`SUR-1` world

`DR01` — the dress rehearsal's own scenario, which is not a `SUR-1` scenario and consumes no
`SUR-1` outcome — was installed through the corrected seam against the live local stack, read back
out of the same database the installer was handed, and the Hollow Oak demo world restored
afterwards. No arm was constructed, no model was called, no armed event was fired and no benchmark
artefact was written. The result is in §7.

## 5. What did not move

Recomputed from the bytes on disk at this revision:

| Frozen element | Value | |
|---|---|---|
| manifest `safe-useful-recovery.v1.json` | `5718340fbd19aa8ba1aedc2327c07a934e22b773271e996f13f0e8d87e70e84c` | unchanged |
| baseline prompt `baseline-agent-prompt.v1.md` | `772ba46025620a1aea4742fac3971c5906ec3252036d07725434e0a89ce47cb1` | unchanged |
| scorer `score_safe_useful_recovery.py` | `SCORER_VERSION` `1.0.0` | unchanged |
| `PREDECLARATION_SHA` | `c53d267a0874d2e91456fdfacc23c86ebfc411f938cbe060ce958cb41d1e1927` | unchanged |
| `program_set_sha` | `88db566c13ef7a9865141583e5d918d43ff1b612b3311393c12af627ab1de649` | unchanged |
| `C01`–`C09` program hashes and world digests | all nine agree | unchanged |

`declaration.differences()` is empty. Ground truth, `the_point`, the arm definitions, the eleven
frozen actions, the tool surface, the attempt budget, the message ceilings, `RETRYABLE`,
`MAX_ATTEMPTS` and the blinding rules are **untouched**. No scenario was added, removed or
reworded. Both evaluation holdouts remain sealed.

`implementation_sha` moved, and it moved for exactly the reason that hash exists. `setup.py` and
`realisation.py` changed, and the new `database.py` was added to `IMPLEMENTATION_MODULES`: which
database a world is installed into decides whether the world an arm acts on is the world the
receivers read, and a world digest cannot see that — it is taken of the canonical snapshot before
the write, so a change that quietly pointed the load elsewhere would leave all nine digests
holding still while every reading became a reading about a world that was never installed. That is
what happened on 2026-09-20.

`world.py` and `run.py` also changed and are deliberately **not** in that list, on the rule `v2`
§4 set: they orchestrate preparation and driving, which is `DRIVER_VERSION`'s to cover, and it was
bumped.

### 5.1 One declaration statement was rewritten because it had become false

`NO_ARM_EXECUTED` said *one scored run has since been driven under it*. Two have. The sentence now
names both and says what each produced, for the reason `v2` §4.1 gives: a freeze whose honesty
rests on a statement that has become false is not a freeze. What the freeze actually claims — that
the nine programs were fixed before any outcome was seen — is unchanged and is still its first
sentence. `program_set_sha`, all nine program hashes and all nine world digests are unmoved.

## 6. Both prior runs are byte-identical

Hashed the way the freeze hashes a module set — path, then bytes, sorted, `\r\n` normalised:

| Run | Files | Digest | |
|---|---|---|---|
| `20260919T2020Z-scored` | 57 | `d599d644c6869fe527a32cfe240fe9a20433ed4a07679b02fbb597fecdc746ed` | unchanged |
| `20260920T1100Z-scored-corrected` | 57 | `e2a46c35b53902c817b9602999bb84f3df82cd3c7b425cb813551e7817364bca` | unchanged |

The second is pinned here for the first time. Both are asserted in
`scripts/tests/test_sur1_database_target.py`, which also counts the second run's verdicts out of
its own files: 27 of 27 `HARNESS_FAILURE`. If either digest fails, something edited a published
run, and the right response is to restore it and never to update the constant.

## 7. The proofs

In `scripts/tests/test_sur1_database_target.py`. None of them drives an arm, calls a model,
reaches AWS or opens a database. `C01`–`C09` were not driven to produce any of this.

| Claim | How |
|---|---|
| a connection string is read as a server and a database and never a credential | the rendered identity and its payload hold no password |
| two roles and two drivers at one database are one database | the local app DSN and the local migration URL compare equal |
| an omitted port is PostgreSQL's own default rather than a difference | `:5432` and nothing compare equal |
| a hosted database and the local one are not the same database | the refusal names both endpoints and no credential |
| a URL that cannot be read is refused rather than treated as agreement | seven malformed and unrecognised forms |
| the split target that lost the second run is now a failed check | the exact configuration of `20260920T1100Z-scored-corrected` |
| one database behind two roles passes, and says where the load resolved it | the detail names the source |
| a world whose receivers read elsewhere than the run was configured for is refused | the third reading |
| a world carrying no installer target may not be driven | `None` is a refusal, not a fallback |
| a load that could not resolve a database at all is reported, not raised | assembly reaches nothing and refuses nothing |
| **the comparison opens no socket** | `socket.socket`, `create_connection` and `getaddrinfo` all fail the test |
| the gate is one of the questions an authorisation is refused without | `REQUIRED_CHECKS`, before `output_directory` |
| the fixture load no longer resolves a database of its own | AST over `realisation.py`: no `require_migration_database_url` |
| a load handed no database refuses instead of finding one | `_write` with `target=None` |
| a load whose target disagrees refuses before it connects | `build_engine` and the socket module both fail the test |
| **the destructive write guard is still in front of the load** | `PP_ALLOW_FIXTURE_RESET` false, engine factory fails the test |
| the installer is built from the target the handles carry | `WorldHandles` → `LiveInstaller` |
| an unresolvable product setting comes back as a fault | `get_settings` raises, `installer_target` does not |
| both published scored runs are byte-identical | 57 files each, two pinned digests |
| the second scored run still says it reached no model | 27 `HARNESS_FAILURE`, counted out of the verdict files |
| this correction moved no frozen benchmark identity | all five, recomputed, plus `differences() == ()` |
| every world digest is the one that was published | nine, recomputed from the programs |

`scripts/tests/test_sur1_run.py` pins the composition tests to one known database, so that file
answers the same way on a developer's machine and on CI rather than reading whatever `.env` holds.

### 7.1 The live local proof

Run once, through `scripts/with_local_env.py`, against the running local stack. Not a benchmark
run: `DR01`, no arm, no model, no fired event, no run directory.

```text
installer identity : postgresql://127.0.0.1:55432/promisepatch
installer source   : promisepatch settings (PP_MIGRATION_DATABASE_URL)
receiver identity  : postgresql://127.0.0.1:55432/promisepatch
identities agree   : true
world installer is the resolved target : true
```

with the committed readback taken out of that database on either side of the install, and the
Hollow Oak demo world restored afterwards. The figures are in §7.2.

### 7.2 What the live proof read back

Read out of the live systems on either side of the install, not out of the installer's return
value. The worker was stopped for the install and the restore and brought back afterwards.

| | before install | after install | after restore |
|---|---|---|---|
| `fixture_state.fixture_name` | `hollow-oak` | **`hollow-oak+sur1-DR01`** | `hollow-oak` |
| `commitment_lines` | 6 | 6 | 6 |
| lines not `EXPECTED` | none | **1 `RECEIVED`** | none |

The install reported `applied: ["order-system:reset", "load:hollow-oak+sur1-DR01"]` at world
digest `609857b7ed129cc10816a3936af98886b3442c9cd6d0beb42dcb8309813fb6d7`, checked against the
rehearsal's own published declaration before the write, and armed `DR01`'s one declared reply on
`tg:1002` without firing it. The restore ran `pp reset-demo-state` (return code `0`, fixture
`hollow-oak`, 160 rows) and the order simulator's own `POST /admin/reset` (6 orders).

**The committed readback came out of the database the installer was handed.** The same
`DatabaseReader` the receivers use, at `postgresql://127.0.0.1:55432/promisepatch`, is what read
`hollow-oak+sur1-DR01` back — a row written inside the load's own transaction.

`reset_demo_state` also clears `cases`, and the local database held the canonical demo case before
this proof. It went to zero across the install and the restore, as `sur1-dress-rehearsal.md`
records that it does, and returned to one when the worker was brought back and re-provisioned it.
Stated rather than left out: the proof is not free of local side effects, it is reversible, and it
was reversed.

## 8. What is still open before a scored run may be bought

- **This revision has not been driven.** No run has been taken under `1.2.0`, and taking one is a
  different session's act under `sur1-phase3-closeout.md` §8.
- **The preflight has not been run end to end against the live stack under this revision.** §4
  exercises the new check in isolation and §7.1 exercises the corrected install; neither is the
  seventeen other questions answering against real bindings in one report.
- **The `C02` disclosure stands unchanged.** On `C02` the apparent-assent hazard is posed to the
  baseline and not to arms B and C, so a `C02` `consent_violations` reading for B and C may be
  vacuous rather than earned. Say it beside any `C02` safety count published from this benchmark.
  See [`sur1-consent-ingress.md`](../sur1-consent-ingress.md).
- **The two observations `v2` §6 recorded as not fixed are still not fixed.** `estimated_usd` is
  `unavailable` on every attempt and `run.json` carries `finished_at: null`. Neither affects a
  score.
- **Nothing outside the database URL was unified.** The fixture load still reads the product's
  settings for the reset permission and the seeded staff passwords. Under this revision a run
  whose settings point somewhere else is refused before it starts, so those cannot silently
  disagree with the scored target; but they are one file's values and `SUR1_WORKSPACE_PASSWORD` is
  another's, and nothing compares those two. Recorded here rather than closed.
