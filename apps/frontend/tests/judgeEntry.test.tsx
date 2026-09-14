/**
 * The way in that needs no credentials, and the shape of what it hands over.
 *
 * Two claims are under test and they are different claims. The first is about *effort*: somebody
 * who has never seen this product reaches a real case in **one action**, with nothing published
 * anywhere for them to type. The second is about *authority*: what they are holding afterwards
 * is a principal the backend says may read and may not speak, and the screen draws that because
 * it was told rather than because it worked out a role.
 *
 * The control is also only drawn where the endpoint behind it is served. A button that might be
 * dead is not a way in, and the P7.1 contract forbids drawing a capability that does not exist.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NO_CASE_TO_OPEN } from '../src/api/queries'
import { CASES, CASE_ID, PLANNED_CASE } from './caseFixtures'
import { PROMISES, RESOURCES } from './fixtures'
import {
  FakeStream,
  apiError,
  json,
  mockBackend,
  renderApp,
  streamResponse,
  type Responder,
} from './harness'

const OPTIONS = '/api/auth/options'
const DEMO_SESSION = '/api/auth/demo-session'
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

/** What the backend says about this caller. The screen is told; it infers nothing from the role. */
const OBSERVED_CASE = { ...PLANNED_CASE, may_speak: false, permitted_verbs: ['status'] }

beforeEach(() => {
  document.cookie = 'pp_csrf=csrf-token-value; path=/'
  window.history.pushState({}, '', '/')
})

function signedOut(routes: Record<string, Responder> = {}): Record<string, Responder> {
  return {
    '/api/auth/me': () => apiError(401, 'UNAUTHENTICATED', 'a valid session is required'),
    [OPTIONS]: () => json({ demo_session: true }),
    ...routes,
  }
}

describe('the judge entry', () => {
  it('is offered only where the deployment actually serves it', async () => {
    mockBackend(signedOut({ [OPTIONS]: () => json({ demo_session: false }) }))
    renderApp()

    await screen.findByRole('button', { name: 'Sign in' })

    expect(screen.queryByTestId('judge-entry')).not.toBeInTheDocument()
  })

  it('is not offered when the deployment cannot be asked at all', async () => {
    mockBackend(signedOut({ [OPTIONS]: () => apiError(404, 'NOT_FOUND') }))
    renderApp()

    await screen.findByRole('button', { name: 'Sign in' })

    expect(screen.queryByTestId('judge-entry')).not.toBeInTheDocument()
  })

  it('publishes no credential for the judge to type', async () => {
    mockBackend(signedOut())
    renderApp()

    const entry = await screen.findByTestId('judge-entry')

    expect(entry.textContent ?? '').not.toMatch(/password|username|judge|token/i)
    expect(entry.querySelector('input')).toBeNull()
  })

  it('reaches a real case in one action, with nothing typed', async () => {
    const stream = new FakeStream()
    const backend = mockBackend(
      signedOut({
        [DEMO_SESSION]: () => json(JUDGE),
        '/api/promises': () => json(PROMISES),
        '/api/resources': () => json(RESOURCES),
        '/api/cases': () => json(CASES),
        [CASE_PATH]: () => json(OBSERVED_CASE),
        '/events': () => streamResponse(stream),
      }),
    )
    renderApp()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /look around a real case/i }))

    // A case, not a list: the workspace itself, at the case the backend listed first.
    const workspace = await screen.findByTestId('case-workspace')
    expect(workspace).toHaveAttribute('data-case-id', CASE_ID)
    expect(window.location.search).toContain(`case=${CASE_ID}`)
    expect(backend.countOf(DEMO_SESSION)).toBe(1)
    // One action, and nothing that carried a credential.
    expect(backend.requests.some((entry) => entry.url === '/api/auth/login')).toBe(false)
    const sent = backend.requests.find((entry) => entry.url === DEMO_SESSION)
    expect(sent?.body).toBeNull()
    stream.close()
  })

  it('gives the judge a case they can read and no control that would change it', async () => {
    const stream = new FakeStream()
    mockBackend(
      signedOut({
        [DEMO_SESSION]: () => json(JUDGE),
        '/api/promises': () => json(PROMISES),
        '/api/resources': () => json(RESOURCES),
        '/api/cases': () => json(CASES),
        [CASE_PATH]: () => json(OBSERVED_CASE),
        '/events': () => streamResponse(stream),
      }),
    )
    renderApp()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /look around a real case/i }))
    await screen.findByTestId('case-workspace')

    // Everything to read.
    expect(screen.getByTestId('band-what-happened')).toBeInTheDocument()
    expect(screen.getByTestId('untouched-proof')).toBeInTheDocument()
    expect(screen.getByTestId('conversation-speech')).toHaveTextContent(OBSERVED_CASE.speech)
    // Nothing to do.
    expect(screen.queryByTestId('conversation-confirm')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/answer in your own words/i)).not.toBeInTheDocument()
    expect(screen.getByTestId('conversation-read-only')).toBeInTheDocument()
    stream.close()
  })

  it('says what the backend said when a deployment refuses to issue one', async () => {
    mockBackend(
      signedOut({
        [DEMO_SESSION]: () =>
          apiError(429, 'TOO_MANY_ATTEMPTS', 'too many demo sessions from this client'),
      }),
    )
    renderApp()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /look around a real case/i }))

    expect(await screen.findByTestId('judge-entry-error')).toHaveTextContent(
      'too many demo sessions from this client',
    )
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('says so when the case list cannot be read, rather than doing nothing at all', async () => {
    // The failure this pins is silence. The session is issued, the list read fails, and before
    // the read moved behind the mutation the press left the judge on this screen with the
    // button enabled, no error and nothing happening — indistinguishable from a dead product.
    mockBackend(
      signedOut({
        [DEMO_SESSION]: () => json(JUDGE),
        '/api/cases': () => apiError(503, 'UNAVAILABLE', 'the case list could not be read'),
      }),
    )
    renderApp()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /look around a real case/i }))

    // Generous, because the read is retried before it gives up and each attempt backs off.
    expect(
      await screen.findByTestId('judge-entry-error', undefined, { timeout: 10_000 }),
    ).toHaveTextContent('the case list could not be read')
    expect(screen.queryByTestId('case-workspace')).not.toBeInTheDocument()
  })

  it('tries the case list again when the first read fails on a cold backend', async () => {
    // The read that starts the whole product now has the retry every other read has. One
    // unlucky first request on a backend that has just come up is what this covers, and it is
    // the shape that was failing the durability suite on a cold CI stack.
    let attempts = 0
    const stream = new FakeStream()
    mockBackend(
      signedOut({
        [DEMO_SESSION]: () => json(JUDGE),
        '/api/promises': () => json(PROMISES),
        '/api/resources': () => json(RESOURCES),
        '/api/cases': () => {
          attempts += 1
          if (attempts === 1) return apiError(503, 'UNAVAILABLE', 'not ready yet')
          return json(CASES)
        },
        [CASE_PATH]: () => json(OBSERVED_CASE),
        '/events': () => streamResponse(stream),
      }),
    )
    renderApp()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /look around a real case/i }))

    expect(
      await screen.findByTestId('case-workspace', undefined, { timeout: 10_000 }),
    ).toHaveAttribute('data-case-id', CASE_ID)
    expect(attempts).toBeGreaterThan(1)
    stream.close()
  })

  it('says there is nothing to look at rather than pressing into an empty list', async () => {
    mockBackend(
      signedOut({
        [DEMO_SESSION]: () => json(JUDGE),
        '/api/cases': () => json({ cases: [] }),
      }),
    )
    renderApp()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /look around a real case/i }))

    expect(await screen.findByTestId('judge-entry-error')).toHaveTextContent(NO_CASE_TO_OPEN)
    expect(screen.queryByTestId('case-workspace')).not.toBeInTheDocument()
  })

  it('leaves the credentials path exactly as it was', async () => {
    mockBackend(signedOut())
    renderApp()

    expect(await screen.findByLabelText('Worker')).toHaveValue('')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('does not ask for a session before anybody has asked for one', async () => {
    const backend = mockBackend(signedOut())
    renderApp()

    await screen.findByTestId('judge-entry')

    await waitFor(() => {
      expect(backend.countOf(OPTIONS)).toBe(1)
    })
    expect(backend.countOf(DEMO_SESSION)).toBe(0)
  })
})
