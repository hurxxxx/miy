import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type UIEvent,
} from 'react';

type Position = { top: number; followLatest: boolean };
type Viewport = { id: string; node: HTMLDivElement; restored: boolean };
const MAX_SAVED_POSITIONS = 100;

// Browser-local view state for visited, loaded tasks. No conversation content is stored.
export function useConversationViewport(
  taskId: string | null,
  eventId: number | undefined,
  authenticated: boolean,
  layout: string,
) {
  const positions = useRef(new Map<string, Position>());
  const mounted = useRef<Viewport | null>(null);
  const remember = useCallback((view: Viewport) => {
    const { node, id } = view;
    // A hidden mobile panel has no usable geometry. Keep its last visible position.
    if (!view.restored || node.clientHeight === 0) return;
    positions.current.delete(id);
    positions.current.set(id, {
      top: node.scrollTop,
      followLatest:
        node.scrollHeight - node.clientHeight - node.scrollTop < 120,
    });
    while (positions.current.size > MAX_SAVED_POSITIONS) {
      const oldest = positions.current.keys().next().value;
      if (oldest === undefined) break;
      positions.current.delete(oldest);
    }
  }, []);
  const ref = useCallback(
    (node: HTMLDivElement | null) => {
      if (mounted.current) remember(mounted.current);
      mounted.current =
        node && taskId ? { id: taskId, node, restored: false } : null;
    },
    [taskId, remember],
  );
  const restore = useCallback(() => {
    if (!authenticated) {
      positions.current.clear();
      return;
    }
    const view = mounted.current;
    if (!view || view.id !== taskId) return;
    if (view.node.clientHeight === 0) {
      view.restored = false;
      return;
    }
    const saved = positions.current.get(view.id);
    if (!view.restored || !saved || saved.followLatest) {
      view.node.scrollTo({
        top: !saved || saved.followLatest ? view.node.scrollHeight : saved.top,
        // Restoration must not animate through history and overwrite the saved reading mode.
        behavior: 'instant',
      });
      view.restored = true;
      remember(view);
    }
  }, [authenticated, taskId, remember]);
  useLayoutEffect(restore, [restore, eventId, layout]);
  useEffect(() => {
    // CSS can reveal the mobile conversation without a React state change.
    // Resize precedes scroll events in a rendering cycle. Let a pending user
    // scroll update reading mode before deciding whether to follow the bottom.
    let frame: number | null = null;
    const resize = () => {
      if (frame !== null) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        restore();
      });
    };
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, [restore]);
  const onScroll = useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      const view = mounted.current;
      if (view?.node === event.currentTarget) remember(view);
    },
    [remember],
  );
  return { ref, onScroll };
}
