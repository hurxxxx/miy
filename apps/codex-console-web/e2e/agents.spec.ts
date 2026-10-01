import { expect, test } from '@playwright/test';
import { submitNewTask } from './task-submission';

test('agent menu preserves search while opening work and keeps legacy and Codex session navigation', async ({
  page,
}) => {
  await page.goto('./?view=history');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  const navigation = page.getByRole('navigation', { name: '콘솔 메뉴' });
  await expect(
    navigation.getByRole('button', { name: '에이전트', exact: true }),
  ).toHaveAttribute('aria-current', 'page');
  await expect(
    page.getByRole('heading', { name: '에이전트', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: '새 작업', exact: true }).click();
  const title = `목록 복귀 검증 ${Date.now()}`;
  await page.getByLabel('작업 제목').fill(title);
  await submitNewTask(page);
  await expect(page.getByRole('heading', { name: title })).toBeVisible();
  const taskUrl = page.url();
  await navigation
    .getByRole('button', { name: '에이전트', exact: true })
    .click();
  await expect(page).toHaveURL(/view=agents/);
  await page.getByLabel('작업 검색', { exact: true }).fill(title);
  const card = page.locator('.agent-run');
  await expect(card).toHaveCount(1);
  await expect(card.locator('.agent-run-path')).not.toBeEmpty();
  await card.getByRole('button', { name: '대화·결과 열기' }).click();
  await expect(page).toHaveURL(taskUrl);
  await page.goBack();
  await expect(page.getByLabel('작업 검색', { exact: true })).toHaveValue(
    title,
  );
  await expect(card).toHaveCount(1);
  const statuses = page.getByRole('group', { name: '상태 필터' });
  await statuses.getByRole('button', { name: /^종료/ }).click();
  await expect(card).toHaveCount(0);
  await expect(
    page.getByRole('heading', { name: '해당하는 작업이 없습니다' }),
  ).toBeVisible();
  await statuses.getByRole('button', { name: /^전체 작업/ }).click();
  await navigation.getByRole('button', { name: '세션', exact: true }).click();
  await page
    .getByRole('button', { name: 'Codex 세션 불러오기', exact: true })
    .click();
  await expect(page).toHaveURL(/view=sessions&tab=codex/);
  await expect(
    page.getByRole('heading', { name: 'Codex 세션 불러오기' }),
  ).toBeVisible();
  await expect(
    page.getByRole('textbox', { name: 'Codex 이력 검색' }),
  ).toBeVisible();
  await page.goBack();
  await navigation
    .getByRole('button', { name: '에이전트', exact: true })
    .click();
  await expect(card).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole('heading', { name: '에이전트', exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole('button', { name: '메뉴 열기' }).click();
  await expect(
    navigation.getByRole('button', { name: '에이전트', exact: true }),
  ).toBeVisible();
  await navigation
    .getByRole('button', { name: '에이전트', exact: true })
    .click();
  await expect(page.locator('.sidebar.open')).toHaveCount(0);
});
