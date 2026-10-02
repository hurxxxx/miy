import { expect, test } from '@playwright/test';
import { submitNewTask } from './task-submission';

test('sessions is the entry menu and restores search, scroll and drafts across workspace navigation', async ({
  page,
}) => {
  await page.goto('./');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '세션', exact: true }),
  ).toBeVisible();
  const sidebar = page.locator('#console-sidebar');
  const prefix = `목록 복원 검증 ${Date.now()}`;
  const cookies = await page.context().cookies();
  const headers = {
    origin: new URL(page.url()).origin,
    'x-csrf-token': cookies.find((c) => c.name === 'codex_console_csrf')!.value,
  };
  for (let i = 0; i < 24; i++) {
    const result = await page.request.post('api/tasks', {
      headers,
      data: { title: `${prefix} ${i}`, isolate: false },
    });
    expect(result.ok()).toBe(true);
  }
  const first = `세션 전환 첫 작업 ${Date.now()}`;
  const second = `세션 전환 다음 작업 ${Date.now()}`;
  for (const title of [first, second]) {
    await sidebar.getByRole('button', { name: '새 작업', exact: true }).click();
    await page.getByLabel('작업 제목').fill(title);
    await submitNewTask(page);
    await expect(page.getByRole('heading', { name: title })).toBeVisible();
    if (title === first)
      await page.getByLabel('요청 내용 입력').fill('전환해도 보존할 초안');
  }
  await expect(sidebar.locator('.session-title')).toHaveCount(0);
  await page.getByRole('button', { name: '세션 목록으로' }).click();
  await expect(page).toHaveURL(/view=sessions/);
  await page.getByLabel('세션 검색').fill(first);
  const list = page.getByRole('list', { name: '세션', exact: true });
  await expect(list.locator('.session-title')).toHaveCount(1);
  await list.getByRole('button', { name: new RegExp(first) }).click();
  await expect(page.getByRole('heading', { name: first })).toBeFocused();
  await expect(page.getByLabel('요청 내용 입력')).toHaveValue(
    '전환해도 보존할 초안',
  );
  await page.getByRole('button', { name: '세션 목록으로' }).click();
  await expect(page.getByLabel('세션 검색')).toHaveValue(first);
  await page.getByLabel('세션 검색').fill(prefix);
  await expect(list.locator('.session-title')).toHaveCount(24);
  const row = list.locator('.session-title').nth(12);
  await row.scrollIntoViewIfNeeded();
  const offset = await page
    .locator('.sessions-view')
    .evaluate((node) => node.scrollTop);
  expect(offset).toBeGreaterThan(100);
  await row.click();
  await expect(page.locator('.workspace')).toBeVisible();
  await page.getByRole('button', { name: '세션 목록으로' }).click();
  await expect(page.getByLabel('세션 검색')).toHaveValue(prefix);
  await expect(list.locator('.session-title')).toHaveCount(24);
  await expect
    .poll(() =>
      page.locator('.sessions-view').evaluate((node) => node.scrollTop),
    )
    .toBeCloseTo(offset, 0);
  // Clicking the selected menu again must not disable future scroll recording.
  await sidebar.getByRole('button', { name: '세션', exact: true }).click();
  await list.locator('.session-title').nth(19).scrollIntoViewIfNeeded();
  const nextOffset = await page
    .locator('.sessions-view')
    .evaluate((node) => node.scrollTop);
  await list.locator('.session-title').nth(19).click();
  await expect(page.locator('.workspace')).toBeVisible();
  await page.goBack();
  await expect(list.locator('.session-title')).toHaveCount(24);
  await expect
    .poll(() =>
      page.locator('.sessions-view').evaluate((node) => node.scrollTop),
    )
    .toBeCloseTo(nextOffset, 0);
  const before = await (await page.request.get('api/overview')).json();
  expect(
    before
      .filter(
        (r: { title: string }) =>
          r.title.startsWith(prefix) || [first, second].includes(r.title),
      )
      .every((r: { thread_id: string | null }) => r.thread_id === null),
  ).toBe(true);
  await page.setViewportSize({ width: 320, height: 720 });
  const description = await page
    .getByText(
      '대화를 이어가고, 실행 상황과 확인이 필요한 요청을 살펴보세요.',
      { exact: true },
    )
    .boundingBox();
  expect(description?.width).toBeGreaterThan(240);
  await page.getByLabel('세션 검색').fill(second);
  await expect(list.locator('.session-title')).toHaveCount(1);
  await list.getByRole('button', { name: new RegExp(second) }).click();
  await expect(page.getByRole('heading', { name: second })).toBeFocused();
  await page.getByRole('button', { name: '메뉴 열기' }).click();
  await sidebar.getByRole('button', { name: '세션', exact: true }).click();
  await expect(page.locator('.sidebar.open')).toHaveCount(0);
  await expect(page.getByLabel('세션 검색')).toHaveValue(second);
  await page
    .getByRole('button', { name: 'Codex 세션 불러오기', exact: true })
    .click();
  await expect(page).toHaveURL(/view=sessions&tab=codex/);
  await page.reload();
  await expect(
    page.getByRole('textbox', { name: 'Codex 이력 검색' }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(await (await page.request.get('api/overview')).json()).toHaveLength(
    before.length,
  );
});
