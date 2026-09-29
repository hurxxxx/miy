import {
  addGarbage,
  emptyGame,
  startGame,
  step,
  WIDTH,
  type Action,
  type Game,
} from './engine';

export type Player = 0 | 1;
export interface Match {
  games: [Game, Game];
  duel: boolean;
  status: Game['status'];
  winner: Player | null;
  sent: [number, number];
}
export function emptyMatch(): Match {
  return {
    games: [emptyGame(), emptyGame()],
    duel: false,
    status: 'ready',
    winner: null,
    sent: [0, 0],
  };
}
export function startMatch(
  duel: boolean,
  random: () => number = Math.random,
): Match {
  return {
    ...emptyMatch(),
    duel,
    status: 'playing',
    games: [startGame(random), duel ? startGame(random) : emptyGame()],
  };
}
export function stepMatch(
  match: Match,
  player: Player,
  action: Action,
  random: () => number = Math.random,
): Match {
  if (match.status !== 'playing' || (player === 1 && !match.duel)) return match;
  const next = step(match.games[player], action, random);
  if (next === match.games[player]) return match;
  const games: [Game, Game] = [...match.games];
  const sent: [number, number] = [...match.sent];
  games[player] = next;
  const attack = Math.max(0, next.lines - match.games[player].lines - 1);
  const other = player === 0 ? 1 : 0;
  if (attack && match.duel) {
    games[other] = addGarbage(
      games[other],
      Array.from({ length: attack }, () => Math.floor(random() * WIDTH)),
    );
    sent[player] += attack;
  }
  const lost =
    games[0].status === 'over' || (match.duel && games[1].status === 'over');
  const winner =
    !lost || !match.duel || games.every((game) => game.status === 'over')
      ? null
      : games[0].status === 'over'
        ? 1
        : 0;
  return { ...match, games, sent, status: lost ? 'over' : 'playing', winner };
}
export function pauseMatch(match: Match): Match {
  if (!['playing', 'paused'].includes(match.status)) return match;
  const action = match.status === 'playing' ? 'pause' : 'resume';
  return {
    ...match,
    status: action === 'pause' ? 'paused' : 'playing',
    games: [step(match.games[0], action), step(match.games[1], action)],
  };
}
