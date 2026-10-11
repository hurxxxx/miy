import i18n from 'i18next';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiRequestError,
  apiFetchBinary,
  apiFetchJson,
  apiFetchJsonWithMappedError,
} from './api-client';

beforeEach(async () => {
  await i18n.init({ lng: 'en-US', resources: {}, fallbackLng: false });
});
afterEach(() => vi.unstubAllGlobals());

describe('platform HTTP client', () => {
  it('uses the current shared locale and caller token for each request', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    await apiFetchJson('/api/example', 'first', { method: 'POST', body: '{}' });
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      cache: 'no-store',
      headers: {
        Authorization: 'Bearer first',
        'X-MIY-Locale': 'en-US',
        'Accept-Language': 'en-US',
        'Content-Type': 'application/json',
      },
    });
    await i18n.changeLanguage('ko-KR');
    await apiFetchJson('/api/example', null);
    expect(fetcher.mock.calls[1][1].headers).toEqual({
      Accept: 'application/json',
      'X-MIY-Locale': 'ko-KR',
      'Accept-Language': 'ko-KR',
    });
  });

  it('preserves multipart boundaries, request cancellation and empty responses', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetcher);
    const signal = new AbortController().signal;
    expect(
      await apiFetchJson('/upload', 'session', {
        method: 'POST',
        body: new FormData(),
        signal,
      }),
    ).toBeUndefined();
    expect(fetcher.mock.calls[0][1].headers['Content-Type']).toBeUndefined();
    expect(fetcher.mock.calls[0][1].signal).toBe(signal);
  });

  it('keeps server error details and domain error mapping', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementation(
          async () =>
            new Response(JSON.stringify({ detail: 'Access withdrawn' }), {
              status: 403,
            }),
        ),
    );
    await expect(apiFetchJson('/items', 'session')).rejects.toMatchObject({
      status: 403,
      message: 'Access withdrawn',
      payload: { detail: 'Access withdrawn' },
    });
    const map = vi.fn(
      (error: ApiRequestError) => new Error(`domain:${error.status}`),
    );
    await expect(
      apiFetchJsonWithMappedError('/items', 'session', {}, map),
    ).rejects.toThrow('domain:403');
    expect(map.mock.calls[0][0]).toBeInstanceOf(ApiRequestError);
  });

  it('preserves authenticated binary response metadata', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response('preview', {
          headers: {
            'Content-Type': 'image/png',
            'Content-Disposition': 'inline; filename=preview.png',
          },
        }),
      );
    vi.stubGlobal('fetch', fetcher);
    const result = await apiFetchBinary('/preview', 'session');
    expect(fetcher.mock.calls[0][1].headers).toMatchObject({
      Authorization: 'Bearer session',
      Accept: '*/*',
    });
    expect(result.contentType).toBe('image/png');
    expect(result.contentDisposition).toBe('inline; filename=preview.png');
    expect(await result.blob.text()).toBe('preview');
  });
});
