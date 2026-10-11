import { expect, test } from '@playwright/test';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

// All Video Chat transport is intercepted. No real room, join token or media device.
const room = {
  id: 'synthetic-room',
  meeting_id: null,
  room_name: 'fixture-room',
  title: 'Synthetic team room',
  status: 'open',
  provider: 'livekit',
  started_by_id: 'user-e2e',
  started_by_name: 'Fixture owner',
  started_at: '2026-10-07T09:00:00Z',
  ended_at: null,
  recording_status: 'idle',
  recording_egress_id: null,
  recording_id: null,
  captions_status: 'off',
  captions_started_at: null,
  captions_ended_at: null,
  created_at: '2026-10-07T09:00:00Z',
  updated_at: '2026-10-07T09:00:00Z',
};

test('Video Chat lobby lists, copies and creates through the unchanged routes without media access', async ({
  page,
}) => {
  await stubAppDataBackend(page);
  await stubShellBackend(page);
  await stubConversationsApi(page);
  await page.addInitScript(() => {
    const evidence = { copied: [] as string[], deviceCalls: 0 };
    Reflect.set(window, 'videoChatFixture', evidence);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (text: string) => {
          evidence.copied.push(text);
        },
      },
    });
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => {
          evidence.deviceCalls += 1;
          throw new Error('Real media is forbidden in this fixture');
        },
        getDisplayMedia: async () => {
          evidence.deviceCalls += 1;
          throw new Error('Real screen sharing is forbidden in this fixture');
        },
        enumerateDevices: async () => {
          evidence.deviceCalls += 1;
          return [];
        },
      },
    });
  });
  const errors: string[] = [];
  const created: unknown[] = [];
  const joinRequests: string[] = [];
  let listRequests = 0;
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/v1/video-chat/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/video-chat/sessions' && request.method() === 'GET') {
      listRequests += 1;
      return route.fulfill({
        json: {
          items: [
            room,
            {
              ...room,
              id: 'ended-room',
              title: 'Finished room',
              status: 'ended',
            },
          ],
          total: 2,
        },
      });
    }
    if (path === '/api/v1/video-chat/sessions' && request.method() === 'POST') {
      created.push(request.postDataJSON());
      return route.fulfill({ json: { ...room, title: 'New fixture room' } });
    }
    if (
      path === '/api/v1/video-chat/sessions/synthetic-room/join-token' &&
      request.method() === 'POST'
    ) {
      joinRequests.push(path);
      return route.fulfill({
        status: 403,
        json: { detail: 'Synthetic room connection is disabled' },
      });
    }
    errors.push(
      `Unexpected Video Chat fixture request: ${request.method()} ${path}`,
    );
    return route.fulfill({
      status: 500,
      json: { detail: 'Unexpected fixture request' },
    });
  });
  await page.goto('/apps/video-chat');
  await expect(
    page.getByRole('heading', { level: 1, name: '화상채팅', exact: true }),
  ).toBeVisible();
  await expect(page.getByText(room.title, { exact: true })).toBeVisible();
  await expect(page.getByText('Finished room', { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  const title = page.getByRole('heading', {
    level: 1,
    name: '화상채팅',
    exact: true,
  });
  await expect(title).toBeVisible();
  expect((await title.boundingBox())?.width).toBeGreaterThan(60);
  await expect(
    page.getByRole('textbox', { name: '방 제목', exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
  await page.getByRole('button', { name: '초대 링크', exact: true }).click();
  await expect(
    page.getByRole('button', { name: '복사됨', exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => Reflect.get(window, 'videoChatFixture').copied),
  ).toEqual([
    new URL('/apps/video-chat/sessions/synthetic-room', page.url()).href,
  ]);
  expect(joinRequests).toEqual([]);
  await page
    .getByRole('textbox', { name: '방 제목', exact: true })
    .fill('  New fixture room  ');
  await page.getByRole('button', { name: '방 만들기', exact: true }).click();
  await expect(page).toHaveURL(/\/apps\/video-chat\/sessions\/synthetic-room$/);
  await expect(
    page.getByText('Synthetic room connection is disabled', { exact: true }),
  ).toBeVisible();
  expect(created).toEqual([{ title: 'New fixture room' }]);
  expect(listRequests).toBeGreaterThanOrEqual(2);
  expect(joinRequests.length).toBeGreaterThanOrEqual(1);
  expect(
    await page.evaluate(
      () => Reflect.get(window, 'videoChatFixture').deviceCalls,
    ),
  ).toBe(0);
  expect(errors).toEqual([]);
});

test('Video Chat admission blocks the lobby before any room data request', async ({
  page,
}) => {
  await stubAppDataBackend(page);
  await stubShellBackend(page, { enabledAppIds: ['home'] });
  await stubConversationsApi(page);
  const requests: string[] = [];
  await page.route('**/api/v1/video-chat/**', (route) => {
    requests.push(route.request().url());
    return route.fulfill({ status: 403, json: { detail: 'denied' } });
  });
  await page.goto('/apps/video-chat');
  await expect(
    page.getByRole('heading', { name: '접근 권한 없음' }),
  ).toBeVisible();
  expect(requests).toEqual([]);
});
