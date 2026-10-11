import { cleanup } from '@testing-library/react';
import { afterEach as cleanupAfterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDocsCollabSnapshotSaveController } from '../views/useDocsCollabSnapshotSaveController';
import { DocsApiError, saveDocsCollabSnapshot } from './docs-api';

const snapshot = {
  updated_at: '2026-10-06T00:00:00Z',
  last_snapshot_at: '2026-10-06T00:00:00Z',
};

function abortedRequest(signal: AbortSignal): Promise<never> {
  return new Promise((_resolve, reject) => {
    if (signal.aborted) reject(signal.reason);
    else
      signal.addEventListener('abort', () => reject(signal.reason), {
        once: true,
      });
  });
}

describe('Docs snapshot request deadline', () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('preserves keepalive and caller input, then clears the deadline and abort listener', async () => {
    fetchMock.mockResolvedValue(Response.json(snapshot));
    const caller = new AbortController();
    const removeListener = vi.spyOn(caller.signal, 'removeEventListener');
    await expect(
      saveDocsCollabSnapshot(
        'token',
        'page /1',
        {
          content_blocks: [{ text: 'Saved' }],
          yjs_state: 'yjs',
        },
        { keepalive: true, signal: caller.signal },
      ),
    ).resolves.toEqual(snapshot);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      '/api/v1/docs/collab/pages/page%20%2F1/snapshot',
      expect.objectContaining({
        method: 'PUT',
        keepalive: true,
        body: JSON.stringify({
          content_blocks: [{ text: 'Saved' }],
          yjs_state: 'yjs',
        }),
        headers: expect.objectContaining({ Authorization: 'Bearer token' }),
      }),
    );
    const requestSignal = fetchMock.mock.calls[0][1]?.signal;
    expect(requestSignal).not.toBe(caller.signal);
    expect(removeListener).toHaveBeenCalledWith('abort', expect.any(Function));
    expect(vi.getTimerCount()).toBe(0);
    caller.abort();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(requestSignal?.aborted).toBe(false);
  });

  it.each(['headers', 'body'] as const)(
    'bounds the request through %s and preserves failed edits for retry',
    async (phase) => {
      fetchMock.mockImplementationOnce(async (_path, init) => {
        const signal = init?.signal;
        if (!signal) throw new Error('Expected bounded request signal');
        if (phase === 'headers') return abortedRequest(signal);
        const response = new Response();
        vi.spyOn(response, 'json').mockImplementation(() =>
          abortedRequest(signal),
        );
        return response;
      });
      const onSavedSnapshot = vi.fn();
      const { result } = renderHook(() =>
        useDocsCollabSnapshotSaveController({
          token: 'token',
          saveSnapshot: saveDocsCollabSnapshot,
          onSavedSnapshot,
          flushOnUnmount: false,
        }),
      );
      act(() =>
        result.current.queueSnapshotSave('page-1', [{ text: 'Initial' }]),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(250);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(29_999);
      });
      expect(result.current.saveFailed).toBe(false);
      expect(onSavedSnapshot).not.toHaveBeenCalled();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(result.current.saveFailed).toBe(true);
      expect(onSavedSnapshot).not.toHaveBeenCalled();
      expect(fetchMock.mock.calls[0][1]?.signal?.reason.name).toBe(
        'TimeoutError',
      );
      expect(vi.getTimerCount()).toBe(0);
      fetchMock.mockResolvedValueOnce(Response.json(snapshot));
      await act(async () => {
        await result.current.flushSnapshotSave();
      });
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(fetchMock.mock.calls[1][1]?.body).toBe(
        JSON.stringify({ content_blocks: [{ text: 'Initial' }] }),
      );
      expect(result.current.saveFailed).toBe(false);
      expect(onSavedSnapshot).toHaveBeenCalledExactlyOnceWith(snapshot);
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it.each(['headers', 'body'] as const)(
    'forwards caller abort during %s without treating it as success',
    async (phase) => {
      fetchMock.mockImplementation(async (_path, init) => {
        const signal = init?.signal;
        if (!signal) throw new Error('Expected bounded request signal');
        if (phase === 'headers') return abortedRequest(signal);
        const response = new Response();
        vi.spyOn(response, 'json').mockImplementation(() =>
          abortedRequest(signal),
        );
        return response;
      });
      const caller = new AbortController();
      const reason = new DOMException('Cancelled by caller', 'AbortError');
      const request = saveDocsCollabSnapshot(
        'token',
        'page-1',
        {},
        { signal: caller.signal },
      );
      const rejected = expect(request).rejects.toBe(reason);
      await Promise.resolve();
      caller.abort(reason);
      await rejected;
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it('does not send a request for an already aborted caller', async () => {
    const caller = new AbortController();
    caller.abort();
    await expect(
      saveDocsCollabSnapshot('token', 'page-1', {}, { signal: caller.signal }),
    ).rejects.toBe(caller.signal.reason);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('preserves a server failure and clears the deadline', async () => {
    fetchMock.mockResolvedValue(
      Response.json({ detail: 'Unavailable' }, { status: 503 }),
    );
    await expect(saveDocsCollabSnapshot('token', 'page-1', {})).rejects.toEqual(
      new DocsApiError(503, 'Unavailable'),
    );
    expect(vi.getTimerCount()).toBe(0);
  });
});

cleanupAfterEach(cleanup);
