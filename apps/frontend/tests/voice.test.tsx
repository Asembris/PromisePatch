/**
 * Speaking a turn, and the review step that stands between a microphone and an attestation.
 *
 * The claim under test is not that capture works — that is the browser's job and this suite
 * stands a controllable recogniser in its place. The claim is that **speaking is not sending**:
 * a transcript is shown, it can be corrected or thrown away, and no request whatsoever reaches
 * the backend until the person who spoke says so. A voice surface that acted on a misheard
 * sentence would have produced a physical attestation nobody made, and the only structural
 * defence against that is that the request cannot be issued from the listening state at all.
 *
 * The second claim is that there is one path and not two: the turn a spoken sentence produces is
 * byte-for-byte the request a typed one produces, on the same route, with the same fields, with
 * no actor in either. That is asserted by comparing the two recorded requests rather than by
 * reading the component.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CASE_ID, NO_CASES, PLANNED_CASE } from './caseFixtures'
import { MAYA, PROMISES, RESOURCES } from './fixtures'
import {
  FakeStream,
  json,
  mockBackend,
  renderApp,
  streamResponse,
  type Backend,
  type Responder,
} from './harness'

const REPORT_PATH = '/api/conversation/report'
const CASE_PATH = `/api/cases/${CASE_ID}`
const SPOKEN = "today's raspberry delivery didn't arrive"

/**
 * A recogniser a test drives by hand.
 *
 * It is deliberately the same surface the real one exposes — `start`, `stop`, `onresult`,
 * `onend` — so the module under test is exercised rather than a branch written for tests.
 */
class FakeRecognition {
  static last: FakeRecognition | null = null
  lang = ''
  continuous = false
  interimResults = false
  maxAlternatives = 1
  started = false
  onresult: ((event: unknown) => void) | null = null
  onerror: ((event: { error?: string }) => void) | null = null
  onend: (() => void) | null = null

  constructor() {
    FakeRecognition.last = this
  }

  start(): void {
    this.started = true
  }

  stop(): void {
    this.started = false
    this.onend?.()
  }

  abort(): void {
    this.started = false
  }

  /** What the browser would report once it had heard something. */
  hear(text: string): void {
    this.onresult?.({
      resultIndex: 0,
      results: { length: 1, 0: { isFinal: true, 0: { transcript: text } } },
    })
  }
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

function withMicrophone(): void {
  vi.stubGlobal('SpeechRecognition', FakeRecognition)
}

beforeEach(() => {
  FakeRecognition.last = null
  document.cookie = 'pp_csrf=csrf-token-value; path=/'
  window.history.pushState({}, '', '/')
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

function mountLanding(routes: Record<string, Responder> = {}): {
  stream: FakeStream
  backend: Backend
} {
  const stream = new FakeStream()
  const backend = mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(NO_CASES),
    [CASE_PATH]: () => json(PLANNED_CASE),
    '/events': () => streamResponse(stream),
    [REPORT_PATH]: () => json(accepted(), 202),
    ...routes,
  })
  renderApp()
  return { stream, backend }
}

/**
 * One whole turn of speaking: press, say something, press stop.
 *
 * The stop is part of it deliberately. Nothing is offered for review while capture is open —
 * a half-finished sentence is not a turn — so a helper that left the microphone running would
 * be testing a state the product does not let anybody act from.
 */
async function speak(text: string): Promise<void> {
  await userEvent.click(screen.getByTestId('report-talk'))
  act(() => {
    FakeRecognition.last?.hear(text)
  })
  await userEvent.click(screen.getByTestId('report-talk'))
}

describe('speaking a turn', () => {
  it('shows the transcript and issues no request at all', async () => {
    withMicrophone()
    const { stream, backend } = mountLanding()

    await screen.findByTestId('report-entry')
    await speak(SPOKEN)

    expect(await screen.findByTestId('report-transcript')).toHaveTextContent(SPOKEN)
    expect(backend.countOf(REPORT_PATH)).toBe(0)
    stream.close()
  })

  it('sends only when the person who spoke says so', async () => {
    withMicrophone()
    const { stream, backend } = mountLanding()

    await screen.findByTestId('report-entry')
    await speak(SPOKEN)
    await screen.findByTestId('report-transcript')

    expect(backend.countOf(REPORT_PATH)).toBe(0)

    await userEvent.click(screen.getByTestId('report-transcript-send'))

    await waitFor(() => {
      expect(backend.countOf(REPORT_PATH)).toBe(1)
    })
    stream.close()
  })

  it('throws a transcript away without sending anything', async () => {
    withMicrophone()
    const { stream, backend } = mountLanding()

    await screen.findByTestId('report-entry')
    await speak('the strawberries came, not the raspberries')
    await screen.findByTestId('report-transcript')

    await userEvent.click(screen.getByTestId('report-transcript-discard'))

    await waitFor(() => {
      expect(screen.queryByTestId('report-transcript')).not.toBeInTheDocument()
    })
    expect(backend.countOf(REPORT_PATH)).toBe(0)
    stream.close()
  })

  it('puts a misheard transcript in the field to be corrected, and still sends nothing', async () => {
    withMicrophone()
    const { stream, backend } = mountLanding()

    await screen.findByTestId('report-entry')
    await speak('today’s rasp very delivery')
    await screen.findByTestId('report-transcript')

    await userEvent.click(screen.getByTestId('report-transcript-edit'))

    const field = screen.getByTestId('report-text')
    await waitFor(() => {
      expect(field).toHaveValue('today’s rasp very delivery')
    })
    expect(screen.queryByTestId('report-transcript')).not.toBeInTheDocument()
    expect(backend.countOf(REPORT_PATH)).toBe(0)
    stream.close()
  })

  it('produces exactly the request a typed turn produces', async () => {
    // Two mounts rather than two turns, because an accepted report opens its case and the
    // landing surface is gone by the second one. What is compared is the two recorded requests.
    withMicrophone()
    const first = mountLanding()
    await screen.findByTestId('report-entry')
    await speak(SPOKEN)
    await screen.findByTestId('report-transcript')
    await userEvent.click(screen.getByTestId('report-transcript-send'))
    await waitFor(() => {
      expect(first.backend.countOf(REPORT_PATH)).toBe(1)
    })
    const spoken = first.backend.requests.find((entry) => entry.url === REPORT_PATH)
    first.stream.close()
    cleanup()
    window.history.pushState({}, '', '/')

    const second = mountLanding()
    await screen.findByTestId('report-entry')
    await userEvent.type(screen.getByTestId('report-text'), SPOKEN)
    await userEvent.click(screen.getByTestId('report-send'))
    await waitFor(() => {
      expect(second.backend.countOf(REPORT_PATH)).toBe(1)
    })
    const typed = second.backend.requests.find((entry) => entry.url === REPORT_PATH)
    second.stream.close()

    expect(spoken?.url).toBe(typed?.url)
    expect(spoken?.method).toBe(typed?.method)
    expect(spoken?.headers['x-csrf-token']).toBe(typed?.headers['x-csrf-token'])
    expect(Object.keys(spoken?.body as object).sort()).toEqual(
      Object.keys(typed?.body as object).sort(),
    )
    expect((spoken?.body as { text: string }).text).toBe(
      (typed?.body as { text: string }).text,
    )
    // The command identity is the one thing that must differ: two turns, not one arriving twice.
    expect((spoken?.body as { command_id: string }).command_id).not.toBe(
      (typed?.body as { command_id: string }).command_id,
    )
  })

  it('announces where capture has got to, for anybody not looking at the screen', async () => {
    withMicrophone()
    const { stream } = mountLanding()

    await screen.findByTestId('report-entry')
    expect(screen.getByTestId('report-voice-state')).toHaveTextContent(/press and speak/i)

    await speak(SPOKEN)

    await waitFor(() => {
      expect(screen.getByTestId('report-voice-state')).toHaveTextContent(/read it back/i)
    })
    stream.close()
  })

  it('claims no listening between turns', async () => {
    withMicrophone()
    const { stream } = mountLanding()

    await screen.findByTestId('report-entry')

    // Nothing is holding a microphone until somebody presses the control.
    expect(FakeRecognition.last).toBeNull()
    const talk = screen.getByTestId('report-talk')
    expect(talk).toHaveAttribute('aria-pressed', 'false')
    expect(talk.textContent ?? '').not.toMatch(/always|wake|hey |alexa/i)

    await speak(SPOKEN)

    // One turn, not continuous: the recogniser is asked for a single utterance.
    expect(FakeRecognition.last?.continuous).toBe(false)
    stream.close()
  })
})

describe('a browser with no microphone', () => {
  it('offers no voice control and says so once', async () => {
    const { stream } = mountLanding()

    await screen.findByTestId('report-entry')

    expect(screen.queryByTestId('report-talk')).not.toBeInTheDocument()
    expect(screen.getByTestId('report-voice-unavailable')).toBeInTheDocument()
    stream.close()
  })

  it('takes the same turn by text, on the same route', async () => {
    const { stream, backend } = mountLanding()

    await screen.findByTestId('report-entry')
    await userEvent.type(screen.getByTestId('report-text'), SPOKEN)
    await userEvent.click(screen.getByTestId('report-send'))

    await waitFor(() => {
      expect(backend.countOf(REPORT_PATH)).toBe(1)
    })
    const sent = backend.requests.find((entry) => entry.url === REPORT_PATH)
    expect((sent?.body as { text: string }).text).toBe(SPOKEN)
    stream.close()
  })
})
