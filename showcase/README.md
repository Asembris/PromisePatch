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
hero (P5).

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

Not yet built: the Playwright suite (P6), the Pages workflow (P8).

Responsive and accessibility fixes beyond the prototype: below 400px a revalidation check's value
drops under its description; below 360px the hero stage is 48px taller and its tags track
tighter so no label runs into another; under `pointer: coarse` the stepper, scenario, trace,
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
  `href`. A link arrow such as "First scored run →" is not a progression. It checks the no-JS page
  and every string the page can show after an interaction.
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
| `tools/verify-assets.mjs`, `verify-content.mjs`, `verify-links.mjs`, `check-budgets.mjs` | The four gates above; `runtime-strings.mjs` collects what `verify-content` checks beyond the no-JS page, hero captions and labels included. |
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
