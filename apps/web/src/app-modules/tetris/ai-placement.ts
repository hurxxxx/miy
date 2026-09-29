import type { ApiSchema } from '@mty/contracts';
import { landingPiece, step, type Game } from './engine';

export type Placement = ApiSchema<'TetrisPlacement'>;
type Control = ApiSchema<'TetrisCandidate'>['action'];
const MOVES = ['left', 'right', 'clockwise', 'counterclockwise'] as const;

/** Shared legal-move search. It never chooses a strategic target. */
export function* reachablePoses(game: Game, allowHold: boolean) {
  if (game.status !== 'playing' || !game.active) return;
  const queue: {
    game: Game;
    action: Control;
    moves: number;
    usesHold: boolean;
  }[] = [{ game, action: 'drop', moves: 0, usesHold: false }];
  if (allowHold && game.canHold) {
    const held = step(game, 'hold', () => 0);
    if (held.status === 'playing')
      queue.push({ game: held, action: 'hold', moves: 1, usesHold: true });
  }
  const visited = new Set<string>();
  for (let index = 0; index < queue.length; index++) {
    const node = queue[index];
    if (!node.game.active) continue;
    const key = JSON.stringify([node.game.active, node.usesHold]);
    if (visited.has(key)) continue;
    visited.add(key);
    yield node;
    for (const action of MOVES) {
      const next = step(node.game, action, () => 0);
      if (!visited.has(JSON.stringify([next.active, node.usesHold])))
        queue.push({
          game: next,
          action: node.moves === 0 ? action : node.action,
          moves: node.moves + 1,
          usesHold: node.usesHold,
        });
    }
  }
}

/** Recheck reachability after gravity; never substitute a different landing. */
export function placementAction(
  game: Game,
  placement: Placement,
): Control | null {
  const target = placement.target;
  for (const node of reachablePoses(
    { ...game, queue: game.queue.slice(0, 1) },
    placement.uses_hold,
  )) {
    if (node.usesHold !== placement.uses_hold) continue;
    const pose = landingPiece(node.game);
    if (
      pose &&
      pose.kind === target.kind &&
      pose.x === target.x &&
      pose.y === target.y &&
      JSON.stringify(pose.shape) === JSON.stringify(target.shape)
    )
      return node.action;
  }
  return null;
}
