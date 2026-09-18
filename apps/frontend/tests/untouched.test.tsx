/**
 * The untouched set, which is the claim rather than the remainder.
 *
 * Every number here has to be the backend's, and the way to prove that on a screen is to hand it
 * a list and a count that disagree: a screen that counts its own rows follows the list, and a
 * screen that renders what it was published follows the count. The product's figure is the
 * count, so these tests assert the disagreement resolves that way.
 *
 * The rest is what may never appear: a completion treatment on a promise nothing was done to, a
 * faint edge back to an incident that never reached it, or silence where the domain gave a
 * reason.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import type { PromiseWorkspaceView } from '../src/api/types'
import { UntouchedProof } from '../src/features/case/Untouched'

const NOT_REACHED = 'Nothing in this case reaches this promise - it depends on none of it.'
const NOT_AT_RISK =
  'A path reaches this promise and nothing about it was put at risk - the quantity covers it.'

function untouched(
  id: string,
  externalId: string,
  customer: string,
  overrides: Partial<PromiseWorkspaceView> = {},
): PromiseWorkspaceView {
  return {
    promise_id: id,
    customer_name: customer,
    order_external_id: externalId,
    state: 'UNTOUCHED',
    phrase: 'left alone',
    authority: 'NONE',
    reason: 'NOT_REACHABLE',
    reason_phrase: 'the exception reaches nothing it depends on',
    deadline_at: null,
    consent: null,
    owner: 'NOBODY',
    next_action: 'Nothing. This promise is not reachable from what happened.',
    track_id: `track-${id}`,
    track_state: 'UNAFFECTED',
    classification: 'UNAFFECTED',
    rule_id: 'R-UNREACH',
    causal_chain: {
      present: false,
      steps: [],
      absence_reason: NOT_REACHED,
      path_count: 0,
      deciding_rule: null,
    },
    ...overrides,
  }
}

const THREE = [
  untouched('pr-d', 'EXT-D', 'Lena Havlik'),
  untouched('pr-e', 'EXT-E', 'Ahmed Bouazizi'),
  untouched('pr-f', 'EXT-F', 'Cafe Marlow'),
]

function draw(
  promises: PromiseWorkspaceView[],
  counts: { untouched?: number; effects?: number; universe?: number } = {},
): void {
  render(
    <UntouchedProof
      promises={promises}
      untouchedCount={counts.untouched ?? promises.length}
      untouchedEffectCount={counts.effects ?? 0}
      promiseCount={counts.universe ?? 6}
    />,
  )
}

describe('the proof', () => {
  it('publishes the backend’s count, its universe and its effect count', () => {
    draw(THREE)

    const proof = screen.getByTestId('untouched-proof')
    expect(proof).toHaveAttribute('data-untouched', '3')
    expect(proof).toHaveAttribute('data-universe', '6')
    expect(proof).toHaveAttribute('data-effects', '0')
    expect(proof).toHaveTextContent('left alone')
    expect(proof).toHaveTextContent('of 6 this case considered')
    expect(proof).toHaveTextContent('incident-caused effects on them')
  })

  it('follows the published count rather than the length of the list beside it', () => {
    // The backend counted four and handed over three rows. A screen that recounts publishes a
    // different figure from the product's own, which is the defect this asserts against.
    draw(THREE, { untouched: 4 })

    expect(screen.getByTestId('untouched-proof')).toHaveAttribute('data-untouched', '4')
    expect(screen.getAllByTestId('untouched-row')).toHaveLength(3)
    expect(within(screen.getByTestId('untouched-proof')).getAllByTestId('count')[0]).toHaveTextContent(
      '4',
    )
  })

  it('shows a non-zero effect count as the number it is', () => {
    draw(THREE, { effects: 2 })

    expect(screen.getByTestId('untouched-proof')).toHaveAttribute('data-effects', '2')
    expect(screen.getByTestId('untouched-proof')).toHaveTextContent('2')
  })

  it('stays visible and says so when the case left nothing alone', () => {
    draw([], { untouched: 0, universe: 3 })

    expect(screen.getByTestId('untouched-proof')).toHaveAttribute('data-untouched', '0')
    expect(screen.getByText('No promise in this case was left alone.')).toBeInTheDocument()
    expect(screen.queryByTestId('band-untouched')).not.toBeInTheDocument()
  })
})

describe('each untouched promise', () => {
  it('carries the domain’s own reason for not having been reached', () => {
    draw(THREE)

    const rows = screen.getAllByTestId('untouched-row')
    expect(rows.map((row) => row.getAttribute('data-promise-id'))).toEqual([
      'pr-d',
      'pr-e',
      'pr-f',
    ])
    for (const row of rows) {
      expect(within(row).getByTestId('causal-absence')).toHaveTextContent(NOT_REACHED)
    }
  })

  it('distinguishes never reached from reached and found safe, because the backend does', () => {
    draw([
      untouched('pr-d', 'EXT-D', 'Lena Havlik'),
      untouched('pr-e', 'EXT-E', 'Ahmed Bouazizi', {
        causal_chain: {
          present: false,
          steps: [],
          absence_reason: NOT_AT_RISK,
          path_count: 2,
          deciding_rule: null,
        },
      }),
    ])

    const rows = screen.getAllByTestId('untouched-row')
    expect(within(rows[0]!).getByTestId('causal-absence')).toHaveTextContent(NOT_REACHED)
    expect(within(rows[1]!).getByTestId('causal-absence')).toHaveTextContent(NOT_AT_RISK)
    // Two stored paths, and still no chain drawn: the count is the track's, not the display's.
    expect(within(rows[1]!).getByTestId('causal-path-count')).toHaveAttribute('data-paths', '2')
  })

  it('draws no edge and no node back to the incident', () => {
    draw(THREE)

    expect(screen.queryAllByTestId('causal-edge')).toHaveLength(0)
    expect(screen.queryAllByTestId('causal-node')).toHaveLength(0)
    for (const row of screen.getAllByTestId('untouched-row')) {
      expect(row).toHaveAttribute('data-chain', 'absent')
    }
  })

  it('is never drawn as an achievement', () => {
    draw(THREE)

    for (const status of screen.getAllByTestId('promise-status')) {
      expect(status).toHaveAttribute('data-state', 'UNTOUCHED')
      expect(status).toHaveAttribute('data-finished', 'false')
      expect(status).toHaveAttribute('data-tone', 'neutral')
      expect(status).toHaveTextContent('left alone')
    }
  })

  it('renders no node reference or rule identifier', () => {
    draw(THREE)

    const text = document.body.textContent ?? ''
    expect(text).not.toContain('R-UNREACH')
    expect(text).not.toContain('track-pr-d')
  })
})

// --------------------------------------------------------------- one sentence, not two

describe('the reason an untouched promise gives', () => {
  it('is the absence sentence alone when the backend sent one', () => {
    render(
      <UntouchedProof
        promises={[
          untouched('pr-e', 'EXT-E', 'Ahmed Bouazizi', {
            reason_phrase: 'the exception reaches nothing it depends on',
          }),
        ]}
        untouchedCount={1}
        untouchedEffectCount={0}
        promiseCount={6}
      />,
    )

    const row = screen.getByTestId('untouched-row')
    expect(within(row).getByTestId('causal-absence')).toHaveTextContent(NOT_REACHED)
    // The fuller sentence already carries the reason; printing the phrase as well made every
    // untouched row state its own conclusion twice.
    expect(row).not.toHaveTextContent('the exception reaches nothing it depends on')
  })

  it('falls back to the reason phrase when no absence sentence arrived', () => {
    render(
      <UntouchedProof
        promises={[
          untouched('pr-f', 'EXT-F', 'Cafe Marlow', {
            reason_phrase: 'what is already reserved for it still covers the need',
            causal_chain: {
              present: false,
              steps: [],
              absence_reason: null,
              path_count: 0,
              deciding_rule: null,
            },
          }),
        ]}
        untouchedCount={1}
        untouchedEffectCount={0}
        promiseCount={6}
      />,
    )

    const row = screen.getByTestId('untouched-row')
    expect(within(row).queryByTestId('causal-absence')).not.toBeInTheDocument()
    expect(row).toHaveTextContent('what is already reserved for it still covers the need')
  })
})

describe('a case that has assessed nothing claims nothing', () => {
  // `promise_count` is the case's own universe. While it is zero the case is still working out
  // what the report even means, and every figure this band exists to publish is unearned: the
  // zero has not been counted, it has merely not been reached yet. The band stays on the screen,
  // because the rule that it is never dropped is not suspended by an empty case — what changes
  // is what it is allowed to say.
  function mountEmpty(): void {
    render(
      <UntouchedProof
        promises={[]}
        untouchedCount={0}
        untouchedEffectCount={0}
        promiseCount={0}
      />,
    )
  }

  it('publishes no zero-effect proof before it has assessed a promise', () => {
    mountEmpty()
    expect(screen.queryByText(/incident-caused effect/)).not.toBeInTheDocument()
    expect(screen.queryByText(/this case considered/)).not.toBeInTheDocument()
    expect(screen.getByText('nothing assessed yet')).toBeInTheDocument()
  })

  it('does not say promises were left alone when none has been looked at', () => {
    mountEmpty()
    expect(screen.queryByText('No promise in this case was left alone.')).not.toBeInTheDocument()
    expect(screen.getByText(/claims nothing about what it left alone/)).toBeInTheDocument()
  })

  it('keeps the band itself, because an empty case is not a reason to drop it', () => {
    mountEmpty()
    expect(screen.getByTestId('untouched-proof')).toBeInTheDocument()
    expect(screen.getByText('nothing below this line was reached')).toBeInTheDocument()
  })

  it('still makes the claim once the case has a universe to make it about', () => {
    render(
      <UntouchedProof
        promises={[]}
        untouchedCount={0}
        untouchedEffectCount={0}
        promiseCount={6}
      />,
    )
    expect(screen.getByText('No promise in this case was left alone.')).toBeInTheDocument()
    expect(screen.getByText(/of 6 this case considered/)).toBeInTheDocument()
  })
})
