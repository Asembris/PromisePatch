// WebGL disabled in the browser itself (a launch option, so its own file and
// worker): the SVG renderer takes over and three.js is never requested.

import { test, expect } from '@playwright/test';
import { openPage, trackErrors } from './helpers.js';

test.use({ launchOptions: { args: ['--disable-webgl', '--disable-webgl2', '--disable-3d-apis'] } });

test('the SVG renderer takes over without three.js', async ({ page }) => {
  const errors = trackErrors(page);
  const threeRequests = [];
  page.on('request', (r) => { if (/three-renderer-/.test(r.url())) threeRequests.push(r.url()); });
  await openPage(page);

  expect(await page.evaluate(() => {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  })).toBe(false);
  expect(await page.evaluate(() => window.__ppHero.renderer)).toBe('svg');
  await expect(page.locator('[data-hero-label]')).toContainText('SVG FALLBACK');
  expect(threeRequests).toEqual([]);

  // Usable: a step works and the page's own sections still enhance.
  await page.locator('[data-hero-step="2"]').click();
  await expect(page.locator('[data-hero-step="2"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#story .stepper')).toBeVisible();
  expect(errors).toEqual([]);
});
