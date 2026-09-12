/**
 * One incident, and every promise it reached, drawn as the path that reached it.
 *
 * This is the product's differentiator on a screen: a judge should see that *one* thing went
 * wrong, that it travelled along stored dependencies, and that where it arrived decided who has
 * to give permission — without reading a word of explanation from the interface.
 *
 * Four decisions, each of which is a constraint rather than a preference.
 *
 * **Every row draws its own chain.** Three promises in one authority lane are three traversals,
 * and none of them is merged into a shared trunk, because a line a judge reads as one path has
 * to be one path that actually happened. The repetition of a source across rows is how the
 * common cause becomes visible; it is not something to optimise away by drawing the node once
 * and fanning out of it.
 *
 * **The geometry is local to a row.** Each edge is laid out by the same flex box that lays out
 * the nodes on either side of it, so nothing measures a rectangle and nothing holds a constant
 * for how many promises a lane contains. A single overlay across the map has to know both, and
 * goes stale the first time a lane holds two orders.
 *
 * **Columns are positions, not steps.** A chain that runs through a recipe version and then the
 * order line pinning it puts two nodes in the version column, and a chain that reaches a promise
 * through equipment puts none in it at all. The column a node lands in is its own slot; its
 * index in the array decides nothing.
 *
 * **Nothing here says whether anything happened.** The lane colour is whose permission a change
 * needs; the promise's own pill is what the domain says has actually been done. A `PLANNED` case
 * draws a complete map with no completion mark anywhere on it, because permission is not an act.
 */
import type { ReactNode } from 'react'
import type { AuthorityBandView, CausalStepView, PromiseWorkspaceView } from '../../api/types'
import { PromiseStatePill, StateMarker } from '../../components/badges'
import { Card, QuietCard, SectionLabel } from '../../components/surfaces'
import {
  CausalAbsence,
  CausalColumnHeading,
  CausalEdge,
  CausalNode,
  CausalPathCount,
} from '../../components/causal'
import { formatDateTime } from '../../components/time'
import { authorityTone } from '../../components/vocabulary'
import {
  CAUSAL_SLOTS,
  groupCausalChain,
  hasIncomingEdge,
  type GroupedCausalChain,
} from './causalChain'

/**
 * The four fixed columns, and the gaps between them.
 *
 * Below the map's width the same seven cells stack in the same order, so the traversal reads
 * top-to-bottom instead of left-to-right and no node is dropped to make it fit. The template is
 * shared by the heading row and by every promise row, which is what keeps a column in the same
 * place on every row of every lane.
 */
const CHAIN_GRID =
  'grid grid-cols-1 items-center gap-x-2 gap-y-1 xl:grid-cols-[1.05fr_auto_0.85fr_auto_1fr_auto_1.7fr]'

/** The incident, and the promises it reached, under the authority each one answers to. */
export function PropagationMap({
  bands,
  exceptionCategory,
  reportedText,
}: {
  bands: readonly AuthorityBandView[]
  exceptionCategory: string | null
  reportedText: string | null
}): ReactNode {
  return (
    <div className="space-y-3">
      <SectionLabel>what changes, under whose authority</SectionLabel>
      <IncidentSource category={exceptionCategory} reportedText={reportedText} />
      {bands.length === 0 ? (
        <QuietCard className="px-4 py-3 text-sm text-muted">
          Nothing has been decided about any promise yet.
        </QuietCard>
      ) : (
        <div className="space-y-3" data-testid="band-what-changes">
          <ColumnHeadings />
          {bands.map((band) => (
            <AuthorityLane key={band.authority} band={band} />
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * Where the paths start.
 *
 * One incident is the whole premise, so it is drawn once, above the lanes, and the lanes hang
 * beneath it. It carries what the worker said and what the domain filed it as — and no count of
 * its own, because the numbers on this case are published once, in band 1.
 */
function IncidentSource({
  category,
  reportedText,
}: {
  category: string | null
  reportedText: string | null
}): ReactNode {
  return (
    <div className="space-y-0" data-testid="incident-source">
      <Card className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5">
        <span className="text-label text-muted uppercase">the incident</span>
        {category === null ? null : (
          <span className="font-mono text-state text-owner">{category}</span>
        )}
        {reportedText === null ? null : (
          <span className="min-w-0 text-reason text-muted">“{reportedText}”</span>
        )}
      </Card>
      <span
        aria-hidden="true"
        data-testid="incident-edge"
        className="flex justify-start pl-6 text-edge-strong"
      >
        <span className="h-3 w-[1.5px] rounded-full bg-current opacity-70" />
      </span>
    </div>
  )
}

/** The four position labels, once, aligned to the columns every row below them uses. */
function ColumnHeadings(): ReactNode {
  return (
    <div className={`${CHAIN_GRID} hidden px-4 xl:grid`} aria-hidden="true">
      {CAUSAL_SLOTS.map((slot, index) => (
        <ChainCellPair key={slot} index={index}>
          <CausalColumnHeading>{COLUMN_LABEL[slot]}</CausalColumnHeading>
        </ChainCellPair>
      ))}
    </div>
  )
}

const COLUMN_LABEL: Record<(typeof CAUSAL_SLOTS)[number], string> = {
  SHORTFALL: 'what did not arrive',
  RESOURCE: 'what it fell short of',
  VERSION: 'the version pinned',
  PROMISE: 'the promise',
}

/** A heading cell, with the empty gap cell that keeps it over its column. */
function ChainCellPair({ index, children }: { index: number; children: ReactNode }): ReactNode {
  return (
    <>
      {index === 0 ? null : <span />}
      <div className="min-w-0">{children}</div>
    </>
  )
}

/**
 * One authority group.
 *
 * The heading is the backend's title and the count is the backend's integer — the lane renders
 * as many rows as it was handed, and says as many as it was told, and the two are separate
 * claims on purpose.
 */
function AuthorityLane({ band }: { band: AuthorityBandView }): ReactNode {
  return (
    <section
      className="space-y-1.5"
      data-testid="authority-band"
      data-authority={band.authority}
      data-count={band.count}
    >
      <h3 className="flex items-center gap-2 px-1 text-sm font-semibold">
        <StateMarker marker="filled" tone={authorityTone(band.authority)} />
        {band.title}
      </h3>
      <ul className="space-y-1.5">
        {band.promises.map((promise) => (
          <PromiseLaneRow key={promise.promise_id} promise={promise} band={band} />
        ))}
      </ul>
    </section>
  )
}

/**
 * One promise, and the path that reached it.
 *
 * The row is the same shape whether its chain is two nodes long or five, and whether it is the
 * only promise in its lane or the third of three.
 */
function PromiseLaneRow({
  promise,
  band,
}: {
  promise: PromiseWorkspaceView
  band: AuthorityBandView
}): ReactNode {
  const chain = groupCausalChain(promise.causal_chain)
  const tone = authorityTone(band.authority)

  return (
    <li>
      <Card
        className="group px-4 py-2 transition-colors hover:border-edge-strong focus-visible:border-edge-strong"
        tabIndex={0}
        data-testid="promise-row"
        data-promise-id={promise.promise_id}
        data-state={promise.state}
        data-chain={chain.present ? 'present' : 'absent'}
      >
        {chain.present ? (
          <div className={CHAIN_GRID}>
            {chain.columns.map((column, index) => (
              <ChainColumn
                key={column.slot}
                steps={column.steps}
                tone={tone}
                incoming={hasIncomingEdge(chain, column.slot)}
                first={index === 0}
                terminal={column.slot === 'PROMISE'}
                promise={promise}
                chain={chain}
              />
            ))}
          </div>
        ) : (
          <div className="space-y-1">
            <PromiseIdentity promise={promise} />
            <CausalAbsence reason={chain.absenceReason} />
            <PromiseReading promise={promise} chain={chain} />
          </div>
        )}

        {chain.unplaced.length === 0 ? null : (
          <div className="mt-1.5 flex flex-wrap gap-2" data-testid="chain-unplaced">
            {chain.unplaced.map((step) => (
              <CausalNode key={step.node_ref} label={step.label} detail={step.detail} />
            ))}
          </div>
        )}
      </Card>
    </li>
  )
}

/**
 * One column of one row.
 *
 * The terminal column is the promise itself: the chain's last node *is* this row's subject, so
 * it is drawn as the promise — its customer, its order and the domain's own reading of it —
 * rather than as a chip repeating what the row is already about.
 */
function ChainColumn({
  steps,
  tone,
  incoming,
  first,
  terminal,
  promise,
  chain,
}: {
  steps: readonly CausalStepView[]
  tone: ReturnType<typeof authorityTone>
  incoming: boolean
  first: boolean
  terminal: boolean
  promise: PromiseWorkspaceView
  chain: GroupedCausalChain
}): ReactNode {
  return (
    <>
      {first ? null : incoming ? <CausalEdge tone={tone} /> : <span />}
      <div className="min-w-0" data-testid="chain-column" data-occupied={steps.length}>
        {terminal ? (
          <div className="space-y-1">
            <PromiseIdentity promise={promise} />
            <PromiseReading promise={promise} chain={chain} />
          </div>
        ) : (
          steps.map((step, index) => (
            <div key={step.node_ref}>
              {index === 0 ? null : <CausalEdge tone={tone} orientation="vertical" />}
              <CausalNode label={step.label} detail={step.detail} emphasis={first} />
            </div>
          ))
        )}
      </div>
    </>
  )
}

/** Who the promise is for, and what the domain says about it. Both are backend strings. */
function PromiseIdentity({ promise }: { promise: PromiseWorkspaceView }): ReactNode {
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
      <span className="text-name font-semibold">{promise.customer_name}</span>
      <span className="font-mono text-state text-muted">{promise.order_external_id}</span>
      <PromiseStatePill state={promise.state} phrase={promise.phrase} />
    </div>
  )
}

/**
 * What the domain says about this promise, beside the promise itself.
 *
 * It sits in the terminal column rather than on a line of its own under the row, because that
 * is where the path arrives: the reason, the customer's clock and the one next action are all
 * statements about the node the chain ends on, and putting them there costs a laptop viewport
 * one line per promise rather than two.
 */
function PromiseReading({
  promise,
  chain,
}: {
  promise: PromiseWorkspaceView
  chain: GroupedCausalChain
}): ReactNode {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-reason">
      <span className="text-muted">
        <span>{promise.reason}</span>
        {promise.deadline_at === null ? null : <> · by {formatDateTime(promise.deadline_at)}</>}
      </span>
      {chain.pathCount > 1 ? <CausalPathCount value={chain.pathCount} /> : null}
      <span className="w-full text-muted" data-testid="promise-next-action">
        <span className="text-label uppercase">next </span>
        {promise.next_action}
      </span>
    </div>
  )
}
