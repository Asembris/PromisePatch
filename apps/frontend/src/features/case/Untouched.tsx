/**
 * The promises the exception did not reach, and the proof that it did not reach them.
 *
 * This is the product's central claim, so it is built as a claim rather than as a leftover list.
 * Three things carry it, and all three are the backend's:
 *
 * - **How many were left alone, against how many the case considered.** Two published integers
 *   printed side by side. The denominator matters: a case that touched nothing proves nothing,
 *   and a case that left three of six alone has drawn a boundary.
 * - **How many operational effects the incident caused on them.** `untouched_effect_count` is
 *   counted from effect rows, not asserted, and it is the one number on this screen that a
 *   sceptical reader would most want to have been counted rather than declared.
 * - **Why each one was not reached**, in the domain's own sentence — and the sentence is not the
 *   same sentence twice. A promise nothing reaches was never in danger; a promise a path reaches
 *   and finds nothing at risk was checked and cleared. Saying the first where the second is true
 *   would be exactly the kind of tidy overstatement this product exists not to make.
 *
 * Quiet ground, never a success treatment, never collapsed, and never the thing that goes when
 * the viewport gets small. "Left alone" is the absence of an effect; a tick here would claim the
 * product had done something to an order it deliberately did not touch.
 */
import type { ReactNode } from 'react'
import type { PromiseWorkspaceView } from '../../api/types'
import { PromiseStatePill } from '../../components/badges'
import { BoundaryRule, QuietCard } from '../../components/surfaces'
import { Count } from '../../components/values'
import { CausalAbsence, CausalPathCount } from '../../components/causal'
import { groupCausalChain } from './causalChain'

export function UntouchedProof({
  promises,
  untouchedCount,
  untouchedEffectCount,
  promiseCount,
}: {
  promises: readonly PromiseWorkspaceView[]
  untouchedCount: number
  untouchedEffectCount: number
  promiseCount: number
}): ReactNode {
  return (
    <div className="space-y-3">
      <BoundaryRule>nothing below this line was reached</BoundaryRule>

      <div
        className="flex flex-wrap items-baseline gap-x-6 gap-y-2"
        data-testid="untouched-proof"
        data-untouched={untouchedCount}
        data-effects={untouchedEffectCount}
        data-universe={promiseCount}
      >
        {/* Two integers with a word between them, and no arithmetic anywhere near it: the
            denominator is the case's own universe and the backend publishes both figures. */}
        <span className="inline-flex items-baseline gap-1.5">
          <Count value={untouchedCount} label="left alone" />
          <span className="text-label text-muted uppercase">
            of {promiseCount} this case considered
          </span>
        </span>
        <Count value={untouchedEffectCount} label="incident-caused effects on them" />
      </div>

      {promises.length === 0 ? (
        <QuietCard className="px-4 py-3 text-sm text-muted">
          No promise in this case was left alone.
        </QuietCard>
      ) : (
        <ul className="grid gap-2 lg:grid-cols-2" data-testid="band-untouched">
          {promises.map((promise) => (
            <li key={promise.promise_id}>
              <UntouchedRow promise={promise} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * One promise nothing was done to.
 *
 * It has no causal column, and the empty space where one would be is the point: there is no path
 * to draw, so none is drawn, and what stands in its place is the domain's sentence saying so.
 * Nothing here invents a dashed edge, a ghost node or a faded connector back to the incident —
 * an edge that exists faintly is still an edge, and there is no path here to be faint about.
 */
function UntouchedRow({ promise }: { promise: PromiseWorkspaceView }): ReactNode {
  const chain = groupCausalChain(promise.causal_chain)

  return (
    <QuietCard
      className="h-full px-4 py-2.5"
      data-testid="untouched-row"
      data-promise-id={promise.promise_id}
      data-state={promise.state}
      data-chain={chain.present ? 'present' : 'absent'}
    >
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span className="text-sm font-medium">{promise.customer_name}</span>
        <span className="font-mono text-state text-muted">{promise.order_external_id}</span>
        <span className="ml-auto">
          <PromiseStatePill state={promise.state} phrase={promise.phrase} />
        </span>
      </div>

      <p className="mt-1 text-reason text-muted">{promise.reason}</p>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <CausalAbsence reason={chain.absenceReason} />
        {chain.pathCount > 1 ? <CausalPathCount value={chain.pathCount} /> : null}
      </div>
    </QuietCard>
  )
}
