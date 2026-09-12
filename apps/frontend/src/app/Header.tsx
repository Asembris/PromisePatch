/**
 * The application shell's one bar: the mark, who is signed in, whether the feed is open, and
 * the way out.
 *
 * Three things it deliberately does not carry.
 *
 * - **No navigation.** There is one product surface and it is the case. A nav bar would turn a
 *   causal story into a reporting tool, and the contract forbids it by name.
 * - **No counts, tiles or totals.** Anything that looks like a figure up here would be a figure
 *   with no case behind it.
 * - **No operator controls.** There is no reseed, no restart and no demo switch: every one of
 *   those is prototype scaffolding, and a control that mutates the fixture has no place on a
 *   surface whose whole claim is that it renders and does not decide.
 *
 * Sign-out is a real button in the document flow rather than a click handler on something
 * else, so it is reachable and operable from the keyboard without any extra machinery.
 */
import type { ReactNode } from 'react'
import { useLogout } from '../api/queries'
import type { WorkerIdentity } from '../api/types'
import type { StreamState } from '../api/useEventStream'
import { PromisePatchLockup } from '../components/Brand'
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
    <header className="sticky top-0 z-20 border-b border-edge bg-surface/85 backdrop-blur-md">
      <div className="mx-auto flex min-h-14 max-w-[100rem] flex-wrap items-center gap-x-5 gap-y-2 px-5 py-2.5 sm:px-6">
        <h1 className="mr-auto text-ink">
          <PromisePatchLockup height={26} />
          <span className="sr-only">— the case workspace</span>
        </h1>

        <StreamStatusIndicator state={stream} />

        <WorkerChip worker={worker} />

        <button
          type="button"
          onClick={() => signOut.mutate()}
          disabled={signOut.isPending}
          className="rounded-control border border-edge px-2.5 py-1 text-meta font-medium text-muted transition-colors hover:border-edge-strong hover:text-ink disabled:opacity-60"
        >
          {signOut.isPending ? 'Signing out…' : 'Sign out'}
        </button>
      </div>
    </header>
  )
}

/**
 * Who the server says this session belongs to.
 *
 * The name and the role are the `/api/auth/me` answer, not a local guess, because the worker
 * identity every attestation is recorded against is the server's — and a bar that displayed a
 * different name from the one a report would be filed under would be worse than displaying
 * none.
 */
function WorkerChip({ worker }: { worker: WorkerIdentity }): ReactNode {
  const initial = worker.display_name.trim().slice(0, 1).toUpperCase()
  return (
    <p className="flex items-center gap-2" data-testid="worker-identity">
      <span
        aria-hidden="true"
        className="grid size-6 place-items-center rounded-full bg-brand/20 text-state font-semibold text-brand"
      >
        {initial}
      </span>
      <span className="text-meta">
        <span className="font-medium text-ink">{worker.display_name}</span>
        <span className="text-muted"> · {worker.role}</span>
      </span>
    </p>
  )
}
