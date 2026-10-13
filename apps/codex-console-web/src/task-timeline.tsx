import { WorkSummary } from './work-summary';
import { Button } from '@miy/ui';
import { useEffect, useState } from 'react';
import { api, locked, type Detail } from './api';
import type { components } from './api.generated';
import { errorCopy, type Copy, type Translate } from './i18n';
import { HistoryEntry } from './task-history';

type Page = components['schemas']['TimelinePage'];
type Segment = components['schemas']['MilestoneOut'];
const phases = [
  'start',
  'implementation',
  'validation',
  'integration',
  'finish',
] as const;
const phaseNames: Record<(typeof phases)[number], Copy> = {
  start: 'Work started',
  implementation: 'Implementation',
  validation: 'Validation',
  integration: 'Development integration',
  finish: 'Work finished',
};
const stateNames: Record<Segment['state'], Copy> = {
  in_progress: 'In progress',
  needs_attention: 'Needs attention',
  completed: 'Completed',
};
export function TaskTimeline({
  task,
  t,
  refreshToken = 0,
}: {
  task: Detail;
  t: Translate;
  refreshToken?: number;
}) {
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<Copy | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    void api<Page>(
      `/tasks/${task.id}/timeline`,
      undefined,
      'GET',
      controller.signal,
    )
      .then((next) => {
        if (!controller.signal.aborted)
          setPage((previous) => {
            if (!previous) return next;
            const merged = new Map(
              previous.items.map((item) => [item.id, item]),
            );
            next.items.forEach((item) => merged.set(item.id, item));
            return {
              items: [...merged.values()].sort(
                (a, b) =>
                  b.created_at.localeCompare(a.created_at) ||
                  b.id.localeCompare(a.id),
              ),
              next_before: previous.next_before,
            };
          });
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(errorCopy(e instanceof Error ? e.message : String(e)));
      });
    return () => controller.abort();
  }, [task.id, task.event_id, attempt, refreshToken]);
  return (
    <section className="task-timeline stack" aria-label={t('Work timeline')}>
      {page && (
        <WorkSummary
          task={task}
          segments={page.items}
          hasEarlier={!!page.next_before}
          t={t}
        />
      )}
      {error && (
        <p role="alert">
          {t(error)}{' '}
          <Button onClick={() => setAttempt(attempt + 1)}>{t('Retry')}</Button>
        </p>
      )}
      {!page && !error && <p role="status">{t('Loading…')}</p>}
      {!!page?.items.length && (
        <details className="work-summary-details">
          <summary>{t('Step details and evidence')}</summary>
          <div className="stack">
            <h3>{t('Work timeline')}</h3>
            {page?.items.map((segment) => (
              <article
                key={segment.id}
                className="timeline-segment"
                data-state={segment.state}
              >
                <div className="history-entry-heading">
                  <h3>{segment.title}</h3>
                  <span>{t(stateNames[segment.state])}</span>
                </div>
                <time dateTime={segment.updated_at}>
                  {new Date(segment.updated_at).toLocaleString(t.locale)}
                </time>
                {segment.merge && (
                  <div className="timeline-merge stack">
                    <code>
                      {segment.merge.source_branch ??
                        segment.merge.source_head.slice(0, 8)}{' '}
                      → {segment.merge.target_branch}
                    </code>
                    <small className="workspace-path">
                      {segment.merge.target_root}
                    </small>
                    {segment.merge.verified ? (
                      <p>
                        {t('Git integration verified')} ·{' '}
                        <code>
                          {segment.merge.source_commit?.slice(0, 8)} →{' '}
                          {segment.merge.integrated_head?.slice(0, 8)}
                        </code>
                      </p>
                    ) : (
                      <>
                        <p>
                          {t(
                            segment.merge.error_code
                              ? 'Git integration is not verified. Check conflicts, remaining changes or rewritten commits.'
                              : 'Merge requested. Completion will be checked against Git.',
                          )}
                        </p>
                        <Button
                          variant="secondary"
                          disabled={busy || locked(task)}
                          onClick={async () => {
                            setBusy(true);
                            setError(null);
                            try {
                              const result = await api<Segment>(
                                `/tasks/${task.id}/timeline/${segment.id}/verify`,
                                {},
                              );
                              setPage((old) =>
                                old
                                  ? {
                                      ...old,
                                      items: old.items.map((s) =>
                                        s.id === result.id ? result : s,
                                      ),
                                    }
                                  : old,
                              );
                            } catch (e) {
                              setError(
                                errorCopy(
                                  e instanceof Error ? e.message : String(e),
                                ),
                              );
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          {t('Check merge')}
                        </Button>
                      </>
                    )}
                  </div>
                )}
                {phases
                  .filter((key) => segment.phases[key])
                  .map((key) => {
                    const phase = segment.phases[key]!;
                    return (
                      <div className="timeline-phase" key={key}>
                        <strong>
                          {t(phaseNames[key])} · {t(stateNames[phase.state])}
                        </strong>
                        <p>{phase.summary}</p>
                      </div>
                    );
                  })}
                {segment.evidence.length > 0 && (
                  <details>
                    <summary>
                      {t('Execution evidence')} · {segment.evidence.length}
                    </summary>
                    <ol className="history-timeline">
                      {segment.evidence.map((entry) => (
                        <HistoryEntry
                          key={entry.id}
                          entry={entry}
                          task={task}
                          t={t}
                        />
                      ))}
                    </ol>
                  </details>
                )}
              </article>
            ))}
          </div>
        </details>
      )}
      {page?.next_before && (
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const older = await api<Page>(
                `/tasks/${task.id}/timeline?before=${page.next_before}`,
              );
              setPage((current) =>
                current
                  ? {
                      items: [
                        ...current.items,
                        ...older.items.filter(
                          (s) => !current.items.some((r) => r.id === s.id),
                        ),
                      ],
                      next_before: older.next_before,
                    }
                  : older,
              );
            } catch (e) {
              setError(errorCopy(e instanceof Error ? e.message : String(e)));
            } finally {
              setBusy(false);
            }
          }}
        >
          {t('Load earlier activity')}
        </Button>
      )}
    </section>
  );
}
