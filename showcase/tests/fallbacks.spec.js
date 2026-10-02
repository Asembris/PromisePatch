// Fallbacks: no JavaScript, a forced SVG renderer, WebGL disabled in the
// browser, and a three.js chunk that never arrives or fails. The stage is
// never blank, and no control is shown before it works.

import { test, expect } from '@playwright/test';
import { THREE_TIMEOUT_MS } from '../src/hero/constants.js';
import { openPage, seek, heroCaption, trackErrors, isShown, recordFirstFrame, paintTiming, expectThreeAfterFirstPaint } from './helpers.js';

const FINAL_CAPTION = '6 promises → 1 auto-recovered · 1 customer-approved · 2 owner-escalated · 2 untouched.';
const THREE_CHUNK = '**/assets/three-renderer-*.js';

/** Sample the stage: it must always show the fallback image or a drawn renderer. */
async function stageNeverBlank(page, ms, every = 100) {
  const blank = [];
  for (let t = 0; t < ms; t += every) {
    const state = await page.evaluate(() => {
      const st = document.querySelector('.hero__stage');
      const img = st.querySelector('.hero__fallback');
      const gl = st.querySelector('.hero__gl');
      return { img: !!img && img.checkVisibility(), drawn: !!gl && gl.childElementCount > 0 };
    });
    if (!state.img && !state.drawn) blank.push(t);
    await page.waitForTimeout(every);
  }
  return blank;
}

test.describe('no JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  for (const width of [390, 1440]) {
    test(`reads completely at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('./');

      // Hero: the settled image and caption; no controls, no overlay.
      await expect(page.locator('.hero__fallback')).toBeVisible();
      await expect(page.locator('[data-hero-controls]')).toBeHidden();
      await expect(page.locator('.hero__overlay')).toHaveCount(0);
      await expect(page.locator('[data-hero-caption]')).toHaveText(FINAL_CAPTION);

      // Six promises: the settled stage with order B, as plain text.
      await expect(page.locator('#story .stage-note__stage')).toHaveText('7 Settled');
      await expect(page.locator('#story .matrix__row')).toHaveCount(6);
      await expect(page.locator('#story .matrix button')).toHaveCount(0);
      await expect(page.locator('#story .detail__title')).toHaveText('Order B');
      await expect(page.locator('#story .matrix__row[data-row="E"] .cell').last()).toHaveText('○ UNTOUCHED');

      // Revalidation: the recorded R3 run, 10/10 PROCEED.
      await expect(page.locator('#revalidate .gate__header')).toHaveText('AUDIT 503–512 · SNAPSHOT 20:31:01.207Z');
      await expect(page.locator('#revalidate .check.is-pass')).toHaveCount(10);
      await expect(page.locator('#revalidate .outcome__verdict')).toHaveText('PROCEED');
      await expect(page.locator('#revalidate')).not.toContainText('ILLUSTRATION');

      // Architecture: the consent trace.
      await expect(page.locator('#architecture [data-trace-name]')).toHaveText('Customer consent');
      await expect(page.locator('#architecture [data-trace-text]')).toContainText('signed web link');
      expect(await isShown(page.locator(width >= 1080 ? '.arch-diagram' : '.chain'))).toBe(true);

      // Proof index and the rehearsal table.
      await expect(page.locator('#proof .proofs > li')).toHaveCount(13);
      await expect(page.locator('#evidence table.rehearsals tbody tr')).toHaveCount(5);

      // No dead controls: every button is hidden; every visible link navigates.
      const visibleButtons = await page.locator('button').evaluateAll((els) => els.filter((e) => e.checkVisibility()).length);
      expect(visibleButtons).toBe(0);
      const deadLinks = await page.locator('a').evaluateAll((els) =>
        els.filter((a) => a.checkVisibility() && !/^(#[\w-]+|https:\/\/)/.test(a.getAttribute('href') || '')).map((a) => a.outerHTML.slice(0, 80)));
      expect(deadLinks).toEqual([]);

      // Final CTA and navigation are plain links.
      await expect(page.locator('.final-cta a[href="https://184.194.40.87.sslip.io"]')).toBeVisible();
      await expect(page.locator('.final-cta a[href="#proof"]')).toBeVisible();
      if (width >= 1000) await expect(page.locator('.site-nav a')).toHaveCount(6);
      await page.locator('.final-cta a[href="#proof"]').click();
      await expect(page).toHaveURL(/#proof$/);
    });
  }
});

test.describe('forced SVG renderer', () => {
  test('?renderer=svg draws the SVG fallback with the same timeline', async ({ page }) => {
    const errors = trackErrors(page);
    const threeRequests = [];
    page.on('request', (r) => { if (/three-renderer-/.test(r.url())) threeRequests.push(r.url()); });
    await openPage(page, { query: '?renderer=svg' });

    expect(await page.evaluate(() => window.__ppHero.renderer)).toBe('svg');
    await expect(page.locator('[data-hero-label]')).toHaveText('HOLLOW OAK BAKERY · CANONICAL CASE · SVG FALLBACK');
    await expect(page.locator('.hero__fallback')).toHaveCount(0);
    await expect(page.locator('.hero__gl svg')).toHaveCount(1);
    await expect(page.locator('[data-hero-controls]')).toBeVisible();

    expect(await seek(page, 5.8)).toBe(5);
    await expect(page.locator('.hero__overlay [data-k="gate"] [data-t]')).toHaveText('5/10 checks');
    expect(await seek(page, 8.2)).toBe(6);
    expect(await heroCaption(page)).toBe(FINAL_CAPTION);
    await expect(page.locator('.hero__overlay [data-k="gate"] [data-t]')).toHaveText('10/10 · still valid');

    expect(threeRequests).toEqual([]);
    expect(errors).toEqual([]);
  });
});

test.describe('three.js chunk', () => {
  test('never arriving: the image stays, controls stay hidden, SVG starts at the timeout', async ({ page }) => {
    const errors = trackErrors(page);
    await page.route(THREE_CHUNK, () => { /* held forever */ });
    await page.goto('./', { waitUntil: 'domcontentloaded' });

    // Before the 4 s timeout: still the settled image, no renderer, no controls.
    await page.waitForTimeout(2500);
    expect(await page.evaluate(() => window.__ppHero.renderer)).toBe('none');
    await expect(page.locator('.hero__fallback')).toBeVisible();
    await expect(page.locator('[data-hero-controls]')).toBeHidden();

    const blank = await stageNeverBlank(page, 3000);
    expect(blank, 'moments the stage was blank').toEqual([]);

    await page.waitForFunction(() => window.__ppHero.renderer === 'svg', null, { timeout: 5000 });
    await expect(page.locator('[data-hero-controls]')).toBeVisible();
    await expect(page.locator('.hero__fallback')).toHaveCount(0);
    await expect(page.locator('[data-hero-label]')).toContainText('SVG FALLBACK');
    expect(errors.filter((e) => !/three-renderer/.test(e))).toEqual([]);
  });

  test('failing: SVG starts at once and the stage is never blank', async ({ page }) => {
    await page.route(THREE_CHUNK, (route) => route.abort('failed'));
    await page.goto('./', { waitUntil: 'domcontentloaded' });
    const blank = await stageNeverBlank(page, 1500);
    expect(blank).toEqual([]);
    await page.waitForFunction(() => window.__ppHero.renderer === 'svg', null, { timeout: 3000 });
    await expect(page.locator('[data-hero-controls]')).toBeVisible();
  });

  test('loading normally: WebGL renderer, requested only after first paint', async ({ page }) => {
    const errors = trackErrors(page);
    await recordFirstFrame(page);
    await openPage(page);
    // The renderer follows how long the chunk took: under the timeout, WebGL;
    // over it (seen here when this machine's loopback stalls for seconds), the
    // designed SVG takeover. Within half a second of the line either is right.
    const load = await page.evaluate(() => {
      const e = performance.getEntriesByType('resource').find((x) => /three-renderer-/.test(x.name));
      return e.responseEnd - e.startTime;
    });
    const renderer = await page.evaluate(() => window.__ppHero.renderer);
    test.info().annotations.push({ type: 'three chunk', description: `${Math.round(load)} ms → ${renderer}` });
    if (load < THREE_TIMEOUT_MS - 500) {
      expect(renderer).toBe('webgl');
      await expect(page.locator('[data-hero-label]')).toHaveText('HOLLOW OAK BAKERY · CANONICAL CASE · WEBGL');
    } else if (load > THREE_TIMEOUT_MS + 500) {
      expect(renderer).toBe('svg');
    }
    expectThreeAfterFirstPaint(await paintTiming(page));
    expect(errors).toEqual([]);
  });
});
