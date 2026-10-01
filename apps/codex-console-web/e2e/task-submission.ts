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
