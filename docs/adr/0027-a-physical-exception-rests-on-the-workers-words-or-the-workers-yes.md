# ADR-0027 — A physical exception rests on the worker's words or the worker's yes

Status: accepted. It amends the semantic intake contract recorded in
[semantic-boundary.md](../semantic-boundary.md) (*What the model contributes*), which no earlier
ADR held. It reopens the G8 feature freeze for a reproduced correctness blocker.
Date: 2026-09-30
Phase: post-G8, before G9

A physical exception is written only when one of two things supports it. Either the worker's own
words assert the condition, or the worker has answered yes to a closed question naming the
condition and the resource. Finding a resource name and a parser or model category in the same
sentence is not enough.

## The evidence

An independent audit reported two failures. Both were reproduced on 2026-09-30 at `375e64d`
before any change, through the product's own intake worker against a disposable PostgreSQL 16.

**Deterministic.** The lexicon settled a category as soon as a marker matched, whatever the rest
of the sentence said.

| report | at `375e64d` |
|---|---|
| *The heavy cream is not spoiled* | `STOCK_UNUSABLE`. Heavy cream went from 100.000 to 0.000, and the case went on to `PLANNED` |
| *The heavy cream is fine, do not mark it spoiled* | `STOCK_UNUSABLE` |
| *The deck oven broke down last year, it works today* | `EQUIPMENT_UNAVAILABLE`. An outage fact was written, and the case reached `PLANNED` |
| *Has the heavy cream spoiled?* | `STOCK_UNUSABLE` (found while reproducing) |
| *If the heavy cream spoiled we would need more* | `STOCK_UNUSABLE` (found while reproducing) |

**Semantic.** When the lexicon stopped at `NO_CATEGORY`, a schema-valid reading whose resource
was written in the sentence grounded. `interpret_grounded` then resolved it exactly as if the
lexicon had read the category. The resource check was the only check, and the category came
from the model alone.

| report | scripted reading | at `375e64d` |
|---|---|---|
| *I need the heavy cream invoice* | `STOCK_UNUSABLE`, heavy cream | one model call; `STOCK_UNUSABLE` recorded; heavy cream 100.000 → 0.000; case at `PLANNED` |
| *Where is the deck oven manual?* | `EQUIPMENT_UNAVAILABLE`, deck oven | one model call; an equipment outage recorded; case at `PLANNED` |

In both paths `PHYSICAL_FACT_RECORDED` named the worker as attestor of something the worker
never said. That contradicts the first authority invariant: model output never produces a
physical attestation.

## Decision

### 1. A lexicon reading must be asserted by the sentence

When the lexicon supplies the category, `interpretation.unasserted` must also pass before the
reading may conclude. It is a closed vocabulary shaped like the markers themselves. It is read
per clause, after every category marker has been taken out of the clause, so the negation inside
`didn't arrive` or `not working` belongs to the marker and is never counted twice. The check
stops the reading when:

- the report instructs the system to record something (`mark`, `record`, `flag`, `log`, …);
- a clause that names the resource or holds a marker is a question or a supposition;
- a clause about the resource, or about nothing named (such as "it"), negates the condition,
  says the thing is fine or working, or dates the condition plainly to the past.

A clause that names only other resources is about them and is skipped. A stop is the new
`EscalationReason.CONDITION_NOT_ASSERTED`. It is **not** a fallback reason, so no model is asked
to read past a sentence that denies its own condition.

### 2. A model's category is a question, never a fact

A reading that grounds, meaning its resource is written in the worker's words, no longer resolves
to a fact, a delivery question or a scope question. It reaches intake as one new clarification,
`ClarificationSlot.CONDITION`. The question is written from the category and the resource's
stored name alone, for example *"is the deck oven out of service right now? Please answer yes or
no."* It has two fixed options, and neither option carries a line, a commitment or a quantity.
The question is persisted, audited and answered through the same clarification path the scope
question uses, and it counts toward the same two-question ceiling.

- **A plain yes** pins the category and the resource *read back off the persisted question*.
  The report is then resolved by the ordinary deterministic code, which may still ask which
  delivery or what scope, or refuse an uncounted quantity.
- **A no**, or "it's fine", escalates under `CONDITION_NOT_CONFIRMED`. Nothing is written.
- **Anything else**, including a yes carrying a negation or a question mark, gets the same
  question again. At the ceiling it goes to a person.

`read_condition_answer` is its own reader, with its own closed vocabulary. It is not the
customer's literal consent parser and not a plan approval, and it shares no code or records with
either.

Before asking, grounding applies the same `unasserted` check with `attested_later=True`. A
question, supposition, healthy state or denial is refused as
`GroundingFailure.CONDITION_NOT_ASSERTED` without asking. An instruction sitting beside a real
observation is still put to the worker, because the fact will rest on their yes rather than on
the sentence.

`SemanticResolution.outcome` is what intake does. `SemanticResolution.proposed` is what the
interpreter would reach on the worker's yes. It is kept for measurement and never persisted.

### 3. What the fact row says

`PHYSICAL_FACT_RECORDED` still names the worker, authority `NONE`, rule
`R-PHYSICAL-FACT-ATTESTED`. For a model-assisted case, the model now appears on the
`CLARIFICATION_REQUESTED` row that asked the question, with `interpretation_source:
SEMANTIC_ASSISTED`. The fact is written from the worker's answer, so it carries `clarified: true`
and `interpretation_source: DETERMINISTIC`.

### 4. Schema

`exception_clarifications.slot` admits `CONDITION` (migration `0010_condition_clarification`).
Only the check constraint changes: no column, table or data.

## What stays exactly as it was

- The canonical report, *today's raspberry delivery didn't arrive*, still asks its one scope
  question and still makes zero model calls.
- Plainly stated current conditions still resolve without a question. Examples: *the heavy cream
  spoiled*, *the deck oven is broken*, *the deck oven is not working*, *the cream went off,
  don't use it*.
- Grounding's earlier refusals are unchanged: unknown candidate, out of scope, category not
  offered, no confirmed resource, cross-kind evidence, ambiguous resource.
- The evaluation dataset: no label, split or hash moved. `evals validate` now checks each gold
  outcome against `reading_outcome`, the conclusion on the worker's yes. It also checks that every
  grounded reading reaches intake as the `CONDITION` question.

## Rejected

- **Special-casing the audit's strings** ("not spoiled", "last year"). The defect is that neither
  path asked whether the sentence asserts the condition. Patching strings leaves that question
  unasked.
- **A confidence threshold, a stronger prompt, trusting `evidence_span`, or a second model as a
  judge.** Each one still lets model output decide a physical fact. The boundary has to hold
  against a fully compromised reading, and only the worker's own answer does that.
- **Refusing every model-assisted reading.** It is safe, but it throws away the model's useful
  role, and `NEEDS_HUMAN_INTERPRETATION` has no human binding surface today, so every such case
  would dead-end.
- **Reusing the scope or commitment question.** Answering "which delivery?" is not saying that a
  delivery failed.
- **Sentence-wide negation on the model path.** Supply failures are negative by nature ("hasn't
  turned up"). On that path the worker's yes/no is the authority, and a denial without a marker
  reaches the worker, whose no writes nothing.

## Residuals, stated

- The lexicon is still a lexicon. A phrasing it does not recognise goes to the model path and then
  to the worker's question, or to a person. It never settles on its own. Some genuine reports that
  pair an exception with a hedge or a healthy clause now go to a person instead of resolving. For
  example, *the cream spoiled, the rest is fine* names nothing in its second clause, and that
  conservatism is deliberate.
- The `CONDITION` question counts toward the frozen two-question ceiling, which is unchanged. A
  model-assisted supply report that also needs *both* a delivery question and a scope question
  therefore reaches the ceiling after the worker's yes and the delivery answer, and goes to a
  person instead of asking a third question. A report that needs one of the two still completes.
- A worker can still answer yes to something untrue. That is a false attestation by a person,
  exactly as with the canonical sentence, and the correction path is unchanged.

## Release consequences

This changes deployable product paths (`apps/backend/src`, `apps/backend/alembic`). Under
[g8-closeout.md](../g8-closeout.md) §5 that **invalidates the G8 feature freeze declared at
`56c3023` / `4529a802e34e`** once it is merged. Those SHAs, and every rehearsal, run and capture
taken on them, remain historical fact and are not rewritten. After merge the repository contract
requires:

1. a new repository release SHA with `pr` green on it, every required job including
   `whole-stack browser`;
2. a new image and deployment, with migration `0010_condition_clarification` applied. The
   deployed stack's template gap in [non-destructive-release.md](../non-destructive-release.md)
   §10.1 is unchanged, so the release path needs the same explicit authorisation as before;
3. five new deployed rehearsals, R1–R5, on the new SHA using the frozen evidence reader;
4. the G8 16/16 release condition, re-taken once against the v2 label correction on the new code.
   The v1 11/16 headline stays immutable and is not re-run;
5. the demo-contract runner (`scripts/demo_contract.py`) re-run against the new code.

Not owed: the SUR-1 scored runs and the semantic benchmark runs. They are bound to their own
implementation SHAs and stay historical, and neither holdout is opened.
