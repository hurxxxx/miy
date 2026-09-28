import { Button, useFeedback } from '@open-work-hub/ui';
import { ChevronDown, Keyboard, RefreshCw, Swords } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '@/src/platform/auth/auth-provider';
import {
  listModels,
  requestDecision,
  type Decide,
  type ModelOption,
} from './ai-api';
import type { Player } from './match';
import { SHAPES, visibleBoard, type Cell, type Kind } from './engine';
import { useTetris } from './use-tetris';

const BLOCK_STYLES: Record<Exclude<Cell, null>, string> = {
  garbage: 'bg-app-ink-muted/30 border-app-ink-muted',
  I: 'bg-app-chart-7/25 border-app-chart-7',
  J: 'bg-app-chart-1/25 border-app-chart-1',
  L: 'bg-app-chart-4/25 border-app-chart-4',
  O: 'bg-app-chart-6/25 border-app-chart-6',
  S: 'bg-app-chart-2/25 border-app-chart-2',
  T: 'bg-app-chart-3/25 border-app-chart-3',
  Z: 'bg-app-chart-5/25 border-app-chart-5',
};

function Block({ cell }: { cell: Cell }) {
  return (
    <span
      data-cell={cell ?? ''}
      className={`flex aspect-square min-h-0 min-w-0 items-center justify-center overflow-hidden border text-[10px] font-semibold leading-none text-app-ink ${cell ? BLOCK_STYLES[cell] : 'border-app-border/50 bg-app-surface'}`}
    >
      {cell === 'garbage' ? '·' : cell}
    </span>
  );
}
function Preview({
  kind,
  label,
  empty,
}: {
  kind: Kind | undefined | null;
  label: string;
  empty: string;
}) {
  return (
    <div>
      <h3 className="app-text-body mb-2 font-medium">{label}</h3>
      <div
        role="img"
        aria-label={kind ? `${label}: ${kind}` : `${label}: ${empty}`}
        className="h-16 w-16"
      >
        {kind ? (
          <div
            aria-hidden="true"
            className="grid"
            style={{
              gridTemplateColumns: `repeat(${SHAPES[kind].length}, 1fr)`,
            }}
          >
            {SHAPES[kind].flat().map((cell, index) => (
              <Block key={index} cell={cell ? kind : null} />
            ))}
          </div>
        ) : (
          <span className="app-text-body text-app-ink-muted">{empty}</span>
        )}
      </div>
    </div>
  );
}
export function TetrisView() {
  const { t } = useTranslation('apps');
  const { token } = useAuth();
  const feedback = useFeedback();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [showControls, setShowControls] = useState(false);
  const catalogRequest = useRef<AbortController | null>(null);
  const reloadModels = useCallback(async () => {
    catalogRequest.current?.abort();
    const controller = new AbortController();
    catalogRequest.current = controller;
    setLoading(true);
    try {
      const result = await listModels(token, controller.signal);
      if (!controller.signal.aborted) setModels(result.models);
    } catch {
      if (!controller.signal.aborted)
        feedback.error(t('tetris.Could not load AI models.'));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [token, feedback, t]);
  useEffect(() => {
    void reloadModels();
    return () => catalogRequest.current?.abort();
  }, [reloadModels]);
  const decide = useCallback<Decide>(
    (game, signal, model, opponent) =>
      requestDecision(token, game, signal, model, opponent),
    [token],
  );
  const game = useTetris(decide, models);
  const { match, players } = game;
  const running = match.status === 'playing' || match.status === 'paused';
  const controls = [
    {
      action: 'counterclockwise',
      label: t('tetris.Rotate left'),
      caption: t('tetris.Rotate'),
      symbol: '↶',
    },
    {
      action: 'hold',
      label: t('tetris.Hold block'),
      caption: t('tetris.Hold'),
      symbol: 'C',
    },
    {
      action: 'clockwise',
      label: t('tetris.Rotate right'),
      caption: t('tetris.Rotate'),
      symbol: '↷',
    },
    {
      action: 'left',
      label: t('tetris.Move left'),
      caption: t('tetris.Left'),
      symbol: '←',
    },
    {
      action: 'down',
      label: t('tetris.Soft drop'),
      caption: t('tetris.Down'),
      symbol: '↓',
    },
    {
      action: 'right',
      label: t('tetris.Move right'),
      caption: t('tetris.Right'),
      symbol: '→',
    },
    {
      action: 'drop',
      label: t('tetris.Drop instantly'),
      caption: t('tetris.Drop'),
      symbol: '⇓',
    },
  ] as const;
  const status = {
    ready: t('tetris.Ready to play'),
    playing: t('tetris.Playing'),
    paused: t('tetris.Paused'),
    over:
      match.winner === null
        ? t('tetris.Game over')
        : t('tetris.Player {{player}} wins!', { player: match.winner + 1 }),
  }[match.status];
  const choiceKey = (model: { kind: string; model_id: string } | null) =>
    model ? `${model.kind}:${model.model_id}` : '';
  const missingModel = players.some(
    (player) =>
      player.mode === 'ai' &&
      !models.some((model) => choiceKey(model) === choiceKey(player.model)),
  );
  const duel = players[1].mode !== 'none';
  const modePicker = (id: Player) => {
    const player = players[id];
    const other = players[id === 0 ? 1 : 0];
    return (
      <select
        aria-label={t('tetris.Player {{player}}', { player: id + 1 })}
        className="h-9 min-w-20 rounded-md border border-app-border bg-app-surface px-2 app-text-body text-app-ink"
        value={player.mode}
        onChange={(event) =>
          game.configure(id, {
            mode: event.target.value as typeof player.mode,
            model: player.model,
          })
        }
      >
        {id === 1 && (
          <option value="none" disabled={running && player.mode !== 'none'}>
            {t('tetris.No player')}
          </option>
        )}
        <option
          value="human"
          disabled={
            other.mode === 'human' || (running && player.mode === 'none')
          }
        >
          {t('tetris.Human')}
        </option>
        <option
          value="ai"
          disabled={
            (!models.length && player.mode !== 'ai') ||
            (running && player.mode === 'none')
          }
        >
          {t('tetris.AI')}
        </option>
      </select>
    );
  };
  const refreshModels = (
    <Button
      variant="ghost"
      className="h-10 w-10 shrink-0 p-0"
      onClick={() => void reloadModels()}
      disabled={loading}
      aria-label={t('tetris.Refresh models')}
      title={t('tetris.Refresh models')}
    >
      <RefreshCw
        className={`h-4 w-4 ${loading ? 'animate-spin motion-reduce:animate-none' : ''}`}
        aria-hidden="true"
      />
    </Button>
  );
  return (
    <section
      className="h-full overflow-auto bg-app-bg p-3 text-app-ink sm:p-5 [--tetris-board-width:clamp(140px,calc((100dvh-450px)/2),460px)] lg:[--tetris-board-width:clamp(200px,calc((100dvh-400px)/2),460px)]"
      aria-labelledby="tetris-title"
    >
      <div className="mx-auto w-full max-w-[1440px]">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-app-border pb-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 id="tetris-title" className="app-text-title-lg">
                {t('tetris.Tetris')}
              </h1>
              <span className="hidden rounded bg-app-surface px-2 py-0.5 app-text-caption text-app-ink-muted sm:inline">
                {duel ? t('tetris.Duel') : t('tetris.Solo play')}
              </span>
            </div>
            <p
              role="status"
              className={`app-text-caption ${match.winner !== null ? 'font-semibold text-app-accent' : 'text-app-ink-muted'}`}
            >
              {status}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {running && (
              <Button variant="secondary" onClick={game.togglePause}>
                {match.status === 'paused'
                  ? t('tetris.Resume game')
                  : t('tetris.Pause game')}
              </Button>
            )}
            <Button
              variant="primary"
              disabled={missingModel}
              onClick={game.start}
            >
              {match.status === 'ready'
                ? t('tetris.Start game')
                : t('tetris.Restart game')}
            </Button>
          </div>
        </header>
        {!models.length && (
          <div className="mb-3 flex items-center justify-center gap-2 app-text-caption text-app-ink-muted">
            <span>
              {loading
                ? t('tetris.Loading AI models…')
                : t('tetris.No compatible AI models are enabled.')}
            </span>
            {refreshModels}
          </div>
        )}
        <div className="mx-auto grid w-full max-w-[calc(2*var(--tetris-board-width)+320px)] items-start gap-4 lg:grid-cols-[minmax(0,1fr)_40px_minmax(0,1fr)]">
          {players.map((player, index) => {
            const id = index as Player;
            const board = match.games[id];
            const stats = game.ai[id];
            const selected = models.find(
              (model) => choiceKey(model) === choiceKey(player.model),
            );
            const last = stats.samples.at(-1);
            const average = stats.samples.length
              ? Math.round(
                  stats.samples.reduce((a, b) => a + b, 0) /
                    stats.samples.length,
                )
              : null;
            const playerStatus =
              player.mode === 'none'
                ? t('tetris.No player')
                : match.status === 'ready'
                  ? t('tetris.Waiting to start')
                  : match.status === 'paused'
                    ? t('tetris.Paused')
                    : match.status === 'over'
                      ? match.winner === id
                        ? t('tetris.Winner')
                        : t('tetris.Game over')
                      : stats.retry
                        ? t('tetris.AI retrying (attempt {{attempt}})', {
                            attempt: stats.retry,
                          })
                        : stats.busy
                          ? t('tetris.AI is deciding')
                          : t('tetris.Playing');
            return (
              <section
                key={id}
                aria-label={t('tetris.Player {{player}}', { player: id + 1 })}
                className={`mx-auto w-full min-w-0 max-w-[calc(var(--tetris-board-width)+100px)] lg:max-w-[calc(var(--tetris-board-width)+124px)] ${id === 1 ? 'lg:col-start-3 lg:row-start-1' : ''}`}
              >
                <header
                  className={`border-t-2 pt-2 ${id === 0 ? 'border-app-chart-1' : 'border-app-chart-3'}`}
                >
                  <div className="flex h-9 items-center justify-between gap-2">
                    <h2 className="flex items-center gap-2 app-text-body font-semibold">
                      <span
                        aria-hidden="true"
                        className={`flex h-7 w-7 items-center justify-center rounded-md ${id === 0 ? 'bg-app-chart-1/15 text-app-chart-1' : 'bg-app-chart-3/15 text-app-chart-3'}`}
                      >
                        {id + 1}
                      </span>
                      {t('tetris.Player {{player}}', { player: id + 1 })}
                    </h2>
                    {modePicker(id)}
                  </div>
                  <div
                    className={`mt-2 h-10 min-w-0 items-center gap-1 ${player.mode === 'ai' ? 'flex' : 'hidden lg:flex'}`}
                  >
                    {player.mode === 'ai' ? (
                      <>
                        <select
                          aria-label={t(
                            'tetris.AI model for player {{player}}',
                            { player: id + 1 },
                          )}
                          className="h-10 min-w-0 flex-1 rounded-md border border-app-border bg-app-surface px-2 app-text-body"
                          value={choiceKey(player.model)}
                          onFocus={() => void reloadModels()}
                          onChange={(event) => {
                            const model = models.find(
                              (item) => choiceKey(item) === event.target.value,
                            );
                            if (model)
                              game.configure(id, {
                                mode: 'ai',
                                model: {
                                  kind: model.kind,
                                  model_id: model.model_id,
                                },
                              });
                          }}
                        >
                          {!selected && (
                            <option value={choiceKey(player.model)}>
                              {t('tetris.Model unavailable')}
                            </option>
                          )}
                          {models.map((model) => (
                            <option
                              key={choiceKey(model)}
                              value={choiceKey(model)}
                            >
                              {model.name}
                              {model.is_default
                                ? ` · ${t('tetris.Default model')}`
                                : ''}
                            </option>
                          ))}
                        </select>
                        {refreshModels}
                      </>
                    ) : player.mode === 'human' ? (
                      <div className="flex items-center gap-2 app-text-body text-app-ink-muted">
                        <Keyboard
                          className="h-4 w-4 shrink-0"
                          aria-hidden="true"
                        />
                        {t('tetris.Arrows move; Space drops; C holds')}
                      </div>
                    ) : null}
                  </div>
                </header>
                <dl className="my-2 grid grid-cols-3 gap-3 border-b border-app-border pb-2 app-text-caption text-app-ink-muted lg:my-3">
                  <div>
                    <dt>{t('tetris.Score')}</dt>
                    <dd
                      data-testid={id === 0 ? 'tetris-score' : 'tetris-score-2'}
                      className="text-lg font-semibold tabular-nums text-app-ink lg:text-xl"
                    >
                      {board.score.toLocaleString()}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('tetris.Lines')}</dt>
                    <dd className="text-lg font-semibold tabular-nums text-app-ink lg:text-xl">
                      {board.lines}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('tetris.Attack lines sent')}</dt>
                    <dd className="text-lg font-semibold tabular-nums text-app-accent lg:text-xl">
                      {match.sent[id]}
                    </dd>
                  </div>
                </dl>
                <div className="grid grid-cols-[minmax(0,1fr)_88px] items-start gap-3 lg:grid-cols-[minmax(0,1fr)_108px] lg:grid-rows-[min-content_1fr] lg:gap-4">
                  <div
                    ref={game.boardRefs[id]}
                    role="region"
                    aria-label={t('tetris.Game board')}
                    aria-describedby={
                      player.mode === 'none' ? undefined : 'tetris-controls'
                    }
                    aria-disabled={player.mode === 'none' || undefined}
                    tabIndex={player.mode === 'none' ? -1 : 0}
                    onKeyDown={
                      player.mode === 'none' ? undefined : game.onKeyDown
                    }
                    className={`overflow-hidden rounded border bg-app-surface outline-none focus-visible:ring-2 focus-visible:ring-app-accent lg:row-span-2 ${match.winner === id ? 'border-app-accent ring-2 ring-app-accent/30' : 'border-app-border'}`}
                  >
                    <div aria-hidden="true" className="grid grid-cols-10">
                      {visibleBoard(board)
                        .flat()
                        .map((cell, cellIndex) => (
                          <Block key={cellIndex} cell={cell} />
                        ))}
                    </div>
                  </div>
                  <aside className="min-w-0 space-y-4">
                    <Preview
                      kind={board.queue[0]}
                      label={t('tetris.Next block')}
                      empty={t('tetris.Empty')}
                    />
                    <Preview
                      kind={board.hold}
                      label={t('tetris.Hold')}
                      empty={t('tetris.Empty')}
                    />
                    <p className="app-text-caption text-app-ink-muted">
                      {t('tetris.Level')}{' '}
                      <span className="font-semibold tabular-nums text-app-ink">
                        {board.level}
                      </span>
                    </p>
                  </aside>
                  <div
                    className="col-span-2 min-w-0 space-y-2 border-t border-app-border pt-3 app-text-caption text-app-ink-muted lg:col-span-1 lg:col-start-2"
                    data-testid={
                      player.mode === 'ai' ? `tetris-ai-${id + 1}` : undefined
                    }
                  >
                    <p
                      className="h-5 truncate font-medium text-app-ink lg:h-10 lg:whitespace-normal lg:line-clamp-2"
                      title={playerStatus}
                    >
                      {playerStatus}
                    </p>
                    {player.mode === 'ai' && (
                      <>
                        <div className="h-10 lg:h-20">
                          {last === undefined && (
                            <p>
                              {stats.retry
                                ? t('tetris.No successful responses yet')
                                : t('tetris.No responses yet')}
                            </p>
                          )}
                          {stats.error && (
                            <p>
                              {
                                {
                                  rate_limited: t(
                                    'tetris.Model request limit reached',
                                  ),
                                  output_limit: t(
                                    'tetris.Model output limit reached',
                                  ),
                                  timeout: t('tetris.Model response timed out'),
                                  failed: t('tetris.AI decision failed.'),
                                }[stats.error]
                              }
                            </p>
                          )}
                        </div>
                        <dl className="grid grid-cols-2 gap-2 lg:grid-cols-1">
                          {(
                            [
                              [t('tetris.Latest response'), last],
                              [t('tetris.Average (last 20)'), average],
                            ] as const
                          ).map(([label, time]) => (
                            <div key={label} className="min-w-0">
                              <dt
                                className="h-5 truncate lg:h-10 lg:whitespace-normal lg:line-clamp-2"
                                title={label}
                              >
                                {label}
                              </dt>
                              <dd className="whitespace-nowrap font-medium tabular-nums text-app-ink">
                                {time == null
                                  ? '—'
                                  : t('tetris.{{time}} ms', { time })}
                              </dd>
                            </div>
                          ))}
                        </dl>
                        {selected && (
                          <p
                            className="h-5 truncate lg:h-10 lg:whitespace-normal lg:line-clamp-2 lg:break-all"
                            title={`${selected.kind === 'decision' ? t('tetris.Decision model') : t('tetris.LLM')} · ${selected.provider}`}
                          >
                            {selected.kind === 'decision'
                              ? t('tetris.Decision model')
                              : t('tetris.LLM')}{' '}
                            · {selected.provider}
                          </p>
                        )}
                        {(stats.last || selected) && (
                          <p
                            className="h-5 truncate lg:h-10 lg:whitespace-normal lg:line-clamp-2 lg:break-all"
                            title={stats.last?.model ?? selected?.model_key}
                          >
                            {stats.last?.model ?? selected?.model_key}
                          </p>
                        )}
                      </>
                    )}
                  </div>
                </div>
                {player.mode === 'human' && (
                  <div className="mt-2">
                    <Button
                      variant="ghost"
                      className="mb-1 hidden w-full justify-between lg:flex"
                      aria-expanded={showControls}
                      aria-controls={`tetris-screen-controls-${id}`}
                      onClick={() => setShowControls((value) => !value)}
                    >
                      {t('tetris.Screen controls')}
                      <ChevronDown
                        aria-hidden="true"
                        className={`h-4 w-4 ${showControls ? 'rotate-180' : ''}`}
                      />
                    </Button>
                    <div
                      id={`tetris-screen-controls-${id}`}
                      role="group"
                      aria-label={t('tetris.Screen controls')}
                      className={`grid grid-cols-4 gap-1.5 ${showControls ? '' : 'lg:hidden'}`}
                    >
                      {controls.map(({ action, label, caption, symbol }) => (
                        <Button
                          key={action}
                          variant="secondary"
                          className={`min-h-11 min-w-0 flex-col gap-0 px-0.5 touch-manipulation select-none ${action === 'drop' ? 'col-start-4 row-start-1 row-span-2' : ''}`}
                          disabled={
                            match.status !== 'playing' ||
                            (action === 'hold' && !board.canHold)
                          }
                          onClick={() => game.play(id, action)}
                          aria-label={label}
                          title={label}
                        >
                          <span aria-hidden="true" className="text-base">
                            {symbol}
                          </span>
                          <span className="text-xs leading-tight">
                            {caption}
                          </span>
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            );
          })}
          <div
            className="hidden self-center text-center text-app-ink-muted lg:col-start-2 lg:row-start-1 lg:block"
            aria-hidden="true"
          >
            <Swords className="mx-auto mb-2 h-5 w-5" />
            <span className="app-text-caption font-semibold">
              {t('tetris.VS')}
            </span>
          </div>
        </div>
        <details className="mx-auto mt-4 max-w-3xl border-t border-app-border pt-3 app-text-caption text-app-ink-muted">
          <summary className="cursor-pointer text-center font-medium text-app-ink">
            {t('tetris.Controls and rules')}
          </summary>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <h2 className="font-medium text-app-ink">
                {t('tetris.Keyboard controls')}
              </h2>
              <p>{t('tetris.Arrows move; down drops faster')}</p>
              <p>
                {t(
                  'tetris.Up or X rotates clockwise; Z rotates counterclockwise',
                )}
              </p>
              <p>{t('tetris.Space drops instantly; C holds a block')}</p>
              <p>{t('tetris.P or Esc pauses or resumes')}</p>
            </div>
            <div className="space-y-1">
              <p>
                {t(
                  'tetris.Clear 2 / 3 / 4 lines to send 1 / 2 / 3 garbage lines immediately.',
                )}
              </p>
              <p>
                {t(
                  'tetris.Set player 2 to no player for solo play. Only one human can play.',
                )}
              </p>
              <p>{t('tetris.Play continues when focus leaves the game')}</p>
              <p>
                {t('tetris.Progress is not saved when you leave or reload')}
              </p>
            </div>
          </div>
        </details>
        <p id="tetris-controls" className="sr-only">
          {t('tetris.Arrows move; down drops faster')}{' '}
          {t('tetris.Up or X rotates clockwise; Z rotates counterclockwise')}{' '}
          {t('tetris.Space drops instantly; C holds a block')}{' '}
          {t('tetris.P or Esc pauses or resumes')}
        </p>
      </div>
    </section>
  );
}
