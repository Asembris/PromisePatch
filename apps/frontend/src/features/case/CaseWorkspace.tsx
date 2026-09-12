/**
 * The first case workspace: four bands and one drawer, in the order the P5 contract fixes.
 *
 * The rule this file is written against is that **it renders and it does not decide.** Every
 * sentence — the headline, each promise's phrase, each reason, the next action, the band
 * titles, the untouched count — arrives from the backend already composed, and none of them is
 * computed, reworded or defaulted here. A screen that wrote its own word for `RECOVERED`, or
 * that counted the untouched promises itself, would be a second implementation of the product's
 * truthful vocabulary living where nobody tests it against a durable case.
 *
 * Two consequences worth naming:
 *
 * - **There is no button that changes a case.** A worker moves a case by saying something,
 *   through the conversational surface, where the attestation and the audit row are written
 *   together. This screen is the evidence, not a second authority.
 * - **Status is legible without colour.** Every state is shown as text — the phrase a person
 *   reads, and the state name beside it — and the tone is decoration on top of that, never the
 *   only carrier. The untouched band is present even when it is long, because it carries the
 *   product's central claim.
 */
import { useState, type ReactNode } from 'react'
import { useCase } from '../../api/queries'
import type {
  AuthorityBandView,
  CaseWorkspaceResponse,
  PromiseWorkspaceView,
  TrackEvidenceView,
} from '../../api/types'
import { Badge, Notice, Panel, StateBadge, Value } from '../../components/primitives'
import { formatDateTime } from '../../components/time'
import type { BadgeTone } from '../../components/tones'

/** Who a next action belongs to, as a tone. Presentation only: the label is always shown. */
const OWNER_TONE: Record<string, BadgeTone> = {
  YOU: 'warn',
  OWNER: 'bad',
  CUSTOMER: 'info',
  SYSTEM: 'neutral',
  NOBODY: 'neutral',
}

export function CaseWorkspace({
  caseId,
  onClose,
}: {
  caseId: string
  onClose: () => void
}): ReactNode {
  const workspace = useCase(caseId)

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-6 py-6">
      <button
        type="button"
        onClick={onClose}
        className="text-xs text-muted underline underline-offset-2"
      >
        ← All cases
      </button>

      {workspace.isPending ? (
        <Notice>Loading the case…</Notice>
      ) : workspace.isError ? (
        <Notice tone="bad">
          This case could not be loaded. Nothing about it has changed; the screen simply could
          not read it.
        </Notice>
      ) : (
        <Bands view={workspace.data} />
      )}
    </main>
  )
}

function Bands({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  return (
    <div className="space-y-6" data-testid="case-workspace" data-case-id={view.case_id}>
      <WhatHappened view={view} />
      <WhatYouMustDo view={view} />
      <WhatChanges bands={view.authority_bands} />
      <WhatWasLeftAlone view={view} />
      <EvidenceDrawer view={view} />
    </div>
  )
}

// -------------------------------------------------------------------------- band 1: the fact

function WhatHappened({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  return (
    <Panel title="What happened" subtitle={view.headline}>
      <div className="space-y-3 px-4 py-3" data-testid="band-what-happened">
        {view.reported_text === null ? (
          <p className="text-sm text-muted">Nothing has been reported on this case yet.</p>
        ) : (
          <blockquote className="border-l-2 border-edge pl-3 text-sm">
            “{view.reported_text}”
            <footer className="mt-1 text-xs text-muted">
              reported by <Value>{view.reported_by}</Value>
              {view.reported_at === null ? null : <> · {formatDateTime(view.reported_at)}</>}
              {view.exception_category === null ? null : (
                <> · <Badge>{view.exception_category}</Badge></>
              )}
            </footer>
          </blockquote>
        )}
        <p className="text-sm">{view.sentence}</p>
        {view.question === null ? null : (
          <div className="rounded-quiet border border-ask/45 bg-ask/8 px-3 py-2" data-testid="case-question">
            <p className="text-sm font-medium text-ink">{view.question.question}</p>
            <ul className="mt-1 list-disc pl-5 text-sm text-muted">
              {view.question.options.map((option) => (
                <li key={option.code}>{option.label}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  )
}

// ------------------------------------------------------------------- band 2: the next action

function WhatYouMustDo({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  const action = view.next_action
  return (
    <Panel title="What you must do now">
      <div className="flex items-start gap-3 px-4 py-3" data-testid="band-next-action">
        <Badge tone={OWNER_TONE[action.owner] ?? 'neutral'}>{action.owner_label}</Badge>
        <p className="text-sm" data-testid="next-action-sentence">
          {action.action}
        </p>
      </div>
    </Panel>
  )
}

// ------------------------------------------------------------- band 3: what changes, and whose

function WhatChanges({ bands }: { bands: AuthorityBandView[] }): ReactNode {
  return (
    <Panel
      title="What changes, under whose authority"
      subtitle={bands.length === 0 ? undefined : `${bands.length} groups`}
    >
      {bands.length === 0 ? (
        <Notice>Nothing has been decided about any promise yet.</Notice>
      ) : (
        <div className="divide-y divide-edge" data-testid="band-what-changes">
          {bands.map((band) => (
            <section key={band.authority} data-testid="authority-band" data-authority={band.authority}>
              <h3 className="bg-surface px-4 py-2 text-xs font-semibold tracking-wide uppercase">
                {band.title}
              </h3>
              <ul>
                {band.promises.map((promise) => (
                  <PromiseRow key={promise.promise_id} promise={promise} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Panel>
  )
}

function PromiseRow({ promise }: { promise: PromiseWorkspaceView }): ReactNode {
  return (
    <li
      className="border-t border-edge px-4 py-3 first:border-t-0"
      data-testid="promise-row"
      data-promise-id={promise.promise_id}
      data-state={promise.state}
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-sm font-medium">{promise.customer_name}</span>
        <span className="font-mono text-xs text-muted">{promise.order_external_id}</span>
        {/* The phrase is the reading; the state name is beside it so the row is legible with
            no colour at all, which is what the contract requires of every status. */}
        <span className="text-sm">— {promise.phrase}</span>
        <StateBadge state={promise.state} />
      </div>
      <p className="mt-1 text-xs text-muted">
        {promise.reason}
        {promise.deadline_at === null ? null : <> · by {formatDateTime(promise.deadline_at)}</>}
      </p>
      <p className="mt-1 text-xs" data-testid="promise-next-action">
        <span className="text-muted">Next: </span>
        {promise.next_action}
      </p>
    </li>
  )
}

// ------------------------------------------------------------------ band 4: what was untouched

function WhatWasLeftAlone({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  return (
    <Panel
      title="What was left alone"
      // The count comes from the backend. It is the product's published claim, and a screen
      // that recomputed it from a list it might have filtered could publish a different one.
      subtitle={`${view.untouched_count} of ${view.untouched_count + view.threatened_count} promises`}
    >
      {view.untouched.length === 0 ? (
        <Notice>No promise in this case was left alone.</Notice>
      ) : (
        <ul className="divide-y divide-edge" data-testid="band-untouched">
          {view.untouched.map((promise) => (
            <li
              key={promise.promise_id}
              className="px-4 py-2"
              data-testid="untouched-row"
              data-promise-id={promise.promise_id}
            >
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-sm">{promise.customer_name}</span>
                <span className="font-mono text-xs text-muted">{promise.order_external_id}</span>
                <span className="text-sm text-muted">— {promise.phrase}</span>
              </div>
              <p className="text-xs text-muted">{promise.reason}</p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

// ----------------------------------------------------------------------- band 5: the evidence

function EvidenceDrawer({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  const [open, setOpen] = useState(false)
  const evidence = view.evidence

  return (
    <Panel title="Evidence">
      <div className="px-4 py-3">
        <button
          type="button"
          onClick={() => {
            setOpen((current) => !current)
          }}
          aria-expanded={open}
          className="text-xs underline underline-offset-2"
          data-testid="evidence-toggle"
        >
          {open ? 'Hide how I know' : 'How do I know?'}
        </button>

        {open ? (
          <div className="mt-3 space-y-3 font-mono text-[11px]" data-testid="evidence-drawer">
            <dl className="grid grid-cols-[auto_1fr] gap-x-3">
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
      </div>
    </Panel>
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
      <td className="py-1 pr-3">{track.fingerprint === null ? '—' : track.fingerprint.slice(0, 12)}</td>
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
