import type { ApiSchema } from '@open-work-hub/contracts';
import { apiFetchJson } from '@/src/platform/api/client';
import { i18n } from '@/src/platform/i18n';
import type { Game } from './engine';

export type TetrisDecision = ApiSchema<'TetrisDecisionResponse'>;
export type Decide = (
  game: Game,
  signal: AbortSignal,
) => Promise<TetrisDecision>;

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
  };
  return apiFetchJson('/api/v1/tetris/decision', token, {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}
