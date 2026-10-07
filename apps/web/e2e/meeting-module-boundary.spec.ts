import type { ApiSchema } from '@miy/contracts/api';
import { expect, test, type Page } from '@playwright/test';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

const timestamp = '2026-10-07T09:00:00Z';
const meeting: ApiSchema<'MeetingDetail'> = {
  id: 'structural-meeting',
  organizer_id: 'fixture-organizer',
  organizer_name: 'Synthetic organizer',
  title: 'Structural meeting',
  agenda: 'Synthetic read-only agenda',
  start_at: timestamp,
  end_at: '2026-10-07T10:00:00Z',
  status: 'scheduled',
  notes_doc_id: null,
  notes_page_id: null,
  attendees: [],
  task_links: [],
  doc_links: [],
  file_attachments: [],
  recordings: [],
  created_at: timestamp,
  updated_at: timestamp,
};
const item: ApiSchema<'MeetingListItem'> = {
  id: meeting.id,
  title: meeting.title,
  organizer_id: meeting.organizer_id,
  organizer_name: meeting.organizer_name,
  start_at: meeting.start_at,
  end_at: meeting.end_at,
  status: meeting.status,
  attendee_count: 0,
  task_link_count: 0,
  doc_link_count: 0,
};

// Only module initialization, public lazy composition and admission are in
// scope. Every API is synthetic; no data, audio, AI or file mutation is used.
async function setup(page: Page, enabledAppIds: string[]) {
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) =>
      route.fulfill({ status: 501, json: { detail: 'Synthetic route' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, { enabledAppIds });
  await stubConversationsApi(page);
  const evidence = {
    errors: [] as string[],
    lists: [] as string[],
    details: 0,
    docs: 0,
    unexpected: [] as string[],
    microphones: 0,
  };
  page.on('pageerror', (error) => evidence.errors.push(error.message));
  await page.exposeFunction('structuralMeetingMicrophoneRequest', () => {
    evidence.microphones += 1;
    throw new Error('Audio use is outside this structural fixture');
  });
  await page.addInitScript(() => {
    if (navigator.mediaDevices) {
      navigator.mediaDevices.getUserMedia = () =>
        (
          window as unknown as {
            structuralMeetingMicrophoneRequest: () => Promise<MediaStream>;
          }
        ).structuralMeetingMicrophoneRequest();
    }
  });
  await page.route('**/api/v1/meeting/**', (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === 'GET') {
      if (url.pathname === '/api/v1/meeting/meetings') {
        evidence.lists.push(url.search);
        return route.fulfill({ json: { items: [item], total: 1 } });
      }
      if (url.pathname === `/api/v1/meeting/meetings/${meeting.id}`) {
        evidence.details += 1;
        return route.fulfill({ json: meeting });
      }
      if (url.pathname === '/api/v1/meeting/users')
        return route.fulfill({ json: [] });
      if (url.pathname === '/api/v1/meeting/availability')
        return route.fulfill({ json: { items: [] } });
    }
    evidence.unexpected.push(`${request.method()} ${url.pathname}`);
    return route.fulfill({ status: 501, json: { detail: 'Synthetic route' } });
  });
  await page.route('**/api/v1/recording/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (
      request.method() === 'GET' &&
      path === '/api/v1/recording/recordings/staging'
    )
      return route.fulfill({ json: [] });
    evidence.unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 501, json: { detail: 'Synthetic route' } });
  });
  await page.route('**/api/v1/docs/**', (route) => {
    evidence.docs += 1;
    return route.fulfill({ status: 403, json: { detail: 'Synthetic denial' } });
  });
  return evidence;
}

test('Meeting owned list opens the shared form without creating a meeting', async ({
  page,
}) => {
  const evidence = await setup(page, ['meeting']);
  await page.goto('/apps/meeting');
  await expect(
    page.getByRole('button', { name: new RegExp(meeting.title) }),
  ).toBeVisible();
  await page.getByRole('button', { name: '새 회의', exact: true }).click();
  const form = page.getByRole('dialog', { name: '새 회의', exact: true });
  await expect(form).toBeVisible();
  await expect(
    form.getByRole('button', { name: '회의 만들기', exact: true }),
  ).toBeDisabled();
  await form.getByRole('button', { name: '취소', exact: true }).click();
  await expect(form).toBeHidden();
  expect(evidence.lists.length).toBeGreaterThan(0);
  expect(evidence.details).toBe(0);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.microphones).toBe(0);
  expect(evidence.errors).toEqual([]);
});

test('Meeting detail loads its moved layout without denied Docs reads or note creation', async ({
  page,
}) => {
  const evidence = await setup(page, ['meeting']);
  await page.goto(`/apps/meeting/meetings/${meeting.id}`);
  await expect(page.getByRole('status')).toHaveText(
    '현재 볼 수 있는 회의 노트가 없습니다. 회의 상세 정보는 아래에서 확인할 수 있습니다.',
  );
  await expect(page.getByText(meeting.agenda, { exact: true })).toBeVisible();
  expect(evidence.details).toBeGreaterThan(0);
  expect(evidence.docs).toBe(0);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.microphones).toBe(0);
  expect(evidence.errors).toEqual([]);
});

test('Meeting admission blocks the owned list before any Meeting data read', async ({
  page,
}) => {
  const evidence = await setup(page, ['home']);
  await page.goto('/apps/meeting');
  await expect(
    page.getByRole('heading', { name: '접근 권한 없음' }),
  ).toBeVisible();
  expect(evidence.lists).toEqual([]);
  expect(evidence.details).toBe(0);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.microphones).toBe(0);
  expect(evidence.errors).toEqual([]);
});

test('Planner opens and closes the public lazy Meeting form', async ({
  page,
}) => {
  const evidence = await setup(page, ['planner', 'meeting']);
  await page.goto('/apps/planner?view=timeline');
  await expect(
    page.getByRole('heading', { name: '플래너', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: '추가', exact: true }).click();
  await page.getByRole('button', { name: '회의', exact: true }).click();
  const form = page.getByRole('dialog', { name: '새 회의', exact: true });
  await expect(form).toBeVisible();
  await form.getByRole('button', { name: '취소', exact: true }).click();
  await expect(form).toBeHidden();
  expect(evidence.details).toBe(0);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.microphones).toBe(0);
  expect(evidence.errors).toEqual([]);
});
