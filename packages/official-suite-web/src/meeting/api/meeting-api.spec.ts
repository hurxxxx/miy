import i18n from 'i18next';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  MeetingApiError,
  listMeetings,
  getMeeting,
  updateMeeting,
  uploadMeetingFile,
  uploadRecordingChunk,
  getMeetingAvailability,
  parseServerDateTime,
} from './meeting-api';

const fetcher = vi.fn<typeof fetch>();
beforeEach(async () => {
  await i18n.init({ lng: 'en-US', fallbackLng: 'en-US', resources: {} });
  vi.stubGlobal('fetch', fetcher);
  fetcher.mockReset().mockImplementation(
    async () =>
      new Response('{}', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  );
});
afterEach(() => vi.unstubAllGlobals());

it('preserves list, detail and update paths, token, JSON and repeated availability parameters', async () => {
  await listMeetings('session', {
    scope: 'all',
    from: '2026-03-08T06:00:00Z',
    to: '2026-03-08T08:00:00Z',
  });
  await getMeeting('session', 'meeting-one');
  await updateMeeting('session', 'meeting-one', { title: 'Updated meeting' });
  await getMeetingAvailability('session', {
    userIds: ['one', 'two'],
    from: 'start',
    to: 'end',
  });
  expect(
    fetcher.mock.calls.map(([path, init]) => [path, init?.method ?? 'GET']),
  ).toEqual([
    [
      '/api/v1/meeting/meetings?scope=all&from=2026-03-08T06%3A00%3A00Z&to=2026-03-08T08%3A00%3A00Z',
      'GET',
    ],
    ['/api/v1/meeting/meetings/meeting-one', 'GET'],
    ['/api/v1/meeting/meetings/meeting-one', 'PATCH'],
    [
      '/api/v1/meeting/availability?user_ids=one&user_ids=two&from=start&to=end',
      'GET',
    ],
  ]);
  expect(JSON.parse(fetcher.mock.calls[2][1]?.body as string)).toEqual({
    title: 'Updated meeting',
  });
  for (const [, init] of fetcher.mock.calls)
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      'Bearer session',
    );
});
it('preserves multipart boundary ownership and recording checksum headers without uploading anywhere', async () => {
  const file = new File(['synthetic'], 'notes.txt');
  await uploadMeetingFile('session', 'meeting-one', file);
  await uploadRecordingChunk(
    'session',
    'meeting-one',
    'staging-one',
    2,
    new Blob(['synthetic']),
    'digest',
  );
  expect(fetcher.mock.calls[0][0]).toBe(
    '/api/v1/meeting/meetings/meeting-one/files',
  );
  expect(fetcher.mock.calls[1][0]).toBe(
    '/api/v1/meeting/meetings/meeting-one/recordings/staging/staging-one/chunks/2',
  );
  for (const [, init] of fetcher.mock.calls) {
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get('file')).toBeInstanceOf(File);
    expect(new Headers(init?.headers).get('Content-Type')).toBeNull();
  }
  expect(
    new Headers(fetcher.mock.calls[1][1]?.headers).get('X-Chunk-Sha256'),
  ).toBe('digest');
});
it.each([401, 403])(
  'keeps %s typed and never retries authentication',
  async (status) => {
    fetcher.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Meeting denied' }), { status }),
    );
    const error = await listMeetings('expired').catch(
      (error: unknown) => error,
    );
    expect(error).toBeInstanceOf(MeetingApiError);
    expect(error).toMatchObject({ status, message: 'Meeting denied' });
    expect(fetcher).toHaveBeenCalledOnce();
  },
);
it('uses the already initialized host language singleton', async () => {
  await i18n.changeLanguage('ko-KR');
  await listMeetings('session');
  await i18n.changeLanguage('en-US');
  await listMeetings('session');
  expect(
    fetcher.mock.calls.map(([, init]) =>
      new Headers(init?.headers).get('X-MIY-Locale'),
    ),
  ).toEqual(['ko-KR', 'en-US']);
});
it('keeps naive API datetime UTC across spring and autumn local DST boundaries', () => {
  for (const value of [
    '2026-03-08T06:30:00',
    '2026-03-08T07:30:00',
    '2026-11-01T05:30:00',
    '2026-11-01T06:30:00',
  ])
    expect(parseServerDateTime(value).toISOString()).toBe(`${value}.000Z`);
  expect(parseServerDateTime('2026-10-07T09:00:00+09:00').toISOString()).toBe(
    '2026-10-07T00:00:00.000Z',
  );
  expect(Number.isNaN(parseServerDateTime('invalid').getTime())).toBe(true);
});
