/**
 * What a worker actually hears, and the four times the product must stay silent.
 *
 * P7.1 §7 gives five of the nine voice states an audible column, and until now the audible
 * column did not exist: every sound this surface could make required somebody to find and press
 * "read this aloud". A worker carrying a crate at six in the morning is the person the voice
 * path is for, and a reply they have to press a button to hear is a reply they do not get.
 *
 * So the claims under test are about **when** sound happens as much as what it says:
 *
 * - the backend's sentence is spoken on its own, on turn resolution, **byte for byte** — this
 *   surface composes nothing for a loudspeaker any more than it does for a screen;
 * - a turn in flight is acknowledged, in a fixed phrase that holds no digit and none of the
 *   thirty-nine outcome words the orchestrator's glue gate bans, so a progress reply can never
 *   be mistaken for a result;
 * - a refused turn says it did not happen and that the case is unchanged, and does **not** read
 *   the backend's refusal message aloud;
 * - **nothing is spoken when capture ends.** The `captured` row's audible column is "nothing",
 *   and the worker has not had an answer yet — acknowledging a microphone is not a response to a
 *   turn, and a surface that spoke there would be talking about itself;
 * - and nothing is spoken on arrival, because nobody took a turn.
 *
 * The timing assertions here prove only that the anchors are *written down* — `onstart` and not
 * the return of `speak`. **No turn has been recorded and no timing is claimed anywhere.**
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CASES, CASE_ID, CLARIFYING_CASE, NO_CASES, PLANNED_CASE } from './caseFixtures'
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
import { TURN_ACKNOWLEDGEMENT, TURN_DID_NOT_HAPPEN } from '../src/features/voice/turnVoice'

const CASE_PATH = `/api/cases/${CASE_ID}`
const CLARIFY_PATH = '/api/conversation/clarify'
const CONFIRM_PATH = '/api/conversation/confirm'
const REPORT_PATH = '/api/conversation/report'

/**
 * The thirty-nine words a sentence about a turn may not contain.
 *
 * Copied from `semantic/jobs.py`'s `CLAIM_WORDS`, which is the bar the model's own conversational
 * glue is held to. A phrase composed on a screen is no more trustworthy than one composed by a
 * model, so it is held to the same list rather than to a kinder one.
 */
const CLAIM_WORDS = [
  'applied', 'approved', 'arranged', 'asked', 'authorised', 'authorized', 'booked', 'called',
  'cancelled', 'canceled', 'changed', 'complete', 'completed', 'confirmed', 'consented',
  'declined', 'delivered', 'done', 'emailed', 'finished', 'fixed', 'guaranteed', 'handled',
  'informed', 'messaged', 'notified', 'ordered', 'recovered', 'refunded', 'replaced',
  'rescheduled', 'resolved', 'safe', 'sent', 'settled', 'sorted', 'substituted', 'texted',
  'updated',
]

// ------------------------------------------------------------------ a loudspeaker a test drives

class FakeUtterance {
  onstart: (() => void) | null = null
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(readonly text: string) {}
}

/**
 * The browser's voice, stopped where the real one would be.
 *
 * `speak` only queues, exactly as the real interface does, and nothing is audible until `begin`
 * is called — which is what makes it possible to assert that the recorded anchor is the
 * utterance starting rather than the call returning.
 */
class FakeSynthesis {
  spoken: FakeUtterance[] = []
  cancelled = 0
  private speaking: FakeUtterance | null = null

  cancel(): void {
    this.cancelled += 1
    const interrupted = this.speaking
    this.speaking = null
    interrupted?.onend?.()
  }

  speak(utterance: FakeUtterance): void {
    this.spoken.push(utterance)
    this.speaking = utterance
  }

  /** The browser getting round to it. Sound begins here and nowhere else. */
  begin(): void {
    this.speaking?.onstart?.()
  }

  finish(): void {
    const ending = this.speaking
    this.speaking = null
    ending?.onend?.()
  }

  get said(): string[] {
    return this.spoken.map((utterance) => utterance.text)
  }
}

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

let voice: FakeSynthesis

beforeEach(() => {
  resetTurnTimings()
  FakeRecognition.last = null
  voice = new FakeSynthesis()
  vi.stubGlobal('speechSynthesis', voice)
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  document.cookie = 'pp_csrf=csrf-token-value; path=/'
  window.history.pushState({}, '', '/')
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

function withMicrophone(): void {
  vi.stubGlobal('SpeechRecognition', FakeRecognition)
}

function accepted(speech: string): unknown {
  return {
    case_id: CASE_ID,
    statement_id: 'b7c1e2d3-4f5a-4b6c-8d7e-9f0a1b2c3d4e',
    state: 'CLARIFYING',
    created: true,
    attested_by: 'maya',
    speech,
  }
}

function mountAtCase(
  view: unknown,
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
    ...routes,
  })
  renderApp()
  return { stream, backend }
}

// ------------------------------------------------------------------- the answer, spoken by itself

describe('the backend’s sentence, spoken on turn resolution', () => {
  it('reads the accepted turn’s speech aloud without anybody pressing anything', async () => {
    const REPLY = 'The raspberries are the missing ones. Working out what that touches now.'
    const { stream } = mountAtCase(CLARIFYING_CASE, {
      [CLARIFY_PATH]: () => json(accepted(REPLY), 202),
    })

    await screen.findByTestId('conversation-panel')
    await userEvent.type(screen.getByTestId('answer-text'), 'the raspberries')
    await userEvent.click(screen.getByTestId('answer-send'))

    await waitFor(() => {
      expect(voice.said).toContain(REPLY)
    })
    stream.close()
  })

  it('speaks it byte for byte, adding and removing nothing', async () => {
    const REPLY = 'Planned, and waiting for you. Nothing has been done yet. Say yes to go ahead.'
    const { stream } = mountAtCase(CLARIFYING_CASE, {
      [CLARIFY_PATH]: () => json(accepted(REPLY), 202),
    })

    await screen.findByTestId('conversation-panel')
    await userEvent.type(screen.getByTestId('answer-text'), 'the raspberries')
    await userEvent.click(screen.getByTestId('answer-send'))

    await waitFor(() => {
      expect(voice.said).toContain(REPLY)
    })
    // The whole string and only that string: not trimmed to a first sentence, not shortened to
    // fit a loudspeaker, and not prefixed with a word this screen chose.
    const spoken = voice.spoken.find((utterance) => utterance.text.includes('Planned'))
    expect(spoken?.text).toBe(REPLY)
    stream.close()
  })

  it('speaks a confirmation’s answer too, and it is the backend’s', async () => {
    const REPLY = 'Going ahead with that plan now. Nothing is finished until each order says so.'
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => json(accepted(REPLY), 202),
    })

    await screen.findByTestId('conversation-panel')
    await userEvent.click(screen.getByTestId('conversation-confirm'))

    await waitFor(() => {
      expect(voice.said).toContain(REPLY)
    })
    stream.close()
  })

  it('speaks the receipt for a report, before the case it opened is on screen', async () => {
    const RECEIPT = 'I have written that down exactly as you said it.'
    const { stream } = mountLanding({
      [REPORT_PATH]: () =>
        json(
          {
            case_id: CASE_ID,
            statement_id: 'f1e2d3c4-b5a6-4978-8899-aabbccddeeff',
            state: 'RECEIVED',
            created: true,
            attested_by: 'maya',
            speech: RECEIPT,
          },
          202,
        ),
    })

    await screen.findByTestId('report-entry')
    await userEvent.type(screen.getByTestId('report-text'), 'the raspberries did not arrive')
    await userEvent.click(screen.getByTestId('report-send'))

    await waitFor(() => {
      expect(voice.said).toContain(RECEIPT)
    })
    stream.close()
  })

  it('says nothing at all on arrival, because nobody took a turn', async () => {
    const { stream } = mountAtCase(PLANNED_CASE)

    await screen.findByTestId('conversation-panel')
    // The whole spoken status is on the screen and is not read out. Opening a case is not a
    // question anybody asked.
    expect(screen.getByTestId('conversation-speech')).toHaveTextContent(/Planned, and waiting/)
    expect(voice.said).toEqual([])
    stream.close()
  })
})

// --------------------------------------------------------------- the turn, acknowledged out loud

describe('the acknowledgement while a turn is in flight', () => {
  it('is spoken when the turn is sent, before any answer exists', async () => {
    let answer: (() => void) | null = null
    const held = new Promise<void>((resolve) => {
      answer = resolve
    })
    const { stream } = mountAtCase(CLARIFYING_CASE, {
      [CLARIFY_PATH]: async () => {
        await held
        return json(accepted('Working that out now.'), 202)
      },
    })

    await screen.findByTestId('conversation-panel')
    await userEvent.type(screen.getByTestId('answer-text'), 'the raspberries')
    await userEvent.click(screen.getByTestId('answer-send'))

    // Held open deliberately: the acknowledgement must exist while the backend still has the
    // turn, which is the only moment it is worth anything.
    await waitFor(() => {
      expect(voice.said).toEqual([TURN_ACKNOWLEDGEMENT])
    })
    act(() => {
      answer?.()
    })
    await waitFor(() => {
      expect(voice.said).toHaveLength(2)
    })
    stream.close()
  })

  it('is replaced by the answer rather than queued in front of it', async () => {
    const { stream } = mountAtCase(CLARIFYING_CASE, {
      [CLARIFY_PATH]: () => json(accepted('The raspberries, then.'), 202),
    })

    await screen.findByTestId('conversation-panel')
    await userEvent.type(screen.getByTestId('answer-text'), 'the raspberries')
    await userEvent.click(screen.getByTestId('answer-send'))

    await waitFor(() => {
      expect(voice.said).toEqual([TURN_ACKNOWLEDGEMENT, 'The raspberries, then.'])
    })
    // Cancelled first, so a worker is not made to sit through a progress phrase before hearing
    // the thing they asked for.
    expect(voice.cancelled).toBeGreaterThanOrEqual(2)
    stream.close()
  })

  it('claims no outcome, names no case and holds no digit', () => {
    expect(TURN_ACKNOWLEDGEMENT).not.toMatch(/\d/)
    for (const word of CLAIM_WORDS) {
      expect(TURN_ACKNOWLEDGEMENT.toLowerCase()).not.toMatch(new RegExp(`\\b${word}\\b`))
    }
    // Short enough to be an acknowledgement rather than a summary of the sentence underneath it.
    expect(TURN_ACKNOWLEDGEMENT.split(/\s+/)).toHaveLength(5)
  })
})

// ------------------------------------------------------------ a turn that did not happen, spoken

describe('a refused turn', () => {
  it('says out loud that it did not happen and that the case is unchanged', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () =>
        apiError(409, 'CASE_MOVED_ON', 'that plan is not the one on offer any more'),
    })

    await screen.findByTestId('conversation-panel')
    await userEvent.click(screen.getByTestId('conversation-confirm'))

    await waitFor(() => {
      expect(voice.said).toContain(TURN_DID_NOT_HAPPEN)
    })
    stream.close()
  })

  it('does not read the backend’s refusal message aloud, and still shows it', async () => {
    const MESSAGE = 'that plan is not the one on offer any more'
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => apiError(409, 'CASE_MOVED_ON', MESSAGE),
    })

    await screen.findByTestId('conversation-panel')
    await userEvent.click(screen.getByTestId('conversation-confirm'))

    expect(await screen.findByTestId('conversation-refusal')).toHaveTextContent(MESSAGE)
    await waitFor(() => {
      expect(voice.said).toContain(TURN_DID_NOT_HAPPEN)
    })
    expect(voice.said).not.toContain(MESSAGE)
    stream.close()
  })

  it('never speaks a case sentence for a turn that was refused', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => apiError(409, 'CASE_MOVED_ON', 'refused'),
    })

    await screen.findByTestId('conversation-panel')
    await userEvent.click(screen.getByTestId('conversation-confirm'))

    await waitFor(() => {
      expect(voice.said).toContain(TURN_DID_NOT_HAPPEN)
    })
    expect(voice.said).not.toContain(PLANNED_CASE.speech)
    stream.close()
  })

  it('claims no outcome and holds no digit either', () => {
    expect(TURN_DID_NOT_HAPPEN).not.toMatch(/\d/)
    for (const word of CLAIM_WORDS) {
      expect(TURN_DID_NOT_HAPPEN.toLowerCase()).not.toMatch(new RegExp(`\\b${word}\\b`))
    }
    expect(TURN_DID_NOT_HAPPEN).toMatch(/did not happen/)
  })
})

// ---------------------------------------------------------------------------- the silence rules

describe('when the product stays silent', () => {
  it('says nothing when capture ends, because the worker has had no answer', async () => {
    withMicrophone()
    const { stream } = mountLanding()

    await screen.findByTestId('report-entry')
    await userEvent.click(screen.getByTestId('report-talk'))
    act(() => {
      FakeRecognition.last?.hear('the raspberries did not arrive')
    })
    await userEvent.click(screen.getByTestId('report-talk'))

    expect(await screen.findByTestId('report-transcript')).toBeInTheDocument()
    // The transcript is on screen, nothing has been sent, and the loudspeaker has said nothing.
    // Acknowledging a microphone is not a response to a turn.
    expect(voice.said).toEqual([])
    stream.close()
  })

  it('still shows the transcript for review before anything is sent or spoken', async () => {
    withMicrophone()
    const { stream, backend } = mountLanding()

    await screen.findByTestId('report-entry')
    await userEvent.click(screen.getByTestId('report-talk'))
    act(() => {
      FakeRecognition.last?.hear('the raspberries did not arrive')
    })
    await userEvent.click(screen.getByTestId('report-talk'))

    expect(await screen.findByTestId('report-transcript')).toHaveTextContent(
      'the raspberries did not arrive',
    )
    expect(backend.countOf(REPORT_PATH)).toBe(0)
    expect(voice.said).toEqual([])
    stream.close()
  })
})

// -------------------------------------------------------------------- stop, replay, and anchors

describe('the manual control, now that every turn speaks for itself', () => {
  it('replays the standing status without taking a turn', async () => {
    const { stream, backend } = mountAtCase(PLANNED_CASE)

    await screen.findByTestId('conversation-panel')
    await userEvent.click(screen.getByTestId('conversation-read-aloud'))

    expect(voice.said).toEqual([PLANNED_CASE.speech])
    expect(backend.countOf(CONFIRM_PATH)).toBe(0)
    stream.close()
  })

  it('stops what is being said, and says so about itself afterwards', async () => {
    const { stream } = mountAtCase(PLANNED_CASE)

    await screen.findByTestId('conversation-panel')
    const control = screen.getByTestId('conversation-read-aloud')
    await userEvent.click(control)
    expect(control).toHaveAttribute('aria-pressed', 'true')

    act(() => {
      voice.finish()
    })
    await waitFor(() => {
      expect(control).toHaveAttribute('aria-pressed', 'false')
    })
    stream.close()
  })
})

describe('the instants a turn wrote down', () => {
  it('records first audio when the utterance starts, not when speak returned', async () => {
    const { stream } = mountAtCase(CLARIFYING_CASE, {
      [CLARIFY_PATH]: () => json(accepted('The raspberries, then.'), 202),
    })

    await screen.findByTestId('conversation-panel')
    await userEvent.type(screen.getByTestId('answer-text'), 'the raspberries')
    await userEvent.click(screen.getByTestId('answer-send'))

    await waitFor(() => {
      expect(voice.said).toHaveLength(2)
    })
    // Two utterances have been queued and the browser has begun neither, so nothing is audible
    // and nothing may be recorded as having been heard.
    expect(turnTimings().at(-1)?.audio).toEqual([])

    act(() => {
      voice.begin()
    })
    expect(turnTimings().at(-1)?.audio.map((one) => one.utterance)).toEqual(['reply'])
    stream.close()
  })

  it('writes down both speech-end anchors for a spoken turn, and the two transport instants', async () => {
    withMicrophone()
    const { stream } = mountLanding({
      [REPORT_PATH]: () =>
        json(
          {
            case_id: CASE_ID,
            statement_id: 'f1e2d3c4-b5a6-4978-8899-aabbccddeeff',
            state: 'RECEIVED',
            created: true,
            attested_by: 'maya',
            speech: 'I have written that down exactly as you said it.',
          },
          202,
        ),
    })

    await screen.findByTestId('report-entry')
    await userEvent.click(screen.getByTestId('report-talk'))
    act(() => {
      FakeRecognition.last?.hear('the raspberries did not arrive')
    })
    await userEvent.click(screen.getByTestId('report-talk'))
    await screen.findByTestId('report-transcript')
    await userEvent.click(screen.getByTestId('report-transcript-send'))

    await waitFor(() => {
      expect(turnTimings().at(-1)?.received).not.toBeNull()
    })
    const record = turnTimings().at(-1)
    expect(record?.verb).toBe('report')
    expect(record?.origin).toBe('spoken')
    expect(record?.speech_end_final_result).not.toBeNull()
    expect(record?.speech_end_recogniser_end).not.toBeNull()
    expect(record?.sent).not.toBeNull()
    expect(record?.outcome).toBe('accepted')
    stream.close()
  })

  it('times a refused turn as a response rather than dropping it', async () => {
    const { stream } = mountAtCase(PLANNED_CASE, {
      [CONFIRM_PATH]: () => apiError(409, 'CASE_MOVED_ON', 'refused'),
    })

    await screen.findByTestId('conversation-panel')
    await userEvent.click(screen.getByTestId('conversation-confirm'))

    await waitFor(() => {
      expect(turnTimings().at(-1)?.outcome).toBe('refused')
    })
    const record = turnTimings().at(-1)
    expect(record?.verb).toBe('confirm')
    expect(record?.received).not.toBeNull()
    stream.close()
  })
})
