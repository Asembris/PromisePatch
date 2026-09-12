/**
 * The pieces a dependency view is drawn from: a node, an edge, a column heading, a count.
 *
 * Two properties of this file are load-bearing rather than stylistic.
 *
 * **A node cannot render an identifier, because it is never given one.** `CausalNode` takes a
 * label and a detail and has no parameter for anything else. The backend carries `node_ref` on
 * every step so the evidence drawer can quote a traversal, and bands 1-4 may carry no identifier
 * at all — so the safeguard here is structural: there is no prop to pass it to, and a call site
 * that tried would not compile.
 *
 * **Emphasis is a row's own.** A node and an edge brighten when the row they belong to is
 * hovered or focused, which is a reading aid and nothing more: it changes no value, reveals no
 * content that was hidden, and is reachable from the keyboard because the row it hangs off is.
 *
 * **Every edge is local.** A connector is a line and a head inside the gap it spans, laid out by
 * the same flex box that lays out the nodes either side of it. Nothing measures a rectangle,
 * nothing shares a coordinate space with another row, and nothing holds a constant that assumes
 * how many promises an authority lane has. One overlay across the whole map would have to know
 * all three, and would go stale the moment a lane held two orders instead of one.
 */
import type { ReactNode } from 'react'
import { TONE_TEXT, type Tone } from './vocabulary'
import { Count } from './values'

/** One named node of a traversal. Label and detail are the backend's strings, verbatim. */
export function CausalNode({
  label,
  detail,
  emphasis = false,
}: {
  label: string
  detail: string | null
  /** The source node of a chain, which is the thing that actually went wrong. */
  emphasis?: boolean
}): ReactNode {
  return (
    <div
      data-testid="causal-node"
      className={`rounded-quiet border px-2.5 py-1 transition-colors group-hover:border-edge-strong group-focus-visible:border-edge-strong ${
        emphasis ? 'border-edge-strong bg-card' : 'border-edge bg-panel/60'
      }`}
    >
      <p className="text-phrase leading-tight font-medium text-ink">{label}</p>
      {detail === null ? null : (
        <p className="mt-0.5 text-state leading-tight text-muted">{detail}</p>
      )}
    </div>
  )
}

/**
 * The join between two nodes.
 *
 * Decorative to a screen reader and load-bearing to everybody else, so it is `aria-hidden` and
 * the reading order carries the same traversal as prose. The head is a fixed-size triangle
 * rather than a scaled one: a marker stretched by a container query is a marker that points
 * somewhere slightly different on every viewport.
 */
export function CausalEdge({
  tone = 'neutral',
  orientation = 'horizontal',
}: {
  tone?: Tone
  orientation?: 'horizontal' | 'vertical'
}): ReactNode {
  const colour = tone === 'neutral' ? 'text-edge-strong' : TONE_TEXT[tone]

  if (orientation === 'vertical') {
    return (
      <span
        aria-hidden="true"
        data-testid="causal-edge"
        data-orientation="vertical"
        className={`flex justify-center py-0.5 opacity-70 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 ${colour}`}
      >
        <span className="h-2 w-[1.5px] rounded-full bg-current" />
      </span>
    )
  }

  // Below the map's width the same element turns: the line stands up and the head turns with
  // it, so a stacked chain still points from one node to the next rather than off the row.
  return (
    <span
      aria-hidden="true"
      data-testid="causal-edge"
      data-orientation="horizontal"
      className={`flex min-w-3 flex-col items-center justify-center opacity-70 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 xl:flex-1 xl:flex-row ${colour}`}
    >
      <span className="h-3 w-[1.5px] rounded-full bg-current xl:h-[1.5px] xl:w-auto xl:flex-1" />
      <svg viewBox="0 0 6 8" className="h-2 w-1.5 shrink-0 rotate-90 xl:rotate-0" fill="currentColor">
        <path d="M0 0 L6 4 L0 8 Z" />
      </svg>
    </span>
  )
}

/** A fixed column's name. The same four words on every row, of every case. */
export function CausalColumnHeading({ children }: { children: ReactNode }): ReactNode {
  return (
    <p className="text-label font-semibold text-muted uppercase" data-testid="causal-column-label">
      {children}
    </p>
  )
}

/**
 * How many traversals a track stored.
 *
 * Shown only where there is more than one, because "1 path" beside a chain that is plainly one
 * path is noise — and never computed from the chain being displayed, which is the single path
 * the domain says decided this promise.
 */
export function CausalPathCount({ value }: { value: number }): ReactNode {
  return (
    <span data-testid="causal-path-count" data-paths={value}>
      <Count value={value} label="paths stored" />
    </span>
  )
}

/**
 * Why nothing reached a promise, in the backend's own sentence.
 *
 * An empty causal column with no sentence reads as a screen that failed to load. Here the
 * emptiness is the claim, so it is said out loud rather than left as white space.
 */
export function CausalAbsence({ reason }: { reason: string | null }): ReactNode {
  if (reason === null) return null
  return (
    <p className="text-reason text-muted" data-testid="causal-absence">
      {reason}
    </p>
  )
}
