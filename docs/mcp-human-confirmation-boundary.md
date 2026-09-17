# The MCP human-confirmation boundary

**Status:** closed. **Decision:** [ADR-0018](adr/0018-a-plan-confirmation-spends-a-human-approval.md).
**Scope:** the authority a plan confirmation stands on, across the browser, the orchestrator and
the MCP surface. Nothing was deployed, no AWS resource was touched, no model was called, and both
holdouts stay sealed.

## The defect

`confirm(case_id, plan_id)` over MCP treated an authenticated host call as proof that a named
human had approved that exact plan.

The chain was: MCP tool → `promisepatch.mcp.engine` → `POST /internal/intents/confirm` with the
shared `X-Service-Token` → `recovery.confirm_plan(worker_id=settings.surface_worker_id, ...)`. The
worker id came from `PP_SURFACE_WORKER_ID`, an environment variable. Nothing in that chain
established that a person was present, that they had been read the plan, or that they had agreed
to it. What committed was a case at `EXECUTING`, every blocked track escalated with its production
task held, one `APPLY_RECOVERY` step per automatically recoverable track, one `REQUEST_APPROVAL`
step per track whose customer had to be asked, and an audit row reading `authority =
HUMAN_APPROVAL, actor = maya`.

In the MCP architecture the model **is** the client. So the reachable statement was: a model that
can call the tool can produce durable evidence that a baker approved a plan they never heard.

## What actually protected the confirmation before, and what each of those was worth

Traced rather than assumed. Every production path that could move a case out of
awaiting-worker-confirmation into `EXECUTING`:

| Path | Credential | Who the record named | Established a human agreed? |
| --- | --- | --- | --- |
| `POST /api/conversation/confirm` | session cookie + CSRF token compared against the session row | `principal.worker_id`, read from that row | **Yes** |
| `POST /internal/intents/confirm` (the MCP process's only road to a case) | shared service token | `PP_SURFACE_WORKER_ID`, from configuration | **No** |
| `pp confirm-plan --case --worker --plan` | direct database access on the host | the `--worker` argument | Yes — an operator at a terminal |
| `promisepatch.orchestrator` | none of its own; it is an MCP client | whatever the surface decided | No |

And the defences that existed:

- **`reads_as_worker_confirmation`** (`orchestrator/policy.py`) — a closed literal grammar over
  the worker's turn, stricter than the domain. Real, and **in a client**. A different MCP host,
  or a direct authenticated call, never runs it. It stops our loop making the call; it cannot stop
  the call.
- **`ToolSelection` has no argument fields** — so a model cannot fabricate a plan identity; the
  host copies it out of `status`. This binds the yes to a plan. It says nothing about whose.
- **`plan_id`** (ADR-0010) — recomputed under the confirming lock, refuses a superseded plan.
  Again: which plan, not whose yes.
- **ADR-0015's server-side reading of a spoken yes** — browser only, because only the browser
  carried words.

So the product's own claims — `docs/p5-product-contract.md`'s *"a model cannot confirm a plan,
cannot confirm on a worker's behalf"*, and `docs/g8-adversarial-proof-map.md` §1.3's
**PROVEN** — were true of the orchestrator and untrue of the surface it talks to.

## The change

A confirmation now **spends** a durable approval it cannot write.

### The artifact

`plan_approvals` — governed, append-only, unique on `(case_id, plan_id)`:

| Column | What it is for |
| --- | --- |
| `case_id`, `plan_id` | what was agreed to. A plan identity covers the case version and every track including the untouched ones, so an approval cannot survive the case moving on and cannot be carried to another case |
| `approved_by` | the person, a FK to `workers` |
| `channel` | `BROWSER_SESSION` or `OPERATOR_CONSOLE`, checked by the database |
| `evidence` | the worker's verbatim words, or the control-press sentinel |
| `approved_at` | the server's clock |

Governed means writing one requires the audit event that authorises it, so the provenance is not
optional. Append-only means nothing edits it; there is deliberately no `consumed` flag, because
consumption is what the *confirmation's* own row records, and a second confirmation of one plan
fails on the case's state and the plan's identity rather than on a mutable marker.

### The structural boundary

`ApprovalChannel` has two members and neither is a service surface. The database's `CHECK` admits
exactly those two, and `test_migration_history.py` pins the migration's literal against the
runtime constant. **The MCP path cannot write an approval because there is no channel it could
name** — not because a route remembered to refuse it.

`recovery.confirm_plan` lost `worker_id` and gained `approval_id: UUID | None`. There is now no
parameter, on any function or request model on any transport, through which a caller can name the
person whose yes it is.

### The refusal order

Fixed, and part of the design. Under the case lock: case exists → case is `PLANNED` → the plan is
the one on offer → **then** the approval. A caller learns facts about the case before it learns
anything about authority, so a caller that has not got the case and the plan right learns nothing
about who has agreed to what.

### The contract change

`confirm` keeps its three arguments and changes what they mean. The tool description, the
`INSTRUCTIONS` a model reads at `initialize`, and `ConfirmResult` all now say that the call spends
a worker's agreement and can never create one; `ConfirmResult` gained `approved_via`, so a
conversation cannot report a confirmation without reporting where the authority came from, and
`confirmed_by` is the approving human rather than the configured surface worker. No misleading
version was kept for compatibility.

`POST /api/conversation/approve` is new: a signed-in worker records their approval **without**
carrying it out, so a conversation on another transport can. That is the production path by which
an MCP `confirm` legitimately succeeds. `POST /api/conversation/confirm` is unchanged from a
caller's point of view — same `202`, same counts, same speech, same ADR-0015 parsing, same
`NOT_A_PLAIN_YES` — and now records the approval it carries out.

## What the tests prove

`apps/backend/tests/test_human_confirmation_boundary.py`, 17 tests against real PostgreSQL, plus
additions to the browser, orchestrator, intent-API and protocol suites.

| Required property | Test |
| --- | --- |
| direct MCP `confirm` cannot manufacture approval | `test_a_direct_confirm_over_the_service_surface_cannot_manufacture_a_yes` — valid token, real case in `PLANNED`, the surface's own plan id: `403`, no approval row, no effect, case unmoved |
| no field can supply the missing authority | `test_no_field_on_the_confirm_request_can_add_the_missing_approval` — `worker_id`, `approved_by`, `approval_id`, `confirmed` each `422` on `extra="forbid"` |
| the absence is structural | `test_the_confirming_function_has_no_parameter_naming_a_person`; `test_the_service_surface_has_no_channel_it_could_record_an_approval_on` |
| valid human confirmation authorises the current plan | `test_an_approval_recorded_in_the_browser_is_spendable_by_the_service_surface` — refused before, accepted after, nothing about the request changed |
| approval cannot transfer to another case | `test_an_approval_cannot_be_carried_to_another_case` |
| stale / superseded fails | `test_an_approval_does_not_survive_the_case_moving_on`; `test_the_plan_the_case_moved_to_cannot_be_confirmed_on_the_old_approval` — neither direction is covered by the old yes |
| refusal order | `test_a_plan_the_case_is_not_offering_is_refused_before_approvals_are_discussed` |
| replay is idempotent | `test_a_redelivered_confirmation_reports_the_same_person_and_confirms_once`; `test_the_same_approval_spent_twice_carries_nothing_out_twice`; `test_recording_one_persons_yes_twice_records_it_once` |
| wrong principal / observer rejected | `test_a_worker_with_no_standing_on_a_case_cannot_approve_its_plan`; `test_an_observer_cannot_approve_a_plan`; `test_an_observer_session_cannot_approve_a_plan` (browser) |
| persistence does not lose or duplicate authority | `test_an_approval_outlives_the_process_that_took_it` |
| provenance is durable and auditable | `test_an_approval_and_the_confirmation_that_spent_it_are_two_audited_facts` — two rows, both `HUMAN_APPROVAL`, the second naming the approval it spent and the channel |
| the answer never names the surface worker | `test_the_answer_names_the_approver_and_never_the_configured_surface_worker` |
| browser confirmation still works | `test_a_confirmation_records_the_approval_it_carries_out`; `test_a_spoken_yes_is_recorded_as_the_words_the_worker_said`; `test_a_sentence_that_is_not_a_yes_records_no_approval_at_all` |
| the service token is not a way onto a person's channel | `test_the_service_token_buys_nothing_on_the_approving_route` |
| orchestrator respects the gate with its own check removed | `test_the_model_choosing_confirm_on_an_unapproved_plan_changes_nothing` — phase permits, grammar passes, real plan identity held, call made, refused, `PLANNED`, no effects, no approval row |
| the two surfaces differ only about authority | `test_the_two_transports_refuse_an_unapproved_plan_for_different_reasons` |

## What changed in claims that were previously stated too broadly

- `docs/g8-adversarial-proof-map.md` §1.3 carried **PROVEN** on client-side evidence only. An
  amendment is appended to that page rather than rewriting it, because its audit recorded
  truthfully what it found at the time.
- `docs/p5-product-contract.md` §*"A model cannot confirm a plan"* is now true of the surface and
  not only of our loop. The wording needed no change; what changed is that it is now enforced
  where a different client would meet it.
- `docs/p5.1` and `docs/p5.2`'s instruction rows record what those slices shipped and are left
  unedited. The instruction text they describe has since changed, and the current text is asserted
  by `test_the_instructions_state_the_boundary`.

## Remaining authority risk, stated rather than closed

1. **A compromised browser session is still a person's authority.** Anyone who can drive a
   signed-in worker's session can approve a plan as that worker. That is what a session is, and
   narrowing it would mean a second factor on every confirmation — a general identity mechanism
   this change deliberately is not.
2. **The operator console is trusted absolutely.** `pp confirm-plan --worker X` records an
   approval as X on the strength of holding the database. That was already true of physical
   attestation, which is a strictly larger authority.
3. **The refusal a worker hears over voice is generic.** `HUMAN_APPROVAL_REQUIRED` maps to the
   frozen `UNAUTHORIZED_SURFACE` tool code, whose deterministic sentence is *"I am not permitted
   to do that on this case."* True, and not actionable: it does not tell the worker to approve on
   their screen. The tool description tells the model, which is where the guidance can live
   without adding a code to a frozen set. A per-verb refusal sentence would fix it and was left
   out of this change.
4. **`/api/conversation/approve` has no control in the workspace yet.** The endpoint exists and is
   tested; the screen still offers only the combined confirm. Until a control is drawn, the
   two-channel flow is reachable by API and by the test suites, and the workspace's own
   confirmation path is the one a person uses.
5. **Nothing here is deployed.** The live host at `184.194.40.87.sslip.io` runs the previous
   behaviour until it is redeployed, and a redeploy needs migration `0009_human_plan_approval`
   applied first.
