import { expect, test } from '@playwright/test';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

test('Planner owned calendar retains root CSS and initializes across surface switches', async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date('2026-10-07T01:00:00Z'));
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) =>
      route.fulfill({ status: 501, json: { detail: 'Synthetic route' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, { enabledAppIds: ['planner'] });
  await stubConversationsApi(page);
  const errors: string[] = [];
  const unexpected: string[] = [];
  let reads = 0;
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/v1/calendar/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'GET' && path === '/api/v1/calendar/events') {
      reads += 1;
      return route.fulfill({ json: { items: [] } });
    }
    unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 501, json: { detail: 'Synthetic route' } });
  });
  await page.route('**/api/v1/planner/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'GET' && path === '/api/v1/planner/events')
      return route.fulfill({ json: { items: [] } });
    unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 501, json: { detail: 'Synthetic route' } });
  });

  // Empty synthetic events; no calendar mutation or user data is used.
  await page.goto('/apps/planner?view=calendar');
  const calendar = page.locator('[data-unified-calendar] .fc');
  await expect(calendar).toBeVisible();
  await expect(page.locator('.fc-view-harness')).toBeVisible();
  const colors = await calendar.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      calendar: style.getPropertyValue('--fc-border-color').trim(),
      platform: style.getPropertyValue('--ui-color-border').trim(),
    };
  });
  expect(colors.platform).not.toBe('');
  expect(colors.calendar).toBe(colors.platform);
  await page.getByRole('button', { name: '타임라인', exact: true }).click();
  await expect(calendar).toHaveCount(0);
  await expect(page).toHaveURL(/view=timeline/);
  await page.getByRole('button', { name: '캘린더', exact: true }).click();
  await expect(calendar).toBeVisible();
  // Calendar is the canonical default; its surface parameter is removed.
  await expect(page).toHaveURL(/\/apps\/planner$/);
  expect(reads).toBeGreaterThan(0);
  expect(unexpected).toEqual([]);
  expect(errors).toEqual([]);
});
