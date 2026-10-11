import i18n from 'i18next';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  VideoChatApiError,
  listVideoChatSessions,
  createVideoChatSession,
  getVideoChatSession,
  createVideoChatJoinToken,
  endVideoChatSession,
  startVideoChatRecording,
  stopVideoChatRecording,
  startVideoChatCaptions,
  stopVideoChatCaptions,
} from './video-chat-api';
const fetcher = vi.fn<typeof fetch>();
beforeEach(async () => {
  await i18n.init({ lng: 'en-US', fallbackLng: 'en-US', resources: {} });
  vi.stubGlobal('fetch', fetcher);
  fetcher
    .mockReset()
    .mockImplementation(
      async () =>
        new Response('{}', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    );
});
afterEach(() => vi.unstubAllGlobals());
it('retains lobby and legacy room endpoint methods, payloads and bearer', async () => {
  await listVideoChatSessions('session', 'open');
  await createVideoChatSession('session', {
    title: 'Plan',
    meeting_id: 'meeting-1',
  });
  await getVideoChatSession('session', 'room-1');
  await createVideoChatJoinToken('session', 'room-1');
  await endVideoChatSession('session', 'room-1');
  await startVideoChatRecording('session', 'room-1');
  await stopVideoChatRecording('session', 'room-1');
  await startVideoChatCaptions('session', 'room-1');
  await stopVideoChatCaptions('session', 'room-1');
  expect(
    fetcher.mock.calls.map(([path, init]) => [path, init?.method ?? 'GET']),
  ).toEqual([
    ['/api/v1/video-chat/sessions?status=open', 'GET'],
    ['/api/v1/video-chat/sessions', 'POST'],
    ['/api/v1/video-chat/sessions/room-1', 'GET'],
    ['/api/v1/video-chat/sessions/room-1/join-token', 'POST'],
    ['/api/v1/video-chat/sessions/room-1/end', 'POST'],
    ['/api/v1/video-chat/sessions/room-1/recording/start', 'POST'],
    ['/api/v1/video-chat/sessions/room-1/recording/stop', 'POST'],
    ['/api/v1/video-chat/sessions/room-1/captions/start', 'POST'],
    ['/api/v1/video-chat/sessions/room-1/captions/stop', 'POST'],
  ]);
  for (const [, init] of fetcher.mock.calls)
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      'Bearer session',
    );
  expect(JSON.parse(fetcher.mock.calls[1][1]?.body as string)).toEqual({
    title: 'Plan',
    meeting_id: 'meeting-1',
  });
});
it.each([401, 403])(
  'keeps %s failures typed and does not retry or exchange credentials',
  async (status) => {
    fetcher.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Access denied' }), { status }),
    );
    const error = await listVideoChatSessions('expired').catch(
      (failure: unknown) => failure,
    );
    expect(error).toBeInstanceOf(VideoChatApiError);
    expect(error).toMatchObject({ status, message: 'Access denied' });
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);
it('uses the host i18next singleton for both request locales', async () => {
  await i18n.changeLanguage('ko-KR');
  await listVideoChatSessions('session');
  await i18n.changeLanguage('en-US');
  await listVideoChatSessions('session');
  expect(
    fetcher.mock.calls.map(([, init]) =>
      new Headers(init?.headers).get('X-MIY-Locale'),
    ),
  ).toEqual(['ko-KR', 'en-US']);
});
