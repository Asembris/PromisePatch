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
import { useState, type ReactNode } from 'react'
import { useCase } from '../../api/queries'
import type { CaseWorkspaceResponse, TrackEvidenceView } from '../../api/types'
import { Badge, CaseHeadlineBadge } from '../../components/badges'
import { Card, Message, QuietCard, SectionLabel } from '../../components/surfaces'
import { Count, Value } from '../../components/values'
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
    <main className="mx-auto w-full max-w-[76rem] px-4 py-5 sm:px-6 sm:py-6">
      <div className="mb-3 flex items-center">
        <button
          type="button"
          onClick={onClose}
          className="text-meta text-muted transition-colors hover:text-ink"
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
    <div className="space-y-4" data-testid="case-workspace" data-case-id={view.case_id}>
      <WhatHappened view={view} />
      <WhatYouMustDo view={view} />
      <Propagation view={view} />
      <EvidenceDrawer view={view} />
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
          <div className="min-w-0 flex-1 space-y-2">
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
                  {view.exception_category === null ? null : (
                    <> · {view.exception_category}</>
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
            <CountTile value={view.threatened_count} label="orders affected" />
            <CountTile value={view.untouched_count} label="left alone" />
          </dl>
        </div>

        {view.question === null ? null : <OpenQuestion view={view} />}
      </div>
    </section>
  )
}

/** One backend integer, with the word it counts. No total is composed from the two. */
function CountTile({ value, label }: { value: number; label: string }): ReactNode {
  return (
    <div className="rounded-quiet border border-edge bg-panel px-3.5 py-2.5">
      <Count value={value} label={label} />
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
        className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-5"
        data-testid="band-next-action"
      >
        <div className="flex shrink-0 flex-col items-start gap-1.5 sm:w-32">
          <SectionLabel>whose move</SectionLabel>
          <Badge tone={actionOwnerTone(action.owner)}>{action.owner_label}</Badge>
        </div>
        <p className="min-w-0 flex-1 text-action font-medium" data-testid="next-action-sentence">
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
        exceptionCategory={view.exception_category}
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

function EvidenceDrawer({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  const [open, setOpen] = useState(false)
  const evidence = view.evidence

  return (
    <section aria-label="Evidence">
      <QuietCard className="px-4 py-3">
        <button
          type="button"
          onClick={() => {
            setOpen((current) => !current)
          }}
          aria-expanded={open}
          className="text-meta font-medium text-muted transition-colors hover:text-ink"
          data-testid="evidence-toggle"
        >
          {open ? 'Hide how I know' : 'How do I know?'}
        </button>

        {open ? (
          <div className="mt-4 space-y-3 font-mono text-state" data-testid="evidence-drawer">
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
              <dt className="text-muted">case</dt>
              <dd>{evidence.case_id}</dd>
              <dt className="text-muted">state</dt>
              <dd>
                {evidence.case_state} · v{evidence.case_version}
              </dd>
              <dt className="text-muted">plan</dt>
              <dd className="break-all">{evidence.plan_id}</dd>
              {evidence.interpretation === null ? null : (
                <>
                  <dt className="text-muted">reading</dt>
                  <dd>
                    {evidence.interpretation.source} · {evidence.interpretation.outcome ?? '—'} ·
                    attested by <Value>{evidence.interpretation.attestor}</Value>
                  </dd>
                </>
              )}
            </dl>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[48rem] text-left">
                <thead className="text-muted">
                  <tr>
                    <th className="py-1 pr-3 font-normal">promise</th>
                    <th className="py-1 pr-3 font-normal">track</th>
                    <th className="py-1 pr-3 font-normal">rule</th>
                    <th className="py-1 pr-3 font-normal">fingerprint</th>
                    <th className="py-1 pr-3 font-normal">effects</th>
                  </tr>
                </thead>
                <tbody>
                  {evidence.tracks.map((track) => (
                    <EvidenceRow key={track.track_id} track={track} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </QuietCard>
    </section>
  )
}

function EvidenceRow({ track }: { track: TrackEvidenceView }): ReactNode {
  return (
    <tr
      className="border-t border-edge align-top"
      data-testid="evidence-row"
      data-promise-id={track.promise_id}
    >
      <td className="py-1 pr-3">{track.promise_id}</td>
      <td className="py-1 pr-3">
        {track.track_state}
        <div className="text-muted">{track.track_id.slice(0, 8)}</div>
      </td>
      <td className="py-1 pr-3">
        <Value>{track.rule_id}</Value>
        <div className="text-muted">{track.reason_detail}</div>
      </td>
      <td className="py-1 pr-3">
        {track.fingerprint === null ? '—' : track.fingerprint.slice(0, 12)}
      </td>
      <td className="py-1 pr-3">
        {track.effects.length === 0 && track.approval === null ? (
          <span className="text-muted">none</span>
        ) : (
          <>
            {track.effects.map((effect) => (
              <div key={effect.idempotency_key} data-testid="evidence-effect">
                {effect.kind} · {effect.state} · <Value>{effect.provider_ref}</Value>
              </div>
            ))}
            {track.approval === null ? null : (
              <div data-testid="evidence-approval">
                ASK · {track.approval.state} · <Value>{track.approval.provider_ref}</Value>
              </div>
            )}
          </>
        )}
      </td>
    </tr>
  )
}
