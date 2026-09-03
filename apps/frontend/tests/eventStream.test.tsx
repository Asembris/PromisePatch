/**
 * The live path, end to end through the real client.
 *
 * The claim being tested is narrow and is the whole point of the slice: a frame causes the
 * authoritative reads to be repeated, and causes nothing else. No assertion here reads a value
 * out of a frame payload, because the app must not either — a frame says *when*, and the REST
 * response says *what*.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { MAYA, PROMISES, RESOURCES } from './fixtures'
import {
  FakeStream,
  apiError,
  json,
  mockBackend,
  renderApp,
  streamResponse,
  type Backend,
} from './harness'

function mount(): { stream: FakeStream; backend: Backend } {
  const stream = new FakeStream()
  const backend = mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/events': () => streamResponse(stream),
  })
  renderApp()
  return { stream, backend }
}

function status(): string | null {
  return screen.getByTestId('stream-status').getAttribute('data-status')
}

describe('event stream', () => {
  it('reaches live once the stream is open', async () => {
    const { stream } = mount()
    await screen.findByTestId('stream-status')

    await waitFor(() => {
      expect(status()).toBe('live')
    })
    stream.close()
  })

  it('refetches the authoritative reads when a domain event arrives', async () => {
    const { stream, backend } = mount()
    await screen.findByText('Amara Fell')
    await stream.opened
    const before = {
      promises: backend.countOf('/api/promises'),
      resources: backend.countOf('/api/resources'),
    }

    stream.push('fixture.reset', { seq: 42, type: 'fixture.reset' }, 42)

    await waitFor(() => {
      expect(backend.countOf('/api/promises')).toBeGreaterThan(before.promises)
      expect(backend.countOf('/api/resources')).toBeGreaterThan(before.resources)
    })
    stream.close()
  })

  it('shows the new authoritative state after an event, not the frame payload', async () => {
    const { stream, backend } = mount()
    await screen.findByText('Amara Fell')
    await stream.opened

    // The order book changes behind the API. The frame says nothing about the change.
    backend.on('/api/promises', () =>
      json({
        ...PROMISES,
        as_of: 42,
        promises: PROMISES.promises.filter((promise) => promise.id !== 'pr-a'),
      }),
    )
    stream.push('fixture.reset', { seq: 42, type: 'fixture.reset' }, 42)

    await waitFor(() => {
      expect(screen.getAllByTestId('promise-row')).toHaveLength(5)
    })
    expect(screen.queryByText('Amara Fell')).not.toBeInTheDocument()
    stream.close()
  })

  it('refetches on a resync frame and returns to live', async () => {
    const { stream, backend } = mount()
    await screen.findByText('Amara Fell')
    await stream.opened
    const before = backend.countOf('/api/promises')

    stream.push(
      'resync',
      { latest_seq: 99, skipped_from_seq: 0, reason: 'no_cursor', detail: 'load the read APIs' },
      99,
    )

    await waitFor(() => {
      expect(backend.countOf('/api/promises')).toBeGreaterThan(before)
    })
    await waitFor(() => {
      expect(status()).toBe('live')
    })
    stream.close()
  })

  it('coalesces a burst of events instead of accumulating local state', async () => {
    const { stream, backend } = mount()
    await screen.findByText('Amara Fell')
    await stream.opened
    const before = backend.countOf('/api/promises')

    // A burst as it actually arrives: five frames in one chunk off the socket.
    let burst = ''
    for (let seq = 43; seq <= 47; seq += 1) {
      burst += `id: ${seq}
event: fixture.reset
data: {"seq":${seq}}

`
    }
    stream.enqueue(burst)

    await waitFor(() => {
      expect(backend.countOf('/api/promises')).toBeGreaterThan(before)
    })
    await waitFor(() => {
      expect(screen.getByTestId('stream-status')).toHaveTextContent('seq 47')
    })

    // All five frames were seen...
    expect(screen.getByText(/5 events this connection/)).toBeInTheDocument()
    // ...and produced one screen, not five accumulated ones. Invalidation supersedes a read
    // that is still in flight rather than queueing behind it, which is both why nothing piles
    // up here and why the last read is guaranteed to have started after the last frame. The
    // count of requests is therefore not the property worth asserting; the absence of local
    // state is, and it is what keeps the backend the only thing that knows what is true.
    expect(screen.getAllByTestId('promise-row')).toHaveLength(6)
    expect(screen.getAllByText('Amara Fell')).toHaveLength(1)
    stream.close()
  })

  it('shows reconnecting when the feed drops', async () => {
    const { stream } = mount()
    await screen.findByTestId('stream-status')
    await waitFor(() => {
      expect(status()).toBe('live')
    })

    stream.close()

    await waitFor(() => {
      expect(status()).toBe('reconnecting')
    })
  })

  it('shows reconnecting when the stream cannot be opened at all', async () => {
    mockBackend({
      '/api/auth/me': () => json(MAYA),
      '/api/promises': () => json(PROMISES),
      '/api/resources': () => json(RESOURCES),
      '/events': () => apiError(503, 'UNAVAILABLE'),
    })
    renderApp()
    await screen.findByTestId('stream-status')

    await waitFor(() => {
      expect(status()).toBe('reconnecting')
    })
  })

  it('resumes from the last sequence it was given after a reconnect', async () => {
    const first = new FakeStream()
    const second = new FakeStream()
    let opens = 0
    const backend = mockBackend({
      '/api/auth/me': () => json(MAYA),
      '/api/promises': () => json(PROMISES),
      '/api/resources': () => json(RESOURCES),
      '/events': () => {
        opens += 1
        return streamResponse(opens === 1 ? first : second)
      },
    })
    renderApp()
    await screen.findByText('Amara Fell')
    await first.opened

    first.push('fixture.reset', { seq: 42, type: 'fixture.reset' }, 42)
    await waitFor(() => {
      expect(screen.getByTestId('stream-status')).toHaveTextContent('seq 42')
    })
    first.close()

    await waitFor(() => {
      expect(backend.requests.filter((entry) => entry.url === '/events')).toHaveLength(2)
    })
    const reconnect = backend.requests.filter((entry) => entry.url === '/events')[1]!
    // The server's own resume header, carrying the sequence the server chose.
    expect(reconnect.headers['last-event-id']).toBe('42')
    second.close()
  })
})
