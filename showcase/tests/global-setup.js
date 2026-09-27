// The suite tests the production build. Refuse to run against a missing one
// rather than silently testing whatever `vite preview` finds.

import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export default function globalSetup() {
  const index = resolve(dirname(fileURLToPath(import.meta.url)), '../dist/index.html');
  if (!existsSync(index)) {
    throw new Error('dist/index.html does not exist; run `npm run build` first (or `npm run check`).');
  }
}
