/**
 * The conversation panel: what it may offer, what it may say, and what it may never do first.
 *
 * The negative assertions are the point again. A panel that offered a confirmation to somebody
 * the domain would refuse, that composed its own sentence about a case, or that showed a turn as
 * having happened before the backend accepted it, would be the product lying in the one place a
 * worker acts. So every test below is one of:
 *
 * - the controls that exist come from `may_speak` and `permitted_verbs`, never from a role;
 * - every sentence on screen is a backend string, byte for byte;
 * - a turn reaches the transcript only after the backend accepted it;
 * - the case is re-read from the server afterwards, and never patched locally;
 * - a refusal is shown as the backend's refusal, and nothing moves.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CASES, CASE_ID, CLARIFYING_CASE, PLANNED_CASE, SETTLED_CASE } from './caseFixtures'
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

const CASE_PATH = `/api/cases/${CASE_ID}`
const CLARIFY_PATH = '/api/conversation/clarify'
const CONFIRM_PATH = '/api/conversation/confirm'
const WITHDRAW_PATH = '/api/conversation/withdraw'

/** The observer a scoped demo session names. Role and `may_speak` both come from the backend. */
const JUDGE = {
  worker: {
    id: 'judge',
    username: 'judge',
    display_name: 'Observer',
    role: 'observer',
    may_report: false,
  },
}

const OBSERVED_CASE = { ...PLANNED_CASE, may_speak: false, permitted_verbs: ['status'] }

function accepted(speech: string, statementId = 'b7c1e2d3-4f5a-4b6c-8d7e-9f0a1b2c3d4e'): unknown {
  return {
    case_id: CASE_ID,
    statement_id: statementId,
    state: 'CLARIFYING',
    created: true,
    attested_by: 'maya',
    speech,
    spoken: speech,
  }
}

function at(search: string): void {
  window.history.pushState({}, '', `/${search}`)
}

afterEach(() => {
  at('')
})

function mountAtCase(routes: Record<string, Responder> = {}): {
  stream: FakeStream
  backend: Backend
} {
  at(`?case=${CASE_ID}`)
  const stream = new FakeStream()
  const backend = mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(CASES),
    [CASE_PATH]: () => json(PLANNED_CASE),
    '/events': () => streamResponse(stream),
    ...routes,
  })
  renderApp()
  return { stream, backend }
}

// -------------------------------------------------------------- what the panel is allowed to say

describe('the conversation panel', () => {
  it('reads the backend’s whole spoken status, and composes none of it', async () => {
    const { stream } = mountAtCase()

    const panel = await screen.findByTestId('conversation-panel')

    expect(within(panel).getByTestId('conversation-speech')).toHaveTextContent(
      PLANNED_CASE.speech,
    )
    stream.close()
  })

  it('lives inside the case workspace rather than on a surface of its own', async () => {
    const { stream } = mountAtCase()

    const workspace = await screen.findByTestId('case-workspace')

    expect(within(workspace).getByTestId('conversation-panel')).toBeInTheDocument()
    expect(within(workspace).getByTestId('band-what-happened')).toBeInTheDocument()
    expect(within(workspace).getByTestId('untouched-proof')).toBeInTheDocument()
    stream.close()
  })

  // ------------------------------------------------------------- what the backend permits

  it('offers a confirmation only because the backend listed the verb', async () => {
    const { stream } = mountAtCase()

    expect(await screen.findByTestId('conversation-confirm')).toBeInTheDocument()
    expect(screen.queryByLabelText(/answer in your own words/i)).not.toBeInTheDocument()
    stream.close()
  })

  it('offers an answer, and no confirmation, while a question is open', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(CLARIFYING_CASE) })

    expect(await screen.findByLabelText(/answer in your own words/i)).toBeInTheDocument()
    expect(screen.queryByTestId('conversation-confirm')).not.toBeInTheDocument()
    stream.close()
  })

  it('offers nothing at all when the backend permits only a read', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(SETTLED_CASE) })

    await screen.findByTestId('conversation-panel')

    expect(screen.queryByTestId('conversation-confirm')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/answer in your own words/i)).not.toBeInTheDocument()
    stream.close()
  })

  it('gives a judge no worker control anywhere on the screen', async () => {
    at(`?case=${CASE_ID}`)
    const stream = new FakeStream()
    mockBackend({
      '/api/auth/me': () => json(JUDGE),
      '/api/promises': () => json(PROMISES),
      '/api/resources': () => json(RESOURCES),
      '/api/cases': () => json(CASES),
      [CASE_PATH]: () => json(OBSERVED_CASE),
      '/events': () => streamResponse(stream),
    })
    renderApp()

    await screen.findByTestId('conversation-panel')

    expect(screen.queryByTestId('conversation-confirm')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/answer in your own words/i)).not.toBeInTheDocument()
    expect(screen.getByTestId('conversation-read-only')).toBeInTheDocument()
    stream.close()
  })

  it('gives a judge no control even when the case is still offering a plan', async () => {
    at(`?case=${CASE_ID}`)
    const stream = new FakeStream()
    // The case genuinely is awaiting a confirmation and genuinely has a plan identity. What
    // withholds the control is `may_speak`, which is the backend's answer about this caller.
    const stillPlanned = { ...OBSERVED_CASE, awaiting_confirmation: true }
    mockBackend({
      '/api/auth/me': () => json(JUDGE),
      '/api/promises': () => json(PROMISES),
      '/api/resources': () => json(RESOURCES),
      '/api/cases': () => json(CASES),
      [CASE_PATH]: () => json(stillPlanned),
      '/events': () => streamResponse(stream),
    })
    renderApp()

    await screen.findByTestId('conversation-panel')

    expect(stillPlanned.plan_id).not.toBeNull()
    expect(screen.queryByTestId('conversation-confirm')).not.toBeInTheDocument()
    stream.close()
  })

  // ------------------------------------------------------------------ what a turn actually does

  it('sends a confirmation quoting the plan identity the backend presented', async () => {
    const { stream, backend } = mountAtCase({
      [CONFIRM_PATH]: () => json(accepted('Confirmed: 1 order covered by a standing preference.')),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('conversation-confirm'))

    await waitFor(() => {
      expect(backend.countOf(CONFIRM_PATH)).toBe(1)
    })
    const sent = backend.requests.find((entry) => entry.url === CONFIRM_PATH)
    expect(sent?.body).toMatchObject({ case_id: CASE_ID, plan_id: PLANNED_CASE.plan_id })
    stream.close()
  })

  it('carries the CSRF header on a turn and names no actor in the body', async () => {
    document.cookie = 'pp_csrf=a-real-token'
    const { stream, backend } = mountAtCase({
      [CONFIRM_PATH]: () => json(accepted('Confirmed.')),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('conversation-confirm'))

    await waitFor(() => {
      expect(backend.countOf(CONFIRM_PATH)).toBe(1)
    })
    const sent = backend.requests.find((entry) => entry.url === CONFIRM_PATH)
    expect(sent?.headers['x-csrf-token']).toBe('a-real-token')
    expect(Object.keys(sent?.body as object).sort()).toEqual([
      'case_id',
      'command_id',
      'plan_id',
    ])
    stream.close()
  })

  it('sends a worker’s answer byte for byte', async () => {
    const { stream, backend } = mountAtCase({
      [CASE_PATH]: () => json(CLARIFYING_CASE),
      [CLARIFY_PATH]: () => json(accepted('Got it.')),
    })
    const user = userEvent.setup()
    const spoken = 'just raspberries - the strawberries came'

    await user.type(await screen.findByLabelText(/answer in your own words/i), spoken)
    await user.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => {
      expect(backend.countOf(CLARIFY_PATH)).toBe(1)
    })
    const sent = backend.requests.find((entry) => entry.url === CLARIFY_PATH)
    expect((sent?.body as { text: string }).text).toBe(spoken)
    stream.close()
  })

  it('says back exactly what the backend said, and nothing it wrote itself', async () => {
    const receipt =
      'I have written that down exactly as you said it. Nothing has changed yet - I am ' +
      'working out what it means for your promises.'
    const { stream } = mountAtCase({
      [CASE_PATH]: () => json(CLARIFYING_CASE),
      [CLARIFY_PATH]: () => json(accepted(receipt)),
    })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(/answer in your own words/i), 'just raspberries')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByTestId('conversation-reply')).toHaveTextContent(receipt)
    stream.close()
  })

  it('shows no turn at all until the backend has accepted it', async () => {
    let release: () => void = () => undefined
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    const { stream } = mountAtCase({
      [CASE_PATH]: () => json(CLARIFYING_CASE),
      [CLARIFY_PATH]: async () => {
        await held
        return json(accepted('Got it.'))
      },
    })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(/answer in your own words/i), 'just raspberries')
    await user.click(screen.getByRole('button', { name: /send/i }))

    // In flight: the composer says so, and nothing has been added to the transcript.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sending/i })).toBeInTheDocument()
    })
    expect(screen.queryByTestId('conversation-transcript')).not.toBeInTheDocument()

    release()
    expect(await screen.findByTestId('conversation-transcript')).toBeInTheDocument()
    stream.close()
  })

  it('re-reads the case from the server after a turn rather than patching it', async () => {
    const { stream, backend } = mountAtCase({
      [CONFIRM_PATH]: () => json(accepted('Confirmed.')),
    })
    const user = userEvent.setup()
    await screen.findByTestId('conversation-confirm')
    const before = backend.countOf(CASE_PATH)

    await user.click(screen.getByTestId('conversation-confirm'))

    await waitFor(() => {
      expect(backend.countOf(CASE_PATH)).toBeGreaterThan(before)
    })
    stream.close()
  })

  it('draws the state the re-read returned, never the one the turn implied', async () => {
    let served = PLANNED_CASE
    const { stream } = mountAtCase({
      [CASE_PATH]: () => json(served),
      [CONFIRM_PATH]: () => {
        // The backend accepted the confirmation. The case it now serves is the one the screen
        // must draw -- and the screen has no way to have drawn it from the answer above.
        served = SETTLED_CASE
        return json(accepted('Confirmed.'))
      },
    })
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('conversation-confirm'))

    await waitFor(() => {
      expect(screen.getByTestId('conversation-speech')).toHaveTextContent(SETTLED_CASE.speech)
    })
    expect(screen.queryByTestId('conversation-confirm')).not.toBeInTheDocument()
    stream.close()
  })

  // -------------------------------------------------------------------------- being refused

  it('shows a refused confirmation as the backend’s refusal, and moves nothing', async () => {
    const { stream } = mountAtCase({
      [CONFIRM_PATH]: () =>
        apiError(409, 'PLAN_SUPERSEDED', 'that plan is not the one this case is offering'),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('conversation-confirm'))

    expect(await screen.findByTestId('conversation-refusal')).toHaveTextContent(
      'that plan is not the one this case is offering',
    )
    expect(screen.queryByTestId('conversation-transcript')).not.toBeInTheDocument()
    stream.close()
  })

  it('re-reads the case after a stale plan, so the plan on offer is the one shown', async () => {
    let served = PLANNED_CASE
    const { stream, backend } = mountAtCase({
      [CASE_PATH]: () => json(served),
      [CONFIRM_PATH]: () => {
        served = { ...PLANNED_CASE, plan_id: 'ffffffffffffffff', speech: 'A new plan is ready.' }
        return apiError(409, 'PLAN_SUPERSEDED', 'that plan is not the one this case is offering')
      },
    })
    const user = userEvent.setup()
    await screen.findByTestId('conversation-confirm')
    const before = backend.countOf(CASE_PATH)

    await user.click(screen.getByTestId('conversation-confirm'))

    await waitFor(() => {
      expect(backend.countOf(CASE_PATH)).toBeGreaterThan(before)
    })
    await waitFor(() => {
      expect(screen.getByTestId('conversation-speech')).toHaveTextContent('A new plan is ready.')
    })
    stream.close()
  })

  it('never renders a confirmation in the language of a customer’s consent', async () => {
    const { stream } = mountAtCase()

    const panel = await screen.findByTestId('conversation-panel')

    expect(panel.textContent ?? '').not.toMatch(/consent|on behalf of|approved by the customer/i)
    stream.close()
  })

  // ------------------------------------------------------- a withdrawal, and what it is not

  it('offers a withdrawal only because the backend listed the verb', async () => {
    const { stream } = mountAtCase()

    expect(await screen.findByTestId('conversation-withdraw')).toBeInTheDocument()
    stream.close()
  })

  it('draws no withdrawal control at all where the backend did not list it', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(SETTLED_CASE) })

    await screen.findByTestId('conversation-panel')

    expect(screen.queryByTestId('conversation-withdraw')).not.toBeInTheDocument()
    stream.close()
  })

  it('offers an observer no withdrawal, whatever the case is doing', async () => {
    const { stream } = mountAtCase({
      '/api/auth/me': () => json(JUDGE),
      [CASE_PATH]: () => json(OBSERVED_CASE),
    })

    await screen.findByTestId('conversation-read-only')

    expect(screen.queryByTestId('conversation-withdraw')).not.toBeInTheDocument()
    stream.close()
  })

  it('says a withdrawal is not an undo before anybody presses it', async () => {
    const { stream } = mountAtCase()

    const button = await screen.findByTestId('conversation-withdraw')

    expect(button.parentElement?.textContent ?? '').toContain(
      'Anything already sent or changed stays as it is',
    )
    stream.close()
  })

  it('changes nothing on screen until the backend has answered', async () => {
    const { stream } = mountAtCase({
      [WITHDRAW_PATH]: () => apiError(409, 'CASE_NOT_WITHDRAWABLE', 'that case has finished'),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('conversation-withdraw'))

    expect(await screen.findByTestId('conversation-refusal')).toHaveTextContent(
      'that case has finished',
    )
    expect(screen.queryByTestId('withdrawal-result')).not.toBeInTheDocument()
    expect(screen.queryByTestId('conversation-transcript')).not.toBeInTheDocument()
    stream.close()
  })

  it('prints what the withdrawal could not stop, in the backend’s own words', async () => {
    const already = '1 order had already been changed in the order system, and that change stands'
    const { stream } = mountAtCase({
      [WITHDRAW_PATH]: () =>
        json({
          case_id: CASE_ID,
          command_id: 'f1e2d3c4-b5a6-4978-8091-a2b3c4d5e6f7',
          state: 'RECONCILING',
          created: true,
          withdrawn_by: 'maya',
          withdrawn: 0,
          escalated: 2,
          reversed_writes: ['released 1 production task this case had put on hold'],
          applied: [already],
          speech: `Withdrawn. I could not undo what had already happened: ${already}.`,
          spoken: `Withdrawn. I could not undo what had already happened: ${already}.`,
        }),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('conversation-withdraw'))

    const applied = await screen.findByTestId('withdrawal-applied')
    expect(applied).toHaveTextContent(already)
    expect(screen.getByTestId('withdrawal-reversed')).toHaveTextContent(
      'released 1 production task this case had put on hold',
    )
    stream.close()
  })

  it('never says a withdrawal undid anything', async () => {
    const { stream } = mountAtCase({
      [WITHDRAW_PATH]: () =>
        json({
          case_id: CASE_ID,
          command_id: 'f1e2d3c4-b5a6-4978-8091-a2b3c4d5e6f7',
          state: 'CANCELLED',
          created: true,
          withdrawn_by: 'maya',
          withdrawn: 3,
          escalated: 0,
          reversed_writes: ['cancelled 1 piece of work that had not started'],
          applied: [],
          speech: 'Withdrawn: I cancelled 1 piece of work that had not started.',
          spoken: 'Withdrawn: I cancelled 1 piece of work that had not started.',
        }),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('conversation-withdraw'))
    await screen.findByTestId('withdrawal-result')

    const panel = screen.getByTestId('conversation-panel')
    expect(panel.textContent ?? '').not.toMatch(/undone|undo|rolled back|reversed|put back/i)
    stream.close()
  })

  it('re-reads the case after a withdrawal rather than patching it locally', async () => {
    let served = PLANNED_CASE
    const { stream, backend } = mountAtCase({
      [CASE_PATH]: () => json(served),
      [WITHDRAW_PATH]: () => {
        served = { ...SETTLED_CASE, speech: 'Cancelled.' }
        return json({
          case_id: CASE_ID,
          command_id: 'f1e2d3c4-b5a6-4978-8091-a2b3c4d5e6f7',
          state: 'CANCELLED',
          created: true,
          withdrawn_by: 'maya',
          withdrawn: 3,
          escalated: 0,
          reversed_writes: [],
          applied: [],
          speech: 'Withdrawn. Nothing was sent and no order was changed.',
          spoken: 'Withdrawn. Nothing was sent and no order was changed.',
        })
      },
    })
    const user = userEvent.setup()
    await screen.findByTestId('conversation-withdraw')
    const before = backend.countOf(CASE_PATH)

    await user.click(screen.getByTestId('conversation-withdraw'))

    await waitFor(() => {
      expect(backend.countOf(CASE_PATH)).toBeGreaterThan(before)
    })
    await waitFor(() => {
      expect(screen.getByTestId('conversation-speech')).toHaveTextContent('Cancelled.')
    })
    stream.close()
  })
})
