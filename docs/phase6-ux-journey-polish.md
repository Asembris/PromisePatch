# Phase 6 session 1 — the judge and customer journey, audited and polished

Date: 2026-09-23. Entry at `82130416d820`, tracked tree clean, `main` equal to `origin/main`,
the eleven known untracked artefacts left as they were. Frontend and presentation only, with
two presentation fields added to the read API. **Nothing here is deployed**: the deployed host
still serves `931a296decad`, and no AWS resource, IAM policy, SUR-1 artefact, effect-set
artefact or frozen document was touched.

The standard the audit was held to is one paragraph a judge should be able to say back without
reading the repository:

> An exception happened. PromisePatch determined what is affected, what it may change
> automatically, what needs the owner, and what needs the customer. Customer authority comes
> only through the secure approval page. Before applying an approved recovery, PromisePatch
> checks current reality again.

## 1. How the audit was done

- **Source first.** Every surface on the ten-step journey — report, interpretation, the five
  workspace bands, plan confirmation, `WAITING`, the signed link, the approval page, the
  decision, revalidation, settlement — was traced from the components to the backend strings
  they print (`status_view`, `api/views/cases.py`, `api/views/customer.py`, `messaging`).
- **The deployed judge view, read only.** The observer session already present in the in-app
  browser read `https://184.194.40.87.sslip.io`. Nothing was pressed that writes.
- **The real local stack.** The canonical case was driven through the product's own transports
  — report, clarification, confirmation in a browser, the customer's signed link in a separate
  browser context with no storage — against a backend image rebuilt from the working tree. Only
  the canonical sentence and answer were sent, which the product resolves deterministically, so
  no model was called.

## 2. What was found

| # | class | finding | disposition |
|---|---|---|---|
| 1 | **P1** | The customer page never says when the question closes. `answer_by` is in the response and was never rendered, and the outbound message names only the order's due time — so a customer is asked for a decision and told no deadline anywhere. | fixed |
| 2 | **P1** | The customer page stopped re-reading at its first `APPROVED`. The decision is written *before* revalidation, so that first reading has no outcome yet; a customer who kept the tab open was left at "Your answer is on the record" for good — or at "We are updating your order now" after the change had landed. The committed browser spec never saw it because it reloads the page. Nothing on the page said the order is checked again before it changes. | fixed |
| 3 | **P1** | The judge is addressed as the worker. On the canonical `PLANNED` case the observer session read **WHOSE MOVE: You — Read the plan below and confirm it** and a chip saying **WAITING FOR YOUR YES**, beside "Changing it is the bakery's to do" and a sign-in promise that they can "change nothing". [`demo-world-restore.md`](demo-world-restore.md) §9 quotes that chip from the deployed host. | fixed |
| 4 | **P1** | One deadline, two unlabelled clocks. A row renders `deadline_at` in the reader's clock with no zone; the spoken status beside it says the same moment in UTC. For any reader not on UTC, two different times for one deadline sit on one screen. | fixed |
| 5 | **P1**, out of scope | The deployed host's only case, `5b825f1b-…`, left `PLANNED` (as the restore record states) and now reads `RESOLVED` at case version 9 with EXT-A to EXT-D all `ESCALATED`, **zero effects and no approval request**. A judge sees "Covered by a standing preference" and "Needs the customer" rows reading "needs you" beside reasons that say the change was pre-approved or needed asking, and nothing anywhere says why they escalated: the escalation cause is not in the read model. | recorded, see §6 |
| 6 | P2 | A `REQUESTED` row says the same sentence twice: consent "the customer has been asked and has not answered", next action "Nothing. The customer has been asked and has not answered." | recorded |
| 7 | P2 | Evidence layer 3, meant to be sentences, prints engine tokens: "Revalidation: PROCEED" and "A decision is recorded: APPROVE". The phrases exist in `explanations` and are not carried to the API. | recorded |
| 8 | P2 | The case list's read failure says "They will be retried on the next event" — engineering wording. | recorded |
| 9 | P2 | `explanations.CONSENT_AUTHORITY` still says a decision is "a literal yes or no on their own channel", which ADR-0021 made untrue. It reaches no runtime surface — only the closed explanation gate's material — so it was left alone. | recorded |

**No P0 was found.** Nothing on any surface implied that a model, a Telegram reply or an
observer had authority it lacks in a way that could cause an effect: the domain refuses every
one of them regardless, and the observer finding (3) is wording, not a permission.

Held up well and left alone: the five-band hierarchy, the untouched proof withheld until
something was assessed, the "planned – waiting for you" discipline with no tick anywhere, owner
escalations styled as work rather than faults, the withdrawal that says it is not an undo, the
approval page's refusal to state a price or a safety claim, and the `RECEIVED` phase that never
claims a decision early.

## 3. What changed, and why

| commit | change |
|---|---|
| `8cee53e` `fix(ui): name the time zone beside every date and time` | `formatDateTime` carries the short zone name, so a row's "by Sep 23, 09:22 PM GMT+2" and the spoken "by 2026-09-23 19:22 (UTC)" visibly name the same moment. Display only, as before. |
| `f3521cd` `fix(customer): say when the question closes and that the change needs their yes` | The open page prints "Please answer by …" from `answer_by` — printed, never compared; `answerable` stays the server's — and under the buttons says "We make this change only if you approve it." |
| `ed69bda` `fix(customer): keep the approval page current until an approved change settles` | The customer view gains `awaiting_outcome`, decided on the server: true while an answer is stored and unread, and while a recorded yes is at `WAITING_FOR_CUSTOMER` or `APPLYING`. The page re-reads while it is true. A recorded yes that has not been carried out yet now says "Before anything changes, the bakery checks that your order can still be made this way." |
| `9f6805f` `fix(workspace): stop addressing a read-only observer as the worker who must act` | `status_view.owner_label` names `YOU` in the third person — "The worker" — for a reader the domain will not let act; the API view applies it with `may_speak`, exactly where it already narrows the verbs. The owner, the sentence and every permission are unchanged. The voice chip says "waiting for your yes" only to a reader whose verbs include `confirm`. |
| `ee03851` `fix(workspace): tell a read-only reader who "you" is before the sentences that say it` | The read-only notice now explains that "you" means the bakery worker handling the case, and sits above the spoken status rather than at the foot of the panel, below the fold. |

The contract's frozen phrases were not reworded: "planned - waiting for you" and the headline
sentences are exactly as they were, and the spoken status (`speech`, `spoken`) is byte for byte
unchanged, so nothing measured under G7 moved.

## 4. Before and after

**The customer, one tab, never reloaded.** Driven live on the local stack after the fix:

```text
OPEN      "We need your decision" ... "Please answer by Sep 23, 09:19 PM GMT+2."
          "We make this change only if you approve it. If you decline, the bakery will follow up with you."
RECEIVED  (no outcome yet)
APPROVED  Before anything changes, the bakery checks that your order can still be made this way.
APPROVED  We are updating your order now.
APPROVED  Your order now shows this change.
```

Before the fix the same tab stopped reading at the first `APPROVED`, which in this run carried no
outcome at all, and no deadline was printed on the open page.

**The judge, on the canonical `PLANNED` case, at 1280×800:**

| | before | after |
|---|---|---|
| band 2 | WHOSE MOVE **You** — Read the plan below and confirm it before anything is done. | WHOSE MOVE **The worker** — the same sentence |
| conversation chip | WAITING FOR YOUR YES | NOTHING IS YOURS RIGHT NOW |
| read-only notice | at the foot of the panel: "Changing it is the bakery's to do." | above the status: "Where it says "you", it means the bakery worker handling it: changing it is theirs to do." |
| confirm controls | 0 | 0 |

A worker reading the same case still sees "You", "waiting for your yes" and the confirm control.

## 5. Validation

| check | result |
|---|---|
| `test_customer_approval_link.py`, real PostgreSQL, real worker | **38 passed**, 5 new |
| `test_case_workspace.py`, real PostgreSQL | **38 passed**, 1 new |
| `test_status_view.py` | **65 passed**, 5 new cases |
| frontend unit suite | **332 passed** of 332; `time.test.ts` new, and new cases in the customer, conversation and voice-state suites |
| `npm run typecheck`, `npm run lint`, `npm run build` | clean |
| `ruff check`, `ruff format --check` on every changed Python file; `mypy` group A | clean; `mypy` 291 files, no issues |
| `customer-approval.spec.ts`, real stack, rebuilt image | **7 passed** |
| `judge-journey.spec.ts` + `responsive.spec.ts`, all four widths | **28 passed** on the final state |
| single-tab settle, driven live (not committed) | the sequence in §4 |

Two things are disclosed rather than smoothed over. One full frontend run failed a single
existing judge test on a one-second `findByTestId` timeout under load; it passed on the full
rerun and three times in isolation. One earlier `responsive.spec.ts` run measured the existing
"Read this aloud" button a fraction under 44px at phone width; it passed at all four widths on
three reruns and on the final run. Neither test was touched. `lint-imports` was not run: no
import was added or moved.

The browser specs need the judge entry, which this machine's `docker/env/api.env` turns off for
a SUR-1 scored stack. It was enabled on `api` alone through a compose override kept outside the
repository, and `api` was recreated on its own environment afterwards. The local stack was
returned to the shape it was found in — `api`, `mcp`, `postgres`, the order system and the
frontend container up, the worker stopped — on a backend image rebuilt from this work. The
fixture reseeds the browser specs perform erased the local cases, which were demo data.

## 6. What remains

- **The deployed judge surface is not demonstrable as it stands** (finding 5). The one deployed
  case shows no recovery, and why A and B escalated with no effect is not established — this
  session read nothing on the host. It needs a read-only diagnosis on the host, then the
  documented restore before anybody is shown the product.
- **Escalation causes are not on the read surface.** When a permitted or approved change
  escalates, the workspace shows the classification reason and not the reason it escalated.
  Closing that is a read-model addition through `analysis`, `status_view`, the API and the
  screen — beyond presentation, so it was not started.
- **None of these fixes is deployed.** A release is deployment work and was out of scope.
- The four P2 items above, and the customer page's own lack of a live refusal path: `STALE`,
  `EXPIRED` and `UNAUTHORIZED` are still proved by tests only, as
  [`customer-disclosure-hardening.md`](customer-disclosure-hardening.md) §7 records.
