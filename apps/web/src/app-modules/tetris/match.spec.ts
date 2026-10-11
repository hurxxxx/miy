import { describe, expect, it } from 'vitest';
import {
  addGarbage,
  emptyGame,
  fits,
  SHAPES,
  startGame,
  type Game,
} from './engine';
import {
  pauseMatch,
  startMatch,
  stepMatch,
  type Match,
  type Player,
} from './match';

function clearRows(lines: number): Game {
  const game = startGame(() => 0.5);
  game.active = {
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
  for (let y = 20 - lines; y < 20; y++)
    game.board[y] = Array.from({ length: 10 }, (_, x) =>
      x === 4 ? null : 'garbage',
    );
  return game;
}
describe('immediate Tetris attacks', () => {
  it.each([0, 1] as const)(
    'sends the exact attack from player %s without replaying it',
    (player: Player) => {
      for (const lines of [1, 2, 3, 4]) {
        const match = startMatch(true);
        match.games[player] = clearRows(lines);
        const other = player === 0 ? 1 : 0;
        const holes = [0.1, 0.6, 0.9];
        const next = stepMatch(
          match,
          player,
          'drop',
          () => holes.shift() ?? 0.5,
        );
        expect(next.games[player].lines).toBe(lines);
        expect(next.sent[player]).toBe(lines - 1);
        expect(
          next.games[other].board.flat().filter((cell) => cell === 'garbage'),
        ).toHaveLength((lines - 1) * 9);
        expect(next.games[other].active).toEqual(match.games[other].active);
        expect(stepMatch(next, player, 'left').sent[player]).toBe(lines - 1);
      }
    },
  );
  it('draws a separate hole for every row', () => {
    const match = startMatch(true);
    match.games[0] = clearRows(4);
    const values = [0.1, 0.6, 0.9];
    const next = stepMatch(match, 0, 'drop', () => values.shift()!);
    expect(
      next.games[1].board.slice(-3).map((row) => row.indexOf(null)),
    ).toEqual([1, 6, 9]);
  });
  it('only lifts a falling piece when it collides with rising garbage', () => {
    const game = {
      ...startGame(),
      active: { kind: 'O' as const, shape: SHAPES.O, x: 4, y: 18 },
    };
    const next = addGarbage(game, [0, 5]);
    expect(next.active!.y).toBe(16);
    expect(fits(next.board, next.active!)).toBe(true);
    expect(game.active.y).toBe(18);
    expect(
      addGarbage({ ...game, active: { ...game.active, y: 5 } }, [0]).active!.y,
    ).toBe(5);
  });
  it('ends the entire match on overflow and freezes the winner', () => {
    const match = startMatch(true);
    match.games[0] = clearRows(2);
    match.games[1].board[0][9] = 'Z';
    const next = stepMatch(match, 0, 'drop');
    expect(next.status).toBe('over');
    expect(next.winner).toBe(0);
    expect(stepMatch(next, 0, 'tick')).toBe(next);
    expect(stepMatch(next, 1, 'drop')).toBe(next);
  });
  it('loses when the active piece cannot fit after the attack', () => {
    const game = startGame();
    game.active = { kind: 'O', shape: SHAPES.O, x: 4, y: 0 };
    game.board[2][4] = 'Z';
    expect(addGarbage(game, [0]).status).toBe('over');
  });
  it('has no opponent or outgoing attacks in solo play and pauses both duel boards', () => {
    const match: Match = {
      ...startMatch(false),
      games: [clearRows(4), emptyGame()],
    };
    const next = stepMatch(match, 0, 'drop');
    expect(next.sent).toEqual([0, 0]);
    expect(next.games[1].status).toBe('ready');
    const duel = startMatch(true);
    const paused = pauseMatch(duel);
    expect(paused.games.map((game) => game.status)).toEqual([
      'paused',
      'paused',
    ]);
    expect(stepMatch(paused, 0, 'tick')).toBe(paused);
    expect(pauseMatch(paused).games.map((game) => game.status)).toEqual([
      'playing',
      'playing',
    ]);
  });
});
