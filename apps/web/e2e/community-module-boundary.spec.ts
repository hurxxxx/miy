import { expect, test } from '@playwright/test';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

// Check ownership, admission and real editor initialization. Opening an empty
// composer does not create a post or upload media; app detail acceptance waits.
test('Community owned module initializes its catalog and real lazy editor', async ({
  page,
}) => {
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) =>
      route.fulfill({ status: 501, json: { detail: 'Synthetic route' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, { enabledAppIds: ['community'] });
  await stubConversationsApi(page);
  const errors: string[] = [];
  const mutations: string[] = [];
  let channelReads = 0;
  let postReads = 0;
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/v1/community/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') mutations.push(request.method());
    if (request.method() === 'GET' && path === '/api/v1/community/channels') {
      channelReads += 1;
      return route.fulfill({
        json: {
          channels: [
            {
              id: 'structural-channel',
              key: 'structural',
              name: 'Structural channel',
              description: 'Synthetic module initialization',
              position: 1,
              active: true,
              readOnly: false,
              forceAnonymous: false,
              adminOnlyContent: false,
              templateTitle: '',
              templateBody: '',
            },
          ],
        },
      });
    }
    if (
      request.method() === 'GET' &&
      path === '/api/v1/community/channels/structural/posts'
    ) {
      postReads += 1;
      return route.fulfill({
        json: { posts: [], total: 0, page: 1, pageSize: 10 },
      });
    }
    return route.fulfill({ status: 501, json: { detail: 'Synthetic route' } });
  });
  await page.goto('/apps/community?channel=structural');
  await expect(
    page.getByText('Synthetic module initialization', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('아직 글이 없습니다.', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: '새 글', exact: true }).click();
  await expect(
    page
      .getByRole('group', { name: '본문', exact: true })
      .locator('.ProseMirror'),
  ).toBeVisible();
  await expect(page.locator('.community-markdown-editor textarea')).toHaveCount(
    0,
  );
  expect(channelReads).toBeGreaterThan(0);
  expect(postReads).toBeGreaterThan(0);
  expect(mutations).toEqual([]);
  expect(errors).toEqual([]);
});

test('Community admission blocks business reads and editor initialization', async ({
  page,
}) => {
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) =>
      route.fulfill({ status: 501, json: { detail: 'Synthetic route' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, { enabledAppIds: ['home'] });
  await stubConversationsApi(page);
  const requests: string[] = [];
  await page.route('**/api/v1/community/**', (route) => {
    requests.push(route.request().method());
    return route.fulfill({ status: 403, json: { detail: 'Synthetic denial' } });
  });
  await page.goto('/apps/community');
  await expect(
    page.getByRole('heading', { name: '접근 권한 없음' }),
  ).toBeVisible();
  await expect(page.locator('.community-markdown-editor')).toHaveCount(0);
  expect(requests).toEqual([]);
});
