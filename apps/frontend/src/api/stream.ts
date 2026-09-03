/**
 * The live feed client.
 *
 * **Why this is not `EventSource`.** Every frame the backend writes is a *named* event: a
 * domain event is named after its `type`, and a discontinuity is named `resync`. Nothing is
 * ever sent as an unnamed `message` frame. `EventSource` dispatches a named event only to a
 * listener registered under that exact name, and `onmessage` never fires for one — so a
 * consumer that wants to react to *any* domain event would have to enumerate the event type
 * names, which are open strings chosen by whatever writes the event. That list would be
 * correct today and silently wrong the first time the backend records a new kind of event:
 * the screen would simply stop updating, with no error anywhere. A catch-all reader is the
 * only honest way to consume this stream.
 *
 * **What is unchanged.** This speaks the same wire protocol and resumes with the same
 * `Last-Event-ID` header the backend already documents and that `EventSource` itself would
 * send. It is not a second cursor: the cursor is still a `domain_events.seq` the server chose
 * and echoed on the frame, and this client only quotes the last one it was given.
 *
 * **What this deliberately does not do.** It does not reconstruct state. A frame decides
 * *when* to refetch and never *what* the answer is; the payload is not read into any view.
 * Reading a 401 is the one place it inspects a response beyond framing, because a revoked
 * session and a flaky network are different facts and only one of them should return a person
 * to the login screen.
 */
import { apiUrl } from './client'

export const EVENTS_PATH = '/events'

/** The frame the backend sends when the feed is not continuous and the reader must refetch. */
export const RESYNC_EVENT = 'resync'

const INITIAL_BACKOFF_MS = 1_000
const MAX_BACKOFF_MS = 15_000

/** One parsed frame. `id` is absent on frames that carry none, such as a keepalive comment. */
export interface StreamFrame {
  id?: string
  event: string
  data: string
}

/**
 * Split a buffer into complete frames, returning the unterminated remainder.
 *
 * Comment lines are dropped: the keepalive is a `:` comment carrying no `id`, so it cannot
 * move a cursor and must not be mistaken for an event.
 */
export function parseFrames(buffer: string): { frames: StreamFrame[]; rest: string } {
  const normalised = buffer.replace(/\r\n/g, '\n')
  const chunks = normalised.split('\n\n')
  const rest = chunks.pop() ?? ''
  const frames: StreamFrame[] = []

  for (const chunk of chunks) {
    let event = 'message'
    let id: string | undefined
    const data: string[] = []
    let sawField = false

    for (const line of chunk.split('\n')) {
      if (line === '' || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      const rawValue = colon === -1 ? '' : line.slice(colon + 1)
      const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue
      if (field === 'event') {
        event = value
        sawField = true
      } else if (field === 'data') {
        data.push(value)
        sawField = true
      } else if (field === 'id') {
        id = value
        sawField = true
      }
    }

    if (sawField) frames.push({ ...(id === undefined ? {} : { id }), event, data: data.join('\n') })
  }

  return { frames, rest }
}

/** Why a connection ended. Only `unauthenticated` means the person has to sign in again. */
export type StreamFailure = 'network' | 'unauthenticated'

export interface StreamHandlers {
  /** A connection was accepted and frames are flowing. */
  onOpen: () => void
  /** A frame arrived. Treat it as a signal to refetch, never as state. */
  onFrame: (frame: StreamFrame) => void
  /** The connection ended. `unauthenticated` is terminal; `network` is retried. */
  onFailure: (failure: StreamFailure) => void
}

/**
 * Keep one stream open until `signal` aborts, reconnecting with bounded backoff.
 *
 * Returns a promise that settles when the caller aborts or the session is refused, so a
 * caller can await teardown rather than guess at it.
 */
export async function runEventStream(
  handlers: StreamHandlers,
  signal: AbortSignal,
  options: { path?: string; backoffMs?: number } = {},
): Promise<void> {
  const path = options.path ?? EVENTS_PATH
  let backoff = options.backoffMs ?? INITIAL_BACKOFF_MS
  let lastEventId: string | undefined

  while (!signal.aborted) {
    let opened = false
    try {
      const headers: Record<string, string> = { Accept: 'text/event-stream' }
      // The server's own resume header. A reconnect replays from here; delivery is at least
      // once by the stream's contract, and every frame carries a stable id, so a repeat is
      // recognisable and — for an invalidation signal — harmless anyway.
      if (lastEventId !== undefined) headers['Last-Event-ID'] = lastEventId

      const response = await fetch(apiUrl(path), {
        method: 'GET',
        headers,
        credentials: 'include',
        cache: 'no-store',
        signal,
      })

      if (response.status === 401) {
        handlers.onFailure('unauthenticated')
        return
      }
      if (!response.ok || response.body === null) {
        throw new Error(`event stream refused with status ${response.status}`)
      }

      opened = true
      backoff = options.backoffMs ?? INITIAL_BACKOFF_MS
      handlers.onOpen()

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const { frames, rest } = parseFrames(buffer)
        buffer = rest
        for (const frame of frames) {
          if (frame.id !== undefined) lastEventId = frame.id
          handlers.onFrame(frame)
        }
      }
      // A clean end of body is still a lost feed: fall through to the retry below.
      throw new Error('event stream closed')
    } catch (error) {
      if (signal.aborted) return
      void error
      handlers.onFailure('network')
      // A connection that lived long enough to deliver frames is retried immediately; only
      // repeated failures back off, so a single dropped feed recovers without a visible pause.
      const delay = opened ? 0 : backoff
      await sleep(delay, signal)
      if (!opened) backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
    }
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  if (ms <= 0) return Promise.resolve()
  return new Promise((resolve) => {
    const timer = setTimeout(finish, ms)
    function finish(): void {
      clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    signal.addEventListener('abort', finish, { once: true })
  })
}
