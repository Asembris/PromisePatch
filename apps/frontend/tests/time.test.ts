/**
 * A date and time on the screen says which clock it is in.
 *
 * The rows render a moment in the reader's own clock, and the backend's sentences beside them
 * say the same moment in a clock they name. Unlabelled, a deadline an hour apart in two places
 * on one screen reads as two deadlines — so the formatter carries the zone, and this holds it to
 * the zone the runtime itself would name for that instant, whatever zone the test runs in.
 */
import { describe, expect, it } from 'vitest'
import { formatDateTime } from '../src/components/time'

const DEADLINE = '2026-09-23T18:06:37.034903+00:00'

describe('a date and time', () => {
  it('names the zone it is shown in', () => {
    const zone = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })
      .formatToParts(new Date(DEADLINE))
      .find((part) => part.type === 'timeZoneName')?.value

    expect(zone).toBeTruthy()
    expect(formatDateTime(DEADLINE)).toContain(zone as string)
  })

  it('passes an absent value through as absent', () => {
    expect(formatDateTime(null)).toBeNull()
  })

  it('shows a value it cannot read exactly as it arrived', () => {
    expect(formatDateTime('not a moment')).toBe('not a moment')
  })
})
