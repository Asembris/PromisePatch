/**
 * The sign-in screen.
 *
 * The credentials go to the backend and nowhere else: nothing is written to `localStorage` or
 * `sessionStorage`, no password is prefilled, and the session that results is an `HttpOnly`
 * cookie this code cannot read. The two demo usernames are named because they are seeded
 * fixture logins, not because a password is known here.
 *
 * Errors are the backend's message. A wrong password and an unknown user are one answer by
 * design, and the screen does not try to be more helpful than the endpoint was.
 */
import { useState, type FormEvent, type ReactNode } from 'react'
import { useLogin } from '../../api/queries'
import { ApiError } from '../../api/client'
import { PromisePatchLockup } from '../../components/Brand'

const FIELD =
  'w-full rounded-control border border-edge bg-panel px-3 py-2.5 text-sm text-ink placeholder:text-muted/60'

function messageFor(error: Error): string {
  if (error instanceof ApiError) return error.message
  return 'the sign-in request could not be completed'
}

export function LoginScreen(): ReactNode {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const signIn = useLogin()

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    signIn.mutate({ username: username.trim(), password })
  }

  return (
    <main className="mx-auto flex min-h-full max-w-sm flex-col justify-center px-6 py-16">
      <h1 className="text-ink">
        <PromisePatchLockup height={34} />
      </h1>
      <p className="mt-3 text-sm text-muted">
        Sign in to open the case you are working on. Your name is the one every report is
        recorded against.
      </p>

      <form className="mt-8 space-y-4" onSubmit={onSubmit}>
        <div className="space-y-1.5">
          <label className="block text-sm font-medium" htmlFor="username">
            Worker
          </label>
          <input
            id="username"
            name="username"
            type="text"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className={FIELD}
          />
          <p className="text-meta text-muted">Seeded demo logins: maya (baker), jo (owner).</p>
        </div>

        <div className="space-y-1.5">
          <label className="block text-sm font-medium" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={FIELD}
          />
        </div>

        {signIn.isError ? (
          <p
            role="alert"
            className="rounded-control border border-owner/40 bg-owner/10 px-3 py-2 text-sm text-owner"
          >
            {messageFor(signIn.error)}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={signIn.isPending}
          className="w-full rounded-control bg-brand px-3 py-2.5 text-sm font-semibold text-brand-ink transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {signIn.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
