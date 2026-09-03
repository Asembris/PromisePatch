/**
 * One stream, one status, and the single effect a frame is allowed to have.
 *
 * The whole contract of this hook is one line of behaviour: **a frame causes a refetch of the
 * authoritative reads, and nothing else.** No frame payload is stored, no view is
 * reconstructed, and no decision is made from an event type. That is what keeps the backend
 * the only thing that knows what is true; the stream just says when to ask again.
 *
 * Coalescing is left to TanStack Query rather than reimplemented here. Invalidating the same
 * key twice while a refetch is in flight is one refetch, so a burst of frames costs one read
 * and no local bookkeeping — which is the point of treating the stream as a signal instead of
 * as a source of state.
 *
 * The status exists so the live path is visible while it is being proved. `resyncing` is a
 * real state rather than a decoration: the backend sends a `resync` frame when the feed is not
 * continuous — on a fresh connection with no resume point, and when a reconnecting subscriber
 * has been away longer than the replay bound — and the honest response is to say so, refetch,
 * and only then claim to be live again.
 */
import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { forgetSession, refreshOperationalState } from './queries'
import { RESYNC_EVENT, runEventStream, type StreamFrame } from './stream'

export type StreamStatus = 'idle' | 'connecting' | 'live' | 'resyncing' | 'reconnecting' | 'offline'

export interface StreamState {
  status: StreamStatus
  /** The sequence of the last frame that carried one, for the operator to quote. */
  lastEventSeq: number | null
  /** How many domain events this feed has delivered. Resync frames are not events. */
  eventsReceived: number
}

const INITIAL: StreamState = { status: 'idle', lastEventSeq: null, eventsReceived: 0 }

/**
 * Keep a feed open while `enabled`, refetching the read APIs whenever it says something moved.
 *
 * A 401 on the stream is treated exactly like a 401 on a read: the session is forgotten and
 * the app returns to the login screen, rather than the feed retrying against a session the
 * server has already revoked.
 */
export function useEventStream(enabled: boolean): StreamState {
  const client = useQueryClient()
  const [state, setState] = useState<StreamState>(INITIAL)

  useEffect(() => {
    if (!enabled) {
      setState(INITIAL)
      return
    }

    const controller = new AbortController()
    setState({ status: 'connecting', lastEventSeq: null, eventsReceived: 0 })

    const onFrame = (frame: StreamFrame): void => {
      const parsed = frame.id === undefined ? Number.NaN : Number.parseInt(frame.id, 10)
      const isResync = frame.event === RESYNC_EVENT
      setState((current) => ({
        status: isResync ? 'resyncing' : 'live',
        lastEventSeq: Number.isFinite(parsed) ? parsed : current.lastEventSeq,
        eventsReceived: current.eventsReceived + (isResync ? 0 : 1),
      }))

      void refreshOperationalState(client)
        .catch(() => undefined)
        .then(() => {
          if (controller.signal.aborted || !isResync) return
          // Only a resync claimed to be catching up, and only a completed refetch earns the
          // return to `live`: saying so before the read landed would be asserting the very
          // continuity the resync frame denied.
          setState((current) => (current.status === 'resyncing' ? { ...current, status: 'live' } : current))
        })
    }

    void runEventStream(
      {
        onOpen: () => {
          setState((current) => ({ ...current, status: 'live' }))
        },
        onFrame,
        onFailure: (failure) => {
          if (failure === 'unauthenticated') {
            setState((current) => ({ ...current, status: 'offline' }))
            forgetSession(client)
            return
          }
          setState((current) => ({ ...current, status: 'reconnecting' }))
        },
      },
      controller.signal,
    )

    return () => {
      controller.abort()
    }
  }, [enabled, client])

  return state
}
