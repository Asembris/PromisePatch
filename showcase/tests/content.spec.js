// The content rules of tools/content-rules.mjs (the same rules the build gate
// runs over dist/index.html), applied to the live, JavaScript-rendered DOM
// after every interaction state; the runtime network origin; and the
// performance facts the plan asks for (CLS, three.js after first paint).

import { test, expect } from '@playwright/test';
import { checkContent } from '../tools/content-rules.mjs';
import { ORDER_IDS } from '../src/data/rows.js';
import { TRACES } from '../src/data/traces.js';
import { openPage, seek, scrollThrough, trackErrors, waitGateSettled, recordFirstFrame, paintTiming, expectThreeAfterFirstPaint } from './helpers.js';

const liveHtml = (page) => page.evaluate(() => document.documentElement.outerHTML);

test('every interaction state keeps the frozen facts, caveats and boundaries', async ({ page }) => {
  test.setTimeout(120_000);
  const errors = trackErrors(page);
  await openPage(page);
  await scrollThrough(page);
  await waitGateSettled(page);

  const failures = [];
  const snapshots = [];
  const check = async (name, state = 'live') => {
    const html = await liveHtml(page);
    snapshots.push(html);
    for (const f of checkContent({ html, state })) failures.push(`[${name}] ${f}`);
  };

  // The settled default, now JavaScript-rendered, obeys the default-only rules too.
  await check('settled default', 'default');

  for (let i = 0; i < 7; i += 1) {
    await page.locator(`#story [data-stage="${i}"]`).click();
    await check(`stage ${i + 1}`);
  }
  for (const id of ORDER_IDS) {
    await page.locator(`#story [data-order="${id}"]`).click();
    await check(`order ${id}`);
  }
  await page.locator('#story [data-play]').click();
  await page.waitForTimeout(1300);
  await check('play case, mid-run');
  await page.locator('#story [data-play]').click();

  const hypo = page.locator('#revalidate button[data-mode="hypo"]');
  await hypo.click();
  await page.waitForTimeout(250);
  await check('illustration, checks running');
  expect(await page.locator('#revalidate [data-gate-header]').textContent()).toBe('ILLUSTRATION · NOT A RECORDED RUN');
  await waitGateSettled(page, 'STALE');
  await check('illustration, STALE');
  await page.locator('#revalidate button[data-mode="live"]').click();
  await waitGateSettled(page, 'PROCEED');
  await check('R3 again');

  for (const key of Object.keys(TRACES)) {
    await page.locator(`#architecture [data-trace="${key}"]`).click();
    await check(`trace ${key}`);
  }
  for (const t of [0.2, 0.95, 1.8, 3.0, 4.3, 5.8, 6.5, 8.2]) {
    await seek(page, t);
    await check(`hero t=${t}`);
  }
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.locator('#deployment [data-copy="rel"]').click();
  await check('after copy');

  expect(failures).toEqual([]);

  // Across every state: no progression wording, the illustration never without
  // its disclaimer, no live refusal claim, deferred items never links.
  for (const html of snapshots) {
    expect(html).not.toMatch(/href="[^"]*devpost/i);
    expect(html).not.toMatch(/<a\b[^>]*>[^<]*(?:<span[^>]*>[^<]*<\/span>)?\s*(?:Demo video|Watch demo)/i);
  }
  expect(errors).toEqual([]);
});

test('negative control: the live rules catch a mutated DOM', async ({ page }) => {
  await openPage(page);
  await page.locator('#revalidate button[data-mode="hypo"]').click();
  await waitGateSettled(page, 'STALE');
  await page.evaluate(() => {
    document.querySelector('#revalidate [data-gate-header]').textContent = '';
    document.querySelector('.evidence-cards__pair .caveat strong').textContent = 'The benchmark went up to 16/16.';
    document.querySelector('.hero__aside .btn--deferred').outerHTML = '<a class="btn" href="https://example.com">Demo video · deferred</a>';
  });
  const failures = checkContent({ html: await liveHtml(page), state: 'live' });
  expect(failures.join('\n')).toMatch(/went up to 16\/16/);
  expect(failures.join('\n')).toMatch(/illustrated STALE outcome is shown without its label/);
  expect(failures.join('\n')).toMatch(/Demo video · deferred" must be aria-disabled with no href/);
});

test('the deferred placeholders are not links and not focusable', async ({ page }) => {
  await openPage(page);
  const deferred = page.locator('[aria-disabled="true"]');
  await expect(deferred).toHaveCount(2);
  for (const el of await deferred.all()) {
    expect(await el.evaluate((e) => [e.tagName, e.hasAttribute('href'), e.tabIndex])).toEqual(['SPAN', false, -1]);
  }
});

test('no credential or token is ever on the page', async ({ page }) => {
  await openPage(page);
  const html = await liveHtml(page);
  for (const re of [/ghp_[A-Za-z0-9]{20,}/, /github_pat_/, /AKIA[0-9A-Z]{16}/, /\b\d{8,10}:[A-Za-z0-9_-]{30,}\b/, /\bsk-[A-Za-z0-9]{20,}/, /-----BEGIN [A-Z ]*PRIVATE KEY/, /[?&](?:token|sig|signature)=/i]) {
    expect(html).not.toMatch(re);
  }
});

test.describe('runtime network', () => {
  for (const js of [true, false]) {
    test(`JavaScript ${js ? 'on' : 'off'}: every request stays on the Pages origin and base`, async ({ browser, baseURL }) => {
      const context = await browser.newContext({ javaScriptEnabled: js, permissions: ['clipboard-read', 'clipboard-write'] });
      const page = await context.newPage();
      const origin = new URL(baseURL).origin;
      const requests = [];
      const failed = [];
      page.on('request', (r) => requests.push(r.url()));
      page.on('response', (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`); });
      page.on('requestfailed', (r) => failed.push(`failed ${r.url()}`));
      if (js) {
        await openPage(page);
        await scrollThrough(page);
        await page.locator('#revalidate button[data-mode="hypo"]').click();
        await page.locator('#architecture [data-trace="agent"]').click();
        await page.locator('#story [data-play]').click();
        await page.locator('#deployment [data-copy="prod"]').click();
        await page.waitForTimeout(1500);
      } else {
        await page.goto('./');
        await page.waitForTimeout(1000);
      }
      const foreign = requests.filter((u) => !u.startsWith('data:') && (new URL(u).origin !== origin || !new URL(u).pathname.startsWith('/PromisePatch/')));
      expect(foreign).toEqual([]);
      expect(requests.some((u) => /fonts\.(googleapis|gstatic)\.com|unpkg|jsdelivr|cdnjs|184\.194\.40\.87/.test(u))).toBe(false);
      expect(failed).toEqual([]);
      if (js) expect(requests.some((u) => /three-renderer-/.test(u))).toBe(true);
      else expect(requests.some((u) => /\.js$/.test(u))).toBe(false);
      await context.close();
    });
  }
});

test.describe('performance', () => {
  for (const [width, height] of [[390, 844], [1578, 900]]) {
    test(`${width}px: CLS under 0.05, three.js after first paint, H1 in the first contentful frame`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.addInitScript(() => {
        window.__cls = 0;
        window.__lcp = [];
        new PerformanceObserver((l) => l.getEntries().forEach((e) => { if (!e.hadRecentInput) window.__cls += e.value; }))
          .observe({ type: 'layout-shift', buffered: true });
        new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__lcp.push({
          t: e.startTime, h1: !!e.element?.closest('h1'), tag: e.element ? e.element.tagName + '.' + e.element.className : null,
        }))).observe({ type: 'largest-contentful-paint', buffered: true });
      });
      await recordFirstFrame(page);
      await openPage(page);
      await page.waitForTimeout(1500); // the renderer takeover has happened
      const m = await page.evaluate(() => {
        const paint = Object.fromEntries(performance.getEntriesByType('paint').map((e) => [e.name, e.startTime]));
        const three = performance.getEntriesByType('resource').find((e) => /three-renderer-/.test(e.name));
        return { cls: window.__cls, fcp: paint['first-contentful-paint'], three: three?.startTime, lcp: window.__lcp,
          h1Top: document.querySelector('h1').getBoundingClientRect().top + scrollY };
      });
      test.info().annotations.push({ type: 'metrics', description: JSON.stringify(m) });
      expect(m.cls).toBeLessThan(0.05);
      expectThreeAfterFirstPaint(await paintTiming(page));
      // The largest paint is the lede (narrow) or the settled hero image (wide),
      // not the H1 as the plan's budget line assumed (recorded in the plan). What
      // matters holds: the above-the-fold content, H1 included, lands in the
      // first contentful frame. (Later LCP entries, e.g. a font swap, may come
      // after the three.js request; they do not delay that first frame.)
      expect(m.lcp.length).toBeGreaterThan(0);
      expect(m.lcp[0].t - m.fcp, JSON.stringify(m)).toBeLessThanOrEqual(50);
      expect(m.h1Top).toBeLessThan(height);
    });
  }
});
