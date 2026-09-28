import { expect, test } from '@playwright/test';
import {
  FAKE_COMPANY_USER,
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

test('plays through the launcher and resets after reload and navigation', async ({
  page,
}) => {
  await stubAppDataBackend(page);
  await stubShellBackend(page);
  await stubConversationsApi(page);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await page.locator('a[href="/apps/tetris"]').first().click();
  await expect(page).toHaveURL(/\/apps\/tetris$/);
  const board = page.getByRole('region', { name: /게임 보드|Game board/ });
  const start = page.getByRole('button', { name: /게임 시작|Start game/ });
  const resume = page.getByRole('button', { name: /게임 재개|Resume game/ });
  await start.click();
  await expect(board).toBeFocused();
  await board.press('ArrowDown');
  await expect(page.getByTestId('tetris-score')).toHaveText('1');
  const beforeScroll = await page.evaluate(() => window.scrollY);
  await board.press('Space');
  await expect(page.getByTestId('tetris-score')).not.toHaveText('1');
  expect(await page.evaluate(() => window.scrollY)).toBe(beforeScroll);
  await board.press('KeyP');
  await expect(resume).toBeVisible();
  const paused = await board.innerHTML();
  await page.waitForTimeout(1100);
  expect(await board.innerHTML()).toBe(paused);
  await resume.click();
  await expect(board).toBeFocused();
  await page.evaluate(() => window.dispatchEvent(new Event('blur')));
  await expect(resume).toHaveCount(0);
  const beforeBlurFall = await board.innerHTML();
  await page.waitForTimeout(1100);
  expect(await board.innerHTML()).not.toBe(beforeBlurFall);
  await page.reload();
  await expect(start).toBeVisible();
  await expect(page.getByTestId('tetris-score')).toHaveText('0');
  await start.click();
  await board.press('Space');
  await page.goto('/');
  await page.locator('a[href="/apps/tetris"]').first().click();
  await expect(start).toBeVisible();
  await expect(page.getByTestId('tetris-score')).toHaveText('0');
  expect(errors).toEqual([]);
});

test('denies direct entry when the server bootstrap does not admit the app', async ({
  page,
}) => {
  await stubShellBackend(page, { enabledAppIds: ['home'] });
  await page.goto('/apps/tetris');
  await expect(
    page.getByRole('heading', { name: /접근 권한 없음|No access/ }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: /게임 시작|Start game/ }),
  ).toHaveCount(0);
});

test('ends a stacked game and restarts from an empty board', async ({
  page,
}) => {
  await stubAppDataBackend(page);
  await stubShellBackend(page);
  await stubConversationsApi(page);
  await page.goto('/apps/tetris');
  await page.getByRole('button', { name: /게임 시작|Start game/ }).click();
  const drop = page.getByRole('button', { name: /즉시 낙하|Drop instantly/ });
  for (let i = 0; i < 25 && (await drop.isEnabled()); i++) await drop.click();
  await expect(page.getByRole('status')).toHaveText(/게임 오버|Game over/);
  await expect(drop).toBeDisabled();
  await page.getByRole('button', { name: /다시 시작|Restart game/ }).click();
  await expect(page.getByTestId('tetris-score')).toHaveText('0');
  await expect(drop).toBeEnabled();
  const board = page.getByRole('region', { name: /게임 보드|Game board/ });
  await expect(board.locator('[data-cell]:not([data-cell=""])')).toHaveCount(4);
});

test.describe('narrow touch screens', () => {
  test.use({ hasTouch: true, viewport: { width: 360, height: 740 } });
  for (const locale of ['ko-KR', 'en-US'] as const) {
    test(`plays using screen buttons in ${locale} and both themes`, async ({
      page,
    }) => {
      await stubAppDataBackend(page);
      await stubShellBackend(page, { user: { ...FAKE_COMPANY_USER, locale } });
      await stubConversationsApi(page);
      await page.goto('/apps/tetris');
      const board = page.getByRole('region', { name: /게임 보드|Game board/ });
      await expect(board).toBeVisible();
      await page.getByRole('button', { name: /게임 시작|Start game/ }).tap();
      await page.getByRole('button', { name: /빠른 낙하|Soft drop/ }).tap();
      await expect(page.getByTestId('tetris-score')).toHaveText('1');
      await page.getByRole('button', { name: /블록 홀드|Hold block/ }).tap();
      await expect(
        page.getByRole('button', { name: /블록 홀드|Hold block/ }),
      ).toBeDisabled();
      await page
        .getByRole('button', { name: /즉시 낙하|Drop instantly/ })
        .tap();
      await expect(
        page.getByRole('button', { name: /블록 홀드|Hold block/ }),
      ).toBeEnabled();
      await page
        .getByRole('button', { name: /일시정지|Pause game/, exact: true })
        .tap();
      await page
        .getByRole('button', { name: /AI 플레이 켜기|Enable AI play/ })
        .tap();
      for (const theme of ['light', 'dark']) {
        await page.evaluate((value) => {
          document.documentElement.classList.toggle('dark', value === 'dark');
        }, theme);
        const box = await board.boundingBox();
        expect(box!.x).toBeGreaterThanOrEqual(0);
        expect(box!.x + box!.width).toBeLessThanOrEqual(360);
        const controls = page.getByRole('group', {
          name: /화면 조작|Screen controls/,
        });
        const controlsBox = await controls.boundingBox();
        expect(controlsBox!.x).toBeGreaterThanOrEqual(0);
        expect(controlsBox!.x + controlsBox!.width).toBeLessThanOrEqual(360);
        expect(controlsBox!.y + controlsBox!.height).toBeLessThanOrEqual(740);
        for (const button of await controls.getByRole('button').all()) {
          const buttonBox = await button.boundingBox();
          expect(buttonBox!.height).toBeGreaterThanOrEqual(44);
          expect(buttonBox!.x + buttonBox!.width).toBeLessThanOrEqual(360);
          expect(
            await button.evaluate(
              (element) => element.scrollWidth <= element.clientWidth,
            ),
          ).toBe(true);
        }
        await expect(page.getByTestId('tetris-score')).toBeInViewport();
        await expect(
          page.getByRole('img', { name: /다음 블록|Next block/ }),
        ).toBeInViewport();
        await page.screenshot({
          path: `test-results/tetris-${locale}-${theme}-narrow.png`,
          fullPage: true,
          animations: 'disabled',
        });
      }
    });
  }
});

test('AI keeps playing without focus and retries repeated failures until disabled', async ({
  page,
}) => {
  await stubAppDataBackend(page);
  await stubShellBackend(page);
  await stubConversationsApi(page);
  let finish!: () => void;
  const delayed = new Promise<void>((resolve) => {
    finish = resolve;
  });
  let calls = 0;
  await page.route('**/api/v1/tetris/decision', async (route) => {
    calls++;
    const body = route.request().postDataJSON();
    expect(body.board).toHaveLength(20);
    expect(body.candidates.length).toBeGreaterThan(0);
    expect(body.candidates.length).toBeLessThanOrEqual(32);
    expect(body.candidates[0]).toMatchObject({
      action: expect.any(String),
      cleared_lines: expect.any(Number),
      holes: expect.any(Number),
      max_height: expect.any(Number),
      aggregate_height: expect.any(Number),
      bumpiness: expect.any(Number),
      key_presses: expect.any(Number),
      piece: expect.any(String),
      uses_hold: expect.any(Boolean),
      follow_ups: expect.any(Array),
    });
    expect(
      body.candidates.every(
        (candidate: { follow_ups: unknown[] }) =>
          candidate.follow_ups.length <= 2,
      ),
    ).toBe(true);
    expect(typeof body.next).toBe('string');
    expect(body).not.toHaveProperty('queue');
    expect(body).not.toHaveProperty('model');
    if (calls === 1) {
      await delayed;
      await route.fulfill({ json: { action: 'down', latency_ms: 1200 } });
    } else {
      await route.fulfill({
        status: 502,
        json: { detail: 'AI decision failed.' },
      });
    }
  });
  await page.goto('/apps/tetris');
  const board = page.getByRole('region', { name: /게임 보드|Game board/ });
  await page
    .getByRole('button', { name: /AI 플레이 켜기|Enable AI play/ })
    .click();
  await page.getByRole('button', { name: /게임 시작|Start game/ }).click();
  const down = page.getByRole('button', { name: /빠른 낙하|Soft drop/ });
  await expect(down).toBeDisabled();
  await expect.poll(() => calls).toBe(1);
  // Move real DOM focus outside the game while a decision is pending.
  await page
    .getByRole('navigation')
    .first()
    .getByRole('button')
    .first()
    .focus();
  await page.evaluate(() => window.dispatchEvent(new Event('blur')));
  const initial = await board.innerHTML();
  await page.waitForTimeout(1200);
  expect(await board.innerHTML()).not.toBe(initial);
  expect(calls).toBe(1);
  finish();
  await expect(page.getByTestId('tetris-score')).toHaveText('1');
  await expect(
    page.getByRole('status').filter({ hasText: /AI 재시도|AI retrying/ }),
  ).toBeVisible();
  await expect.poll(() => calls, { timeout: 10000 }).toBeGreaterThanOrEqual(6);
  await expect(down).toBeDisabled();
  await expect(page.getByRole('status')).toHaveText(/AI 재시도|AI retrying/);
  await page
    .getByRole('button', { name: /AI 플레이 끄기|Disable AI play/ })
    .click();
  await expect(down).toBeEnabled();
  const stoppedAt = calls;
  const before = await board.innerHTML();
  await page.waitForTimeout(1100);
  expect(await board.innerHTML()).not.toBe(before);
  expect(calls).toBe(stoppedAt);
  await down.click();
  await expect(page.getByTestId('tetris-score')).toHaveText('2');
});

test('AI recovers after an invalid response and resumes controlling the fallen piece', async ({
  page,
}) => {
  await stubAppDataBackend(page);
  await stubShellBackend(page);
  await stubConversationsApi(page);
  const observedY: number[] = [];
  await page.route('**/api/v1/tetris/decision', async (route) => {
    observedY.push(route.request().postDataJSON().active.y);
    if (observedY.length === 1) {
      await route.fulfill({
        status: 502,
        json: { detail: 'Invalid decision response' },
      });
    } else {
      await route.fulfill({
        json: {
          action: observedY.length === 2 ? 'down' : 'wait',
          latency_ms: 0,
        },
      });
    }
  });
  await page.goto('/apps/tetris');
  await page
    .getByRole('button', { name: /AI 플레이 켜기|Enable AI play/ })
    .click();
  await page.getByRole('button', { name: /게임 시작|Start game/ }).click();
  await expect(
    page.getByRole('status').filter({ hasText: /AI 재시도|AI retrying/ }),
  ).toBeVisible();
  await expect(page.getByTestId('tetris-score')).toHaveText('1');
  expect(observedY[1]).toBeGreaterThan(observedY[0]);
  await expect(
    page.getByRole('button', { name: /AI 플레이 끄기|Disable AI play/ }),
  ).toBeVisible();
  await expect(
    page
      .getByRole('status')
      .filter({ hasText: /AI 오류|AI error|AI 재시도|AI retrying/ }),
  ).toHaveCount(0);
  await page
    .getByRole('button', { name: /AI 플레이 끄기|Disable AI play/ })
    .click();
});
