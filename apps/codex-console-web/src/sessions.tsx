import { Pin } from 'lucide-react';
import type { Task } from './api';
import { activityGroup, rowStatus } from './agent-state';
import type { Locale, Translate } from './i18n';

export function sortSessions(tasks: Task[]) {
  return [...tasks].sort(
    (a, b) =>
      Number(!!b.pinned) - Number(!!a.pinned) ||
      b.updated_at.localeCompare(a.updated_at) ||
      a.id.localeCompare(b.id),
  );
}

export function SessionList({
  tasks,
  selected,
  locale,
  t,
  openTask,
}: {
  tasks: Task[];
  selected: string | null;
  locale: Locale;
  t: Translate;
  openTask: (id: string) => void;
}) {
  return (
    <ul className="session-list" aria-label={t('Sessions')}>
      {tasks.map((task) => {
        const group = activityGroup(task);
        const status = t(group ? rowStatus(task, group) : 'Not started');
        return (
          <li key={task.id}>
            <button
              className="session-row"
              aria-current={task.id === selected ? 'true' : undefined}
              onClick={() => openTask(task.id)}
              title={task.title}
            >
              <span className="session-title">
                {task.pinned && (
                  <>
                    <Pin size={12} aria-hidden="true" />
                    <span className="sr-only">{t('Pinned')}</span>
                  </>
                )}
                <span>{task.title}</span>
              </span>
              <span className="session-meta">
                <span className="session-status" data-state={group ?? 'ready'}>
                  {status}
                </span>
                <time dateTime={task.updated_at}>
                  {new Date(task.updated_at).toLocaleDateString(locale, {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                  })}
                </time>
              </span>
              <span className="session-source">
                {t(
                  task.executor === 'templates'
                    ? 'Template run'
                    : 'Task workspace',
                )}{' '}
                · {task.root}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
