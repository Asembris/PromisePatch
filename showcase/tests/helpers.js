// Shared helpers for the showcase suite. No assertions about content live
// here; the content rules are tools/content-rules.mjs, shared with the build gate.

import { expect } from '@playwright/test';

/** Plan §5 width matrix. */
export const WIDTHS = [320, 360, 390, 414, 640, 768, 1000, 1024, 1079, 1080, 1280, 1440, 1578, 1920];

export const HERO_PHASE_ENDS = [0.35, 1.25, 2.3, 3.25, 4.9, 8.2];

/**
 * Collect console errors and uncaught page errors for the life of the page.
 * @param {import('@playwright/test').Page} page
 */
export function trackErrors(page) {
  const errors = [];
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(`console: ${m.text()}`);
  });
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  return errors;
}

/**
 * Open the page (relative to the /PromisePatch/ base) and, with JS on, wait
 * until the hero has a renderer drawing.
 * @param {import('@playwright/test').Page} page
 * @param {{ query?: string, hero?: boolean }} [opts]
 */
export async function openPage(page, { query = '', hero = true } = {}) {
  await page.goto(`./${query}`);
  if (hero) await waitHero(page);
}

/** @param {import('@playwright/test').Page} page */
export async function waitHero(page, timeout = 15_000) {
  await page.waitForFunction(() => window.__ppHero && window.__ppHero.renderer !== 'none', null, { timeout });
}

/** Text of a hero overlay label's text target (`data-t`) or anchor. */
export async function heroLabel(page, key) {
  return page.evaluate((k) => {
    const el = document.querySelector(`.hero__overlay [data-k="${k}"]`);
    if (!el) return null;
    const t = el.querySelector('[data-t]') || el.querySelector('[data-a]');
    // The target opacity the scene set; the computed value may be mid-transition (300 ms).
    return { text: (t?.textContent || '').trim(), all: el.textContent.trim(), opacity: Number(el.style.opacity || 0) };
  }, key);
}

/** Seek the hero deterministically and return the phase index. */
export async function seek(page, t) {
  return page.evaluate((x) => window.__ppHero.seek(x), t);
}

/** Hero time is not exposed; the caption and the pressed step are its public state. */
export async function heroCaption(page) {
  return (await page.locator('[data-hero-caption]').textContent()).trim();
}

/**
 * Bring every reveal block and the gate into view once, pausing on each so
 * their observers fire (a fast programmatic scroll can skip an intersection).
 */
export async function scrollThrough(page) {
  const targets = await page.locator('[data-reveal], [data-gate]').all();
  for (const t of targets) {
    await t.evaluate((el) => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
    await page.waitForTimeout(120);
  }
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
}

/** Wait until the recorded gate has finished its ten checks. */
export async function waitGateSettled(page, verdict = 'PROCEED') {
  await expect(page.locator('#revalidate .outcome__verdict')).toHaveText(verdict, { timeout: 10_000 });
}

/** True when an element is rendered and not clipped away as visually-hidden. */
export async function isShown(locator) {
  return locator.evaluate((el) => {
    if (!el.checkVisibility({ opacityProperty: false, visibilityProperty: true })) return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  });
}

/**
 * "three.js after first paint" is asserted against the first rendered frame,
 * recorded in-page (rAF, then a task after it). The paint entries are not
 * used for this: they carry the frame's presentation time, which on this
 * machine's software renderer trails the rendered frame by up to ~55 ms.
 */
/** Install before navigation: records when the first frame was rendered. */
export async function recordFirstFrame(page) {
  await page.addInitScript(() => {
    requestAnimationFrame(() => setTimeout(() => { window.__firstFrameDone = performance.now(); }, 0));
  });
}

export async function paintTiming(page) {
  return page.evaluate(() => {
    const paint = Object.fromEntries(performance.getEntriesByType('paint').map((e) => [e.name, e.startTime]));
    const three = performance.getEntriesByType('resource').find((e) => /three-renderer-/.test(e.name));
    return { fp: paint['first-paint'], fcp: paint['first-contentful-paint'], three: three?.startTime, firstFrame: window.__firstFrameDone };
  });
}

/** @param {Awaited<ReturnType<typeof paintTiming>>} t */
export function expectThreeAfterFirstPaint(t) {
  expect(t.fp, 'first paint recorded').toBeGreaterThan(0);
  expect(t.three, 'three.js requested').toBeGreaterThan(0);
  expect(t.firstFrame, 'first frame recorded').toBeGreaterThan(0);
  expect(t.three, 'three.js requested after the first rendered frame').toBeGreaterThanOrEqual(t.firstFrame);
}
