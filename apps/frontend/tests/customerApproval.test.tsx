/**
 * The customer's page, mounted through the whole app exactly as an approval link arrives at it.
 *
 * Rendered through `renderApp` rather than by importing the component, because half of what is
 * under test is the shell's dispatch: an approval address must reach the question without
 * bootstrapping a session, and a page that asked `/api/auth/me` on a customer's behalf would
 * be one refactor away from showing them a sign-in form for an account they cannot have.
 *
 * The rest is about what the page may and may not say. It renders the backend's reading and
 * computes nothing — no deadline comparison, no decision, no price — and it never reports an
 * approval the protocol has not written.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  apiError,
  json,
  mockBackend,
  renderApp,
  type Backend,
  type Responder,
} from './harness'

const TOKEN = 'v1.cGF5bG9hZA.c2lnbmF0dXJl'
const PATH = `/api/customer/approval/${TOKEN}`

/** One open question, in the shape the backend returns it. */
const OPEN = {
  phase: 'OPEN',
  answerable: true,
  customer_name: 'Tomas Lindqvist',
  order_reference: 'EXT-B',
  option_code: 'OPT-A1B2C3',
  due_at: '2026-09-18T14:00:00Z',
  answer_by: '2026-09-18T11:00:00Z',
  from_product: 'Raspberry tart (v1)',
  to_product: 'Blackberry tart (v2)',
  affected_resource: 'raspberries',
  substitute_resource: 'blackberries',
  outcome: null,
  answered_at: null,
}

const CLOSED = {
  phase: 'CLOSED',
  answerable: false,
  customer_name: null,
  order_reference: null,
  option_code: null,
  due_at: null,
  answer_by: null,
  from_product: null,
  to_product: null,
  affected_resource: null,
  substitute_resource: null,
  outcome: null,
  answered_at: null,
}

/** Answers the read, and answers a POST with whatever the test's own route says. */
const RECEIVED: Responder = (record) =>
  record.method === 'POST' ? json({ ...OPEN, phase: 'RECEIVED', answerable: false }) : json(OPEN)

function arriving(routes: Record<string, Responder> = {}): Backend {
  window.history.pushState({}, '', `/?approve=${TOKEN}`)
  return mockBackend({ [PATH]: () => json(OPEN), ...routes })
}

beforeEach(() => {
  document.cookie = 'pp_csrf=csrf-token-value; path=/'
  window.history.pushState({}, '', '/')
})

describe('arriving on an approval link', () => {
  it('reaches the question without bootstrapping a session', async () => {
    const backend = arriving()
    renderApp()

    await screen.findByText('We need your decision')

    expect(backend.countOf('/api/auth/me')).toBe(0)
    expect(backend.countOf('/api/events/stream')).toBe(0)
    expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument()
  })

  it('sends no CSRF token with the read', async () => {
    // The link is the only credential this surface has, and the client is written so that no
    // other one is even reachable from it. A worker signed in on the same browser gains
    // nothing here.
    const backend = arriving()
    renderApp()

    await screen.findByText('We need your decision')

    const read = backend.requests.find((entry) => entry.url === PATH)
    expect(read?.headers['x-csrf-token']).toBeUndefined()
  })

  it('shows the order, the exact change and the ingredient that replaces it', async () => {
    arriving()
    renderApp()

    await screen.findByText('We need your decision')

    expect(screen.getByText('EXT-B')).toBeInTheDocument()
    expect(screen.getByText(/Tomas Lindqvist/)).toBeInTheDocument()
    expect(screen.getByText('Raspberry tart (v1)')).toBeInTheDocument()
    expect(screen.getByText('Blackberry tart (v2)')).toBeInTheDocument()
    expect(screen.getByText('blackberries in place of raspberries')).toBeInTheDocument()
    expect(screen.getByText('OPT-A1B2C3')).toBeInTheDocument()
  })

  it('shows no line for a difference the backend did not send', async () => {
    // A page that rendered a blank row, a dash or "no change" would be making a claim out of
    // an absent column. The line goes instead.
    arriving({
      [PATH]: () =>
        json({ ...OPEN, affected_resource: null, substitute_resource: null, due_at: null }),
    })
    renderApp()

    await screen.findByText('We need your decision')

    expect(screen.queryByText(/in place of/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Due /)).not.toBeInTheDocument()
    expect(screen.queryByText('unknown')).not.toBeInTheDocument()
  })

  it('states no price, because nothing in the product holds one', async () => {
    arriving()
    renderApp()

    await screen.findByText('We need your decision')

    expect(document.body.textContent).not.toMatch(/price|[$€£]\d/i)
  })

  it('claims nothing about whether the change is safe to eat', async () => {
    arriving()
    renderApp()

    await screen.findByText('We need your decision')

    expect(document.body.textContent).not.toMatch(
      /should be fine|safe|allergen|allergy|suitable for/i,
    )
  })
})

describe('answering', () => {
  it('sends the choice and nothing that could name who is answering', async () => {
    const backend = arriving({ [PATH]: RECEIVED })
    renderApp()
    await screen.findByText('We need your decision')

    await userEvent.click(screen.getByRole('button', { name: 'Approve this change' }))

    const sent = backend.requests.find((entry) => entry.method === 'POST')
    expect(sent?.body).toEqual({ answer: 'APPROVE' })
  })

  it('says the answer is kept and does not say what it did', async () => {
    // The whole of the honesty here. The record is durable; the decision is a row the protocol
    // writes later, under the case lock, and this page must not report one that does not exist.
    arriving({ [PATH]: RECEIVED })
    renderApp()
    await screen.findByText('We need your decision')

    await userEvent.click(screen.getByRole('button', { name: 'Approve this change' }))

    await screen.findByText('Thank you — we have your answer')
    expect(screen.queryByText('You approved this change')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve this change' })).not.toBeInTheDocument()
  })

  it('reports the decision once the backend says one exists', async () => {
    arriving({
      [PATH]: () =>
        json({
          ...OPEN,
          phase: 'APPROVED',
          answerable: false,
          answered_at: '2026-09-18T10:31:00Z',
          outcome: 'Your order now shows this change.',
        }),
    })
    renderApp()

    await screen.findByText('You approved this change')
    expect(screen.getByTestId('outcome-sentence')).toHaveTextContent(
      'Your order now shows this change.',
    )
  })

  it('offers a decline that is not drawn as an error', async () => {
    const backend = arriving({ [PATH]: RECEIVED })
    renderApp()
    await screen.findByText('We need your decision')

    await userEvent.click(screen.getByRole('button', { name: 'Decline' }))

    expect(backend.requests.find((entry) => entry.method === 'POST')?.body).toEqual({
      answer: 'DECLINE',
    })
  })

  it('never promises the original order back to somebody who declines', async () => {
    arriving({
      [PATH]: () =>
        json({
          ...OPEN,
          phase: 'DECLINED',
          answerable: false,
          answered_at: '2026-09-18T10:31:00Z',
          outcome: 'The bakery will follow up with you about this order.',
        }),
    })
    renderApp()

    await screen.findByText('You declined this change')
    expect(document.body.textContent).not.toMatch(/as (originally )?ordered|as first agreed/i)
  })

  it('says nothing was recorded when the answer did not reach the bakery', async () => {
    arriving({
      [PATH]: (record) => (record.method === 'POST' ? apiError(503, 'UNAVAILABLE') : json(OPEN)),
    })
    renderApp()
    await screen.findByText('We need your decision')

    await userEvent.click(screen.getByRole('button', { name: 'Approve this change' }))

    await screen.findByRole('alert')
    expect(screen.getByRole('alert')).toHaveTextContent('Nothing was recorded')
    // Still answerable: a failed send left the question exactly where it was.
    expect(screen.getByRole('button', { name: 'Approve this change' })).toBeInTheDocument()
  })
})

describe('a question that is not open', () => {
  it('offers no choice once the window has closed', async () => {
    arriving({ [PATH]: () => json({ ...OPEN, phase: 'EXPIRED', answerable: false }) })
    renderApp()

    await screen.findByText('This question has closed')
    expect(screen.queryByRole('button', { name: 'Approve this change' })).not.toBeInTheDocument()
    expect(document.body.textContent).toMatch(/nothing was done to your order/i)
  })

  it('offers no choice once the order has moved under it', async () => {
    arriving({ [PATH]: () => json({ ...OPEN, phase: 'SUPERSEDED', answerable: false }) })
    renderApp()

    await screen.findByText('This question no longer applies')
    expect(screen.queryByRole('button', { name: 'Approve this change' })).not.toBeInTheDocument()
  })

  it('takes answerable from the backend and never from the deadline it was shown', async () => {
    // `answer_by` is long past and the server says the question is open. The page believes the
    // server: the deadline that decides is the database's, compared under the request's own
    // lock, and a browser second-guessing it with a device clock would be a second deadline.
    arriving({ [PATH]: () => json({ ...OPEN, answer_by: '2000-01-01T00:00:00Z' }) })
    renderApp()

    await screen.findByText('We need your decision')
    expect(screen.getByRole('button', { name: 'Approve this change' })).toBeInTheDocument()
  })

  it('shows nothing about an order when the link opens none', async () => {
    arriving({ [PATH]: () => json(CLOSED) })
    renderApp()

    await screen.findByText('This link does not open anything')
    expect(screen.queryByText('EXT-B')).not.toBeInTheDocument()
    expect(screen.queryByTestId('proposed-change')).not.toBeInTheDocument()
  })

  it('says a forged link opens nothing, without saying why', async () => {
    arriving({ [PATH]: () => apiError(404, 'LINK_NOT_FOUND', 'this link does not open anything') })
    renderApp()

    await screen.findByText('This link does not open anything')
    expect(document.body.textContent).not.toMatch(/signature|token|forged|secret/i)
  })

  it('distinguishes an unreachable bakery from a link that opens nothing', async () => {
    // A 503 is a transport failure, so the shared retry policy tries it again before the page
    // gives up -- which is right, and is why this waits longer than the default. A signature
    // never becomes valid on a second attempt, so the 404 above is not retried at all.
    arriving({ [PATH]: () => apiError(503, 'UNAVAILABLE') })
    renderApp()

    await waitFor(
      () => {
        expect(screen.getByRole('alert')).toHaveTextContent('We cannot reach the bakery')
      },
      { timeout: 10_000 },
    )
    expect(document.body.textContent).toMatch(/nothing about your order has changed/i)
  })
})

describe('the worker app is untouched by it', () => {
  it('still bootstraps a session when the address carries no approval token', async () => {
    window.history.pushState({}, '', '/')
    const backend = mockBackend({
      '/api/auth/me': () => apiError(401, 'UNAUTHENTICATED', 'a valid session is required'),
      '/api/auth/options': () => json({ demo_session: false }),
    })
    renderApp()

    await screen.findByRole('button', { name: 'Sign in' })
    expect(backend.countOf('/api/auth/me')).toBe(1)
  })
})
