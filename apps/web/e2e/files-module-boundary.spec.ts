import { expect, test, type Page } from '@playwright/test';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

async function setup(page: Page, admitted = true) {
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) =>
      route.fulfill({ status: 501, json: { detail: 'Synthetic route' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, {
    enabledAppIds: admitted ? ['files', 'chatbot'] : ['home'],
  });
  await stubConversationsApi(page);
  const evidence = {
    errors: [] as string[],
    fileReads: 0,
    sessions: [] as URL[],
    writes: [] as string[],
  };
  page.on('pageerror', (error) => evidence.errors.push(error.message));
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (
      path.startsWith('/api/') &&
      // The shell's route telemetry is fulfilled by stubShellBackend.
      !(path === '/api/v1/usage/events' && request.method() === 'POST') &&
      !['GET', 'HEAD'].includes(request.method())
    ) {
      evidence.writes.push(`${request.method()} ${path}`);
    }
    if (path === '/api/v1/agent/sessions')
      evidence.sessions.push(new URL(request.url()));
  });
  await page.route('**/api/v1/files**', (route) => {
    const request = route.request();
    if (
      request.method() === 'GET' &&
      new URL(request.url()).pathname === '/api/v1/files'
    ) {
      evidence.fileReads += 1;
      return route.fulfill({
        json: {
          current_folder: null,
          breadcrumbs: [],
          folders: [],
          files: [],
          all_folders: [],
        },
      });
    }
    return route.fulfill({ status: 403, json: { detail: 'Synthetic denial' } });
  });
  return evidence;
}

test('Files main and search retain the owned lazy composition without writes', async ({
  page,
}) => {
  const evidence = await setup(page);
  await page.goto('/apps/files');
  await expect.poll(() => evidence.fileReads).toBeGreaterThan(0);
  await expect(
    page.getByRole('main', { name: '파일 드래그 앤 드롭 업로드' }),
  ).toBeVisible();
  await page.goto('/apps/files?view=search');
  await expect(
    page.getByRole('searchbox', { name: '파일 검색어' }),
  ).toBeVisible();
  expect(evidence.writes).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test('Files chat uses the actual common engine with its registered Files scope', async ({
  page,
}) => {
  const evidence = await setup(page);
  await page.goto('/apps/files/chat');
  await expect(
    page.getByText('저장된 문서에 무엇이든 물어보세요', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('textbox', { name: '메시지를 입력하세요', exact: true }),
  ).toBeVisible();
  // The workspace separately fetches unpaginated session titles. Check the
  // conversation list's actual paginated requests rather than that lookup.
  const conversationLists = () =>
    evidence.sessions.filter((url) => url.searchParams.has('offset'));
  await expect.poll(() => conversationLists().length).toBeGreaterThan(0);
  for (const url of conversationLists()) {
    expect(url.searchParams.get('scope_ref')).toBe('files');
    expect(url.searchParams.get('scope_resource_id')).toBe('company');
  }
  expect(evidence.writes).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test('Files chat admission prevents common conversation reads and writes', async ({
  page,
}) => {
  const evidence = await setup(page, false);
  await page.goto('/apps/files/chat');
  await expect(
    page.getByRole('heading', { name: '접근 권한 없음' }),
  ).toBeVisible();
  expect(evidence.sessions).toEqual([]);
  expect(evidence.fileReads).toBe(0);
  expect(evidence.writes).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test('Portal Chatbot keeps its common empty conversation and composer', async ({
  page,
}) => {
  test.skip(
    process.env.PLAYWRIGHT_APP_COMPOSITION === 'official',
    'Platform Chatbot route is owned by the portal composition.',
  );
  const evidence = await setup(page);
  await page.goto('/apps/chatbot');
  await expect(
    page.getByText('안녕하세요, 업무를 도와드릴게요.', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('textbox', { name: '메시지를 입력하세요', exact: true }),
  ).toBeVisible();
  await expect.poll(() => evidence.sessions.length).toBeGreaterThan(0);
  expect(evidence.writes).toEqual([]);
  expect(evidence.errors).toEqual([]);
});
