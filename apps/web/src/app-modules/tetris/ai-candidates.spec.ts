import { describe, expect, it } from 'vitest';
import { buildCandidates } from './ai-candidates';
import { KINDS, SHAPES, startGame, step, type Game, type Kind } from './engine';

function gameWith(kind: Kind = 'I'): Game {
  return {
    ...startGame(() => 0.5),
    active: { kind, shape: SHAPES[kind], x: 3, y: 0 },
    canHold: false,
  };
}

describe('Tetris observations for decisions', () => {
  it.each(['left', 'right'] as const)(
    'finds the reachable line clear to the %s',
    (direction) => {
      const game = gameWith();
      game.board[19] = game.board[19].map((_, x) =>
        (direction === 'left' ? x < 4 : x >= 6) ? null : 'J',
      );
      const before = structuredClone(game);
      const candidates = buildCandidates(game);
      expect(
        candidates.some(
          (item) =>
            item.action === direction &&
            item.cleared_lines === 1 &&
            item.holes === 0,
        ),
      ).toBe(true);
      expect(
        candidates
          .filter((item) => item.action === 'drop')
          .every((item) => item.cleared_lines === 0),
      ).toBe(true);
      expect(game).toEqual(before);
    },
  );

  it('accounts for rotation before reaching a four-line well', () => {
    const game = gameWith();
    for (let y = 16; y < 20; y++)
      game.board[y] = Array.from({ length: 10 }, (_, x) =>
        x === 5 ? null : 'J',
      );
    const candidates = buildCandidates(game);
    expect(
      candidates.some(
        (item) =>
          item.action === 'clockwise' &&
          item.cleared_lines === 4 &&
          item.max_height === 0,
      ),
    ).toBe(true);
  });

  it('does not offer moves through a blocking wall', () => {
    const game = gameWith('O');
    for (let y = 0; y < 20; y++) game.board[y][2] = 'J';
    game.board[19] = game.board[19].map((_, x) => (x < 2 ? null : 'J'));
    expect(
      buildCandidates(game).every((item) => item.cleared_lines === 0),
    ).toBe(true);
  });

  it('counts covered holes and resulting height using locked board cells', () => {
    const game = gameWith('O');
    const candidates = buildCandidates(game);
    const drop = candidates.find((item) => item.action === 'drop')!;
    expect(drop).toMatchObject({
      holes: 0,
      max_height: 2,
      aggregate_height: 4,
      bumpiness: 4,
      key_presses: 1,
    });
  });

  it('uses a legal hold without reading the hidden bag or changing the game', () => {
    const game = gameWith('O');
    game.canHold = true;
    game.queue = ['I', 'Z', 'S'];
    for (let y = 16; y < 20; y++)
      game.board[y] = Array.from({ length: 10 }, (_, x) =>
        x === 5 ? null : 'J',
      );
    const candidates = buildCandidates(game);
    expect(
      candidates.some(
        (item) => item.action === 'hold' && item.cleared_lines === 4,
      ),
    ).toBe(true);
    expect(buildCandidates({ ...game, queue: ['I', 'T', 'J'] })).toEqual(
      candidates,
    );
    expect(
      buildCandidates({ ...game, canHold: false }).some(
        (item) => item.action === 'hold',
      ),
    ).toBe(false);
  });

  it.each(KINDS)(
    'bounds the observations for %s and stops for paused games',
    (kind) => {
      const game = gameWith(kind);
      const candidates = buildCandidates(game);
      expect(candidates.length).toBeGreaterThan(0);
      expect(candidates.length).toBeLessThanOrEqual(32);
      expect(candidates.every((item) => item.key_presses <= 64)).toBe(true);
      expect(buildCandidates(step(game, 'pause'))).toEqual([]);
    },
  );

  it('prepares a four-line clear for the visible next I without using hold', () => {
    const game = gameWith('O');
    game.queue = ['I', 'Z'];
    for (let y = 16; y < 20; y++)
      game.board[y] = Array.from({ length: 10 }, (_, x) =>
        x === 5 ? null : 'J',
      );
    const candidates = buildCandidates(game);
    expect(
      candidates.some(
        (c) =>
          c.cleared_lines === 0 &&
          c.follow_ups.some(
            (f) => f.piece === 'I' && !f.uses_hold && f.cleared_lines === 4,
          ),
      ),
    ).toBe(true);
    expect(candidates.every((c) => c.next_piece === 'I')).toBe(true);
    expect(buildCandidates({ ...game, queue: ['I', 'S', 'T'] })).toEqual(
      candidates,
    );
    expect(
      buildCandidates({ ...game, queue: ['O', 'Z'] }).some((c) =>
        c.follow_ups.some((f) => f.cleared_lines === 4),
      ),
    ).toBe(false);
  });

  it('compares using the reserve now with keeping it for the second placement', () => {
    const game = gameWith('O');
    game.canHold = true;
    game.hold = 'I';
    game.queue = ['T', 'Z'];
    for (let y = 16; y < 20; y++)
      game.board[y] = Array.from({ length: 10 }, (_, x) =>
        x === 5 ? null : 'J',
      );
    const candidates = buildCandidates(game);
    expect(
      candidates.some(
        (c) =>
          c.uses_hold &&
          c.piece === 'I' &&
          c.hold_after === 'O' &&
          c.cleared_lines === 4,
      ),
    ).toBe(true);
    expect(
      candidates.some(
        (c) =>
          !c.uses_hold &&
          c.hold_after === 'I' &&
          c.follow_ups.some(
            (f) =>
              f.uses_hold &&
              f.piece === 'I' &&
              f.hold_after === 'T' &&
              f.cleared_lines === 4,
          ),
      ),
    ).toBe(true);
  });

  it('marks the forecast unknown when empty hold consumes the visible next piece', () => {
    const game = {
      ...gameWith('O'),
      canHold: true,
      queue: ['I', 'T'] as Kind[],
    };
    const held = buildCandidates(game).filter((c) => c.uses_hold);
    expect(held.length).toBeGreaterThan(0);
    for (const candidate of held)
      expect(candidate).toMatchObject({
        action: 'hold',
        piece: 'I',
        hold_after: 'O',
        next_piece: null,
        next_spawn_blocked: null,
        follow_ups: [],
      });
  });

  it('does not use a hidden piece via empty hold on the second placement', () => {
    const game = { ...gameWith('O'), queue: ['T', 'I'] as Kind[] };
    const candidates = buildCandidates(game);
    expect(
      candidates.every(
        (c) =>
          c.follow_ups.length > 0 &&
          c.follow_ups.every(
            (f) => !f.uses_hold && f.piece === 'T' && f.hold_after === null,
          ),
      ),
    ).toBe(true);
  });
});
