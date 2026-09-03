/**
 * Who is signed in, whether the feed is open, and the way out.
 *
 * Sign-out is a real button in the document flow rather than a click handler on something
 * else, so it is reachable and operable from the keyboard without any extra machinery.
 */
import type { ReactNode } from 'react'
import { useLogout } from '../api/queries'
import type { WorkerIdentity } from '../api/types'
import type { StreamState } from '../api/useEventStream'
import { StreamStatusIndicator } from '../features/live-ops/StreamStatus'

export function Header({
  worker,
  stream,
}: {
  worker: WorkerIdentity
  stream: StreamState
}): ReactNode {
  const signOut = useLogout()

  return (
    <header className="sticky top-0 z-10 border-b border-edge bg-panel/95 backdrop-blur">
      <div className="mx-auto flex max-w-[100rem] flex-wrap items-center gap-x-6 gap-y-2 px-6 py-3">
        <div className="mr-auto">
          <h1 className="text-sm font-semibold tracking-tight">PromisePatch</h1>
          <p className="text-xs text-muted">Live Operations</p>
        </div>

        <p className="text-xs">
          <span className="font-medium">{worker.display_name}</span>
          <span className="text-muted"> · {worker.role}</span>
        </p>

        <StreamStatusIndicator state={stream} />

        <button
          type="button"
          onClick={() => signOut.mutate()}
          disabled={signOut.isPending}
          className="rounded border border-edge px-2.5 py-1 text-xs font-medium disabled:opacity-60"
        >
          {signOut.isPending ? 'Signing out…' : 'Sign out'}
        </button>
      </div>
    </header>
  )
}
