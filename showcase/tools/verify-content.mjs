// Content gate over the production page and every string the page can render
// at runtime. Offline; reads dist/index.html, src/data and the renderers.
//
//  - every frozen fact in src/data/facts.js appears byte-exact, with its
//    caveats nearby, and every cited source path exists in the repository;
//  - 11/16 and 16/16 may each appear wherever they are labelled as their own
//    result, but nothing may join them as a progression: no arrow between the
//    two scores, no "improved", "now", "from … to", before/after framing, and
//    no "benchmark scored 16/16". A link arrow ("First scored run →") is not a
//    progression and is allowed;
//  - product boundaries: Telegram is outbound only, the signed web link is the
//    consent entry, the order system is labelled simulated, Alexa+ is not
//    native, no refusal is claimed live, the illustration is labelled;
//  - forbidden phrases, case-insensitive, unless inside an explicit negation;
//  - deferred items carry aria-disabled and no href; Devpost is absent.
//
// The rules themselves live in tools/content-rules.mjs, which the Playwright
// suite also runs over the live, JavaScript-rendered DOM.
//
//   npm run build && npm run verify:content      (or: node tools/verify-content.mjs <page.html>)

import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { FACTS, BOUNDARIES } from '../src/data/facts.js';
import { checkContent } from './content-rules.mjs';
import * as data from './runtime-strings.mjs';

export { textOf } from './content-rules.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../..');
const distIndex = process.argv[2] ? resolve(process.argv[2]) : resolve(here, '../dist/index.html');

if (!existsSync(distIndex)) {
  console.error('dist/index.html does not exist; run the build first.');
  process.exit(1);
}

const html = readFileSync(distIndex, 'utf8');
const failures = checkContent({ html, extra: data.strings(), state: 'default' });

// Every cited source path exists in the repository.
for (const [key, entry] of Object.entries({ ...FACTS, ...BOUNDARIES })) {
  for (const source of entry.source) {
    if (/^https?:/.test(source)) continue;
    for (const part of source.split(' … ')) {
      const path = part.replace(/\s+(§.*|\(.*\))$/, '').trim();
      if (!existsSync(resolve(repo, path))) failures.push(`${key}: source ${path} does not exist in the repository`);
    }
  }
}

if (failures.length) {
  console.error(`verify-content: ${failures.length} failure(s)`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log(`verify-content: ${Object.keys(FACTS).length} facts with caveats and sources, ${Object.keys(BOUNDARIES).length} boundaries, progression and forbidden-phrase rules pass over the page and ${data.strings().length} runtime strings`);
