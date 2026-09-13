/**
 * The worker with nothing open yet, and the judge who must never be offered the same control.
 *
 * Three separate claims, and they fail in different ways:
 *
 * - **It is the real route.** A panel that posted somewhere else, or that carried an actor field,
 *   would be a second way into the product with a different idea of who was speaking. So the
 *   request itself is asserted — path, method, CSRF header and body keys.
 * - **It is not offered to an observer.** Not disabled, not greyed: absent. The backend says so
 *   with `may_report`, and the screen is told rather than comparing a role.
 * - **It creates nothing until the backend has.** No case row, no placeholder, no navigation —
 *   the address bar moves to the id the backend returned and to nothing before it.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CASES, CASE_ID, NO_CASES, PLANNED_CASE } from './caseFixtures'
import { MAYA, PROMISES, RESOURCES } from './fixtures'
import {
  FakeStream,
  apiError,
  json,
  mockBackend,
  renderApp,
  streamResponse,
  type Backend,
  type Responder,
} from './harness'

const REPORT_PATH = '/api/conversation/report'
const CASE_PATH = `/api/cases/${CASE_ID}`

const JUDGE = {
  worker: {
    id: 'judge',
    username: 'judge',
    display_name: 'Observer',
    role: 'observer',
    may_report: false,
  },
}

function accepted(): unknown {
  return {
    case_id: CASE_ID,
    statement_id: 'f1e2d3c4-b5a6-4978-8899-aabbccddeeff',
    state: 'RECEIVED',
    created: true,
    attested_by: 'maya',
    speech: 'I have written that down exactly as you said it.',
  }
}

afterEach(() => {
  window.history.pushState({}, '', '/')
})

function mountLanding(routes: Record<string, Responder> = {}): {
  stream: FakeStream
  backend: Backend
} {
  window.history.pushState({}, '', '/')
  document.cookie = 'pp_csrf=csrf-token-value; path=/'
  const stream = new FakeStream()
  const backend = mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(NO_CASES),
    [CASE_PATH]: () => json(PLANNED_CASE),
    '/events': () => streamResponse(stream),
    ...routes,
  })
  renderApp()
  return { stream, backend }
}

describe('reporting what happened, with no case open', () => {
  it('is offered to a worker the backend says may attest', async () => {
    const { stream } = mountLanding()

    expect(await screen.findByTestId('report-entry')).toBeInTheDocument()
    stream.close()
  })

  it('is not offered to an observer, disabled or otherwise', async () => {
    const { stream } = mountLanding({ '/api/auth/me': () => json(JUDGE) })

    await screen.findByText(/No case has been opened/)

    expect(screen.queryByTestId('report-entry')).not.toBeInTheDocument()
    expect(screen.queryByTestId('report-send')).not.toBeInTheDocument()
    stream.close()
  })

  it('posts the worker’s words to the real conversation route, with no actor field', async () => {
    const { stream, backend } = mountLanding({ [REPORT_PATH]: () => json(accepted(), 202) })

    await screen.findByTestId('report-entry')
    await userEvent.type(
      screen.getByTestId('report-text'),
      "today's raspberry delivery didn't arrive",
    )
    await userEvent.click(screen.getByTestId('report-send'))

    await waitFor(() => {
      expect(backend.countOf(REPORT_PATH)).toBe(1)
    })
    const sent = backend.requests.find((entry) => entry.url === REPORT_PATH)
    expect(sent?.method).toBe('POST')
    expect(sent?.headers['x-csrf-token']).toBe('csrf-token-value')
    expect(Object.keys(sent?.body as object).sort()).toEqual(['command_id', 'text'])
    expect((sent?.body as { text: string }).text).toBe(
      "today's raspberry delivery didn't arrive",
    )
    stream.close()
  })

  it('opens the case the backend returned, and none before it', async () => {
    const { stream, backend } = mountLanding({
      [REPORT_PATH]: () => json(accepted(), 202),
      '/api/cases': () => json(CASES),
    })

    await screen.findByTestId('report-entry')
    await userEvent.type(screen.getByTestId('report-text'), 'the mixer is out')

    expect(window.location.search).toBe('')
    expect(backend.countOf(CASE_PATH)).toBe(0)

    await userEvent.click(screen.getByTestId('report-send'))

    await waitFor(() => {
      expect(window.location.search).toBe(`?case=${CASE_ID}`)
    })
    stream.close()
  })

  it('opens nothing at all when the backend refuses the turn', async () => {
    const { stream } = mountLanding({
      [REPORT_PATH]: () => apiError(403, 'CASE_NOT_PERMITTED', 'that is not yours to report'),
    })

    await screen.findByTestId('report-entry')
    await userEvent.type(screen.getByTestId('report-text'), 'the mixer is out')
    await userEvent.click(screen.getByTestId('report-send'))

    expect(await screen.findByTestId('report-refusal')).toHaveTextContent(
      'that is not yours to report',
    )
    expect(window.location.search).toBe('')
    expect(screen.queryByTestId('case-workspace')).not.toBeInTheDocument()
    stream.close()
  })

  it('sends nothing at all until the worker asks it to', async () => {
    const { stream, backend } = mountLanding({ [REPORT_PATH]: () => json(accepted(), 202) })

    await screen.findByTestId('report-entry')
    await userEvent.type(screen.getByTestId('report-text'), 'the mixer is out')

    expect(backend.countOf(REPORT_PATH)).toBe(0)
    stream.close()
  })
})
