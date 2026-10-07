import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  checkedIndependentFileSelectionRequest,
  type IndependentFileSelectionMetadata,
  type IndependentFileSelectionRequest,
  type IndependentFileSelectionResult,
} from './independent-app-host';
import {
  authorizeFileSelection,
  getFileCandidates,
  type FileCandidatePage,
} from './independent-app-files';
import type { IndependentNavigationSource } from './independent-app-navigation';

export interface FilePickerView extends FileCandidatePage {
  scope: object;
  requestId: string;
  query: string;
  phase: 'loading' | 'ready' | 'confirming' | 'unknown';
  selected: IndependentFileSelectionMetadata | null;
  error: 'loadFailed' | 'selectionUnknown' | null;
}

interface Pending {
  view: FilePickerView;
  request: IndependentFileSelectionRequest;
  controller: AbortController;
  isCurrent: () => boolean;
  expiresAt: number;
  end: (result: IndependentFileSelectionResult) => void;
  load?: AbortController;
}

/** One explicit selection tied to the exact mounted app document and MIY login. */
export function useIndependentAppFiles({
  token,
  actorId,
  source,
  documentVersion,
}: {
  token: string | null;
  actorId: string | null;
  source: IndependentNavigationSource | null;
  documentVersion: string;
}) {
  const scope = useMemo(
    () => ({}),
    [
      token,
      actorId,
      source?.appId,
      source?.installationId,
      source?.origin,
      source?.generation,
      source?.entrypoint,
      documentVersion,
    ],
  );
  const latest = useRef(scope);
  latest.current = scope;
  const active = useRef(false);
  const pending = useRef<Pending | null>(null);
  const [view, setView] = useState<FilePickerView | null>(null);
  useLayoutEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      pending.current?.end({ status: 'unavailable' });
    };
  }, [scope]);
  const live = useCallback(
    (item: Pending) =>
      active.current &&
      latest.current === scope &&
      item.view.scope === scope &&
      pending.current === item &&
      !item.controller.signal.aborted &&
      item.isCurrent() &&
      Date.now() < item.expiresAt,
    [scope],
  );

  const load = useCallback(
    async (item: Pending, query: string, cursor: string | null) => {
      if (
        !token ||
        !live(item) ||
        query.length > 120 ||
        item.view.phase === 'confirming' ||
        item.view.phase === 'unknown'
      )
        return;
      item.load?.abort();
      const controller = new AbortController();
      item.load = controller;
      const cancel = () => controller.abort();
      item.controller.signal.addEventListener('abort', cancel, { once: true });
      item.view = {
        ...item.view,
        phase: 'loading',
        query,
        items: [],
        next_cursor: null,
        incomplete: false,
        selected: null,
        error: null,
      };
      setView(item.view);
      try {
        const page = await getFileCandidates(
          token,
          item.request,
          query,
          cursor,
          controller.signal,
        );
        if (
          !live(item) ||
          item.load !== controller ||
          controller.signal.aborted
        )
          return;
        // A repeated cursor cannot cause an endless Next loop on stale pages.
        if (cursor !== null && page.next_cursor === cursor)
          throw new Error('invalid-file-cursor');
        item.view = { ...item.view, ...page, phase: 'ready' };
        setView(item.view);
      } catch {
        if (
          !live(item) ||
          item.load !== controller ||
          controller.signal.aborted
        )
          return;
        item.view = { ...item.view, phase: 'ready', error: 'loadFailed' };
        setView(item.view);
      } finally {
        item.controller.signal.removeEventListener('abort', cancel);
      }
    },
    [token, live],
  );

  const selectFile = useCallback(
    (
      raw: IndependentFileSelectionRequest,
      signal: AbortSignal,
      isCurrent: () => boolean,
    ): Promise<IndependentFileSelectionResult> => {
      if (
        !token ||
        !actorId ||
        !source ||
        !active.current ||
        latest.current !== scope ||
        signal.aborted ||
        !isCurrent()
      )
        return Promise.resolve({ status: 'unavailable' });
      const request = checkedIndependentFileSelectionRequest(
        raw,
        source.installationId,
        source.origin,
      );
      if (!request) return Promise.resolve({ status: 'unavailable' });
      if (pending.current) return Promise.resolve({ status: 'busy' });
      return new Promise((resolve) => {
        let finished = false;
        const controller = new AbortController();
        const onCancel = () => item.end({ status: 'unavailable' });
        const timer = setTimeout(
          onCancel,
          Math.max(0, Date.parse(request.expires_at) - Date.now()),
        );
        const item: Pending = {
          request,
          controller,
          isCurrent,
          expiresAt: Date.parse(request.expires_at),
          view: {
            scope,
            requestId: request.selection_id,
            query: '',
            phase: 'ready',
            items: [],
            next_cursor: null,
            incomplete: false,
            selected: null,
            error: null,
          },
          end: (result) => {
            if (finished) return;
            finished = true;
            clearTimeout(timer);
            signal.removeEventListener('abort', onCancel);
            controller.abort();
            item.load?.abort();
            if (pending.current === item) {
              pending.current = null;
              setView(null);
            }
            resolve(result);
          },
        };
        pending.current = item;
        signal.addEventListener('abort', onCancel, { once: true });
        if (signal.aborted || !live(item))
          return item.end({ status: 'unavailable' });
        void load(item, '', null);
      });
    },
    [token, actorId, source, scope, live, load],
  );

  const choose = useCallback(
    (file: IndependentFileSelectionMetadata) => {
      const item = pending.current;
      if (!item || !live(item) || item.view.phase !== 'ready') return;
      const offered = item.view.items.find(
        (candidate) =>
          candidate.file_id === file.file_id &&
          candidate.version === file.version,
      );
      if (!offered) return;
      item.view = { ...item.view, selected: offered };
      setView(item.view);
    },
    [live],
  );
  const confirm = useCallback(async () => {
    const item = pending.current;
    if (
      !token ||
      !item ||
      !live(item) ||
      item.view.phase !== 'ready' ||
      !item.view.selected
    )
      return;
    const file = item.view.selected;
    item.view = { ...item.view, phase: 'confirming', error: null };
    setView(item.view);
    try {
      const selection = await authorizeFileSelection(
        token,
        item.request,
        file,
        item.controller.signal,
      );
      if (!live(item)) return;
      item.end({ status: 'selected', selection });
    } catch {
      if (!live(item)) return;
      // Even a malformed or lost success may have issued a grant. Never replay it.
      item.view = { ...item.view, phase: 'unknown', error: 'selectionUnknown' };
      setView(item.view);
    }
  }, [token, live]);
  const rendered = view?.scope === scope ? view : null;
  const fromThisView = (requireLive = true) => {
    const item = pending.current;
    return item &&
      rendered &&
      active.current &&
      latest.current === scope &&
      item.view.scope === scope &&
      item.view.requestId === rendered.requestId &&
      (!requireLive || live(item))
      ? item
      : null;
  };
  return {
    view: rendered,
    selectFile,
    choose: (file: IndependentFileSelectionMetadata) => {
      if (fromThisView()) choose(file);
    },
    confirm: async () => {
      if (fromThisView()) await confirm();
    },
    cancel: () => fromThisView(false)?.end({ status: 'canceled' }),
    search: (query: string) => {
      const item = fromThisView();
      if (item) void load(item, query.trim(), null);
    },
    next: () => {
      const item = fromThisView();
      if (item?.view.next_cursor)
        void load(item, item.view.query, item.view.next_cursor);
    },
  };
}
