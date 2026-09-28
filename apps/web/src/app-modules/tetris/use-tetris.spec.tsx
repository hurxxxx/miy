import { StrictMode, type ReactNode } from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Decide, TetrisDecision } from './ai-api';
import { useTetris } from './use-tetris';
import { ApiRequestError } from '@/src/platform/api/client';

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
    view.result.current.start();
    view.result.current.toggleAi();
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
  it('stops both loops when AI reaches game over', async () => {
    const { decide, result } = setup();
    decide.mockResolvedValue({ action: 'drop', latency_ms: 0 });
    await advance(10000);
    expect(result.current.game.status).toBe('over');
    const count = decide.mock.calls.length;
    await advance(5000);
    expect(decide).toHaveBeenCalledTimes(count);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('makes no decisions while paused and resumes from the current board', async () => {
    const { result, pending, decide } = setup();
    await advance(0);
    act(() => result.current.pause());
    const paused = result.current.game;
    await act(async () => pending.resolve({ action: 'drop', latency_ms: 0 }));
    await advance(3000);
    expect(result.current.game).toBe(paused);
    expect(decide).toHaveBeenCalledTimes(1);
    const next = deferred();
    decide.mockImplementation(() => next.promise);
    act(() => result.current.resume());
    await advance(0);
    expect(decide).toHaveBeenCalledTimes(2);
    expect(decide.mock.calls[1][0].board).toBe(paused.board);
  });
  it('keeps gravity independent, serializes requests and applies to the fallen same piece', async () => {
    const { result, pending, decide } = setup();
    await advance(0);
    const initial = result.current.game.active!;
    await advance(2100);
    expect(decide).toHaveBeenCalledTimes(1);
    expect(result.current.game.active!.y).toBe(initial.y + 2);
    await act(async () => {
      pending.resolve({ action: 'left', latency_ms: 2100 });
    });
    expect(result.current.game.active!.x).toBe(initial.x - 1);
    expect(result.current.game.active!.y).toBe(initial.y + 2);
  });

  it('rejects a decision after gravity has spawned another piece', async () => {
    const { result, pending } = setup();
    await advance(20000);
    const before = result.current.game;
    expect(before.pieceId).toBeGreaterThan(1);
    await act(async () => {
      pending.resolve({ action: 'drop', latency_ms: 20000 });
    });
    expect(result.current.game).toBe(before);
  });

  it.each(['restart', 'pause', 'toggle'] as const)(
    'discards stale responses after %s, without overlap',
    async (change) => {
      const { result, pending, decide } = setup();
      await advance(0);
      act(() => {
        if (change === 'restart') result.current.start();
        if (change === 'pause') {
          result.current.pause();
          result.current.resume();
        }
        if (change === 'toggle') {
          result.current.toggleAi();
          result.current.toggleAi();
        }
      });
      await advance(300);
      expect(decide).toHaveBeenCalledTimes(1);
      const before = result.current.game;
      await act(async () => {
        pending.resolve({ action: 'drop', latency_ms: 300 });
      });
      expect(result.current.game).toBe(before);
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
    expect(result.current.aiRetry).toBe(0);
    expect(result.current.aiEnabled).toBe(true);
  });

  it('keeps AI control after failure until the user disables it', async () => {
    const { result, pending, decide } = setup();
    await advance(400);
    act(() => result.current.play('left'));
    const x = result.current.game.active!.x;
    await act(async () => pending.reject(new Error('unavailable')));
    expect(result.current.aiEnabled).toBe(true);
    expect(result.current.aiRetry).toBe(1);
    act(() => result.current.play('left'));
    expect(result.current.game.active!.x).toBe(x);
    await advance(600);
    expect(result.current.game.active!.y).toBe(1);
    expect(decide).toHaveBeenCalledTimes(1);
    act(() => result.current.toggleAi());
    expect(result.current.aiRetry).toBe(0);
    act(() => result.current.play('left'));
    expect(result.current.game.active!.x).toBe(x - 1);
    await advance(1000);
    expect(decide).toHaveBeenCalledTimes(1);
  });

  it('does not reset gravity when switching modes', async () => {
    const { result } = setup();
    await advance(900);
    act(() => result.current.toggleAi());
    await advance(100);
    expect(result.current.game.active!.y).toBe(1);
  });

  it('limits fast responses to four calls per second, including wait actions', async () => {
    const { decide } = setup();
    decide.mockResolvedValue({ action: 'wait', latency_ms: 0 });
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
    expect(result.current.aiRetry).toBe(1);
    expect(result.current.aiEnabled).toBe(true);
    expect(result.current.game.status).toBe('playing');
    decide.mockResolvedValue({ action: 'wait', latency_ms: 0 });
    await advance(1000);
    expect(result.current.aiRetry).toBe(0);
  });

  it('recovers from one invalid response using a new observation while gravity continues', async () => {
    const { result, pending, decide } = setup();
    await advance(0);
    const first = decide.mock.calls[0][0];
    await act(async () =>
      pending.reject(new ApiRequestError(502, 'invalid response')),
    );
    expect(result.current.aiRetry).toBe(1);
    expect(result.current.aiEnabled).toBe(true);
    const retry = deferred();
    decide.mockImplementation(() => retry.promise);
    await advance(999);
    expect(decide).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(decide).toHaveBeenCalledTimes(2);
    expect(decide.mock.calls[1][0].active!.y).toBe(first.active!.y + 1);
    await advance(2000);
    expect(decide).toHaveBeenCalledTimes(2);
    await act(async () => retry.resolve({ action: 'left', latency_ms: 2000 }));
    expect(result.current.game.active!.x).toBe(first.active!.x - 1);
    expect(result.current.aiRetry).toBe(0);
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
    'keeps retrying failures (%s) once per second without a retry limit',
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
        expect(result.current.aiRetry).toBe(attempt);
        await advance(999);
        expect(decide).toHaveBeenCalledTimes(attempt);
        await advance(1);
        expect(decide).toHaveBeenCalledTimes(attempt + 1);
        expect(result.current.aiEnabled).toBe(true);
      }
      expect(result.current.game.active!.y).toBe(5);
      expect(decide.mock.calls[5][0].active!.y).toBe(5);
    },
  );

  it('retries throughout a failing game and stops when gravity reaches game over', async () => {
    const { result, decide } = setup();
    decide.mockRejectedValue(new ApiRequestError(502, 'invalid response'));
    await advance(600000);
    expect(result.current.game.status).toBe('over');
    expect(result.current.aiEnabled).toBe(true);
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
        : Promise.resolve({ action: 'drop', latency_ms: 0 }),
    );
    await advance(10000);
    expect(result.current.game.status).toBe('over');
    const count = decide.mock.calls.length;
    expect(decide.mock.calls[count - 1][1].aborted).toBe(true);
    await act(async () => pending.reject(new Error('aborted')));
    await advance(10000);
    expect(decide).toHaveBeenCalledTimes(count);
    expect(result.current.aiRetry).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(['pause', 'toggle', 'unmount'] as const)(
    'cancels a scheduled retry on %s',
    async (change) => {
      const { result, decide, unmount } = setup();
      decide.mockRejectedValue(new ApiRequestError(502, 'temporary'));
      await advance(0);
      act(() => {
        if (change === 'pause') result.current.pause();
        if (change === 'toggle') result.current.toggleAi();
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
  const x = result.current.game.active!.x;
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  act(() => {
    window.dispatchEvent(new Event('blur'));
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await advance(1100);
  expect(result.current.game.status).toBe('playing');
  expect(result.current.game.active!.y).toBe(1);
  expect(decide).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve({ action: 'left', latency_ms: 1100 }));
  expect(result.current.game.active!.x).toBe(x - 1);
  const next = deferred();
  decide.mockImplementation(() => next.promise);
  await advance(250);
  expect(decide).toHaveBeenCalledTimes(2);
  expect(result.current.aiEnabled).toBe(true);
  hidden.mockRestore();
});
