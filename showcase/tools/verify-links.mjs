// Link gate over the production page. Offline by design: it never fetches a
// URL, so the build never depends on the network or the live deployment.
//
//  - no <a href> is empty, "#", or TBD;
//  - an in-page anchor names an id that exists;
//  - an external href is one src/data/links.js lists;
//  - a `blob/main/<path>` target exists in this working tree, and the
//    README anchor exists as a README heading;
//  - canonical and social-preview URLs are the listed Pages URLs;
//  - nothing labelled deferred is a link.
//
//   npm run build && npm run verify:links      (or: node tools/verify-links.mjs <page.html>)

import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ALLOWED_URLS, LINKS, META_URLS, REPO } from '../src/data/links.js';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../..');
const distIndex = process.argv[2] ? resolve(process.argv[2]) : resolve(here, '../dist/index.html');
const failures = [];
const fail = (msg) => failures.push(msg);

if (!existsSync(distIndex)) {
  console.error('dist/index.html does not exist; run the build first.');
  process.exit(1);
}

const html = readFileSync(distIndex, 'utf8').replace(/<!--[\s\S]*?-->/g, '');
const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]));
const BLOB = `${REPO}/blob/main/`;

const slug = (heading) => heading.trim().toLowerCase().replace(/[^\w\- ]+/g, '').replace(/ /g, '-');
const readmeAnchors = new Set(
  readFileSync(resolve(repo, 'README.md'), 'utf8').split('\n').filter((l) => /^#{1,6} /.test(l)).map((l) => slug(l.replace(/^#+ /, ''))),
);

function checkExternal(href, where) {
  if (!ALLOWED_URLS.has(href)) {
    fail(`${where}: ${href} is not listed in src/data/links.js`);
    return;
  }
  if (href.startsWith(BLOB)) {
    const path = href.slice(BLOB.length).split('#')[0];
    if (!existsSync(resolve(repo, path))) fail(`${where}: ${path} does not exist in the repository`);
  } else if (href.startsWith(`${REPO}#`)) {
    const anchor = href.slice(REPO.length + 1);
    if (!readmeAnchors.has(anchor)) fail(`${where}: README has no heading for #${anchor}`);
  }
}

// Every listed link must resolve, used on the page or not.
for (const [key, url] of Object.entries(LINKS)) checkExternal(url, `links.js ${key}`);

let count = 0;
for (const m of html.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/gi)) {
  count += 1;
  const attrs = m[1];
  const label = m[2].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
  const href = attrs.match(/\shref="([^"]*)"/)?.[1];
  const where = `<a> "${label.slice(0, 40)}"`;
  if (/deferred/i.test(label)) fail(`${where}: a deferred item must not be a link`);
  if (href === undefined) {
    fail(`${where}: <a> without href`);
    continue;
  }
  const h = href.trim();
  if (!h || h === '#' || /\bTBD\b/i.test(h)) {
    fail(`${where}: empty, "#" or TBD href`);
  } else if (h.startsWith('#')) {
    if (!ids.has(h.slice(1))) fail(`${where}: #${h.slice(1)} is not an id on the page`);
  } else if (/^https?:\/\//.test(h)) {
    checkExternal(h, where);
  } else {
    fail(`${where}: unexpected relative href ${h}`);
  }
}

for (const m of html.matchAll(/<(?:link|meta)\b[^>]*(?:rel="canonical"|property="og:(?:url|image)"|name="twitter:image")[^>]*>/gi)) {
  const url = m[0].match(/(?:href|content)="([^"]+)"/)?.[1];
  if (!META_URLS.includes(url)) fail(`meta: ${url} is not a listed Pages URL`);
}

if (failures.length) {
  console.error(`verify-links: ${failures.length} failure(s)`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log(`verify-links: ${count} links on the page and ${Object.keys(LINKS).length} listed links resolve offline; no empty, "#", TBD or deferred href`);
