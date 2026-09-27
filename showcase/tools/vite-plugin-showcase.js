// Build-time glue for the showcase. Three jobs, nothing else:
//
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

const here = dirname(fileURLToPath(import.meta.url));
const BRAND_DIR = resolve(here, '../../brand');

/** Published path → repository source file name in `brand/`. */
export const BRAND_FILES = {
  'brand/promisepatch-logo-on-dark.svg': 'promisepatch-logo-on-dark.svg',
  'brand/promisepatch-icon-on-dark.svg': 'promisepatch-icon-on-dark.svg',
  'brand/promisepatch-icon-monochrome.svg': 'promisepatch-icon-monochrome.svg',
  'favicon.svg': 'promisepatch-icon-on-dark.svg',
};

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
