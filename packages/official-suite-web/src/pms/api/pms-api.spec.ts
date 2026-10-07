import i18n from 'i18next';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { listPmsTaskLists, exportTaskListCsv } from './pms-api';
const fetcher = vi.fn<typeof fetch>();
beforeEach(async () => {
  await i18n.init({
    lng: 'en',
    fallbackLng: 'en',
    resources: {
      en: { apps: { pms: { errors: { exportFailed: 'Export failed' } } } },
      ko: { apps: { pms: { errors: { exportFailed: '내보내기 실패' } } } },
    },
  });
  vi.stubGlobal('fetch', fetcher);
  fetcher
    .mockReset()
    .mockResolvedValue(
      new Response('{}', { headers: { 'Content-Type': 'application/json' } }),
    );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it.each([401, 403])(
  'preserves mapped %s errors without retry',
  async (status) => {
    fetcher.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Access denied' }), { status }),
    );
    const error = await listPmsTaskLists('expired').catch(
      (err: unknown) => err,
    );
    expect(error).toBeInstanceOf(Error);
    expect(error).toMatchObject({ status, message: 'Access denied' });
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);
it('uses the host locale singleton for JSON and CSV errors', async () => {
  await i18n.changeLanguage('ko');
  await listPmsTaskLists('current');
  await i18n.changeLanguage('en');
  await listPmsTaskLists('current');
  expect(
    fetcher.mock.calls.map(([, init]) =>
      new Headers(init?.headers).get('X-MIY-Locale'),
    ),
  ).toEqual(['ko', 'en']);
  for (const [locale, message] of [
    ['ko', '내보내기 실패'],
    ['en', 'Export failed'],
  ]) {
    await i18n.changeLanguage(locale);
    fetcher.mockResolvedValueOnce(new Response('', { status: 403 }));
    await expect(
      exportTaskListCsv('current', 'list-one'),
    ).rejects.toMatchObject({ status: 403, message });
  }
});
it('retains the CSV bearer, path and object URL cleanup', async () => {
  fetcher.mockResolvedValue(
    new Response('task,title\n1,Plan', {
      headers: { 'Content-Type': 'text/csv' },
    }),
  );
  const create = vi.fn().mockReturnValue('blob:synthetic-csv'),
    revoke = vi.fn();
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    },
  );
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, 'click')
    .mockImplementation(() => undefined);
  await exportTaskListCsv('current', 'list-one');
  expect(fetcher).toHaveBeenCalledExactlyOnceWith(
    '/api/v1/pms/lists/list-one/export?format=csv',
    { headers: { Authorization: 'Bearer current' } },
  );
  expect(click).toHaveBeenCalledOnce();
  expect(create).toHaveBeenCalledOnce();
  expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:synthetic-csv');
  expect(document.querySelector('a[download]')).toBeNull();
});
