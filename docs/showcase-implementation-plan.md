# Showcase implementation plan

Date: **2026-09-27**. Status: **P1–P5 implemented; P6 implemented with one target not met
(Lighthouse mobile performance, see the S4 notes); P7's audit done; its five copy
discrepancies are corrected by the claim-hardening pass, awaiting review (see the later truth
under the P7 audit); P8–P9 open.** `showcase/` holds the
scaffold, tokens, self-hosted fonts, brand copy, every section's static content, the data modules
with their build-time render (P3), the interactive six promises, revalidation gate,
architecture traces, Copy buttons and section reveals (P4), the hero: three.js `0.149.0`
with the SVG renderer and the no-JS image behind it (P5), and the Playwright suite behind
`npm run check` (P6). Nothing is deployed and no workflow exists.

**Recorded during P1/P2** (implementation notes; the design is unchanged):

- Versions: `vite` 8.3.1, `@fontsource/instrument-sans` 5.3.0, `@fontsource/ibm-plex-mono` 5.3.0,
  all exact. No JavaScript ships yet, so `src/main.js` does not exist yet; it arrives with P4.
- `apple-touch-icon.png` was rendered with a local headless Chrome/Edge
  (`tools/render-touch-icon.mjs`), not Playwright, because Playwright is not a dependency until P6.
- The prototype sizes every box as `content-box`, and its 1240px container and flex bases assume
  that; the port keeps `content-box` rather than a global `border-box` reset.
- Below 400px a revalidation check's value drops under its description: the prototype's
  three-column row collides at 320px.
- ~~Two conflicts for P7 to resolve~~ **resolved in P3/P4 as a validator-spec correction, not a
  copy change** (see §6.3). The approved copy is unchanged: "First scored run →" and
  "v2 release condition →" stay, and proof rows 06 and 07 keep 11/16 and 16/16.

**Recorded during P3/P4** (implementation notes; the design is unchanged):

- **Data and render.** `STAGES ROWS DET CELL CHECKS TRACES ARCH PROOFS` are in `src/data/`
  verbatim, with the R1–R5 table (`rehearsals.js`), `facts.js` (each fact with its `source` and
  caveats) and `links.js`. The diagram's nodes, edges and labels moved into `arch.js` so the SVG
  is rendered too. Renderers expose view functions (`cellView`, `checkView`, `outcomeView`,
  `edgeView`); the build uses them to emit strings and the runtime uses them to update the
  existing elements in place, so focus survives a click and cell colours can transition. The
  plugin also replaces `{{fact.<key>}}` tokens. Build output was diffed against the S1 page:
  the no-JS visible text is identical.
- **No-JS stand-ins.** Where the prototype names the current state only on a control (the pressed
  stage, the pressed scenario, the pressed trace), the no-JS page shows a small label instead
  ("7 Settled" chip, "Deployed rehearsal R3" heading, "Customer consent" heading), as S1 did.
  Once a section is enhanced the chip is hidden and the two headings become visually hidden, so
  assistive technology keeps a heading. Order ids are plain text without JS and buttons with it.
- **Accessibility additions**, none visible: a polite status region announces each stage change
  and the gate's result once all ten checks finish (not every tick); order buttons carry
  "Order X, show details"; Copy buttons carry "Copy the deployed product SHA" / "Copy the
  repository release SHA" and announce the copy; under `pointer: coarse` the stepper, scenario,
  trace and Copy buttons are at least 44px tall. *Play case* changes its label and does not use
  `aria-pressed`, so a changing name and a pressed state are not combined.
- **Below 640px** the matrix shows only the current stage's cell (`.is-current`), whichever stage
  it is, by CSS; nothing is measured in script.
- **Reveals** are armed only by script, only for `[data-reveal]` blocks below the fold at load, and
  never under reduced motion; print shows everything. Reveal markers follow the prototype's.
- **`?motion=reduced`** adds a `motion-reduced` class that applies the same CSS clamp as the media
  query, so the QA switch removes transitions as well as script timing.
- Verified with a scratch CDP script against headless Edge (uncommitted, no new dependency): no
  JS, widths 320/390/768/1280/1578, every control by click and by Enter/Space, reduced motion and
  the QA switch, and screenshots compared with `reference/desktop/04, 06, 07, 08, 09, 09b` and
  `reference/mobile/03, 05, 07`. The stepper's buttons sit a few pixels wider than in
  `reference/desktop/04`; nothing else differs structurally.

**Recorded during P5** (implementation notes; the design is unchanged):

- **three.js `0.149.0`, exact**, the release the prototype ran, pinned directly rather than
  pinning the current release and switching colour management off (§1.4 allowed either). r149
  has no colour management by default, so no colour setting is needed. It is the only runtime
  dependency, bundled from npm into its own chunk; nothing loads from a CDN. MIT notice in
  `showcase/THIRD_PARTY_NOTICES.md`.
- **Modules** as §3: `src/hero/constants.js` (`K PH END LD LM`, step labels, captions, the label
  overlay), `scene.js` (`scene(t, L)` and `phaseOf`, verbatim), `three-renderer.js`
  (`makeThree()` with named imports), `svg-renderer.js` (`makeSvg()`, unchanged), and
  `controller.js` (layout, frame, place, step/Replay/Pause, lazy boot, fallback, pausing). Only
  mechanical changes: `this.` and React state removed, `preserveDrawingBuffer` dropped, and
  `dispose()` also removes the canvas.
- **Lazy load and fallback.** The stage's `hero-fallback.svg` is a plain `<img>`, not a
  `<noscript>` one: it is the no-JS state *and* the first paint with JS. After first paint
  (`requestAnimationFrame` → `setTimeout 0`), once the stage is within a viewport, `boot()` probes
  WebGL and imports `three-renderer.js`. `?renderer=svg` (or `pp-qa`), a failed probe, a rejected
  import, a throwing `makeThree()` or 4 s without a start all start the SVG renderer instead;
  the label reads `… · WEBGL` or `… · SVG FALLBACK`. The image is removed only after a renderer
  has drawn its first frame, and the step controls (rendered `hidden`) appear only then, so the
  stage is never blank and no control is dead. Measured: three is requested ~170–220 ms after
  first paint; CLS 0.0012 at 1578 and 0 at 390.
- **Pausing.** The render loop stops entirely off-screen (IntersectionObserver) and in a hidden
  tab (`visibilitychange`) and restarts on return; the timeline does not advance while stopped.
  The prototype's watchdog (draw if rAF stalls > 300 ms) is kept but only runs for a visible
  stage.
- **Reduced motion** (system or `?motion=reduced`): opens at `END` with the gate at 10/10; no
  parallax, spin or dust drift; the loop draws only when something changed, so nothing runs
  continuously. Step buttons jump to `PH[i+1] − 0.001` as the prototype does (06 to `END`).
  *Pause* is hidden because it would do nothing. A system change while open jumps to the settled
  end either way, never a half-played state.
- **Controls.** *Pause* changes its label (❚❚ Pause / ▶ Play) and does not also carry
  `aria-pressed`, as *Play case* in P4. Below 640px the step names are visually hidden, as the
  prototype shows numbers only, but stay in each button's accessible name. Under
  `pointer: coarse` the hero buttons are 44px tall, as `RESPONSIVE_SPEC.md` asks. The caption is
  `aria-live="polite"`. `window.__ppHero.seek(t)` is kept (returns the phase, or −1 before a
  renderer starts) with a `renderer` getter.
- **Below 360px** (a responsive fix): the two-line stage label reached "NOT RECEIVED" and the
  two UNTOUCHED tags ran together. The stage gains 48px (the width-fitted mobile scene only moves
  down) and tag tracking is −.02em there; `LM` is unchanged and labels stay 11px.
- **Budget** (`tools/check-budgets.mjs`, now part of `npm run verify`): three chunk
  **106.59 KB gz** (Vite reports 107.76 at its gzip level) against 150; total JS **120.66 KB gz**
  against 200. A negative control (an extra 120 KB gz chunk) fails it.
- **Reference comparison**, scratch headless Edge over CDP, `seek(t)` at 0.95, 4.3, 5.8, 8.2:
  desktop 1578 matches `reference/desktop/01–02` in structure, positions, labels, colours and
  tags; mobile 390 matches `reference/mobile/01` and `01a`; `?renderer=svg` matches
  `reference/webgl-fallback/` (5/10 at 5.8, final at 8.2); reduced motion on load matches
  `reference/reduced-motion/01`; laptop 1280 matches `reference/laptop/01`. Deviations:
  (1) `reference/reduced-motion/02` shows the final state, but the prototype's own `heroGo(4)`
  under reduced motion lands on t = 4.899 (B "YES · HELD", gate 0/10), which is what ships; the
  reference is a crop that does not match its code. (2) The mobile stage is 554px at 390, the
  spec's 1.42 × width; the reference is ~584px because its capture rewrote `vw`. (3) At 768 the
  desktop scene is width-fitted as specified and the gate label and A's tag sit 0.9px apart
  (no glyph overlap); the prototype composes it the same way.
- Also verified: WebGL disabled by browser flags → SVG with no three request; three request
  held forever → image stays with controls hidden, SVG at ~4 s; three request failed → SVG at
  once; JS disabled → image, settled caption, no controls, no overlay; widths 320 / 360 / 390 /
  768 / 1280 / 1578 without overflow; keyboard (Tab, Enter, Space) on every hero control with the
  focus ring; S2 stepper, order detail, gate 10/10 and illustration toggle, traces and Copy
  unchanged; zero console errors.

**Recorded during P6/P7, session S4** (adversarial QA; the design is unchanged):

- **Dependencies, exact:** `@playwright/test` 1.63.0 and `@axe-core/playwright` 4.13.0 (axe-core
  4.13). `typescript` was not added: nothing in S1–S3 uses `// @ts-check`, so the plan's
  `typecheck` step would check nothing yet. Playwright's own Chromium download timed out through
  the local TLS-intercepting proxy; the same Chrome for Testing 153 zips were fetched with curl
  into the Playwright cache. CI will use `npx playwright install --with-deps chromium`.
- **`npm run check`** = `build` → `verify` (assets, content, links, budgets) → `test`, one build.
  The suite runs against `vite preview` of `dist/` under `/PromisePatch/` and refuses to run
  without a build. **92 tests in 7 files**, Chromium only: `layout` 42, `a11y` 18, `interaction`
  9, `hero` 8, `content` 8, `fallbacks` 6, `webgl-disabled` 1. Final run: exit 0, 92 passed.
- **One set of content rules.** `tools/content-rules.mjs` holds the rules; `verify-content` runs
  them over the built page and `content.spec.js` over the live DOM after about forty interaction
  states (every stage, order, scenario, trace, hero time, Copy). A negative control mutates the
  live DOM and the rules catch all three mutations. Every snapshot passes.
- **Width matrix** 320 / 360 / 390 / 414 / 640 / 768 / 1000 / 1024 / 1079 / 1080 / 1280 / 1440 /
  1578 / 1920: no overflow, nothing crossing the viewport outside a clipping ancestor, no text
  under 11px outside the stage and diagram, no `[hidden]` element rendered, no clipped control,
  stage height as specified and stable, every breakpoint form on its side. All pass; no layout
  defect found.
- **Fallbacks:** no JS (390, 1440), `?renderer=svg`, WebGL disabled by launch flags (no three.js
  request), the three chunk held (image stays, controls hidden, SVG at the 4 s timeout, stage
  never blank) and aborted. All pass. The WebGL path asserts the renderer the chunk's load time
  calls for: on this machine a loopback stall once delayed the chunk 11 s, and the designed SVG
  takeover correctly happened.
- **Hero:** `seek()` states at 0.95 / 4.3 / 5.8 / 8.2 (tags, lanes, gate label, caption, pressed
  step) at 1578 and 390; keyboard; both reduced-motion switches (settled on load, at most 3 rAF
  in an idle second, no parallax, steps to phase ends); a live preference change; off-screen and
  hidden-tab pausing. All pass. The hidden tab is simulated by overriding `visibilityState` and
  dispatching `visibilitychange`, not by a real tab switch.
- **Accessibility:** axe zero serious or critical at 390 and 1440 with JS on and off (JS off is
  the entry script blocked, the same DOM as no JS since the page has no `<noscript>`), on the
  illustration and on the pending gate, with no rule disabled and nothing excluded. Also one
  `h1`, one `h2` per section, no skipped level, landmarks, skip link, a full Tab walk (ring on
  every stop, no trap, deferred items not focusable), pressed state, table caption and scope,
  colour-alone, 44px targets under a coarse pointer, WCAG 1.4.12 text spacing.
- **Real defects found and fixed**, each reproduced by a test that failed before the fix:
  1. Past matrix cells at the prototype's opacity .62 were 3.89–4.30:1 on 28 cells of the
     settled default, which is also the no-JS state. Now .72 (.70 is the measured threshold).
  2. Pending revalidation checks (the gate before it is 35% in view) were 2.74–4.34:1. Now
     opacity .75 with the mark in `--muted`. Found by Lighthouse, missed by axe runs that judged
     only the settled gate; `a11y.spec.js` now judges the pending gate too.
  3. The scenario buttons had a fixed 32px `height`, so under the WCAG 1.4.12 spacing overrides
     their wrapped labels spilled out. Now `min-height`, identical at normal spacing.

  Test-side faults fixed on the way, not product defects: computed opacity read mid-transition,
  smooth scroll racing the focus and scroll checks, a fixed-pause reveal walk, a reduced-motion
  read before its frame, and paint entries whose presentation time trails the rendered frame by
  up to ~55 ms (three.js is now asserted after the first rendered frame, recorded in-page).
- **Network and budgets:** every request stays on the preview origin under `/PromisePatch/`, JS
  on and off, with no 4xx. three chunk 106.59 KB gz, total 120.68 KB gz. CLS at most 0.0013
  (390, 1578). Deviation from §5: the LCP element is the lede (390) or the settled hero image
  (1578), not the H1; both land in the first contentful frame, and three.js is requested after
  the first rendered frame.
- **Lighthouse 13.5.0**, run locally (not a dependency) against `vite preview`, Chrome for
  Testing 153 headless, default mobile (simulated slow 4G, 4× CPU) and `--preset=desktop`, on
  this Windows development machine with a TLS-intercepting antivirus active:
  - Accessibility **97** before fix 2, **100** after. Best Practices **100**. SEO **100**.
  - Performance, mobile: **39–87** across seven runs (after the fixes: 69, 68 and 87 default,
    68 `?motion=reduced`, 49 `?renderer=svg`). Desktop: **63** and **95**.
  - **The ≥ 95 mobile performance target is not met.** The cause, from traces, is Total Blocking
    Time. The long tasks are style recalculation and layout (the cold first layout of the long
    page with seven self-hosted font files) and, with JS on, WebGL context creation and frame
    commits on headless Chrome's software GL from the hero's continuous render loop (approved:
    parallax and dust stay on). A blank page on the same machine scores 100 with TBT 0, and
    identical code swings TBT from 183 ms to 2.7 s between runs, so the machine adds large
    variance. No low-risk fix exists without removing approved behaviour or fonts, so none was
    made.
- **Manual pass:** the keyboard walk is scripted at 390 and 1440, and the focus ring was reviewed
  in screenshots on the skip link, stepper, order, scenario, trace, hero step, Copy and CTA
  (visible everywhere). Reduced motion is held by the tests. Zoom: 320 CSS px is 1280 at 400%
  and reflows, except that under the 1.4.12 spacing overrides the R1–R5 table widens the page to
  337px at 320 (a data table, the reflow exception; nothing is lost). **No screen reader was run**
  (no NVDA or VoiceOver here), so the screen-reader row of §5 stays open.
- **Reference comparison** (1578 and 390, viewport captures): hero final, six promises,
  revalidation (R3 and the illustration), architecture with the consent trace, evidence and the
  final CTA match `reference/` in structure, positions, labels and colours. The one visible
  deviation is the slightly brighter past cells (fix 1). An element screenshot taller than the
  viewport briefly resizes the stage to 0 wide during capture, so hero captures must be viewport
  captures.
- **P7 content audit**, sentence by sentence (rendered copy, then `CONTENT_SOURCES.md`, then the
  cited record): about 115 claim-bearing items verified; no 11/16–16/16 progression; no Telegram
  inbound, native Alexa+, live refusal or production-safety claim; deferred URLs absent from
  `dist/`. **Five discrepancies, recorded and not changed**, because they change claim wording,
  which is the owner's call:
  1. "Worker starts again, 2 min 29 s later" (R3 timeline, `index.html`): 2 min 29.5 s is how long
     the stored answer waited; press to worker start was about 2 min 27.5 s
     (`docs/g8-rehearsal-r3.md` §4).
  2. The deadline check value "20:31:01Z ≤ 01:26:54Z" (`src/data/checks.js`): the record reads
     `≤ 2026-09-25T01:26:54Z`; without the date it reads as false (`g8-rehearsal-r3.md` §9).
  3. "Customer presses APPROVE" (R3 timeline): R3 records the owner's APPROVE, pressed as the
     canonical demo customer (`g8-rehearsal-r3.md` §4).
  4. A plan approval "in a signed-in session" (`stages.js` stage 4, the `arch.js` edge label, the
     `traces.js` report trace, the authority rule strip): the deployed rehearsals confirmed
     through `OPERATOR_CONSOLE` (`pp confirm-plan`), and ADR-0018 defines two human channels.
     The page follows `README.md` §How authority works, which says the same and is itself
     contradicted by ADR-0018.
  5. The hero caption "…and the world keeps moving while it waits" (`src/hero/constants.js`): the
     deployed record says the world did not move between the message and the answer
     (`docs/deployed-customer-channel.md` §11), so as a statement about the case it is
     unsupported.

  Four ledger citations were wrong and are corrected without changing any claim: the v1
  "hand-labelled before the runner existed" caveat (README §Measured evidence and
  `docs/effect-set-manifest.md`, not the run protocol), "best-of-two" (`docs/claims-audit.md`),
  the per-rehearsal Telegram count (`docs/g8-demo-funnel.md`), and the freeze date (README §AWS
  deployment, not §License). **P7 closes only once the five items are resolved.**

  **Later truth (2026-09-28, claim hardening, branch `showcase/claim-hardening`).** The five
  items above are recorded as they were found; the owner asked for them corrected, and the copy
  now moves toward the record. Each was re-verified against the repository first:
  1. The R3 row at `20:30:58` now reads "Worker starts again, 3 min 35 s after it stopped": the
     stopped window, `FinishedAt` `20:27:23.607` → `StartedAt` `20:30:58.991`. The 2 min 29 s
     interval was right for what it measures, so it moved rather than went: the `20:31:01` row
     says "Stored answer taken up, 2 min 29 s after the press" (`20:28:31.492` →
     `20:31:00.972`, R3 §4).
  2. The deadline value reads `24 Sep 20:31:01Z ≤ 25 Sep 01:26:54Z`.
  3. The timeline reads "The owner, as the demo customer, presses APPROVE"; stage 5 adds that in
     the rehearsals the owner acted as the demo customer. The Telegram delivery and the web
     approval stay described as real.
  4. Plan approval is described as a signed-in browser session **or the operator console**
     (`ApprovalChannel`), everywhere it appeared, the root README included; stage 4 says the
     deployed rehearsals used the console.
  5. The hero caption reads "Conditions can change while an answer waits."

  The same pass corrected four further claims the audit had not listed, each against code:
  customer consent no longer mentions an option code (`domain/consent.py` reads a normalized
  `YES` or `NO` only, and says it deliberately implements no option code); MCP intake is named a
  trusted reporting channel whose reports are attested as the configured surface worker
  (`api/routers/intents.py`), and the model card no longer says the model cannot attest a
  physical fact; revalidation is scoped to the commit it guards, with only the production start
  judged again at an amendment's first dispatch (ADR-0024, ADR-0026), and `STALE` is no longer
  a universal re-plan (an expired answer, and staleness found at apply time or first dispatch,
  go to the owner); and "effects applied exactly once" is replaced by the rehearsals' recorded
  result, beside a new limitation that Telegram's Bot API has no idempotency key. The hero lede
  and the root README's subhead now state the customer-level value first. The corrected
  sentences depart from the prototype's copy, which §10 item 2 otherwise requires verbatim; the
  record wins. `tools/content-rules.mjs` now enforces each correction as a semantic rule, over
  the page, every runtime string and the root README (§6.3).
- **Freeze:** all three §7 checks print nothing; the frozen manifest verifies
  (`d41f5afc…2cdc`); `git diff --check` is clean; no product path, CI workflow or evidence file
  changed.
- **Local constraint:** concurrent browsers stall loopback requests for 20–60 s on this machine
  (reproduced against a plain static server), so the suite runs one worker locally
  (`PW_WORKERS` overrides) and two on CI.

This plan turns the approved Claude Design handoff into a static GitHub Pages site served from
this repository at **`https://asembris.github.io/PromisePatch/`**. The design is frozen; this
plan implements it and does not redesign it. The site is a presentation artefact. It adds no
product behaviour and makes no claim the repository does not already make.

## 0. Inputs and the facts that bind the plan

**The handoff.** Extracted locally at `.handoff/showcase/` and ignored by `.gitignore`, so it is
never committed. Read in full for this plan: `README_FIRST.md`, `DO_NOT_CHANGE.md`,
`HANDOFF.md`, `IMPLEMENTATION_CHECKLIST.md`, `CONTENT_MAP.md`, `ASSET_MANIFEST.md`, `LINKS.md`,
`TOKENS.md`, `MOTION_SPEC.md`, `RESPONSIVE_SPEC.md`, `ACCESSIBILITY_AND_PERFORMANCE.md`,
`reference/README.md`, the prototype `PromisePatch_Showcase.dc.html` (993 lines; the logic class
from line 591 holds the scene model, both renderers and every data table), `support.js`, the
three packaged brand SVGs, `assets/hero-fallback.svg`, `assets/hero-fallback.png`,
`assets/og-preview-1200x630.png` and the 38 reference screenshots under `reference/`.

**Source-of-truth priority** (from `README_FIRST.md`, unchanged here): repository facts at the
frozen release, then `DO_NOT_CHANGE.md`, then the spec files, then the prototype, then the
screenshots. Where the prototype conflicts with a fact, the fact wins, and the implementation
session records the conflict rather than guessing.

**What the prototype is and is not.** It is a design file, not a site. `support.js` is the
Claude Design runtime: it pulls React 18, ReactDOM and Babel from unpkg at runtime and compiles
the page's `<x-dc>` template (`<sc-if>`, `<sc-for>`, `style-hover=`, `style-focus=` attributes)
in the browser. The prototype also loads Google Fonts and `three@0.149.0/build/three.min.js`
from unpkg. **None of that runtime ships.** The port keeps the logic (scene model, renderers,
layouts, timings, data tables) and replaces the runtime with static HTML plus small vanilla
ES modules.

**Repository facts found during inspection that shape the plan.**

| Fact | Consequence |
|---|---|
| There is no root `package.json` and no npm workspace; `apps/frontend` has its own `package.json` + `package-lock.json` and the `pr` `frontend` job runs with `working-directory: apps/frontend`. | A self-contained `showcase/package.json` with its own lockfile touches no existing job and no product lockfile. |
| `pr.yml` and `effect-sets.yml` trigger on every push to `main` except Markdown-only changes. | Every showcase commit that adds non-Markdown files **will run the full 13-job `pr` workflow and the effect-set workflow** (which is red on v1 by design). That is correct and is not changed. It costs CI minutes, not correctness. |
| `.gitignore` already ignores `node_modules/`, `dist/` and `build/` at any depth. | `showcase/node_modules/` and `showcase/dist/` are ignored with no new rule. |
| `docs/` is the authoritative record, and `pr.yml` deliberately does not exclude it because the frozen manifest lives there. | The site must not live under `docs/`. |
| The `brand/` SVGs in the handoff differ from the repository's only in serialization (`<path …></path>` vs `<path …/>`). | The build takes the brand files from `brand/`, byte-for-byte, as `ASSET_MANIFEST.md` asks. |
| `brand/promisepatch-logo-on-dark.svg` carries its wordmark as one `<text>` element in a system-sans stack. | The logo renders with the viewer's system font; it is used as an `<img>` and never retyped. |
| `assets/hero-fallback.svg` references no external URL except namespace URIs and carries an embedded C2PA provenance block. | It is copied byte-for-byte; the provenance block is kept. |
| The 15 doc link targets in `LINKS.md`, the `pr` run id `36310794944` and the R3 timeline values were spot-checked and exist on `main`. | The link checker in §8 turns that one-off check into a build gate. |

## 1. Chosen architecture

### 1.1 Directory: `showcase/` at the repository root

Evaluated against the repository, not chosen by default:

| Candidate | Verdict | Why |
|---|---|---|
| `apps/showcase/` or inside `apps/frontend/` | **rejected** | `apps/` is product territory. `apps/frontend` is named in the freeze-check path list in [g8-closeout.md](g8-closeout.md) §5, so any file there would void the feature freeze. A sibling under `apps/` would read as a product surface and invite the same mistake. |
| `docs/site/` | **rejected** | `docs/` is the authoritative evidence record. A `package.json`, lockfile and build tree there would mix tooling into evidence, and the "Pages from `/docs`" mode would publish every internal document as a web page. |
| `site/` | acceptable, not chosen | Clean, but generic, and it disagrees with the handoff, whose checklist and Pages path filter already say `showcase/`. |
| **`showcase/`** | **chosen** | Matches the handoff's own naming (checklist steps 2 and 19), is outside every freeze path, outside `docs/`, and makes the one-folder path filter in §2 exact. |

Isolation rules:

- `showcase/` has its own `package.json`, `package-lock.json`, `vite.config.js` and tooling. It
  imports nothing from `apps/`, `packages/` or any Python module, and nothing outside it imports
  from it.
- The only files outside `showcase/` the implementation may add or change are
  `.github/workflows/showcase-pages.yml`, this plan (status updates), and, optionally, one link
  line in `README.md` once the site is live. The only repository paths the build **reads**
  outside `showcase/` are `brand/*.svg` and, for the link gate, the list of files under `docs/`.
  It writes nothing outside `showcase/dist/`.
- The site never calls the live app. It links to it.

### 1.2 Build: Vite (vanilla, no framework) with plain ES modules

- **Vite**, current major, pinned exactly in `showcase/package.json` (no caret) and locked by
  `package-lock.json`. The repository already uses Vite, so the tool is familiar, and it gives
  what the budget needs: code-splitting for a lazy three.js chunk, hashed assets, a `base` for
  `/PromisePatch/`, and a static `dist/`.
- **No React, no Tailwind, no UI framework.** The page is static HTML with progressive
  enhancement; a framework would add 40+ KB gz and a hydration step for nothing.
- **Plain JavaScript ES modules**, not TypeScript. The hero code is ported from the prototype
  "as it is" (checklist step 5); translating it to TypeScript is exactly the kind of rewrite that
  moves a timing or a coordinate. `// @ts-check` with JSDoc is allowed where it catches real
  mistakes, checked by `tsc --noEmit --allowJs --checkJs` as a dev dependency.
- **Runtime dependencies: `three` only.** Fonts come in as npm packages that are resolved at
  build time and ship as static files.
- **Dev dependencies, the complete list:** `vite`, `typescript` (check only),
  `@playwright/test`, `@axe-core/playwright`, `@fontsource/instrument-sans`,
  `@fontsource/ibm-plex-mono`. Nothing else is added without a line in this plan saying why.

### 1.3 One source of truth for content: build-time rendering

The page must read fully without JavaScript (accessibility spec: "Ship all section content as
static HTML… Interactive sections render their settled state as default markup"), and the same
data drives the interactive states. Writing the settled HTML by hand beside a JS data table would
let them drift.

So: the prototype's data tables (`STAGES`, `ROWS`, `DET`, `CELL`, `CHECKS`, `TRACES`, `ARCH`,
`PROOFS`) move verbatim into `showcase/src/data/*.js`. Small **pure string renderers** in
`showcase/src/render/*.js` turn a data table plus a state into HTML. They run twice:

1. **At build time**, from a ~40-line Vite plugin (`transformIndexHtml`) that replaces
   `<!-- @render:section -->` markers in `index.html` with each section's settled default:
   stage 7 *Settled* with order B selected, R3 at 10/10 PROCEED, the *Customer consent* trace.
2. **At runtime**, when a control changes state, the same renderer produces the new markup for
   the one region that changed.

Static prose (headings, ledes, caveats) is written directly in `index.html`, copied verbatim
from the prototype.

### 1.4 Three.js: bundled, lazy, tree-shaken

- `three` is installed from npm and **pinned to an exact version**. No CDN at runtime.
- `src/hero/three-renderer.js` is the port of `makeThree()`. It imports **named** classes only:
  `WebGLRenderer, Scene, PerspectiveCamera, Group, Mesh, CircleGeometry, RingGeometry,
  PlaneGeometry, BufferGeometry, BufferAttribute, Line, LineBasicMaterial, LineDashedMaterial,
  Points, PointsMaterial, MeshBasicMaterial, Color, Vector3` — the exact set the prototype uses
  (the accessibility spec's list plus `BufferAttribute`, which the prototype also uses).
- The module is reached only through a dynamic `import()` fired when the stage is within one
  viewport of the screen **and** after first paint (`requestAnimationFrame` → `setTimeout 0`),
  so Vite emits it as its own chunk and it never blocks the H1.
- **Version and colour parity.** The prototype ran r149, before three.js turned colour management
  on by default (r152). Implementation pins the current release and sets
  `ColorManagement.enabled = false` and `renderer.outputColorSpace = LinearSRGBColorSpace`, so
  hex colours and alpha blending render as the prototype rendered them. The screenshot
  comparison in phase 5 is the arbiter. **If parity is not reached, pin `three@0.149.0`
  instead**, and record which version shipped and why in this document.
- Renderer settings from the performance spec: `antialias: true, alpha: true,
  powerPreference: 'low-power'`, DPR capped at 2, `preserveDrawingBuffer` removed, rendering
  paused off-screen (IntersectionObserver) and in hidden tabs (`visibilitychange`).
- **Budget gate:** the three chunk must be ≤ 150 KB gz and total JS ≤ 200 KB gz, checked by
  `tools/check-budgets.mjs` after every build.

### 1.5 Hero port: what is copied unchanged

From the prototype logic class, unchanged apart from the mechanical removal of `this.` and
React state: `K` (colours), `PH = [0, 0.35, 1.25, 2.3, 3.25, 4.9, 6.9]`, `END = 8.2`, the `LD`
and `LM` layout tables, `scene(t, L)`, `makeThree()`, `makeSvg()`, `place()`, `phaseOf()`,
`frame()`, `layout()`, `heroGo()`, the watchdog interval, pointer parallax and the label
overlay contract (`data-k`, `data-a`, `data-t`). React `setState` calls become direct DOM writes
to the caption, the step buttons' `aria-pressed` and the renderer label. The `window.__ppHero.seek`
hook stays, because the screenshot comparison in phase 5 uses it to capture t = 0.95, 4.3, 5.8
and 8.2.

### 1.6 Fallbacks

| Condition | Behaviour | How |
|---|---|---|
| **No JavaScript** | The stage shows `assets/hero-fallback.svg`, and every section shows its settled state. | `<noscript><img src="…/hero-fallback.svg" alt=""></noscript>` inside the stage; the stage's `role="img"` `aria-label` carries the description. All sections are static markup (§1.3). Controls that do nothing without JS (Play case, step buttons, trace and scenario toggles, Copy) are rendered with a `hidden` attribute that the enhancement script removes, so a no-JS reader never meets a dead button. |
| **WebGL unavailable** | The SVG renderer draws the same scene model with the same labels and timeline. | `glOK()` probe; three.js import rejects or does not resolve within **4 s**; or `makeThree()` throws. Any of the three starts `makeSvg()`. The renderer label reads `SVG FALLBACK`. |
| **Reduced motion** | Hero opens at its final state; step buttons jump to each phase's end state; no parallax, spin, dust drift, reveals or staggered checks. | `matchMedia('(prefers-reduced-motion: reduce)')` read once at start and on change, plus the prototype's global CSS clamp. |
| **QA switches** | `?renderer=svg` forces the fallback; `?motion=reduced` forces reduced motion; also read from `localStorage['pp-qa']` as JSON. | Kept exactly as in the prototype, every `localStorage` access in `try/catch`. |
| **Layout shift** | None from the hero. | The stage has its final height in CSS before any script runs (`clamp(440px,62vh,640px)`; mobile `min(620px, 1.42 × 100vw)`). |

### 1.7 Assets

| Asset | Source | Handling |
|---|---|---|
| `promisepatch-logo-on-dark.svg`, `promisepatch-icon-on-dark.svg`, `promisepatch-icon-monochrome.svg` | repository `brand/` | Copied at build time into `dist/brand/` by the Vite plugin, byte-for-byte. `tools/verify-assets.mjs` asserts the copies' SHA-256 equals the `brand/` originals. Not committed a second time. |
| `favicon.svg` | copy of `brand/promisepatch-icon-on-dark.svg` | Same build-time copy. |
| `apple-touch-icon.png` (180 × 180 on `#111A2B`) | rendered once from the icon | Generated once in the implementation session with the Playwright Chromium already in dev dependencies, by `tools/render-touch-icon.mjs`, and committed under `showcase/public/`. No image library is added. |
| `hero-fallback.svg` | handoff `assets/` | Copied byte-for-byte into `showcase/public/assets/` and committed. |
| `og-preview-1200x630.png` | handoff `assets/` | Copied byte-for-byte into `showcase/public/assets/` and committed; referenced only by meta tags, with an absolute URL. |
| `hero-fallback.png` | handoff `assets/` | **Not shipped.** Nothing on the page references it; the SVG covers every context the page has. |
| Fonts | `@fontsource/instrument-sans` (400/500/600/700) and `@fontsource/ibm-plex-mono` (400/500/600), Latin subset only | Both families are SIL OFL 1.1, and Fontsource redistributes the upstream Google Fonts files under that licence. Vite emits the WOFF2 files into `dist/assets/`; `font-display: swap`; `<link rel="preload">` for Instrument Sans 600 Latin. The OFL text and attribution ship in `showcase/THIRD_PARTY_NOTICES.md` and in `dist/`. **No Google Fonts request at runtime.** If a package turns out to lack a weight or its licence file, the fallback is the system stacks `TOKENS.md` already specifies, not a CDN. |
| three.js | npm `three` | MIT; its notice goes in the same `THIRD_PARTY_NOTICES.md`. |
| Reference screenshots, prototype, `support.js` | handoff | **Never copied** into the repository. They stay in the ignored `.handoff/`. |

## 2. GitHub Pages deployment

**Strategy: GitHub Actions as the Pages source, from this repository, on `main`.** No `gh-pages`
branch, no `/docs` folder publishing, no separate `Asembris.github.io` repository.

| Item | Decision |
|---|---|
| Workflow file | `.github/workflows/showcase-pages.yml` (new; `pr.yml` and `effect-sets.yml` untouched) |
| Trigger | `push` to `main` with `paths: ['showcase/**', 'brand/**', '.github/workflows/showcase-pages.yml']`, plus `workflow_dispatch`. `brand/**` is included because the build copies from it. No `pull_request` deploy. |
| Jobs | `build`: checkout → `actions/setup-node` (Node `24`, the version `pr.yml` pins) with npm cache keyed on `showcase/package-lock.json` → `npm ci` → `npm run check` (§8) → `npm run build` → `actions/upload-pages-artifact` with `path: showcase/dist`. `deploy`: `needs: build`, `environment: { name: github-pages, url: ${{ steps.deployment.outputs.page_url }} }` → `actions/deploy-pages`. |
| Working directory | `defaults.run.working-directory: showcase` |
| Build command | `npm ci && npm run check && npm run build` |
| Artifact directory | `showcase/dist` |
| Base path | `base: '/PromisePatch/'` in `vite.config.js`, overridable with `SHOWCASE_BASE=/` for local preview. |
| Permissions | Workflow-level `contents: read`; job `deploy` adds `pages: write` and `id-token: write`. Nothing else. |
| Concurrency | `group: showcase-pages`, `cancel-in-progress: false` (a distinct group, so it never cancels `pr-*` or `effect-sets-*`). |
| Actions | Official `actions/checkout`, `actions/setup-node`, `actions/upload-pages-artifact`, `actions/deploy-pages`, `actions/configure-pages`, each pinned to a full commit SHA with the version in a comment. |
| Secrets | None. |
| Expected public URL | `https://asembris.github.io/PromisePatch/` |
| Social preview | `og:url` and `og:image` use the absolute Pages URL (`https://asembris.github.io/PromisePatch/assets/og-preview-1200x630.png`), `og:image:width=1200`, `og:image:height=630`, `og:image:alt` "PromisePatch — The model understands. The deterministic protocol authorizes.", `twitter:card=summary_large_image`. |

**One manual step belongs to the repository owner**, and it is not taken by any session without
being asked: *Settings → Pages → Build and deployment → Source: GitHub Actions.* Until it is set,
the `deploy` job fails with a clear "Pages not enabled" error; the `build` job and its checks
still run and still mean something. The `github-pages` environment is created by GitHub on first
deployment and by default allows only `main`.

**What this session does not do:** enable Pages, create the workflow, push, or deploy.

## 3. File map

```
showcase/
├── package.json               exact-pinned deps; scripts below
├── package-lock.json
├── vite.config.js             base, build target, the render + brand-copy plugin
├── index.html                 every section's static prose; @render markers; meta; noscript
├── README.md                  how to run, build, check; what this folder may and may not touch
├── CONTENT_SOURCES.md         committed claim → repository-source ledger (§6)
├── THIRD_PARTY_NOTICES.md     OFL 1.1 (both fonts), MIT (three)
├── public/
│   ├── assets/hero-fallback.svg          byte-for-byte from the handoff
│   ├── assets/og-preview-1200x630.png    byte-for-byte from the handoff
│   └── apple-touch-icon.png              rendered once from brand/, committed
├── src/
│   ├── main.js                entry: qa switches, reduced-motion flag, wires each enhancer
│   ├── styles/
│   │   ├── tokens.css         every TOKENS.md variable, verbatim values
│   │   ├── base.css           reset, fonts, links, focus ring, skip link, selection
│   │   ├── layout.css         container, section, band, flex-pair primitives, header
│   │   └── sections.css       per-section rules, breakpoints 400/640/1000/1080, coarse-pointer 44px
│   ├── data/
│   │   ├── stages.js  rows.js  detail.js  cells.js   STAGES, ROWS, DET, CELL
│   │   ├── checks.js          CHECKS, R3 values
│   │   ├── traces.js  arch.js TRACES, ARCH
│   │   ├── proofs.js          PROOFS (10 rows)
│   │   ├── facts.js           the DO_NOT_CHANGE facts, each with its source path
│   │   └── links.js           every href on the page; deferred items marked, with no URL
│   ├── render/                pure (state) → HTML string; used by the build and at runtime
│   │   ├── matrix.js  detail.js  gate.js  arch.js  proofs.js  rehearsals.js
│   ├── hero/
│   │   ├── constants.js       K, PH, END, LD, LM
│   │   ├── scene.js           scene(t, L), unchanged
│   │   ├── three-renderer.js  makeThree(), named three imports (lazy chunk)
│   │   ├── svg-renderer.js    makeSvg()
│   │   └── controller.js      init, layout, frame, place, phaseOf, heroGo, watchdog, fallback
│   ├── sections/
│   │   ├── header.js          logo swap < 400px (CSS-only preferred)
│   │   ├── story.js           stepper, Play case, matrix, detail (aria-pressed, aria-live)
│   │   ├── revalidate.js      scenario toggle, time-based checks, outcome card
│   │   ├── architecture.js    trace buttons, SVG ≥ 1080 / chain below, staggered edges
│   │   ├── deployment.js      Copy buttons, "Copied ✓" for 1.6 s, announced
│   │   └── reveal.js          one-shot section reveal, off under reduced motion
│   └── lib/
│       └── motion.js          glide, settle, ui easings; reduced-motion helper
├── tools/
│   ├── vite-plugin-showcase.js  @render markers + brand copy
│   ├── verify-content.mjs     §6 content and forbidden-phrase gate over dist/index.html
│   ├── verify-links.mjs       §5/§6 link gate
│   ├── verify-assets.mjs      brand hashes, no external runtime origins in dist/
│   ├── check-budgets.mjs      gz sizes against the budgets
│   └── render-touch-icon.mjs  one-off, Playwright
└── tests/                     Playwright, against `vite preview`
    ├── layout.spec.js         overflow at every width, breakpoint forms
    ├── fallbacks.spec.js      no-JS, WebGL off, reduced motion, 4 s timeout
    ├── interaction.spec.js    stepper, matrix, gate toggle, traces, copy, keyboard order
    ├── a11y.spec.js           axe, landmarks, headings, aria-pressed, aria-live
    └── hero.spec.js           seek(t) captures for the screenshot comparison

.github/workflows/showcase-pages.yml   §2
```

`package.json` scripts: `dev`, `build`, `preview`, `typecheck` (`tsc --noEmit --allowJs
--checkJs`), `verify` (content + links + assets + budgets over `dist/`), `test` (Playwright),
`check` (`typecheck` → `build` → `verify` → `test`).

## 4. Implementation phases

Each phase is one coding session or less, ends in one commit (§9), and does not start until the
previous phase's acceptance criteria hold. Phases follow `IMPLEMENTATION_CHECKLIST.md`; its step
numbers are given in brackets.

| # | Phase | Covers | Accept when |
|---|---|---|---|
| **P1** | Scaffold and tokens | [2, 3] `showcase/` with `package.json`, lockfile, `vite.config.js` (base), `index.html` skeleton (landmarks, one `h1`, skip link, meta, empty section shells with ids `top problem story authority revalidate evidence architecture deployment proof`), `tokens.css`, `base.css`, `layout.css`, fonts via Fontsource, the brand-copy plugin, `THIRD_PARTY_NOTICES.md`, `README.md`. | `npm ci && npm run build` succeeds; `dist/` has no request to `fonts.googleapis.com`, `fonts.gstatic.com` or `unpkg.com`; colours and type scale match the reference screenshots; the freeze check in §7 is empty. |
| **P2** | Header and all static prose | [4, 8, 13 prose, 14] Sticky header, nav from 1000px, icon below 400px; every section's headings, ledes and caveats verbatim from the prototype; authority split and rule strip; AWS spec list and SHA cards; proof-index rows and limitations panel; final CTA; footer; deferred items as `aria-disabled="true"` with no `href`, Devpost hidden. | The page reads completely with JS disabled; keyboard order is logo → links → CTA; no overflow at 320px; every copy block diffs clean against the prototype text. |
| **P3** | Data tables and build-time render | [7, 9, 11, 13 data] Move `STAGES ROWS DET CELL CHECKS TRACES ARCH PROOFS` verbatim into `src/data/`; write the pure renderers; the plugin injects the settled defaults; `facts.js` and `links.js`; `CONTENT_SOURCES.md`. | With JS disabled: the matrix shows stage 7 *Settled* with B selected, the gate shows R3 at 10/10 PROCEED, the architecture shows the consent trace, the proof index shows ten rows. `verify-content` and `verify-links` pass. |
| **P4** | Interactive sections | [7, 9, 10, 11, 12] Stepper and Play case (1150 ms per stage; 400 ms and manual under reduced motion); single-column matrix below 640px; gate scenario toggle with the coral "ILLUSTRATION · NOT A RECORDED RUN" header and tests-only note; time-based checks (120 ms each, 35% in view); architecture SVG ≥ 1080px and stacked chain below, trace stagger 140 ms; evidence block with the R1–R5 `<table>`; Copy buttons. | Matches `reference/desktop/04, 06, 07, 08, 09, 09b, 10` and `reference/mobile/03–08`; every toggle exposes `aria-pressed`; `aria-live` regions announce; no arrow or progression between 11/16 and 16/16. |
| **P5** | Hero, three.js and fallbacks | [5, 6] Port the hero exactly as §1.5; lazy three chunk; SVG renderer; 4 s timeout; reduced motion; `<noscript>`; QA switches; off-screen and hidden-tab pause. | Frames at t = 0.95, 4.3, 5.8 and 8.2 match `reference/desktop/01–02` and `reference/mobile/01*`; `?renderer=svg` matches `reference/webgl-fallback/`; `?motion=reduced` matches `reference/reduced-motion/`; three chunk ≤ 150 KB gz; the caption is `aria-live`; step buttons work by keyboard alone. |
| **P6** | Responsive, accessibility, performance | [15, 16, 17] Widths 320 / 390 / 768 / 1024 / 1280 / 1440 / 1920; 44px targets under `pointer: coarse`; axe; contrast; Lighthouse mobile. | §5 matrix all green. |
| **P7** | Content and link verification | [18] Run §6 end to end; sentence-by-sentence diff against `CONTENT_SOURCES.md`; forbidden-phrase gate. | Zero forbidden phrases, zero unverifiable claims, deferred URLs absent, every link resolves. |
| **P8** | Pages workflow | [19] `.github/workflows/showcase-pages.yml` as §2; OG/Twitter meta with absolute URLs. | The workflow's `build` job passes on a push; `pr.yml` and `effect-sets.yml` are byte-identical to before. Deployment itself waits for the owner's Pages setting and an explicit push. |
| **P9** | Screenshot comparison and closeout | [20] Capture every state `reference/` holds with the same widths and `seek(t)` values; compare side by side; record each deviation with its reason; update this plan's status. | No structural difference; every deviation is a documented accessibility or responsive fix. |

## 5. Validation matrix

All automated rows run in Playwright (Chromium) against `vite preview` of the production build.
Manual rows are taken once per release of the site and their results recorded in the closeout
note.

| Dimension | Check | How | Auto/manual |
|---|---|---|---|
| Widths | 320, 360, 390, 414, 640, 768, 1000, 1024, 1079, 1080, 1280, 1440, 1578, 1920 | `document.documentElement.scrollWidth === innerWidth` at each; no text under 11px outside the canvas (computed styles) | auto |
| Breakpoint forms | icon < 400; nav ≥ 1000; hero `LM` < 640; matrix current-stage column < 640; architecture SVG ≥ 1080, chain below | assert visibility of each form on both sides of each breakpoint | auto |
| Devices | desktop 1440/1920, laptop 1280, tablet 768/1024 portrait and landscape, phone 390 and 320 | visual pass against `reference/`; one real phone (iOS Safari or Android Chrome) | manual |
| Reduced motion | hero final on load; step buttons jump to phase end; gate 10/10 at once; no reveal opacity; no parallax | `page.emulateMedia({ reducedMotion: 'reduce' })` and `?motion=reduced` | auto |
| WebGL disabled | SVG renderer draws; label `SVG FALLBACK`; timeline and labels identical | `?renderer=svg`; Chromium with `--disable-webgl --disable-webgl2`; three import blocked by route to force the 4 s timeout | auto |
| No JS | fallback SVG in stage; every section's settled content present; no visible dead controls | `javaScriptEnabled: false` context; text assertions per section | auto |
| Keyboard | skip link first; logo → nav → CTA; every control reachable; `aria-pressed` toggles on Enter/Space; no trap; focus ring visible | scripted Tab walk | auto + manual |
| Screen reader | landmarks, one `h1`, one `h2` per section, table caption/scope, live-region announcements, stage description | NVDA + Firefox or VoiceOver + Safari, one pass | manual |
| Accessibility | axe: zero serious or critical | `@axe-core/playwright` at 390 and 1440, JS on and off | auto |
| Contrast | values in `ACCESSIBILITY_AND_PERFORMANCE.md` hold | axe colour-contrast rule plus spot checks of lane colours | auto + manual |
| Links | internal anchors resolve; external hrefs match the allowlist; `blob/main/docs/*.md` targets exist; deferred items have no `href` | `verify-links.mjs` (offline, against the working tree) | auto |
| Live links | live app, `pr` run 36310794944, GitHub repo, `#honest-limitations` anchor | fetched once by hand; never in CI, so the build never depends on the network or the deployment | manual |
| Performance | total JS ≤ 200 KB gz; three ≤ 150 KB gz; three requested only after first paint; LCP element is the H1; CLS < 0.05 | `check-budgets.mjs`; Playwright network log for three's request order; `PerformanceObserver` for CLS | auto |
| Lighthouse | ≥ 95 performance and ≥ 95 accessibility, mobile | `npx lighthouse` against `vite preview`, run locally, not a dependency | manual |
| Pages base | every asset URL resolves under `/PromisePatch/` | preview with the production base; 404 scan of the network log | auto |

## 6. Content verification

Every visible claim must trace to a committed repository source, and the trace must survive the
handoff staying uncommitted.

1. **A committed ledger.** `showcase/CONTENT_SOURCES.md` restates `CONTENT_MAP.md` in the
   repository: one row per displayed sentence or number, with its repository path and heading.
   It adds no claim; it points to where each claim already lives. Paths use `main`; where a row's
   truth is release-specific it cites the frozen SHA.
2. **Facts as data.** `src/data/facts.js` holds the `DO_NOT_CHANGE.md` facts exactly — `56c302366b3ddc0d824c1588a4a9ddbd193ed891`
   and short `56c3023`, `4529a802e34e`, `11/16`, `16/16`, `5/5`, `0 of 2 … in each`, the funnel
   `6 → 1 · 1 · 2 · 2`, `9/10` with its caveat, `13/13` and run `36310794944`, MCP revision
   `2025-11-25`, the AWS stack, freeze date `2026-09-27` — each with its `source` path. The page
   renders those values from this module, so a fact is typed once.
3. **`verify-content.mjs`**, run on `dist/index.html` (the no-JS page) and, through Playwright,
   on the hydrated DOM:
   - every fact in `facts.js` appears byte-exact, and every caveat `DO_NOT_CHANGE.md` requires is
     present near it (rehearsals: "not a reliability rate"; voice: run 1 voided, best-of-two,
     local stack, not a latency SLA; SHAs: different commits, tree-identical product paths;
     effect sets: developer-authored, finite, public, not an independent benchmark);
   - **11/16 and 16/16** *(corrected in P3/P4; the approved copy did not change)*: each may
     appear wherever it is labelled as its own result — the effect-set pair card with its badges
     (`PERMANENT HEADLINE`, `SEPARATE RELEASE CONDITION`), proof rows 06 and 07, and the caveat
     "The original benchmark did not become 16/16." Every occurrence must have its own label
     nearby (headline or v1; separate release condition or v2). The gate bans **progression
     semantics**, not arrow glyphs: an arrow or "to" joining the two scores (`11/16 → 16/16`,
     `11/16 -> 16/16`, `from 11/16 to 16/16`), "improved" beside a score, "now 16/16", "went up
     to 16/16", "became 16/16", before/after framing of the pair, and "benchmark scored 16/16"
     all fail. Link affordances such as "First scored run →" and "v2 release condition →" are
     navigation and pass. The original wording ("appear only inside the pair card", "no `→`
     within that card") contradicted the approved copy and is superseded;
   - **boundaries:** "Telegram" is never followed by inbound-consent language; the signed web
     link is named as the consent entry; "not a native Alexa+ integration" is present in the
     architecture section; "simulat" labels the order system and the Alexa+-style client; the
     illustration toggle carries "ILLUSTRATION · NOT A RECORDED RUN" and the tests-only note;
     the limitations panel says no refusal path was exercised live;
   - **forbidden phrases**, case-insensitive, zero hits: production-ready, production proven,
     formally safe, guaranteed safe, enterprise proven, zero risk, 100% reliable, native Alexa+
     integration (except inside the literal negation "not a native Alexa+ integration"),
     "benchmark improved";
   - **deferred:** "Demo video" and "Watch demo" elements have `aria-disabled="true"` and no
     `href`; no Devpost link exists;
   - **claim scope** *(added by the claim-hardening pass)*, sentence by sentence over the page,
     every runtime string and the root README: no option-code consent; no plan approval tied to
     a signed-in session alone (the operator console is the other channel); no unqualified
     "exactly once" and no ruled-out duplicate message; no MCP or AI caller described as holding
     no authority or as unable to attest; no atomic revalidation and no revalidation placed at
     external execution; no APPROVE press attributed to a customer; no world that moved while it
     waited; no universal `STALE` re-plan, and no general `STALE`-and-re-planned sentence without
     the owner path; no refusal presented as recorded; a time comparison that crosses midnight
     carries both dates; and every "N min S s" in the R3 timeline reaches back from its own
     row's time to another row's. The page must also state the operator console, MCP intake as a
     trusted reporting channel, Telegram's missing idempotency key, the owner as the demo
     customer, and the first dispatch as where revalidation stops.
4. **`verify-links.mjs`**: every `href` is internal (`#id` that exists), or in `links.js`; every
   `https://github.com/Asembris/PromisePatch/blob/main/<path>` target exists in the working tree;
   no `href` is empty, `#`, or `TBD`.
5. **Manual sentence diff** in phase P7: each rendered sentence against the prototype text and
   its `CONTENT_SOURCES.md` row. Any prototype sentence that conflicts with the repository is
   corrected toward the repository and listed in the closeout, never silently.

If a later repository document changes a fact the page shows, the page follows the repository and
`facts.js` changes with a new `source`; frozen and historical evidence is never edited to match
the page.

## 7. Freeze verification

The showcase must not move the release. Run at every implementation commit and before any push.

The frozen check from [g8-closeout.md](g8-closeout.md) §5, unchanged — **output must be empty**:

```bash
git diff --name-only 56c302366b3ddc0d824c1588a4a9ddbd193ed891 HEAD -- apps/backend/src apps/backend/alembic apps/backend/alembic.ini apps/backend/pyproject.toml apps/frontend apps/order-simulator packages docker .dockerignore deploy uv.lock
```

The wider showcase check — every path changed since the release must be one the showcase or the
documentation may touch. **Output must be empty:**

```bash
git diff --name-only 56c302366b3ddc0d824c1588a4a9ddbd193ed891 HEAD | grep -vE '^(showcase/|docs/[^/]+\.md$|docs/assets/|README\.md$|CLAUDE\.md$|\.gitignore$|\.github/workflows/showcase-pages\.yml$)'
```

Evidence, benchmarks and CI must be untouched by any showcase commit. **Output must be empty:**

```bash
git diff --name-only 5cc275f299e2436beffdbdbfe42db7384bf031e0 HEAD -- docs/effect-sets docs/benchmarks docs/rehearsals docs/adr scripts evals brand pyproject.toml .github/workflows/pr.yml .github/workflows/effect-sets.yml .gitleaks.toml
```

The frozen manifest still verifies:

```bash
uv run python scripts/verify_effect_set_manifest.py
```

And before any commit, the staging discipline from `CLAUDE.md`: explicit paths only, then
`git diff --cached --name-only` and `git diff --cached --stat`, confirming nothing outside the
phase's files is staged. The historical untracked artefacts stay untracked.

## 8. CI strategy

- **Existing CI is not weakened, edited or re-scoped.** `pr.yml` and `effect-sets.yml` stay
  byte-identical. Showcase commits will trigger both, because both run on every non-Markdown
  push; that is their designed behaviour and is accepted. The effect-set workflow is red on v1
  by design and a red run on a showcase commit means nothing new.
- **The showcase's own gate lives in `showcase-pages.yml`'s `build` job**, which runs
  `npm run check` before it uploads anything: typecheck, production build, `verify-content`,
  `verify-links`, `verify-assets`, `check-budgets`, and the Playwright suite (Chromium only,
  installed with `npx playwright install --with-deps chromium`). A failing check means no
  artefact and no deployment.
- **No network in CI checks.** The link gate reads the working tree; live URLs are checked by
  hand (§5), so a slow deployment or a GitHub hiccup never blocks a docs site.
- **Locally**, before every commit: `cd showcase && npm run check`, plus the three freeze
  commands in §7. The backend suite is irrelevant to showcase changes and is not run for them;
  the `fast-validate` skill's rule — run the smallest correct set and say what was skipped —
  applies, and what was skipped is the whole Python and product-frontend surface, because none
  of it changed.
- **Pull-request builds** are not added: work lands on `main` directly, as instructed, and the
  Pages workflow is push-only.

## 9. Commit boundaries

One-line Conventional Commit subjects, no body. Each commit is one phase, passes
`npm run check` for the parts that exist, and passes §7.

| Phase | Subject |
|---|---|
| P1 | `feat(showcase): scaffold the static site with tokens, fonts and brand assets` |
| P2 | `feat(showcase): add the header and every section's static content` |
| P3 | `feat(showcase): render the settled case, gate, traces and proof index at build time` |
| P4 | `feat(showcase): make the six promises, revalidation and architecture interactive` |
| P5 | `feat(showcase): port the three.js hero with svg, reduced-motion and no-js fallbacks` |
| P6 | `test(showcase): hold layout, accessibility and budgets across widths and fallbacks` |
| P7 | `test(showcase): gate content against repository sources and forbidden phrases` |
| P8 | `ci(showcase): deploy the showcase to GitHub Pages from main` |
| P9 | `docs(showcase): record the reference comparison and close the implementation` |

Tests may land with the phase they cover instead of in P6/P7 when that keeps a commit
self-checking; the subject then says so. Nothing is pushed until the owner asks.

## 10. Final acceptance criteria

The Pages site is done when **all** of the following are true, and not before:

1. `https://asembris.github.io/PromisePatch/` serves the showcase from a `showcase-pages`
   workflow run on `main`, and that run's `build` job passed `npm run check`.
2. Every section in `HANDOFF.md`'s page map is present in order, with the prototype's copy
   verbatim, and nothing else: no new section, visual concept or claim.
3. The hero matches the reference frames at t = 0.95, 4.3, 5.8 and 8.2 on desktop and mobile;
   the SVG fallback and reduced-motion states match their references; with JS off, the stage
   shows `hero-fallback.svg` and the page reads in full.
4. Every fact in `DO_NOT_CHANGE.md` appears exactly, with its caveat, and `verify-content` passes:
   release SHA `56c302366b3ddc0d824c1588a4a9ddbd193ed891` / `56c3023`, deployed `4529a802e34e`,
   `11/16` and `16/16` side by side as two results from two documents with their badges and no
   progression, 5/5 rehearsals as repeatability not a reliability rate, 0 of 2 in each, 9/10
   with its caveat, 13/13 on run `36310794944`, Telegram outbound only, consent by the signed web
   link, Telegram inbound deliberately unbuilt, the Alexa+-style experience simulated through
   MCP and not native, the order system simulated, no refusal path exercised live, and no
   production-safety claim.
5. Zero forbidden phrases; the deferred demo video and Devpost have no URL anywhere.
6. Every link resolves: internal anchors exist, doc targets exist on `main`, and the live app,
   CI run and repository links were checked by hand on the day of deployment.
7. No horizontal overflow from 320px to 1920px; axe reports no serious or critical issue;
   keyboard-only use reaches every control; Lighthouse mobile ≥ 95 performance and accessibility;
   total JS ≤ 200 KB gz, three ≤ 150 KB gz and loaded after first paint; CLS < 0.05.
8. No runtime request leaves the Pages origin: no Google Fonts, no unpkg, no CDN, no call to the
   live app.
9. All three freeze checks in §7 print nothing; `pr.yml` and `effect-sets.yml` are byte-identical
   to `5cc275f`; the frozen manifest verifies; the release facts — repository `56c3023`, deployed
   `4529a802e34e` — are unchanged and still the ones the page states.
10. `.handoff/` is not tracked, and no handoff file other than the two assets in §1.7 was copied
    into the repository.
11. This document's status line is updated to say what shipped, which three.js version, and every
    deviation from the references with its reason.

## 11. Not done in this session

No HTML, CSS or JavaScript was written. Three.js was not added. No workflow was created. No asset
was copied. GitHub Pages was not enabled. Nothing was deployed or pushed. No product path, CI
workflow, evidence document or benchmark file was touched. The only changes are `.gitignore`
(ignore `.handoff/`) and this plan.
