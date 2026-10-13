import { Check, Circle, Clock3, AlertCircle } from 'lucide-react';
import { record, string, type Detail } from './api';
import type { components } from './api.generated';
import type { Copy, Translate } from './i18n';

type Segment = components['schemas']['MilestoneOut'];
type Phase = components['schemas']['PhaseOut'];
type State = Segment['state'] | 'pending';
type Summary = {
  id: string;
  title: string;
  description: string;
  state: State;
  time?: string;
};
const states: Record<State, Copy> = {
  in_progress: 'In progress',
  completed: 'Completed',
  needs_attention: 'Needs attention',
  pending: 'Planned work',
};
const icons = {
  in_progress: Clock3,
  completed: Check,
  needs_attention: AlertCircle,
  pending: Circle,
};
const shortLine = (value: string, length = 180) => {
  const text = value.replace(/\s+/g, ' ').trim();
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
};
function latestPhase(segment: Segment): Phase | undefined {
  // A blocked phase remains relevant even when another phase reports success later.
  const all = Object.values(segment.phases)
    .filter((phase): phase is Phase => !!phase)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return (
    (segment.state === 'needs_attention'
      ? all.find((p) => p.state === 'needs_attention')
      : undefined) ?? all[0]
  );
}
function summarize(segment: Segment, t: Translate): Summary {
  const phase = latestPhase(segment);
  const mergeDescription = segment.merge?.verified
    ? 'The requested changes are included in development.'
    : segment.state === 'needs_attention'
      ? 'The development merge still needs checking.'
      : 'The changes have been requested for development integration.';
  return {
    id: segment.id,
    title: shortLine(
      phase?.headline ||
        (segment.merge ? t('Apply the changes to development') : segment.title),
      80,
    ),
    description: shortLine(
      phase?.one_line ||
        (segment.merge
          ? t(mergeDescription)
          : phase?.summary || t('Waiting for the next progress update.')),
    ),
    state: segment.state,
    time: segment.updated_at,
  };
}
function reportedPlan(task: Detail): Summary[] {
  const steps = task.progress?.steps;
  if (!Array.isArray(steps)) return [];
  return steps.slice(0, 100).flatMap((value, index) => {
    const step = record(value);
    const title = string(step.step).trim();
    if (
      !title ||
      !['pending', 'inProgress', 'completed'].includes(string(step.status))
    )
      return [];
    return [
      {
        id: `plan-${index}`,
        title: shortLine(title, 160),
        description: '',
        state:
          step.status === 'completed'
            ? 'completed'
            : step.status === 'inProgress'
              ? 'in_progress'
              : 'pending',
      },
    ];
  });
}

export function WorkSummary({
  task,
  segments,
  hasEarlier,
  t,
}: {
  task: Detail;
  segments: Segment[];
  hasEarlier: boolean;
  t: Translate;
}) {
  const fallback = segments.length === 0;
  const items = fallback
    ? reportedPlan(task)
    : segments.map((segment) => summarize(segment, t));
  const current =
    items.find((item) => item.state === 'needs_attention') ??
    items.find((item) => item.state === 'in_progress');
  const finished = items.filter((item) => item.state === 'completed').length;
  // Milestones describe the last report. An idle/interrupted conversation must not
  // imply an agent is still executing that report.
  const live = ['starting', 'running'].includes(task.status);
  const focusLabel: Copy =
    current?.state === 'needs_attention'
      ? 'Work needing attention'
      : live && current
        ? 'Work in progress now'
        : 'Latest work update';
  return (
    <section className="work-summary" aria-label={t('Work at a glance')}>
      <header className="work-summary-heading">
        <h2>{t('Work at a glance')}</h2>
        {items.length > 0 && (
          <span className="work-summary-count">
            {t('Completed')} {finished} · {t('Shown work')} {items.length}
          </span>
        )}
      </header>
      <p className="muted">
        {t('See what changed and what is happening, one work item at a time.')}
      </p>
      {fallback && items.length > 0 && (
        <p className="work-summary-source">
          {t(
            'Showing the last reported plan until work summaries are available.',
          )}
        </p>
      )}
      {current && (
        <div className="work-summary-focus" data-state={current.state}>
          <span>{t(focusLabel)}</span>
          <strong>{current.title}</strong>
          {current.description && <p>{current.description}</p>}
        </div>
      )}
      {items.length === 0 ? (
        <p className="context-note">
          {t('The work flow will appear here when progress is reported.')}
        </p>
      ) : (
        <ol className="work-summary-list">
          {items.map((item) => {
            const Icon = icons[item.state];
            return (
              <li key={item.id} data-state={item.state}>
                <span className="work-summary-dot">
                  <Icon size={14} aria-hidden="true" />
                </span>
                <article>
                  <div className="work-summary-item-heading">
                    <h3>{item.title}</h3>
                    <span className="work-summary-state">
                      {t(
                        item.state === 'in_progress' && !live
                          ? 'Last reported in progress'
                          : states[item.state],
                      )}
                    </span>
                  </div>
                  {item.description && <p>{item.description}</p>}
                  {item.time && (
                    <time dateTime={item.time}>
                      {new Date(item.time).toLocaleString(t.locale, {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </time>
                  )}
                </article>
              </li>
            );
          })}
        </ol>
      )}
      {hasEarlier && (
        <small className="muted">
          {t('Recent work is shown first. Load earlier work below.')}
        </small>
      )}
    </section>
  );
}
