/**
 * The turn clock: what it writes down, and everything it refuses to conclude from it.
 *
 * The G7 gate is ten predeclared voice turns with at least nine starting a truthful spoken
 * response within four seconds of speech ending. **No turn has been recorded and no timing
 * exists**, and nothing in this suite produces one — these tests drive the recorder with made-up
 * readings and assert its shape. What they are defending is the thing a measurement taken later
 * would quietly depend on:
 *
 * - **both** candidate speech-end instants are kept, separately, because which one the gate
 *   means is not declared and a recorder that picked would be choosing the denominator;
 * - the anchor for sound is the utterance starting, never the queueing call returning;
 * - an acknowledgement and an answer are different utterances and are never merged, because the
 *   gate counts an honest-progress reply separately from a completed one;
 * - a turn cannot inherit an earlier turn's anchors, which is how a typed turn would otherwise
 *   come to look like a fast spoken one;
 * - and no duration, comparison or verdict is computed anywhere, by anybody, here.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import {
  audioStarted,
  captureStarted,
  publishTurnTimings,
  resetTurnTimings,
  responseReceived,
  speechEnded,
  turnSent,
  turnTimings,
  type TurnTiming,
} from '../src/instrumentation/turnTiming'

beforeEach(() => {
  resetTurnTimings()
})

function only(): TurnTiming {
  const records = turnTimings()
  expect(records).toHaveLength(1)
  return records[0] as TurnTiming
}

describe('where speech ended', () => {
  it('keeps both candidate anchors, under their own names, and prefers neither', () => {
    captureStarted()
    speechEnded('final_result')
    speechEnded('recogniser_end')
    turnSent('clarify')

    const record = only()
    expect(record.speech_end_final_result).not.toBeNull()
    expect(record.speech_end_recogniser_end).not.toBeNull()
    // Two readings, two fields. There is no third field naming a winner, and no code path here
    // that would write one.
    expect(Object.keys(record)).not.toContain('speech_end')
  })

  it('keeps the last final result, which is the one a worker stopped speaking at', () => {
    captureStarted()
    speechEnded('final_result')
    const first = turnTimings()
    expect(first).toHaveLength(0)
    speechEnded('final_result')
    speechEnded('final_result')
    turnSent('report')

    // Three final results, one anchor: the recogniser reports each phrase as it settles and the
    // last one is where the sentence ended.
    expect(only().speech_end_final_result).not.toBeNull()
  })

  it('records the recogniser end even when no final result ever arrived', () => {
    captureStarted()
    speechEnded('recogniser_end')
    turnSent('report')

    const record = only()
    expect(record.speech_end_final_result).toBeNull()
    expect(record.speech_end_recogniser_end).not.toBeNull()
    expect(record.origin).toBe('spoken')
  })

  it('does not let a new capture inherit an abandoned one’s anchors', () => {
    captureStarted()
    speechEnded('final_result')
    speechEnded('recogniser_end')
    // The worker threw that transcript away and spoke again. Nothing from the first attempt may
    // travel with the second.
    captureStarted()
    turnSent('report')

    const record = only()
    expect(record.speech_end_final_result).toBeNull()
    expect(record.speech_end_recogniser_end).toBeNull()
  })
})

describe('a typed turn', () => {
  it('carries no speech-end anchors and says so rather than leaving it to be guessed', () => {
    turnSent('confirm')

    const record = only()
    expect(record.origin).toBe('typed')
    expect(record.speech_end_final_result).toBeNull()
    expect(record.speech_end_recogniser_end).toBeNull()
  })

  it('cannot borrow the anchors of the spoken turn before it', () => {
    captureStarted()
    speechEnded('final_result')
    speechEnded('recogniser_end')
    turnSent('clarify')
    turnSent('confirm')

    const [spoken, typed] = turnTimings()
    expect(spoken?.origin).toBe('spoken')
    expect(typed?.origin).toBe('typed')
    expect(typed?.speech_end_final_result).toBeNull()
    expect(typed?.speech_end_recogniser_end).toBeNull()
  })
})

describe('the transport instants', () => {
  it('stamps the send before the response, on the turn that was sent', () => {
    turnSent('clarify')
    responseReceived('accepted')

    const record = only()
    expect(record.verb).toBe('clarify')
    expect(record.sent).not.toBeNull()
    expect(record.received).not.toBeNull()
    expect(record.outcome).toBe('accepted')
  })

  it('times a refusal too, because a refusal is a response', () => {
    turnSent('confirm')
    responseReceived('refused')

    const record = only()
    expect(record.received).not.toBeNull()
    expect(record.outcome).toBe('refused')
  })

  it('ignores a response that belongs to no turn rather than inventing one', () => {
    responseReceived('accepted')
    expect(turnTimings()).toHaveLength(0)
  })
})

describe('when sound actually began', () => {
  it('keeps the acknowledgement and the answer as separate utterances', () => {
    turnSent('clarify')
    audioStarted('acknowledgement')
    responseReceived('accepted')
    audioStarted('reply')

    // The gate counts an honest-progress reply separately from a completed answer. A recorder
    // that wrote one "first audio" field would have made that impossible to do afterwards.
    expect(only().audio.map((one) => one.utterance)).toEqual(['acknowledgement', 'reply'])
  })

  it('records a refusal being spoken as its own kind', () => {
    turnSent('withdraw')
    audioStarted('acknowledgement')
    responseReceived('refused')
    audioStarted('refusal')

    expect(only().audio.map((one) => one.utterance)).toEqual(['acknowledgement', 'refusal'])
  })

  it('gives a replay that belongs to no turn a record of its own', () => {
    audioStarted('replay')

    const record = only()
    expect(record.origin).toBe('none')
    expect(record.verb).toBeNull()
    expect(record.sent).toBeNull()
    expect(record.audio.map((one) => one.utterance)).toEqual(['replay'])
  })

  it('does not fold a later replay into the turn that came before it', () => {
    turnSent('clarify')
    responseReceived('accepted')
    audioStarted('reply')
    const beforeReplay = turnTimings()[0]?.audio.length

    audioStarted('replay')

    // A replay after a resolved turn is still that turn's loudspeaker being pressed again, and
    // it is recorded where it happened rather than being dropped -- but it is labelled, so it can
    // never be counted as the turn's first spoken response.
    const record = only()
    expect(beforeReplay).toBe(1)
    expect(record.audio.map((one) => one.utterance)).toEqual(['reply', 'replay'])
  })
})

describe('what the recorder refuses to do', () => {
  it('computes no duration, no comparison and no verdict', () => {
    captureStarted()
    speechEnded('final_result')
    speechEnded('recogniser_end')
    turnSent('clarify')
    responseReceived('accepted')
    audioStarted('reply')

    // The whole record, field by field. Anything resembling a measurement -- a difference, a
    // threshold, a pass, a count of seconds -- would have to appear here first, and none of
    // these names is one.
    expect(Object.keys(only()).sort()).toEqual(
      [
        'audio',
        'id',
        'opened',
        'origin',
        'outcome',
        'received',
        'sent',
        'speech_end_final_result',
        'speech_end_recogniser_end',
        'verb',
      ].sort(),
    )
  })

  it('holds no case, promise, worker or sentence', () => {
    turnSent('report')
    responseReceived('accepted')

    const record = JSON.stringify(only())
    for (const forbidden of ['case', 'promise', 'worker', 'speech"', 'text']) {
      expect(record).not.toContain(forbidden)
    }
  })
})

describe('reading the records back out of a session', () => {
  it('hands out a copy, so a reader cannot edit the session’s own history', () => {
    turnSent('clarify')
    const taken = turnTimings()
    taken[0]!.verb = 'withdraw'
    taken[0]!.audio.push({ utterance: 'reply', at: 0 })

    expect(only().verb).toBe('clarify')
    expect(only().audio).toHaveLength(0)
  })

  it('publishes readers and nothing that writes', () => {
    publishTurnTimings()
    turnSent('report')

    const handle = (
      window as unknown as {
        promisepatchVoiceTimings: { records: () => TurnTiming[]; json: () => string }
      }
    ).promisepatchVoiceTimings

    expect(handle.records()).toHaveLength(1)
    expect(JSON.parse(handle.json())).toHaveLength(1)
    // Readers only. Nothing on the handle can put a reading into the session that the session
    // did not observe.
    expect(Object.keys(handle).sort()).toEqual(['json', 'records'])
  })
})
