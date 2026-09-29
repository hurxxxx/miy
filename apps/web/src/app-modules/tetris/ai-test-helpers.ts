import type { TetrisDecision } from './ai-api';
import { landingPiece, step, type Action, type Game } from './engine';

export function decisionFor(
  game: Game,
  action: Action | 'wait' = 'drop',
  latency = 0,
): TetrisDecision {
  const pose = landingPiece(
    action === 'drop' || action === 'wait' ? game : step(game, action),
  );
  return {
    action: action === 'wait' ? 'wait' : action === 'hold' ? 'hold' : 'drop',
    placement:
      action === 'wait' || !pose
        ? null
        : {
            uses_hold: action === 'hold',
            target: {
              ...pose,
              shape: pose.shape.map((row) =>
                row.map((cell): 0 | 1 => (cell ? 1 : 0)),
              ),
            },
          },
    latency_ms: latency,
    model: 'test/model',
    provider: 'test',
    kind: 'decision',
  };
}
