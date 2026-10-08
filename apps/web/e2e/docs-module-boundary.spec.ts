import { expect, test } from '@playwright/test';
import type { ApiSchema } from '@miy/contracts/api';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

// Structural native/HTML initialization with read-only synthetic content.
// No editing, collaboration session, publication, share or save is performed.
for (const format of ['block', 'html'] as const) {
  test(`Docs owned ${format} surface initializes through the common shell`, async ({
    page,
  }) => {
    await page.route(
      (url) => url.pathname.startsWith('/api/'),
      (route) =>
        route.fulfill({ status: 501, json: { detail: 'Synthetic route' } }),
    );
    await stubAppDataBackend(page);
    await stubShellBackend(page, { enabledAppIds: ['docs'] });
    await stubConversationsApi(page);
    const docId = `structural-${format}`;
    const pageId = `structural-${format}-page`;
    const content = `Structural ${format} body`;
    const doc = {
      id: docId,
      title: `Structural ${format} document`,
      ownership_kind: 'personal',
      company_visible: false,
      source_app: 'docs',
      source_type: 'native_doc',
      source_id: docId,
      source_kind: 'native',
      source_ref: null,
      generation_kind: 'manual',
      rag_scope: 'excluded',
      doc_type: 'general',
      content_format: format,
      structure_kind: 'page_tree',
      location_label: '',
      target_label: '',
      collection: null,
      primary_target: null,
      source_badge: '',
      source_deeplink: null,
      page_count: 1,
      created_by_id: 'synthetic-owner',
      created_by_name: 'Synthetic owner',
      created_at: '2026-10-07T00:00:00Z',
      updated_at: '2026-10-07T00:00:00Z',
      trashed_at: null,
      is_favorite: false,
      is_private: true,
      last_viewed_at: null,
      can_view: true,
      can_edit: false,
      can_share: false,
      can_manage: false,
      sharing_summary: null,
    } satisfies ApiSchema<'DocsHubItem'>;
    const docPage = {
      id: pageId,
      doc_id: docId,
      source_type: 'native_doc_page',
      source_page_id: pageId,
      parent_id: null,
      title: `Structural ${format} page`,
      content_blocks:
        format === 'block'
          ? [{ id: 'structural-paragraph', type: 'paragraph', content }]
          : null,
      content_text: format === 'html' ? `<p>${content}</p>` : null,
      content_format: format,
      sort_order: 0,
      created_by_id: 'synthetic-owner',
      created_by_name: 'Synthetic owner',
      created_at: '2026-10-07T00:00:00Z',
      updated_at: '2026-10-07T00:00:00Z',
      trashed_at: null,
      can_edit: false,
      realtime_collab: false,
    } satisfies ApiSchema<'DocsPageItem'>;
    const errors: string[] = [];
    const unexpectedWrites: string[] = [];
    let detailReads = 0;
    let pageReads = 0;
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/docs/**', (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (request.method() === 'GET') {
        if (path === `/api/v1/docs/items/${docId}`) {
          detailReads += 1;
          return route.fulfill({ json: doc });
        }
        if (path === `/api/v1/docs/items/${docId}/pages`) {
          pageReads += 1;
          return route.fulfill({ json: { items: [docPage] } });
        }
        if (path === '/api/v1/docs/hub') {
          return route.fulfill({
            json: { items: [], total: 0, page: 1, page_size: 200 },
          });
        }
        if (path === `/api/v1/docs/items/${docId}/pms-tasks`) {
          return route.fulfill({ json: { items: [] } });
        }
        if (
          ['/api/v1/docs/favorites', '/api/v1/docs/recent-pages'].includes(path)
        ) {
          return route.fulfill({ json: [] });
        }
      }
      if (
        request.method() === 'POST' &&
        path === `/api/v1/docs/items/${docId}/view`
      ) {
        return route.fulfill({ status: 204 });
      }
      if (request.method() !== 'GET') unexpectedWrites.push(request.method());
      return route.fulfill({
        status: 501,
        json: { detail: 'Synthetic route' },
      });
    });
    const path =
      format === 'block'
        ? `/apps/docs/documents/${docId}`
        : `/apps/docs/documents/${docId}/html/${pageId}`;
    await page.goto(path);
    if (format === 'block') {
      await expect(page.locator('main .ui-block-editor')).toBeVisible();
      await expect(
        page.locator('main').getByText(content, { exact: true }),
      ).toBeVisible();
    } else {
      await expect(
        page.frameLocator('iframe').getByText(content, { exact: true }),
      ).toBeVisible();
    }
    expect(detailReads).toBeGreaterThan(0);
    expect(pageReads).toBeGreaterThan(0);
    expect(unexpectedWrites).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('Docs admission blocks its owned module before business reads', async ({
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
  await page.route('**/api/v1/docs/**', (route) => {
    requests.push(route.request().method());
    return route.fulfill({ status: 403, json: { detail: 'Synthetic denial' } });
  });
  await page.goto('/apps/docs/documents/structural-block');
  await expect(
    page.getByRole('heading', { name: '접근 권한 없음' }),
  ).toBeVisible();
  await expect(page.locator('main .ui-block-editor')).toHaveCount(0);
  expect(requests).toEqual([]);
});
