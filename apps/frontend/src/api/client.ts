/**
 * The one place this app talks to the backend.
 *
 * Three rules, each of which exists because breaking it would move authority into the browser:
 *
 * - **Credentials are the cookie, and nothing else.** Every request is sent with
 *   `credentials: 'include'`; no token is read, stored or attached. The session lives in an
 *   `HttpOnly` cookie the server issued, so this module could not hold one if it wanted to.
 * - **An error is the backend's envelope.** Failures arrive as `{"error": {code, message}}`,
 *   and `ApiError` carries the status and that code so a caller can branch on `401` without
 *   pattern-matching on a sentence. Nothing internal is surfaced to a screen.
 * - **No business logic.** This layer parses and types; it computes nothing the backend
 *   already computed.
 *
 * The CSRF token is the deliberate exception to "read nothing": the backend sets `pp_csrf` as
 * a readable cookie precisely so a client can echo it in `X-CSRF-Token` on a mutation, and
 * validates the header against the session row rather than against the cookie.
 */
import type { ErrorResponse, PromisesResponse, ResourcesResponse, WorkerResponse } from './types'

/** Empty by default: same-origin through the Vite proxy. See `vite.config.ts`. */
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

const CSRF_COOKIE = 'pp_csrf'
const CSRF_HEADER = 'X-CSRF-Token'

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

/** A failed request, carrying the backend's stable code rather than a parsed message. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }

  get isUnauthenticated(): boolean {
    return this.status === 401
  }
}

/** The CSRF token the backend set, or `''` when there is no session. */
export function csrfToken(): string {
  const match = document.cookie.split('; ').find((entry) => entry.startsWith(`${CSRF_COOKIE}=`))
  return match ? decodeURIComponent(match.slice(CSRF_COOKIE.length + 1)) : ''
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false
  const body = value.error
  return (
    typeof body === 'object' &&
    body !== null &&
    typeof (body as { code?: unknown }).code === 'string' &&
    typeof (body as { message?: unknown }).message === 'string'
  )
}

async function toApiError(response: Response): Promise<ApiError> {
  // A failure that is not the documented envelope is still a failure. It is reported with the
  // status and a neutral sentence rather than with whatever body happened to arrive, because
  // an unexpected body is exactly the case where the contents are least safe to show.
  let parsed: unknown = null
  try {
    parsed = await response.json()
  } catch {
    parsed = null
  }
  if (isErrorResponse(parsed)) {
    return new ApiError(response.status, parsed.error.code, parsed.error.message)
  }
  return new ApiError(response.status, 'UNEXPECTED_RESPONSE', 'the request could not be completed')
}

interface RequestOptions {
  method?: string
  body?: unknown
  signal?: AbortSignal
}

async function request(path: string, options: RequestOptions = {}): Promise<Response> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  // Reads are CSRF-exempt on the server and the header is omitted for them, which keeps the
  // set of requests carrying a token the same as the set of requests that change something.
  if (method !== 'GET' && method !== 'HEAD') {
    const token = csrfToken()
    if (token) headers[CSRF_HEADER] = token
  }

  const init: RequestInit = {
    method,
    headers,
    credentials: 'include',
    ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
    ...(options.signal ? { signal: options.signal } : {}),
  }

  const response = await fetch(apiUrl(path), init)
  if (!response.ok) throw await toApiError(response)
  return response
}

async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await request(path, options)
  return (await response.json()) as T
}

// ---------------------------------------------------------------------------- the endpoints

export async function login(username: string, password: string): Promise<WorkerResponse> {
  return requestJson<WorkerResponse>('/api/auth/login', {
    method: 'POST',
    body: { username, password },
  })
}

export async function logout(): Promise<void> {
  await request('/api/auth/logout', { method: 'POST' })
}

/** The signed-in worker, or `null` when there is no live session. */
export async function fetchMe(signal?: AbortSignal): Promise<WorkerResponse | null> {
  try {
    return await requestJson<WorkerResponse>('/api/auth/me', signal ? { signal } : {})
  } catch (error) {
    // Signed out is a normal answer to "who am I", not a failure to report. Anything else is
    // a real error and is allowed to propagate.
    if (error instanceof ApiError && error.isUnauthenticated) return null
    throw error
  }
}

export async function fetchPromises(signal?: AbortSignal): Promise<PromisesResponse> {
  return requestJson<PromisesResponse>('/api/promises', signal ? { signal } : {})
}

export async function fetchResources(signal?: AbortSignal): Promise<ResourcesResponse> {
  return requestJson<ResourcesResponse>('/api/resources', signal ? { signal } : {})
}
