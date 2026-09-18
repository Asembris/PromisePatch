/**
 * The shell: choose which product this address is for, then show one screen or the other.
 *
 * Two products are served from one bundle, and the split is the first thing that happens. An
 * approval link goes to the customer's page, which has no session and must not ask for one;
 * everything else goes to the worker's app, which bootstraps one before it draws anything.
 *
 * There are exactly three states, and the middle one is the reason this is a component rather
 * than a ternary. Until `/api/auth/me` has answered, the app does not know whether anyone is
 * signed in, and rendering the login form during that gap would flash a sign-in screen at a
 * worker who is already signed in on every reload.
 *
 * The feed is opened only when there is a session, and closed when there is not. That is not a
 * cosmetic detail: the stream is a session endpoint, so keeping one open across a sign-out
 * would be retrying an authenticated read on a session the server has revoked.
 *
 * Which case is open is read from the address bar rather than held here. That is the reload
 * guarantee stated as code: there is no in-memory selection to lose, so a refresh mounts the
 * app already pointing at the same case and renders whatever the durable case then says.
 */
import type { ReactNode } from 'react'
import { useMe } from '../api/queries'
import { useEventStream } from '../api/useEventStream'
import { LoginScreen } from '../features/auth/LoginScreen'
import { CaseWorkspace } from '../features/case/CaseWorkspace'
import { CustomerApproval } from '../features/customer/CustomerApproval'
import { LiveOperations } from '../features/live-ops/LiveOperations'
import { PromisePatchLockup } from '../components/Brand'
import { Header } from './Header'
import { currentApprovalToken, useCaseRoute } from './useCaseRoute'

/**
 * Which of the two products this address is for, decided before either one mounts.
 *
 * A dispatcher rather than a branch inside the shell, because the two screens have genuinely
 * different needs and hooks cannot be conditional: the worker's app opens a session and a feed,
 * and the customer's page must do neither. A customer has no account to bootstrap, and an
 * approval link that flashed a sign-in form on its way to the question would be telling
 * somebody they needed a login they will never have.
 *
 * The token is read once, at mount, and not watched. There is no in-app navigation to or from
 * a customer link — it is arrived at from a message and left by closing the tab — so listening
 * for `popstate` here would be wiring up a transition that does not exist.
 */
export function App(): ReactNode {
  const approvalToken = currentApprovalToken()
  if (approvalToken !== null) return <CustomerApproval token={approvalToken} />
  return <WorkerApp />
}

/** The worker's product: a session, a live feed, and one case or the order book. */
function WorkerApp(): ReactNode {
  const me = useMe()
  const worker = me.data?.worker ?? null
  const stream = useEventStream(worker !== null)
  const route = useCaseRoute()

  if (me.isPending) {
    return (
      <Boot role="status">
        <PromisePatchLockup height={30} />
        <p className="text-sm text-muted">Opening your session…</p>
      </Boot>
    )
  }

  if (me.isError) {
    return (
      <Boot role="alert">
        <PromisePatchLockup height={30} />
        <p className="text-sm text-muted">
          PromisePatch cannot be reached from this device right now. Nothing about your cases
          has changed; this screen simply cannot read them. Try again in a moment.
        </p>
      </Boot>
    )
  }

  // The shell owns the address bar, so the sign-in screen asks it to open a case rather
  // than moving the URL under a component that does not own it.
  if (worker === null) return <LoginScreen onEntered={route.open} />

  return (
    <div className="min-h-full">
      {/* First in the tab order, visible the moment it is focused, and pointing at the one
          landmark on the page. A judge or a worker arriving by keyboard should not have to walk
          the header to reach the case.

          Every visible style is on `focus:` rather than on the base. `sr-only` sets its own
          padding to zero, and a padded base put a 21-pixel clipped box in the document that
          measured as a control nobody could see — so the unfocused link is now genuinely a
          1px box, and the focused one is a full-size target. */}
      <a
        href="#case-surface"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-30 focus:inline-flex focus:min-h-11 focus:items-center focus:rounded-control focus:bg-brand focus:px-4 focus:text-sm focus:font-semibold focus:text-brand-ink"
      >
        Skip to the case
      </a>
      <Header worker={worker} stream={stream} />
      {route.caseId === null ? (
        <LiveOperations stream={stream} onOpenCase={route.open} />
      ) : (
        <CaseWorkspace
          caseId={route.caseId}
          onClose={() => {
            route.open(null)
          }}
        />
      )}
    </div>
  )
}

/**
 * The two screens that exist before there is a session to show.
 *
 * Both carry the mark, because the alternative is a bare sentence on a dark page that reads as
 * a crash. Neither instructs anybody to run a command: a shell that told a baker to start a
 * backend would be the product speaking as its own build system.
 */
function Boot({ role, children }: { role: 'status' | 'alert'; children: ReactNode }): ReactNode {
  return (
    <main className="mx-auto flex min-h-full max-w-sm flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="flex flex-col items-center gap-4 text-ink" role={role}>
        {children}
      </div>
    </main>
  )
}
