import { expect, test } from '@playwright/test';

test('monitoring links to templates without running commands and task history stays usable on mobile', async ({
  page,
}) => {
  await page.goto('./?view=monitoring');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '서비스 상태' }),
  ).toBeVisible();
  const before = await (await page.request.get('api/overview')).json();
  await page
    .getByRole('button', { name: '템플릿으로 작업 요청' })
    .first()
    .click();
  await expect(
    page.getByRole('heading', { name: '작업 템플릿' }),
  ).toBeVisible();
  expect(await (await page.request.get('api/overview')).json()).toHaveLength(
    before.length,
  );
  await page.getByRole('button', { name: '새 작업', exact: true }).click();
  await page.getByLabel('작업 제목').fill('모니터링 후 작업');
  await page.getByRole('button', { name: '작업 만들기' }).click();
  await expect(page.getByLabel('실행 모드')).toHaveValue('plan');
  await expect(page.getByLabel('현재 실행 상태')).toContainText('준비됨');
  const taskId = new URL(page.url()).searchParams.get('task');
  const task = await (await page.request.get(`api/tasks/${taskId}`)).json();
  expect(task.thread_id).toBeNull();
  expect(task.executor).toBe('session');
  await page
    .getByRole('navigation', { name: '콘솔 메뉴' })
    .getByRole('button', { name: '에이전트', exact: true })
    .click();
  const card = page.locator('.overview-task').filter({ hasText: task.title });
  await card.getByRole('button', { name: '고정', exact: true }).click();
  await expect(card.getByRole('button', { name: '고정 해제' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '메뉴 열기' }).click();
  await expect(
    page.getByRole('button', { name: '새 작업', exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
