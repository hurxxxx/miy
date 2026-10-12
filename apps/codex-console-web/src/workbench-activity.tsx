import { Button, Input } from '@miy/ui';
import { ArrowRight, Clock3 } from 'lucide-react';
import { useState } from 'react';
import { record, type Task } from './api';
import {
  currentStep,
  executing,
  needsAttention,
  taskAction,
  taskStatus,
} from './agent-state';
import type { Translate } from './i18n';
import { useTaskSearch } from './task-search';

export function StatusPill({ task, t }: { task: Task; t: Translate }) {
  return (
    <span
      className="work-status"
      data-state={
        needsAttention(task)
          ? 'attention'
          : executing(task)
            ? 'running'
            : 'rest'
      }
    >
      {t(taskStatus(task))}
    </span>
  );
}

export function TaskPreview({
  task,
  t,
  openTask,
}: {
  task: Task;
  t: Translate;
  openTask: (id: string) => void;
}) {
  const context = record(task.context);
  return (
    <button className="work-preview" onClick={() => openTask(task.id)}>
      <div className="work-preview-heading">
        <strong>{task.title}</strong>
        <StatusPill task={task} t={t} />
      </div>
      <p>
        {task.pending_count
          ? t('Open this work to answer its pending requests.')
          : executing(task)
            ? currentStep(task, t)
            : task.summary?.latest_result?.excerpt ||
              t('No result recorded yet.')}
      </p>
      <div className="work-preview-footer">
        <span>
          {task.summary?.project_title
            ? task.summary.project_title
            : typeof context.app_id === 'string'
              ? context.app_id
              : t('General work')}{' '}
          · {new Date(task.updated_at).toLocaleString(t.locale)}
        </span>
        <span>
          {t(taskAction(task))} <ArrowRight size={14} aria-hidden="true" />
        </span>
      </div>
    </button>
  );
}

export function StudioActivity({
  tasks,
  t,
  openTask,
  failed = false,
}: {
  tasks: Task[];
  t: Translate;
  openTask: (id: string) => void;
  failed?: boolean;
}) {
  const sorted = [...tasks].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );
  const waiting = sorted.filter(needsAttention);
  const active = sorted.filter(
    (task) => executing(task) && !needsAttention(task),
  );
  return (
    <div className="studio-activity">
      {failed && (
        <p role="status" className="muted">
          {t('Live work could not be refreshed. Showing the last report.')}
        </p>
      )}
      {[
        { title: 'Your next decisions' as const, rows: waiting },
        { title: 'Work in progress' as const, rows: active },
      ].map(
        ({ title, rows }) =>
          rows.length > 0 && (
            <section key={title} aria-label={t(title)} className="work-section">
              <div className="work-section-heading">
                <h2>{t(title)}</h2>
                <span>{rows.length}</span>
              </div>
              <div className="work-queue">
                {rows.map((task) => (
                  <TaskPreview
                    key={task.id}
                    task={task}
                    t={t}
                    openTask={openTask}
                  />
                ))}
              </div>
            </section>
          ),
      )}
    </div>
  );
}

export function TaskHistory({
  tasks,
  projectId,
  appId,
  t,
  openTask,
}: {
  tasks: Task[];
  projectId?: string;
  appId?: string;
  t: Translate;
  openTask: (id: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState(false);
  const [retry, setRetry] = useState(0);
  const { search, key } = useTaskSearch(tasks, query, null, retry, true, {
    projectId,
    appId,
  });
  const rows =
    search.key === key
      ? [...search.rows].sort((a, b) =>
          b.updated_at.localeCompare(a.updated_at),
        )
      : [];
  const loading = search.key !== key || search.loading;
  return (
    <section className="task-history" aria-label={t('Work history')}>
      <div className="work-section-heading">
        <h3>
          <Clock3 size={17} aria-hidden="true" /> {t('Work history')}
        </h3>
        <label className="history-search">
          <span className="sr-only">{t('Search work history')}</span>
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('Search work history')}
          />
        </label>
      </div>
      {search.failed && (
        <div role="alert">
          <p>{t('Could not load work history.')}</p>
          <Button onClick={() => setRetry((n) => n + 1)}>{t('Retry')}</Button>
        </div>
      )}
      {loading && <p role="status">{t('Loading work history…')}</p>}
      {!loading && !search.failed && !rows.length && (
        <p className="empty-result">{t('No related work yet.')}</p>
      )}
      <div className="work-history-list">
        {rows.slice(0, expanded ? 200 : 5).map((task) => (
          <TaskPreview key={task.id} task={task} t={t} openTask={openTask} />
        ))}
      </div>
      {rows.length > 5 && (
        <Button variant="ghost" onClick={() => setExpanded((v) => !v)}>
          {t(expanded ? 'Show recent work' : 'Show more work')}
        </Button>
      )}
    </section>
  );
}
