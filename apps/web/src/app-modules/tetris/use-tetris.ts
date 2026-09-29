import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MutableRefObject,
} from 'react';
import { fallInterval, type Action, type Game } from './engine';
import { placementAction, type Placement } from './ai-placement';
import {
  emptyMatch,
  pauseMatch,
  startMatch,
  stepMatch,
  type Match,
  type Player,
} from './match';
import type {
  Decide,
  ModelChoice,
  ModelOption,
  TetrisDecision,
} from './ai-api';
import { ApiRequestError } from '@/src/platform/api/client';

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
export interface PlayerConfig {
  mode: 'human' | 'ai' | 'none';
  model: ModelChoice | null;
}
interface State {
  match: Match;
  players: [PlayerConfig, PlayerConfig];
  round: number;
  versions: [number, number];
}
type Update = (change: (state: State) => State) => void;
interface Stats {
  busy: boolean;
  retry: number;
  samples: number[];
  last: TetrisDecision | null;
  error: 'rate_limited' | 'output_limit' | 'timeout' | 'failed' | null;
}
const emptyStats = (): Stats => ({
  busy: false,
  retry: 0,
  samples: [],
  last: null,
  error: null,
});

function failureReason(
  error: unknown,
  timedOut: boolean,
): NonNullable<Stats['error']> {
  if (timedOut) return 'timeout';
  if (error instanceof ApiRequestError) {
    if (error.status === 429) return 'rate_limited';
    if (error.status === 408 || error.status === 504) return 'timeout';
    if (
      error.payload &&
      typeof error.payload === 'object' &&
      'code' in error.payload &&
      error.payload.code === 'tetris.ai_output_limit'
    )
      return 'output_limit';
  }
  return 'failed';
}

function useGravity(
  player: Player,
  state: State,
  current: MutableRefObject<State>,
  update: Update,
) {
  const { status, duel, games } = state.match;
  const level = games[player].level;
  useEffect(() => {
    if (status !== 'playing' || (player === 1 && !duel)) return;
    const timer = window.setInterval(() => {
      if (current.current.match.status === 'playing')
        update((value) => ({
          ...value,
          match: stepMatch(value.match, player, 'tick'),
        }));
    }, fallInterval(level));
    return () => window.clearInterval(timer);
  }, [player, status, duel, level, state.round, current, update]);
}

function usePlayerAi(
  player: Player,
  state: State,
  current: MutableRefObject<State>,
  update: Update,
  decide: Decide,
) {
  const config = state.players[player];
  const { round } = state;
  const version = state.versions[player];
  const status = state.match.status;
  const inFlight = useRef(false);
  const request = useRef<AbortController | null>(null);
  const lastStarted = useRef(-Infinity);
  const [stats, setStats] = useState(emptyStats);
  useEffect(
    () => setStats(emptyStats()),
    [round, config.mode, config.model?.model_id, config.model?.kind],
  );
  useEffect(() => {
    if (status === 'over') request.current?.abort();
    if (config.mode !== 'ai' || status !== 'playing') return;
    let stopped = false;
    let timer: number | undefined;
    let plan: {
      placement: Placement;
      pieceId: number;
      board: Game['board'];
    } | null = null;
    const active = () =>
      !stopped &&
      current.current.round === round &&
      current.current.versions[player] === version &&
      current.current.match.status === 'playing' &&
      current.current.players[player].mode === 'ai';
    const schedule = (delay: number) => {
      if (active())
        timer = window.setTimeout(() => {
          void run();
        }, delay);
    };
    const run = async () => {
      if (!active()) return;
      if (advancePlan()) {
        schedule(100);
        return;
      }
      if (inFlight.current) {
        schedule(250);
        return;
      }
      const remaining = 250 - (performance.now() - lastStarted.current);
      if (remaining > 0) {
        schedule(remaining);
        return;
      }
      const snapshot = current.current.match.games[player];
      const other = player === 0 ? 1 : 0;
      const opponent = current.current.match.duel
        ? current.current.match.games[other]
        : undefined;
      const controller = new AbortController();
      request.current = controller;
      inFlight.current = true;
      const started = performance.now();
      lastStarted.current = started;
      setStats((value) => ({ ...value, busy: true }));
      const timeout = window.setTimeout(() => controller.abort(), 35000);
      let retry = false;
      try {
        const result = await decide(
          snapshot,
          controller.signal,
          config.model,
          opponent,
        );
        if (active()) {
          setStats((value) => ({
            ...value,
            retry: 0,
            error: null,
            last: result,
            samples: [
              ...value.samples.slice(-19),
              Math.round(performance.now() - started),
            ],
          }));
          const latest = current.current.match.games[player];
          // Retain the chosen landing through movement and hold. Gravity is
          // independent; the shared engine rechecks its path before every key.
          if (
            latest.pieceId === snapshot.pieceId &&
            latest.board === snapshot.board &&
            result.placement
          ) {
            plan = {
              placement: result.placement,
              pieceId: latest.pieceId,
              board: latest.board,
            };
            advancePlan();
          }
        }
      } catch (error) {
        if (active()) {
          retry = true;
          setStats((value) => ({
            ...value,
            retry: value.retry + 1,
            error: failureReason(error, controller.signal.aborted),
          }));
        }
      } finally {
        window.clearTimeout(timeout);
        inFlight.current = false;
        if (request.current === controller) request.current = null;
        if (!stopped) setStats((value) => ({ ...value, busy: false }));
        schedule(
          retry
            ? 500
            : plan
              ? 100
              : Math.max(0, 250 - (performance.now() - started)),
        );
      }
    };
    const advancePlan = () => {
      if (!plan) return false;
      const game = current.current.match.games[player];
      if (game.pieceId !== plan.pieceId || game.board !== plan.board) {
        plan = null;
        return false;
      }
      const action = placementAction(game, plan.placement);
      if (!action) {
        plan = null;
        return false;
      }
      update((value) => ({
        ...value,
        match: stepMatch(value.match, player, action),
      }));
      if (action === 'drop') plan = null;
      else if (action === 'hold') {
        plan.pieceId = current.current.match.games[player].pieceId;
        plan.placement = { ...plan.placement, uses_hold: false };
      }
      return true;
    };
    schedule(0);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [
    player,
    status,
    round,
    version,
    config.mode,
    config.model,
    current,
    update,
    decide,
  ]);
  useEffect(() => () => request.current?.abort(), []);
  return stats;
}

export function useTetris(decide: Decide, models?: readonly ModelOption[]) {
  const [state, setState] = useState<State>(() => ({
    match: emptyMatch(),
    players: [
      { mode: 'ai', model: null },
      { mode: 'ai', model: null },
    ],
    round: 0,
    versions: [0, 0],
  }));
  const current = useRef(state);
  const boardRefs = [
    useRef<HTMLDivElement>(null),
    useRef<HTMLDivElement>(null),
  ] as const;
  const update = useCallback<Update>((change) => {
    const next = change(current.current);
    current.current = next;
    setState(next);
  }, []);
  useEffect(() => {
    if (!models?.length) return;
    update((value) => {
      const initialModel = (
        player: PlayerConfig,
        kind: ModelChoice['kind'],
      ) => {
        if (player.model) return player;
        const model = models.find(
          (item) => item.kind === kind && item.is_default,
        );
        return model
          ? { ...player, model: { kind: model.kind, model_id: model.model_id } }
          : player;
      };
      const players: State['players'] = [
        initialModel(value.players[0], 'decision'),
        initialModel(value.players[1], 'generation'),
      ];
      return players.every((player, id) => player === value.players[id])
        ? value
        : { ...value, players };
    });
  }, [models, update]);
  useGravity(0, state, current, update);
  useGravity(1, state, current, update);
  const firstAi = usePlayerAi(0, state, current, update, decide);
  const secondAi = usePlayerAi(1, state, current, update, decide);
  const focusHuman = () => {
    const human = current.current.players.findIndex(
      (player) => player.mode === 'human',
    );
    boardRefs[human === 1 ? 1 : 0].current?.focus();
  };
  const configure = (player: Player, config: PlayerConfig) => {
    const value = current.current;
    const other = player === 0 ? 1 : 0;
    if (
      (player === 0 && config.mode === 'none') ||
      (config.mode === 'human' && value.players[other].mode === 'human')
    )
      return;
    if (
      ['playing', 'paused'].includes(value.match.status) &&
      (config.mode === 'none') !== (value.players[player].mode === 'none')
    )
      return;
    update((before) => {
      const players: State['players'] = [...before.players];
      const versions: State['versions'] = [...before.versions];
      players[player] = config;
      versions[player]++;
      return { ...before, players, versions };
    });
  };
  const start = () => {
    update((value) => ({
      ...value,
      round: value.round + 1,
      match: startMatch(value.players[1].mode !== 'none'),
    }));
    focusHuman();
  };
  const togglePause = () => {
    update((value) => ({
      ...value,
      match: pauseMatch(value.match),
      versions: [value.versions[0] + 1, value.versions[1] + 1],
    }));
    focusHuman();
  };
  const play = (player: Player, action: Action) => {
    if (current.current.players[player].mode === 'human')
      update((value) => ({
        ...value,
        match: stepMatch(value.match, player, action),
      }));
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    const toggle = event.code === 'KeyP' || event.code === 'Escape';
    const action = ACTIONS[event.code];
    if (
      (!toggle && !action) ||
      !['playing', 'paused'].includes(current.current.match.status)
    )
      return;
    event.preventDefault();
    event.stopPropagation();
    if (event.repeat && (toggle || !['left', 'right', 'down'].includes(action)))
      return;
    if (toggle) togglePause();
    else {
      const human = current.current.players.findIndex(
        (player) => player.mode === 'human',
      );
      if (human === 0 || human === 1) play(human, action);
    }
  };
  return {
    ...state,
    boardRefs,
    start,
    togglePause,
    configure,
    play,
    onKeyDown,
    ai: [firstAi, secondAi] as const,
  };
}
