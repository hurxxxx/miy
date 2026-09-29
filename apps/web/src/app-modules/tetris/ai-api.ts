import type { ApiSchema } from '@mty/contracts';
import { apiFetchJson } from '@/src/platform/api/client';
import { i18n } from '@/src/platform/i18n';
import type { Game } from './engine';

export type TetrisDecision = ApiSchema<'TetrisDecisionResponse'>;
export type ModelChoice = ApiSchema<'TetrisModelChoice'>;
export type ModelOption = ApiSchema<'TetrisModelOption'>;
export type Decide = (
  game: Game,
  signal: AbortSignal,
  model?: ModelChoice | null,
  opponent?: Game,
) => Promise<TetrisDecision>;

export function listModels(token: string | null, signal: AbortSignal) {
  return apiFetchJson<ApiSchema<'TetrisModelsResponse'>>(
    '/api/v1/tetris/models',
    token,
    { signal },
  );
}

function decisionError() {
  return new Error(i18n.t('apps:tetris.AI decision failed.'));
}

// Two-placement search runs off the UI thread, so gravity and rendering keep
// their own clock even on slower devices. Credentials never enter the worker.
function computeCandidates(
  game: Game,
  signal: AbortSignal,
): Promise<ApiSchema<'TetrisCandidate'>[]> {
  signal.throwIfAborted();
  const worker = new Worker(
    new URL('./ai-candidates.worker.ts', import.meta.url),
    { type: 'module' },
  );
  let abort: (() => void) | undefined;
  return new Promise<ApiSchema<'TetrisCandidate'>[]>((resolve, reject) => {
    abort = () => reject(signal.reason);
    signal.addEventListener('abort', abort, { once: true });
    worker.onmessage = (event: MessageEvent<ApiSchema<'TetrisCandidate'>[]>) =>
      resolve(event.data);
    worker.onerror = () => reject(decisionError());
    worker.onmessageerror = () => reject(decisionError());
    worker.postMessage({ ...game, queue: game.queue.slice(0, 1) });
  }).finally(() => {
    if (abort) signal.removeEventListener('abort', abort);
    worker.terminate();
  });
}

export async function requestDecision(
  token: string | null,
  game: Game,
  signal: AbortSignal,
  model?: ModelChoice | null,
  opponent?: Game,
): Promise<TetrisDecision> {
  if (!token || !game.active) throw decisionError();
  const candidates = await computeCandidates(game, signal);
  const payload: ApiSchema<'TetrisDecisionRequest'> = {
    board: game.board,
    active: {
      ...game.active,
      shape: game.active.shape.map((row) =>
        row.map((cell): 0 | 1 => (cell ? 1 : 0)),
      ),
    },
    next: game.queue[0],
    hold: game.hold,
    can_hold: game.canHold,
    score: game.score,
    lines: game.lines,
    level: game.level,
    candidates,
    model_choice: model,
    opponent: opponent?.active
      ? {
          board: opponent.board,
          active: {
            ...opponent.active,
            shape: opponent.active.shape.map((row) =>
              row.map((cell): 0 | 1 => (cell ? 1 : 0)),
            ),
          },
          next: opponent.queue[0],
          hold: opponent.hold,
          can_hold: opponent.canHold,
          score: opponent.score,
          lines: opponent.lines,
          level: opponent.level,
        }
      : null,
  };
  return apiFetchJson('/api/v1/tetris/decision', token, {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}
