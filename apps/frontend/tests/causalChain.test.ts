/**
 * What the chain adapter is allowed to do with a stored traversal, and what it must never do.
 *
 * Almost every case here is a shape the canonical fixture does not have, which is the point: the
 * fixture is one path, three nodes long, with one promise per authority lane, and a screen that
 * only works for that shape is a screen that works for one demo. So the cases are a chain that
 * visits the same column twice, a track with more paths than it shows, a promise nothing reached,
 * a slot this build has never heard of, and a lane holding three promises at once.
 */
import { describe, expect, it } from 'vitest'
import type { CausalChainView, CausalStepView } from '../src/api/types'
import {
  CAUSAL_SLOTS,
  groupCausalChain,
  hasIncomingEdge,
  isCausalSlot,
} from '../src/features/case/causalChain'

function step(slot: string, label: string, nodeRef = `node-${label}`): CausalStepView {
  return { slot, label, detail: null, node_ref: nodeRef }
}

function chain(overrides: Partial<CausalChainView> = {}): CausalChainView {
  return {
    present: true,
    steps: [
      step('SHORTFALL', 'Valley Produce: Raspberries'),
      step('RESOURCE', 'Raspberries'),
      step('VERSION', 'Raspberry Charlotte v2'),
      step('PROMISE', 'Priya Nair - EXT-A'),
    ],
    absence_reason: null,
    path_count: 1,
    deciding_rule: 'R-PREAPPROVED',
    ...overrides,
  }
}

describe('placing a traversal in the fixed columns', () => {
  it('always returns the four columns in the same order, empty ones included', () => {
    const grouped = groupCausalChain(chain({ steps: [step('PROMISE', 'Priya Nair - EXT-A')] }))

    expect(grouped.columns.map((column) => column.slot)).toEqual([...CAUSAL_SLOTS])
    expect(grouped.columns.map((column) => column.steps.length)).toEqual([0, 0, 0, 1])
  })

  it('puts both steps in the column when a chain visits one twice', () => {
    const grouped = groupCausalChain(
      chain({
        steps: [
          step('SHORTFALL', 'Valley Produce: Raspberries'),
          step('RESOURCE', 'Raspberries'),
          step('VERSION', 'Raspberry Charlotte v2'),
          step('VERSION', 'the line on EXT-A'),
          step('PROMISE', 'Priya Nair - EXT-A'),
        ],
      }),
    )

    const version = grouped.columns.find((column) => column.slot === 'VERSION')!
    expect(version.steps.map((entry) => entry.label)).toEqual([
      'Raspberry Charlotte v2',
      'the line on EXT-A',
    ])
    // Five steps, four columns: the step's own index is never the column it lands in.
    expect(grouped.columns.map((column) => column.steps.length)).toEqual([1, 1, 2, 1])
  })

  it('keeps the backend’s order inside a column and never sorts it', () => {
    const grouped = groupCausalChain(
      chain({
        steps: [
          step('VERSION', 'zebra'),
          step('VERSION', 'alpha'),
          step('PROMISE', 'Priya Nair - EXT-A'),
        ],
      }),
    )

    const version = grouped.columns.find((column) => column.slot === 'VERSION')!
    expect(version.steps.map((entry) => entry.label)).toEqual(['zebra', 'alpha'])
  })

  it('carries a slot it has never heard of rather than dropping the step', () => {
    const grouped = groupCausalChain(
      chain({ steps: [step('SHORTFALL', 'Valley Produce'), step('KILN', 'something new')] }),
    )

    expect(isCausalSlot('KILN')).toBe(false)
    expect(grouped.unplaced.map((entry) => entry.label)).toEqual(['something new'])
    expect(grouped.columns.flatMap((column) => column.steps)).toHaveLength(1)
  })
})

describe('a promise nothing reached', () => {
  it('has no columns and carries the backend’s reason', () => {
    const grouped = groupCausalChain(
      chain({
        present: false,
        steps: [],
        absence_reason: 'Nothing in this case reaches this promise.',
        path_count: 0,
        deciding_rule: null,
      }),
    )

    expect(grouped.present).toBe(false)
    expect(grouped.occupied).toEqual([])
    expect(grouped.columns.every((column) => column.steps.length === 0)).toBe(true)
    expect(grouped.absenceReason).toBe('Nothing in this case reaches this promise.')
  })

  it('draws nothing from residual steps when the backend says no path is present', () => {
    const grouped = groupCausalChain(
      chain({ present: false, absence_reason: 'A path reaches this promise and nothing was at risk' }),
    )

    // `present` is the domain's answer about whether a path exists. The array is not a second
    // opinion, and the screen never overrides the first one with it.
    expect(grouped.columns.flatMap((column) => column.steps)).toEqual([])
    expect(grouped.unplaced).toEqual([])
  })
})

describe('the path count', () => {
  it('is the backend’s integer and not the number of steps shown', () => {
    const grouped = groupCausalChain(chain({ path_count: 3 }))

    expect(grouped.pathCount).toBe(3)
    expect(grouped.columns.flatMap((column) => column.steps)).toHaveLength(4)
  })

  it('survives a track that stored paths but shows none of them', () => {
    const grouped = groupCausalChain(
      chain({ present: false, steps: [], absence_reason: 'No deciding path.', path_count: 2 }),
    )

    expect(grouped.pathCount).toBe(2)
  })
})

describe('where an edge is drawn', () => {
  it('joins consecutive occupied columns and leaves the first one a source', () => {
    const grouped = groupCausalChain(chain())

    expect(grouped.occupied).toEqual(['SHORTFALL', 'RESOURCE', 'VERSION', 'PROMISE'])
    expect(hasIncomingEdge(grouped, 'SHORTFALL')).toBe(false)
    expect(hasIncomingEdge(grouped, 'PROMISE')).toBe(true)
  })

  it('joins across a column no step landed in, rather than through it', () => {
    const grouped = groupCausalChain(
      chain({
        steps: [step('SHORTFALL', 'Bench oven'), step('PROMISE', 'Priya Nair - EXT-A')],
      }),
    )

    expect(grouped.occupied).toEqual(['SHORTFALL', 'PROMISE'])
    expect(hasIncomingEdge(grouped, 'RESOURCE')).toBe(false)
    expect(hasIncomingEdge(grouped, 'PROMISE')).toBe(true)
  })

  it('gives an absent chain no edges at all', () => {
    const grouped = groupCausalChain(chain({ present: false, steps: [], absence_reason: 'none' }))

    for (const slot of CAUSAL_SLOTS) expect(hasIncomingEdge(grouped, slot)).toBe(false)
  })
})

describe('several promises in one authority lane', () => {
  it('groups each promise’s chain on its own, with nothing shared between them', () => {
    const lane = [
      chain({ steps: [step('SHORTFALL', 'Valley Produce'), step('PROMISE', 'Priya - EXT-A')] }),
      chain({
        steps: [
          step('SHORTFALL', 'Valley Produce'),
          step('RESOURCE', 'Raspberries'),
          step('PROMISE', 'Tomas - EXT-B'),
        ],
        path_count: 2,
      }),
      chain({ present: false, steps: [], absence_reason: 'Nothing reaches it.', path_count: 0 }),
    ]

    const grouped = lane.map(groupCausalChain)

    expect(grouped.map((entry) => entry.occupied)).toEqual([
      ['SHORTFALL', 'PROMISE'],
      ['SHORTFALL', 'RESOURCE', 'PROMISE'],
      [],
    ])
    expect(grouped.map((entry) => entry.pathCount)).toEqual([1, 2, 0])
    // Three chains from one lane: each one's own steps, with nothing merged into a shared
    // trunk and nothing carried from the promise above it.
    expect(grouped.map((entry) => entry.columns.flatMap((column) => column.steps).length)).toEqual(
      [2, 3, 0],
    )
    expect(grouped[2]!.absenceReason).toBe('Nothing reaches it.')
  })
})
