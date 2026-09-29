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

type Well = ApiSchema<'TetrisWell'>;
type Landing = ApiSchema<'TetrisLanding'> & { wells: Well[] };
type Candidate = Landing &
  Omit<ApiSchema<'TetrisCandidate'>, keyof Landing | 'follow_ups'> & {
    follow_ups: Landing[];
  };
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
  const wells: Well[] = [];
  for (let column = 0; column < WIDTH; column++) {
    const depth =
      Math.min(heights[column - 1] ?? HEIGHT, heights[column + 1] ?? HEIGHT) -
      heights[column];
    if (depth <= 0) continue;
    // Only the shaft above the column's highest cell is open from the top.
    // Covered gaps must never be presented as accessible attack setups.
    const floor = HEIGHT - heights[column];
    let readyRows = 0;
    let filledCells = 0;
    for (let y = Math.max(0, floor - 4); y < floor; y++) {
      const filled = board[y].filter(
        (cell, x) => x !== column && cell !== null,
      ).length;
      filledCells += filled;
      if (filled === WIDTH - 1) readyRows++;
    }
    wells.push({
      column,
      depth,
      ready_rows: readyRows,
      filled_cells: filledCells,
    });
  }
  return {
    holes,
    max_height: Math.max(...heights),
    aggregate_height: heights.reduce((sum, height) => sum + height, 0),
    bumpiness: heights
      .slice(1)
      .reduce((sum, height, x) => sum + Math.abs(height - heights[x]), 0),
    wells,
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
    a.cleared_lines >= b.cleared_lines &&
    COSTS.every((key) => a[key] <= b[key]) &&
    // Similar surface costs do not make different attack shafts interchangeable.
    b.wells.every((bw) =>
      a.wells.some(
        (aw) =>
          aw.column === bw.column &&
          Math.min(aw.depth, 4) >= Math.min(bw.depth, 4) &&
          aw.ready_rows >= bw.ready_rows &&
          aw.filled_cells >= bw.filled_cells,
      ),
    )
  );
}

function wellValue(landing: Landing): number {
  // Completed rows, then filled cells in the four-row target area. Depth alone
  // earns no reward: a tall thin tower is not better than filling out the stack.
  return Math.max(
    0,
    ...landing.wells.map(
      (well) => well.ready_rows * (4 * (WIDTH - 1) + 1) + well.filled_cells,
    ),
  );
}

function compareAttack(a: Landing, b: Landing): number {
  return (
    a.holes - b.holes ||
    Math.max(0, b.cleared_lines - 1) - Math.max(0, a.cleared_lines - 1) ||
    wellValue(b) - wellValue(a) ||
    compare(a, b)
  );
}

function attackFuture(candidate: Candidate) {
  const end = [...candidate.follow_ups].sort(compareAttack)[0] ?? candidate;
  return {
    end,
    attack:
      Math.max(0, candidate.cleared_lines - 1) +
      (end === candidate ? 0 : Math.max(0, end.cleared_lines - 1)),
  };
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
          const alternatives = future
            .filter((item) => item.outcome.uses_hold === usesHold)
            .map((item) => item.outcome);
          const safe = [...alternatives].sort(compare)[0];
          const attack = [...alternatives].sort(compareAttack)[0];
          if (safe) followUps.push(safe);
          if (attack && attack !== safe) followUps.push(attack);
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
  const byAttack = [...frontier].sort(
    (a, b) => safe(a, b) || compareAttack(a, b),
  );
  const byAttackFuture = [...frontier].sort((a, b) => {
    const af = attackFuture(a);
    const bf = attackFuture(b);
    return (
      safe(a, b) ||
      af.end.holes - bf.end.holes ||
      bf.attack - af.attack ||
      wellValue(bf.end) - wellValue(af.end) ||
      compare(af.end, bf.end) ||
      compare(a, b)
    );
  });
  // Interleave survival and attack (now/next, with/without hold) before the
  // server's shared 26-choice limit. These are options, never an engine policy.
  const lists = [
    byNow,
    byAttackFuture.filter((c) => !c.uses_hold),
    byAttackFuture.filter((c) => c.uses_hold),
    byAttack,
    byFuture.filter((c) => !c.uses_hold),
    byFuture.filter((c) => c.uses_hold),
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
