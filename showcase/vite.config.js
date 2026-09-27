import { defineConfig } from 'vite';
import showcase from './tools/vite-plugin-showcase.js';

// GitHub Pages serves the site from https://asembris.github.io/PromisePatch/.
// SHOWCASE_BASE=/ previews it at the server root instead.
const base = process.env.SHOWCASE_BASE || '/PromisePatch/';

export default defineConfig({
  base,
  plugins: [showcase()],
  build: {
    target: 'es2020',
    outDir: 'dist',
    emptyOutDir: true,
    assetsInlineLimit: 0,
  },
});
