/**
 * A fake backend, and the way a test mounts the app against it.
 *
 * The seam is `fetch`, deliberately: everything this app does to the backend — the reads, the
 * two mutations and the event stream — goes through it, so stubbing it exercises the real
 * client, the real error parsing and the real stream reader rather than a stand-in for them.
 *
 * The event stream is served as a controllable body so a test can push a frame at the moment
 * it chooses, which is what makes "an event causes a refetch" observable as a sequence rather
 * than inferred from a timer.
 */
import { render, type RenderResult } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import { App } from '../src/app/App'
import { createQueryClient } from '../src/app/queryClient'

export interface RequestRecord {
  url: string
  method: string
  headers: Record<string, string>
  body: unknown
}

/** A stream a test can write frames into and close. */
export class FakeStream {
  private controller: ReadableStreamDefaultController<Uint8Array> | null = null
  readonly body: ReadableStream<Uint8Array>
  /** Resolves once the client has actually started reading, so a push cannot race the open. */
  readonly opened: Promise<void>

  constructor() {
    let markOpened: () => void = () => undefined
    this.opened = new Promise<void>((resolve) => {
      markOpened = resolve
    })
    this.body = new ReadableStream<Uint8Array>({
      start: (controller) => {
        this.controller = controller
        markOpened()
      },
    })
  }

  /** Write one SSE frame. `id` is omitted when null, exactly as a keepalive would omit it. */
  push(event: string, data: unknown, id: number | null): void {
    const head = id === null ? '' : `id: ${id}\n`
    this.enqueue(`${head}event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
  }

  enqueue(text: string): void {
    this.controller?.enqueue(new TextEncoder().encode(text))
  }

  close(): void {
    try {
      this.controller?.close()
    } catch {
      // Already closed; a test that ends twice is not a failure.
    }
  }
}

export type Responder = (record: RequestRecord) => Response | Promise<Response>

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** The backend's one error shape, so the client parses a real envelope rather than a guess. */
export function apiError(status: number, code: string, message = 'refused'): Response {
  return json({ error: { code, message } }, status)
}

export function streamResponse(stream: FakeStream): Response {
  return new Response(stream.body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

export interface Backend {
  /** Every request the app made, in order. */
  readonly requests: RequestRecord[]
  /** Requests for one path, which is how a refetch is counted. */
  countOf(path: string): number
  /** Replace the responder for a path mid-test, to simulate state changing behind the API. */
  on(path: string, responder: Responder): void
}

export function mockBackend(routes: Record<string, Responder>): Backend {
  const table = new Map<string, Responder>(Object.entries(routes))
  const requests: RequestRecord[] = []

  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = url.split('?')[0] ?? url
    const headers: Record<string, string> = {}
    new Headers(init?.headers).forEach((value, key) => {
      headers[key.toLowerCase()] = value
    })
    const record: RequestRecord = {
      url: path,
      method: init?.method ?? 'GET',
      headers,
      body: typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : null,
    }
    requests.push(record)

    const responder = table.get(path)
    if (responder === undefined) return apiError(404, 'NOT_FOUND', `no route for ${path}`)
    return responder(record)
  })

  return {
    requests,
    countOf: (path) => requests.filter((entry) => entry.url === path).length,
    on: (path, responder) => table.set(path, responder),
  }
}

/** Mount the whole app, with its own cache, exactly as `main.tsx` does. */
export function renderApp(): RenderResult {
  const client = createQueryClient()
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

/** A stream route that never opens, so a test can assert the disconnected states. */
export const REFUSED_STREAM: Responder = () => {
  throw new TypeError('network error')
}
