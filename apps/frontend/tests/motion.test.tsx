/**
 * Motion, and the two rules that decide whether any of it may exist.
 *
 * **It may only follow a backend-confirmed change.** Every animated element on this surface is
 * marked with `data-motion`, and every one of those marks is on something the backend has
 * already said is so: a causal edge the chain returned, a promise state the server now reports,
 * a drawer opened over data already in hand, a case that has arrived. There is no thinking
 * animation, no ambient movement and nothing that moves while a request is in flight — and the
 * surest way to keep it that way is to assert that a pending screen carries no mark at all.
 *
 * **Removing it removes nothing.** The reduced-motion assertion is deliberately not "the
 * animation is absent" — a stylesheet is not applied here and that would be testing the test.
 * It is stronger: the rendered content is *identical* under `prefers-reduced-motion: reduce`, so
 * no sentence, count, state or control is conditional on somebody being willing to watch it
 * move.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CASES, CASE_ID, PLANNED_CASE } from './caseFixtures'
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

/** What a browser set to "reduce" answers, for anything that asks. */
function prefersReducedMotion(reduce: boolean): void {
  vi.stubGlobal(
    'matchMedia',
    (query: string) =>
      ({
        matches: reduce && query.includes('prefers-reduced-motion'),
        media: query,
        onchange: null,
        addListener: () => undefined,
        removeListener: () => undefined,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  )
}

beforeEach(() => {
  document.cookie = 'pp_csrf=csrf-token-value; path=/'
  window.history.pushState({}, '', `/?case=${CASE_ID}`)
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

function mountCase(routes: Record<string, Responder> = {}): { stream: FakeStream } {
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

describe('what is allowed to move', () => {
  it('marks the case that arrived, and nothing while it is still being read', async () => {
    let release: () => void = () => undefined
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    const { stream } = mountCase({
      [CASE_PATH]: async () => {
        await held
        return json(PLANNED_CASE)
      },
    })

    await screen.findByText(/Opening the case/i)
    expect(document.querySelectorAll('[data-motion]')).toHaveLength(0)

    release()
    const workspace = await screen.findByTestId('case-workspace')
    expect(workspace).toHaveAttribute('data-motion', 'settle')
    stream.close()
  })

  it('draws a causal edge the backend returned, and keys a pill to the state it reported', async () => {
    const { stream } = mountCase()

    const workspace = await screen.findByTestId('case-workspace')

    const edges = workspace.querySelectorAll('[data-motion^="draw-"]')
    expect(edges.length).toBeGreaterThan(0)
    for (const pill of workspace.querySelectorAll('[data-testid="promise-status"]')) {
      expect(pill.querySelector('[data-motion="restate"]')).not.toBeNull()
    }
    stream.close()
  })

  it('marks a drawer only once a reader has opened it', async () => {
    const { stream } = mountCase()

    await screen.findByTestId('case-workspace')
    const toggle = screen.getByTestId('evidence-toggle')
    const panel = document.getElementById(toggle.getAttribute('aria-controls') ?? '')

    expect(panel).not.toBeNull()
    expect(panel).not.toHaveAttribute('data-motion')

    await userEvent.click(toggle)

    expect(panel).toHaveAttribute('data-motion', 'settle')
    stream.close()
  })
})

describe('with motion turned off', () => {
  it('says exactly the same thing', async () => {
    prefersReducedMotion(false)
    const moving = mountCase()
    const withMotion = (await screen.findByTestId('case-workspace')).textContent
    moving.stream.close()
    cleanup()
    vi.unstubAllGlobals()

    window.history.pushState({}, '', `/?case=${CASE_ID}`)
    prefersReducedMotion(true)
    const still = mountCase()
    const withoutMotion = (await screen.findByTestId('case-workspace')).textContent
    still.stream.close()

    expect(withoutMotion).toBe(withMotion)
    expect((withoutMotion ?? '').length).toBeGreaterThan(0)
  })

  it('keeps every control and the untouched proof', async () => {
    prefersReducedMotion(true)
    const { stream } = mountCase()

    const workspace = await screen.findByTestId('case-workspace')

    expect(screen.getByTestId('untouched-proof')).toBeInTheDocument()
    expect(screen.getByTestId('conversation-panel')).toBeInTheDocument()
    expect(screen.getByTestId('evidence-toggle')).toBeInTheDocument()
    expect(workspace.querySelectorAll('[data-testid="promise-status"]').length).toBeGreaterThan(0)
    stream.close()
  })
})
