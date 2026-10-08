import { expect, test, type Page } from '@playwright/test';
import { buildAppHref } from '@miy/contracts/app-routes';
import type { ApiSchema } from '@miy/contracts/api';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

const timestamp = '2026-10-07T09:00:00Z';
const taskList: ApiSchema<'TaskListItem'> = {
  id: 'synthetic-list',
  key: 'FIX',
  name: 'Synthetic task list',
  description: '',
  status: 'active',
  status_mode: 'custom',
  archived: false,
  team_id: null,
  team_name: null,
  folder_id: null,
  folder_name: null,
  sort_order: 0,
  role: 'owner',
  progress: 0,
  member_count: 1,
  milestone_count: 0,
  task_count: 1,
  overdue_task_count: 0,
  created_at: timestamp,
  updated_at: timestamp,
};
const task: ApiSchema<'TaskItem'> = {
  id: 'synthetic-task',
  list_id: taskList.id,
  reference: 'FIX-1',
  title: 'Synthetic planning task',
  description: '',
  description_blocks: null,
  parent_id: null,
  subtask_count: 0,
  status: 'open',
  status_label: 'Open',
  priority: 'normal',
  priority_label: 'Normal',
  assignee_id: null,
  assignee_name: null,
  assignee_ids: [],
  assignee_names: [],
  follower_ids: [],
  follower_names: [],
  reporter_id: 'user-e2e',
  reporter_name: 'Fixture owner',
  milestone_id: null,
  milestone_title: null,
  start_date: null,
  due_date: null,
  completed_date: null,
  board_position: 0,
  archived: false,
  progress: 0,
  comments_count: 0,
  checklist_total: 0,
  checklist_done: 0,
  recurrence_rule: null,
  labels: [],
  updated_at: timestamp,
};
const recording: ApiSchema<'RecordingDetailOut'> = {
  id: 'synthetic-recording',
  owner_id: 'user-e2e',
  title: 'Synthetic recording',
  started_at: timestamp,
  ended_at: timestamp,
  duration_sec: 0,
  source: 'quick_record',
  storage_key: null,
  file_size: 0,
  mime_type: 'audio/webm',
  audio_status: 'saved',
  transcript_status: 'done',
  summary_status: 'done',
  meeting_insight_status: 'done',
  progress_pct: 100,
  failure_reason: null,
  transcribe_started_at: null,
  transcribe_completed_at: null,
  created_at: timestamp,
  updated_at: timestamp,
  trashed_at: null,
  targets: [],
  publications: [],
  result: null,
};

async function setup(page: Page, enabled = true) {
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) =>
      route.fulfill({ status: 501, json: { detail: 'Unconfigured fixture' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, {
    enabledAppIds: enabled
      ? ['home', 'recording', 'pms']
      : ['home', 'recording'],
  });
  await stubConversationsApi(page);
  const evidence = {
    reads: [] as string[],
    mutations: [] as unknown[],
    errors: [] as string[],
    finish: (): void => undefined,
  };
  page.on('pageerror', (error) => evidence.errors.push(error.message));
  let current = { ...recording };
  const gate = new Promise<void>((resolve) => {
    evidence.finish = resolve;
  });
  await page.route('**/api/v1/pms/**', (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === 'GET' && url.pathname === '/api/v1/pms/lists') {
      evidence.reads.push(url.pathname + url.search);
      expect(url.searchParams.get('archived')).toBe('false');
      return route.fulfill({
        json: { items: [taskList], total: 1, page: 1, page_size: 50 },
      });
    }
    if (
      request.method() === 'GET' &&
      url.pathname === `/api/v1/pms/lists/${taskList.id}/tasks`
    ) {
      evidence.reads.push(url.pathname + url.search);
      expect(url.searchParams.get('archived')).toBe('false');
      const items = url.searchParams.get('q') === 'missing' ? [] : [task];
      return route.fulfill({
        json: { items, total: items.length, page: 1, page_size: 100 },
      });
    }
    evidence.errors.push(
      `Unexpected PMS fixture: ${request.method()} ${url.pathname}`,
    );
    return route.fulfill({
      status: 501,
      json: { detail: 'Unexpected fixture' },
    });
  });
  await page.route('**/api/v1/recording/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (
      request.method() === 'GET' &&
      path === `/api/v1/recording/recordings/${recording.id}`
    )
      return route.fulfill({ json: current });
    if (request.method() === 'GET' && path === '/api/v1/recording/recordings')
      return route.fulfill({ json: { items: [], total: 0 } });
    if (
      request.method() === 'POST' &&
      path === `/api/v1/recording/recordings/${recording.id}/targets`
    ) {
      evidence.mutations.push(request.postDataJSON());
      await gate;
      current = {
        ...recording,
        targets: [
          {
            id: 'synthetic-task-link',
            recording_id: recording.id,
            target_app: 'pms',
            target_type: 'task',
            target_id: task.id,
            target_title: task.title,
            is_primary: false,
            sort_order: 0,
            added_by_id: 'user-e2e',
            created_at: timestamp,
          },
        ],
      };
      return route.fulfill({ json: current });
    }
    evidence.errors.push(
      `Unexpected Recording fixture: ${request.method()} ${path}`,
    );
    return route.fulfill({
      status: 501,
      json: { detail: 'Unexpected fixture' },
    });
  });
  await page.goto(
    buildAppHref({
      routeId: 'recording.detail',
      pathParams: { recordingId: recording.id },
    }),
  );
  await expect(
    page.getByRole('button', { name: '태스크 추가', exact: true }),
  ).toBeVisible();
  return evidence;
}

test('Recording uses the public PMS picker with current list/search, explicit attachment and excluded linked tasks', async ({
  page,
}) => {
  const evidence = await setup(page);
  expect(evidence.reads).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '태스크 추가', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '태스크 추가', exact: true });
  const pick = dialog.getByRole('button', { name: new RegExp(task.title) });
  await expect(pick).toBeVisible();
  await expect(
    dialog.getByRole('combobox', { name: '태스크 목록', exact: true }),
  ).toHaveValue(taskList.id);
  const bounds = await dialog.boundingBox();
  expect(bounds?.width).toBeGreaterThan(200);
  expect(bounds?.width).toBeLessThanOrEqual(390);
  const search = dialog.getByRole('textbox', { name: '검색', exact: true });
  await search.fill('missing');
  await expect(pick).toHaveCount(0);
  await search.fill('planning');
  await expect(pick).toBeVisible();
  expect(
    evidence.reads.filter((url) => url.includes('q=planning')),
  ).toHaveLength(1);
  expect(evidence.mutations).toEqual([]);
  await pick.click();
  // Existing Recording callback returns void; the UI closes before the server response.
  await expect(dialog).toBeHidden();
  await expect.poll(() => evidence.mutations.length).toBe(1);
  expect(evidence.mutations).toEqual([
    { target_app: 'pms', target_type: 'task', target_id: task.id },
  ]);
  evidence.finish();
  const link = page.getByRole('link', { name: new RegExp(task.title) });
  await expect(link).toHaveAttribute(
    'href',
    buildAppHref({ routeId: 'pms.root', queryParams: { task: task.id } }),
  );
  await page.getByRole('button', { name: '태스크 추가', exact: true }).click();
  await expect(dialog).toBeVisible();
  await expect(search).toHaveValue('');
  await expect(pick).toHaveCount(0);
  await dialog
    .getByRole('button', { name: '닫기', exact: true })
    .last()
    .click();
  expect(evidence.mutations).toHaveLength(1);
  expect(evidence.errors).toEqual([]);
});

test('Recording remains admitted when PMS denial blocks the public task picker before its API calls', async ({
  page,
}) => {
  const evidence = await setup(page, false);
  await page.getByRole('button', { name: '태스크 추가', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '태스크 추가', exact: true });
  await expect(dialog.getByRole('alert')).toBeVisible();
  await expect(dialog.getByRole('textbox')).toHaveCount(0);
  await dialog
    .getByRole('button', { name: '닫기', exact: true })
    .last()
    .click();
  expect(evidence.reads).toEqual([]);
  expect(evidence.mutations).toEqual([]);
  expect(evidence.errors).toEqual([]);
});
