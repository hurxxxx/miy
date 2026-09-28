import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import {
  emptyGame,
  fallInterval,
  startGame,
  step,
  type Action,
  type Game,
} from './engine';
import type { Decide } from './ai-api';

const ACTIONS: Record<string, Action> = {
  ArrowLeft: 'left',
  ArrowRight: 'right',
  ArrowDown: 'down',
  ArrowUp: 'clockwise',
  KeyX: 'clockwise',
  KeyZ: 'counterclockwise',
  Space: 'drop',
  KeyC: 'hold',
};
const AI_INTERVAL_MS = 250;
const AI_TIMEOUT_MS = 35_000;
const AI_RETRY_INTERVAL_MS = 1000;

export function useTetris(decide: Decide) {
  const [game, setGame] = useState(emptyGame);
  // Commit synchronously so timer, network and keyboard callbacks see the same
  // game even when React batches rendering across those callbacks.
  const current = useRef(game);
  const [round, setRound] = useState(0);
  const [aiEnabled, setAiEnabled] = useState(false);
  const enabled = useRef(false);
  const epoch = useRef(0);
  const [controlVersion, setControlVersion] = useState(0);
  const failures = useRef(0);
  const [aiRetry, setAiRetry] = useState(0);
  const invalidate = useCallback(() => {
    epoch.current++;
    failures.current = 0;
    setAiRetry(0);
    setControlVersion((value) => value + 1);
  }, []);
  const lastStarted = useRef(-Infinity);
  const inFlight = useRef(false);
  const request = useRef<AbortController | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const boardRef = useRef<HTMLDivElement>(null);
  const commit = useCallback((next: Game) => {
    current.current = next;
    setGame(next);
  }, []);
  const pause = useCallback(() => {
    invalidate();
    commit(step(current.current, 'pause'));
  }, [commit, invalidate]);

  useEffect(() => {
    if (game.status !== 'playing') return;
    const timer = window.setInterval(
      () => commit(step(current.current, 'tick')),
      fallInterval(game.level),
    );
    return () => window.clearInterval(timer);
  }, [game.status, game.level, round, commit]);

  useEffect(() => {
    if (game.status === 'over') request.current?.abort();
    if (!aiEnabled || game.status !== 'playing') return;
    let stopped = false;
    let timer: number | undefined;
    const generation = epoch.current;
    const active = () =>
      !stopped &&
      enabled.current &&
      epoch.current === generation &&
      current.current.status === 'playing';
    const schedule = (delay: number) => {
      if (active())
        timer = window.setTimeout(() => {
          void run();
        }, delay);
    };
    const run = async () => {
      if (!active()) return;
      // Mode changes never start a second paid call while the first is pending.
      if (inFlight.current) {
        schedule(AI_INTERVAL_MS);
        return;
      }
      const remaining =
        AI_INTERVAL_MS - (performance.now() - lastStarted.current);
      if (remaining > 0) {
        schedule(remaining);
        return;
      }
      const snapshot = current.current;
      const started = performance.now();
      lastStarted.current = started;
      const controller = new AbortController();
      let retryDelay: number | undefined;
      request.current = controller;
      inFlight.current = true;
      setAiBusy(true);
      const timeout = window.setTimeout(
        () => controller.abort(),
        AI_TIMEOUT_MS,
      );
      try {
        const result = await decide(snapshot, controller.signal);
        if (active()) {
          failures.current = 0;
          setAiRetry(0);
          if (
            current.current.pieceId === snapshot.pieceId &&
            result.action !== 'wait'
          )
            commit(step(current.current, result.action));
        }
      } catch {
        if (active()) {
          failures.current++;
          setAiRetry(failures.current);
          retryDelay = AI_RETRY_INTERVAL_MS;
        }
      } finally {
        window.clearTimeout(timeout);
        inFlight.current = false;
        if (request.current === controller) request.current = null;
        if (!stopped) setAiBusy(false);
        // A retry is a new decision about the latest game, never replay of an
        // old action. The previous request has settled before the delay starts.
        schedule(
          retryDelay ??
            Math.max(0, AI_INTERVAL_MS - (performance.now() - started)),
        );
      }
    };
    schedule(0);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [aiEnabled, game.status, round, controlVersion, decide, commit]);

  useEffect(
    () => () => {
      epoch.current++;
      request.current?.abort();
    },
    [],
  );
  const start = () => {
    invalidate();
    setAiBusy(false);
    commit(startGame());
    setRound((value) => value + 1);
    boardRef.current?.focus();
  };
  const resume = () => {
    invalidate();
    commit(step(current.current, 'resume'));
    boardRef.current?.focus();
  };
  const toggleAi = () => {
    invalidate();
    enabled.current = !enabled.current;
    setAiEnabled(enabled.current);
    setAiBusy(false);
    boardRef.current?.focus();
  };
  const play = (action: Action) => {
    if (!enabled.current) commit(step(current.current, action));
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    const toggle = event.code === 'KeyP' || event.code === 'Escape';
    const action = ACTIONS[event.code];
    if (!toggle && !action) return;
    if (!['playing', 'paused'].includes(current.current.status)) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.repeat && (toggle || !['left', 'right', 'down'].includes(action)))
      return;
    if (toggle) {
      if (current.current.status === 'paused') resume();
      else pause();
    } else play(action);
  };
  return {
    game,
    boardRef,
    start,
    pause,
    resume,
    onKeyDown,
    play,
    aiEnabled,
    aiBusy,
    aiRetry,
    toggleAi,
  };
}
