// The hero through its deterministic QA hook, keyboard, reduced motion and
// pausing. Semantic state (phase, caption, tags, gate label, pressed step),
// not screenshots. Time itself is not exposed, so pausing is proved through
// the phase the hero reaches and through label positions.

import { test, expect } from '@playwright/test';
import { CAPTIONS } from '../src/hero/constants.js';
import { openPage, seek, heroLabel, heroCaption, trackErrors } from './helpers.js';

const tag = async (page, id) => (await heroLabel(page, `t${id}`));
const tagText = async (page, id) => {
  const l = await tag(page, id);
  return l.opacity > 0 ? l.text : '';
};
const nodeTransform = (page, id) => page.locator(`.hero__overlay [data-k="n${id}"]`).evaluate((el) => el.style.transform);
const pressedStep = (page) => page.locator('[data-hero-step][aria-pressed="true"]').evaluateAll((els) => els.map((e) => Number(e.dataset.heroStep)));

test.describe('seek(t) states', () => {
  for (const [width, mobile] of [[1578, false], [390, true]]) {
    test(`at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const errors = trackErrors(page);
      await openPage(page);

      // 0.95: the failure reaches A and B first; nothing is in a lane yet.
      expect(await seek(page, 0.95)).toBe(1);
      expect(await heroCaption(page)).toBe(CAPTIONS[1]);
      expect(await pressedStep(page)).toEqual([1]);
      expect(await tagText(page, 'A')).toBe('REACHED');
      expect(await tagText(page, 'B')).toBe('REACHED');
      expect(await tagText(page, 'E')).toBe('');
      expect(await tagText(page, 'F')).toBe('');
      expect((await heroLabel(page, 'l0')).opacity).toBe(0);

      // 4.3: A recovered, B's YES held, C and D with the owner, E and F untouched; lanes shown.
      expect(await seek(page, 4.3)).toBe(4);
      expect(await heroCaption(page)).toBe(CAPTIONS[4]);
      expect(await tagText(page, 'A')).toBe('RECOVERED ✓');
      expect(await tagText(page, 'B')).toBe('YES · HELD');
      expect(await tagText(page, 'C')).toBe('OWNER');
      expect(await tagText(page, 'D')).toBe('OWNER');
      expect(await tagText(page, 'E')).toBe('UNTOUCHED');
      expect(await tagText(page, 'F')).toBe('UNTOUCHED');
      for (const [k, text] of [['l0', '● AUTO'], ['l1', '◆ ASK'], ['l2', '■ BLOCKED'], ['l3', '○ UNAFFECTED']]) {
        const l = await heroLabel(page, k);
        expect(l.all).toContain(text);
        expect(l.opacity).toBe(1);
      }
      expect((await heroLabel(page, 'cust')).opacity).toBeGreaterThan(0.9);
      expect((await heroLabel(page, 'gate')).opacity).toBe(0);

      // 5.8: revalidating, five of ten checks lit.
      expect(await seek(page, 5.8)).toBe(5);
      expect(await tagText(page, 'B')).toBe('REVALIDATING');
      const gate = await heroLabel(page, 'gate');
      expect(gate.all).toContain('REVALIDATE');
      expect(gate.text).toBe('5/10 checks');
      expect(gate.opacity).toBe(1);

      // 8.2: settled; the final caption; E and F never moved.
      expect(await seek(page, 8.2)).toBe(6);
      expect(await heroCaption(page)).toBe(CAPTIONS[6]);
      expect(await pressedStep(page)).toEqual([]);
      expect(await tagText(page, 'B')).toBe('RECOVERED ✓');
      expect((await heroLabel(page, 'gate')).text).toBe(mobile ? '10/10 ✓' : '10/10 · still valid');
      expect(await tagText(page, 'E')).toBe('UNTOUCHED');
      expect(errors).toEqual([]);
    });
  }
});

test.describe('keyboard', () => {
  test('Tab reaches every hero control; Enter and Space operate them; focus stays visible', async ({ page }) => {
    await openPage(page);
    await page.locator('.hero__aside .btn--outline').focus();
    const reached = [];
    for (let i = 0; i < 12; i += 1) {
      await page.keyboard.press('Tab');
      const info = await page.evaluate(() => {
        const el = document.activeElement;
        const cs = getComputedStyle(el);
        return { step: el.dataset.heroStep ?? null, replay: el.hasAttribute('data-hero-replay'), pause: el.hasAttribute('data-hero-pause'),
          visible: el.matches(':focus-visible') && cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 2 };
      });
      if (info.step === null && !info.replay && !info.pause) continue;
      expect(info.visible, 'focus ring visible').toBe(true);
      reached.push(info.step ?? (info.replay ? 'replay' : 'pause'));
    }
    expect(reached).toEqual(['0', '1', '2', '3', '4', '5', 'replay', 'pause']);

    const step = (i) => page.locator(`[data-hero-step="${i}"]`);
    await step(3).focus();
    await page.keyboard.press('Enter');
    await expect(step(3)).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('[data-hero-caption]')).toHaveText(CAPTIONS[3]);
    await step(1).focus();
    await page.keyboard.press('Space');
    await expect(step(1)).toHaveAttribute('aria-pressed', 'true');

    // Pause and Play, by keyboard; the label changes, not aria-pressed.
    const pause = page.locator('[data-hero-pause]');
    await pause.focus();
    await page.keyboard.press('Enter');
    await expect(pause).toHaveAccessibleName(/Play/);
    await expect(pause).not.toHaveAttribute('aria-pressed');
    const held = await nodeTransform(page, 'A');
    const phaseHeld = await pressedStep(page);
    await page.waitForTimeout(900);
    expect(await nodeTransform(page, 'A')).toBe(held);
    expect(await pressedStep(page)).toEqual(phaseHeld);
    await page.keyboard.press('Space');
    await expect(pause).toHaveAccessibleName(/Pause/);

    // Replay: back to the first phase, playing.
    await page.locator('[data-hero-replay]').focus();
    await page.keyboard.press('Enter');
    await expect(step(0)).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('[data-hero-caption]')).toHaveText(CAPTIONS[1], { timeout: 3000 });
    await expect(page.locator('[data-hero-caption]')).toHaveText(CAPTIONS[6], { timeout: 12_000 });
  });
});

for (const [name, setup] of [
  ['system preference', async (page) => { await page.emulateMedia({ reducedMotion: 'reduce' }); await openPage(page); }],
  ['?motion=reduced', async (page) => { await openPage(page, { query: '?motion=reduced' }); }],
]) {
  test.describe(`reduced motion (${name})`, () => {
    test('opens settled, draws only on change, no parallax, steps jump to phase ends', async ({ page }) => {
      await page.addInitScript(() => {
        window.__rafCount = 0;
        const raf = window.requestAnimationFrame.bind(window);
        window.requestAnimationFrame = (cb) => { window.__rafCount += 1; return raf(cb); };
      });
      const errors = trackErrors(page);
      await setup(page);

      await expect(page.locator('[data-hero-caption]')).toHaveText(CAPTIONS[6]);
      expect(await tagText(page, 'B')).toBe('RECOVERED ✓');
      await expect(page.locator('[data-hero-pause]')).toBeHidden();
      await expect(page.locator('[data-hero-replay]')).toBeVisible();

      // No continuous animation: at most a handful of frames in a second.
      await page.waitForTimeout(400);
      const before = await page.evaluate(() => window.__rafCount);
      const positions = await nodeTransform(page, 'B');
      // No parallax: moving the pointer over the stage changes nothing.
      const box = await page.locator('.hero__stage').boundingBox();
      await page.mouse.move(box.x + 10, box.y + 10);
      await page.mouse.move(box.x + box.width - 10, box.y + box.height - 10, { steps: 8 });
      await page.waitForTimeout(1000);
      expect(await page.evaluate(() => window.__rafCount) - before).toBeLessThanOrEqual(3);
      expect(await nodeTransform(page, 'B')).toBe(positions);

      // Steps jump to each phase's end (06 to the settled end), deterministically.
      const expectations = [
        [0, CAPTIONS[0], ''], [1, CAPTIONS[1], 'REACHED'], [2, CAPTIONS[2], 'ASK'],
        [3, CAPTIONS[3], 'ASKING'], [4, CAPTIONS[4], 'YES · HELD'], [5, CAPTIONS[6], 'RECOVERED ✓'],
      ];
      for (const [i, caption, bTag] of expectations) {
        await page.locator(`[data-hero-step="${i}"]`).click();
        await expect(page.locator('[data-hero-caption]')).toHaveText(caption);
        expect(await tagText(page, 'B')).toBe(bTag);
      }
      await page.locator('[data-hero-step="4"]').click();
      // The jump is drawn on the next frame; wait for it before reading the label.
      await expect(page.locator('[data-hero-caption]')).toHaveText(CAPTIONS[4]);
      expect((await heroLabel(page, 'gate')).text).toBe('0/10 checks');
      expect(errors).toEqual([]);
    });
  });
}

test('a live change to reduced motion lands on the settled end, never mid-animation', async ({ page }) => {
  await openPage(page);
  await page.locator('[data-hero-step="2"]').click();
  await expect(page.locator('[data-hero-caption]')).toHaveText(CAPTIONS[2]);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(page.locator('[data-hero-caption]')).toHaveText(CAPTIONS[6]);
  expect(await tagText(page, 'A')).toBe('RECOVERED ✓');
  expect(await tagText(page, 'B')).toBe('RECOVERED ✓');
  expect((await heroLabel(page, 'gate')).text).toBe('10/10 · still valid');
  await expect(page.locator('[data-hero-pause]')).toBeHidden();
  const held = await nodeTransform(page, 'B');
  await page.waitForTimeout(600);
  expect(await nodeTransform(page, 'B')).toBe(held);

  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await expect(page.locator('[data-hero-pause]')).toBeVisible();
  await expect(page.locator('[data-hero-caption]')).toHaveText(CAPTIONS[6]);
});

test.describe('pausing', () => {
  test('off-screen, the timeline does not advance, and it resumes where it stopped', async ({ page }) => {
    await openPage(page);
    await page.locator('[data-hero-step="2"]').click(); // t = 1.25, playing
    await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }));
    await page.waitForTimeout(3500); // enough to reach phase 4 if it kept playing
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    await page.waitForTimeout(150);
    // Still in Partition: at most one capped frame (0.2 s) was added on return.
    expect(await pressedStep(page)).toEqual([2]);
    expect(await tagText(page, 'A')).toBe('AUTO');
    await expect(page.locator('[data-hero-caption]')).toHaveText(CAPTIONS[6], { timeout: 10_000 });
  });

  test('in a hidden document, the timeline does not advance', async ({ page }) => {
    await openPage(page);
    const setHidden = (hidden) => page.evaluate((h) => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (h ? 'hidden' : 'visible') });
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => h });
      document.dispatchEvent(new Event('visibilitychange'));
    }, hidden);
    await page.locator('[data-hero-step="2"]').click();
    await setHidden(true);
    await page.waitForTimeout(3500);
    await setHidden(false);
    await page.waitForTimeout(150);
    expect(await pressedStep(page)).toEqual([2]);
    expect(await tagText(page, 'A')).toBe('AUTO');
  });
});
