import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import type { ApiSchema } from '@miy/contracts/api';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

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
  role: 'viewer',
  progress: 0,
  member_count: 1,
  milestone_count: 0,
  task_count: 1,
  overdue_task_count: 0,
  created_at: '2026-10-07T09:00:00Z',
  updated_at: '2026-10-07T09:00:00Z',
};

const task: ApiSchema<'TaskItem'> = {
  id: 'synthetic-task',
  list_id: 'synthetic-list',
  reference: 'FIX-1',
  title: 'Synthetic structural task',
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
  updated_at: '2026-10-07T09:00:00Z',
};

async function setup(page: Page, admitted = true) {
  await page.clock.setFixedTime(new Date('2026-10-07T09:00:00Z'));
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) =>
      route.fulfill({ status: 501, json: { detail: 'Synthetic route' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, {
    enabledAppIds: admitted ? ['pms'] : ['home'],
  });
  await stubConversationsApi(page);
  const evidence = {
    errors: [] as string[],
    reads: [] as string[],
    unexpected: [] as string[],
  };
  page.on('pageerror', (error) => evidence.errors.push(error.message));
  const empty = { items: [], total: 0, page: 1, page_size: 50 };
  await page.route('**/api/v1/pms/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/v1/pms/notifications')) return route.fallback();
    evidence.reads.push(`${request.method()} ${path}`);
    if (admitted && request.method() === 'GET') {
      if (path === '/api/v1/pms/view-preferences') {
        const preferences: ApiSchema<'PmsViewPreferencesResponse'> = {
          task_list_group_by: 'status',
        };
        return route.fulfill({ json: preferences });
      }
      if (path === '/api/v1/pms/tasks/today-overdue')
        return route.fulfill({ json: empty });
      if (path === `/api/v1/pms/tasks/${task.id}`) {
        const detail: ApiSchema<'TaskDetailResponse'> = {
          task,
          comments: [],
          linked_docs: [],
          subtasks: [],
          attachments: [],
          checklist_items: [],
        };
        return route.fulfill({ json: detail });
      }
      if (path === `/api/v1/pms/tasks/${task.id}/activity-logs`)
        return route.fulfill({ json: empty });
      if (
        [
          '/api/v1/pms/spaces',
          '/api/v1/pms/lists',
          '/api/v1/pms/tasks/assigned',
          '/api/v1/pms/dashboard/summary',
          '/api/v1/pms/folders',
          '/api/v1/pms/users',
        ].includes(path)
      ) {
        return route.fallback();
      }
    }
    evidence.unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 403, json: { detail: 'Synthetic denial' } });
  });
  return evidence;
}

// Read-only synthetic surfaces exercise relocated lazy screens and shared
// initialization, without accepting app features or changing actual tasks.
test('PMS assigned and today routes retain owned lazy screens and messages', async ({
  page,
}) => {
  const evidence = await setup(page);
  await page.goto('/apps/pms/assigned');
  await expect(
    page.getByRole('heading', { name: '내게 배정됨', exact: true }),
  ).toBeVisible();
  await page.goto('/apps/pms/today');
  await expect(
    page.getByRole('heading', { name: '오늘 및 지연', exact: true }),
  ).toBeVisible();
  expect(evidence.reads).toContain('GET /api/v1/pms/tasks/assigned');
  expect(evidence.reads).toContain('GET /api/v1/pms/tasks/today-overdue');
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test('PMS main list composes its owned calendar with the shared theme', async ({
  page,
}) => {
  const evidence = await setup(page);
  await page.route('**/api/v1/pms/lists/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    evidence.reads.push(`${request.method()} ${path}`);
    if (request.method() === 'GET') {
      if (path === `/api/v1/pms/lists/${taskList.id}`)
        return route.fulfill({ json: taskList });
      if (
        ['tasks', 'statuses', 'milestones', 'labels'].some(
          (suffix) => path === `/api/v1/pms/lists/${taskList.id}/${suffix}`,
        )
      ) {
        return route.fulfill({
          json: { items: [], total: 0, page: 1, page_size: 50 },
        });
      }
    }
    evidence.unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 501, json: { detail: 'Synthetic route' } });
  });
  await page.goto(`/apps/pms/lists/${taskList.id}?tab=calendar`);
  await expect(
    page.getByRole('heading', { name: taskList.name, exact: true }),
  ).toBeVisible();
  const calendar = page.locator('[data-unified-calendar] .fc');
  await expect(calendar).toBeVisible();
  const colors = await calendar.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      calendar: style.getPropertyValue('--fc-border-color').trim(),
      platform: style.getPropertyValue('--ui-color-border').trim(),
    };
  });
  expect(colors.platform).not.toBe('');
  expect(colors.calendar).toBe(colors.platform);
  expect(evidence.reads).toContain(
    `GET /api/v1/pms/lists/${taskList.id}/tasks`,
  );
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test('PMS read-only detail composes after source ownership moves', async ({
  page,
}) => {
  const evidence = await setup(page);
  await page.goto(`/apps/pms/assigned?task=${task.id}`);
  await expect(page.getByTestId('task-detail-title')).toHaveText(task.title);
  expect(evidence.reads).toContain(`GET /api/v1/pms/tasks/${task.id}`);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test('PMS admission prevents owned screen and task reads', async ({ page }) => {
  const evidence = await setup(page, false);
  await page.goto(`/apps/pms/assigned?task=${task.id}`);
  await expect(
    page.getByRole('heading', { name: '접근 권한 없음' }),
  ).toBeVisible();
  await expect(page.getByTestId('task-detail-title')).toHaveCount(0);
  expect(evidence.reads).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test('PMS owned help keeps its exact public HTML URL and English anchor', async ({
  request,
  page,
}) => {
  const expected = await readFile(
    resolve(
      __dirname,
      '../../../packages/official-suite-web/public/help/pms/user-guide.html',
    ),
  );
  for (const url of [
    '/help/pms/user-guide.html',
    '/help/pms/user-guide.html?structural=1',
  ]) {
    const response = await request.get(url);
    expect(response.status()).toBe(200);
    expect(response.headers()['content-type']).toMatch(/text\/html/i);
    expect(await response.body()).toEqual(expected);
  }
  const head = await request.head('/help/pms/user-guide.html');
  expect(head.status()).toBe(200);
  expect(head.headers()['content-type']).toMatch(/text\/html/i);
  expect(await head.body()).toHaveLength(0);
  await page.goto('/help/pms/user-guide.html#english');
  await expect(page.locator('#english')).toBeVisible();
});
