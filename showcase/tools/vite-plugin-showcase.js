// Build-time glue for the showcase. Four jobs, nothing else:
//
// 0. Replace `<!-- @render:<name> -->` markers in index.html with the settled
//    default of that region, from the same pure renderers the page runs at
//    runtime (src/render/), and `{{fact.<key>}}` tokens with src/data/facts.js
//    values. An unknown marker or fact fails the build.
// 1. Copy the three brand SVGs from the repository's `brand/` folder into the
//    build, byte-for-byte, plus `favicon.svg` (a copy of the on-dark icon).
//    They are never committed a second time under `showcase/`.
// 2. Ship THIRD_PARTY_NOTICES.md beside the page.
// 3. Preload the display face (Instrument Sans 600, Latin) by its emitted,
//    hashed file name.
//
// The build reads nothing else outside `showcase/` and writes nothing outside
// `showcase/dist/`.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { SECTIONS } from '../src/render/index.js';
import { FACTS } from '../src/data/facts.js';

const here = dirname(fileURLToPath(import.meta.url));
const BRAND_DIR = resolve(here, '../../brand');

/** Published path → repository source file name in `brand/`. */
export const BRAND_FILES = {
  'brand/promisepatch-logo-on-dark.svg': 'promisepatch-logo-on-dark.svg',
  'brand/promisepatch-icon-on-dark.svg': 'promisepatch-icon-on-dark.svg',
  'brand/promisepatch-icon-monochrome.svg': 'promisepatch-icon-monochrome.svg',
  'favicon.svg': 'promisepatch-icon-on-dark.svg',
};

const MARKER = /<!--\s*@render:([\w-]+)\s*-->/g;
const FACT = /\{\{fact\.(\w+)\}\}/g;

/** Inject the settled defaults and the facts. Pure: string in, string out. */
export function renderIndex(html) {
  return html
    .replace(MARKER, (_, name) => {
      if (!SECTIONS[name]) throw new Error(`unknown render marker @render:${name}`);
      return SECTIONS[name]();
    })
    .replace(FACT, (_, key) => {
      if (!FACTS[key]) throw new Error(`unknown fact {{fact.${key}}}`);
      return FACTS[key].value;
    });
}

const DISPLAY_FONT = /instrument-sans-latin-600-normal-[\w-]+\.woff2$/;

/** @returns {import('vite').Plugin} */
export default function showcase() {
  let base = '/';
  return {
    name: 'promisepatch-showcase',

    configResolved(config) {
      base = config.base;
    },

    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url || '').split('?')[0];
        if (!path.startsWith(base)) return next();
        const source = BRAND_FILES[path.slice(base.length)];
        if (!source) return next();
        res.setHeader('Content-Type', 'image/svg+xml');
        res.end(readFileSync(resolve(BRAND_DIR, source)));
      });
    },

    generateBundle() {
      for (const [fileName, source] of Object.entries(BRAND_FILES)) {
        this.emitFile({ type: 'asset', fileName, source: readFileSync(resolve(BRAND_DIR, source)) });
      }
      this.emitFile({
        type: 'asset',
        fileName: 'THIRD_PARTY_NOTICES.md',
        source: readFileSync(resolve(here, '../THIRD_PARTY_NOTICES.md')),
      });
    },

    transformIndexHtml: {
      order: 'pre',
      handler: (html) => renderIndex(html),
    },
  };
}

/** @returns {import('vite').Plugin} */
export function showcasePreload() {
  let base = '/';
  return {
    name: 'promisepatch-showcase-preload',

    configResolved(config) {
      base = config.base;
    },

    transformIndexHtml: {
      order: 'post',
      handler(_html, ctx) {
        if (!ctx.bundle) return [];
        const font = Object.keys(ctx.bundle).find((name) => DISPLAY_FONT.test(name));
        if (!font) {
          this.error('display font not found in the bundle; the preload cannot be emitted');
        }
        return [
          {
            tag: 'link',
            attrs: { rel: 'preload', href: base + font, as: 'font', type: 'font/woff2', crossorigin: '' },
            injectTo: 'head',
          },
        ];
      },
    },
  };
}
