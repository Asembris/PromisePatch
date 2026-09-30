# PromisePatch showcase

A single static page that presents PromisePatch to a hackathon judge, built for GitHub Pages at
`https://asembris.github.io/PromisePatch/`. It is a presentation artefact: it adds no product
behaviour, never calls the live app (it links to it), and makes no claim the repository does not
already make.

The design is frozen. It was approved as a Claude Design handoff, kept locally under the ignored
`.handoff/showcase/`, and is implemented here without redesign. The implementation plan, its
phases and its acceptance criteria are in
[`docs/showcase-implementation-plan.md`](../docs/showcase-implementation-plan.md).

## Status

Plan phases P1–P5 are in: the scaffold, tokens, fonts, brand assets, every section's static
content, the data modules and build-time render (P3), the interactive sections (P4), and the
hero (P5). P6 (the Playwright suite, accessibility and budgets) is in, with one target not met:
Lighthouse mobile performance (see the plan's S4 notes). P7's content audit is done, and its five
copy discrepancies against the repository record are corrected by the claim-hardening pass, with
the content rules extended to hold them; see the later truth under the plan's P7 audit. P8 is
complete and the showcase is live at <https://asembris.github.io/PromisePatch/>. P9 is CLOSED, after the
successful Pages deployment of `6370e9b` (run `36475649479`) and the owner's direct verification
of the public site; the plan's §10 resolution and §12 list what is met, what is qualified and the accepted
limitations.

**One model, two renders.** The prototype's tables live in `src/data/`. Pure renderers in
`src/render/` turn a table plus a state into HTML. At build time the plugin replaces each
`<!-- @render:<name> -->` marker in `index.html` with the settled default, and each
`{{fact.<key>}}` token with its `src/data/facts.js` value. At runtime `src/main.js` takes over the
same markup and changes it through the same view functions, so the two cannot drift.

**Without JavaScript** the page reads completely: stage 7 *Settled* with order B, R3 at 10/10
PROCEED, the *Customer consent* trace (diagram from 1080px, stacked chain below), and all ten
proof rows. Controls that do nothing without JavaScript (stepper, *Play case*, order buttons,
scenario toggle, trace buttons, Copy) are rendered `hidden` or as plain text, and each section's
enhancer reveals them only once they are wired. If one enhancer fails, the others still run and
that section keeps its settled content.

**With JavaScript:** the stepper and *Play case* (1150 ms a stage, 400 ms under reduced motion),
selectable orders and their detail, the illustration toggle "If the substitute had run out"
(headed ILLUSTRATION · NOT A RECORDED RUN), checks lighting one per 120 ms when 35% of the gate is
in view, trace buttons lighting their path 140 ms an edge, Copy for the two public SHAs, and a
one-shot reveal of below-the-fold blocks. Under `prefers-reduced-motion: reduce` or
`?motion=reduced`: no reveals, all ten checks at once, no edge stagger, instant cell changes.

**The hero** is the prototype's scene model and both renderers, ported unchanged into
`src/hero/`. The stage first shows the settled `assets/hero-fallback.svg` (with or without
JavaScript). After first paint, once the stage is near the viewport, three.js **0.149.0** is
imported as its own chunk; if WebGL is missing, the import fails, the renderer throws or nothing
starts within 4 s, the SVG renderer draws the same scene (label `SVG FALLBACK`). Steps 01–06,
Replay and Pause appear only once a renderer is drawing; the caption is `aria-live`. Rendering
stops off-screen and in hidden tabs. Under reduced motion the hero opens settled, steps jump to
each phase's end, and nothing animates. QA switches: `?renderer=svg`, `?motion=reduced`, or the
same keys as JSON in `localStorage['pp-qa']`. `window.__ppHero.seek(t)` draws time `t` for
reference captures.

The Pages workflow (P8) is `.github/workflows/showcase-pages.yml`: on a push to `main` that
touches `showcase/**`, `brand/**` or the workflow itself, or on a manual `workflow_dispatch`, it
runs `npm ci`, installs Chromium and runs `npm run check`, then uploads that same `dist/` with
`actions/upload-pages-artifact` and publishes it with `actions/deploy-pages`. **It is deployed:**
<https://asembris.github.io/PromisePatch/>. `30acdd5` was the initial successful Pages deployment,
from run `36448600018`. On attempt 1 its gate passed and its deploy failed with a 404, because Pages was not
yet enabled. Attempt 2 deployed the same gated artifact once the owner set *Settings → Pages →
Source: GitHub Actions*. Every later push that matches the filter redeploys.

Responsive and accessibility fixes beyond the prototype: below 400px a revalidation check's value
drops under its description; below 360px the hero stage is 48px taller and its tags track
tighter so no label runs into another; past matrix cells (opacity .72) and pending revalidation
checks (opacity .75, `--muted` mark) meet WCAG AA contrast, and the scenario buttons grow rather
than clip under the WCAG 1.4.12 text-spacing overrides; under `pointer: coarse` the stepper, scenario, trace,
Copy and hero buttons are at least 44px tall.

## Run it

Node 24 (the version the repository's `pr` workflow pins).

```bash
npm ci
```

```bash
npm run dev
```

```bash
npm run build
```

```bash
npm run preview
```

`npm run dev` and `npm run preview` serve under `/PromisePatch/`, the Pages base. Set
`SHOWCASE_BASE=/` to serve at the root instead.

## Check it

```bash
npm run check
```

The release gate: production build, the four offline gates below, then the Playwright suite. It
exits non-zero on any failure. `npm test` runs the suite alone against an existing `dist/`.

The suite (`tests/`, Chromium only, `@playwright/test` and `@axe-core/playwright`) runs against
`vite preview` of the production build under `/PromisePatch/`, never the dev server:

- `layout.spec.js`: widths 320–1920 (14 of them): no horizontal overflow, nothing crossing the
  viewport, no text under 11px outside the stage and diagram, nothing `hidden` rendered, no
  clipped control, the stage's designed height, and every breakpoint form.
- `fallbacks.spec.js`, `webgl-disabled.spec.js`: no JavaScript, `?renderer=svg`, WebGL off in the
  browser, the three.js chunk held (SVG at 4 s, stage never blank) or failing, and three.js
  requested only after the first rendered frame.
- `hero.spec.js`: `seek()` at 0.95 / 4.3 / 5.8 / 8.2 on desktop and mobile, keyboard, both
  reduced-motion switches, a live preference change, pausing off-screen and in a hidden tab.
- `interaction.spec.js`: stepper, *Play case*, orders A–F, the mobile current-stage form, R3 and
  the labelled illustration, every trace lighting only its path, Copy of the two SHAs.
- `a11y.spec.js`: axe (zero serious or critical, no rule disabled) at 390 and 1440 with and
  without JavaScript, on the illustration and on the pending gate; landmarks and headings; the
  skip link; a full Tab walk; pressed state; the R1–R5 table; colour-alone; text spacing; 44px
  targets under a coarse pointer.
- `content.spec.js`: the content rules of `tools/content-rules.mjs` (shared with `verify:content`)
  over the live DOM after about forty interaction states, with two negative controls (one per
  rule family) and a pure claim-scope test that feeds each corrected overclaim, reworded, through
  the rules and the corrected copy back through them; no token on the page; every request on the Pages origin; CLS and the first contentful frame.

Chromium comes from `npx playwright install chromium`. Locally the suite runs one worker: on the
development machine concurrent browsers stall loopback requests (reproduced against a plain static
server too); `PW_WORKERS=2` overrides, and CI uses two.

The offline gates, also runnable alone after a build:

```bash
npm run verify
```

Run after a build. It runs four offline gates over `dist/`:

- `verify:assets` fails if a brand copy in `dist/` differs from its original in `brand/`, if
a shipped asset is missing, or if anything the page loads comes from another origin (Google
Fonts, unpkg or any CDN, the Claude Design runtime, or any `http(s)` URL in `src`, `srcset` or a
CSS `url()`).
- `verify:content` fails if a frozen fact from `src/data/facts.js` is missing or lacks its
  caveat nearby, if a cited source path does not exist, if anything joins 11/16 and 16/16 as a
  progression (an arrow between the two scores, "improved", "now 16/16", "from … to",
  before/after, "benchmark scored 16/16"), if a score appears without its own label, if Telegram
  is implied as a consent channel, if a refusal is claimed live, if the illustration loses its
  label, on any forbidden phrase outside an explicit negation, or if a deferred item gains an
  `href`. A link arrow such as "First scored run →" is not a progression. It also fails on a
  claim wider than the implementation: option-code consent, a plan approval tied to a signed-in
  session alone, unqualified "exactly once", an MCP or AI caller with "no authority", atomic or
  execution-time revalidation, a customer pressing APPROVE in R3, a universal `STALE` re-plan, a
  refusal presented as recorded, a midnight-crossing time without dates, or an R3 timeline
  interval that does not reach back to another row. It checks the no-JS page, every string the
  page can show after an interaction, and (claim scope only) the root `README.md`.
- `verify:links` fails on an empty, `#` or TBD href, an anchor with no target, an external URL
  not listed in `src/data/links.js`, a `blob/main/` target missing from the working tree, or a
  deferred item rendered as a link. It never fetches anything.
- `check:budgets` fails if the lazy three.js chunk exceeds 150 KB gzipped, if all JavaScript
  together exceeds 200 KB gzipped, or if the entry imports the three.js chunk statically. At P5:
  106.59 KB and 120.66 KB.

Both take an optional page path, so a mutated copy can be checked: `node tools/verify-content.mjs
some.html`.

## Layout

| Path | What it is |
|---|---|
| `index.html` | The whole page: meta, landmarks, static prose, `@render` markers and `{{fact.*}}` tokens. |
| `CONTENT_SOURCES.md` | Every displayed claim and number, and the repository record it comes from. |
| `src/data/` | The prototype's tables verbatim (`stages`, `rows`, `detail`, `cells`, `checks`, `traces`, `arch`, `proofs`, `rehearsals`), plus `facts.js` and `links.js`. |
| `src/render/` | Pure `(state) → HTML` renderers and view functions, used at build time and at runtime. |
| `src/main.js`, `src/sections/`, `src/lib/motion.js` | Progressive enhancement, one module per interactive section, and the reduced-motion flag and QA switches. |
| `src/hero/` | The hero: constants and layouts, `scene(t, L)`, the three.js renderer (the lazy chunk), the SVG renderer, and the controller. |
| `src/styles/tokens.css` | Every `TOKENS.md` value, verbatim. |
| `src/styles/base.css` | Reset, self-hosted fonts, links, focus ring, skip link. |
| `src/styles/layout.css` | Container, sections, pairs, header, buttons, cards, footer. |
| `src/styles/sections.css` | Per-section rules and the breakpoints 400 / 640 / 1000 / 1080. |
| `public/assets/hero-fallback.svg` | The settled hero, byte-for-byte from the handoff. |
| `public/assets/og-preview-1200x630.png` | The social preview, byte-for-byte from the handoff. |
| `public/apple-touch-icon.png` | 180 × 180 on `#111A2B`, rendered once by `tools/render-touch-icon.mjs`. |
| `tools/vite-plugin-showcase.js` | Injects the renders and facts; copies the brand SVGs and the notices into the build; preloads the display font. |
| `tools/verify-assets.mjs`, `verify-content.mjs`, `verify-links.mjs`, `check-budgets.mjs` | The four offline gates above; `runtime-strings.mjs` collects what `verify-content` checks beyond the no-JS page, hero captions and labels included. |
| `tools/content-rules.mjs` | The content rules themselves, pure; run by `verify-content` over the built page and by `tests/content.spec.js` over the live DOM. |
| `playwright.config.js`, `tests/` | The Playwright suite above, against `vite preview` of the production build. |
| `THIRD_PARTY_NOTICES.md` | Font attribution, the SIL OFL 1.1 text and the three.js MIT licence; shipped in `dist/` too. |

## Assets

- **Brand.** The logo, icon and monochrome icon are read from the repository's `brand/` at build
  time and copied into `dist/brand/` byte-for-byte; `favicon.svg` is a copy of the on-dark icon.
  They are never committed a second time here.
- **Fonts.** Instrument Sans (400/500/600/700) and IBM Plex Mono (400/500/600), Latin only, from
  the exact-pinned `@fontsource` packages. Vite emits the files into `dist/assets/`;
  `font-display: swap`; Instrument Sans 600 is preloaded. No font is requested from any CDN.
- **Touch icon.** Rendered once from `brand/promisepatch-icon-on-dark.svg` with a local headless
  Chrome or Edge (`CHROMIUM=… npm run render:touch-icon`) and committed. The plan named
  Playwright for this; it is not a dependency yet, so a local browser binary was used instead.
- **Never copied here:** the prototype (`*.dc.html`), `support.js`, the handoff documents, the
  reference screenshots and `hero-fallback.png`. They stay in the ignored `.handoff/`.

## What this folder may and may not touch

It may read `brand/*.svg`, and it writes only to `showcase/dist/`. It imports nothing from
`apps/`, `packages/` or any Python module, and nothing outside it imports from it. Product code,
evidence documents, benchmarks and the existing CI workflows are out of bounds; the freeze checks
in the plan's §7 must print nothing after every commit.
