# G8 row 1: the demo-contract runner

**Date:** 2026-09-27. **Row:** G8 row 1, *demo-contract runner*.
**Verdict:** **CLOSED.**

[g8-evidence-packaging.md](g8-evidence-packaging.md) §3 left row 1 PARTIAL, for one reason: the
bullet's subject is a *runner*, and the frozen design says what a runner is. `ARCHITECTURE_PLAN.md`
§3 describes it as *"Demo-contract runner (`scripts/demo_contract.py`) | CLI | Executes the
storyboard as assertions, including a real worker restart"*. Nothing tracked was one. The owner
chose option (a), building it under G8. This page records what was built, what it does, and what
it does not.

**No product path changed.** The runner and its tests are two new files. No module under
`apps/backend/src`, `apps/order-simulator/src` or `packages/`, no deployment file, no manifest and
no frozen record moved. Product code at HEAD is identical to the release candidate
`4529a802e34e`: `git diff 4529a802e34e HEAD` over those trees, `docker/`, `deploy/` and `uv.lock`
is empty, and the only `pyproject.toml` difference is a ruff `extend-exclude`. So the deployed RC
and R1–R5 stand, as §6 of the packaging page said they would.

## 1. The literal requirement, and how each clause is met

> *"Demo-contract runner uses the new transport boundaries; no direct DB consent inserts. Fixture
> setup and fault injection are explicit operator actions."* — `new_roadmap.md` §11 G8

| clause | how the runner meets it | where it is proved |
|---|---|---|
| a runner that executes the storyboard as assertions | `scripts/demo_contract.py`: 49 named assertions from `PLANNED` to `SETTLED`, exit `0` only if every one holds | §4, §6, §7 |
| uses the new transport boundaries | the internal intent API (`status`, `confirm`), the signed customer approval link, and the External Order System's own HTTP read. Evidence comes from read-only database reads | §3 |
| no direct DB consent inserts | it holds no writer. Every evidence transaction is `SET TRANSACTION READ ONLY` before its first statement. The customer's answer arrives through the link route, which writes only a `customer-reply` inbox row the worker then decides | §6 tests 7 and 8; the `customer-link` transport header asserted on the processed row |
| fixture setup is an explicit operator action | the runner never seeds, resets or provisions. A world that is not the freshly restored canonical one is refused with exit `2` before any transport is called, and nothing is created | §6 tests 1 and 2 |
| fault injection is an explicit operator action | the runner never touches a process. It asks the operator to restart the worker, waits, then proves the restart changed nothing durable and that a different worker process did everything after it. An acknowledgement without a restart fails the run | §6 tests 3 and 5 |

## 2. The storyboard it executes

It is the storyboard G8's five deployed rehearsals were judged against,
[g8-rehearsal-preparation.md](g8-rehearsal-preparation.md) §3.1 (R1's shape). It is also frozen
effect-set scenario `S16`: `S01` through the worker's confirmation, then a restart while
`ord-b` waits, then the customer's yes. Of `S16`, the manifest says it *"passes only if the restart
is invisible in the result and visible in the worker identity that produced it"*.

Two parts of the older Phase 2 wording are **not** re-enacted, and neither is a gap the runner
could close:

- **Report and clarification are fixture setup in this product.** The worker's demo-case keeper
  and `pp restore-demo-world` both provision the canonical case to `PLANNED` through
  `intake.open_physical_exception` and `intake.answer_clarification`. The runner starts where
  every rehearsal started, at `PLANNED`, and asserts that partition through the intent API.
  Report and clarify over MCP are proved separately under G5, by independent-client replay.
- **The free-text reply ("Strawberries work" → one confirmation prompt) is not reachable through
  the deployed customer transport.** Under ADR-0021 the customer answers on the web, and the link
  writes only the parser's own two words. Telegram inbound is deliberately unbuilt. The free-text
  path is proved by the consent-protocol tests, not by this runner.

## 3. Interface

### Command

```bash
PP_INTERNAL_SERVICE_TOKEN="$(grep '^PP_INTERNAL_SERVICE_TOKEN=' docker/env/api.env | cut -d= -f2-)" \
  uv run python scripts/with_local_env.py -- \
  uv run python scripts/demo_contract.py --api http://127.0.0.1:48000 --order-system http://127.0.0.1:48100
```

The ports are this machine's published ones (`PROMISEPATCH_API_PUBLISHED_PORT`,
`PROMISEPATCH_ORDER_SIMULATOR_PUBLISHED_PORT`). `--timeout SECONDS` (default 120) bounds each
checkpoint.

### Inputs

| input | source | why there |
|---|---|---|
| `--api` | argument | PromisePatch's HTTP API |
| `--order-system` | argument | the External Order System, read independently of the mirror |
| `PP_DATABASE_URL` | environment (`host.env` through `with_local_env.py`) | the runtime role, used read-only for evidence |
| `PP_INTERNAL_SERVICE_TOKEN` | environment only | never an argument, so it never appears in a process list or transcript |

There is **no option** to create a fixture, approve a plan, restart a process, choose a provider
or mint a link.

### Exit codes

| code | meaning |
|---|---|
| `0` | `DEMO CONTRACT PASS (n assertions)`: every assertion held |
| `1` | `FAIL <assertion>: <detail>`: the first assertion that did not hold, named |
| `2` | `REFUSED <reason>`: a prerequisite is not met; nothing was called and nothing written |

### Transport boundaries used

| step | surface | authority it carries |
|---|---|---|
| read the plan | `POST /internal/intents/status` (`X-Service-Token`) | none: a read |
| carry out the person's approval | `POST /internal/intents/confirm` | can only *spend* a `plan_approvals` row a person left (ADR-0018). The response must name that person and channel |
| customer reads the question | `GET /api/customer/approval/{token}` | possession of the delivered link |
| customer answers `APPROVE` | `POST /api/customer/approval/{token}` | writes one `customer-reply` inbox row. The worker checks sender, state and deadline, then the literal parser decides |
| external readback | `GET /orders` on the order system | none: the system of record's own store |
| evidence | one `SET TRANSACTION READ ONLY` transaction per snapshot, product ORM models | none: the database refuses any write |

**The link comes from the delivered message**, the `MESSAGE_SEND` payload's `approval_url`, which
under the fake provider is the customer's device. The runner holds no link secret and cannot mint
one. The customer's channel address is compared inside SQL, and for the digest it is hashed there
too, so it never enters the runner. No address, token or link is printed.

## 4. Assertions

The digest scopes are those of the frozen reader `g8ev.py` (sha256 `c9731c8f…`,
[g8-rehearsal-r1.md](g8-rehearsal-r1.md) appendix), re-implemented read-only over the ORM models.
The frozen bytes are not imported and not edited.

| checkpoint | asserted |
|---|---|
| prerequisite (refuses, exit 2) | fixture `hollow-oak`; exactly one case, `PLANNED`; `pr-a` `AUTO_RECOVERABLE`/`R-PREAPPROVED`, `pr-b` `APPROVAL_REQUIRED`/`R-VISIBLE-ASK`, `pr-c`/`pr-d` `BLOCKED`/`R-NOSUB`; `pr-e`/`pr-f` `UNAFFECTED`; outbox, requests, decisions, replies and plan approvals all `0`; every order at version 1 |
| `PLANNED` | intent status answers with a plan on offer; it names the threatened four and `pr-e`/`pr-f` untouched; the order system holds every order at v1 |
| `CONFIRMED` | exactly one human approval of *this* plan, on `BROWSER_SESSION` or `OPERATOR_CONSOLE`; the intent confirm names that approver and channel; case `WAITING`; `pr-a` `RECOVERED`; `pr-b` `WAITING_FOR_CUSTOMER` with one request `SENT`; `pr-c`/`pr-d` `ESCALATED`, their tasks held and no others; one amendment and one message, each `DELIVERED` at attempt 1; `PLAN_APPROVED` and `PLAN_CONFIRMED` both `HUMAN_APPROVAL` by the approver; the order system holds `EXT-A` at v2 on `rv-raspberry-almond-4`; `EXT-B` still v1 on `rose-2` |
| restart | worker identities exist before it; the restart changed no case, track, effect, request, decision, approval, order, line, held task or unrelated digest |
| `CONSENT_SETTLED` | the delivered message carries a link; the link opens the question; the press is stored (`202`); one decision `APPROVE` by `LITERAL` from the asked channel; the inbox row `PROCESSED` via transport `customer-link`, one reply; `APPROVAL_DECISION_RECORDED` `HUMAN_APPROVAL` by `CUSTOMER cus-tomas`; ten `REVALIDATION_CHECK` rows, all passed, after the decision; `RECOVERY_REVALIDATED`, `RECOVERY_APPLIED`, `RECOVERY_COMPLETED` on `pr-b` under `HUMAN_APPROVAL` |
| `SETTLED` | case `RESOLVED`; `pr-a`/`pr-b` `RECOVERED`, `pr-c`/`pr-d` `ESCALATED`; the request `ANSWERED`; plan approvals still `1` |
| exactly once | three effects (two `ORDER_AMEND`, one `MESSAGE_SEND`), all `DELIVERED` at attempt 1, with three distinct idempotency keys; one case, one request, one decision, one reply; the order system holds `EXT-A` and `EXT-B` at v2 on the authored versions, and the mirror agrees |
| untouched | `EXT-C`…`EXT-F` at v1 in the order system and the mirror; zero audit rows, domain events, outbox payloads or requests attributed to `pr-e`/`pr-f` since the fixture loaded; `pr-e`/`pr-f` byte-identical to `PLANNED`; everything outside `pr-a`/`pr-b` identical from `CONFIRMED` to `SETTLED` |
| restart was real | all ten checks run by one worker process; the worker identities after the customer's answer are disjoint from every worker identity before the restart |

## 5. Explicit operator actions

| # | action | when | how the runner treats it |
|---|---|---|---|
| 0 | `uv run pp restore-demo-world --confirm destroy-and-restore` | before the runner | required; otherwise exit `2`, and the refusal text names this command |
| 1 | approve the plan as yourself: Approve in your own workspace, or `uv run pp confirm-plan --case … --worker maya --plan …` | the runner prints the case and plan, then waits for Enter | verifies exactly one `plan_approvals` row for that plan on a human channel. After a browser approval it carries it out through the intent API; after `pp confirm-plan` it observes that the console already did, and calls nothing |
| 2 | `docker compose restart worker` | after `CONFIRMED`, before the customer answers | verifies the restart changed nothing durable, and later that post-restart work carries only new worker identities |

## 6. Tests and results

**New tests,** in [test_demo_contract.py](../apps/backend/tests/test_demo_contract.py). They run
against the real application, the real simulator (its own ASGI application over its own SQLite
file, with its own webhook dispatcher delivering signed `order.updated` events back), and the
product's own `Worker` loop. The world is built by `demo_restore.restore_demo_world`, the
function behind `pp restore-demo-world`. The test operator is a double with exactly the two
powers the runner asks for.

| # | test | proves |
|---|---|---|
| 1 | `test_a_world_nobody_restored_is_refused_and_nothing_is_created` | a seeded world with no case: exit `2`, no operator request, **zero transport calls**, zero cases and zero outbox rows afterwards |
| 2 | `test_a_world_with_a_plan_already_approved_is_refused` | a used world: exit `2`, and the one existing plan approval is not added to |
| 3 | `test_the_storyboard_holds_with_a_browser_approval_and_a_real_restart` | exit `0`, 49 assertions; the operator asked for exactly `approve-plan` then `restart-worker`; the runner's only writes are one `POST /internal/intents/confirm` and one `GET`+`POST` on the approval link; it never used `/api/conversation/`; its output holds no link or address |
| 4 | `test_an_approval_already_carried_out_at_the_console_is_observed_not_repeated` | `pp confirm-plan` (`OPERATOR_CONSOLE`): exit `0`, and the runner made **no** intent confirm call |
| 5 | `test_a_restart_acknowledged_but_never_performed_fails_the_run` | the operator presses Enter without restarting: exit `1`, `FAIL RESTART: the work after the restart carries no identity …`, *"the same worker process did work on both sides"* |
| 6 | `test_an_approval_acknowledged_but_never_given_fails_and_confirms_nothing` | exit `1` at `CONFIRMED: exactly one human approval …`; no intent confirm call; zero plan approvals, the case still `PLANNED`, zero effects |
| 7 | `test_the_evidence_connection_refuses_a_write` | a reader substituted to `UPDATE cases` inside `read_world` is refused by PostgreSQL: *read-only transaction* |
| 8 | `test_the_runner_holds_no_writer_no_signer_and_no_process_control` | from the runner's own AST: sqlalchemy imports limited to `func`, `select`, `text`, `AsyncConnection`; no `subprocess`, `docker`, `os` or `promisepatch.worker`; no `.record`, `.ingest`, `.mint`, `.confirm_plan`, `.begin`, `.insert` or `.delete`; the only SQL text sent is `SET TRANSACTION READ ONLY` |
| 9 | `test_the_console_operator_shows_the_instruction_and_waits_for_the_person` | the console operator prints the instruction and returns only after Enter |

**Results.** Each suite was run one at a time, with no parallel runner. The compose `api`, `mcp`
and `worker` were stopped for the database runs.

| what | result |
|---|---|
| `pytest apps/backend/tests/test_demo_contract.py` | **9 passed** |
| the same, together with the neighbouring suites `test_demo_restore_command.py` (22), `test_customer_approval_link.py` (52), `test_intent_api.py` (57) and `test_browser_conversation.py` (69) | **209 passed**, 0 failed, exit `0`, 714 s |
| `ruff check`, `ruff format --check` on both files | clean |
| `mypy evals scripts` (group C) | no issues, 148 files |
| `mypy packages/promise-graph packages/order-contract apps/backend` (group A, tests included) | no issues, 299 files |
| `lint-imports` | 30 contracts kept, 0 broken |
| `pytest apps/backend/tests/test_demo_contract.py`, re-run on the committed bytes after the last edit | **9 passed** |

The committed bytes: `scripts/demo_contract.py` sha256
`4845ea25fed47fe3372d7cd9ebddc5f764df0d1f216b85fee80796e575b5c21d`, and
`apps/backend/tests/test_demo_contract.py` sha256
`18bf820531987a7f8c93551a2fbbb898fa17ead557290af41f8be3b2b9991281`. After the 209-test run
and the live run, two things were edited:

- in the runner, the module docstring's usage example and the wording of the refusal printed
  when `PP_DATABASE_URL` or `PP_INTERNAL_SERVICE_TOKEN` is missing, a branch no run took;
- in the test, a debug `print` that ruff's `T201` rejects.

No assertion, transport call or read changed, and the last row above is the re-run on the final
bytes.

**Deliberately not run:** the full backend suite (about an hour; nothing outside these two new
files changed), group B mypy (`apps/order-simulator`, untouched), the frontend, any effect-set or
SUR-1 run, and any model, AWS or Telegram call. GitHub CI remains the broad regression authority.

## 7. The live run

One run against the local compose stack, on 2026-09-27, with this session as the operator.

**Stack.**

- `promisepatch-backend:local` was rebuilt from HEAD at `09:43:38Z`. Its product code is
  identical to `4529a802e34e`. The image it replaced predated `b244e69` by six minutes, so it
  was not used.
- `api` and `worker` were started with `--no-deps` and a scratch compose override, never
  committed, setting `PP_LLM_PROVIDER=fake` and `PP_CUSTOMER_CHANNEL_PROVIDER=fake`. Both
  containers reported `fake` for both before the run and after the restart.
- The worker's demo-case keeper answered `DISABLED` and wrote nothing.
- The order system is the compose `order-simulator`, delivering its webhooks.

**Operator action 0, the fixture**, run from the host while `api` and `worker` were stopped:

```bash
PP_DEMO_SESSION_ENABLED=true uv run python scripts/with_local_env.py -- uv run pp restore-demo-world --confirm destroy-and-restore
```

The first attempt, without `PP_DEMO_SESSION_ENABLED`, was refused by the restore itself with exit
`2`, before anything was destroyed: *"This deployment does not serve the judge entry …"*. It is
the same kind of env union R1–R5 supplied. The second attempt exited `0`:

- `action: restored`;
- anchor `2026-09-27T09:44:20Z`;
- case `f7cbb88d-d373-572b-8f4d-23e769c24de4`, `PLANNED`;
- `orders: 6 reset in the external order system`;
- after it, outbox, requests, decisions, approvals and replies were all `0`;
- `ledgers: grew only`.

**Operator action 1, the approval**, at `09:45:37Z`. Signed in as `maya` and pressed Approve in her
browser session (`POST /api/auth/login` → `200`, `POST /api/conversation/approve` → `201`
`BROWSER_SESSION`), through a scratch client. The password came from the environment and was not
printed. Then Enter.

**Operator action 2, the fault**, at `09:46:06Z`: `docker compose restart worker`.

- The container's `StartedAt` moved from `09:44:38Z` to `09:46:08Z`.
- The log shows `worker.stop` for `68df81b9c95c:1:4147190e`, then `worker.start` for
  `68df81b9c95c:1:7cfdc8a3`.
- The container was healthy, with provider `fake`, before Enter was pressed.

**The command:**

```bash
PP_INTERNAL_SERVICE_TOKEN="$(grep '^PP_INTERNAL_SERVICE_TOKEN=' docker/env/api.env | cut -d= -f2-)"   uv run python scripts/with_local_env.py --   uv run python scripts/demo_contract.py --api http://127.0.0.1:48000 --order-system http://127.0.0.1:48100
```

**The output, verbatim** (framed by `date -u` and the exit code):

```text
started 2026-09-27T09:45:04Z
demo-contract runner 1.0.0
      case f7cbb88d-d373-572b-8f4d-23e769c24de4
PASS  PLANNED: intent status answers
PASS  PLANNED: a plan is on offer
PASS  PLANNED: status names the threatened four
PASS  PLANNED: status names pr-e and pr-f untouched
PASS  order system answers its own read
PASS  PLANNED: every order is at version 1 in the order system
      plan 9220b0c428e65f2952063c85a77362724eaab7347be81aa0e2e6dba62e50959a

OPERATOR ACTION [approve-plan]
Approve this plan as yourself, on a surface where you authenticate (ADR-0018). Either press Approve on the case in your own workspace, or run:
  uv run pp confirm-plan --case f7cbb88d-d373-572b-8f4d-23e769c24de4 --worker maya --plan 9220b0c428e65f2952063c85a77362724eaab7347be81aa0e2e6dba62e50959a
The runner never approves a plan; it carries out the approval you leave.
Press Enter once it is done.
PASS  CONFIRMED: exactly one human approval of this plan exists
      approved by maya via BROWSER_SESSION
PASS  CONFIRMED: the intent API carries out the person's approval
PASS  CONFIRMED: the confirmation names the approver and channel, not the service
PASS  CONFIRMED: case is WAITING
PASS  CONFIRMED: pr-a recovered without asking anyone
PASS  CONFIRMED: pr-b waits for its customer
PASS  CONFIRMED: pr-c and pr-d escalated to the owner
PASS  CONFIRMED: the tasks of pr-c and pr-d are held, and only theirs
PASS  CONFIRMED: one request SENT on pr-b
PASS  CONFIRMED: one amendment and one message, each delivered at attempt 1
PASS  CONFIRMED: approval and confirmation are HUMAN_APPROVAL by the person who approved
PASS  order system answers its own read
PASS  CONFIRMED: the order system itself holds EXT-A at v2 on the authored version
PASS  CONFIRMED: EXT-B is untouched until its customer answers
PASS  CONFIRMED: plan approvals are still exactly one
PASS  RESTART: the work so far was done by a worker process

OPERATOR ACTION [restart-worker]
Restart the worker process now, while the customer has not answered:
  docker compose restart worker
The runner does not restart anything; it checks afterwards that a different worker process did the rest.
Press Enter once it is done.
PASS  RESTART: the restart itself changed nothing durable
PASS  CONSENT: the delivered message carries an approval link
PASS  CONSENT: the link opens the question
PASS  CONSENT: the customer's APPROVE is stored by the link transport
PASS  SETTLED: case is RESOLVED
PASS  CONSENT: one decision, APPROVE, by the literal parser, from the asked channel
PASS  CONSENT: the answer arrived through the customer link and was processed
PASS  CONSENT: the decision is HUMAN_APPROVAL by the customer
PASS  CONSENT: ten revalidation checks, all passed, written after the decision
PASS  CONSENT: pr-b revalidated, applied and completed under HUMAN_APPROVAL
PASS  SETTLED: pr-a and pr-b recovered, pr-c and pr-d escalated
PASS  SETTLED: the request is ANSWERED
PASS  SETTLED: a customer's yes spent no worker approval
PASS  EXACTLY ONCE: three effects, two amendments and one message, all at attempt 1
PASS  EXACTLY ONCE: three distinct idempotency keys
PASS  EXACTLY ONCE: one case, one request, one decision, one reply
PASS  order system answers its own read
PASS  SETTLED: the order system holds EXT-A at v2 on the authored version
PASS  SETTLED: the mirror agrees on EXT-A
PASS  SETTLED: the order system holds EXT-B at v2 on the authored version
PASS  SETTLED: the mirror agrees on EXT-B
PASS  UNTOUCHED: EXT-C to EXT-F at v1, in the order system and in the mirror
PASS  UNTOUCHED: no message, write, hold or audit event is attributed to pr-e or pr-f
PASS  UNTOUCHED: pr-e and pr-f are byte-identical to PLANNED
PASS  UNTOUCHED: everything outside pr-a and pr-b is identical from CONFIRMED to SETTLED
PASS  RESTART: every check was run by one worker process
PASS  RESTART: the work after the restart carries no identity the work before it carried
      2 worker identity before the restart, 1 after, disjoint
DEMO CONTRACT PASS (49 assertions)
exit=0
ended 2026-09-27T09:46:34Z
```

**Cross-checked from outside the runner**, read-only:

- the case holds exactly 10 `REVALIDATION_CHECK` rows, and every one has
  `provenance.worker = 68df81b9c95c:1:7cfdc8a3`, the post-restart instance;
- the `api` and `worker` logs since `09:44Z` hold zero lines naming Bedrock or a model
  invocation;
- the runner's output holds zero links, tokens or `tg:` addresses.

The run was taken with the runner as it stood before the two non-executing edits described in §6.

## 8. Limitations

- **`pr` is not yet shown green on a SHA that contains the runner.** Nothing was pushed.
  [g8-evidence-packaging.md](g8-evidence-packaging.md) §6 made that a condition of building it,
  and it passes to the freeze session (rows 13 and 15). That session dispatches `pr` on a SHA that
  must contain these two files and be product-identical to `4529a802e34e`.

- **Local only.** No `--deployed` mode was built and nothing ran against AWS. The deployed
  storyboard with real Telegram out and a real web answer in is R1–R5, on `4529a802e34e`.
- **The fake customer channel.** Locally the link is read from the delivered outbox payload. It
  says nothing about Telegram delivery, which R1–R5 proved.
- **The report and the clarification are fixture setup** (§2). The free-text apparent-assent path
  is not reachable through the deployed transport and is not re-enacted.
- **Not scheduled in CI.** The runner needs a running stack and an operator, so no workflow
  calls it. Its tests are ordinary `integration` tests and run where those run.
- **It proves one storyboard, once per invocation.** It measures demo readiness, not
  reliability, and it is not the effect-set harness, whose 16 scenarios keep their own record.
