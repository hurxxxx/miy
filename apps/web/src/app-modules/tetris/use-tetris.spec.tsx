import { StrictMode, type ReactNode } from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Decide, TetrisDecision } from './ai-api';
import { useTetris } from './use-tetris';
import { decisionFor } from './ai-test-helpers';
import { step } from './engine';
import { ApiRequestError } from '@/src/platform/api/client';

function toggleAi(value: ReturnType<typeof useTetris>) {
  value.configure(0, {
    ...value.players[0],
    mode: value.players[0].mode === 'ai' ? 'human' : 'ai',
  });
}

function deferred() {
  let resolve!: (value: TetrisDecision) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<TetrisDecision>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function setup() {
  const pending = deferred();
  const decide = vi.fn<Decide>().mockImplementation(() => pending.promise);
  const view = renderHook(() => useTetris(decide), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <StrictMode>{children}</StrictMode>
    ),
  });
  act(() => {
    view.result.current.configure(1, { mode: 'none', model: null });
    view.result.current.start();
    view.result.current.configure(0, { mode: 'ai', model: null });
  });
  return { ...view, pending, decide };
}
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('asynchronous Tetris decisions', () => {
  it('keeps one landing through multiple keys and gravity instead of asking again after every key', async () => {
    const { result, pending, decide } = setup();
    await advance(950);
    const first = result.current.match.games[0];
    const x = first.active!.x;
    const target = decisionFor({
      ...first,
      active: { ...first.active!, x: 0 },
    });
    const next = deferred();
    decide.mockImplementation(() => next.promise);
    await act(async () => pending.resolve(target));
    expect(result.current.match.games[0].active!.x).toBe(x - 1);
    await advance(50);
    expect(result.current.match.games[0].active!.y).toBe(1);
    await advance((x - 1) * 100 - 50);
    expect(decide).toHaveBeenCalledTimes(1);
    expect(result.current.match.games[0].active!.x).toBe(0);
    expect(result.current.match.games[0].board).toBe(first.board);
    await advance(100);
    expect(result.current.match.games[0].pieceId).toBe(first.pieceId + 1);
    expect(
      result.current.match.games[0].board.flat().filter(Boolean),
    ).toHaveLength(4);
    expect(decide).toHaveBeenCalledTimes(1);
    await advance(100);
    expect(decide).toHaveBeenCalledTimes(2);
  });

  it('finishes the selected held piece without asking for a new target on the hold spawn', async () => {
    const { result, pending, decide } = setup();
    await advance(0);
    const first = result.current.match.games[0];
    const held = step(first, 'hold');
    const reply = decisionFor({ ...held, active: { ...held.active!, x: 0 } });
    reply.placement!.uses_hold = true;
    const next = deferred();
    decide.mockImplementation(() => next.promise);
    await act(async () => pending.resolve(reply));
    expect(result.current.match.games[0].pieceId).toBe(first.pieceId + 1);
    expect(result.current.match.games[0].hold).toBe(first.active!.kind);
    await advance(held.active!.x * 100);
    expect(result.current.match.games[0].active!.x).toBe(0);
    expect(decide).toHaveBeenCalledTimes(1);
    await advance(100);
    expect(result.current.match.games[0].pieceId).toBe(first.pieceId + 2);
    expect(
      result.current.match.games[0].board.flat().filter(Boolean),
    ).toHaveLength(4);
    expect(decide).toHaveBeenCalledTimes(1);
  });

  it.each(['pause', 'toggle', 'restart', 'model', 'unmount'] as const)(
    'cancels the remaining placement keys on %s',
    async (change) => {
      const { result, pending, decide, unmount } = setup();
      await advance(0);
      const first = result.current.match.games[0];
      const reply = decisionFor({
        ...first,
        active: { ...first.active!, x: 0 },
      });
      decide.mockImplementation(() => deferred().promise);
      await act(async () => pending.resolve(reply));
      act(() => {
        if (change === 'pause') result.current.togglePause();
        if (change === 'toggle') toggleAi(result.current);
        if (change === 'restart') result.current.start();
        if (change === 'model')
          result.current.configure(0, {
            mode: 'ai',
            model: { kind: 'decision', model_id: 'new' },
          });
        if (change === 'unmount') unmount();
      });
      const after = result.current.match.games[0];
      await advance(800);
      expect(result.current.match.games[0].board).toBe(after.board);
      expect(result.current.match.games[0].active!.x).toBe(after.active!.x);
      if (change === 'unmount') expect(vi.getTimerCount()).toBe(0);
    },
  );

  it('stops both loops when AI reaches game over', async () => {
    const { decide, result } = setup();
    decide.mockImplementation((game) =>
      Promise.resolve(decisionFor(game, 'drop')),
    );
    await advance(10000);
    expect(result.current.match.games[0].status).toBe('over');
    const count = decide.mock.calls.length;
    await advance(5000);
    expect(decide).toHaveBeenCalledTimes(count);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('makes no decisions while paused and resumes from the current board', async () => {
    const { result, pending, decide } = setup();
    await advance(0);
    act(() => result.current.togglePause());
    const paused = result.current.match.games[0];
    await act(async () =>
      pending.resolve(decisionFor(result.current.match.games[0], 'drop', 0)),
    );
    await advance(3000);
    expect(result.current.match.games[0]).toBe(paused);
    expect(decide).toHaveBeenCalledTimes(1);
    const next = deferred();
    decide.mockImplementation(() => next.promise);
    act(() => result.current.togglePause());
    await advance(0);
    expect(decide).toHaveBeenCalledTimes(2);
    expect(decide.mock.calls[1][0].board).toBe(paused.board);
  });
  it('keeps gravity independent, serializes requests and applies to the fallen same piece', async () => {
    const { result, pending, decide } = setup();
    await advance(0);
    const initial = result.current.match.games[0].active!;
    await advance(2100);
    expect(decide).toHaveBeenCalledTimes(1);
    expect(result.current.match.games[0].active!.y).toBe(initial.y + 2);
    await act(async () => {
      pending.resolve(decisionFor(result.current.match.games[0], 'left', 2100));
    });
    expect(result.current.match.games[0].active!.x).toBe(initial.x - 1);
    expect(result.current.match.games[0].active!.y).toBe(initial.y + 2);
  });

  it('rejects a decision after gravity has spawned another piece', async () => {
    const { result, pending } = setup();
    await advance(20000);
    const before = result.current.match.games[0];
    expect(before.pieceId).toBeGreaterThan(1);
    await act(async () => {
      pending.resolve(
        decisionFor(result.current.match.games[0], 'drop', 20000),
      );
    });
    expect(result.current.match.games[0]).toBe(before);
  });

  it.each(['restart', 'pause', 'toggle'] as const)(
    'discards stale responses after %s, without overlap',
    async (change) => {
      const { result, pending, decide } = setup();
      await advance(0);
      act(() => {
        if (change === 'restart') result.current.start();
        if (change === 'pause') {
          result.current.togglePause();
          result.current.togglePause();
        }
        if (change === 'toggle') {
          result.current.configure(0, { mode: 'human', model: null });
          result.current.configure(0, { mode: 'ai', model: null });
        }
      });
      await advance(300);
      expect(decide).toHaveBeenCalledTimes(1);
      const before = result.current.match.games[0];
      await act(async () => {
        pending.resolve(
          decisionFor(result.current.match.games[0], 'drop', 300),
        );
      });
      expect(result.current.match.games[0]).toBe(before);
      const next = deferred();
      decide.mockImplementation(() => next.promise);
      await advance(250);
      expect(decide).toHaveBeenCalledTimes(2);
    },
  );

  it('ignores errors from an obsolete control generation', async () => {
    const { result, pending } = setup();
    await advance(0);
    act(() => result.current.start());
    await act(async () => pending.reject(new Error('old')));
    expect(result.current.ai[0].retry).toBe(0);
    expect(result.current.players[0].mode === 'ai').toBe(true);
  });

  it('keeps AI control after failure until the user disables it', async () => {
    const { result, pending, decide } = setup();
    await advance(400);
    act(() => result.current.play(0, 'left'));
    const x = result.current.match.games[0].active!.x;
    await act(async () => pending.reject(new Error('unavailable')));
    expect(result.current.players[0].mode === 'ai').toBe(true);
    expect(result.current.ai[0].retry).toBe(1);
    act(() => result.current.play(0, 'left'));
    expect(result.current.match.games[0].active!.x).toBe(x);
    await advance(400);
    expect(result.current.match.games[0].active!.y).toBe(0);
    expect(decide).toHaveBeenCalledTimes(1);
    act(() => toggleAi(result.current));
    expect(result.current.ai[0].retry).toBe(0);
    act(() => result.current.play(0, 'left'));
    expect(result.current.match.games[0].active!.x).toBe(x - 1);
    await advance(1000);
    expect(decide).toHaveBeenCalledTimes(1);
  });

  it('does not reset gravity when switching modes', async () => {
    const { result } = setup();
    await advance(900);
    act(() => toggleAi(result.current));
    await advance(100);
    expect(result.current.match.games[0].active!.y).toBe(1);
  });

  it('limits fast responses to four calls per second, including wait actions', async () => {
    const { decide } = setup();
    decide.mockImplementation((game) =>
      Promise.resolve(decisionFor(game, 'wait')),
    );
    await advance(999);
    expect(decide).toHaveBeenCalledTimes(4);
  });

  it('aborts on unmount and never retries its late failure', async () => {
    const { unmount, pending, decide } = setup();
    await advance(0);
    const signal = decide.mock.calls[0][1];
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => pending.reject(new Error('aborted')));
    await advance(1000);
    expect(decide).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('retries a timed out request from the latest board', async () => {
    const { decide, result } = setup();
    decide.mockImplementation(
      (_game, signal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(new Error('timeout')));
        }),
    );
    await advance(35000);
    expect(result.current.ai[0].retry).toBe(1);
    expect(result.current.players[0].mode === 'ai').toBe(true);
    expect(result.current.match.games[0].status).toBe('playing');
    decide.mockImplementation((game) =>
      Promise.resolve(decisionFor(game, 'wait')),
    );
    await advance(1000);
    expect(result.current.ai[0].retry).toBe(0);
  });

  it('recovers from one invalid response using a new observation while gravity continues', async () => {
    const { result, pending, decide } = setup();
    await advance(0);
    const first = decide.mock.calls[0][0];
    await advance(600);
    await act(async () =>
      pending.reject(new ApiRequestError(502, 'invalid response')),
    );
    expect(result.current.ai[0].retry).toBe(1);
    expect(result.current.players[0].mode === 'ai').toBe(true);
    const retry = deferred();
    decide.mockImplementation(() => retry.promise);
    await advance(499);
    expect(decide).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(decide).toHaveBeenCalledTimes(2);
    expect(decide.mock.calls[1][0].active!.y).toBe(first.active!.y + 1);
    await advance(2000);
    expect(decide).toHaveBeenCalledTimes(2);
    await act(async () =>
      retry.resolve(decisionFor(result.current.match.games[0], 'left', 2000)),
    );
    expect(result.current.match.games[0].active!.x).toBe(first.active!.x - 1);
    expect(result.current.ai[0].retry).toBe(0);
  });

  it.each([
    401,
    403,
    408,
    422,
    429,
    500,
    502,
    503,
    504,
    'network',
    'local',
  ] as const)(
    'keeps retrying failures (%s) every 500ms without a retry limit',
    async (status) => {
      const { result, decide } = setup();
      decide.mockRejectedValue(
        status === 'network'
          ? new TypeError('network')
          : status === 'local'
            ? new Error('calculation failed')
            : new ApiRequestError(status, 'rejected'),
      );
      await advance(0);
      for (let attempt = 1; attempt <= 5; attempt++) {
        expect(result.current.ai[0].retry).toBe(attempt);
        expect(result.current.ai[0].error).toBe(
          status === 429
            ? 'rate_limited'
            : status === 408 || status === 504
              ? 'timeout'
              : 'failed',
        );
        await advance(499);
        expect(decide).toHaveBeenCalledTimes(attempt);
        await advance(1);
        expect(decide).toHaveBeenCalledTimes(attempt + 1);
        expect(result.current.players[0].mode === 'ai').toBe(true);
      }
      expect(result.current.match.games[0].active!.y).toBe(2);
      expect(decide.mock.calls[5][0].active!.y).toBe(2);
    },
  );

  it('retries throughout a failing game and stops when gravity reaches game over', async () => {
    const { result, decide } = setup();
    decide.mockRejectedValue(new ApiRequestError(502, 'invalid response'));
    await advance(600000);
    expect(result.current.match.games[0].status).toBe('over');
    expect(result.current.players[0].mode === 'ai').toBe(true);
    const count = decide.mock.calls.length;
    expect(count).toBeGreaterThan(5);
    await advance(10000);
    expect(decide).toHaveBeenCalledTimes(count);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('aborts the pending request at game over and ignores its late failure', async () => {
    const { result, decide, pending } = setup();
    decide.mockImplementation((game) =>
      game.board.slice(0, 4).some((row) => row.some(Boolean))
        ? pending.promise
        : Promise.resolve(decisionFor(game)),
    );
    await advance(10000);
    expect(result.current.match.games[0].status).toBe('over');
    const count = decide.mock.calls.length;
    expect(decide.mock.calls[count - 1][1].aborted).toBe(true);
    await act(async () => pending.reject(new Error('aborted')));
    await advance(10000);
    expect(decide).toHaveBeenCalledTimes(count);
    expect(result.current.ai[0].retry).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(['pause', 'toggle', 'unmount'] as const)(
    'cancels a scheduled retry on %s',
    async (change) => {
      const { result, decide, unmount } = setup();
      decide.mockRejectedValue(new ApiRequestError(502, 'temporary'));
      await advance(0);
      act(() => {
        if (change === 'pause') result.current.togglePause();
        if (change === 'toggle') toggleAi(result.current);
        if (change === 'unmount') unmount();
      });
      await advance(4000);
      expect(decide).toHaveBeenCalledTimes(1);
    },
  );
});

it('keeps the current AI decision and both loops alive across focus and visibility changes', async () => {
  const { result, pending, decide } = setup();
  await advance(0);
  const x = result.current.match.games[0].active!.x;
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  act(() => {
    window.dispatchEvent(new Event('blur'));
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await advance(1100);
  expect(result.current.match.games[0].status).toBe('playing');
  expect(result.current.match.games[0].active!.y).toBe(1);
  expect(decide).toHaveBeenCalledTimes(1);
  await act(async () =>
    pending.resolve(decisionFor(result.current.match.games[0], 'left', 1100)),
  );
  expect(result.current.match.games[0].active!.x).toBe(x - 1);
  const next = deferred();
  decide.mockImplementation(() => next.promise);
  await advance(250);
  expect(decide).toHaveBeenCalledTimes(2);
  expect(result.current.players[0].mode === 'ai').toBe(true);
  hidden.mockRestore();
});
