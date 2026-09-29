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
    const candidates = buildCandidates(game).slice(0, 26);
    expect(
      candidates.some(
        (c) =>
          c.cleared_lines === 0 &&
          c.wells.some(
            (well) =>
              well.column === 5 &&
              well.ready_rows === 4 &&
              well.filled_cells === 36,
          ) &&
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
    const candidates = buildCandidates(game).slice(0, 26);
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

  it('keeps both edge-well openings within the shared choice budget before an I is visible', () => {
    const game = { ...gameWith('O'), queue: ['O', 'Z'] as Kind[] };
    const candidates = buildCandidates(game).slice(0, 26);
    for (const [x, column] of [
      [1, 0],
      [7, 9],
    ]) {
      expect(candidates).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            target: expect.objectContaining({ x }),
            cleared_lines: 0,
            holes: 0,
            wells: [{ column, depth: 2, ready_rows: 0, filled_cells: 4 }],
          }),
        ]),
      );
    }
    // Survival alternatives remain available; the engine does not choose attack.
    expect(candidates.some((c) => c.target.x === 0 && c.max_height === 2)).toBe(
      true,
    );
    expect(buildCandidates({ ...game, queue: ['O', 'I'] })).toEqual(
      buildCandidates(game),
    );
  });

  it('preserves an attack-building follow-up alongside a flatter survival follow-up', () => {
    const game = { ...gameWith('O'), queue: ['O'] as Kind[] };
    const candidate = buildCandidates(game)
      .slice(0, 26)
      .find((c) => c.target.x === 3);
    if (!candidate) throw new Error('Missing central landing');
    expect(
      candidate.follow_ups.some(
        (f) => f.wells.length === 0 && f.max_height === 2,
      ),
    ).toBe(true);
    expect(
      candidate.follow_ups.some(
        (f) =>
          f.wells.some(
            (well) => well.column === 0 && well.filled_cells === 8,
          ) && f.max_height === 2,
      ),
    ).toBe(true);
    expect(candidate.follow_ups.length).toBeLessThanOrEqual(4);
  });

  it.each([0, 5, 9])(
    'measures partial four-row preparation in open column %s',
    (column) => {
      const game = { ...gameWith('O'), queue: ['O'] as Kind[] };
      for (let y = 18; y < 20; y++)
        game.board[y] = game.board[y].map((_, x) =>
          x === column ? null : 'J',
        );
      const candidate = buildCandidates(game)
        .slice(0, 26)
        .find((c) => c.target.x === 3);
      if (!candidate) throw new Error('Missing central landing');
      expect(candidate.wells).toContainEqual({
        column,
        depth: 2,
        ready_rows: 2,
        filled_cells: 22,
      });
      expect(candidate.cleared_lines).toBe(0);
    },
  );

  it('does not describe a covered shaft as accessible preparation', () => {
    const game = { ...gameWith('O'), queue: ['O'] as Kind[] };
    for (let y = 16; y < 20; y++)
      game.board[y] = game.board[y].map((_, x) => (x === 0 ? null : 'J'));
    game.board[15][0] = 'J';
    const candidates = buildCandidates(game);
    expect(candidates.length).toBeGreaterThan(0);
    expect(candidates.every((c) => c.holes >= 4)).toBe(true);
    // A new shallow shaft can form ABOVE the cover; the four buried rows must
    // not be counted as its depth or as ready attack rows.
    const aboveCover = candidates
      .flatMap((c) => c.wells)
      .filter((well) => well.column === 0);
    expect(aboveCover.length).toBeGreaterThan(0);
    for (const well of aboveCover)
      expect(well).toEqual({
        column: 0,
        depth: 1,
        ready_rows: 0,
        filled_cells: 2,
      });
  });
});
