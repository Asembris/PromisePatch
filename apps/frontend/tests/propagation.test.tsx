/**
 * What the propagation map must draw, and what it must never draw.
 *
 * The shapes here are the ones the canonical case does not have. A lane with one promise, one
 * path and one node per column is the easy case and it is the one the prototype proved; these
 * tests are three promises in a single lane, a chain that visits a column twice, a track that
 * stored more paths than it shows, and a threatened promise with no readable path at all.
 *
 * Two of the assertions are about absence rather than presence, and they are the important ones:
 * an identifier must never reach the map, and a `PLANNED` case must carry no finished treatment
 * anywhere on it — permission is not an act, and a tick drawn before the order system agreed
 * would be the product claiming something nobody has done.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import type {
  AuthorityBandView,
  CausalChainView,
  CausalStepView,
  PromiseWorkspaceView,
} from '../src/api/types'
import { PropagationMap } from '../src/features/case/Propagation'

const NODE_REF = 'cl-0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0'

function step(slot: string, label: string, detail: string | null = null): CausalStepView {
  return { slot, label, detail, node_ref: `${NODE_REF}:${label}` }
}

function chain(overrides: Partial<CausalChainView> = {}): CausalChainView {
  return {
    present: true,
    steps: [
      step('SHORTFALL', 'Valley Produce: Raspberries', '4 kg expected, none received'),
      step('RESOURCE', 'Raspberries', 'needed 4 kg, 1.2 kg available, 2.8 kg short'),
      step('VERSION', 'Raspberry Charlotte v2', 'used as the filling'),
      step('PROMISE', 'Priya Nair - EXT-A'),
    ],
    absence_reason: null,
    path_count: 1,
    deciding_rule: 'R-PREAPPROVED',
    ...overrides,
  }
}

function promise(
  id: string,
  externalId: string,
  customer: string,
  overrides: Partial<PromiseWorkspaceView> = {},
): PromiseWorkspaceView {
  return {
    promise_id: id,
    customer_name: customer,
    order_external_id: externalId,
    state: 'PLANNED',
    phrase: 'planned - waiting for you',
    authority: 'STANDING_PREFERENCE',
    reason: 'PREAPPROVAL_COVERS',
    reason_phrase: 'the order already pre-approves this substitution',
    deadline_at: null,
    owner: 'YOU',
    next_action: 'Read the plan and confirm it, or leave it as it is.',
    track_id: `track-${id}`,
    track_state: 'PENDING',
    classification: 'AUTO_RECOVERABLE',
    rule_id: 'R-PREAPPROVED',
    causal_chain: chain(),
    ...overrides,
  }
}

function band(
  authority: string,
  title: string,
  promises: PromiseWorkspaceView[],
  count = promises.length,
): AuthorityBandView {
  return { authority, title, promises, count }
}

function draw(bands: AuthorityBandView[]): void {
  render(
    <PropagationMap
      bands={bands}
      exceptionPhrase="a supplier delivery did not arrive"
      reportedText="today’s raspberry delivery didn’t arrive"
    />,
  )
}

const LANE = [band('STANDING_PREFERENCE', 'Covered by a standing preference', [promise('pr-a', 'EXT-A', 'Priya Nair')])]

describe('the incident, as the source', () => {
  it('is drawn once, above the lanes, with the worker’s own words', () => {
    draw(LANE)

    const source = screen.getByTestId('incident-source')
    expect(within(source).getByText(/raspberry delivery/)).toBeInTheDocument()
    expect(within(source).getByText('a supplier delivery did not arrive')).toBeInTheDocument()
    expect(screen.getAllByTestId('incident-source')).toHaveLength(1)
  })
})

describe('several promises in one authority lane', () => {
  it('gives each of them its own chain, with no shared trunk between them', () => {
    draw([
      band('CUSTOMER', 'Needs the customer', [
        promise('pr-b', 'EXT-B', 'Tomas Lindqvist', { authority: 'CUSTOMER' }),
        promise('pr-c', 'EXT-C', 'Okafor-Reyes wedding', { authority: 'CUSTOMER' }),
        promise('pr-d', 'EXT-D', 'Lena Havlik', { authority: 'CUSTOMER' }),
      ]),
    ])

    const lanes = screen.getAllByTestId('authority-band')
    expect(lanes).toHaveLength(1)
    const rows = within(lanes[0]!).getAllByTestId('promise-row')
    expect(rows.map((row) => row.getAttribute('data-promise-id'))).toEqual([
      'pr-b',
      'pr-c',
      'pr-d',
    ])
    // Three rows, three sources: the common cause is visible because it is drawn three times,
    // never because three rows were merged into one trunk.
    for (const row of rows) {
      expect(within(row).getByText('Valley Produce: Raspberries')).toBeInTheDocument()
    }
    expect(screen.getAllByText('Valley Produce: Raspberries')).toHaveLength(3)
  })

  it('keeps every lane the backend sent, in the order it sent them', () => {
    draw([
      band('STANDING_PREFERENCE', 'Covered by a standing preference', [
        promise('pr-a', 'EXT-A', 'Priya Nair'),
      ]),
      band('CUSTOMER', 'Needs the customer', [
        promise('pr-b', 'EXT-B', 'Tomas Lindqvist', { authority: 'CUSTOMER' }),
        promise('pr-c', 'EXT-C', 'Ines Ferreira', { authority: 'CUSTOMER' }),
      ]),
    ])

    const lanes = screen.getAllByTestId('authority-band')
    expect(lanes.map((lane) => lane.getAttribute('data-authority'))).toEqual([
      'STANDING_PREFERENCE',
      'CUSTOMER',
    ])
    expect(within(lanes[1]!).getAllByTestId('promise-row')).toHaveLength(2)
    expect(lanes[1]!).toHaveAttribute('data-count', '2')
  })
})

describe('a chain that visits one column twice', () => {
  it('draws both nodes in that column, in the order they were stored', () => {
    draw([
      band('STANDING_PREFERENCE', 'Covered by a standing preference', [
        promise('pr-a', 'EXT-A', 'Priya Nair', {
          causal_chain: chain({
            steps: [
              step('SHORTFALL', 'Valley Produce: Raspberries'),
              step('RESOURCE', 'Raspberries'),
              step('VERSION', 'Raspberry Charlotte v2'),
              step('VERSION', 'the line on EXT-A'),
              step('PROMISE', 'Priya Nair - EXT-A'),
            ],
          }),
        }),
      ]),
    ])

    const row = screen.getByTestId('promise-row')
    const columns = within(row).getAllByTestId('chain-column')
    expect(columns.map((column) => column.getAttribute('data-occupied'))).toEqual([
      '1',
      '1',
      '2',
      '1',
    ])
    const version = columns[2]!
    expect(
      within(version)
        .getAllByTestId('causal-node')
        .map((node) => node.textContent),
    ).toEqual(['Raspberry Charlotte v2', 'the line on EXT-A'])
  })
})

describe('the path count', () => {
  it('is the backend’s integer, not the number of nodes drawn', () => {
    draw([
      band('STANDING_PREFERENCE', 'Covered by a standing preference', [
        promise('pr-a', 'EXT-A', 'Priya Nair', { causal_chain: chain({ path_count: 3 }) }),
      ]),
    ])

    const row = screen.getByTestId('promise-row')
    expect(within(row).getByTestId('causal-path-count')).toHaveAttribute('data-paths', '3')
    expect(within(row).getByTestId('causal-path-count')).toHaveTextContent('3')
    // Three nodes are drawn beside a figure of three paths, and the two are different things.
    expect(within(row).getAllByTestId('causal-node')).toHaveLength(3)
  })

  it('is left off a track that holds a single path', () => {
    draw(LANE)

    expect(screen.queryByTestId('causal-path-count')).not.toBeInTheDocument()
  })
})

describe('a threatened promise with no readable path', () => {
  it('states the backend’s reason and draws no edge at all', () => {
    draw([
      band('OWNER', 'Needs the owner', [
        promise('pr-c', 'EXT-C', 'Okafor-Reyes wedding', {
          authority: 'OWNER',
          causal_chain: {
            present: false,
            steps: [],
            absence_reason: 'No stored path carries the rule that decided this promise.',
            path_count: 2,
            deciding_rule: null,
          },
        }),
      ]),
    ])

    const row = screen.getByTestId('promise-row')
    expect(row).toHaveAttribute('data-chain', 'absent')
    expect(within(row).getByTestId('causal-absence')).toHaveTextContent(
      'No stored path carries the rule that decided this promise.',
    )
    expect(within(row).queryAllByTestId('causal-edge')).toHaveLength(0)
    expect(within(row).queryAllByTestId('causal-node')).toHaveLength(0)
    // The promise is still named, still stated, and still carries its own next action.
    expect(within(row).getByText('Okafor-Reyes wedding')).toBeInTheDocument()
    expect(within(row).getByTestId('promise-next-action')).toBeInTheDocument()
  })
})

describe('a payload that carries no chain', () => {
  it('renders the promise and no causal column, and makes no claim about reachability', () => {
    const older: Record<string, unknown> = { ...promise('pr-a', 'EXT-A', 'Priya Nair') }
    delete older.causal_chain
    draw([
      band('STANDING_PREFERENCE', 'Covered by a standing preference', [
        older as unknown as PromiseWorkspaceView,
      ]),
    ])

    const row = screen.getByTestId('promise-row')
    expect(row).toHaveAttribute('data-chain', 'absent')
    expect(within(row).getByText('Priya Nair')).toBeInTheDocument()
    expect(within(row).getByTestId('promise-next-action')).toBeInTheDocument()
    expect(within(row).queryAllByTestId('causal-edge')).toHaveLength(0)
    expect(within(row).queryByTestId('causal-absence')).not.toBeInTheDocument()
  })
})

describe('reading the row by keyboard', () => {
  it('makes every promise row focusable, so the path emphasis is not hover-only', () => {
    draw([
      band('CUSTOMER', 'Needs the customer', [
        promise('pr-b', 'EXT-B', 'Tomas Lindqvist', { authority: 'CUSTOMER' }),
        promise('pr-c', 'EXT-C', 'Ines Ferreira', { authority: 'CUSTOMER' }),
      ]),
    ])

    for (const row of screen.getAllByTestId('promise-row')) {
      expect(row).toHaveAttribute('tabindex', '0')
    }
  })
})

describe('what the map may never carry', () => {
  it('renders no node reference anywhere on it', () => {
    draw([
      band('CUSTOMER', 'Needs the customer', [
        promise('pr-b', 'EXT-B', 'Tomas Lindqvist', { authority: 'CUSTOMER' }),
        promise('pr-c', 'EXT-C', 'Ines Ferreira', { authority: 'CUSTOMER' }),
      ]),
    ])

    expect(document.body.textContent ?? '').not.toContain(NODE_REF)
  })

  it('renders no rule identifier on a promise row', () => {
    draw(LANE)

    expect(screen.getByTestId('promise-row').textContent ?? '').not.toContain('R-PREAPPROVED')
  })

  it('puts no finished treatment on a planned case', () => {
    draw([
      band('STANDING_PREFERENCE', 'Covered by a standing preference', [
        promise('pr-a', 'EXT-A', 'Priya Nair'),
      ]),
      band('CUSTOMER', 'Needs the customer', [
        promise('pr-b', 'EXT-B', 'Tomas Lindqvist', { authority: 'CUSTOMER' }),
      ]),
    ])

    for (const status of screen.getAllByTestId('promise-status')) {
      expect(status).toHaveAttribute('data-finished', 'false')
      expect(status).not.toHaveAttribute('data-tone', 'done')
      expect(status).toHaveTextContent('planned - waiting for you')
    }
  })

  it('draws a recovered promise as finished only because the backend said so', () => {
    draw([
      band('STANDING_PREFERENCE', 'Covered by a standing preference', [
        promise('pr-a', 'EXT-A', 'Priya Nair', { state: 'RECOVERED', phrase: 'changed' }),
      ]),
    ])

    const status = screen.getByTestId('promise-status')
    expect(status).toHaveAttribute('data-state', 'RECOVERED')
    expect(status).toHaveAttribute('data-finished', 'true')
  })
})
