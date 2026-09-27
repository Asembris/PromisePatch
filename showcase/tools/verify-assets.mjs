// Checks the production build in dist/:
//  - every brand copy is byte-identical to its repository original in brand/;
//  - the byte-for-byte handoff assets are present;
//  - nothing the page loads comes from another origin: no Google Fonts, no
//    unpkg or other CDN, no Claude Design runtime, and no http(s) URL in any
//    src=, srcset= or CSS url(). Outbound links (<a href>, canonical, og:*)
//    are navigation, not requests, and are not checked here.
//
//   npm run build && npm run verify:assets

import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BRAND_FILES } from './vite-plugin-showcase.js';

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, '../dist');
const brand = resolve(here, '../../brand');
const failures = [];

const sha = (path) => createHash('sha256').update(readFileSync(path)).digest('hex');

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

if (!existsSync(dist)) {
  console.error('dist/ does not exist; run the build first.');
  process.exit(1);
}

for (const [published, source] of Object.entries(BRAND_FILES)) {
  const copy = join(dist, published);
  if (!existsSync(copy)) failures.push(`missing ${published}`);
  else if (sha(copy) !== sha(join(brand, source))) failures.push(`${published} differs from brand/${source}`);
}

for (const required of ['assets/hero-fallback.svg', 'assets/og-preview-1200x630.png', 'apple-touch-icon.png']) {
  if (!existsSync(join(dist, required))) failures.push(`missing ${required}`);
}

const FORBIDDEN = [
  /fonts\.googleapis\.com/i,
  /fonts\.gstatic\.com/i,
  /unpkg\.com/i,
  /cdn\.jsdelivr\.net/i,
  /cdnjs\.cloudflare\.com/i,
  /support\.js/i,
  /<x-dc\b/i,
  /DCLogic/,
  /text\/x-dc/i,
];
const REMOTE_LOAD = [
  /\b(?:src|srcset|poster|data)\s*=\s*["']?\s*(?:https?:)?\/\//i,
  /url\(\s*["']?\s*(?:https?:)?\/\//i,
  /@import\s+["']?\s*(?:url\()?\s*["']?(?:https?:)?\/\//i,
  /\bimport\s*\(\s*["'](?:https?:)?\/\//i,
];

for (const file of walk(dist)) {
  if (!/\.(html|css|js|mjs|svg|json|txt)$/i.test(file)) continue;
  const text = readFileSync(file, 'utf8');
  const name = relative(dist, file).replaceAll('\\', '/');
  for (const pattern of [...FORBIDDEN, ...REMOTE_LOAD]) {
    if (pattern.test(text)) failures.push(`${name}: matches ${pattern}`);
  }
}

if (failures.length) {
  console.error(`verify-assets: ${failures.length} failure(s)`);
  for (const failure of failures) console.error(`  ${failure}`);
  process.exit(1);
}
console.log('verify-assets: brand copies byte-identical; no external runtime origin in dist/');
