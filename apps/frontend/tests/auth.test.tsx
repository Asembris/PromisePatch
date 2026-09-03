/**
 * Signing in, being already signed in, signing out, and being signed out by the server.
 *
 * The last one is the interesting case. A session can be revoked while a screen is open, and
 * the honest response is to return to the login screen rather than to keep rendering an order
 * book behind a session the server has already refused.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MAYA, PROMISES, RESOURCES } from './fixtures'
import {
  FakeStream,
  apiError,
  json,
  mockBackend,
  renderApp,
  streamResponse,
  type Responder,
} from './harness'

function signedOutRoutes(): Record<string, Responder> {
  return {
    '/api/auth/me': () => apiError(401, 'UNAUTHENTICATED', 'a valid session is required'),
  }
}

beforeEach(() => {
  document.cookie = 'pp_csrf=csrf-token-value; path=/'
})

describe('authentication', () => {
  it('shows the login screen when nobody is signed in', async () => {
    mockBackend(signedOutRoutes())
    renderApp()

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByText('Live Operations')).not.toBeInTheDocument()
  })

  it('never prefills a password', async () => {
    mockBackend(signedOutRoutes())
    renderApp()

    const password = await screen.findByLabelText('Password')
    expect(password).toHaveValue('')
  })

  it('moves to Live Operations on a valid login and sends credentials only to the backend', async () => {
    const stream = new FakeStream()
    const backend = mockBackend({
      '/api/auth/me': () => apiError(401, 'UNAUTHENTICATED'),
      '/api/auth/login': () => json(MAYA),
      '/api/promises': () => json(PROMISES),
      '/api/resources': () => json(RESOURCES),
      '/events': () => streamResponse(stream),
    })
    renderApp()

    await userEvent.type(await screen.findByLabelText('Worker'), 'maya')
    await userEvent.type(screen.getByLabelText('Password'), 'a-demo-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Live Operations')).toBeInTheDocument()
    expect(await screen.findByText('Maya')).toBeInTheDocument()
    expect(screen.getByText(/baker/)).toBeInTheDocument()

    const login = backend.requests.find((entry) => entry.url === '/api/auth/login')
    expect(login?.body).toEqual({ username: 'maya', password: 'a-demo-password' })
    // The session is a cookie the server issued; nothing is kept client-side.
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
    stream.close()
  })

  it('reports a rejected login with the backend message and stays on the login screen', async () => {
    mockBackend({
      '/api/auth/me': () => apiError(401, 'UNAUTHENTICATED'),
      '/api/auth/login': () => apiError(401, 'INVALID_CREDENTIALS', 'the username or password is incorrect'),
    })
    renderApp()

    await userEvent.type(await screen.findByLabelText('Worker'), 'maya')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('the username or password is incorrect')
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('restores an existing session from /api/auth/me without a login', async () => {
    const stream = new FakeStream()
    const backend = mockBackend({
      '/api/auth/me': () => json(MAYA),
      '/api/promises': () => json(PROMISES),
      '/api/resources': () => json(RESOURCES),
      '/events': () => streamResponse(stream),
    })
    renderApp()

    expect(await screen.findByText('Live Operations')).toBeInTheDocument()
    expect(backend.countOf('/api/auth/login')).toBe(0)
    stream.close()
  })

  it('returns to the login screen on sign-out and clears the protected data', async () => {
    const stream = new FakeStream()
    const backend = mockBackend({
      '/api/auth/me': () => json(MAYA),
      '/api/promises': () => json(PROMISES),
      '/api/resources': () => json(RESOURCES),
      '/api/auth/logout': () => new Response(null, { status: 204 }),
      '/events': () => streamResponse(stream),
    })
    renderApp()

    expect(await screen.findByText('Amara Fell')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    // Not merely hidden behind a route: the rows are gone from the cache.
    expect(screen.queryByText('Amara Fell')).not.toBeInTheDocument()
    expect(screen.queryByTestId('promise-row')).not.toBeInTheDocument()

    const logout = backend.requests.find((entry) => entry.url === '/api/auth/logout')
    expect(logout?.method).toBe('POST')
    // The backend requires the CSRF token bound to the session for this mutation.
    expect(logout?.headers['x-csrf-token']).toBe('csrf-token-value')
    stream.close()
  })

  it('returns to the login screen when a protected read is refused mid-session', async () => {
    const stream = new FakeStream()
    const backend = mockBackend({
      '/api/auth/me': () => json(MAYA),
      '/api/promises': () => json(PROMISES),
      '/api/resources': () => json(RESOURCES),
      '/events': () => streamResponse(stream),
    })
    renderApp()
    expect(await screen.findByText('Amara Fell')).toBeInTheDocument()

    // The session is revoked behind the app's back, then an event prompts a refetch.
    backend.on('/api/promises', () => apiError(401, 'UNAUTHENTICATED'))
    backend.on('/api/resources', () => apiError(401, 'UNAUTHENTICATED'))
    await stream.opened
    stream.push('fixture.reset', { seq: 42, type: 'fixture.reset' }, 42)

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByText('Amara Fell')).not.toBeInTheDocument()
    stream.close()
  })
})
