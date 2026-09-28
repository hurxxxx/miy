import type { ApiSchema } from '@open-work-hub/contracts';
import {
  HEIGHT,
  WIDTH,
  landingPiece,
  step,
  type Cell,
  type Game,
} from './engine';
import { reachablePoses } from './ai-placement';

type Candidate = ApiSchema<'TetrisCandidate'>;
type Landing = ApiSchema<'TetrisLanding'>;
type Preview = { game: Game; action: Candidate['action']; outcome: Landing };
const COSTS = [
  'holes',
  'max_height',
  'aggregate_height',
  'bumpiness',
  'key_presses',
] as const;

function surface(board: Cell[][]) {
  const heights = Array.from({ length: WIDTH }, (_, x) => {
    const top = board.findIndex((row) => row[x] !== null);
    return top < 0 ? 0 : HEIGHT - top;
  });
  let holes = 0;
  for (let x = 0; x < WIDTH; x++) {
    for (let y = HEIGHT - heights[x]; y < HEIGHT; y++) {
      if (board[y][x] === null) holes++;
    }
  }
  return {
    holes,
    max_height: Math.max(...heights),
    aggregate_height: heights.reduce((sum, height) => sum + height, 0),
    bumpiness: heights
      .slice(1)
      .reduce((sum, height, x) => sum + Math.abs(height - heights[x]), 0),
  };
}

function compare(a: Landing, b: Landing): number {
  return (
    a.holes - b.holes ||
    a.max_height - b.max_height ||
    b.cleared_lines - a.cleared_lines ||
    a.bumpiness - b.bumpiness ||
    a.aggregate_height - b.aggregate_height ||
    a.key_presses - b.key_presses
  );
}

function noWorse(a: Landing, b: Landing): boolean {
  return (
    a.cleared_lines >= b.cleared_lines && COSTS.every((key) => a[key] <= b[key])
  );
}

/** Enumerate legal paths with the real engine. Keep different reserve states:
 * identical board metrics can have different value for the following piece. */
function landings(game: Game, allowHold: boolean): Preview[] {
  const results = new Map<string, Preview>();
  for (const node of reachablePoses(game, allowHold)) {
    const target = landingPiece(node.game);
    if (!target) continue;
    const landed = step(node.game, 'drop', () => 0);
    const outcome: Landing = {
      piece: target.kind,
      target: {
        ...target,
        shape: target.shape.map((row) =>
          row.map((cell): 0 | 1 => (cell ? 1 : 0)),
        ),
      },
      uses_hold: node.usesHold,
      hold_after: landed.hold,
      cleared_lines: landed.lines - game.lines,
      ...surface(landed.board),
      key_presses: node.moves + 1,
    };
    const boardKey = JSON.stringify([
      landed.board,
      outcome.hold_after,
      node.usesHold,
    ]);
    if (!results.has(boardKey))
      results.set(boardKey, { game: landed, action: node.action, outcome });
  }
  return [...results.values()];
}

function futureValue(candidate: Candidate): Landing {
  if (!candidate.follow_ups.length) return candidate;
  const best = [...candidate.follow_ups].sort(compare)[0];
  return {
    ...best,
    cleared_lines: candidate.cleared_lines + best.cleared_lines,
    key_presses: candidate.key_presses + best.key_presses,
  };
}

/** One visible next piece, at most two placements, no hidden bag access.
 * These previews never select a target. The model chooses one landing. */
export function buildCandidates(game: Game): Candidate[] {
  if (game.status !== 'playing' || !game.active) return [];
  const root = { ...game, queue: game.queue.slice(0, 1) };
  const all = landings(root, true).map(
    ({ game: landed, action, outcome }): Candidate => {
      // Empty hold consumes the only visible next piece. Any later spawn made by
      // the engine is a simulation artifact and must not enter the observations.
      const next =
        outcome.uses_hold && game.hold === null ? null : game.queue[0];
      const blocked = next === null ? null : landed.status === 'over';
      const followUps: Landing[] = [];
      if (next !== null && !blocked) {
        // Future empty hold would read the hidden bag; only a known reserve is legal.
        const future = landings({ ...landed, queue: [] }, landed.hold !== null);
        for (const usesHold of [false, true]) {
          const best = future
            .filter((item) => item.outcome.uses_hold === usesHold)
            .sort((a, b) => compare(a.outcome, b.outcome))[0];
          if (best) followUps.push(best.outcome);
        }
      }
      return {
        ...outcome,
        action,
        next_piece: next,
        next_spawn_blocked: blocked,
        follow_ups: followUps,
      };
    },
  );
  // Do not discard a placement just because its immediate board looks worse:
  // it may prepare a clear for the next piece or preserve a useful reserve.
  const frontier = all.filter(
    (b) =>
      !all.some(
        (a) =>
          a !== b &&
          a.uses_hold === b.uses_hold &&
          a.hold_after === b.hold_after &&
          a.next_spawn_blocked === b.next_spawn_blocked &&
          noWorse(a, b) &&
          compare(a, b) < 0 &&
          b.follow_ups.every((bf) =>
            a.follow_ups.some(
              (af) => af.uses_hold === bf.uses_hold && noWorse(af, bf),
            ),
          ),
      ),
  );
  const safe = (a: Candidate, b: Candidate) =>
    Number(a.next_spawn_blocked === true) -
    Number(b.next_spawn_blocked === true);
  const byNow = [...frontier].sort((a, b) => safe(a, b) || compare(a, b));
  const byFuture = [...frontier].sort(
    (a, b) =>
      safe(a, b) || compare(futureValue(a), futureValue(b)) || compare(a, b),
  );
  // Alternate immediate and two-placement rankings, with and without hold, so
  // the bounded choice list retains both kinds of tradeoff for every model.
  const lists = [
    byFuture.filter((c) => !c.uses_hold),
    byFuture.filter((c) => c.uses_hold),
    byNow,
    byFuture,
  ];
  const chosen = new Set<Candidate>();
  for (let index = 0; index < frontier.length && chosen.size < 32; index++) {
    for (const list of lists) {
      if (list[index]) chosen.add(list[index]);
      if (chosen.size === 32) break;
    }
  }
  return [...chosen];
}
