import { expect, test } from '@playwright/test';

test('service requests become editable Codex drafts and work stays visible on mobile', async ({
  page,
}) => {
  await page.goto('./');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '서비스 상태' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Codex에 점검 요청' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: '작업 만들기' }).click();
  await expect(page.getByLabel('요청 내용 입력')).toContainText(
    'Codex sessions',
  );
  await expect(page.getByLabel('실행 모드')).toHaveValue('plan');
  await expect(page.getByLabel('현재 실행 상태')).toContainText('준비됨');
  const taskId = new URL(page.url()).searchParams.get('task');
  const task = await (await page.request.get(`api/tasks/${taskId}`)).json();
  expect(task.thread_id).toBeNull();
  expect(task.context.purpose).toBe('inspection');
  expect(task.context.service_id).toBe('console-session');
  await page.getByRole('button', { name: '작업 현황', exact: true }).click();
  const card = page.locator('.overview-task').filter({ hasText: task.title });
  await card.getByRole('button', { name: '고정', exact: true }).click();
  await expect(card.getByRole('button', { name: '고정 해제' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole('button', { name: '새 작업', exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
