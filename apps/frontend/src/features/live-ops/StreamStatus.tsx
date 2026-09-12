/**
 * The feed indicator.
 *
 * It exists to make the live path visible while it is being proved, so it reports the
 * connection and nothing more. It is not a health summary and it does not claim anything about
 * the data: `live` means a stream is open, not that the screen is correct — the screen is
 * correct because the reads behind it are authoritative.
 *
 * Two rules the indicator itself has to keep.
 *
 * **Every status here is the hook's own, and none of them is a constant.** A screen that said
 * "live" because it was written that way would be the one failure the freshness contract names
 * by name: a stale screen that looks current. `useEventStream` reports what the connection is
 * actually doing, including `reconnecting` and `resyncing`, and this renders that verbatim.
 *
 * **The marker's shape carries the state, not only its colour.** A filled disc is an open feed,
 * a ring is one catching up, a hollow circle is one still trying and a hollow square is no feed
 * at all — so the distinction survives a monochrome frame and a colour-blind reader, and the
 * word is there beside it regardless.
 */
import type { ReactNode } from 'react'
import type { StreamState, StreamStatus as Status } from '../../api/useEventStream'

interface Presentation {
  label: string
  /** The marker's own classes. Shape first, colour second — never colour alone. */
  marker: string
  title: string
}

const LABELS: Record<Status, Presentation> = {
  idle: {
    label: 'idle',
    marker: 'rounded-[2px] border border-muted/50',
    title: 'no feed open',
  },
  connecting: {
    label: 'connecting',
    marker: 'rounded-full border border-ask',
    title: 'opening the event stream',
  },
  live: {
    label: 'live',
    marker: 'rounded-full bg-auto',
    title: 'event stream open',
  },
  resyncing: {
    label: 'resyncing',
    marker: 'rounded-full border-2 border-brand',
    title: 'the feed was not continuous; refetching authoritative state',
  },
  reconnecting: {
    label: 'reconnecting',
    marker: 'rounded-full border border-ask',
    title: 'the feed dropped; retrying',
  },
  offline: {
    label: 'offline',
    marker: 'rounded-[2px] border border-owner',
    title: 'the feed is not open',
  },
}

export function StreamStatusIndicator({ state }: { state: StreamState }): ReactNode {
  const { label, marker, title } = LABELS[state.status]
  return (
    <div
      className="flex items-center gap-2 rounded-control border border-edge bg-panel px-2.5 py-1"
      data-testid="stream-status"
      data-status={state.status}
      title={title}
      role="status"
    >
      <span className={`size-2 ${marker}`} aria-hidden="true" />
      <span className="text-meta font-medium">
        <span className="sr-only">Event stream: </span>
        {label}
      </span>
      {state.lastEventSeq === null ? null : (
        <span className="font-mono text-state text-muted">seq {state.lastEventSeq}</span>
      )}
    </div>
  )
}
