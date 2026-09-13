/**
 * The four voice states that belong to a case rather than to a microphone.
 *
 * The P7.1 voice contract fixes nine, and says every one of them needs a visible treatment as
 * well as an audible one, because the text path is the same product rather than a degraded copy
 * of it. Five are postures of capture and are proved in `voice.test.tsx`. These four are
 * postures of a case, and the thing worth asserting about them is what they are read *off*:
 * every branch is a field the backend published, and no branch consults a role, a colour or a
 * sentence the screen wrote.
 *
 * `unavailable` is deliberately about the turn and not the case. A refused turn leaves the case
 * exactly as it was, and a state that said otherwise would be the surface reporting a change
 * nobody made.
 */
import { describe, expect, it } from 'vitest'
import { CASE_VOICE_LABEL, caseVoiceState } from '../src/features/case/voiceState'
import { APPLYING_CASE, CLARIFYING_CASE, PLANNED_CASE, SETTLED_CASE } from './caseFixtures'

const settled = { pending: false, refused: false }

describe('what the conversation is doing, read off the case', () => {
  it('is clarifying while the backend reports an open question', () => {
    expect(CLARIFYING_CASE.question).not.toBeNull()
    expect(caseVoiceState(CLARIFYING_CASE, settled)).toBe('clarifying')
  })

  it('is confirming while the backend says a plan is awaiting one', () => {
    expect(PLANNED_CASE.awaiting_confirmation).toBe(true)
    expect(caseVoiceState(PLANNED_CASE, settled)).toBe('confirming')
  })

  it('is processing while the backend says the case is still working', () => {
    expect(APPLYING_CASE.headline).toBe('WORKING')
    expect(caseVoiceState(APPLYING_CASE, settled)).toBe('processing')
  })

  it('is waiting when the case asks nothing of this worker', () => {
    expect(SETTLED_CASE.awaiting_confirmation).toBe(false)
    expect(SETTLED_CASE.question).toBeNull()
    expect(caseVoiceState(SETTLED_CASE, settled)).toBe('waiting')
  })
})

describe('what the conversation is doing, read off the turn', () => {
  it('is processing while one is in flight, whatever the case says', () => {
    expect(caseVoiceState(SETTLED_CASE, { pending: true, refused: false })).toBe('processing')
  })

  it('says the turn did not happen when it was refused, and claims nothing about the case', () => {
    expect(caseVoiceState(PLANNED_CASE, { pending: false, refused: true })).toBe('unavailable')
    // The plan is still on offer. The refusal changed the turn, not the case.
    expect(PLANNED_CASE.awaiting_confirmation).toBe(true)
  })

  it('prefers the refusal to the flight, so a failed retry is not shown as progress', () => {
    expect(caseVoiceState(PLANNED_CASE, { pending: true, refused: true })).toBe('unavailable')
  })
})

describe('every state has words', () => {
  it('names all five without a colour', () => {
    const states = [
      'processing',
      'clarifying',
      'confirming',
      'waiting',
      'unavailable',
    ] as const
    for (const state of states) {
      expect(CASE_VOICE_LABEL[state].trim().length).toBeGreaterThan(0)
    }
  })

  it('claims no outcome in any of them', () => {
    // None of these may read as a result. "Recovered", "done", "changed" and "sent" are band 3's
    // to say, from the backend's own phrase for one promise, and never a chip about a turn.
    for (const label of Object.values(CASE_VOICE_LABEL)) {
      expect(label).not.toMatch(/recovered|done|changed|sent|complete|success/i)
    }
  })
})
