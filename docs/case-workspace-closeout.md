# The case workspace — the last G5 item carried into G7, and why it is closed

*Three obligations were carried forward from the G5 closeout. Two have their own record —
[the bounded withdrawal](bounded-withdrawal.md) and
[the classifier removal](customer-intent-classifier-removal.md). This is the third, and it is the
one that had no closeout record of its own, which is how two committed documents came to disagree
about it.*

---

## 1. The disagreement this resolves

Two durable statements in this repository contradicted each other.

| | says |
|---|---|
| [`p7.3-visual-acceptance.md`](p7.3-visual-acceptance.md) §6 | finishing the case workspace is *"substantially closed by P7.3's implementation and accepted here"* |
| [`bounded-withdrawal.md`](bounded-withdrawal.md) §9, [`customer-intent-classifier-removal.md`](customer-intent-classifier-removal.md) and `CLAUDE.md` | it *"is still the other G7 obligation"* |

Neither of the later two names a criterion the workspace fails. Both are slices that did not touch
the frontend and carried the three-item list forward as it was handed to them — the withdrawal was
genuinely open when the first of them was written, and the workspace travelled beside it in the
same sentence. **Nothing was measured and found wanting; the list was copied.**

This page decides it the only way that is not bookkeeping: against the frozen roadmap, against the
current source, and against tests that run today.

## 2. What the obligation actually was

The roadmap's September 18 cutoff names it in one clause — *"Move bounded withdrawal (fifth tool),
classifier removal after its recorded decision, and **case-workspace finishing** to named MUST
items in G7"* — having retained a *"minimal real-state case/status view"* in the deployment-entry
subset. So the obligation is exactly **the distance between P5.4's minimal view and the finished
one**, and what "finished" means is G7's own text rather than a later paraphrase:

> One primary case workspace, concise promise view, stable dependency view and expandable evidence
> drawer. Each concept need not become a separate screen.
>
> Explain resource → version/task → promise only where causal. Unrelated promises remain visible
> but quiet. Stable graph placement; statuses use text as well as color.
>
> Blocked promise has owner/next-action/reason. Approval names exact change and deadline. Stale
> consent explains why the previous plan cannot execute. Reload/restart cannot falsely reset
> state.

plus the deferred half of G5's item 7: *"First case UI uses real state and shows next action,
affected/unaffected reasons. Reconnect/reload preserves case."*

The same cutoff **cuts** rather than defers *"graph animation"* and *"optional evidence-detail
presentation"*, so neither is owed here.

## 3. Criterion by criterion, against the code that is committed now

| frozen criterion | where it lives | proof |
|---|---|---|
| One primary case workspace, not a screen per concept | [`CaseWorkspace.tsx`](../apps/frontend/src/features/case/CaseWorkspace.tsx) — five bands and the conversation panel on one route | `caseWorkspace.test.tsx` *the band order is fixed, and the untouched band is never the one that goes*; `responsive.spec.ts` asserts that order at 1440, 1280, tablet and phone |
| Concise promise view | `PromiseIdentity` and `PromiseReading` in [`Propagation.tsx`](../apps/frontend/src/features/case/Propagation.tsx) — customer, order, phrase, state name, reason, deadline and next action, every one a backend string | `caseWorkspace.test.tsx` *renders each of the four outcomes in the backend's own words* |
| Stable dependency view | `CHAIN_GRID`'s four fixed columns, one traversal per row, no shared trunk | `propagation.test.tsx` *gives each of them its own chain, with no shared trunk between them* and *draws both nodes in that column, in the order they were stored* |
| Expandable evidence drawer | [`Evidence.tsx`](../apps/frontend/src/features/case/Evidence.tsx) — four layers, collapsed, arriving with the case | `caseWorkspace.test.tsx` *is collapsed until it is asked for*; `evidence.test.tsx` *reaches every layer without issuing a single request* |
| Resource → version → promise only where causal | `CAUSAL_SLOTS`; a promise with no path draws none | `propagation.test.tsx` *states the backend's reason and draws no edge at all*; `untouched.test.tsx` *draws no edge and no node back to the incident* |
| Unrelated promises visible but quiet | [`Untouched.tsx`](../apps/frontend/src/features/case/Untouched.tsx) — quiet ground, never collapsed, counted against the case's own universe | `untouched.test.tsx` *is never drawn as an achievement* and *stays visible and says so when the case left nothing alone* |
| Statuses use text as well as colour | [`vocabulary.ts`](../apps/frontend/src/components/vocabulary.ts) — exhaustive tables over the fourteen promise states and the nine case headlines, each carrying a phrase, a state name and a marker *shape* | `vocabulary.test.tsx`; `caseWorkspace.test.tsx` *states every promise as text as well as colour* |
| Blocked promise has owner, next action and reason | `owner`, `next_action` and `reason_phrase` per promise, and band 2's single action with its owner | `caseWorkspace.test.tsx` *gives every blocked promise an owner, a reason and a next action* |
| Approval names exact change and deadline | the exact change is `build_approval_request` in `domain/messaging.py` — the product ordered, the product that would arrive, and the substitution named beneath both; the deadline reaches the surface as `ApprovalEvidenceView.deadline`, printed by `ApprovalLine` as *asked ... , answer due by ...* | `test_consent_parser.py` *the message names the exact change*; `test_case_workspace.py` asserts the approval row on the asked promise and its provider reference. The `ApprovalLine` sentence itself has no dedicated frontend test |
| Stale consent explains why the previous plan cannot execute | `PromiseState.STALE`'s published phrase, and layer 3's revalidation checks with `expected` beside `actual` | `evidence.test.tsx` revalidation cases |
| Reload and restart cannot falsely reset state | the case id in the address bar, and the read is the durable case | `durability.spec.ts` — *a reload*, *a restored tab* and *a second browser* each land on the same durable case |
| Real state, next action, affected and unaffected reasons | every sentence, count and grouping arrives composed from `/api/cases/{id}` | `caseWorkspace.test.tsx` *takes the case's own universe from the backend's field, not from the counts beside it* |

Everything in the wider audit holds too, and each part has a test rather than an assertion: the
verbatim report with its attribution; the answered-question history
([`Clarifications.tsx`](../apps/frontend/src/features/case/Clarifications.tsx)); the conversation
panel inside the workspace, with its read-only posture, its plan-bound confirmation and a
withdrawal drawn **only** where `permitted_verbs` lists the verb; the judge's one-action entry,
offered no control that would change a case; no optimistic effect on a `PLANNED` case; and no
disabled control anywhere for a capability that does not exist.

`npx vitest run` in `apps/frontend`: **238 tests across 22 files, all passing** on the working tree
as this was written. No test was changed, weakened or added by this page.

## 4. The one item recorded as unmet, and why it does not hold this open

[`p7.3-visual-acceptance.md`](p7.3-visual-acceptance.md) §2 records that the five demo-critical
frames do not each compose in one unscrolled 1280×800 viewport — frame 3 measures 1485px and is one
scroll — and states why the content stayed: reaching 800 means compressing the causal rows, which
are the one thing on the screen a judge is meant to read.

That item comes from the **design handoff's own §9 acceptance list**, written by this project in
P7.1. It is not a frozen roadmap criterion, and the roadmap directs that optional polish be cut
before it encroaches on P8. It stays recorded as unmet where it was recorded, with the trade
stated. It is a composition preference deliberately traded against content, not a capability the
product lacks.

## 5. What this does not close

- **The G7 voice measurement.** Push-to-talk capture, the nine voice states and the text fallback
  are implemented; the predeclared ten real turns and the K/10-within-four-seconds figure are
  **not measured**, and no timing of any kind is claimed anywhere.
- **The demo-narrative comprehension check** with three unfamiliar viewers.
- **The executable sixteen-scenario fixtures and runner** against the frozen manifest.
- **Correcting a physical fact**, which remains reachable only from the CLI, exactly as P7.1
  records it.

None of these is the case-workspace obligation and none of them is closed by this page. **G7 as a
whole remains open.** What closes here is the last of the three items G5 carried into it.
