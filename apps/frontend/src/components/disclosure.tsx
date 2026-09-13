/**
 * A section that is closed until somebody asks for it, and gives focus back when it shuts.
 *
 * Three properties, and each one exists because of a way a disclosure can mislead.
 *
 * **It hides; it never fetches.** The children are rendered from data the caller already holds,
 * and closing one is not a signal to anything. A disclosure that loaded on open would make the
 * deepest evidence the slowest to reach, which is precisely backwards: the reader who opens it
 * is the reader who doubts the claim above it.
 *
 * **Closing returns focus to the control that closed it.** A nested panel can hold the focused
 * element, and collapsing its parent unmounts it — which leaves focus on `document.body` and a
 * keyboard reader at the top of the page with no way back. So the summary button takes focus
 * back explicitly rather than relying on where the pointer happened to be.
 *
 * **The state is the button's own.** No context, no store, no url. Two disclosures on a screen
 * know nothing about each other, so opening one never closes another out from under a reader.
 */
import { useId, useRef, useState, type ReactNode } from 'react'

export function Disclosure({
  summary,
  children,
  testId,
  tone = 'quiet',
  defaultOpen = false,
}: {
  /** What the control says when it is closed. Never a claim about the content behind it. */
  summary: ReactNode
  children: ReactNode
  testId: string
  /** `loud` is the one a reader is meant to find; `quiet` is a level inside another. */
  tone?: 'loud' | 'quiet'
  defaultOpen?: boolean
}): ReactNode {
  const [open, setOpen] = useState(defaultOpen)
  const button = useRef<HTMLButtonElement>(null)
  const panelId = useId()

  return (
    <div data-testid={`${testId}-section`} data-open={open}>
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => {
          // Read before the update: `open` is still the value the click is leaving.
          if (open) button.current?.focus()
          setOpen((current) => !current)
        }}
        // `min-h-11` is 44px, which is the smallest target a finger can be asked to hit. The
        // negative inline margin keeps the text where it was: the target grows, the layout does
        // not move, and a control that was reachable only with a mouse becomes reachable on a
        // phone without the page being redrawn around it.
        className={`-mx-2 inline-flex min-h-11 items-center gap-1.5 rounded-quiet px-2 transition-colors ${
          tone === 'loud'
            ? 'text-meta font-medium text-muted hover:text-ink'
            : 'text-label text-muted uppercase hover:text-ink'
        }`}
        data-testid={testId}
      >
        <Chevron open={open} />
        {summary}
      </button>
      <div id={panelId} hidden={!open} data-motion={open ? 'settle' : undefined}>
        {open ? children : null}
      </div>
    </div>
  )
}

/** The one piece of state carried by shape rather than by words. The words are there too. */
function Chevron({ open }: { open: boolean }): ReactNode {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 8 8"
      className={`h-2 w-2 shrink-0 fill-current transition-transform ${open ? 'rotate-90' : ''}`}
    >
      <path d="M1 0 L7 4 L1 8 Z" />
    </svg>
  )
}
