/**
 * "Why did PromisePatch decide this?", answered in four layers a reader chooses between.
 *
 * The judge's real question is not what happened but how they would know this is not a picture
 * of what happened. That question has four different depths, and answering it at one depth
 * fails two readers: a baker handed fingerprints, or a sceptic handed a sentence. So the layers
 * are explicit and each one is a disclosure the reader opens:
 *
 * 1. **In plain words** — one sentence per promise, built from strings the domain composed.
 * 2. **The path it travelled** — the same traversal the bands draw, written out in order.
 * 3. **What was checked** — the authority a change needed, what the customer was asked, and
 *    every revalidation check with the two values it compared, expected beside actual.
 * 4. **The technical record** — identifiers, versions, provider references and timestamps.
 *
 * Four rules hold across all of them.
 *
 * **Nothing is composed here.** Every sentence, count, phrase and reason is a backend field.
 * This file joins two projections of the same track by id and orders nothing of its own: the
 * rows are `evidence.tracks` in the order the backend sent them, which is why an untouched
 * promise cannot be filtered out of the record that proves it was left alone.
 *
 * **Identifiers live in layer 4 and nowhere above it.** `node_ref`, `track_id`, `rule_id`,
 * fingerprints, idempotency keys and provider references appear in the deepest layer only. The
 * three above it read as sentences, which is the whole reason a worker can be shown the same
 * surface as a judge.
 *
 * **Opening a layer is never a request.** Everything rendered here arrived with the case, and
 * the tests fail if a toggle issues a fetch. A drawer that loaded on open would make the
 * evidence the slowest thing on the screen to reach.
 *
 * **A layer with nothing in it says so.** An empty revalidation list is "nothing was
 * revalidated", not blank space — silence in an evidence surface reads as something withheld.
 */
import type { ReactNode } from 'react'
import type {
  ApprovalEvidenceView,
  CaseWorkspaceResponse,
  CausalChainView,
  EffectEvidenceView,
  EvidenceView,
  PromiseWorkspaceView,
  RevalidationEvidenceView,
  TrackEvidenceView,
} from '../../api/types'
import { Disclosure } from '../../components/disclosure'
import { PromiseStatePill } from '../../components/badges'
import { QuietCard, SectionLabel } from '../../components/surfaces'
import { Value } from '../../components/values'
import { formatDateTime } from '../../components/time'

/**
 * One track, seen from both projections of it.
 *
 * `promise` is absent only for a track the bands and the untouched set between them did not
 * carry, which is a backend that knows about a track the workspace does not. The record still
 * shows the track rather than hiding it, because a row missing from an evidence surface is the
 * one thing it must never be.
 */
interface Subject {
  track: TrackEvidenceView
  promise: PromiseWorkspaceView | undefined
}

function subjects(view: CaseWorkspaceResponse): Subject[] {
  const byPromise = new Map<string, PromiseWorkspaceView>()
  for (const band of view.authority_bands) {
    for (const promise of band.promises) byPromise.set(promise.promise_id, promise)
  }
  for (const promise of view.untouched) byPromise.set(promise.promise_id, promise)
  // The backend's own order, over the backend's own list of tracks. Nothing is sorted here.
  return view.evidence.tracks.map((track) => ({
    track,
    promise: byPromise.get(track.promise_id),
  }))
}

export function EvidenceLayers({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  const rows = subjects(view)

  return (
    <section aria-label="Evidence">
      <QuietCard className="px-4 py-3">
        <Disclosure summary="Why did PromisePatch decide this?" testId="evidence-toggle" tone="loud">
          <div className="mt-4 space-y-4" data-testid="evidence-drawer">
            <PlainWords view={view} rows={rows} />
            <CausalPaths rows={rows} />
            <WhatWasChecked view={view} rows={rows} />
            <TechnicalRecord evidence={view.evidence} rows={rows} />
          </div>
        </Disclosure>
      </QuietCard>
    </section>
  )
}

// ----------------------------------------------------------------------- 1. in plain words

/**
 * The answer a person would give out loud, for every promise the case looked at.
 *
 * Open with the section rather than behind another control, because this is the layer that has
 * to be reachable without a decision. The three below it are for a reader who did not believe
 * this one.
 */
function PlainWords({
  view,
  rows,
}: {
  view: CaseWorkspaceResponse
  rows: readonly Subject[]
}): ReactNode {
  return (
    <div className="space-y-2" data-testid="evidence-plain">
      <SectionLabel>in plain words</SectionLabel>
      {view.exception_phrase === null ? null : (
        <p className="text-reason text-muted" data-testid="evidence-exception">
          What happened: {view.exception_phrase}.
        </p>
      )}
      {rows.length === 0 ? (
        <p className="text-reason text-muted">
          This case has not decided anything about a promise yet.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map(({ track, promise }) => (
            <li
              key={track.track_id}
              className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-reason"
              data-testid="evidence-plain-row"
              data-promise-id={track.promise_id}
            >
              <span className="text-sm font-medium">
                {promise === undefined ? track.order_external_id : promise.customer_name}
              </span>
              {promise === undefined ? null : (
                <PromiseStatePill state={promise.state} phrase={promise.phrase} />
              )}
              <span className="text-muted">
                {promise?.reason_phrase === null || promise?.reason_phrase === undefined
                  ? 'The recovery rules record no further reason.'
                  : `Because ${promise.reason_phrase}.`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ 2. the path it travelled

/**
 * The same traversal the bands draw, written out as a sentence-shaped sequence.
 *
 * It is here as well as in band 3 because the two answer different readers: the band shows
 * that a path exists and where it stopped, and this shows what each node of it actually was,
 * in a form somebody can read aloud into a transcript. Neither is composed — both render the
 * same `causal_chain` the domain projected from the stored traversal.
 */
function CausalPaths({ rows }: { rows: readonly Subject[] }): ReactNode {
  return (
    <Disclosure summary="the path from what happened to each promise" testId="evidence-path">
      <ul className="mt-2 space-y-2">
        {rows.map(({ track, promise }) => (
          <li
            key={track.track_id}
            className="text-reason"
            data-testid="evidence-path-row"
            data-promise-id={track.promise_id}
          >
            <span className="text-sm font-medium">
              {promise === undefined ? track.order_external_id : promise.customer_name}
            </span>
            <ChainInWords chain={promise?.causal_chain} />
          </li>
        ))}
      </ul>
    </Disclosure>
  )
}

/**
 * One chain, in order, with no identifier in it.
 *
 * `node_ref` is deliberately not reachable from here: this reads `label` and `detail` and there
 * is nothing else on a step it could print. The reference itself belongs to layer 4, beside the
 * other identifiers, where a reader has asked for exactly that.
 */
function ChainInWords({ chain }: { chain: CausalChainView | undefined }): ReactNode {
  if (chain === undefined) {
    return <p className="text-muted">This build was told nothing about how this was reached.</p>
  }
  if (!chain.present) {
    return (
      <p className="text-muted" data-testid="evidence-path-absent">
        {chain.absence_reason ?? 'Nothing reached this promise.'}
      </p>
    )
  }
  return (
    <ol className="mt-1 space-y-0.5">
      {chain.steps.map((step, index) => (
        <li key={step.node_ref} className="flex gap-2 text-muted">
          <span className="font-mono text-state tabular-nums">{index + 1}.</span>
          <span>
            <span className="text-ink">{step.label}</span>
            {step.detail === null ? null : <> — {step.detail}</>}
          </span>
        </li>
      ))}
    </ol>
  )
}

// --------------------------------------------------------------------- 3. what was checked

/**
 * Whose permission a change needed, what was asked, and what each check compared.
 *
 * The revalidation rows quote both values rather than a verdict word, because a checklist that
 * reported only "failed" is asking to be believed. `expected` beside `actual` is the smallest
 * form in which a reader can disagree with the conclusion.
 */
function WhatWasChecked({
  view,
  rows,
}: {
  view: CaseWorkspaceResponse
  rows: readonly Subject[]
}): ReactNode {
  const reading = view.evidence.interpretation
  return (
    <Disclosure summary="what was checked, and under whose authority" testId="evidence-authority">
      <div className="mt-2 space-y-3">
        {reading === null ? null : (
          <p className="text-reason text-muted" data-testid="evidence-reading">
            The report was read by {reading.source.toLowerCase()} and the facts are attested by{' '}
            <Value>{reading.attestor}</Value>.
          </p>
        )}
        {rows.map(({ track, promise }) => (
          <div
            key={track.track_id}
            className="space-y-1 text-reason"
            data-testid="evidence-authority-row"
            data-promise-id={track.promise_id}
          >
            <p className="flex flex-wrap items-baseline gap-x-2.5">
              <span className="text-sm font-medium">
                {promise === undefined ? track.order_external_id : promise.customer_name}
              </span>
              {promise === undefined ? null : (
                <span className="text-muted">
                  changes under the authority of {promise.authority.toLowerCase().replace('_', ' ')}
                </span>
              )}
            </p>
            <ApprovalLine approval={track.approval} />
            <RevalidationChecks revalidation={track.revalidation} />
          </div>
        ))}
      </div>
    </Disclosure>
  )
}

/** What one customer was asked, and whether an answer of theirs has been recorded. */
function ApprovalLine({ approval }: { approval: ApprovalEvidenceView | null }): ReactNode {
  if (approval === null) return null
  return (
    <p className="text-muted" data-testid="evidence-approval-line">
      Asked {formatDateTime(approval.sent_at)}, answer due by {formatDateTime(approval.deadline)}.{' '}
      {approval.decided
        ? `A decision is recorded: ${approval.decision ?? 'unknown'}.`
        : 'No decision is recorded.'}{' '}
      {approval.replies} repl{approval.replies === 1 ? 'y' : 'ies'} received.
    </p>
  )
}

/** Every check the ledger holds for one track, with the two values each one compared. */
function RevalidationChecks({
  revalidation,
}: {
  revalidation: RevalidationEvidenceView | null
}): ReactNode {
  if (revalidation === null) {
    return (
      <p className="text-muted" data-testid="evidence-revalidation-absent">
        Nothing has been revalidated on this promise.
      </p>
    )
  }
  return (
    <div data-testid="evidence-revalidation" data-outcome={revalidation.outcome}>
      <p className="text-muted">
        Revalidation: {revalidation.outcome}
        {revalidation.detail === null ? null : <> — {revalidation.detail}</>}
      </p>
      <ul className="mt-1 space-y-0.5">
        {revalidation.checks.map((check) => (
          <li
            key={check.index}
            className="flex flex-wrap gap-x-2 font-mono text-state"
            data-testid="evidence-check"
            data-passed={check.passed}
          >
            <span className="text-muted">{check.name}</span>
            <span>expected {check.expected}</span>
            <span>actual {check.actual}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ------------------------------------------------------------------- 4. the technical record

/**
 * The identifiers, and the only place on the surface any of them appears.
 *
 * A reader who has opened three disclosures to get here has asked for exactly this, so nothing
 * is abbreviated to look tidy: a fingerprint that is shown truncated is a fingerprint nobody
 * can check against the row it came from.
 */
function TechnicalRecord({
  evidence,
  rows,
}: {
  evidence: EvidenceView
  rows: readonly Subject[]
}): ReactNode {
  return (
    <Disclosure summary="the technical record" testId="evidence-technical">
      <div className="mt-2 space-y-3 font-mono text-state" data-testid="evidence-technical-panel">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          <dt className="text-muted">case</dt>
          <dd className="break-all">{evidence.case_id}</dd>
          <dt className="text-muted">state</dt>
          <dd>
            {evidence.case_state} · v{evidence.case_version}
          </dd>
          <dt className="text-muted">plan</dt>
          <dd className="break-all">{evidence.plan_id}</dd>
          <dt className="text-muted">exception</dt>
          <dd className="break-all">
            <Value>{evidence.exception_id}</Value>
          </dd>
          {evidence.interpretation === null ? null : (
            <>
              <dt className="text-muted">reading</dt>
              <dd>
                {evidence.interpretation.source} · {evidence.interpretation.outcome ?? '—'} ·{' '}
                <Value>{evidence.interpretation.model_id}</Value>
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
                <th className="py-1 pr-3 font-normal">order</th>
                <th className="py-1 pr-3 font-normal">fingerprint</th>
                <th className="py-1 pr-3 font-normal">effects</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ track, promise }) => (
                <TechnicalRow key={track.track_id} track={track} promise={promise} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Disclosure>
  )
}

function TechnicalRow({
  track,
  promise,
}: {
  track: TrackEvidenceView
  promise: PromiseWorkspaceView | undefined
}): ReactNode {
  return (
    <tr
      className="border-t border-edge align-top"
      data-testid="evidence-row"
      data-promise-id={track.promise_id}
    >
      <td className="py-1 pr-3 break-all">{track.promise_id}</td>
      <td className="py-1 pr-3">
        {track.track_state}
        <div className="break-all text-muted">{track.track_id}</div>
      </td>
      <td className="py-1 pr-3">
        <Value>{track.rule_id}</Value>
        <div className="text-muted">
          <Value>{track.reason_detail}</Value>
        </div>
      </td>
      <td className="py-1 pr-3">
        {track.order_external_id} · v{track.order_external_version}
        {Object.entries(track.mirrored_versions).map(([line, version]) => (
          <div key={line} className="break-all text-muted">
            {line} → {version}
          </div>
        ))}
      </td>
      <td className="py-1 pr-3 break-all">
        <Value>{track.fingerprint}</Value>
        <div className="text-muted">
          {track.paths} path{track.paths === 1 ? '' : 's'} · {track.watched_entities} watched
        </div>
        {promise?.causal_chain.present === true ? (
          <div className="break-all text-muted" data-testid="evidence-node-refs">
            {promise.causal_chain.steps.map((step) => step.node_ref).join(' → ')}
          </div>
        ) : null}
      </td>
      <td className="py-1 pr-3">
        {track.effects.length === 0 && track.approval === null ? (
          <span className="text-muted">none</span>
        ) : (
          <>
            {track.effects.map((effect) => (
              <EffectRecord key={effect.idempotency_key} effect={effect} />
            ))}
            {track.approval === null ? null : (
              <div data-testid="evidence-approval">
                ASK · {track.approval.state} · <Value>{track.approval.provider_ref}</Value>
                <div className="text-muted">{track.approval.request_id}</div>
              </div>
            )}
          </>
        )}
      </td>
    </tr>
  )
}

/** One outbound effect, with the two identifiers that prove it happened and when it landed. */
function EffectRecord({ effect }: { effect: EffectEvidenceView }): ReactNode {
  return (
    <div data-testid="evidence-effect">
      {effect.kind} · {effect.state} · <Value>{effect.provider_ref}</Value>
      <div className="break-all text-muted">{effect.idempotency_key}</div>
      <div className="text-muted">
        {effect.attempts} attempt{effect.attempts === 1 ? '' : 's'} ·{' '}
        {effect.delivered_at === null ? 'not delivered' : formatDateTime(effect.delivered_at)}
        {effect.last_error === null ? null : <> · {effect.last_error}</>}
      </div>
    </div>
  )
}
