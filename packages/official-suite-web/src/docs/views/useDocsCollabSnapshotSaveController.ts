import { useCallback, useEffect, useRef, useState } from 'react';

import type {
  DocsCollabSnapshotResponse,
  saveDocsCollabSnapshot,
} from '../api/docs-api';

type SaveDocsCollabSnapshot = typeof saveDocsCollabSnapshot;

interface PendingCollabSnapshotSave {
  pageRef: string;
  contentBlocks: Record<string, unknown>[];
  yjsState?: string | null;
}

interface FlushSnapshotSaveOptions {
  keepalive?: boolean;
}

export interface DocsCollabSnapshotSaveControllerOptions {
  token: string | null | undefined;

  debounceMs?: number;
  flushOnUnmount?: boolean;
  saveSnapshot: SaveDocsCollabSnapshot;
  onSavedSnapshot?: (snapshot: DocsCollabSnapshotResponse) => void;
}

export function useDocsCollabSnapshotSaveController({
  token,
  debounceMs = 250,
  flushOnUnmount = true,
  saveSnapshot,
  onSavedSnapshot,
}: DocsCollabSnapshotSaveControllerOptions) {
  const latestConfigRef = useRef({
    token,
    saveSnapshot,
    onSavedSnapshot,
  });
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSnapshotRef = useRef<PendingCollabSnapshotSave | null>(null);
  const inFlightRef = useRef<Promise<void> | null>(null);
  const identityRef = useRef({ token });
  const mountedRef = useRef(true);
  const [failedIdentity, setFailedIdentity] = useState<object | null>(null);
  const failureRef = useRef(false);

  // A queued edit and an old response cannot cross a login boundary.
  if (identityRef.current.token !== token) {
    identityRef.current = { token };
    pendingSnapshotRef.current = null;
    // An old login's stalled request must not own the new login's save queue.
    inFlightRef.current = null;
    failureRef.current = false;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = null;
  }

  latestConfigRef.current = {
    token,
    saveSnapshot,
    onSavedSnapshot,
  };

  const clearSaveTimer = useCallback(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
  }, []);

  const flushSnapshotSave = useCallback(
    async (options: FlushSnapshotSaveOptions = {}): Promise<void> => {
      const identity = identityRef.current;
      if (inFlightRef.current) {
        await inFlightRef.current;
        if (identityRef.current !== identity) return;
        if (pendingSnapshotRef.current) await flushSnapshotSave(options);
        return;
      }
      const pending = pendingSnapshotRef.current;
      if (!pending) return;
      const config = latestConfigRef.current;
      const savingToken = config.token;
      if (!savingToken) return;
      clearSaveTimer();
      pendingSnapshotRef.current = null;
      const operation = (async () => {
        try {
          const snapshotPayload = {
            content_blocks: pending.contentBlocks,
            ...(pending.yjsState ? { yjs_state: pending.yjsState } : {}),
          };
          const snapshot = options.keepalive
            ? await config.saveSnapshot(
                savingToken,
                pending.pageRef,
                snapshotPayload,
                { keepalive: true },
              )
            : await config.saveSnapshot(
                savingToken,
                pending.pageRef,
                snapshotPayload,
              );
          if (identityRef.current === identity) {
            failureRef.current = false;
            if (mountedRef.current) {
              setFailedIdentity(null);
              config.onSavedSnapshot?.(snapshot);
            }
          }
        } catch {
          if (identityRef.current === identity) {
            // Keep the latest edit; an older failed request must not replace it.
            pendingSnapshotRef.current ??= pending;
            failureRef.current = true;
            if (mountedRef.current) setFailedIdentity(identity);
          }
        }
      })();
      inFlightRef.current = operation;
      try {
        await operation;
      } finally {
        if (inFlightRef.current === operation) inFlightRef.current = null;
      }
    },
    [clearSaveTimer],
  );

  const queueSnapshotSave = useCallback(
    (
      pageRef: string,
      contentBlocks: Record<string, unknown>[],
      yjsState?: string | null,
    ) => {
      if (!latestConfigRef.current.token) return;
      pendingSnapshotRef.current = { pageRef, contentBlocks, yjsState };
      clearSaveTimer();
      saveTimerRef.current = setTimeout(() => {
        void flushSnapshotSave();
      }, debounceMs);
    },
    [clearSaveTimer, debounceMs, flushSnapshotSave],
  );

  useEffect(() => {
    if (!flushOnUnmount) return clearSaveTimer;

    const flushBeforePageLeaves = (event: Event) => {
      if (event.type === 'beforeunload' && failureRef.current) {
        event.preventDefault();
        (event as BeforeUnloadEvent).returnValue = '';
      }
      void flushSnapshotSave({ keepalive: true });
    };
    const flushWhenHidden = () => {
      if (document.visibilityState === 'hidden') {
        void flushSnapshotSave({ keepalive: true });
      }
    };

    window.addEventListener('beforeunload', flushBeforePageLeaves);
    window.addEventListener('pagehide', flushBeforePageLeaves);
    document.addEventListener('visibilitychange', flushWhenHidden);

    return () => {
      window.removeEventListener('beforeunload', flushBeforePageLeaves);
      window.removeEventListener('pagehide', flushBeforePageLeaves);
      document.removeEventListener('visibilitychange', flushWhenHidden);
      clearSaveTimer();
      void flushSnapshotSave();
    };
  }, [clearSaveTimer, flushOnUnmount, flushSnapshotSave]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  return {
    saveFailed: failedIdentity === identityRef.current,
    flushSnapshotSave,
    queueSnapshotSave,
  };
}
