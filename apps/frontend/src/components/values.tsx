/**
 * How a value reaches the screen.
 *
 * `Unknown` is the important one: an absent value from the backend means *unknown*, the engine
 * fails closed on it, and every place that could be tempted to print `0` or an empty cell
 * instead routes through here so that the distinction survives to the screen.
 */
import type { ReactNode } from 'react'

/** What an absent value looks like. Never a zero, never a blank cell. */
export function Unknown(): ReactNode {
  return (
    <span className="text-muted italic" title="unknown — the backend returned no value">
      unknown
    </span>
  )
}

/** A value, or the explicit unknown marker when the backend sent `null`. */
export function Value({ children }: { children: string | null | undefined }): ReactNode {
  if (children === null || children === undefined || children === '') return <Unknown />
  return <>{children}</>
}

/**
 * A quantity, rendered as the string the backend sent.
 *
 * Deliberately not parsed. The engine's arithmetic is decimal and is serialised as a
 * fixed-point string precisely so it cannot be perturbed by a binary float on the way to a
 * display; converting it here to right-align it more prettily would reintroduce the problem
 * the representation was chosen to avoid. A negative value is a shortfall and is shown as one.
 */
export function QuantityValue({ value }: { value: string | null }): ReactNode {
  if (value === null) return <Unknown />
  const negative = value.trimStart().startsWith('-')
  return (
    <span className={`font-mono tabular-nums ${negative ? 'font-semibold text-owner' : ''}`}>
      {value}
    </span>
  )
}

/**
 * A number the backend published, with the word it counts.
 *
 * It takes the figure as a number and has no arithmetic in it — no total, no remainder, no
 * percentage. Every count on the screen is the backend's, so that a screen cannot publish a
 * different one from a list it happened to filter.
 */
export function Count({ value, label }: { value: number; label: string }): ReactNode {
  return (
    <span className="inline-flex items-baseline gap-1.5" data-testid="count">
      <span className="text-lg leading-none font-semibold tabular-nums">{value}</span>
      <span className="text-label text-muted uppercase">{label}</span>
    </span>
  )
}
