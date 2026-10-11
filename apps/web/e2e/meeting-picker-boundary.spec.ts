import { expect, test, type Page } from '@playwright/test';
import { buildAppHref } from '@miy/contracts/app-routes';
import type { ApiSchema } from '@miy/contracts/api';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

const timestamp = '2026-10-07T09:00:00Z';
const meeting: ApiSchema<'MeetingListItem'> = {
  id: 'synthetic-meeting',
  title: 'Synthetic planning meeting',
  organizer_id: 'user-e2e',
  organizer_name: 'Fixture owner',
  start_at: timestamp,
  end_at: '2026-10-07T10:00:00Z',
  status: 'scheduled',
  attendee_count: 1,
  task_link_count: 0,
  doc_link_count: 0,
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

async function setup(page: Page, meetingEnabled: boolean) {
  // No unhandled transport may reach a live API, storage or media source.
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({ status: 501, json: { detail: 'Unconfigured fixture' } }),
  );
  await stubAppDataBackend(page);
  await stubShellBackend(page, {
    enabledAppIds: meetingEnabled
      ? ['home', 'recording', 'meeting']
      : ['home', 'recording'],
  });
  await stubConversationsApi(page);
  const evidence = {
    lists: [] as string[],
    mutations: [] as unknown[],
    errors: [] as string[],
    completeAttachment: (): void => undefined,
  };
  page.on('pageerror', (error) => evidence.errors.push(error.message));
  let current = { ...recording };
  const attachmentReady = new Promise<void>((resolve) => {
    evidence.completeAttachment = resolve;
  });
  await page.route('**/api/v1/meeting/**', (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (
      request.method() === 'GET' &&
      url.pathname === '/api/v1/meeting/meetings'
    ) {
      evidence.lists.push(url.search);
      return route.fulfill({ json: { items: [meeting], total: 1 } });
    }
    evidence.errors.push(
      `Unexpected Meeting fixture: ${request.method()} ${url.pathname}`,
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
      path === '/api/v1/recording/recordings/synthetic-recording'
    )
      return route.fulfill({ json: current });
    if (request.method() === 'GET' && path === '/api/v1/recording/recordings')
      return route.fulfill({ json: { items: [], total: 0 } });
    if (
      request.method() === 'POST' &&
      path === '/api/v1/recording/recordings/synthetic-recording/targets'
    ) {
      evidence.mutations.push(request.postDataJSON());
      await attachmentReady;
      current = {
        ...recording,
        targets: [
          {
            id: 'synthetic-link',
            recording_id: recording.id,
            target_app: 'meeting',
            target_type: 'meeting',
            target_id: meeting.id,
            target_title: meeting.title,
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
    page.getByRole('button', { name: '회의 추가', exact: true }),
  ).toBeVisible();
  return evidence;
}

test('Recording uses the public Meeting picker, preserves explicit attachment and excludes an existing link', async ({
  page,
}) => {
  const evidence = await setup(page, true);
  expect(evidence.lists).toEqual([]);
  expect(evidence.mutations).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '회의 추가', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '회의 추가', exact: true });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole('button', { name: new RegExp(meeting.title) }),
  ).toBeVisible();
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds?.width).toBeLessThanOrEqual(390);
  const search = dialog.getByRole('textbox', { name: '검색', exact: true });
  await search.fill('missing');
  await expect(
    dialog.getByText('연결할 수 있는 회의가 없습니다.'),
  ).toBeVisible();
  await search.fill('planning');
  expect(evidence.mutations).toEqual([]);
  await dialog.getByRole('button', { name: new RegExp(meeting.title) }).click();
  // Existing Recording onPick returns void. Closing does not claim server success.
  await expect(dialog).toBeHidden();
  await expect.poll(() => evidence.mutations.length).toBe(1);
  expect(evidence.mutations).toEqual([
    {
      target_app: 'meeting',
      target_type: 'meeting',
      target_id: meeting.id,
    },
  ]);
  evidence.completeAttachment();
  const meetingLink = page.getByRole('link', {
    name: `${meeting.title} 회의`,
    exact: true,
  });
  await expect(meetingLink).toBeVisible();
  await expect(meetingLink).toHaveAttribute(
    'href',
    buildAppHref({
      routeId: 'meeting.detail',
      pathParams: { meetingId: meeting.id },
    }),
  );
  await page.getByRole('button', { name: '회의 추가', exact: true }).click();
  await expect(dialog).toBeVisible();
  await expect(search).toHaveValue('');
  await expect(
    dialog.getByText('연결할 수 있는 회의가 없습니다.'),
  ).toBeVisible();
  await dialog
    .getByRole('button', { name: '닫기', exact: true })
    .last()
    .click();
  await expect(dialog).toBeHidden();
  expect(evidence.lists).toEqual(['?scope=all', '?scope=all']);
  expect(evidence.mutations).toHaveLength(1);
  expect(evidence.errors).toEqual([]);
});

test('Recording stays accessible while denied Meeting admission blocks picker data and attachment', async ({
  page,
}) => {
  const evidence = await setup(page, false);
  await page.getByRole('button', { name: '회의 추가', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '회의 추가', exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('alert')).toBeVisible();
  await expect(dialog.getByRole('textbox')).toHaveCount(0);
  await dialog
    .getByRole('button', { name: '닫기', exact: true })
    .last()
    .click();
  await expect(dialog).toBeHidden();
  expect(evidence.lists).toEqual([]);
  expect(evidence.mutations).toEqual([]);
  expect(evidence.errors).toEqual([]);
});
