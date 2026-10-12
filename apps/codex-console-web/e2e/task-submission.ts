import { expect, type Page } from '@playwright/test';

export async function submitNewTask(page: Page) {
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === 'POST' &&
      new URL(r.url()).pathname.endsWith('/api/tasks'),
  );
  await page.getByRole('button', { name: '작업 만들기' }).click();
  expect((await response).status()).toBe(200);
}

export async function openNewTask(page: Page) {
  const menu = page.getByRole('button', { name: '메뉴 열기', exact: true });
  // Login transitions asynchronously; inspect responsive navigation after it mounts.
  await expect(page.locator('#console-sidebar')).toBeAttached();
  const history = page
    .getByRole('navigation', { name: 'Workbench 메뉴' })
    .getByRole('button', { name: '작업 기록', exact: true });
  if (
    (await menu.isVisible()) &&
    !(await page
      .locator('#console-sidebar')
      .evaluate((e) => e.classList.contains('open')))
  )
    await menu.click();
  await history.click();
  await page
    .getByRole('button', { name: '새 작업', exact: true })
    .first()
    .click();
}
