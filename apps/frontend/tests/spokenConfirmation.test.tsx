/**
 * Authorising a plan by saying so, and the four things that does not change.
 *
 * ADR-0015 gave `confirm` the composer every other spoken turn already had. What these tests are
 * really about is the boundary rather than the feature:
 *
 * - **Nothing here reads the sentence.** The panel forwards the worker's words and the *server*
 *   decides whether they were a yes. So the assertions about a non-yes are assertions about the
 *   request the panel made and the refusal it rendered — never about a judgement it reached.
 * - **The plan binding is untouched.** A spoken yes quotes the same `plan_id` the case response
 *   presented, and a stale one is refused exactly as a pressed one is.
 * - **Review still comes first**, and it matters more here than anywhere: a misheard *yes* that
 *   could be sent unseen would be an authorisation nobody gave.
 * - **The timing anchors are the same ones**, because it is the same composer and the same
 *   instrumented exit. **No voice turn has been recorded and no timing is claimed by any of
 *   this.**
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CASES, CASE_ID, CLARIFYING_CASE, PLANNED_CASE } from './caseFixtures'
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
import { resetTurnTimings, turnTimings } from '../src/instrumentation/turnTiming'

/** The body of the last request to one path, read off the harness's own record. */
function bodySentTo(backend: Backend, path: string): Record<string, unknown> {
  const sent = backend.requests.filter((entry) => entry.url === path).at(-1)
  expect(sent, `nothing was sent to ${path}`).toBeDefined()
  return sent?.body as Record<string, unknown>
}

const CASE_PATH = `/api/cases/${CASE_ID}`
const CONFIRM_PATH = '/api/conversation/confirm'

/** The recogniser a test drives, so a spoken turn is a real capture rather than a typed one. */
class FakeRecognition {
  static last: FakeRecognition | null = null
  lang = ''
  continuous = false
  interimResults = false
  maxAlternatives = 1
  onresult: ((event: unknown) => void) | null = null
  onerror: ((event: { error?: string }) => void) | null = null
  onend: (() => void) | null = null

  constructor() {
    FakeRecognition.last = this
  }

  start(): void {}

  stop(): void {
    this.onend?.()
  }

  abort(): void {}

  hear(text: string): void {
    this.onresult?.({
      resultIndex: 0,
      results: { length: 1, 0: { isFinal: true, 0: { transcript: text } } },
    })
  }
}

beforeEach(() => {
  resetTurnTimings()
  FakeRecognition.last = null
  vi.stubGlobal('SpeechRecognition', FakeRecognition)
  document.cookie = 'pp_csrf=csrf-token-value; path=/'
  window.history.pushState({}, '', '/')
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

function confirmed(): unknown {
  return {
    case_id: CASE_ID,
    statement_id: 'b7c1e2d3-4f5a-4b6c-8d7e-9f0a1b2c3d4e',
    state: 'EXECUTING',
    created: true,
    attested_by: 'maya',
    speech: 'Confirmed. Nothing has been changed yet.',
    spoken: 'Confirmed. Nothing has been changed yet.',
  }
}

function mountAtCase(
  view: unknown = PLANNED_CASE,
  routes: Record<string, Responder> = {},
): { stream: FakeStream; backend: Backend } {
  window.history.pushState({}, '', `/?case=${CASE_ID}`)
  const stream = new FakeStream()
  const backend = mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(CASES),
    [CASE_PATH]: () => json(view),
    '/events': () => streamResponse(stream),
    ...routes,
  })
  renderApp()
  return { stream, backend }
}

/** Capture, hear, stop. Leaves the transcript on screen and sends nothing. */
async function speak(words: string): Promise<void> {
  await userEvent.click(await screen.findByTestId('confirm-talk'))
  act(() => {
    FakeRecognition.last?.hear(words)
  })
  await userEvent.click(screen.getByTestId('confirm-talk'))
}

// --------------------------------------------------------------------------- a yes, out loud

describe('confirming a plan by saying so', () => {
  it('sends the words and the plan identity the backend presented', async () => {
    const { stream, backend } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => json(confirmed()),
    })

    await screen.findByTestId('confirm-composer')
    await speak('yes, go ahead')
    await userEvent.click(screen.getByTestId('confirm-transcript-send'))

    const sent = bodySentTo(backend, CONFIRM_PATH)
    expect(sent.text).toBe('yes, go ahead')
    // Quoted back, never composed. The screen cannot describe a plan, only name the one it read.
    expect(sent.plan_id).toBe(PLANNED_CASE.plan_id)
    expect(sent.case_id).toBe(CASE_ID)
    // And no actor. There is no field for one and the panel adds none.
    expect(sent).not.toHaveProperty('worker_id')
    stream.close()
  })

  it('quotes the worker’s own words back, not a sentence the screen chose', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => json(confirmed()),
    })

    await screen.findByTestId('confirm-composer')
    await speak('yep')
    await userEvent.click(screen.getByTestId('confirm-transcript-send'))

    const transcript = await screen.findByTestId('conversation-transcript')
    expect(transcript).toHaveTextContent('yep')
    // The control's own label is what a *press* is recorded as; a spoken turn is not a press.
    expect(transcript).not.toHaveTextContent('Yes, go ahead.')
    stream.close()
  })

  it('shows the backend’s answer, which is a permission and not an outcome', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => json(confirmed()),
    })

    await screen.findByTestId('confirm-composer')
    await speak('yes')
    await userEvent.click(screen.getByTestId('confirm-transcript-send'))

    expect(await screen.findByTestId('conversation-reply')).toHaveTextContent(
      'Nothing has been changed yet',
    )
    stream.close()
  })
})

// ------------------------------------------------------------ what the panel refuses to decide

describe('a sentence that is not a yes', () => {
  it('is still sent, because deciding what it meant is not the screen’s to do', async () => {
    const { stream, backend } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () =>
        apiError(409, 'NOT_A_PLAIN_YES', 'that was not a plain yes, so nothing was confirmed'),
    })

    await screen.findByTestId('confirm-composer')
    await speak('yes but not the strawberries')
    await userEvent.click(screen.getByTestId('confirm-transcript-send'))

    // The panel did not filter it out and did not confirm it either. It asked, and was told no.
    expect(backend.countOf(CONFIRM_PATH)).toBe(1)
    expect(bodySentTo(backend, CONFIRM_PATH).text).toBe('yes but not the strawberries')
    stream.close()
  })

  it('renders the backend’s refusal and moves nothing on screen', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () =>
        apiError(409, 'NOT_A_PLAIN_YES', 'that was not a plain yes, so nothing was confirmed'),
    })

    await screen.findByTestId('confirm-composer')
    await speak('what does that mean for the wedding cake')
    await userEvent.click(screen.getByTestId('confirm-transcript-send'))

    expect(await screen.findByTestId('conversation-refusal')).toHaveTextContent(
      'that was not a plain yes',
    )
    // No exchange was recorded, because nothing was accepted.
    expect(screen.queryByTestId('conversation-transcript')).not.toBeInTheDocument()
    stream.close()
  })

  it('keeps the worker’s words in the composer when the turn did not happen', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () =>
        apiError(409, 'NOT_A_PLAIN_YES', 'that was not a plain yes, so nothing was confirmed'),
    })

    await screen.findByTestId('confirm-composer')
    await speak('hold on')
    await userEvent.click(screen.getByTestId('confirm-transcript-send'))

    await screen.findByTestId('conversation-refusal')
    // Theirs to keep, and still under review. A composer that emptied itself on a refusal would
    // throw a worker's sentence away over a turn that never happened.
    expect(screen.getByTestId('confirm-transcript')).toHaveTextContent('hold on')
    stream.close()
  })

  it('shows a superseded plan as the backend’s refusal, however good the words were', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () =>
        apiError(409, 'PLAN_SUPERSEDED', 'that plan is not the one this case is offering'),
    })

    await screen.findByTestId('confirm-composer')
    await speak('yes, go ahead')
    await userEvent.click(screen.getByTestId('confirm-transcript-send'))

    expect(await screen.findByTestId('conversation-refusal')).toHaveTextContent(
      'that plan is not the one this case is offering',
    )
    stream.close()
  })
})

// ------------------------------------------------------------------- review, before anything

describe('the review a spoken yes cannot skip', () => {
  it('shows the transcript and sends nothing until the worker says to', async () => {
    const { stream, backend } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => json(confirmed()),
    })

    await screen.findByTestId('confirm-composer')
    await speak('yes, go ahead')

    expect(await screen.findByTestId('confirm-transcript')).toHaveTextContent('yes, go ahead')
    // The whole point: a misheard yes is on screen and has authorised nothing.
    expect(backend.countOf(CONFIRM_PATH)).toBe(0)
    stream.close()
  })

  it('lets a misheard yes be thrown away without a request', async () => {
    const { stream, backend } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => json(confirmed()),
    })

    await screen.findByTestId('confirm-composer')
    await speak('yes, go ahead')
    await userEvent.click(screen.getByTestId('confirm-transcript-discard'))

    expect(screen.queryByTestId('confirm-transcript')).not.toBeInTheDocument()
    expect(backend.countOf(CONFIRM_PATH)).toBe(0)
    stream.close()
  })
})

// ------------------------------------------------------- the control, and where neither appears

describe('the control beside it', () => {
  it('still confirms, and carries no words at all', async () => {
    const { stream, backend } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => json(confirmed()),
    })

    await userEvent.click(await screen.findByTestId('conversation-confirm'))

    const sent = bodySentTo(backend, CONFIRM_PATH)
    // A press is the yes. Nothing fabricates a sentence to stand in for one nobody said.
    expect(sent).not.toHaveProperty('text')
    expect(sent.plan_id).toBe(PLANNED_CASE.plan_id)
    stream.close()
  })

  it('reaches the same route as the spoken path', async () => {
    const { stream, backend } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => json(confirmed()),
    })

    await userEvent.click(await screen.findByTestId('conversation-confirm'))

    expect(backend.countOf(CONFIRM_PATH)).toBe(1)
    stream.close()
  })

  it('offers neither where the backend does not permit the verb', async () => {
    const { stream } = mountAtCase(CLARIFYING_CASE)

    await screen.findByTestId('conversation-panel')
    // Not a disabled control and not a hidden composer: absent, because the phase does not
    // permit it and an advertised capability the case cannot offer is worse than none.
    expect(screen.queryByTestId('conversation-confirm')).not.toBeInTheDocument()
    expect(screen.queryByTestId('confirm-composer')).not.toBeInTheDocument()
    stream.close()
  })
})

// ------------------------------------------------------------------------ the timing anchors

describe('the anchors a spoken confirmation leaves', () => {
  it('records both speech-end readings and both transport instants', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => json(confirmed()),
    })

    await screen.findByTestId('confirm-composer')
    await speak('yes, go ahead')
    await userEvent.click(screen.getByTestId('confirm-transcript-send'))
    await screen.findByTestId('conversation-transcript')

    const record = turnTimings().find((one) => one.verb === 'confirm')
    expect(record?.origin).toBe('spoken')
    // Both candidate anchors, neither chosen here. Which one G7 means is a measurement's to
    // decide, and this module decides nothing.
    expect(record?.speech_end_final_result).not.toBeNull()
    expect(record?.speech_end_recogniser_end).not.toBeNull()
    expect(record?.sent).not.toBeNull()
    expect(record?.received).not.toBeNull()
    expect(record?.outcome).toBe('accepted')
    stream.close()
  })

  it('times a refused spoken confirmation rather than dropping it', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () =>
        apiError(409, 'NOT_A_PLAIN_YES', 'that was not a plain yes, so nothing was confirmed'),
    })

    await screen.findByTestId('confirm-composer')
    await speak('no')
    await userEvent.click(screen.getByTestId('confirm-transcript-send'))
    await screen.findByTestId('conversation-refusal')

    const record = turnTimings().find((one) => one.verb === 'confirm')
    expect(record?.origin).toBe('spoken')
    expect(record?.outcome).toBe('refused')
    expect(record?.received).not.toBeNull()
    stream.close()
  })

  it('says a pressed confirmation was typed, rather than borrowing a spoken anchor', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => json(confirmed()),
    })

    await userEvent.click(await screen.findByTestId('conversation-confirm'))
    await screen.findByTestId('conversation-transcript')

    const record = turnTimings().find((one) => one.verb === 'confirm')
    expect(record?.origin).toBe('typed')
    expect(record?.speech_end_final_result).toBeNull()
    stream.close()
  })
})
