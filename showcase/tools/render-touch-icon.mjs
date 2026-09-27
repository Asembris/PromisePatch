// One-off: render public/apple-touch-icon.png (180 × 180 on #111A2B) from the
// repository's brand/promisepatch-icon-on-dark.svg with a local headless
// Chromium-family browser. The PNG is committed; this runs only when the brand
// icon changes. No image library is added.
//
//   CHROMIUM=/path/to/chrome-or-msedge node tools/render-touch-icon.mjs

import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const icon = resolve(here, '../../brand/promisepatch-icon-on-dark.svg');
const out = resolve(here, '../public/apple-touch-icon.png');
const browser = process.env.CHROMIUM;

if (!browser || !existsSync(browser)) {
  console.error('Set CHROMIUM to a local Chrome or Edge executable.');
  process.exit(1);
}

const svg = readFileSync(icon, 'utf8');
const work = mkdtempSync(join(tmpdir(), 'pp-touch-icon-'));
const page = join(work, 'icon.html');
writeFileSync(
  page,
  `<!doctype html><html><head><style>
html,body{margin:0;width:180px;height:180px;background:#111A2B;overflow:hidden}
body{display:flex;align-items:center;justify-content:center}
body>svg{width:144px;height:144px}
</style></head><body>${svg}</body></html>`,
);

try {
  execFileSync(browser, [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    '--force-device-scale-factor=1',
    '--default-background-color=111A2BFF',
    '--window-size=180,180',
    `--user-data-dir=${join(work, 'profile')}`,
    `--screenshot=${out}`,
    pathToFileURL(page).href,
  ], { stdio: 'inherit' });
} finally {
  rmSync(work, { recursive: true, force: true });
}

console.log(`wrote ${out}`);
