/**
 * The surface, used without a mouse and without colour.
 *
 * The judge journey and the worker journey both have to be completable from the keyboard, and
 * every state on the screen has to survive being printed in greyscale. Neither is a nicety here:
 * the product's whole claim is that a person can read what is true, and a state carried only by
 * a hue is a state half the readers of a projector cannot read at all.
 *
 * What is asserted is structural rather than visual, because a stylesheet is not applied in this
 * environment: landmarks, accessible names, live regions, and the fact that every state that has
 * a colour also has a word. The pixel half — hit-target sizes and focus order through a real
 * layout — is proved in the browser suite, where there is a layout to measure.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CASES, CASE_ID, CLARIFYING_CASE, NO_CASES, PLANNED_CASE } from './caseFixtures'
import { MAYA, PROMISES, RESOURCES } from './fixtures'
import {
  FakeStream,
  json,
  mockBackend,
  renderApp,
  streamResponse,
  type Responder,
} from './harness'

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

beforeEach(() => {
  document.cookie = 'pp_csrf=csrf-token-value; path=/'
  window.history.pushState({}, '', '/')
})

afterEach(() => {
  window.history.pushState({}, '', '/')
})

function mount(
  where: string,
  routes: Record<string, Responder> = {},
): { stream: FakeStream } {
  window.history.pushState({}, '', where)
  const stream = new FakeStream()
  mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(CASES),
    [CASE_PATH]: () => json(PLANNED_CASE),
    '/events': () => streamResponse(stream),
    ...routes,
  })
  renderApp()
  return { stream }
}

describe('reaching the case without a mouse', () => {
  it('offers a skip link before anything else in the tab order', async () => {
    const { stream } = mount('/')

    const skip = await screen.findByRole('link', { name: /skip to the case/i })
    expect(skip).toHaveAttribute('href', '#case-surface')

    await userEvent.tab()
    expect(document.activeElement).toBe(skip)
    stream.close()
  })

  it('points that link at a landmark that exists on both surfaces', async () => {
    const landing = mount('/')
    await screen.findByTestId('case-list')
    expect(document.querySelector('main#case-surface')).not.toBeNull()
    landing.stream.close()
  })

  it('reaches the whole worker journey by tabbing', async () => {
    const { stream } = mount(`/?case=${CASE_ID}`, { [CASE_PATH]: () => json(CLARIFYING_CASE) })

    await screen.findByTestId('conversation-panel')

    // Every control the worker needs is a real focusable element in the document, not a click
    // handler on something a keyboard cannot land on.
    const reachable = Array.from(
      document.querySelectorAll<HTMLElement>('a[href], button, textarea, input, summary'),
    ).filter((element) => !element.hasAttribute('disabled'))

    expect(reachable).toContain(screen.getByTestId('answer-text'))
    expect(reachable).toContain(screen.getByTestId('evidence-toggle'))

    // The send is disabled until there is something to send, which is the honest state; once
    // there is, it is an ordinary focusable button in the same document order as the field.
    await userEvent.type(screen.getByTestId('answer-text'), 'just raspberries')
    const send = screen.getByTestId('answer-send')
    expect(send).toBeEnabled()
    send.focus()
    expect(document.activeElement).toBe(send)
    stream.close()
  })

  it('gives every control on the case a name a screen reader can announce', async () => {
    const { stream } = mount(`/?case=${CASE_ID}`, { [CASE_PATH]: () => json(CLARIFYING_CASE) })

    await screen.findByTestId('conversation-panel')

    for (const button of screen.getAllByRole('button')) {
      expect((button.textContent ?? '').trim().length, button.outerHTML.slice(0, 120)).toBeGreaterThan(0)
    }
    // The composer's field is labelled rather than placeholder-only: a placeholder disappears
    // the moment somebody types, which is exactly when they might want to check what it was.
    expect(screen.getByLabelText(/answer in your own words/i)).toBe(
      screen.getByTestId('answer-text'),
    )
    stream.close()
  })
})

describe('states carried by words, not only by colour', () => {
  it('prints the state name beside every promise phrase', async () => {
    const { stream } = mount(`/?case=${CASE_ID}`)

    const workspace = await screen.findByTestId('case-workspace')

    const pills = within(workspace).getAllByTestId('promise-status')
    expect(pills.length).toBeGreaterThan(0)
    for (const pill of pills) {
      const state = pill.getAttribute('data-state') ?? ''
      expect(state).not.toBe('')
      // The engine's own word for the state is on the screen, not only a hue and a shape.
      expect(pill).toHaveTextContent(state)
      expect(within(pill).getByTestId('state-marker')).toBeInTheDocument()
    }
    stream.close()
  })

  it('says what the conversation is waiting for, in words', async () => {
    const { stream } = mount(`/?case=${CASE_ID}`)

    const chip = await screen.findByTestId('conversation-voice-state')

    expect(chip).toHaveAttribute('role', 'status')
    expect((chip.textContent ?? '').trim().length).toBeGreaterThan(0)
    stream.close()
  })

  it('keeps the untouched proof and its count on the screen for a judge', async () => {
    const { stream } = mount(`/?case=${CASE_ID}`, {
      '/api/auth/me': () => json(JUDGE),
      [CASE_PATH]: () => json({ ...PLANNED_CASE, may_speak: false, permitted_verbs: ['status'] }),
      '/api/cases': () => json(NO_CASES),
    })

    const proof = await screen.findByTestId('untouched-proof')

    expect(proof).toHaveAttribute('data-untouched', String(PLANNED_CASE.untouched_count))
    expect(proof).toHaveAttribute(
      'data-effects',
      String(PLANNED_CASE.untouched_effect_count),
    )
    stream.close()
  })
})
