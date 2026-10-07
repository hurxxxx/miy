import { afterEach, beforeEach, expect, it, vi } from 'vitest';

beforeEach(async () => {
  vi.resetModules();
  const actual = await vi.importActual<typeof import('i18next')>('i18next');
  const singleton = actual.createInstance();
  vi.doMock('i18next', () => ({ ...actual, default: singleton }));
});
afterEach(() => vi.doUnmock('i18next'));

it('does not initialize a host when common auth, media and locale APIs are imported', async () => {
  const locale = await import('./index');
  await import('../auth-api');
  await import('../media/use-media-upload');
  const singleton = (await import('i18next')).default;
  expect(locale.i18n).toBe(singleton);
  expect(singleton.isInitialized).not.toBe(true);
});
