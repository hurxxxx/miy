import { expect, test } from '@playwright/test';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

// Structural route/admission checks only. No business edit, editor or external
// document server is used; detailed application acceptance is deferred.
for (const appId of ['diagrams', 'bento', 'whiteboard'] as const) {
  test(`${appId} loads its owned lazy module through the common shell`, async ({
    page,
  }) => {
    await page.route(
      (url) => url.pathname.startsWith('/api/'),
      (route) =>
        route.fulfill({
          status: 501,
          json: { detail: 'Unconfigured synthetic route' },
        }),
    );
    await stubAppDataBackend(page);
    let realtimeConnections = 0;
    await stubShellBackend(page, {
      enabledAppIds: [appId],
      onRealtimeConnection: () => {
        realtimeConnections += 1;
      },
    });
    await stubConversationsApi(page);
    const errors: string[] = [];
    const mutations: string[] = [];
    let hubReads = 0;
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route(`**/api/v1/${appId}/**`, (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (request.method() !== 'GET') mutations.push(request.method());
      if (request.method() === 'GET' && path === `/api/v1/${appId}/hub`) {
        hubReads += 1;
        return route.fulfill({
          json: { items: [], view: 'all', page: 1, page_size: 200, total: 0 },
        });
      }
      if (
        request.method() === 'GET' &&
        appId === 'bento' &&
        path === '/api/v1/bento/ai-jobs'
      ) {
        return route.fulfill({ json: [] });
      }
      return route.fulfill({
        status: 501,
        json: { detail: 'Unconfigured synthetic route' },
      });
    });
    await page.goto(`/apps/${appId}`);
    await expect(page.locator('main h1').last()).toBeVisible();
    await expect.poll(() => hubReads).toBeGreaterThan(0);
    await expect(
      page.getByRole('heading', { name: '접근 권한 없음' }),
    ).toHaveCount(0);
    expect(mutations).toEqual([]);
    expect(errors).toEqual([]);
    if (appId === 'whiteboard') {
      // The portal connects once; the stage-zero suite supplies an offline
      // context without opening platform realtime traffic.
      const expected =
        process.env.PLAYWRIGHT_APP_COMPOSITION === 'official' ? 0 : 1;
      await expect.poll(() => realtimeConnections).toBe(expected);
    }
  });

  test(`${appId} admission blocks its owned module before business reads`, async ({
    page,
  }) => {
    await page.route(
      (url) => url.pathname.startsWith('/api/'),
      (route) =>
        route.fulfill({
          status: 501,
          json: { detail: 'Unconfigured synthetic route' },
        }),
    );
    await stubAppDataBackend(page);
    await stubShellBackend(page, { enabledAppIds: ['home'] });
    await stubConversationsApi(page);
    const requests: string[] = [];
    await page.route(`**/api/v1/${appId}/**`, (route) => {
      requests.push(route.request().method());
      return route.fulfill({
        status: 403,
        json: { detail: 'Synthetic denial' },
      });
    });
    await page.goto(`/apps/${appId}`);
    await expect(
      page.getByRole('heading', { name: '접근 권한 없음' }),
    ).toBeVisible();
    expect(requests).toEqual([]);
  });
}
