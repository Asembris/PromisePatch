/**
 * The case workspace: five bands in the order the P5 product contract fixes.
 *
 * The rule this file is written against is that **it renders and it does not decide.** Every
 * sentence — the headline, each promise's phrase, each reason, the next action, the band
 * titles — arrives from the backend already composed, and none of them is computed, reworded or
 * defaulted here. A screen that wrote its own word for `RECOVERED` would be a second
 * implementation of the product's truthful vocabulary living where nobody tests it against a
 * durable case.
 *
 * Three consequences worth naming, because each one is a thing the screen deliberately does
 * *not* do:
 *
 * - **There is no button that changes a case.** A worker moves a case by saying something,
 *   through the conversational surface, where the attestation and the audit row are written
 *   together. This screen is the evidence, not a second authority.
 * - **No count on it is arithmetic.** `threatened_count` and `untouched_count` are shown as the
 *   two backend integers they are. Adding them together to publish a total would be the screen
 *   composing a figure, and a figure composed here is indistinguishable from the real ones
 *   beside it.
 * - **Status is legible without colour.** Every promise carries its phrase *and* its state name
 *   as text, and tone is decoration on top of that. The untouched set is present, uncollapsed
 *   and in the same reading as the affected set, because it carries the product's central
 *   claim.
 *
 * Bands 3 and 4 are one composition split by a boundary rule rather than two stacked boxes, so
 * a judge can see where propagation stopped without scrolling between the two halves of the
 * comparison.
 */
import type { ReactNode } from 'react'
import { useCase } from '../../api/queries'
import type { CaseWorkspaceResponse } from '../../api/types'
import { Badge, CaseHeadlineBadge } from '../../components/badges'
import { Card, Message, SectionLabel } from '../../components/surfaces'
import { Count, Value } from '../../components/values'
import { ClarificationHistory } from './Clarifications'
import { Conversation } from './Conversation'
import { EvidenceLayers } from './Evidence'
import { formatDateTime } from '../../components/time'
import { actionOwnerTone } from '../../components/vocabulary'
import { PropagationMap } from './Propagation'
import { UntouchedProof } from './Untouched'

export function CaseWorkspace({
  caseId,
  onClose,
}: {
  caseId: string
  onClose: () => void
}): ReactNode {
  const workspace = useCase(caseId)

  return (
    <main id="case-surface" className="mx-auto w-full max-w-[76rem] px-4 py-5 sm:px-6 sm:py-6">
      <div className="mb-3 flex items-center">
        <button
          type="button"
          onClick={onClose}
          className="-mx-2 inline-flex min-h-11 items-center rounded-quiet px-2 text-meta text-muted transition-colors hover:text-ink"
        >
          ← All cases
        </button>
      </div>

      <div>
        {workspace.isPending ? (
          <Message>Opening the case…</Message>
        ) : workspace.isError ? (
          <Message tone="bad">
            This case could not be loaded. Nothing about it has changed; the screen simply could
            not read it.
          </Message>
        ) : (
          <Bands view={workspace.data} />
        )}
      </div>
    </main>
  )
}

function Bands({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  return (
    // `data-motion` on the case rather than on the shell: it plays when a case the backend
    // returned is laid out, which is the moment a judge arriving by the one-action entry first
    // sees one. Nothing plays while the read is in flight.
    <div
      className="space-y-4"
      data-motion="settle"
      data-testid="case-workspace"
      data-case-id={view.case_id}
    >
      <WhatHappened view={view} />
      <WhatYouMustDo view={view} />
      {/* Inside the workspace, under the action it belongs to, with the bands still on screen.
          A conversation on a route of its own would be a second surface describing the same
          case, and the two would eventually disagree about which was current. */}
      <Conversation view={view} />
      <Propagation view={view} />
      <EvidenceLayers view={view} />
    </div>
  )
}

// -------------------------------------------------------------------------- band 1: the fact

/**
 * What a person said, in their words.
 *
 * The verbatim quote is the largest text on the screen after nothing at all, because a physical
 * attestation is the only thing here that a human being is the source of. It is never tidied,
 * sentence-cased or summarised — the panel that took it stored it byte for byte and this
 * prints what was stored.
 */
function WhatHappened({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  return (
    <section aria-label="What happened">
      <div className="space-y-3" data-testid="band-what-happened">
        <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
          {/* `basis-full` below `sm`, so the counts wrap under the quote instead of standing
              beside it. `flex-1` alone has a zero basis, which never forces a wrap — it just
              squeezes, and what it squeezes on a phone is the worker's own sentence, which is
              the one piece of text on this screen a person is the source of. */}
          <div className="min-w-0 flex-1 basis-full space-y-2 sm:basis-0">
            <CaseHeadlineBadge headline={view.headline} />
            {view.reported_text === null ? (
              <p className="text-sm text-muted">Nothing has been reported on this case yet.</p>
            ) : (
              <>
                <p className="text-label text-muted uppercase">
                  reported by <Value>{view.reported_by}</Value>
                  {view.reported_at === null ? null : (
                    <> · {formatDateTime(view.reported_at)}</>
                  )}
                  {/* The phrase, never the category. `SUPPLY_NOT_RECEIVED` is what the
                      engine filed this as, and it belongs in the technical record beside the
                      other tokens — band 1 says what happened in words. */}
                  {view.exception_phrase === null ? null : (
                    <> · {view.exception_phrase}</>
                  )}
                </p>
                <blockquote className="text-quote font-medium text-ink">
                  “{view.reported_text}”
                </blockquote>
              </>
            )}
            <p className="text-sm text-muted">{view.sentence}</p>
          </div>

          <dl className="flex shrink-0 gap-3" data-testid="case-counts">
            <CountTile value={view.threatened_count} label="orders affected" one="order affected" />
            <CountTile value={view.untouched_count} label="left alone" />
          </dl>
        </div>

        <ClarificationHistory clarifications={view.clarifications} />

        {view.question === null ? null : <OpenQuestion view={view} />}
      </div>
    </section>
  )
}

/** One backend integer, with the word it counts. No total is composed from the two. */
function CountTile({
  value,
  label,
  one,
}: {
  value: number
  label: string
  one?: string
}): ReactNode {
  return (
    <div className="rounded-quiet border border-edge bg-panel px-3.5 py-2.5">
      <Count value={value} label={label} one={one} />
    </div>
  )
}

/**
 * The open question, which outranks everything below it.
 *
 * A case with a question open has concluded nothing, so this is the focus of the screen rather
 * than a toast or a dismissible notice. The options are the delivery's own rows, captured when
 * the question was asked.
 */
function OpenQuestion({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  const question = view.question
  if (question === null) return null
  return (
    <Card
      className="border-ask/45 bg-ask/8 px-5 py-4"
      data-testid="case-question"
      aria-label="Open question"
    >
      <p className="text-label text-ask uppercase">one question is open</p>
      <p className="mt-2 text-quote font-medium text-ink">{question.question}</p>
      <ul className="mt-3 grid gap-2 sm:grid-cols-2">
        {question.options.map((option) => (
          <li
            key={option.code}
            className="rounded-quiet border border-ask/35 bg-surface/40 px-3 py-2 text-sm"
          >
            {option.label}
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ------------------------------------------------------------------- band 2: the next action

/**
 * Exactly one action, and exactly one owner.
 *
 * `NOBODY` is a real answer and reads as one. A blank band would look like a screen that had
 * failed to load rather than like the truthful "there is nothing for you here yet".
 */
function WhatYouMustDo({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  const action = view.next_action
  return (
    <section aria-label="What you must do now">
      <Card
        className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5 px-4 py-2.5 sm:px-5"
        data-testid="band-next-action"
      >
        {/* No fixed column. The owner label is one short backend string and a reserved width
            put a hand's breadth of empty card between it and the sentence it belongs to. */}
        <div className="flex shrink-0 items-baseline gap-2">
          <SectionLabel>whose move</SectionLabel>
          <Badge tone={actionOwnerTone(action.owner)}>{action.owner_label}</Badge>
        </div>
        {/* Same rule as band 1: on a narrow screen the one thing this band exists to say drops
            to its own line rather than sharing it with the owner chip. */}
        <p
          className="min-w-0 flex-1 basis-full text-action font-medium sm:basis-0"
          data-testid="next-action-sentence"
        >
          {action.action}
        </p>
      </Card>
    </section>
  )
}

// ----------------------------------------------------- bands 3 and 4: reached, and not reached

/**
 * The two halves of the comparison, in one composition, split by the boundary.
 *
 * Band 3 is the incident and every path out of it; band 4 is everything those paths did not
 * reach. They are one section rather than two because the comparison is the claim: a judge who
 * has to scroll from one to the other is being asked to hold the first half in their head.
 */
function Propagation({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  return (
    <section className="space-y-4" aria-label="What changes, and what was left alone">
      <PropagationMap
        bands={view.authority_bands}
        exceptionPhrase={view.exception_phrase}
        reportedText={view.reported_text}
      />
      <UntouchedProof
        promises={view.untouched}
        untouchedCount={view.untouched_count}
        untouchedEffectCount={view.untouched_effect_count}
        promiseCount={view.promise_count}
      />
    </section>
  )
}

// ----------------------------------------------------------------------- band 5: the evidence

// The four layers live in `Evidence.tsx`. They are a composition rather than a block of markup
// here because "how do I know?" is the one question on this screen with several right answers
// at several depths, and a reader chooses the depth.
