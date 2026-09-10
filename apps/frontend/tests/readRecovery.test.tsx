/**
 * A read that fails once must not leave the screen empty for ever.
 *
 * The order book is refreshed by the feed rather than by a timer, and that is the right design:
 * polling a healthy screen would be a worse version of the stream. But it left one hole. The
 * retry policy correctly stops after three attempts on a server or transport failure, and until
 * this was fixed nothing tried again afterwards -- the only two things that could were a feed
 * frame and a window focus. A browser nobody is looking at, whose feed is also unhappy, sat on
 * an empty panel indefinitely with the heading rendered above it.
 *
 * That is not a hypothetical. It is exactly what CI saw: the worker was signed in, the "Customer
 * promises" heading was on screen, and `promise-row` stayed at zero for the full twenty seconds
 * while the locator polled forty-four times. A screen whose entire job is to say what is true
 * right now is the last place that failure mode belongs.
 *
 * These tests are about recovery only. That a healthy read is *not* polled is asserted here too,
 * because a fix that quietly turned the screen into a poller would have traded one problem for
 * the one the design already rejected.
 */
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { CASES } from './caseFixtures'
import { MAYA, PROMISES, RESOURCES } from './fixtures'
import { FakeStream, apiError, json, mockBackend, renderApp, streamResponse } from './harness'

/** More than `retryTransportFailures` will attempt, so the query really does reach `error`. */
const ATTEMPTS_BEFORE_SUCCESS = 4

function failThenSucceed(body: unknown, failures: number): () => Response {
  let seen = 0
  return () => {
    seen += 1
    return seen <= failures ? apiError(503, 'UNAVAILABLE', 'the database is starting') : json(body)
  }
}

describe('a read that fails and is given no help', () => {
  it('recovers on its own, with no feed frame and no window focus', async () => {
    const stream = new FakeStream()
    const backend = mockBackend({
      '/api/auth/me': () => json(MAYA),
      '/api/promises': failThenSucceed(PROMISES, ATTEMPTS_BEFORE_SUCCESS),
      '/api/resources': () => json(RESOURCES),
      '/api/cases': () => json(CASES),
      '/events': () => streamResponse(stream),
    })
    renderApp()

    // The heading is a panel title and renders whether or not the read worked, which is why its
    // presence is not evidence of anything. This is the state CI was stuck in.
    expect(await screen.findByRole('heading', { name: 'Customer promises' })).toBeInTheDocument()
    expect(screen.queryAllByTestId('promise-row')).toHaveLength(0)

    // Nothing below sends a frame or focuses the window. If the screen fills, it filled itself.
    const rows = await screen.findAllByTestId('promise-row', undefined, { timeout: 15_000 })
    expect(rows).toHaveLength(6)

    const attempts = backend.requests.filter((request) => request.url === '/api/promises')
    expect(attempts.length).toBeGreaterThan(ATTEMPTS_BEFORE_SUCCESS)
    stream.close()
  }, 20_000)

  it('stops trying once it has an answer, so a healthy screen is never polled', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const stream = new FakeStream()
      const backend = mockBackend({
        '/api/auth/me': () => json(MAYA),
        '/api/promises': () => json(PROMISES),
        '/api/resources': () => json(RESOURCES),
        '/api/cases': () => json(CASES),
        '/events': () => streamResponse(stream),
      })
      renderApp()
      await screen.findAllByTestId('promise-row')

      const afterFirstRead = backend.requests.filter((r) => r.url === '/api/promises').length
      // Far longer than the recovery interval. A succeeding read must ask again only when the
      // feed says something happened -- that contract is the whole reason the stream exists.
      await vi.advanceTimersByTimeAsync(30_000)
      const afterWaiting = backend.requests.filter((r) => r.url === '/api/promises').length

      expect(afterWaiting).toBe(afterFirstRead)
      stream.close()
    } finally {
      vi.useRealTimers()
    }
  })
})
