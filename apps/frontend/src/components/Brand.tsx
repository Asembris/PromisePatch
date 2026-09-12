/**
 * The PromisePatch mark, inlined.
 *
 * The geometry is `brand/promisepatch-icon-on-dark.svg` path for path. It is inlined rather
 * than loaded as an image for two reasons the brand sheet already asks for: the mark has to
 * stay crisp at 16px with no container stroke or shadow, and its two Reverse paths have to take
 * the surrounding text colour so the same component works on the header, the sign-in screen and
 * a monochrome print of either.
 *
 * The repair — the small structural insert that bridges the loop's deliberate break — is the
 * one part that keeps its own colour, because it is the thing the mark is *about*. It is drawn
 * in `--color-brand`, which is the interaction token and never a state tone, so the mark can
 * never be mistaken for a status.
 *
 * The artboards are 64×64 and 300×64 and every coordinate in them is even, so rendering at an
 * exact half scale puts every edge on a whole pixel.
 */
import type { ReactNode } from 'react'

/** The two Reverse paths, in the icon's own 64×64 coordinates. */
const LOOP =
  'M8 8h22c11.046 0 18 6.954 18 18s-6.954 18-18 18H20v-8h10c6.252 0 10-3.748 10-10S36.252 16 30 16H20v6H8V8Z'
const STEM = 'M8 30h12v14c0 6.627-5.373 12-12 12V30Z'
/** The repair. */
const PATCH = 'M8 22h12c1.105 0 2 .895 2 2v4c0 1.105-.895 2-2 2H8v-8Z'

export function PromisePatchIcon({ size = 32 }: { size?: number }): ReactNode {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-hidden="true"
      focusable="false"
      data-testid="brand-icon"
    >
      <path fill="currentColor" d={LOOP} />
      <path fill="currentColor" d={STEM} />
      <path fill="var(--color-brand)" d={PATCH} />
    </svg>
  )
}

/**
 * The horizontal lockup: the mark, then the wordmark.
 *
 * The clear space either side is the brand sheet's rule — one quarter of the icon's height —
 * expressed as the 4px inset the artboard already carries at this scale.
 */
export function PromisePatchLockup({ height = 28 }: { height?: number }): ReactNode {
  const scale = height / 64
  return (
    <span className="inline-flex items-center gap-2.5" data-testid="brand-lockup">
      <span style={{ lineHeight: 0 }}>
        <PromisePatchIcon size={Math.round(64 * scale)} />
      </span>
      <span
        className="font-semibold tracking-[-0.03em]"
        style={{ fontSize: `${String(Math.round(32 * scale))}px` }}
      >
        PromisePatch
      </span>
    </span>
  )
}
