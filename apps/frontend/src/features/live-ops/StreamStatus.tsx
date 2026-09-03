/**
 * The feed indicator.
 *
 * It exists to make the live path visible while it is being proved, so it reports the
 * connection and nothing more. It is not a health summary and it does not claim anything about
 * the data: `live` means a stream is open, not that the screen is correct — the screen is
 * correct because the reads behind it are authoritative.
 */
import type { ReactNode } from 'react'
import type { StreamState, StreamStatus as Status } from '../../api/useEventStream'

const LABELS: Record<Status, { label: string; dot: string; title: string }> = {
  idle: { label: 'idle', dot: 'bg-slate-300', title: 'no feed open' },
  connecting: { label: 'connecting', dot: 'bg-amber-400', title: 'opening the event stream' },
  live: { label: 'live', dot: 'bg-emerald-500', title: 'event stream open' },
  resyncing: {
    label: 'resyncing',
    dot: 'bg-sky-500',
    title: 'the feed was not continuous; refetching authoritative state',
  },
  reconnecting: { label: 'reconnecting', dot: 'bg-amber-500', title: 'the feed dropped; retrying' },
  offline: { label: 'offline', dot: 'bg-red-500', title: 'the feed is not open' },
}

export function StreamStatusIndicator({ state }: { state: StreamState }): ReactNode {
  const { label, dot, title } = LABELS[state.status]
  return (
    <div
      className="flex items-center gap-2 rounded border border-edge bg-panel px-2 py-1"
      data-testid="stream-status"
      data-status={state.status}
      title={title}
    >
      <span className={`size-2 rounded-full ${dot}`} aria-hidden="true" />
      <span className="text-xs font-medium">
        <span className="sr-only">Event stream: </span>
        {label}
      </span>
      {state.lastEventSeq === null ? null : (
        <span className="font-mono text-[11px] text-muted">seq {state.lastEventSeq}</span>
      )}
    </div>
  )
}
