/**
 * The surfaces a case is drawn on.
 *
 * Four of them, and the difference between them is editorial rather than decorative: a `Card`
 * is something the exception reached, a `QuietCard` is something it did not, a `Panel` is a
 * region of the secondary order book, and a `Message` is the screen saying something about
 * itself rather than about a case.
 *
 * `QuietCard` is the one with a rule attached to it. Quiet means **lower emphasis, never lower
 * legibility**: its text token is the same one the affected cards use, because the untouched
 * set carries the product's central claim and a judge has to be able to read it in the same
 * glance as the set beside it.
 */
import type { ReactNode } from 'react'

/** The small uppercase label above a region or a column. */
export function SectionLabel({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}): ReactNode {
  return (
    <h2 className={`text-label font-semibold text-muted uppercase ${className}`}>{children}</h2>
  )
}

/** A thing the exception reached. */
export function Card({
  children,
  className = '',
  ...rest
}: {
  children: ReactNode
  className?: string
} & React.HTMLAttributes<HTMLDivElement>): ReactNode {
  return (
    <div
      className={`rounded-card border border-edge bg-card shadow-card ${className}`}
      {...rest}
    >
      {children}
    </div>
  )
}

/** A thing it did not. Quieter ground, the same text contrast. */
export function QuietCard({
  children,
  className = '',
  ...rest
}: {
  children: ReactNode
  className?: string
} & React.HTMLAttributes<HTMLDivElement>): ReactNode {
  return (
    <div className={`rounded-quiet border border-edge/70 bg-quiet ${className}`} {...rest}>
      {children}
    </div>
  )
}

/**
 * The line between what the exception reached and what it did not.
 *
 * It is drawn, and drawn as a boundary rather than as a gap, because the selectivity claim is
 * the product's centre: a judge should be able to point at the place where propagation stopped.
 */
export function BoundaryRule({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="flex items-center gap-3" data-testid="boundary-rule">
      <span className="text-label text-muted uppercase">{children}</span>
      <span className="h-px flex-1 border-t border-dashed border-edge-strong" aria-hidden="true" />
    </div>
  )
}

/** A titled region of the secondary order book. */
export function Panel({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: ReactNode
  children: ReactNode
}): ReactNode {
  return (
    <section className="rounded-card border border-edge bg-panel">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-edge px-4 py-3">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {subtitle ? <p className="text-meta text-muted">{subtitle}</p> : null}
      </header>
      {children}
    </section>
  )
}

/**
 * The screen saying something about itself.
 *
 * Every sentence that reaches one of these is written for the person standing in the bakery,
 * not for whoever built the thing. A message that tells a baker to run a command is the product
 * speaking as its own build system, and it is forbidden by name.
 */
export function Message({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'bad'
  children: ReactNode
}): ReactNode {
  const style =
    tone === 'bad'
      ? 'border-owner/40 bg-owner/10 text-owner'
      : 'border-edge bg-surface/50 text-muted'
  return <p className={`m-4 rounded-quiet border px-3 py-2.5 text-sm ${style}`}>{children}</p>
}
