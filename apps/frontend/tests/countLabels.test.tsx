/**
 * The word beside a backend count, at every count the backend can publish.
 *
 * `threatened_count` is an integer and it is frequently one — a single-order incident is the
 * ordinary small case, not an edge. "1 ORDERS AFFECTED" is the first thing a reader sees on
 * one, and a surface that cannot count to one has spent the credibility it needs for the
 * number that matters, which is the zero on the untouched band.
 *
 * What is asserted here is only the *word*. The figure itself is the backend's and is rendered
 * unchanged — these tests pass the count in and expect it back, so a future convenience that
 * started deriving, rounding or pluralising the number rather than the noun fails here.
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Count } from '../src/components/values'

function label(): string {
  return screen.getByTestId('count').textContent ?? ''
}

describe('a count names what it counts', () => {
  it('uses the singular wording at exactly one', () => {
    render(<Count value={1} label="orders affected" one="order affected" />)
    expect(label()).toContain('order affected')
    expect(label()).not.toContain('orders affected')
  })

  it('uses the plural wording at zero, which is the count the product exists to publish', () => {
    render(<Count value={0} label="incident-caused effects on them" one="incident-caused effect" />)
    expect(label()).toContain('incident-caused effects on them')
  })

  it('uses the plural wording above one', () => {
    render(<Count value={4} label="orders affected" one="order affected" />)
    expect(label()).toContain('orders affected')
  })

  it('keeps the one wording it was given when no singular was supplied', () => {
    render(<Count value={1} label="left alone" />)
    expect(label()).toContain('left alone')
  })

  it('renders the backend figure unchanged, and composes no other number', () => {
    render(<Count value={6} label="orders affected" one="order affected" />)
    expect(screen.getByTestId('count').textContent).toBe('6orders affected')
  })
})
