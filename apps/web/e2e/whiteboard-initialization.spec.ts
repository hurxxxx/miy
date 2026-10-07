import { expect, test } from '@playwright/test';
import type { ApiSchema } from '@miy/contracts/api';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

// One structural editor mount: no drawing, sharing, save or collaboration
// acceptance. The real lazy editor must have its shared provider in both roots.
test('Whiteboard lazy editor has its shared initialization context', async ({
  page,
}) => {
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) =>
      route.fulfill({ status: 501, json: { detail: 'Synthetic route' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, { enabledAppIds: ['whiteboard'] });
  await stubConversationsApi(page);
  const board = {
    id: 'structural-board',
    title: 'Structural initialization',
    ownership_kind: 'personal',
    company_visible: false,
    is_private: true,
    source_app: 'whiteboard',
    source_type: 'whiteboard',
    source_id: 'structural-board',
    source_kind: 'native',
    source_ref: null,
    generation_kind: 'manual',
    location_label: '',
    target_label: '',
    primary_target: null,
    targets: [],
    source_badge: '',
    source_deeplink: null,
    created_by_id: 'synthetic-owner',
    created_by_name: 'Synthetic owner',
    created_at: '2026-10-07T00:00:00Z',
    updated_at: '2026-10-07T00:00:00Z',
    trashed_at: null,
    is_favorite: false,
    last_viewed_at: null,
    can_view: true,
    can_edit: false,
    can_share: false,
    can_manage: false,
    scene: { elements: [], appState: {}, files: {} },
  } satisfies ApiSchema<'WhiteboardDetail'>;
  let detailReads = 0;
  const unexpectedWrites: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/v1/whiteboard/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (
      request.method() === 'GET' &&
      path === '/api/v1/whiteboard/items/structural-board'
    ) {
      detailReads += 1;
      return route.fulfill({ json: board });
    }
    if (
      request.method() === 'POST' &&
      path === '/api/v1/whiteboard/items/structural-board/view'
    ) {
      return route.fulfill({ status: 204 });
    }
    if (request.method() !== 'GET') unexpectedWrites.push(request.method());
    return route.fulfill({ status: 501, json: { detail: 'Synthetic route' } });
  });
  await page.goto('/apps/whiteboard/boards/structural-board');
  await expect(page.locator('main .excalidraw')).toBeVisible();
  expect(detailReads).toBeGreaterThan(0);
  expect(unexpectedWrites).toEqual([]);
  expect(errors).toEqual([]);
});
