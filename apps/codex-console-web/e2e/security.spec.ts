import { expect, test } from '@playwright/test';
import { submitNewTask } from './task-submission';

test('untrusted conversation content stays inert and private APIs require authentication', async ({
  page,
}) => {
  const failures: string[] = [];
  const externalRequests: string[] = [];
  page.on('pageerror', (error) => failures.push(error.message));
  await page.route('https://attacker.invalid/**', (route) => {
    externalRequests.push(route.request().url());
    return route.fulfill({ status: 200, body: '' });
  });
  await page.goto('./');
  for (const path of [
    'api/tasks',
    'api/templates',
    'api/overview',
    'api/monitor/host',
  ]) {
    const response = await page.request.get(path);
    expect(response.status()).toBe(401);
    expect(response.headers()['cache-control']).toBe('no-store');
  }
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page
    .getByRole('button', { name: '새 작업', exact: true })
    .first()
    .click();
  await page.getByLabel('작업 제목').fill('Security boundary verification');
  await submitNewTask(page);
  const content =
    '<img src=x onerror="window.consoleInjected=true">\n\n' +
    '[Unsafe action](javascript:window.consoleInjected=true)\n\n' +
    '![External image](https://attacker.invalid/image.png)\n\n' +
    '[Safe reference](https://example.com/reference)';
  await page.getByLabel('요청 내용 입력').fill(content);
  const accepted = page.waitForResponse(
    (r) =>
      r.request().method() === 'POST' &&
      new URL(r.url()).pathname.endsWith('/messages'),
  );
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  expect((await accepted).status()).toBe(200);
  const message = page.locator('.user-message').last();
  await expect(
    message.getByText('Safe reference', { exact: true }),
  ).toBeVisible();
  expect(
    await message.locator('script, [onerror], a[href^="javascript:"]').count(),
  ).toBe(0);
  expect(await page.evaluate(() => 'consoleInjected' in window)).toBe(false);
  expect(externalRequests).toEqual([]);
  expect(failures).toEqual([]);
  await expect(
    message.getByRole('link', { name: 'Safe reference' }),
  ).toHaveAttribute('rel', 'noreferrer noopener');
});
