/**
 * A stored traversal, arranged into the four fixed columns the dependency view is drawn in.
 *
 * This module is the whole of the screen's involvement with a causal chain, and it is
 * deliberately the dullest code in the feature: it **places** steps, and it decides nothing
 * about them. Every label, every detail, the reason a promise was not reached and the number of
 * paths a track holds are the backend's strings and the backend's integers, carried through
 * untouched.
 *
 * Four rules, each of which is a way the screen could have lied and does not.
 *
 * 1. **A step is placed by its own slot, never by where it sits in the array.** A supply path
 *    runs through a recipe version and then the order line pinning it, and both are the version
 *    column, so the third step of one chain and the fourth of another land in the same place. An
 *    index-to-column mapping would put them in different ones and invite a judge to compare
 *    positions that mean nothing.
 * 2. **`present` is the backend's answer and it is final.** When it is false there is no chain,
 *    whatever else arrived, and what the screen shows instead is the sentence saying why. A
 *    column drawn from residual steps under a `false` would be the screen asserting a path the
 *    domain declined to assert.
 * 3. **Nothing is dropped.** A slot this build has never heard of does not silently disappear: it
 *    is carried out in `unplaced`, so a chain that grows a fifth kind of node renders short of
 *    the design rather than short of the truth.
 * 4. **`pathCount` is copied, never counted.** It is how many traversals the track stored, which
 *    is not the length of the one being shown, and the two are different numbers for every
 *    multi-path track in the product.
 */
import type { CausalChainView, CausalStepView } from '../../api/types'

/** The four columns, in the order a judge reads them. `promisepatch.domain.causal.CausalSlot`. */
export const CAUSAL_SLOTS = ['SHORTFALL', 'RESOURCE', 'VERSION', 'PROMISE'] as const

export type CausalSlot = (typeof CAUSAL_SLOTS)[number]

/**
 * The fixed geometry's own column names, from the contract's dependency view.
 *
 * These label *positions*, not values: they are the same four words on every row of every case,
 * and none of them makes a claim about the promise beside it. Everything that is about this
 * promise — what failed, what it fell short of, what the order pins — is the backend's label on
 * the step itself.
 */
export const CAUSAL_SLOT_LABEL: Record<CausalSlot, string> = {
  SHORTFALL: 'what did not arrive',
  RESOURCE: 'what it fell short of',
  VERSION: 'the version the order pins',
  PROMISE: 'the promise',
}

const CAUSAL_SLOT_SET: ReadonlySet<string> = new Set<string>(CAUSAL_SLOTS)

export function isCausalSlot(value: string): value is CausalSlot {
  return CAUSAL_SLOT_SET.has(value)
}

export interface CausalColumn {
  slot: CausalSlot
  /** The fixed position label. Never a sentence about this promise. */
  label: string
  /** The steps that belong in this column, in the order the backend stored them. */
  steps: readonly CausalStepView[]
}

export interface GroupedCausalChain {
  present: boolean
  /** Always four, always in `CAUSAL_SLOTS` order, empty ones included. */
  columns: readonly CausalColumn[]
  /**
   * The columns that actually carry a step.
   *
   * An edge is drawn between consecutive members of this list and nowhere else, so a chain that
   * skips a column is joined across the gap rather than through a node that does not exist.
   */
  occupied: readonly CausalSlot[]
  /** Steps whose slot this build does not know. Shown, never discarded. */
  unplaced: readonly CausalStepView[]
  /** The backend's sentence for why nothing reached this promise, when nothing did. */
  absenceReason: string | null
  /** Every traversal stored for this track. Not `steps.length`, and never recomputed here. */
  pathCount: number
}

const EMPTY_COLUMNS: readonly CausalColumn[] = CAUSAL_SLOTS.map((slot) => ({
  slot,
  label: CAUSAL_SLOT_LABEL[slot],
  steps: [],
}))

/**
 * One promise's chain, arranged for the fixed columns.
 *
 * Total: every `CausalChainView` the backend can send has an answer here, including one whose
 * steps are empty, whose slots are unknown, or whose `present` contradicts its own array.
 */
export function groupCausalChain(chain: CausalChainView): GroupedCausalChain {
  if (!chain.present) {
    return {
      present: false,
      columns: EMPTY_COLUMNS,
      occupied: [],
      unplaced: [],
      absenceReason: chain.absence_reason,
      pathCount: chain.path_count,
    }
  }

  const placed = new Map<CausalSlot, CausalStepView[]>(CAUSAL_SLOTS.map((slot) => [slot, []]))
  const unplaced: CausalStepView[] = []
  for (const step of chain.steps) {
    if (isCausalSlot(step.slot)) placed.get(step.slot)?.push(step)
    else unplaced.push(step)
  }

  const columns = CAUSAL_SLOTS.map((slot) => ({
    slot,
    label: CAUSAL_SLOT_LABEL[slot],
    steps: placed.get(slot) ?? [],
  }))

  return {
    present: true,
    columns,
    occupied: columns.filter((column) => column.steps.length > 0).map((column) => column.slot),
    unplaced,
    absenceReason: chain.absence_reason,
    pathCount: chain.path_count,
  }
}

/**
 * Whether an edge is drawn into this column from the one before it.
 *
 * The first occupied column is a source and takes no incoming edge; every later one is joined to
 * whichever occupied column precedes it. Nothing is joined to an empty column, so no edge on the
 * screen crosses a node that was never stored.
 */
export function hasIncomingEdge(grouped: GroupedCausalChain, slot: CausalSlot): boolean {
  const position = grouped.occupied.indexOf(slot)
  return position > 0
}
