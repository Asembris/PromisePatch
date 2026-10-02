// The S2 interactive sections against their own data: six promises (stepper,
// Play case, orders A–F, detail, mobile current-stage form, keyboard, status),
// the revalidation gate (R3 and the labelled illustration), the architecture
// traces (only the traced path lights), and the Copy buttons.

import { test, expect } from '@playwright/test';
import { STAGES } from '../src/data/stages.js';
import { ROWS, ORDER_IDS } from '../src/data/rows.js';
import { DET } from '../src/data/detail.js';
import { FUTURE_TEXT } from '../src/data/cells.js';
import { CHECKS, GATE_MODES } from '../src/data/checks.js';
import { TRACES } from '../src/data/traces.js';
import { EDGES, EDGE_STYLE } from '../src/data/arch.js';
import { openPage, trackErrors, waitGateSettled } from './helpers.js';

const stage = (page, i) => page.locator(`#story [data-stage="${i}"]`);
const order = (page, id) => page.locator(`#story [data-order="${id}"]`);
const cellTexts = (page, id) => page.locator(`#story [data-row="${id}"] .cell`).allTextContents();

async function expectStage(page, i, { announced = true } = {}) {
  await expect(stage(page, i)).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#story [data-stage][aria-pressed="true"]')).toHaveCount(1);
  await expect(page.locator('#story [data-stage-note]')).toHaveText(STAGES[i].note);
  // Nothing is announced on load; every change is.
  await expect(page.locator('#story [data-story-status]')).toHaveText(announced ? `Stage ${i + 1} of 7, ${STAGES[i].name}. ${STAGES[i].note}` : '');
  for (const id of ORDER_IDS) {
    const expected = ROWS[id].map(([, text], c) => (c > i ? FUTURE_TEXT : text));
    expect(await cellTexts(page, id)).toEqual(expected);
  }
}

// Play case advances on a 1150 ms timer, so a stage read in many round trips
// can straddle a tick: the first rows read at one stage and the last at the
// next. Record every state the page renders instead, each taken in one piece:
// a MutationObserver callback runs only after the task that changed the DOM
// (setStage, which rewrites every cell at once) has finished.
async function recordStages(page) {
  await page.evaluate(() => {
    const section = document.getElementById('story');
    const snap = () => ({
      stage: Number(section.querySelector('[data-stage][aria-pressed="true"]')?.dataset.stage),
      pressed: section.querySelectorAll('[data-stage][aria-pressed="true"]').length,
      note: section.querySelector('[data-stage-note]').textContent,
      status: section.querySelector('[data-story-status]').textContent,
      cells: Object.fromEntries([...section.querySelectorAll('[data-row]')].map((row) =>
        [row.dataset.row, [...row.querySelectorAll('.cell')].map((c) => c.textContent)])),
    });
    // Log each change of stage from the one on screen now; other mutations
    // in the section (a reveal, a selected order) are not stages.
    const log = [];
    let last = snap().stage;
    window.__stageLog = log;
    new MutationObserver(() => {
      const s = snap();
      if (s.stage !== last) log.push(s);
      last = s.stage;
    }).observe(section, { subtree: true, attributes: true, childList: true, characterData: true });
  });
}

function expectSnapshot(s, i) {
  expect(s.stage).toBe(i);
  expect(s.pressed).toBe(1);
  expect(s.note).toBe(STAGES[i].note);
  expect(s.status).toBe(`Stage ${i + 1} of 7, ${STAGES[i].name}. ${STAGES[i].note}`);
  for (const id of ORDER_IDS) {
    expect(s.cells[id], `order ${id} at stage ${i}`).toEqual(ROWS[id].map(([, text], c) => (c > i ? FUTURE_TEXT : text)));
  }
}

test.describe('six promises', () => {
  test('stepper forward and back, by click and by keyboard', async ({ page }) => {
    const errors = trackErrors(page);
    await openPage(page);
    await expect(page.locator('#story .stepper')).toBeVisible();
    await expect(page.locator('#story .stage-note__stage')).toBeHidden();
    await expectStage(page, 6, { announced: false });
    for (const i of [0, 1, 4, 2]) {
      await stage(page, i).click();
      await expectStage(page, i);
    }
    await stage(page, 3).focus();
    await page.keyboard.press('Enter');
    await expectStage(page, 3);
    await stage(page, 5).focus();
    await page.keyboard.press('Space');
    await expectStage(page, 5);
    expect(errors).toEqual([]);
  });

  test('Play case steps through the stages, pauses, and stops at Settled', async ({ page }) => {
    await openPage(page);
    const play = page.locator('#story [data-play]');
    await expect(play).toHaveText('▶ Play case');
    await expect(play).not.toHaveAttribute('aria-pressed');
    await recordStages(page);
    await play.click();
    await expect(play).toHaveText('❚❚ Pause');
    // Starts at stage 0 and steps to 1, each stage whole when it rendered.
    await page.waitForFunction(() => window.__stageLog.some((s) => s.stage === 1));
    const first = await page.evaluate(() => window.__stageLog.slice(0, 2));
    expectSnapshot(first[0], 0);
    expectSnapshot(first[1], 1);
    await play.click(); // pause
    await expect(play).toHaveText('▶ Play case');
    const held = await page.locator('#story [data-stage][aria-pressed="true"]').getAttribute('data-stage');
    await page.waitForTimeout(1600);
    await expect(page.locator('#story [data-stage][aria-pressed="true"]')).toHaveAttribute('data-stage', held);
    await play.click();
    await expect(stage(page, 6)).toHaveAttribute('aria-pressed', 'true', { timeout: 12_000 });
    await expect(play).toHaveText('▶ Play case');
    await expectStage(page, 6);
    // Every stage the run rendered, before and after the pause, was whole,
    // and each run stepped one stage at a time: 0, 1, … up to where it was
    // paused, then 0 again (Play restarts) through 6.
    const log = await page.evaluate(() => window.__stageLog);
    log.forEach((s) => expectSnapshot(s, s.stage));
    const stages = log.map((s) => s.stage);
    const restart = stages.lastIndexOf(0);
    expect(restart).toBeGreaterThan(0);
    expect(stages.slice(0, restart)).toEqual([...Array(restart).keys()]);
    expect(stages.slice(restart)).toEqual([0, 1, 2, 3, 4, 5, 6]);
  });

  test('orders A–F select and fill the detail panel', async ({ page }) => {
    await openPage(page);
    await expect(order(page, 'B')).toHaveAttribute('aria-pressed', 'true');
    for (const id of ORDER_IDS) {
      await order(page, id).click();
      await expect(order(page, id)).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator('#story [data-order][aria-pressed="true"]')).toHaveCount(1);
      await expect(order(page, id)).toHaveAccessibleName(`Order ${id}, show details`);
      const d = DET[id];
      await expect(page.locator('#story .detail__title')).toHaveText(`Order ${id}`);
      await expect(page.locator('#story .detail .chip--lane')).toHaveText(`${d.glyph} ${d.lane}`);
      await expect(page.locator('#story .detail__list dd')).toHaveText([d.why, d.who, d.out, d.fx]);
    }
    await order(page, 'C').focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('#story .detail__title')).toHaveText('Order C');
    await expect(page.locator('#story [data-detail]')).toHaveAttribute('aria-live', 'polite');
  });

  test('below 640px each order shows only the current stage', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    await openPage(page);
    for (const i of [2, 4, 6]) {
      await stage(page, i).click();
      for (const id of ORDER_IDS) {
        const visible = await page.locator(`#story [data-row="${id}"] .cell`).evaluateAll(
          (els) => els.filter((e) => e.checkVisibility()).map((e) => e.textContent));
        expect(visible).toEqual([ROWS[id][i][1]]);
      }
    }
  });
});

test.describe('revalidation gate', () => {
  test('R3 by default, the labelled illustration on request, and back', async ({ page }) => {
    const errors = trackErrors(page);
    await openPage(page);
    const gate = page.locator('#revalidate [data-gate]');
    const live = page.locator('#revalidate button[data-mode="live"]');
    const hypo = page.locator('#revalidate button[data-mode="hypo"]');
    await gate.scrollIntoViewIfNeeded();
    await waitGateSettled(page, 'PROCEED');
    await expect(page.locator('#revalidate .check.is-pass')).toHaveCount(10);
    await expect(live).toHaveAttribute('aria-pressed', 'true');
    await expect(hypo).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('#revalidate [data-gate-header]')).toHaveText(GATE_MODES.live.header);
    await expect(page.locator('#revalidate .check__value')).toHaveText(CHECKS.map((c) => c[2]));
    await expect(page.locator('#revalidate [data-gate-status]')).toHaveText('Deployed rehearsal R3. 10 of 10 checks passed. Outcome PROCEED.');

    await hypo.click();
    await expect(hypo).toHaveAttribute('aria-pressed', 'true');
    await expect(live).toHaveAttribute('aria-pressed', 'false');
    // The label is there from the first moment, not only at the end.
    await expect(page.locator('#revalidate [data-gate-header]')).toHaveText('ILLUSTRATION · NOT A RECORDED RUN');
    await expect(page.locator('#revalidate [data-gate-note]')).toHaveText(GATE_MODES.hypo.note);
    await waitGateSettled(page, 'STALE');
    await expect(gate).toHaveAttribute('data-mode', 'hypo');
    await expect(page.locator('#revalidate .outcome')).toHaveClass(/is-stale/);
    await expect(page.locator('#revalidate .check.is-fail')).toHaveCount(1);
    await expect(page.locator('#revalidate .check').nth(4)).toHaveClass(/is-fail/);
    await expect(page.locator('#revalidate .check').nth(4).locator('.check__value')).toHaveText('no longer available');
    await expect(page.locator('#revalidate .outcome__sub')).toHaveText(GATE_MODES.hypo.sub);
    await expect(page.locator('#revalidate [data-gate-header]')).not.toContainText('AUDIT');
    await expect(page.locator('#revalidate [data-gate-status]')).toHaveText(/^Illustration, not a recorded run\./);

    await live.click();
    await expect(page.locator('#revalidate [data-gate-header]')).toHaveText(GATE_MODES.live.header);
    await waitGateSettled(page, 'PROCEED');
    await expect(page.locator('#revalidate .outcome')).toHaveClass(/is-proceed/);
    await expect(page.locator('#revalidate .check.is-fail')).toHaveCount(0);
    await expect(page.locator('#revalidate')).not.toContainText('ILLUSTRATION');
    expect(errors).toEqual([]);
  });

  test('under reduced motion both scenarios complete at once', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openPage(page);
    await expect(page.locator('#revalidate .outcome__verdict')).toHaveText('PROCEED');
    await page.locator('#revalidate button[data-mode="hypo"]').click();
    // Read synchronously after the click: no pending state in between.
    const now = await page.evaluate(() => ({
      verdict: document.querySelector('#revalidate .outcome__verdict').textContent,
      pending: document.querySelectorAll('#revalidate .check.is-pending').length,
    }));
    expect(now).toEqual({ verdict: 'STALE', pending: 0 });
    await page.locator('#revalidate button[data-mode="hypo"]').focus();
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Enter');
    await expect(page.locator('#revalidate .outcome__verdict')).toHaveText('PROCEED');
  });
});

test.describe('architecture traces', () => {
  const litEdges = (page) => page.locator('.arch-diagram [data-edge]').evaluateAll(
    (paths, lit) => paths.filter((p) => p.getAttribute('stroke') === lit).map((p) => p.dataset.edge),
    EDGE_STYLE.lit.stroke);

  test('every trace lights only its own path (diagram, 1440px)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const errors = trackErrors(page);
    await openPage(page);
    await expect(page.locator('#architecture .traces')).toBeVisible();
    expect((await litEdges(page)).sort()).toEqual([...TRACES.consent.e].sort());
    for (const [key, t] of Object.entries(TRACES)) {
      const btn = page.locator(`#architecture [data-trace="${key}"]`);
      await btn.click();
      await expect(btn).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator('#architecture [data-trace][aria-pressed="true"]')).toHaveCount(1);
      await expect(page.locator('#architecture [data-trace-name]')).toHaveText(t.label);
      await expect(page.locator('#architecture [data-trace-text]')).toHaveText(t.text);
      expect((await litEdges(page)).sort()).toEqual([...t.e].sort());
      const dim = await page.locator('.arch-diagram [data-edge]').evaluateAll(
        (paths, lit) => paths.filter((p) => p.getAttribute('stroke') !== lit).length, EDGE_STYLE.lit.stroke);
      expect(dim).toBe(EDGES.length - t.e.length);
    }
    expect(errors).toEqual([]);
  });

  test('stacked chain on mobile, trace text by keyboard', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    await openPage(page);
    await expect(page.locator('#architecture .chain')).toBeVisible();
    await expect(page.locator('#architecture .arch-diagram')).toBeHidden();
    await expect(page.locator('#architecture .traces')).toBeVisible();
    const btn = page.locator('#architecture [data-trace="model"]');
    await btn.focus();
    await page.keyboard.press('Enter');
    await expect(btn).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('#architecture [data-trace-text]')).toHaveText(TRACES.model.text);
    await page.locator('#architecture [data-trace="agent"]').focus();
    await page.keyboard.press('Space');
    await expect(page.locator('#architecture [data-trace-text]')).toHaveText(TRACES.agent.text);
  });
});

test.describe('copy buttons', () => {
  test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

  test('copy exactly the two public SHAs, and nothing else', async ({ page }) => {
    await openPage(page);
    const buttons = page.locator('#deployment [data-copy]');
    await expect(buttons).toHaveCount(2);
    for (const [key, value, name] of [
      ['prod', '740a062838e0', 'Deployed product SHA'],
      ['rel', '740a062838e0ea2620499abed27d653c42fc05f7', 'Repository release SHA'],
    ]) {
      const btn = page.locator(`#deployment [data-copy="${key}"]`);
      await expect(btn).toBeVisible();
      await btn.click();
      await expect(btn).toHaveText('Copied ✓');
      await expect(page.locator('#deployment [data-copy-status]')).toHaveText(`${name} copied.`);
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(value);
      await expect(btn).toHaveText('Copy', { timeout: 3000 });
    }
    // The copied values are the ones the page shows.
    await expect(page.locator('#deployment .sha-card__value--short')).toHaveText('740a062838e0');
    await expect(page.locator('#deployment .sha-card__value--long')).toHaveText('740a062838e0ea2620499abed27d653c42fc05f7');
  });
});
