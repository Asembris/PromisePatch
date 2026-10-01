/**
 * The simulated Alexa+ panel (ADR-0028): what it sends, what it labels, and what it keeps apart.
 *
 * - it sends a case and the reviewed words, and nothing else, with the session's CSRF token;
 * - it holds no MCP credential, so no request it makes carries one;
 * - the worker's approval is its own explicit control, on its own route, never a spoken turn;
 * - it is labelled as a simulation and is absent for anybody the backend says may not speak.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CASES, CASE_ID, PLANNED_CASE } from './caseFixtures'
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

const BRIDGE_PATH = '/api/conversation/simulated-alexa'
const APPROVE_PATH = '/api/conversation/approve'
const CONFIRM_PATH = '/api/conversation/confirm'
const SAID = 'yes, go ahead'

const REPLY = {
  case_id: CASE_ID,
  reply: 'Confirmed. Nothing has been changed yet.',
  phase: 'WORKING',
  hydrated: true,
  selected: 'CONFIRM',
  calls: ['confirm', 'status'],
  blocked: null,
  refusal: null,
}

afterEach(() => {
  window.history.pushState({}, '', '/')
})

function mount(
  routes: Record<string, Responder> = {},
  view: unknown = PLANNED_CASE,
): { stream: FakeStream; backend: Backend } {
  window.history.pushState({}, '', `/?case=${CASE_ID}`)
  const stream = new FakeStream()
  const backend = mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(CASES),
    [`/api/cases/${CASE_ID}`]: () => json(view),
    '/events': () => streamResponse(stream),
    ...routes,
  })
  renderApp()
  return { stream, backend }
}

describe('the simulated Alexa+ panel', () => {
  it('is labelled as a simulation over MCP, apart from the direct conversation panel', async () => {
    const { stream } = mount()

    const panel = await screen.findByTestId('simulated-alexa-panel')

    expect(within(panel).getByText('Simulated Alexa+ via MCP')).toBeInTheDocument()
    expect(within(panel).getByTestId('simulated-alexa-disclosure')).toHaveTextContent(
      /not Alexa\+ and not an Alexa skill/i,
    )
    expect(within(panel).queryByTestId('conversation-confirm')).not.toBeInTheDocument()
    expect(screen.getByTestId('conversation-panel')).not.toContainElement(panel)
    stream.close()
  })

  it('sends only the case and the reviewed words, with CSRF and no credential', async () => {
    document.cookie = 'pp_csrf=a-real-token'
    const { stream, backend } = mount({ [BRIDGE_PATH]: () => json(REPLY) })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(/say it to the case over MCP/i), SAID)
    await user.click(screen.getByRole('button', { name: /say it over MCP/i }))

    expect(await screen.findByTestId('simulated-alexa-transcript')).toHaveTextContent(REPLY.reply)
    expect(screen.getByTestId('simulated-alexa-calls')).toHaveTextContent(
      'MCP: status, confirm, status',
    )
    const sent = backend.requests.filter((entry) => entry.url === BRIDGE_PATH)
    expect(sent).toHaveLength(1)
    expect(sent[0]?.method).toBe('POST')
    expect(sent[0]?.body).toEqual({ case_id: CASE_ID, text: SAID })
    expect(sent[0]?.headers['x-csrf-token']).toBe('a-real-token')
    for (const request of backend.requests) {
      expect(request.headers.authorization).toBeUndefined()
    }
    expect(backend.countOf(APPROVE_PATH)).toBe(0)
    expect(backend.countOf(CONFIRM_PATH)).toBe(0)
    stream.close()
  })

  it('records the approval on its own control and route, never as a spoken turn', async () => {
    const { stream, backend } = mount({
      [APPROVE_PATH]: () =>
        json(
          {
            case_id: CASE_ID,
            plan_id: PLANNED_CASE.plan_id,
            approved_by: 'maya',
            approved_via: 'BROWSER_SESSION',
            speech: 'Approval recorded. Nothing has been carried out yet.',
          },
          201,
        ),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('simulated-alexa-approve'))

    expect(await screen.findByTestId('simulated-alexa-approved')).toHaveTextContent(
      'Approval recorded. Nothing has been carried out yet.',
    )
    const sent = backend.requests.find((entry) => entry.url === APPROVE_PATH)
    expect(sent?.body).toEqual({ case_id: CASE_ID, plan_id: PLANNED_CASE.plan_id })
    expect(backend.countOf(BRIDGE_PATH)).toBe(0)
    expect(backend.countOf(CONFIRM_PATH)).toBe(0)
    stream.close()
  })

  it('shows the server’s refusal and keeps nothing it did not accept', async () => {
    const { stream } = mount({
      [BRIDGE_PATH]: () =>
        apiError(403, 'NOT_THE_SURFACE_WORKER', 'only the worker MCP speaks for may use it'),
    })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(/say it to the case over MCP/i), SAID)
    await user.click(screen.getByRole('button', { name: /say it over MCP/i }))

    expect(await screen.findByTestId('simulated-alexa-refusal')).toHaveTextContent(
      'only the worker MCP speaks for may use it',
    )
    expect(screen.queryByTestId('simulated-alexa-transcript')).not.toBeInTheDocument()
    stream.close()
  })

  it('is absent for a reader the backend says may not speak', async () => {
    const { stream } = mount({}, { ...PLANNED_CASE, may_speak: false, permitted_verbs: ['status'] })

    await screen.findByTestId('conversation-panel')

    expect(screen.queryByTestId('simulated-alexa-panel')).not.toBeInTheDocument()
    stream.close()
  })
})
