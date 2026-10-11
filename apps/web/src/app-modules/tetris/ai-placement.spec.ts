import { describe, expect, it } from 'vitest';
import { buildCandidates } from './ai-candidates';
import { placementAction, type Placement } from './ai-placement';
import {
  addGarbage,
  KINDS,
  landingPiece,
  SHAPES,
  startGame,
  step,
  type Game,
} from './engine';

describe('execution of a model-selected landing', () => {
  it.each(KINDS)(
    'reaches every offered %s landing through legal keys, including hold and gravity',
    (kind) => {
      const game: Game = {
        ...startGame(() => 0.5),
        active: { kind, shape: SHAPES[kind], x: 3, y: 0 },
        hold: 'I',
      };
      for (const candidate of buildCandidates(game)) {
        let current = game;
        let placement: Placement = candidate;
        let dropped = false;
        for (let count = 0; count < 64; count++) {
          const action = placementAction(current, placement);
          expect(action).not.toBeNull();
          if (!action) break;
          if (action === 'drop') {
            expect(landingPiece(current)).toEqual(candidate.target);
            const landed = step(current, action);
            expect(landed.lines - game.lines).toBe(candidate.cleared_lines);
            expect(landed.hold).toBe(candidate.hold_after);
            dropped = true;
            break;
          }
          current = step(current, action);
          if (action === 'hold') placement = { ...placement, uses_hold: false };
          current = step(current, 'tick');
        }
        expect(dropped).toBe(true);
      }
    },
  );

  it('does not replace a target that gravity made unreachable with an unrelated drop', () => {
    const game: Game = {
      ...startGame(),
      canHold: false,
      active: { kind: 'O', shape: SHAPES.O, x: 3, y: 0 },
    };
    for (const row of [17, 18, 19]) game.board[row][2] = 'J';
    const placement: Placement = {
      uses_hold: false,
      target: {
        kind: 'O',
        shape: [
          [1, 1],
          [1, 1],
        ],
        x: 0,
        y: 18,
      },
    };
    expect(placementAction(game, placement)).toBe('left');
    const fallen = { ...game, active: { ...game.active!, y: 18 } };
    expect(placementAction(fallen, placement)).toBeNull();
    expect(placementAction(addGarbage(game, [0]), placement)).toBeNull();
  });
});
