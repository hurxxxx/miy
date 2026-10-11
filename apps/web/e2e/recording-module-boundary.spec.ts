import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

// Synthetic empty collections in an isolated browser profile. No microphone,
// upload, playback, mutation or existing user recording is used.
test('Recording owned collection initializes without requesting audio', async ({
  page,
}) => {
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) =>
      route.fulfill({ status: 501, json: { detail: 'Synthetic route' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, { enabledAppIds: ['recording'] });
  await stubConversationsApi(page);
  let microphoneCalls = 0;
  await page.exposeFunction('structuralMicrophoneRequest', () => {
    microphoneCalls += 1;
    throw new Error('Microphone use is outside this structural fixture');
  });
  await page.addInitScript(() => {
    if (navigator.mediaDevices) {
      navigator.mediaDevices.getUserMedia = () =>
        (
          window as unknown as {
            structuralMicrophoneRequest: () => Promise<MediaStream>;
          }
        ).structuralMicrophoneRequest();
    }
  });
  const errors: string[] = [];
  const unexpectedRequests: string[] = [];
  let reads = 0;
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/v1/recording/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'GET' && path === '/api/v1/recording/recordings') {
      reads += 1;
      return route.fulfill({ json: { items: [], total: 0 } });
    }
    if (
      request.method() === 'GET' &&
      path === '/api/v1/recording/recordings/staging'
    ) {
      return route.fulfill({ json: [] });
    }
    unexpectedRequests.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 501, json: { detail: 'Synthetic route' } });
  });
  await page.goto('/apps/recording?view=mine');
  await expect(page.getByRole('textbox', { name: '녹음 검색' })).toBeVisible();
  await expect(
    page.getByText('아직 녹음이 없어요', { exact: true }),
  ).toBeVisible();
  expect(reads).toBeGreaterThan(0);
  expect(unexpectedRequests).toEqual([]);
  expect(microphoneCalls).toBe(0);
  expect(errors).toEqual([]);
});

test('Recording admission blocks collection and recovery reads', async ({
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
  await page.route('**/api/v1/recording/**', (route) => {
    requests.push(route.request().method());
    return route.fulfill({ status: 403, json: { detail: 'Synthetic denial' } });
  });
  await page.goto('/apps/recording?view=mine');
  await expect(
    page.getByRole('heading', { name: '접근 권한 없음' }),
  ).toBeVisible();
  await expect(page.getByRole('textbox', { name: '녹음 검색' })).toHaveCount(0);
  expect(requests).toEqual([]);
});

test('Recording sync asset retains its exact bytes and fixed root URL', async ({
  request,
}) => {
  const expected = await readFile(
    resolve(
      __dirname,
      '../../../packages/official-suite-web/public/recording-sync-sw.js',
    ),
  );
  for (const url of [
    '/recording-sync-sw.js',
    '/recording-sync-sw.js?structural=1',
  ]) {
    const response = await request.get(url);
    expect(response.status()).toBe(200);
    expect(response.headers()['content-type']).toMatch(/(?:java|ecma)script/i);
    expect(await response.body()).toEqual(expected);
  }
  const head = await request.head('/recording-sync-sw.js');
  expect(head.status()).toBe(200);
  expect(head.headers()['content-type']).toMatch(/(?:java|ecma)script/i);
  expect(await head.body()).toHaveLength(0);
});
