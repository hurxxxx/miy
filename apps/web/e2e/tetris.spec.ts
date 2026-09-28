import {
  expect,
  test,
  type Page,
  type Locator,
  type Route,
} from '@playwright/test';
import {
  FAKE_COMPANY_USER,
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

const modelOptions = [
  {
    kind: 'decision',
    model_id: 'decision',
    name: 'Test decision',
    model_key: 'test/decision',
    provider: 'test',
    is_default: true,
  },
  {
    kind: 'generation',
    model_id: 'llm',
    name: 'Test LLM',
    model_key: 'test/llm',
    provider: 'test',
    is_default: true,
  },
];
const playerMode = (page: Page, player = 1) =>
  page.getByRole('combobox', {
    name: new RegExp(`^(플레이어 ${player}|Player ${player})$`),
  });
const playerPanel = (page: Page, player = 1) =>
  page.getByRole('region', {
    name: new RegExp(`^(플레이어 ${player}|Player ${player})$`),
  });
const playerBoard = (page: Page, player = 1) =>
  playerPanel(page, player).getByRole('region', {
    name: /게임 보드|Game board/,
  });
const aiStats = (page: Page) => page.getByTestId('tetris-ai-1');
async function solo(page: Page, mode: 'human' | 'ai' = 'human') {
  await playerMode(page, 2).selectOption('none');
  await playerMode(page).selectOption(mode);
}
test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/tetris/models', (route) =>
    route.fulfill({ json: { models: modelOptions } }),
  );
});

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
  await solo(page);
  const board = playerBoard(page);
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
  await solo(page);
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
  await solo(page);
  await page.getByRole('button', { name: /게임 시작|Start game/ }).click();
  await page
    .getByRole('button', { name: /화면 조작|Screen controls/, exact: true })
    .click();
  const drop = page.getByRole('button', { name: /즉시 낙하|Drop instantly/ });
  for (let i = 0; i < 25 && (await drop.isEnabled()); i++) await drop.click();
  await expect(page.getByRole('status')).toHaveText(/게임 오버|Game over/);
  await expect(drop).toBeDisabled();
  await page.getByRole('button', { name: /다시 시작|Restart game/ }).click();
  await expect(page.getByTestId('tetris-score')).toHaveText('0');
  await expect(drop).toBeEnabled();
  const board = playerBoard(page);
  await expect(board.locator('[data-cell]:not([data-cell=""])')).toHaveCount(4);
});

test.describe('narrow touch screens', () => {
  test.use({ hasTouch: true, viewport: { width: 360, height: 740 } });
  for (const locale of ['ko-KR', 'en-US'] as const) {
    test(`keeps both boards and scroll position stable as response times change in ${locale}`, async ({
      page,
    }) => {
      await stubAppDataBackend(page);
      await stubShellBackend(page, { user: { ...FAKE_COMPANY_USER, locale } });
      await stubConversationsApi(page);
      const pending: Route[] = [];
      await page.route('**/api/v1/tetris/decision', (route) => {
        pending.push(route);
      });
      await page.goto('/apps/tetris');
      await expect(
        page.getByRole('button', { name: /게임 시작|Start game/ }),
      ).toBeEnabled();
      await page.clock.install({ time: new Date('2026-09-28T00:00:00Z') });
      await page.clock.pauseAt(new Date('2026-09-28T00:00:01Z'));
      await page.getByRole('button', { name: /게임 시작|Start game/ }).click();
      await page.clock.runFor(1);
      const surface = page.locator('section[aria-labelledby="tetris-title"]');
      const measure = () =>
        surface.evaluate((element) => ({
          scrollTop: element.scrollTop,
          scrollLeft: element.scrollLeft,
          width: element.clientWidth,
          scrollWidth: element.scrollWidth,
          boards: Array.from(element.querySelectorAll('[role="region"]')).map(
            (board) => {
              const { x, y, width, height } = board.getBoundingClientRect();
              return { x, y, width, height };
            },
          ),
        }));
      for (const width of [360, 390]) {
        await page.setViewportSize({ width, height: 740 });
        await surface.evaluate((element) => {
          element.scrollTop = 100;
        });
        const before = await measure();
        expect(before.scrollWidth).toBeLessThanOrEqual(before.width);
        let previous = await aiStats(page).locator('dd').first().textContent();
        for (const delay of [99, 9900, 30000]) {
          await expect.poll(() => pending.length).toBe(2);
          await page.clock.runFor(delay);
          await Promise.all(
            pending.splice(0).map((route) =>
              route.fulfill({
                json: {
                  action: 'wait',
                  latency_ms: delay,
                  model: 'test/model-with-a-long-version-suffix',
                  provider: 'test',
                  kind: route.request().postDataJSON().model_choice.kind,
                },
              }),
            ),
          );
          await expect(aiStats(page).locator('dd').first()).toHaveText(
            /\d+ ms/,
          );
          await expect(aiStats(page).locator('dd').first()).not.toHaveText(
            previous ?? '',
          );
          previous = await aiStats(page).locator('dd').first().textContent();
          expect(await measure()).toEqual(before);
          for (const value of await page
            .locator('[data-testid^="tetris-ai-"] dd')
            .all()) {
            expect(
              await value.evaluate(
                (element) => element.scrollWidth <= element.clientWidth,
              ),
            ).toBe(true);
          }
          await page.clock.runFor(250);
        }
      }
      await page
        .getByRole('button', { name: /일시정지|Pause game/, exact: true })
        .click();
    });

    test(`plays using screen buttons in ${locale} and both themes`, async ({
      page,
    }) => {
      await stubAppDataBackend(page);
      await stubShellBackend(page, { user: { ...FAKE_COMPANY_USER, locale } });
      await stubConversationsApi(page);
      await page.goto('/apps/tetris');
      await solo(page);
      const board = playerBoard(page);
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
          playerPanel(page).getByRole('img', { name: /다음 블록|Next block/ }),
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
      await route.fulfill({
        json: {
          action: 'down',
          latency_ms: 1200,
          model: 'test/decision',
          provider: 'test',
          kind: 'decision',
        },
      });
    } else {
      await route.fulfill({
        status: 502,
        json: { detail: 'AI decision failed.' },
      });
    }
  });
  await page.goto('/apps/tetris');
  await solo(page, 'ai');
  const board = playerBoard(page);
  await expect(playerMode(page).locator('option[value=ai]')).toHaveJSProperty(
    'disabled',
    false,
  );
  await playerMode(page).selectOption('ai');
  await page.getByRole('button', { name: /게임 시작|Start game/ }).click();
  const down = page.getByRole('button', { name: /빠른 낙하|Soft drop/ });
  await expect(down).toHaveCount(0);
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
    aiStats(page).filter({ hasText: /AI 재시도|AI retrying/ }),
  ).toBeVisible();
  await expect.poll(() => calls, { timeout: 10000 }).toBeGreaterThanOrEqual(6);
  await expect(down).toHaveCount(0);
  await expect(aiStats(page)).toContainText(/AI 재시도|AI retrying/);
  await playerMode(page).selectOption('human');
  await page
    .getByRole('button', { name: /화면 조작|Screen controls/, exact: true })
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
      await page.waitForTimeout(600);
      await route.fulfill({
        status: 502,
        json: { detail: 'Invalid decision response' },
      });
    } else {
      await route.fulfill({
        json: {
          action: observedY.length === 2 ? 'down' : 'wait',
          latency_ms: 0,
          model: 'test/decision',
          provider: 'test',
          kind: 'decision',
        },
      });
    }
  });
  await page.goto('/apps/tetris');
  await solo(page, 'ai');
  await expect(playerMode(page).locator('option[value=ai]')).toHaveJSProperty(
    'disabled',
    false,
  );
  await playerMode(page).selectOption('ai');
  await page.getByRole('button', { name: /게임 시작|Start game/ }).click();
  await expect(
    aiStats(page).filter({ hasText: /AI 재시도|AI retrying/ }),
  ).toBeVisible();
  await expect(page.getByTestId('tetris-score')).toHaveText('1');
  expect(observedY[1]).toBeGreaterThan(observedY[0]);
  await expect(playerMode(page)).toHaveValue('ai');
  await expect(
    aiStats(page).filter({ hasText: /AI 오류|AI error|AI 재시도|AI retrying/ }),
  ).toHaveCount(0);
  await playerMode(page).selectOption('human');
});

test('defaults to AI versus AI with the decision and generation defaults and stops both on a duel loss', async ({
  page,
}) => {
  await stubAppDataBackend(page);
  await stubShellBackend(page);
  await stubConversationsApi(page);
  let finish!: () => void;
  const delayed = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const calls = { decision: 0, llm: 0 };
  await page.route('**/api/v1/tetris/decision', async (route) => {
    const body = route.request().postDataJSON();
    expect(body.opponent.board).toHaveLength(20);
    const id = body.model_choice.model_id as keyof typeof calls;
    calls[id]++;
    if (id === 'decision') await delayed;
    await route.fulfill({
      json: {
        action: 'drop',
        latency_ms: 5,
        model: `test/${id}`,
        provider: 'test',
        kind: body.model_choice.kind,
      },
    });
  });
  await page.goto('/apps/tetris');
  await expect(playerMode(page).locator('option[value=ai]')).toHaveJSProperty(
    'disabled',
    false,
  );
  await expect(playerMode(page)).toHaveValue('ai');
  await expect(playerMode(page, 2)).toHaveValue('ai');
  await expect(
    page.getByRole('combobox', {
      name: /플레이어 1 AI 모델|AI model for player 1/,
    }),
  ).toHaveValue('decision:decision');
  await expect(
    page.getByRole('combobox', {
      name: /플레이어 2 AI 모델|AI model for player 2/,
    }),
  ).toHaveValue('generation:llm');
  expect(calls).toEqual({ decision: 0, llm: 0 });
  await page.getByRole('button', { name: /게임 시작|Start game/ }).click();
  await expect(
    page.getByRole('region', { name: /게임 보드|Game board/ }),
  ).toHaveCount(2);
  await expect.poll(() => calls.llm).toBeGreaterThan(2);
  expect(calls.decision).toBe(1);
  await expect(page.getByTestId('tetris-ai-2')).toContainText('test/llm');
  await expect(
    page.getByTestId('tetris-ai-2').locator('dd').first(),
  ).toHaveText(/\d+ ms/);
  await expect(page.getByRole('status')).toHaveText(
    /플레이어 1 승리|Player 1 wins/,
    { timeout: 15000 },
  );
  const count = { ...calls };
  finish();
  await page.waitForTimeout(1100);
  expect(calls).toEqual(count);
});

test('loads new models dynamically and moves the human to player 2', async ({
  page,
}) => {
  await stubAppDataBackend(page);
  await stubShellBackend(page);
  await stubConversationsApi(page);
  await page.route('**/api/v1/tetris/decision', (route) =>
    route.fulfill({
      json: {
        action: 'wait',
        latency_ms: 1,
        model: 'test/decision',
        provider: 'test',
        kind: 'decision',
      },
    }),
  );
  await page.goto('/apps/tetris');
  await expect(playerMode(page).locator('option[value=ai]')).toHaveJSProperty(
    'disabled',
    false,
  );
  await playerMode(page).selectOption('ai');
  await playerMode(page, 2).selectOption('human');
  await expect(
    playerMode(page).locator('option[value=human]'),
  ).toHaveJSProperty('disabled', true);
  await page.route('**/api/v1/tetris/models', (route) =>
    route.fulfill({
      json: {
        models: [
          ...modelOptions,
          {
            ...modelOptions[1],
            model_id: 'new',
            name: 'New approved model',
            is_default: false,
          },
        ],
      },
    }),
  );
  await page
    .getByRole('button', { name: /모델 새로고침|Refresh models/ })
    .click();
  await expect(
    page.getByRole('option', { name: /New approved model/ }),
  ).toBeAttached();
  await page.getByRole('button', { name: /게임 시작|Start game/ }).click();
  const second = page
    .getByRole('region', { name: /게임 보드|Game board/ })
    .nth(1);
  await expect(second).toBeFocused();
  await second.press('ArrowDown');
  await expect(page.getByTestId('tetris-score-2')).toHaveText('1');
  await expect(page.getByTestId('tetris-score')).toHaveText('0');
  await page
    .getByRole('button', { name: /일시정지|Pause game/, exact: true })
    .click();
});

test('always shows both boards and keeps their layout when player 2 is absent', async ({
  page,
}) => {
  const bounds = async (locator: Locator) => {
    const box = await locator.boundingBox();
    if (!box) throw new Error('Expected a visible game element');
    return box;
  };
  await page.setViewportSize({ width: 1920, height: 1080 });
  await stubAppDataBackend(page);
  await stubShellBackend(page, {
    user: { ...FAKE_COMPANY_USER, locale: 'en-US' },
  });
  await stubConversationsApi(page);
  await page.goto('/apps/tetris');
  await expect(
    playerMode(page, 2).locator('option[value=ai]'),
  ).toHaveJSProperty('disabled', false);
  const boards = page.getByRole('region', { name: 'Game board', exact: true });
  const firstPanel = page.getByRole('region', {
    name: 'Player 1',
    exact: true,
  });
  const secondPanel = page.getByRole('region', {
    name: 'Player 2',
    exact: true,
  });
  await expect(boards).toHaveCount(2);
  await expect(boards.nth(1)).toBeVisible();
  await playerMode(page, 2).selectOption('none');
  await expect(boards.nth(1)).toHaveAttribute('aria-disabled', 'true');
  const before = await bounds(boards.first());
  await playerMode(page, 2).selectOption('ai');
  await expect(page.getByTestId('tetris-ai-2')).toContainText(
    'Waiting to start',
  );
  await expect(page.getByTestId('tetris-ai-2')).toContainText(
    'No responses yet',
  );
  await expect(page.getByTestId('tetris-ai-2')).not.toContainText('— ms');
  await expect(
    page.getByRole('group', { name: 'Screen controls' }),
  ).not.toBeVisible();
  for (const [firstMode, secondMode] of [
    ['human', 'none'],
    ['human', 'ai'],
    ['ai', 'ai'],
    ['ai', 'none'],
  ]) {
    await playerMode(page).selectOption(firstMode);
    await playerMode(page, 2).selectOption(secondMode);
    const first = await bounds(boards.nth(0));
    const second = await bounds(boards.nth(1));
    expect(first.width).toBeGreaterThanOrEqual(330);
    expect(Math.abs(first.y - second.y)).toBeLessThan(1);
    expect(Math.abs(first.height - second.height)).toBeLessThan(1);
    expect(first.y).toBeCloseTo(before.y, 0);
    expect(first.x).toBeCloseTo(before.x, 0);
    expect(first.width).toBeCloseTo(before.width, 0);
    expect(first.y + first.height).toBeLessThan(1000);
    expect(second.y + second.height).toBeLessThan(1000);
    const a = await bounds(firstPanel);
    const b = await bounds(secondPanel);
    const surface = await bounds(
      page.locator('section[aria-labelledby="tetris-title"]'),
    );
    expect(
      Math.abs((a.x + b.x + b.width) / 2 - (surface.x + surface.width / 2)),
    ).toBeLessThan(2);
  }
  await playerMode(page).selectOption('human');
  await page
    .getByRole('button', { name: 'Screen controls', exact: true })
    .click();
  await expect(
    page.getByRole('group', { name: 'Screen controls' }),
  ).toBeVisible();
  await page.getByText('Controls and rules', { exact: true }).click();
  await expect(
    page.getByText('Play continues when focus leaves the game', {
      exact: true,
    }),
  ).toBeVisible();
  await page.setViewportSize({ width: 360, height: 740 });
  const top = await bounds(boards.nth(0));
  const bottom = await bounds(boards.nth(1));
  expect(bottom.y).toBeGreaterThan(top.y + top.height);
  expect(top.x).toBeGreaterThanOrEqual(0);
  expect(bottom.x + bottom.width).toBeLessThanOrEqual(360);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
