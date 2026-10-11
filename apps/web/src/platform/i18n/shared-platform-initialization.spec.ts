import { afterEach, beforeEach, expect, it, vi } from 'vitest';

beforeEach(async () => {
  vi.resetModules();
  window.localStorage.clear();
  const actual = await vi.importActual<typeof import('i18next')>('i18next');
  const singleton = actual.createInstance();
  vi.doMock('i18next', () => ({ ...actual, default: singleton }));
});

afterEach(() => {
  vi.doUnmock('i18next');
  window.localStorage.clear();
});

it.each([
  [null, 'ko-KR'],
  ['en-US', 'en-US'],
  ['unsupported', 'ko-KR'],
])(
  'uses the host locale initialization for the first request with stored locale %s',
  async (storedLocale, expectedLocale) => {
    if (storedLocale) window.localStorage.setItem('miy:locale', storedLocale);
    // The compatibility entry reaches the shared implementation without starting a host.
    const client = await import('../api/client');
    const singleton = (await import('i18next')).default;
    expect(singleton.isInitialized).not.toBe(true);
    const host = await import('./i18n');
    expect(host.i18n).toBe(singleton);
    expect(singleton.isInitialized).toBe(true);
    expect(client.jsonHeaders('session')).toMatchObject({
      'Accept-Language': expectedLocale,
      'X-MIY-Locale': expectedLocale,
    });
  },
);
