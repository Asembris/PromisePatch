// Checks the production build in dist/ against the performance budgets:
//  - the lazy three.js hero chunk (three-renderer-*.js) is at most 150 KB gzipped;
//  - all JavaScript the site ships is at most 200 KB gzipped;
//  - the entry chunk does not import three statically (three stays lazy).
// Sizes are gzip level 9 of the built files, in KB of 1000 bytes, the unit
// Vite reports.
//
//   npm run build && npm run check:budgets

import { gzipSync } from 'node:zlib';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const THREE_BUDGET_KB = 150;
const TOTAL_JS_BUDGET_KB = 200;

const here = dirname(fileURLToPath(import.meta.url));
const assets = resolve(here, '../dist/assets');
if (!existsSync(assets)) {
  console.error('dist/assets does not exist; run the build first.');
  process.exit(1);
}

const kb = (bytes) => bytes / 1000;
const js = readdirSync(assets)
  .filter((name) => name.endsWith('.js'))
  .map((name) => {
    const bytes = readFileSync(join(assets, name));
    return { name, raw: bytes.length, gz: gzipSync(bytes, { level: 9 }).length, text: bytes.toString('utf8') };
  });

const failures = [];
const three = js.filter((f) => f.name.startsWith('three-renderer-'));
if (three.length !== 1) failures.push(`expected one three-renderer chunk, found ${three.length}`);
const entries = js.filter((f) => !f.name.startsWith('three-renderer-'));
for (const f of entries) {
  if (three.some((t) => new RegExp(`^import[^;]*${t.name.replace(/[.$]/g, '\\$&')}`, 'm').test(f.text))) {
    failures.push(`${f.name} imports ${three[0].name} statically`);
  }
}

const total = js.reduce((sum, f) => sum + f.gz, 0);
for (const f of js) console.log(`  ${f.name.padEnd(34)} ${kb(f.raw).toFixed(2).padStart(8)} KB  gzip ${kb(f.gz).toFixed(2).padStart(7)} KB`);
const threeGz = three.reduce((sum, f) => sum + f.gz, 0);
console.log(`  three.js hero chunk: ${kb(threeGz).toFixed(2)} KB gz (budget ${THREE_BUDGET_KB})`);
console.log(`  total JavaScript:    ${kb(total).toFixed(2)} KB gz (budget ${TOTAL_JS_BUDGET_KB})`);

if (kb(threeGz) > THREE_BUDGET_KB) failures.push(`three.js chunk ${kb(threeGz).toFixed(2)} KB gz exceeds ${THREE_BUDGET_KB} KB`);
if (kb(total) > TOTAL_JS_BUDGET_KB) failures.push(`total JavaScript ${kb(total).toFixed(2)} KB gz exceeds ${TOTAL_JS_BUDGET_KB} KB`);

if (failures.length) {
  console.error(`check-budgets: ${failures.length} failure(s)`);
  for (const failure of failures) console.error(`  ${failure}`);
  process.exit(1);
}
console.log('check-budgets: within budget; three.js is only in its lazy chunk');
