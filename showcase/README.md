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

Plan phases P1 and P2 are in: the scaffold, tokens, fonts, brand assets, header and every
section's static content. The page ships **no JavaScript yet**, so it reads the same with
JavaScript on or off, and it contains no control that would do nothing.

Where a section is interactive in the approved design, it shows its settled default as static
markup, written by hand from the prototype's data tables: the six-promise matrix at stage 7
*Settled* with order B selected, the revalidation gate at R3 10/10 PROCEED, the *Customer consent*
trace (diagram from 1080px, stacked chain below), and the ten proof rows. Phase P3 replaces those
hand-written blocks with build-time renders from `src/data/`. The hero stage shows the approved
settled fallback, `assets/hero-fallback.svg`, until the three.js and SVG renderers land in P5.

Not yet built: the stage stepper and *Play case*, order selection, the illustration scenario
toggle, trace buttons, Copy buttons, section reveals, the hero and its step controls, the Pages
workflow and the Playwright suite.

One responsive fix beyond the prototype: below 400px a revalidation check's value drops under its
description (still right-aligned), because the three-column row collides at 320px.

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
npm run verify:assets
```

Run after a build. It fails if a brand copy in `dist/` differs from its original in `brand/`, if
a shipped asset is missing, or if anything the page loads comes from another origin (Google
Fonts, unpkg or any CDN, the Claude Design runtime, or any `http(s)` URL in `src`, `srcset` or a
CSS `url()`).

## Layout

| Path | What it is |
|---|---|
| `index.html` | The whole page: meta, landmarks and every section's static content. |
| `src/styles/tokens.css` | Every `TOKENS.md` value, verbatim. |
| `src/styles/base.css` | Reset, self-hosted fonts, links, focus ring, skip link. |
| `src/styles/layout.css` | Container, sections, pairs, header, buttons, cards, footer. |
| `src/styles/sections.css` | Per-section rules and the breakpoints 400 / 640 / 1000 / 1080. |
| `public/assets/hero-fallback.svg` | The settled hero, byte-for-byte from the handoff. |
| `public/assets/og-preview-1200x630.png` | The social preview, byte-for-byte from the handoff. |
| `public/apple-touch-icon.png` | 180 × 180 on `#111A2B`, rendered once by `tools/render-touch-icon.mjs`. |
| `tools/vite-plugin-showcase.js` | Copies the brand SVGs and the notices into the build; preloads the display font. |
| `tools/verify-assets.mjs` | The asset and external-origin gate above. |
| `THIRD_PARTY_NOTICES.md` | Font attribution and the SIL OFL 1.1 text; shipped in `dist/` too. |

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
