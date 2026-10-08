import { expect, test, type Page } from '@playwright/test';
import { buildAppHref } from '@miy/contracts/app-routes';
import type { ApiSchema } from '@miy/contracts/api';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

const timestamp = '2026-10-07T09:00:00Z';
const folder: ApiSchema<'FileFolderItem'> = {
  id: 'synthetic-folder',
  corpus_id: null,
  parent_id: null,
  name: 'Synthetic folder',
  visibility: 'private',
  owner_id: 'user-e2e',
  owner_name: 'Fixture owner',
  can_manage: true,
  created_at: timestamp,
  updated_at: timestamp,
};
const file: ApiSchema<'FileItem'> = {
  id: 'synthetic-file',
  corpus_id: null,
  folder_id: null,
  filename: 'synthetic.txt',
  content_type: 'text/plain',
  size_bytes: 3,
  visibility: 'private',
  owner_id: 'user-e2e',
  owner_name: 'Fixture owner',
  can_delete: true,
  rag_status: 'ready',
  rag_updated_at: timestamp,
  created_at: timestamp,
  updated_at: timestamp,
};

async function setup(page: Page, enabled = true) {
  await page.route('**/api/**', (route) =>
    route.fulfill({ status: 501, json: { detail: 'Unconfigured fixture' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, {
    enabledAppIds: enabled ? ['home', 'files'] : ['home'],
  });
  await stubConversationsApi(page);
  const evidence = {
    reads: [] as string[],
    writes: [] as { path: string; data: unknown }[],
    searches: [] as unknown[],
    downloads: 0,
    errors: [] as string[],
    releaseUpload: (): void => undefined,
  };
  page.on('pageerror', (error) => evidence.errors.push(error.message));
  let created = false;
  let uploaded = false;
  const uploadGate = new Promise<void>((resolve) => {
    evidence.releaseUpload = resolve;
  });
  await page.route('**/api/v1/files**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === 'GET' && path === '/api/v1/files') {
      evidence.reads.push(url.search);
      const inside = url.searchParams.get('folder_id') === folder.id;
      return route.fulfill({
        json: {
          current_folder: inside ? folder : null,
          breadcrumbs: inside ? [folder] : [],
          folders: created && !inside ? [folder] : [],
          files: inside
            ? []
            : uploaded
              ? [
                  file,
                  { ...file, id: 'synthetic-upload', filename: 'upload.txt' },
                ]
              : [file],
          all_folders: created ? [folder] : [],
        },
      });
    }
    if (request.method() === 'POST' && path === '/api/v1/files/folders') {
      evidence.writes.push({ path, data: request.postDataJSON() });
      created = true;
      return route.fulfill({ json: folder });
    }
    if (request.method() === 'POST' && path === '/api/v1/files/upload') {
      const data = request.postData() ?? '';
      expect(data).toContain('filename="upload.txt"');
      expect(data).toContain('name="visibility"\r\n\r\nprivate');
      evidence.writes.push({ path, data: 'synthetic multipart upload' });
      await uploadGate;
      uploaded = true;
      return route.fulfill({
        json: { ...file, id: 'synthetic-upload', filename: 'upload.txt' },
      });
    }
    if (request.method() === 'POST' && path === '/api/v1/files/search') {
      const data = request.postDataJSON();
      evidence.searches.push(data);
      return route.fulfill({
        json: {
          ...data,
          has_more: false,
          max_ranked_results: 25,
          latency_ms: 1,
          trace_id: null,
          hits: [
            {
              rank: 1,
              file_id: file.id,
              filename: file.filename,
              folder_id: null,
              content_type: file.content_type,
              size_bytes: file.size_bytes,
              score: 1,
              methods: ['bm25'],
              snippet: {
                text: '<img src=x onerror=alert(1)> synthetic',
                highlights: [],
              },
              updated_at: timestamp,
            },
          ],
        },
      });
    }
    if (
      request.method() === 'GET' &&
      path === `/api/v1/files/${file.id}/download`
    ) {
      return route.fulfill({
        json: { url: '/api/v1/content#grant=synthetic-files-grant' },
      });
    }
    evidence.errors.push(
      `Unexpected Files fixture: ${request.method()} ${path}`,
    );
    return route.fulfill({
      status: 501,
      json: { detail: 'Unexpected Files fixture' },
    });
  });
  await page.route('**/api/v1/content', (route) => {
    expect(route.request().headers()['x-miy-content-grant']).toBe(
      'synthetic-files-grant',
    );
    expect(route.request().url()).not.toContain('grant');
    evidence.downloads += 1;
    return route.fulfill({
      body: 'abc',
      contentType: 'application/octet-stream',
    });
  });
  return evidence;
}

test('Files preserves explicit private folder creation and the shared upload state across folder navigation', async ({
  page,
}) => {
  const evidence = await setup(page);
  await page.goto(buildAppHref({ routeId: 'files.root' }));
  await expect(page.getByText(file.filename, { exact: true })).toBeVisible();
  expect(evidence.writes).toEqual([]);
  await page.getByRole('button', { name: '새 폴더', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '새 폴더', exact: true });
  await dialog
    .getByRole('textbox', { name: '폴더 이름', exact: true })
    .fill(folder.name);
  expect(evidence.writes).toEqual([]);
  await dialog.getByRole('button', { name: '생성', exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(evidence.writes).toHaveLength(1);
  expect(evidence.writes[0].data).toMatchObject({
    name: folder.name,
    visibility: 'private',
  });
  await page.locator('input[type=file]').setInputFiles({
    name: 'upload.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('abc'),
  });
  const panel = page.getByRole('region', { name: '파일 업로드 상태' });
  await expect(panel).toBeVisible();
  await expect.poll(() => evidence.writes.length).toBe(2);
  await page
    .getByRole('button', { name: folder.name, exact: true })
    .first()
    .click();
  await expect(
    page.getByRole('heading', { name: folder.name, exact: true }),
  ).toBeVisible();
  await expect(panel).toBeVisible();
  await expect(
    page.getByRole('button', { name: '업로드', exact: true }),
  ).toBeDisabled();
  evidence.releaseUpload();
  await expect(panel.getByRole('status')).toHaveText('최근 업로드');
  await expect(
    page.getByRole('button', { name: '업로드', exact: true }),
  ).toBeEnabled();
  await page.getByRole('button', { name: '전체 파일', exact: true }).click();
  await expect(page.getByText('upload.txt', { exact: true })).toBeVisible();
  expect(evidence.writes).toHaveLength(2);
  expect(evidence.errors).toEqual([]);
});

test('Files search keeps snippets as text and downloads through the shared authenticated content helper', async ({
  page,
}) => {
  const evidence = await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${buildAppHref({ routeId: 'files.root' })}?view=search`);
  await page
    .getByRole('searchbox', { name: '파일 검색어', exact: true })
    .fill('synthetic');
  expect(evidence.searches).toEqual([]);
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.getByText(file.filename, { exact: true })).toBeVisible();
  await expect(
    page.getByText('<img src=x onerror=alert(1)> synthetic', { exact: true }),
  ).toBeVisible();
  await expect(page.locator('img[src=x]')).toHaveCount(0);
  expect(evidence.searches).toHaveLength(1);
  expect(evidence.downloads).toBe(0);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '다운로드', exact: true }).click();
  await download;
  expect(evidence.downloads).toBe(1);
  expect(evidence.writes).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test('Files admission denies the moved workspace before listing, searching or uploading', async ({
  page,
}) => {
  const evidence = await setup(page, false);
  await page.goto(buildAppHref({ routeId: 'files.root' }));
  await expect(
    page.getByRole('heading', { name: '접근 권한 없음' }),
  ).toBeVisible();
  await expect(page.locator('input[type=file]')).toHaveCount(0);
  expect(evidence.reads).toEqual([]);
  expect(evidence.searches).toEqual([]);
  expect(evidence.writes).toEqual([]);
  expect(evidence.errors).toEqual([]);
});
