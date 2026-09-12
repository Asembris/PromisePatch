/**
 * The state system, held to the three rules that make it safe.
 *
 * These are table tests rather than screen tests on purpose. The hazard this replaces was a
 * function that chose a colour by looking for substrings in a state name — so the guard has to
 * be over the whole vocabulary at once, not over the handful of states one fixture happens to
 * contain. A state the backend adds and this build has never seen is caught by the compiler
 * (`Record<PromiseState, …>` has no default branch); a state that has *drifted* into a
 * forbidden reading is caught here.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen, within } from '@testing-library/react'
import { PromiseStatePill, StateBadge } from '../src/components/badges'
import {
  ACTION_OWNERS,
  ACTION_OWNER_TONE,
  AUTHORITIES,
  AUTHORITY_TONE,
  CASE_HEADLINES,
  CASE_HEADLINE_TONE,
  MARKER_CLASSES,
  PROMISE_STATES,
  PROMISE_STATE_TREATMENT,
  TONE_PILL,
  TONE_TEXT,
  promiseStateTreatment,
} from '../src/components/vocabulary'

// ------------------------------------------------------------------ every value is accounted for

describe('the closed vocabularies', () => {
  it('treats all fourteen promise states and no others', () => {
    expect(PROMISE_STATES).toHaveLength(14)
    expect(Object.keys(PROMISE_STATE_TREATMENT).sort()).toEqual([...PROMISE_STATES].sort())
  })

  it('treats all nine case headlines and no others', () => {
    expect(CASE_HEADLINES).toHaveLength(9)
    expect(Object.keys(CASE_HEADLINE_TONE).sort()).toEqual([...CASE_HEADLINES].sort())
  })

  it('treats every action owner and every authority', () => {
    expect(Object.keys(ACTION_OWNER_TONE).sort()).toEqual([...ACTION_OWNERS].sort())
    expect(Object.keys(AUTHORITY_TONE).sort()).toEqual([...AUTHORITIES].sort())
  })

  it('resolves every tone and every marker it names to real classes', () => {
    for (const state of PROMISE_STATES) {
      const treatment = PROMISE_STATE_TREATMENT[state]
      expect(TONE_PILL[treatment.tone], state).toBeTruthy()
      expect(TONE_TEXT[treatment.tone], state).toBeTruthy()
      expect(MARKER_CLASSES[treatment.marker], state).toBeTruthy()
    }
  })
})

// ------------------------------------------------------------------ what may never be claimed

describe('what a state may never claim', () => {
  it('lets exactly one state read as finished, and it is RECOVERED', () => {
    const finished = PROMISE_STATES.filter((state) => PROMISE_STATE_TREATMENT[state].finished)
    expect(finished).toEqual(['RECOVERED'])
  })

  it('gives the done tone to RECOVERED alone', () => {
    const done = PROMISE_STATES.filter((state) => PROMISE_STATE_TREATMENT[state].tone === 'done')
    expect(done).toEqual(['RECOVERED'])
  })

  it('never lets a case headline reach the done tone', () => {
    // A settled case is a case that has stopped. It is not an order that changed, and a
    // terminal case can still hold an escalation nobody has dealt with.
    for (const headline of CASE_HEADLINES) {
      expect(CASE_HEADLINE_TONE[headline], headline).not.toBe('done')
    }
  })

  it('never draws UNTOUCHED as a success', () => {
    const untouched = PROMISE_STATE_TREATMENT.UNTOUCHED
    expect(untouched.finished).toBe(false)
    expect(untouched.tone).toBe('neutral')
    expect(untouched.marker).not.toBe('filled')
  })

  it('separates permission, acknowledgement and the act', () => {
    // AUTHORIZED is permission, CONSENTED is the customer's decision, APPLYING is work in
    // flight, REQUESTED is a provider acknowledging delivery. None of them is the change.
    for (const state of ['AUTHORIZED', 'CONSENTED', 'APPLYING', 'REQUESTED'] as const) {
      expect(PROMISE_STATE_TREATMENT[state].finished, state).toBe(false)
      expect(PROMISE_STATE_TREATMENT[state].tone, state).not.toBe('done')
    }
    const readings = new Set(
      (['AUTHORIZED', 'APPLYING', 'RECOVERED'] as const).map((state) => {
        const { tone, marker } = PROMISE_STATE_TREATMENT[state]
        return `${tone}/${marker}`
      }),
    )
    expect(readings.size).toBe(3)
  })

  it('never lets worker confirmation and customer consent share a colour', () => {
    // `brand` is the worker-interaction channel; no promise state may borrow it, because a
    // customer's decision and a worker's confirmation are two authorities and two records.
    for (const state of PROMISE_STATES) {
      expect(PROMISE_STATE_TREATMENT[state].tone, state).not.toBe('brand')
    }
    expect(ACTION_OWNER_TONE.YOU).toBe('brand')
    expect(PROMISE_STATE_TREATMENT.CONSENTED.tone).toBe('ask')
  })
})

// ---------------------------------------------------------------- never colour alone

describe('legibility with no colour at all', () => {
  it('gives every pair of states a different tone or a different marker shape', () => {
    const seen = new Map<string, string>()
    for (const state of PROMISE_STATES) {
      const { tone, marker } = PROMISE_STATE_TREATMENT[state]
      const key = `${tone}/${marker}`
      expect(seen.get(key), `${state} is indistinguishable from ${seen.get(key) ?? ''}`).toBe(
        undefined,
      )
      seen.set(key, state)
    }
    expect(seen.size).toBe(PROMISE_STATES.length)
  })

  it('shows the phrase, the state name and a marker for every state', () => {
    for (const state of PROMISE_STATES) {
      const { unmount } = render(<PromiseStatePill state={state} phrase={`phrase for ${state}`} />)
      const pill = screen.getByTestId('promise-status')
      expect(within(pill).getByText(`phrase for ${state}`)).toBeInTheDocument()
      expect(within(pill).getByText(state)).toBeInTheDocument()
      expect(within(pill).getByTestId('state-marker')).toHaveAttribute(
        'data-marker',
        PROMISE_STATE_TREATMENT[state].marker,
      )
      unmount()
    }
  })
})

// --------------------------------------------------------------------- what an unknown value does

describe('a value this build has never seen', () => {
  it('falls closed to the default rather than to any outcome', () => {
    const treatment = promiseStateTreatment('SOMETHING_NEW')
    expect(treatment).toEqual(PROMISE_STATE_TREATMENT.AWAITING_PLAN)
    expect(treatment.finished).toBe(false)
    expect(treatment.tone).not.toBe('done')
  })

  it('still prints the unknown name verbatim', () => {
    render(<PromiseStatePill state="SOMETHING_NEW" phrase="not decided yet" />)
    expect(screen.getByText('SOMETHING_NEW')).toBeInTheDocument()
  })

  it('gives an engine string with no table of its own a neutral badge, never a guessed one', () => {
    // The substring matcher this replaced read `UNAFFECTED` as a success. Nothing infers a
    // tone from the shape of a word any more, so an order state, a track state or a
    // classification is printed and nothing is claimed about it.
    for (const value of ['UNAFFECTED', 'BLOCKED', 'AUTO_RECOVERABLE', 'IN_SERVICE']) {
      const { unmount } = render(<StateBadge state={value} />)
      const badge = screen.getByText(value)
      expect(badge.className).toContain(TONE_PILL.neutral)
      expect(badge.className).not.toContain('done')
      unmount()
    }
  })
})

// --------------------------------------------------------------------- the two global CSS rules

/**
 * Both of these are stylesheet facts rather than rendered ones — jsdom applies no author
 * stylesheet, so this asserts on the source that ships, which is where the regression would
 * actually be. It is a weaker check than a browser would give and is named as one.
 */
describe('the global rules the stylesheet carries', () => {
  const css = readFileSync(
    resolve(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'index.css'),
    'utf8',
  )

  it('puts a visible focus ring on everything, in the interaction colour', () => {
    const rule = /:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--color-brand\)[^}]*\}/
    expect(css).toMatch(rule)
  })

  it('honours prefers-reduced-motion globally', () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
    expect(css).toMatch(/transition-duration:\s*0\.01ms\s*!important/)
  })
})
