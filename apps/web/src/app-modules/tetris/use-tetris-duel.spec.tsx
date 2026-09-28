import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useTetris } from './use-tetris';
import { decisionFor } from './ai-test-helpers';
import type { Game } from './engine';
import { startMatch, type Match } from './match';
import type { Decide, TetrisDecision } from './ai-api';

const fixture = vi.hoisted(() => ({ match: null as Match | null }));
vi.mock('./match', async (original) => {
  const actual = await original<typeof import('./match')>();
  return {
    ...actual,
    startMatch: (...args: Parameters<typeof startMatch>) =>
      fixture.match ?? actual.startMatch(...args),
  };
});
const answer = (
  game: Game,
  action: 'left' | 'drop' | 'wait' = 'left',
): TetrisDecision => ({
  ...decisionFor(game, action, 3),
  model: 'reported/model',
});
const ai = (model_id: string) => ({
  mode: 'ai' as const,
  model: { kind: 'decision' as const, model_id },
});
function pending() {
  let resolve!: (value: TetrisDecision) => void;
  const promise = new Promise<TetrisDecision>((done) => {
    resolve = done;
  });
  return { promise, resolve };
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
  fixture.match = null;
});
function attackingMatch() {
  const match = startMatch(true);
  const first = match.games[0];
  first.active = {
    kind: 'I',
    shape: [
      [0, 1, 0, 0],
      [0, 1, 0, 0],
      [0, 1, 0, 0],
      [0, 1, 0, 0],
    ],
    x: 3,
    y: 0,
  };
  for (const row of [18, 19])
    first.board[row] = Array.from({ length: 10 }, (_, x) =>
      x === 4 ? null : 'garbage',
    );
  return match;
}
it('runs two models independently while one waits, with separate response statistics', async () => {
  const slow = pending();
  const decide = vi.fn<Decide>((game, _signal, model) =>
    model?.model_id === 'slow'
      ? slow.promise
      : Promise.resolve(answer(game, 'drop')),
  );
  const { result } = renderHook(() => useTetris(decide));
  act(() => {
    result.current.configure(0, ai('slow'));
    result.current.configure(1, ai('fast'));
    result.current.start();
  });
  await advance(1500);
  expect(
    decide.mock.calls.filter((call) => call[2]?.model_id === 'slow'),
  ).toHaveLength(1);
  expect(
    decide.mock.calls.filter((call) => call[2]?.model_id === 'fast').length,
  ).toBeGreaterThan(4);
  expect(result.current.match.games[0].active!.y).toBe(1);
  expect(result.current.match.games[1].score).toBeGreaterThan(4);
  expect(result.current.ai[0].samples).toHaveLength(0);
  expect(result.current.ai[1].samples.length).toBeGreaterThan(4);
  expect(decide.mock.calls.every((call) => call[3]?.active)).toBe(true);
  await act(async () => slow.resolve(answer(result.current.match.games[0])));
  expect(result.current.ai[0].samples).toEqual([1500]);
  expect(result.current.ai[0].last!.model).toBe('reported/model');
});
it('ignores a pre-attack response even when the same piece is still falling', async () => {
  fixture.match = attackingMatch();
  const deferred = pending();
  const decide = vi.fn<Decide>(() => deferred.promise);
  const { result } = renderHook(() => useTetris(decide));
  act(() => {
    result.current.configure(0, { mode: 'human', model: null });
    result.current.configure(1, ai('opponent'));
    result.current.start();
  });
  await advance(0);
  const before = result.current.match.games[1];
  act(() => result.current.play(0, 'drop'));
  expect(result.current.match.games[1].pieceId).toBe(before.pieceId);
  expect(result.current.match.games[1].board).not.toBe(before.board);
  const after = result.current.match.games[1];
  await act(async () => deferred.resolve(answer(before, 'left')));
  expect(result.current.match.games[1]).toBe(after);
  await advance(250);
  expect(decide.mock.calls[1][0].board).toBe(after.board);
});
it('abandons remaining movement when garbage invalidates an already selected target', async () => {
  fixture.match = attackingMatch();
  fixture.match.games[1].active = {
    kind: 'O',
    shape: [
      [1, 1],
      [1, 1],
    ],
    x: 4,
    y: 0,
  };
  const initial = fixture.match.games[1];
  const deferred = pending();
  const decide = vi
    .fn<Decide>()
    .mockResolvedValueOnce(
      answer(
        {
          ...initial,
          active: { ...initial.active!, x: 0 },
        },
        'drop',
      ),
    )
    .mockImplementation(() => deferred.promise);
  const { result } = renderHook(() => useTetris(decide));
  act(() => {
    result.current.configure(0, { mode: 'human', model: null });
    result.current.configure(1, ai('opponent'));
    result.current.start();
  });
  await advance(0);
  expect(result.current.match.games[1].active!.x).toBe(3);
  act(() => result.current.play(0, 'drop'));
  const after = result.current.match.games[1];
  await advance(250);
  expect(result.current.match.games[1]).toBe(after);
  expect(decide).toHaveBeenCalledTimes(2);
  expect(decide.mock.calls[1][0].board).toBe(after.board);
});
it('stops both players and aborts pending AI when an attack ends the game', async () => {
  fixture.match = attackingMatch();
  fixture.match.games[1].board[0][9] = 'Z';
  const deferred = pending();
  const decide = vi.fn<Decide>(() => deferred.promise);
  const { result } = renderHook(() => useTetris(decide));
  act(() => {
    result.current.configure(0, { mode: 'human', model: null });
    result.current.configure(1, ai('opponent'));
    result.current.start();
  });
  await advance(0);
  act(() => result.current.play(0, 'drop'));
  expect(result.current.match.winner).toBe(0);
  expect(decide.mock.calls[0][1].aborted).toBe(true);
  const ended = result.current.match;
  await act(async () =>
    deferred.resolve(answer(result.current.match.games[1], 'drop')),
  );
  await advance(4000);
  expect(decide).toHaveBeenCalledTimes(1);
  expect(result.current.match).toBe(ended);
  expect(vi.getTimerCount()).toBe(0);
});
it('changes models without overlap or applying the old response and resets timing samples', async () => {
  const deferred = pending();
  const decide = vi.fn<Decide>(() => deferred.promise);
  const { result } = renderHook(() => useTetris(decide));
  act(() => {
    result.current.configure(1, { mode: 'none', model: null });
    result.current.configure(0, ai('old'));
    result.current.start();
  });
  await advance(100);
  act(() => result.current.configure(0, ai('new')));
  await advance(300);
  expect(decide).toHaveBeenCalledTimes(1);
  const before = result.current.match.games[0];
  await act(async () => deferred.resolve(answer(before)));
  expect(result.current.match.games[0]).toBe(before);
  expect(result.current.ai[0].samples).toHaveLength(0);
  const next = pending();
  decide.mockImplementation(() => next.promise);
  await advance(250);
  expect(decide.mock.calls[1][2]?.model_id).toBe('new');
});
it('rejects two humans and changes to the participant count during a game', () => {
  const { result } = renderHook(() => useTetris(vi.fn()));
  act(() => result.current.configure(0, { mode: 'human', model: null }));
  act(() => result.current.configure(1, { mode: 'human', model: null }));
  expect(result.current.players[1].mode).toBe('ai');
  act(() => {
    result.current.configure(0, ai('first'));
    result.current.configure(1, { mode: 'human', model: null });
    result.current.start();
  });
  expect(result.current.players[1].mode).toBe('human');
  act(() => result.current.configure(1, { mode: 'none', model: null }));
  expect(result.current.players[1].mode).toBe('human');
});
