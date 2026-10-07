import type { components } from '@miy/contracts/openapi.generated';
import { expect, test, type Page } from '@playwright/test';

import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

type PlannerEvent = components['schemas']['PlannerEventOut'];

// All HTTP mutations are intercepted. No calendar, Meeting or PMS data is written.
async function shell(page: Page, enabled: boolean, errors: string[]) {
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) => {
      errors.push(
        `Unexpected fixture API: ${route.request().method()} ${new URL(route.request().url()).pathname}`,
      );
      return route.fulfill({
        status: 500,
        json: { detail: 'Unexpected fixture request' },
      });
    },
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, {
    enabledAppIds: enabled ? ['home', 'planner'] : ['home'],
  });
  await stubConversationsApi(page);
  await page.route(/\/api\/v1\/(?:meeting|pms)\//, (route) => {
    if (route.request().method() === 'GET') return route.fallback();
    errors.push('Unexpected cross-app write');
    return route.fulfill({
      status: 403,
      json: { detail: 'Synthetic write denied' },
    });
  });
  page.on('pageerror', (error) => errors.push(error.message));
}

test('Planner shares the moved editor and date picker through create, update and delete', async ({
  page,
}) => {
  const errors: string[] = [];
  const actions: string[] = [];
  let event: PlannerEvent | null = null;
  await page.clock.setFixedTime(new Date('2026-10-07T01:00:00Z'));
  await shell(page, true, errors);
  await page.route('**/api/v1/calendar/events**', (route) =>
    route.fulfill({
      json: {
        items: event
          ? [
              {
                id: `planner-event-${event.id}`,
                title: event.title,
                start: event.calendarStart,
                end: event.calendarEnd,
                allDay: event.calendarAllDay,
                sourceType: 'planner_event',
                sourceId: event.id,
                color: '#818cf8',
                metadata: {
                  plannerEventId: event.id,
                  ownerId: event.ownerId,
                  ownerName: event.ownerName,
                  plannerAllDay: true,
                  plannerStartHasTime: false,
                  plannerEndHasTime: false,
                  plannerTimeZone: event.timeZone,
                },
              },
            ]
          : [],
      },
    }),
  );
  await page.route('**/api/v1/planner/events**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (method === 'GET') {
      return route.fulfill({
        json: path.endsWith('/events')
          ? { items: event ? [event] : [] }
          : event,
      });
    }
    if (
      (method === 'POST' && path.endsWith('/events')) ||
      (method === 'PATCH' && path.endsWith('/fixture-event') && event)
    ) {
      const body = request.postDataJSON();
      expect(body).toMatchObject({
        allDay: true,
        start: '2026-10-08',
        end: '2026-10-09',
      });
      actions.push(method === 'POST' ? 'create' : 'update');
      event = {
        id: 'fixture-event',
        ownerId: 'user-e2e',
        ownerName: 'E2E Tester',
        title: body.title,
        description: body.description,
        location: body.location,
        timeZone: 'Asia/Seoul',
        allDay: true,
        startHasTime: false,
        endHasTime: false,
        start: body.start,
        end: body.end,
        calendarStart: body.start,
        calendarEnd: body.end,
        calendarAllDay: true,
        createdAt: '2026-10-07T01:00:00Z',
        updatedAt: '2026-10-07T01:00:00Z',
      };
      return route.fulfill({ json: event });
    }
    if (method === 'DELETE' && path.endsWith('/fixture-event') && event) {
      actions.push('delete');
      event = null;
      return route.fulfill({ status: 204 });
    }
    errors.push(`Unexpected Planner fixture request: ${method} ${path}`);
    return route.fulfill({
      status: 500,
      json: { detail: 'Unexpected fixture request' },
    });
  });

  await page.goto('/apps/planner?view=timeline');
  await expect(
    page.getByRole('heading', { level: 1, name: '플래너', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: '추가', exact: true }).click();
  await page.getByRole('button', { name: '이벤트', exact: true }).click();
  const create = page.getByRole('dialog', { name: '새 이벤트', exact: true });
  await create
    .getByRole('textbox', { name: '제목', exact: true })
    .fill('Synthetic planning');
  await create.getByRole('radio', { name: '종일 일정', exact: true }).click();
  await create
    .getByRole('button', { name: '날짜 선택', exact: true })
    .first()
    .click();
  const picker = page.getByRole('dialog', { name: '날짜 선택', exact: true });
  await expect(picker).toBeVisible();
  await expect(picker).toHaveCSS('position', 'fixed');
  await expect(picker).toHaveCSS('width', '288px');
  await expect(picker).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await picker
    .getByRole('button', { name: '2026년 10월 8일 목요일', exact: true })
    .click();
  await expect(picker).toBeHidden();
  await create
    .getByRole('textbox', { name: '종료 날짜', exact: true })
    .fill('2026. 10. 8.');
  await create
    .getByRole('textbox', { name: '종료 날짜', exact: true })
    .press('Enter');
  await create.getByRole('button', { name: '저장', exact: true }).click();
  await expect(create).toBeHidden();
  await expect.poll(() => actions).toEqual(['create']);

  await page
    .getByRole('button', { name: 'Synthetic planning 열기', exact: true })
    .click();
  const edit = page.getByRole('dialog', { name: '이벤트 수정', exact: true });
  await expect(
    edit.getByRole('textbox', { name: '제목', exact: true }),
  ).toHaveValue('Synthetic planning');
  await edit
    .getByRole('textbox', { name: '제목', exact: true })
    .fill('Revised planning');
  await edit.getByRole('button', { name: '저장', exact: true }).click();
  await expect(edit).toBeHidden();
  await expect.poll(() => actions).toEqual(['create', 'update']);
  await page
    .getByRole('button', { name: 'Revised planning 열기', exact: true })
    .click();
  await expect(
    edit.getByRole('textbox', { name: '제목', exact: true }),
  ).toHaveValue('Revised planning');
  await edit.getByRole('button', { name: '삭제', exact: true }).click();
  await expect(edit).toBeHidden();
  await expect.poll(() => actions).toEqual(['create', 'update', 'delete']);
  await expect(
    page.getByRole('button', { name: 'Revised planning 열기', exact: true }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('Planner admission denies its editor before any personal event API request', async ({
  page,
}) => {
  const errors: string[] = [];
  const requests: string[] = [];
  await shell(page, false, errors);
  await page.route('**/api/v1/planner/**', (route) => {
    requests.push(route.request().url());
    return route.fulfill({
      status: 403,
      json: { detail: 'Synthetic admission denied' },
    });
  });
  await page.goto('/apps/planner?event=fixture-event');
  await expect(
    page.getByRole('heading', { name: '접근 권한 없음' }),
  ).toBeVisible();
  await expect(page.getByRole('dialog', { name: '이벤트 수정' })).toHaveCount(
    0,
  );
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
});
