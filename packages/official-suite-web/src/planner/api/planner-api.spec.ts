import i18n from 'i18next';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import {
  createPlannerEvent,
  deletePlannerEvent,
  getPlannerEvent,
  listPlannerEvents,
  PlannerApiError,
  updatePlannerEvent,
} from './planner-api';

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

it('retains personal event paths, methods, payloads and the current bearer', async () => {
  const body = {
    title: 'Plan',
    allDay: true,
    start: '2026-03-07',
    end: '2026-03-09',
  };
  await listPlannerEvents('session', { from: body.start, to: body.end });
  await getPlannerEvent('session', 'event-1');
  await createPlannerEvent('session', body);
  await updatePlannerEvent('session', 'event-1', { title: 'Revised' });
  fetcher.mockResolvedValueOnce(new Response(null, { status: 204 }));
  await expect(
    deletePlannerEvent('session', 'event-1'),
  ).resolves.toBeUndefined();
  expect(
    fetcher.mock.calls.map(([path, init]) => [path, init?.method ?? 'GET']),
  ).toEqual([
    ['/api/v1/planner/events?from=2026-03-07&to=2026-03-09', 'GET'],
    ['/api/v1/planner/events/event-1', 'GET'],
    ['/api/v1/planner/events', 'POST'],
    ['/api/v1/planner/events/event-1', 'PATCH'],
    ['/api/v1/planner/events/event-1', 'DELETE'],
  ]);
  for (const [, init] of fetcher.mock.calls)
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      'Bearer session',
    );
  expect(JSON.parse(fetcher.mock.calls[2][1]?.body as string)).toEqual(body);
});

it('keeps unauthorized errors typed without silently retrying', async () => {
  fetcher.mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: 'Session expired' }), {
      status: 401,
    }),
  );
  const error = await listPlannerEvents('expired').catch(
    (failure: unknown) => failure,
  );
  expect(error).toBeInstanceOf(PlannerApiError);
  expect(error).toMatchObject({ status: 401, message: 'Session expired' });
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it('uses the same host i18next locale for Korean and English requests', async () => {
  await i18n.changeLanguage('ko-KR');
  await listPlannerEvents('session');
  await i18n.changeLanguage('en-US');
  await listPlannerEvents('session');
  expect(
    fetcher.mock.calls.map(([, init]) =>
      new Headers(init?.headers).get('X-MIY-Locale'),
    ),
  ).toEqual(['ko-KR', 'en-US']);
});
