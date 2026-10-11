import { cleanup } from '@testing-library/react';
import { afterEach as cleanupAfterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  DocsCollabSnapshotResponse,
  saveDocsCollabSnapshot,
} from '../api/docs-api';
import {
  type DocsCollabSnapshotSaveControllerOptions,
  useDocsCollabSnapshotSaveController,
} from './useDocsCollabSnapshotSaveController';

type SaveDocsCollabSnapshot = typeof saveDocsCollabSnapshot;

function renderController(
  overrides: Partial<DocsCollabSnapshotSaveControllerOptions> = {},
) {
  const snapshot: DocsCollabSnapshotResponse = {
    updated_at: '2026-06-19T00:00:00Z',
    last_snapshot_at: '2026-06-19T00:00:00Z',
  };
  const saveSnapshot = vi.fn<SaveDocsCollabSnapshot>(async () => snapshot);
  const onSavedSnapshot = vi.fn<(saved: DocsCollabSnapshotResponse) => void>();
  const hook = renderHook(() =>
    useDocsCollabSnapshotSaveController({
      token: 'token-1',
      saveSnapshot,
      onSavedSnapshot,
      ...overrides,
    }),
  );

  return { ...hook, onSavedSnapshot, saveSnapshot, snapshot };
}

describe('useDocsCollabSnapshotSaveController', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('debounces collaboration snapshot saves and persists the latest blocks', async () => {
    vi.useFakeTimers();
    const { result, saveSnapshot, onSavedSnapshot, snapshot } =
      renderController({});
    const oldBlocks = [{ type: 'paragraph', content: [{ text: 'Old' }] }];
    const latestBlocks = [{ type: 'paragraph', content: [{ text: 'Latest' }] }];

    act(() => {
      result.current.queueSnapshotSave('native_doc_page__page-1', oldBlocks);
      result.current.queueSnapshotSave('native_doc_page__page-1', latestBlocks);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });

    expect(saveSnapshot).toHaveBeenCalledTimes(1);
    expect(saveSnapshot).toHaveBeenCalledWith(
      'token-1',
      'native_doc_page__page-1',
      { content_blocks: latestBlocks },
    );
    expect(onSavedSnapshot).toHaveBeenCalledWith(snapshot);
  });

  it('flushes a pending collaboration snapshot immediately', async () => {
    vi.useFakeTimers();
    const { result, saveSnapshot } = renderController();
    const blocks = [{ type: 'paragraph', content: [{ text: 'Draft' }] }];

    act(() => {
      result.current.queueSnapshotSave('native_doc_page__page-1', blocks);
    });
    await act(async () => {
      await result.current.flushSnapshotSave();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });

    expect(saveSnapshot).toHaveBeenCalledTimes(1);
    expect(saveSnapshot).toHaveBeenCalledWith(
      'token-1',
      'native_doc_page__page-1',
      { content_blocks: blocks },
    );
  });

  it('includes the latest Yjs state when one is provided', async () => {
    vi.useFakeTimers();
    const { result, saveSnapshot } = renderController();
    const blocks = [{ type: 'paragraph', content: [{ text: 'Yjs' }] }];

    act(() => {
      result.current.queueSnapshotSave(
        'native_doc_page__page-1',
        blocks,
        'base64-yjs-state',
      );
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });

    expect(saveSnapshot).toHaveBeenCalledWith(
      'token-1',
      'native_doc_page__page-1',
      { content_blocks: blocks, yjs_state: 'base64-yjs-state' },
    );
  });

  it('flushes a pending collaboration snapshot with keepalive before page unload', async () => {
    vi.useFakeTimers();
    const { result, saveSnapshot } = renderController();
    const blocks = [{ type: 'paragraph', content: [{ text: 'Unload' }] }];

    act(() => {
      result.current.queueSnapshotSave('native_doc_page__page-1', blocks);
      window.dispatchEvent(new Event('pagehide'));
    });

    expect(saveSnapshot).toHaveBeenCalledTimes(1);
    expect(saveSnapshot).toHaveBeenCalledWith(
      'token-1',
      'native_doc_page__page-1',
      { content_blocks: blocks },
      { keepalive: true },
    );
  });

  it('does not save without a token', async () => {
    vi.useFakeTimers();
    const { result, saveSnapshot } = renderController({ token: null });

    act(() => {
      result.current.queueSnapshotSave('native_doc_page__page-1', []);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });

    expect(saveSnapshot).not.toHaveBeenCalled();
  });

  it('retains a failed snapshot for explicit retry and reports only confirmed saves', async () => {
    vi.useFakeTimers();
    const { result, saveSnapshot, onSavedSnapshot, snapshot } =
      renderController();
    saveSnapshot.mockRejectedValueOnce(new Error('unavailable'));
    const blocks = [{ type: 'paragraph', content: [{ text: 'Unsaved' }] }];
    act(() => result.current.queueSnapshotSave('page-1', blocks, 'yjs-1'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(result.current.saveFailed).toBe(true);
    expect(onSavedSnapshot).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(saveSnapshot).toHaveBeenCalledTimes(1);
    await act(async () => {
      await result.current.flushSnapshotSave();
    });
    expect(saveSnapshot).toHaveBeenLastCalledWith('token-1', 'page-1', {
      content_blocks: blocks,
      yjs_state: 'yjs-1',
    });
    expect(result.current.saveFailed).toBe(false);
    expect(onSavedSnapshot).toHaveBeenCalledExactlyOnceWith(snapshot);
  });

  it('serializes saves and keeps a newer edit when the first request fails', async () => {
    vi.useFakeTimers();
    const { result, saveSnapshot } = renderController();
    let rejectFirst!: (reason: Error) => void;
    saveSnapshot.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectFirst = reject;
        }),
    );
    act(() => result.current.queueSnapshotSave('page-1', [{ text: 'Old' }]));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    const latest = [{ text: 'Latest' }];
    act(() => result.current.queueSnapshotSave('page-1', latest));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(saveSnapshot).toHaveBeenCalledTimes(1);
    await act(async () => {
      rejectFirst(new Error('unavailable'));
    });
    expect(saveSnapshot).toHaveBeenCalledTimes(2);
    expect(saveSnapshot).toHaveBeenLastCalledWith('token-1', 'page-1', {
      content_blocks: latest,
    });
    expect(result.current.saveFailed).toBe(false);
  });

  it.each([false, true])(
    'separates new login edits from a stale response (failure=%s)',
    async (failOld) => {
      vi.useFakeTimers();
      const snapshot = {
        updated_at: '2026-10-06T00:00:00Z',
        last_snapshot_at: '2026-10-06T00:00:00Z',
      };
      let complete!: (result: DocsCollabSnapshotResponse) => void;
      let reject!: (reason: Error) => void;
      const saveSnapshot = vi
        .fn<SaveDocsCollabSnapshot>(async () => snapshot)
        .mockImplementationOnce(
          () =>
            new Promise((resolve, rejectPromise) => {
              complete = resolve;
              reject = rejectPromise;
            }),
        );
      const onSavedSnapshot = vi.fn();
      const { result, rerender } = renderHook(
        ({ token }) =>
          useDocsCollabSnapshotSaveController({
            token,
            saveSnapshot,
            onSavedSnapshot,
          }),
        { initialProps: { token: 'token-1' } },
      );
      act(() =>
        result.current.queueSnapshotSave('page-1', [{ text: 'In flight' }]),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(250);
      });
      act(() =>
        result.current.queueSnapshotSave('page-1', [{ text: 'Pending' }]),
      );
      rerender({ token: 'token-2' });
      act(() =>
        result.current.queueSnapshotSave('page-1', [{ text: 'New login' }]),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(250);
      });
      // A stalled request from the old login cannot delay the new login.
      expect(saveSnapshot).toHaveBeenCalledTimes(2);
      expect(onSavedSnapshot).toHaveBeenCalledExactlyOnceWith(snapshot);
      await act(async () => {
        if (failOld) reject(new Error('old request failed'));
        else complete(snapshot);
      });
      expect(saveSnapshot).toHaveBeenCalledTimes(2);
      expect(saveSnapshot).toHaveBeenLastCalledWith('token-2', 'page-1', {
        content_blocks: [{ text: 'New login' }],
      });
      expect(onSavedSnapshot).toHaveBeenCalledExactlyOnceWith(snapshot);
      expect(result.current.saveFailed).toBe(false);
    },
  );

  it('does not let an old login waiter flush or release the new login request', async () => {
    vi.useFakeTimers();
    const snapshot = {
      updated_at: '2026-10-06T00:00:00Z',
      last_snapshot_at: '2026-10-06T00:00:00Z',
    };
    let completeOld!: (result: DocsCollabSnapshotResponse) => void;
    let completeNew!: (result: DocsCollabSnapshotResponse) => void;
    const saveSnapshot = vi
      .fn<SaveDocsCollabSnapshot>(async () => snapshot)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            completeOld = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            completeNew = resolve;
          }),
      );
    const { result, rerender } = renderHook(
      ({ token }) =>
        useDocsCollabSnapshotSaveController({ token, saveSnapshot }),
      { initialProps: { token: 'old-login' } },
    );
    act(() =>
      result.current.queueSnapshotSave('page-1', [{ text: 'Old request' }]),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    act(() =>
      result.current.queueSnapshotSave('page-1', [{ text: 'Old pending' }]),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    rerender({ token: 'new-login' });
    act(() =>
      result.current.queueSnapshotSave('page-1', [{ text: 'New request' }]),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    act(() => result.current.queueSnapshotSave('page-1', [{ text: 'Latest' }]));
    await act(async () => {
      completeOld(snapshot);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(saveSnapshot).toHaveBeenCalledTimes(2);
    await act(async () => {
      completeNew(snapshot);
    });
    expect(saveSnapshot).toHaveBeenCalledTimes(3);
    expect(saveSnapshot).toHaveBeenLastCalledWith('new-login', 'page-1', {
      content_blocks: [{ text: 'Latest' }],
    });
    expect(result.current.saveFailed).toBe(false);
  });

  it('requests a leave confirmation only after a failed save', async () => {
    vi.useFakeTimers();
    const { result, saveSnapshot } = renderController();
    saveSnapshot.mockRejectedValue(new Error('unavailable'));
    const cleanLeave = new Event('beforeunload', { cancelable: true });
    act(() => {
      window.dispatchEvent(cleanLeave);
    });
    expect(cleanLeave.defaultPrevented).toBe(false);
    act(() => result.current.queueSnapshotSave('page-1', [{ text: 'Keep' }]));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    const failedLeave = new Event('beforeunload', { cancelable: true });
    await act(async () => {
      window.dispatchEvent(failedLeave);
    });
    expect(failedLeave.defaultPrevented).toBe(true);
    expect(result.current.saveFailed).toBe(true);
  });

  it('cancels the timer when unmounted with flushing disabled', async () => {
    vi.useFakeTimers();
    const { result, saveSnapshot, unmount } = renderController({
      flushOnUnmount: false,
    });
    act(() => result.current.queueSnapshotSave('page-1', []));
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(saveSnapshot).not.toHaveBeenCalled();
  });
});

cleanupAfterEach(cleanup);
